import uuid
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app

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


def test_challenge_state_not_found():
    non_existent_id = uuid.uuid4()
    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=None):
        resp = client.get(f"/challenges/{non_existent_id}/state")
        assert resp.status_code == 404


def test_challenge_state_fragment_content():
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "30-Day Fitness Challenge",
        "criteria": "Run 5k every single day",
        "entry_fee_minor": 1000,
        "pool_minor": 2000,
        "proof_code": "FIT12345",
        "status": "open",
        "join_deadline": "2026-11-10T12:00:00+00:00",
        "proof_deadline": "2026-11-20T12:00:00+00:00",
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
                "display_name": "Bob Runner",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T11:30:00+00:00",
            },
            {
                "user_id": "33333333-3333-3333-3333-333333333333",
                "display_name": "Charlie Lurker",
                "paid": False,
                "outcome": "pending",
                "joined_at": "2026-11-06T12:00:00+00:00",
            },
        ],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge):
        resp = client.get(f"/challenges/{challenge_id}/state")
        assert resp.status_code == 200
        html = resp.text

        # HTMX out-of-band swap for pool banner
        assert 'id="pool-banner"' in html
        assert 'hx-swap-oob="outerHTML"' in html
        assert "20.00 PLN" in html
        assert "10.00 PLN" in html

        # Participants section
        assert "Participants (3)" in html
        assert "Alice Tester" in html
        assert "Bob Runner" in html
        assert "Charlie Lurker" in html
        assert "Paid" in html
        assert "Unpaid" in html

        # Payment History section
        assert "Payment History" in html
        assert "+10.00 PLN" in html
        assert "2026-11-06 10:00" in html
        assert "2026-11-06 11:30" in html

        # Charlie Lurker is unpaid so should not appear in payment history
        # We can check that only 2 history rows are rendered
        assert html.count("history-row") == 2


def test_challenge_detail_page_has_htmx_trigger():
    challenge_id = uuid.uuid4()
    mock_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "30-Day Fitness Challenge",
        "criteria": "Run 5k every single day",
        "entry_fee_minor": 1000,
        "pool_minor": 1000,
        "proof_code": "FIT12345",
        "status": "open",
        "join_deadline": "2026-11-10T12:00:00+00:00",
        "proof_deadline": "2026-11-20T12:00:00+00:00",
        "participants": [
            {
                "user_id": MOCK_USER["id"],
                "display_name": "Alice Tester",
                "paid": True,
                "outcome": "pending",
                "joined_at": "2026-11-06T10:00:00+00:00",
            },
        ],
    }

    with patch("app.routes.challenge_pages.get_challenge_by_id", return_value=mock_challenge), \
         patch("app.routes.challenge_pages.get_my_evidence", return_value=[]):
        resp = client.get(f"/challenges/{challenge_id}")
        assert resp.status_code == 200
        html = resp.text

        assert 'id="pool-banner"' in html
        assert f'hx-get="/challenges/{challenge_id}/state"' in html
        assert 'hx-trigger="every 3s"' in html
        assert 'hx-swap="innerHTML"' in html
        assert "Payment History" in html

