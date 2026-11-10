import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.models.challenge import ChallengeCreate
from app.services.challenge_service import calculate_challenge_status, sync_challenge_status

client = TestClient(app)

MOCK_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "paypal_user_id": "PP-USER-1",
    "display_name": "Alice Tester",
    "paypal_email": "alice@example.com",
}


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[current_user] = lambda: MOCK_USER
    yield
    app.dependency_overrides.clear()


def test_calculate_challenge_status_all_stages():
    now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
    join_dl = now + timedelta(days=1)
    proof_dl = now + timedelta(days=2)
    voting_dl = now + timedelta(days=3)

    challenge = {
        "status": "open",
        "join_deadline": join_dl.isoformat(),
        "proof_deadline": proof_dl.isoformat(),
        "voting_deadline": voting_dl.isoformat(),
    }

    # 1. Before join_deadline -> open
    t_open = now
    assert calculate_challenge_status(challenge, now=t_open) == "open"

    # 2. After join_deadline, before proof_deadline -> active
    t_active = join_dl + timedelta(hours=1)
    assert calculate_challenge_status(challenge, now=t_active) == "active"

    # 3. After proof_deadline, before voting_deadline -> voting
    t_voting = proof_dl + timedelta(hours=1)
    assert calculate_challenge_status(challenge, now=t_voting) == "voting"

    # 4. After voting_deadline -> closed
    t_closed = voting_dl + timedelta(hours=1)
    assert calculate_challenge_status(challenge, now=t_closed) == "closed"


def test_calculate_challenge_status_terminal_states_preserved():
    now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
    past_dl = (now - timedelta(days=10)).isoformat()

    for terminal in ("settling", "settled", "cancelled"):
        challenge = {
            "status": terminal,
            "join_deadline": past_dl,
            "proof_deadline": past_dl,
            "voting_deadline": past_dl,
        }
        # Even though all deadlines are long past, terminal state must not change
        assert calculate_challenge_status(challenge, now=now) == terminal


def test_challenge_create_model_voting_deadline_validation():
    now = datetime.now(timezone.utc)
    join_dl = now + timedelta(days=1)
    proof_dl = now + timedelta(days=2)

    # Valid: voting_deadline omitted -> defaults to proof_dl + 1 day
    c1 = ChallengeCreate(
        title="Valid Challenge",
        criteria="Complete 10 pullups",
        entry_fee_pln=Decimal("20.00"),
        join_deadline=join_dl,
        proof_deadline=proof_dl,
    )
    assert c1.voting_deadline is not None
    assert c1.voting_deadline > c1.proof_deadline

    # Valid: explicit voting_deadline later than proof_dl
    voting_dl = proof_dl + timedelta(days=2)
    c2 = ChallengeCreate(
        title="Valid Challenge",
        criteria="Complete 10 pullups",
        entry_fee_pln=Decimal("20.00"),
        join_deadline=join_dl,
        proof_deadline=proof_dl,
        voting_deadline=voting_dl,
    )
    assert c2.voting_deadline == voting_dl

    # Invalid: voting_deadline <= proof_deadline
    with pytest.raises(ValidationError) as exc:
        ChallengeCreate(
            title="Invalid Challenge",
            criteria="Complete 10 pullups",
            entry_fee_pln=Decimal("20.00"),
            join_deadline=join_dl,
            proof_deadline=proof_dl,
            voting_deadline=proof_dl - timedelta(hours=1),
        )
    assert "voting_deadline must be later than proof_deadline" in str(exc.value)


def test_pay_blocked_when_challenge_not_open():
    challenge_id = uuid.uuid4()
    mock_challenge_active = {
        "id": challenge_id,
        "status": "active",  # Join deadline passed!
        "join_deadline": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        "proof_deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        "voting_deadline": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
        "participants": [],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_active):
        resp = client.post(f"/challenges/{challenge_id}/pay")
        assert resp.status_code == 400
        assert "Joining this challenge is closed" in resp.json()["detail"]


def test_upload_evidence_blocked_when_proof_deadline_passed():
    challenge_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    mock_challenge_voting = {
        "id": challenge_id,
        "status": "voting",  # Proof deadline passed!
        "join_deadline": (now - timedelta(days=2)).isoformat(),
        "proof_deadline": (now - timedelta(hours=1)).isoformat(),
        "voting_deadline": (now + timedelta(days=1)).isoformat(),
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "paid": True,
                "outcome": "pending",
            }
        ],
    }

    import io
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="red")
    img.save(buf, format="JPEG")
    fake_photo = buf.getvalue()

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_voting), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]):
        resp = client.post(
            f"/challenges/{challenge_id}/evidence",
            files={"photo": ("proof.jpg", fake_photo, "image/jpeg")},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}?proof_error=closed"


def test_vote_blocked_when_voting_deadline_passed():
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    other_user = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    from app.services.evidence import cast_vote

    mock_supabase = MagicMock()
    # Evidence exists
    mock_supabase.table().select().eq().execute.return_value.data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": other_user,
        "status": "needs_vote",
    }]

    # Challenges table returns closed challenge
    chal_mock = MagicMock()
    chal_mock.data = [{
        "id": challenge_id,
        "status": "closed",
        "voting_deadline": (now - timedelta(hours=1)).isoformat(),
    }]

    def table_router(name):
        tbl = MagicMock()
        if name == "challenges":
            tbl.select().eq().execute.return_value = chal_mock
        elif name == "evidence":
            tbl.select().eq().execute.return_value.data = [{
                "id": evidence_id,
                "challenge_id": challenge_id,
                "user_id": other_user,
                "status": "needs_vote",
            }]
        elif name == "participants":
            tbl.select().eq().eq().execute.return_value.data = [{"user_id": MOCK_USER["id"], "paid": True}]
        return tbl

    mock_supabase.table.side_effect = table_router

    with patch("app.services.evidence.supabase", mock_supabase):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert exc.value.status_code == 400
        assert "Voting is closed" in exc.value.detail


def test_ui_elements_visibility_across_statuses():
    challenge_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. Open challenge: unpaid user sees Join & pay
    c_open = {
        "id": challenge_id,
        "title": "Status Test Challenge",
        "criteria": "Test criteria",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "proof_code": "CODE123",
        "status": "open",
        "join_deadline": (now + timedelta(days=1)).isoformat(),
        "proof_deadline": (now + timedelta(days=2)).isoformat(),
        "voting_deadline": (now + timedelta(days=3)).isoformat(),
        "verification_mode": "ai",
        "participants": [],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=c_open):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        assert 'id="pay-btn"' in resp.text
        assert "Join &amp; pay" in resp.text
        assert "Voting Deadline" in resp.text

    # 2. Active challenge: unpaid user does NOT see Join & pay
    c_active = dict(c_open, status="active", join_deadline=(now - timedelta(hours=1)).isoformat())
    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=c_active):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        assert 'id="pay-btn"' not in resp.text

    # 3. Voting challenge: paid user sees proof closed notice, not proof upload form
    c_voting = dict(
        c_open,
        status="voting",
        participants=[{"user_id": MOCK_USER["id"], "paid": True, "outcome": "pending"}],
    )
    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=c_voting), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=[]):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        assert 'id="proof-form"' not in resp.text
        assert "Proof submissions are closed for this challenge" in resp.text
