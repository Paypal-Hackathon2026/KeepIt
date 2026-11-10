import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.services.evidence import cast_vote, get_pending_votes_for_user

client = TestClient(app)

MOCK_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "paypal_user_id": "PP-USER-1",
    "display_name": "Alice Voter",
    "paypal_email": "alice@example.com",
}

OTHER_USER_ID = "22222222-2222-2222-2222-222222222222"
THIRD_USER_ID = "33333333-3333-3333-3333-333333333333"
FOURTH_USER_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(autouse=True)
def override_user():
    app.dependency_overrides[current_user] = lambda: MOCK_USER
    yield
    app.dependency_overrides.clear()


def make_mock_table(evidence_data=None, voter_participant=None, paid_participants=None, votes_data=None, challenge_data=None):
    """
    Helper to configure a mock supabase.table() dispatcher.
    """
    table_mocks = {}

    def get_table(name):
        mock_tbl = MagicMock()
        if name == "challenges":
            mock_sel = MagicMock()
            mock_sel.select.return_value.eq.return_value.execute.return_value.data = challenge_data if challenge_data is not None else []
            mock_tbl.select.return_value = mock_sel.select.return_value
        elif name == "evidence":
            mock_sel = MagicMock()
            mock_sel.select.return_value.eq.return_value.execute.return_value.data = evidence_data or []
            mock_tbl.select.return_value = mock_sel.select.return_value
            mock_tbl.update.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "participants":
            def part_select(*args, **kwargs):
                sel_mock = MagicMock()
                def eq_1(col1, val1):
                    eq1_mock = MagicMock()
                    def eq_2(col2, val2):
                        eq2_mock = MagicMock()
                        if col2 == "user_id":
                            # Checking specific voter
                            eq2_mock.execute.return_value.data = voter_participant if voter_participant is not None else []
                        elif col2 == "paid":
                            # Checking all paid participants
                            eq2_mock.execute.return_value.data = paid_participants if paid_participants is not None else []
                        return eq2_mock
                    eq1_mock.eq = eq_2
                    return eq1_mock
                sel_mock.eq = eq_1
                return sel_mock
            mock_tbl.select = part_select
            mock_tbl.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        elif name == "votes":
            mock_tbl.upsert.return_value.execute.return_value = MagicMock()
            mock_sel = MagicMock()
            mock_sel.select.return_value.eq.return_value.execute.return_value.data = votes_data or []
            mock_tbl.select.return_value = mock_sel.select.return_value
        table_mocks[name] = mock_tbl
        return mock_tbl

    return get_table


def test_vote_evidence_not_found():
    evidence_id = str(uuid.uuid4())
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(evidence_data=[])

    with patch("app.services.evidence.supabase", mock_supabase):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert exc_info.value.status_code == 404


def test_vote_evidence_not_needs_vote():
    evidence_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": str(uuid.uuid4()),
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "auto_approved",
    }]
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(evidence_data=evidence_data)

    with patch("app.services.evidence.supabase", mock_supabase):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert exc_info.value.status_code == 400
        assert "not needs_vote" in exc_info.value.detail


def test_voting_other_user_can_vote_after_community_verdict():
    """
    When an evidence has achieved community approved status, other participants
    who have not yet voted can still cast their vote during the voting period.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    voter_2_id = str(uuid.uuid4())

    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "approved",
    }]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=[{"user_id": MOCK_USER["id"], "paid": True}],
        paid_participants=[
            {"user_id": OTHER_USER_ID, "paid": True},
            {"user_id": MOCK_USER["id"], "paid": True},
            {"user_id": voter_2_id, "paid": True},
        ],
        votes_data=[
            {"evidence_id": evidence_id, "challenge_id": challenge_id, "voter_id": voter_2_id, "approve": True},
        ],
        challenge_data=[
            {"id": challenge_id, "status": "active", "voting_deadline": None, "verification_mode": "vote"}
        ],
    )

    with patch("app.services.evidence.supabase", mock_supabase):
        result = cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert result["evidence_id"] == evidence_id
        assert result["approve"] is True


def test_vote_author_cannot_vote_on_own_evidence():
    evidence_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": str(uuid.uuid4()),
        "user_id": MOCK_USER["id"],  # Author is voter!
        "attempt": 1,
        "status": "needs_vote",
    }]
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(evidence_data=evidence_data)

    with patch("app.services.evidence.supabase", mock_supabase):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert exc_info.value.status_code == 403
        assert "cannot vote on your own evidence" in exc_info.value.detail


def test_vote_unpaid_participant_cannot_vote():
    evidence_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": str(uuid.uuid4()),
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    # Voter is unpaid
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": False}]
    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
    )

    with patch("app.services.evidence.supabase", mock_supabase):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            cast_vote(evidence_id, MOCK_USER["id"], approve=True)
        assert exc_info.value.status_code == 403
        assert "Only paid participants can vote" in exc_info.value.detail


def test_voting_invalid_if_less_than_3_participants():
    """
    Requirement: There must always be at least 3 participants for voting to be valid.
    If total_paid < 3, vote is recorded but status remains 'needs_vote'.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    # Only 2 paid participants in total!
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
    ]
    votes_data = [{"voter_id": MOCK_USER["id"], "approve": True}]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status, \
         patch("app.services.evidence.mark_verified") as mock_mark_verified:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=True)

        assert result["status"] == "needs_vote"
        assert result["quorum_reached"] is False
        assert result["total_paid"] == 2
        mock_set_status.assert_not_called()
        mock_mark_verified.assert_not_called()


def test_voting_quorum_requires_50_percent():
    """
    Requirement: At least 50% of registered & paid participants must vote.
    With 4 participants, 50% = 2 votes. If only 1 vote cast, status remains 'needs_vote'.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    # 4 paid participants
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
        {"user_id": THIRD_USER_ID, "paid": True},
        {"user_id": FOURTH_USER_ID, "paid": True},
    ]
    # Only 1 vote cast so far
    votes_data = [{"voter_id": MOCK_USER["id"], "approve": True}]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=True)

        assert result["status"] == "needs_vote"
        assert result["quorum_reached"] is False
        mock_set_status.assert_not_called()


def test_voting_approved_when_tak_strictly_greater_than_nie():
    """
    Requirement: glosy na tak > glosy na nie -> approved.
    3 participants: 2 votes cast (MOCK_USER=True, THIRD_USER=True).
    2 > 0 -> approved, mark_verified called.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
        {"user_id": THIRD_USER_ID, "paid": True},
    ]
    votes_data = [
        {"voter_id": MOCK_USER["id"], "approve": True},
        {"voter_id": THIRD_USER_ID, "approve": True},
    ]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status, \
         patch("app.services.evidence.mark_verified") as mock_mark_verified:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=True)

        assert result["status"] == "approved"
        assert result["quorum_reached"] is True
        assert result["yes_votes"] == 2
        assert result["no_votes"] == 0
        mock_set_status.assert_called_once_with(evidence_id, "approved")
        mock_mark_verified.assert_called_once_with(challenge_id, OTHER_USER_ID)


def test_voting_rejected_on_tie():
    """
    Requirement: glosy na tak = glosy na nie -> nie zaliczony (rejected).
    3 participants: 2 votes cast (1 Yes, 1 No).
    1 == 1 -> rejected.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
        {"user_id": THIRD_USER_ID, "paid": True},
    ]
    votes_data = [
        {"voter_id": MOCK_USER["id"], "approve": True},
        {"voter_id": THIRD_USER_ID, "approve": False},
    ]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status, \
         patch("app.services.evidence.mark_verified") as mock_mark_verified:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=True)

        assert result["status"] == "rejected"
        assert result["yes_votes"] == 1
        assert result["no_votes"] == 1
        mock_set_status.assert_called_once_with(evidence_id, "rejected")
        mock_mark_verified.assert_not_called()


def test_voting_attempt_3_rejected_marks_forfeited():
    """
    When attempt 3 is rejected, participant outcome is marked forfeited.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 3,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
        {"user_id": THIRD_USER_ID, "paid": True},
    ]
    votes_data = [
        {"voter_id": MOCK_USER["id"], "approve": False},
        {"voter_id": THIRD_USER_ID, "approve": False},
    ]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status, \
         patch("app.services.evidence.mark_forfeited") as mock_mark_forfeited:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=False)

        assert result["status"] == "rejected"
        mock_set_status.assert_called_once_with(evidence_id, "rejected")
        mock_mark_forfeited.assert_called_once_with(challenge_id, OTHER_USER_ID)


def test_voting_only_mode_attempt_1_rejected_marks_forfeited():
    """
    In vote mode, there is only 1 attempt allowed.
    Rejecting attempt 1 must immediately mark the participant as forfeited!
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())
    evidence_data = [{
        "id": evidence_id,
        "challenge_id": challenge_id,
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "needs_vote",
    }]
    voter_participant = [{"user_id": MOCK_USER["id"], "paid": True}]
    paid_participants = [
        {"user_id": OTHER_USER_ID, "paid": True},
        {"user_id": MOCK_USER["id"], "paid": True},
        {"user_id": THIRD_USER_ID, "paid": True},
    ]
    votes_data = [
        {"voter_id": MOCK_USER["id"], "approve": False},
        {"voter_id": THIRD_USER_ID, "approve": False},
    ]
    challenge_data = [{
        "id": challenge_id,
        "status": "active",
        "join_deadline": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "verification_mode": "vote",
    }]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=voter_participant,
        paid_participants=paid_participants,
        votes_data=votes_data,
        challenge_data=challenge_data,
    )

    with patch("app.services.evidence.supabase", mock_supabase), \
         patch("app.services.evidence.set_status") as mock_set_status, \
         patch("app.services.evidence.mark_forfeited") as mock_mark_forfeited:

        result = cast_vote(evidence_id, MOCK_USER["id"], approve=False)

        assert result["status"] == "rejected"
        mock_set_status.assert_called_once_with(evidence_id, "rejected")
        # In vote mode, attempt 1 already forfeits!
        mock_mark_forfeited.assert_called_once_with(challenge_id, OTHER_USER_ID)


def test_voting_only_mode_blocks_more_than_one_attempt():
    """
    In vote mode, uploading more than 1 attempt raises ValueError.
    """
    from app.services.evidence import save_evidence
    from PIL import Image
    import io

    challenge_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    buf = io.BytesIO()
    img = Image.new("RGB", (10, 10), color="blue")
    img.save(buf, format="JPEG")
    fake_photo = buf.getvalue()

    # User already has 1 attempt
    with patch("app.services.evidence.count_attempts", return_value=1), \
         patch("app.services.evidence.get_challenge_max_attempts", return_value=1):

        with pytest.raises(ValueError) as exc_info:
            save_evidence(challenge_id, user_id, fake_photo)
        assert "You have already used all 1 attempts" in str(exc_info.value)


def test_post_vote_endpoint_form_redirects():
    """
    POST /evidence/{id}/vote with form data redirects to /challenges/{challenge_id}?vote=success
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())

    mock_result = {
        "evidence_id": evidence_id,
        "challenge_id": challenge_id,
        "voter_id": MOCK_USER["id"],
        "approve": True,
        "status": "needs_vote",
    }

    with patch("app.routes.challenge_pages.cast_vote", return_value=mock_result) as mock_cast:
        resp = client.post(
            f"/evidence/{evidence_id}/vote",
            data={"approve": "true"},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}?vote=success"
        mock_cast.assert_called_once_with(evidence_id, MOCK_USER["id"], True)


def test_post_vote_endpoint_json():
    """
    POST /evidence/{id}/vote with JSON body returns JSON result.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())

    mock_result = {
        "evidence_id": evidence_id,
        "challenge_id": challenge_id,
        "voter_id": MOCK_USER["id"],
        "approve": False,
        "status": "rejected",
    }

    with patch("app.routes.challenge_pages.cast_vote", return_value=mock_result) as mock_cast:
        resp = client.post(
            f"/evidence/{evidence_id}/vote",
            json={"approve": False},
            headers={"accept": "application/json"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"
        assert data["approve"] is False
        mock_cast.assert_called_once_with(evidence_id, MOCK_USER["id"], False)


def test_challenge_page_renders_go_to_voting_button():
    """
    GET /challenges/{id} renders the Go to voting button under copy invite link when user is paid.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Do 50 squats",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "VOTE999",
        "status": "active",
        "join_deadline": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Voter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
        ],
    }

    mock_pending = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "attempt": 1,
            "photo_url": "https://example.com/photo.jpg",
            "my_vote": None,
            "yes_count": 1,
            "no_count": 0,
            "total_votes": 1,
        }
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=mock_pending):

        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="go-to-voting-btn"' in html
        assert f"/challenges/{challenge_id}/voting" in html
        assert 'target="_blank"' in html
        assert "Community Voting Active" in html
        assert '<span class="voting-pill">1</span>' in html
        assert "There are 1 proof(s) waiting for your review." in html


def test_challenge_page_hides_pill_and_banner_when_user_already_voted():
    """
    When the current user has already voted on all pending proofs,
    the voting-pill count and the Community Voting Active banner are not shown.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Do 50 squats",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "VOTE999",
        "status": "open",
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Voter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
        ],
    }

    mock_pending = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "attempt": 1,
            "photo_url": "https://example.com/photo.jpg",
            "my_vote": True,  # User already voted!
            "yes_count": 1,
            "no_count": 0,
            "total_votes": 1,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": THIRD_USER_ID,
            "author_name": "Charlie Submitter",
            "attempt": 1,
            "photo_url": "https://example.com/photo2.jpg",
            "my_vote": False,  # User already voted!
            "yes_count": 0,
            "no_count": 1,
            "total_votes": 1,
        },
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=mock_pending):

        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        html = resp.text
        # Button to visit voting subpage remains accessible
        assert 'id="go-to-voting-btn"' in html
        # But pill badge and active banner are hidden
        assert "voting-pill" not in html
        assert "Community Voting Active" not in html


def test_voting_subpage_renders_proofs_and_modal():
    """
    GET /challenges/{id}/voting renders the dedicated voting subpage with zoomable photos and vote buttons.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Do 50 squats",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "VOTE999",
        "status": "active",
        "join_deadline": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Voter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
            {
                "user_id": OTHER_USER_ID,
                "display_name": "Bob Submitter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:30:00+00:00",
            },
        ],
    }

    mock_pending = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "attempt": 1,
            "photo_url": "https://example.com/photo.jpg",
            "my_vote": None,
            "yes_count": 1,
            "no_count": 0,
            "total_votes": 1,
        }
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_voting_feed", return_value=mock_pending):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        html = resp.text
        assert "Community Voting" in html
        assert "Bob Submitter" in html
        assert "Approve" in html
        assert "Reject" in html
        assert f"/evidence/{mock_pending[0]['id']}/vote" in html
        assert 'id="image-modal"' in html
        assert "openImageModal" in html
        assert "vote-photo-clickable" in html
        assert "photo-zoom-hint" not in html
        assert "fa-magnifying-glass-plus" not in html
        assert "1 awaiting your vote" in html


def test_voting_subpage_when_user_already_voted_on_all():
    """
    GET /challenges/{id}/voting displays that user has voted on all proofs when unvoted_count is 0.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Do 50 squats",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "VOTE999",
        "status": "active",
        "join_deadline": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "verification_mode": "vote",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Voter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
        ],
    }

    mock_pending = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "attempt": 1,
            "photo_url": "https://example.com/photo.jpg",
            "my_vote": True,
            "yes_count": 1,
            "no_count": 0,
            "total_votes": 1,
        }
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=mock_pending):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        html = resp.text
        assert "You&#39;ve voted on all proofs" in html or "You've voted on all proofs" in html
        assert "awaiting your vote" not in html


def test_post_vote_endpoint_with_return_to_redirects():
    """
    POST /evidence/{id}/vote with return_to parameter redirects back to voting subpage.
    """
    evidence_id = str(uuid.uuid4())
    challenge_id = str(uuid.uuid4())

    mock_result = {
        "evidence_id": evidence_id,
        "challenge_id": challenge_id,
        "voter_id": MOCK_USER["id"],
        "approve": True,
        "status": "needs_vote",
    }

    with patch("app.routes.challenge_pages.cast_vote", return_value=mock_result) as mock_cast:
        resp = client.post(
            f"/evidence/{evidence_id}/vote",
            data={"approve": "true", "return_to": f"/challenges/{challenge_id}/voting"},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/challenges/{challenge_id}/voting?vote=success"
        mock_cast.assert_called_once_with(evidence_id, MOCK_USER["id"], True)


def test_voting_subpage_chat_layout_me_on_right_others_on_left():
    """
    Voting page chat layout displays:
    - Top header with 'Voting Page', challenge title, and challenge description/criteria.
    - My photo on the RIGHT (chat-msg-me) with 'You' and no vote buttons.
    - Other participant's photo on the LEFT (chat-msg-them) with their name, avatar, and voting buttons.
    """
    challenge_id = uuid.uuid4()
    my_evidence_id = str(uuid.uuid4())
    other_evidence_id = str(uuid.uuid4())

    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Squat Master 3000",
        "criteria": "Record yourself completing 30 deep squats",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "SQUAT123",
        "status": "voting",
        "verification_mode": "vote",
        "voting_deadline": "2026-11-10T21:46:00+00:00",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Voter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
            {
                "user_id": OTHER_USER_ID,
                "display_name": "Bob Submitter",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:30:00+00:00",
            },
        ],
    }

    mock_feed = [
        # Chronological order: first Bob submitted, then Alice submitted
        {
            "id": other_evidence_id,
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "avatar_initials": "BS",
            "is_me": False,
            "attempt": 1,
            "status": "needs_vote",
            "photo_url": "https://example.com/bob_photo.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        },
        {
            "id": my_evidence_id,
            "challenge_id": str(challenge_id),
            "user_id": MOCK_USER["id"],
            "author_name": "You",
            "avatar_initials": "YOU",
            "is_me": True,
            "attempt": 1,
            "status": "needs_vote",
            "photo_url": "https://example.com/my_photo.jpg",
            "my_vote": None,
            "yes_count": 1,
            "no_count": 0,
            "total_votes": 1,
        },
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_voting_feed", return_value=mock_feed):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        html = resp.text

        # Header has the voting title, challenge title, and criteria.
        assert "Community Voting" in html
        assert "Squat Master 3000" in html
        assert "Record yourself completing 30 deep squats" in html
        assert "SQUAT123" in html

        # 2. My photo is on the RIGHT
        assert "chat-msg-me" in html
        assert "chat-bubble-me" in html
        assert 'alt="Your proof"' in html
        # You cannot vote on your own photo (no form to vote on my_evidence_id)
        assert f"/evidence/{my_evidence_id}/vote" not in html

        # 3. Other's photo is on the LEFT
        assert "chat-msg-them" in html
        assert "chat-bubble-them" in html
        assert "Bob Submitter" in html
        # Vote buttons are present for other's photo
        assert f"/evidence/{other_evidence_id}/vote" in html
        assert "Approve" in html
        assert "Reject" in html


def test_voting_notifications_hidden_when_challenge_is_settling_or_closed():
    """
    When a challenge is in settling, closed, or other non-voting status:
    1. Detail page hides the voting-pill on 'Go to voting' button and the 'Community Voting Active' banner.
    2. Voting page does not show 'awaiting your vote' pill and displays 'Voting closed'.
    """
    challenge_id = uuid.uuid4()
    other_evidence_id = str(uuid.uuid4())

    for status in ("settling", "closed", "settled", "cancelled"):
        mock_challenge = {
            "id": challenge_id,
            "creator_id": MOCK_USER["id"],
            "title": "Settling Challenge",
            "criteria": "Run 5km",
            "entry_fee_minor": 1000,
            "pool_minor": 2000,
            "proof_code": "RUN123",
            "status": status,
            "verification_mode": "vote",
            "voting_deadline": "2026-11-08T10:00:00+00:00",
            "participants": [
                {
                    "user_id": MOCK_USER["id"],
                    "display_name": "Alice Voter",
                    "paid": True,
                    "outcome": "pending",
                    "joined_at": "2026-11-06T10:00:00+00:00",
                },
            ],
        }

        mock_pending = [
            {
                "id": other_evidence_id,
                "challenge_id": str(challenge_id),
                "user_id": OTHER_USER_ID,
                "author_name": "Bob Submitter",
                "attempt": 1,
                "photo_url": "https://example.com/bob.jpg",
                "my_vote": None,  # Not voted yet, but voting is closed!
                "yes_count": 0,
                "no_count": 0,
                "total_votes": 0,
                "status": "needs_vote",
                "is_me": False,
            }
        ]

        # 1. Detail page check
        with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
             patch("app.routes.challenge_pages.get_my_evidence", return_value=[]), \
             patch("app.routes.challenge_pages.get_voting_feed", return_value=[]), \
             patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=mock_pending):

            resp = client.get(f"/challenges/{challenge_id}")
            assert resp.status_code == 200
            assert "voting-pill" not in resp.text
            assert "Community Voting Active" not in resp.text

        # 2. Voting page check
        with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
             patch("app.routes.challenge_pages.get_voting_feed", return_value=mock_pending):

            resp = client.get(f"/challenges/{challenge_id}/voting")
            assert resp.status_code == 200
            assert "awaiting your vote" not in resp.text
            assert "Voting closed" in resp.text
            assert "Voting has concluded" in resp.text
            # No vote action buttons when closed/settling
            assert f"/evidence/{other_evidence_id}/vote" not in resp.text


def test_ai_mode_voting_page_only_shows_needs_vote_photos():
    """
    In an AI arbiter challenge (verification_mode == 'ai'), the voting page feed must
    strictly show photos with status 'needs_vote'. Photos that were auto-approved or rejected
    by AI must not appear in the voting feed.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "AI Arbiter Challenge",
        "criteria": "Run 5km",
        "verification_mode": "ai",
        "status": "active",
        "participants": [
            {"user_id": MOCK_USER["id"], "paid": True, "display_name": "Alice Tester"},
            {"user_id": OTHER_USER_ID, "paid": True, "display_name": "Bob Runner"},
        ],
    }

    raw_feed_items = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Runner",
            "is_me": False,
            "attempt": 1,
            "status": "auto_approved",
            "photo_url": "https://example.com/bob_auto_approved.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Runner",
            "is_me": False,
            "attempt": 2,
            "status": "auto_rejected",
            "photo_url": "https://example.com/bob_auto_rejected.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Runner",
            "is_me": False,
            "attempt": 3,
            "status": "needs_vote",
            "photo_url": "https://example.com/bob_needs_vote.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Runner",
            "is_me": False,
            "attempt": 4,
            "status": "approved",
            "photo_url": "https://example.com/bob_community_approved.jpg",
            "my_vote": True,
            "yes_count": 2,
            "no_count": 0,
            "total_votes": 2,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Runner",
            "is_me": False,
            "attempt": 5,
            "status": "rejected",
            "photo_url": "https://example.com/bob_community_rejected.jpg",
            "my_vote": False,
            "yes_count": 0,
            "no_count": 2,
            "total_votes": 2,
        },
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_voting_feed", return_value=raw_feed_items):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        html = resp.text

        # Needs_vote, community-approved, and community-rejected should be in the feed
        assert "bob_needs_vote.jpg" in html
        assert "bob_community_approved.jpg" in html
        assert "bob_community_rejected.jpg" in html
        # Auto-approved and auto-rejected must not appear in the feed
        assert "bob_auto_approved.jpg" not in html
        assert "bob_auto_rejected.jpg" not in html


def test_group_voting_mode_shows_approved_and_rejected_photos_on_voting_page():
    """
    In group vote only challenges (verification_mode == 'vote'), all submitted photos
    must appear on the voting page timeline even after being approved or rejected by the community.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Group Vote Challenge",
        "criteria": "Submit daily code",
        "verification_mode": "vote",
        "status": "active",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "participants": [
            {"user_id": MOCK_USER["id"], "paid": True, "display_name": "Alice Tester"},
            {"user_id": OTHER_USER_ID, "paid": True, "display_name": "Bob Submitter"},
        ],
    }

    raw_feed_items = [
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob Submitter",
            "is_me": False,
            "attempt": 1,
            "status": "approved",
            "photo_url": "https://example.com/bob_approved.jpg",
            "my_vote": True,
            "yes_count": 2,
            "no_count": 0,
            "total_votes": 2,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": str(uuid.uuid4()),
            "author_name": "Charlie Submitter",
            "is_me": False,
            "attempt": 1,
            "status": "rejected",
            "photo_url": "https://example.com/charlie_rejected.jpg",
            "my_vote": False,
            "yes_count": 0,
            "no_count": 2,
            "total_votes": 2,
        },
        {
            "id": str(uuid.uuid4()),
            "challenge_id": str(challenge_id),
            "user_id": MOCK_USER["id"],
            "author_name": "You",
            "is_me": True,
            "attempt": 1,
            "status": "needs_vote",
            "photo_url": "https://example.com/my_needs_vote.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        },
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_voting_feed", return_value=raw_feed_items):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        html = resp.text

        # In vote mode, ALL photos (approved, rejected, needs_vote) must appear!
        assert "bob_approved.jpg" in html
        assert "charlie_rejected.jpg" in html
        assert "my_needs_vote.jpg" in html
        assert "Approved by community" in html
        assert "Rejected by community" in html


def test_group_voting_mode_does_not_render_ai_arbiter_opinion():
    """
    In group vote only challenges (verification_mode == 'vote'), attempt cards should not
    say "AI Arbiter's opinion", only "Needs voting".
    In AI mode challenges, "AI Arbiter's opinion" should be displayed.
    """
    challenge_id = uuid.uuid4()
    mock_evidence = [
        {
            "attempt": 1,
            "status": "needs_vote",
            "photo_url": "https://example.com/proof.jpg",
            "verdict": None,
        }
    ]

    # 1. Group vote challenge
    mock_challenge_vote = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Vote Only Challenge",
        "criteria": "Cook pasta",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "verification_mode": "vote",
        "status": "active",
        "participants": [
            {"user_id": MOCK_USER["id"], "paid": True, "outcome": "pending"},
        ],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_vote), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=mock_evidence), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=[]):

        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        assert "Needs voting" in resp.text
        assert "AI Arbiter&#39;s opinion" not in resp.text
        assert "AI Arbiter's opinion" not in resp.text

    # 2. AI Arbiter challenge
    mock_challenge_ai = dict(mock_challenge_vote, verification_mode="ai")
    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge_ai), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=mock_evidence), \
         patch("app.routes.challenge_pages.get_pending_votes_for_user", return_value=[]):

        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        assert "Needs voting" in resp.text
        assert ("AI Arbiter&#39;s opinion" in resp.text or "AI Arbiter's opinion" in resp.text)


def test_get_voting_feed_mode_filtering():
    """
    Directly tests get_voting_feed:
    - In AI arbiter mode ('ai'): excludes auto_approved and auto_rejected items;
      retains pending, needs_vote, approved, and rejected items.
    - In group vote mode ('vote'): retains all submitted items without exception.
    """
    from app.services.evidence import get_voting_feed

    challenge_id = str(uuid.uuid4())
    mock_supabase = MagicMock()

    sample_data = [
        {"id": "ev-1", "challenge_id": challenge_id, "user_id": "u1", "attempt": 1, "storage_path": "p1", "status": "approved"},
        {"id": "ev-2", "challenge_id": challenge_id, "user_id": "u2", "attempt": 1, "storage_path": "p2", "status": "rejected"},
        {"id": "ev-3", "challenge_id": challenge_id, "user_id": "u3", "attempt": 1, "storage_path": "p3", "status": "needs_vote"},
        {"id": "ev-4", "challenge_id": challenge_id, "user_id": "u4", "attempt": 1, "storage_path": "p4", "status": "auto_approved"},
        {"id": "ev-5", "challenge_id": challenge_id, "user_id": "u5", "attempt": 1, "storage_path": "p5", "status": "auto_rejected"},
        {"id": "ev-6", "challenge_id": challenge_id, "user_id": "u6", "attempt": 1, "storage_path": "p6", "status": "pending"},
    ]

    tbl = MagicMock()
    tbl.select.return_value.eq.return_value.execute.return_value.data = sample_data
    tbl.select.return_value.in_.return_value.execute.return_value.data = [
        {"evidence_id": "ev-1", "voter_id": "u2", "approve": True},
        {"evidence_id": "ev-2", "voter_id": "u1", "approve": False},
    ]
    mock_supabase.table.return_value = tbl
    mock_supabase.storage.from_().create_signed_url.return_value = {"signedUrl": "https://url.com"}

    with patch("app.services.evidence.supabase", mock_supabase):
        # AI mode: strictly needs_vote, community-approved, community-rejected
        feed_ai = get_voting_feed(challenge_id, "u1", verification_mode="ai")
        feed_ids_ai = [item["id"] for item in feed_ai]
        assert "ev-1" in feed_ids_ai
        assert "ev-2" in feed_ids_ai
        assert "ev-3" in feed_ids_ai
        assert "ev-4" not in feed_ids_ai
        assert "ev-5" not in feed_ids_ai
        assert "ev-6" not in feed_ids_ai

        # Vote mode (vote only): all photos displayed
        feed_vote = get_voting_feed(challenge_id, "u1", verification_mode="vote")
        assert len(feed_vote) == 6
        feed_ids_vote = [item["id"] for item in feed_vote]
        assert "ev-1" in feed_ids_vote
        assert "ev-2" in feed_ids_vote
        assert "ev-3" in feed_ids_vote
        assert "ev-4" in feed_ids_vote
        assert "ev-5" in feed_ids_vote
        assert "ev-6" in feed_ids_vote


def test_vote_only_challenge_first_user_photo_visible_and_votable_by_subsequent_users():
    """
    When user 1 uploads in vote-only challenge:
    - Status is 'needs_vote' (not auto_approved, not immediately verified).
    - Their photo is visible in the voting feed for other participants.
    - Subsequent participants can vote on it.
    - Even if a photo in vote mode has 'auto_approved' from a prior bug,
      it still appears and other participants can vote on it.
    """
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": OTHER_USER_ID,
        "title": "Community Vote Challenge",
        "criteria": "Run 5k",
        "verification_mode": "vote",
        "status": "active",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "participants": [
            {"user_id": OTHER_USER_ID, "paid": True, "display_name": "Bob First"},
            {"user_id": MOCK_USER["id"], "paid": True, "display_name": "Alice Voter"},
        ],
    }

    evidence_id = str(uuid.uuid4())
    mock_feed = [
        {
            "id": evidence_id,
            "challenge_id": str(challenge_id),
            "user_id": OTHER_USER_ID,
            "author_name": "Bob First",
            "is_me": False,
            "attempt": 1,
            "status": "needs_vote",
            "photo_url": "https://example.com/bob_proof.jpg",
            "my_vote": None,
            "yes_count": 0,
            "no_count": 0,
            "total_votes": 0,
        }
    ]

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_voting_feed", return_value=mock_feed):

        resp = client.get(f"/challenges/{challenge_id}/voting")
        assert resp.status_code == 200
        assert "bob_proof.jpg" in resp.text
        assert f"/evidence/{evidence_id}/vote" in resp.text

    # Verify that cast_vote allows voting on vote-mode evidence even if status was auto_approved
    legacy_auto_approved_ev_id = str(uuid.uuid4())
    evidence_data = [{
        "id": legacy_auto_approved_ev_id,
        "challenge_id": str(challenge_id),
        "user_id": OTHER_USER_ID,
        "attempt": 1,
        "status": "auto_approved",
    }]

    mock_supabase = MagicMock()
    mock_supabase.table.side_effect = make_mock_table(
        evidence_data=evidence_data,
        voter_participant=[{"user_id": MOCK_USER["id"], "paid": True}],
        paid_participants=[
            {"user_id": OTHER_USER_ID, "paid": True},
            {"user_id": MOCK_USER["id"], "paid": True},
            {"user_id": str(uuid.uuid4()), "paid": True},
        ],
        challenge_data=[{
            "id": str(challenge_id),
            "status": "active",
            "verification_mode": "vote",
            "voting_deadline": None,
        }],
    )

    with patch("app.services.evidence.supabase", mock_supabase):
        res = cast_vote(legacy_auto_approved_ev_id, MOCK_USER["id"], approve=True)
        assert res["approve"] is True
        assert res["evidence_id"] == legacy_auto_approved_ev_id





