import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.models.challenge import ChallengeCreate, ChallengeOut, ChallengeDetailOut
from app.services.challenge_service import create_challenge

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


def test_challenge_create_model_verification_mode():
    now = datetime.now(timezone.utc)
    join_dl = now + timedelta(days=1)
    proof_dl = now + timedelta(days=2)

    # Default should be "ai"
    c_default = ChallengeCreate(
        title="Default Mode Challenge",
        criteria="Do 20 pushups every day",
        entry_fee_pln=Decimal("15.00"),
        join_deadline=join_dl,
        proof_deadline=proof_dl,
    )
    assert c_default.verification_mode == "ai"

    # Explicit "vote" mode
    c_vote = ChallengeCreate(
        title="Vote Mode Challenge",
        criteria="Do 20 pushups every day",
        entry_fee_pln=Decimal("15.00"),
        join_deadline=join_dl,
        proof_deadline=proof_dl,
        verification_mode="vote",
    )
    assert c_vote.verification_mode == "vote"

    # Invalid mode should raise ValidationError
    with pytest.raises(ValidationError):
        ChallengeCreate(
            title="Invalid Mode",
            criteria="Do 20 pushups every day",
            entry_fee_pln=Decimal("15.00"),
            join_deadline=join_dl,
            proof_deadline=proof_dl,
            verification_mode="invalid_mode",
        )


def test_create_challenge_passes_verification_mode():
    now = datetime.now(timezone.utc)
    join_dl = now + timedelta(days=1)
    proof_dl = now + timedelta(days=2)

    c_vote = ChallengeCreate(
        title="Vote Mode Challenge",
        criteria="Do 20 pushups every day",
        entry_fee_pln=Decimal("20.00"),
        join_deadline=join_dl,
        proof_deadline=proof_dl,
        verification_mode="vote",
    )

    mock_rpc = MagicMock()
    mock_rpc.execute.return_value.data = {"id": str(uuid.uuid4()), "verification_mode": "vote"}

    with patch("app.services.challenge_service.supabase.rpc", return_value=mock_rpc) as mocked_rpc:
        result = create_challenge(c_vote, creator_id=MOCK_USER["id"])
        assert result["verification_mode"] == "vote"

        mocked_rpc.assert_called_once()
        args, kwargs = mocked_rpc.call_args
        assert args[0] == "create_challenge_with_participant"
        rpc_params = args[1]
        assert rpc_params["p_verification_mode"] == "vote"


def test_new_challenge_page_renders_mode_select():
    resp = client.get("/challenges/new")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="verification_mode"' in html
    assert 'name="verification_mode"' in html
    assert 'value="ai"' in html
    assert 'value="vote"' in html


def test_post_new_challenge_vote_mode():
    now = datetime.now(timezone.utc)
    join_str = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    proof_str = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")

    created_id = str(uuid.uuid4())
    mock_created = {"id": created_id, "verification_mode": "vote"}

    with patch("app.routes.challenge_pages.create_challenge", return_value=mock_created) as mock_create:
        resp = client.post(
            "/challenges/new",
            data={
                "title": "Group Vote Sprint",
                "criteria": "Complete 5 lessons on Duolingo",
                "entry_fee_pln": "25.00",
                "join_deadline": join_str,
                "proof_deadline": proof_str,
                "verification_mode": "vote",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{created_id}"

        mock_create.assert_called_once()
        called_payload, _ = mock_create.call_args
        assert called_payload[0].verification_mode == "vote"


def test_challenge_detail_renders_verification_mode_badge():
    challenge_id = uuid.uuid4()
    mock_challenge_vote = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Run 5k every morning",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "proof_code": "VOTE1234",
        "status": "open",
        "join_deadline": "2026-11-10T12:00:00+00:00",
        "proof_deadline": "2026-11-20T12:00:00+00:00",
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Tester",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            }
        ],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_vote), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "Group Vote" in html
        assert "mode-vote" in html

    mock_challenge_ai = dict(mock_challenge_vote, verification_mode="ai")
    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_ai), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        html = resp.text
        assert "AI Arbiter" in html
        assert "mode-ai" in html


def test_upload_evidence_vote_mode_single_participant_auto_approve():
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Solo Vote Challenge",
        "criteria": "Run 5k every morning",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "proof_code": "SOLO1234",
        "status": "open",
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Tester",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            }
        ],
    }

    # Generate a dummy 1x1 JPEG image
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="JPEG")
    fake_photo_bytes = buf.getvalue()

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.save_evidence", return_value=({"id": str(uuid.uuid4()), "attempt": 1}, fake_photo_bytes)) as mock_save_evidence, \
         patch("app.routes.challenge_pages.mark_verified") as mock_mark_verified:

        resp = client.post(
            f"/challenges/{challenge_id}/evidence",
            files={"photo": ("proof.jpg", fake_photo_bytes, "image/jpeg")},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}?proof=auto_approved"

        # Verify save_evidence was called with status="auto_approved"
        mock_save_evidence.assert_called_once()
        _, kwargs = mock_save_evidence.call_args
        assert kwargs.get("status") == "auto_approved"

        # Verify participant was marked verified
        mock_mark_verified.assert_called_once_with(str(challenge_id), str(MOCK_USER["id"]))


def test_upload_evidence_vote_mode_multiple_participants_needs_vote():
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Run 5k every morning",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "GROUP123",
        "status": "open",
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Tester",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
            {
                "user_id": "22222222-2222-2222-2222-222222222222",
                "display_name": "Bob Friend",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:30:00+00:00",
            },
        ],
    }

    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="JPEG")
    fake_photo_bytes = buf.getvalue()

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.save_evidence", return_value=({"id": str(uuid.uuid4()), "attempt": 1}, fake_photo_bytes)) as mock_save_evidence:

        resp = client.post(
            f"/challenges/{challenge_id}/evidence",
            files={"photo": ("proof.jpg", fake_photo_bytes, "image/jpeg")},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}?proof=needs_vote"

        mock_save_evidence.assert_called_once()
        _, kwargs = mock_save_evidence.call_args
        assert kwargs.get("status") == "needs_vote"


def test_upload_evidence_ai_mode_calls_judge():
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "AI Mode Challenge",
        "criteria": "Run 5k every morning",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "AI123456",
        "status": "open",
        "verification_mode": "ai",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Tester",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
            {
                "user_id": "22222222-2222-2222-2222-222222222222",
                "display_name": "Bob Friend",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:30:00+00:00",
            },
        ],
    }

    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="JPEG")
    fake_photo_bytes = buf.getvalue()

    from app.services.arbiter import Verdict
    mock_verdict = Verdict(
        observations="Looks good",
        verified=True,
        confidence=0.9,
        code_visible=True,
        reasoning="All done",
        fraud_flags=[],
    )

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.save_evidence", return_value=({"id": str(uuid.uuid4()), "attempt": 1}, fake_photo_bytes)) as mock_save_evidence, \
         patch("app.routes.challenge_pages.judge", return_value=(mock_verdict, "gemini-test")), \
         patch("app.routes.challenge_pages.save_verdict"), \
         patch("app.routes.challenge_pages.set_status"), \
         patch("app.routes.challenge_pages.mark_verified") as mock_mark_verified:

        resp = client.post(
            f"/challenges/{challenge_id}/evidence",
            files={"photo": ("proof.jpg", fake_photo_bytes, "image/jpeg")},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}?proof=auto_approved"

        mock_save_evidence.assert_called_once()
        mock_mark_verified.assert_called_once_with(str(challenge_id), str(MOCK_USER["id"]))

