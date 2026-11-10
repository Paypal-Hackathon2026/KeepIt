from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID

import pytest
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.routes import challenges as challenge_routes


MOCK_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "paypal_user_id": "PP-TEST-USER",
    "display_name": "Test User",
    "paypal_email": "test@example.com",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides, current_user, lambda: MOCK_USER
    )
    return TestClient(app)


def _challenge_payload():
    now = datetime.now(timezone.utc)
    return {
        "title": "Run 5km",
        "criteria": "Run 5km and provide a photo as proof",
        "entry_fee_pln": 10.50,
        "join_deadline": (now + timedelta(days=1)).isoformat(),
        "proof_deadline": (now + timedelta(days=15)).isoformat(),
    }


def test_create_challenge_returns_created_challenge(client, monkeypatch):
    challenge_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    created_challenge = {
        "id": challenge_id,
        "creator_id": MOCK_USER["id"],
        "title": "Run 5km",
        "criteria": "Run 5km and provide a photo as proof",
        "entry_fee_minor": 1050,
        "proof_code": "ABC12345",
        "status": "open",
        "join_deadline": "2026-12-01T12:00:00+00:00",
        "proof_deadline": "2026-12-15T12:00:00+00:00",
    }
    mock_create_challenge = Mock(return_value=created_challenge)
    monkeypatch.setattr(challenge_routes, "create_challenge", mock_create_challenge)
    response = client.post("/api/challenges", json=_challenge_payload())

    assert response.status_code == 201
    assert response.json()["id"] == challenge_id
    assert response.json()["entry_fee_minor"] == 1050
    assert UUID(response.json()["creator_id"]) == UUID(MOCK_USER["id"])
    mock_create_challenge.assert_called_once()
    assert mock_create_challenge.call_args.kwargs["creator_id"] == MOCK_USER["id"]


@pytest.mark.parametrize(
    "invalid_deadlines",
    ["past", "reverse"],
)
def test_create_challenge_rejects_invalid_deadlines(
    client, monkeypatch, invalid_deadlines
):
    monkeypatch.setattr(
        challenge_routes,
        "create_challenge",
        lambda payload, creator_id: pytest.fail("Invalid challenge reached database"),
    )
    payload = _challenge_payload()
    now = datetime.now(timezone.utc)
    if invalid_deadlines == "past":
        payload["join_deadline"] = (now - timedelta(days=1)).isoformat()
        payload["proof_deadline"] = (now + timedelta(days=1)).isoformat()
    else:
        payload["join_deadline"] = (now + timedelta(days=2)).isoformat()
        payload["proof_deadline"] = (now + timedelta(days=1)).isoformat()

    response = client.post("/api/challenges", json=payload)

    assert response.status_code == 422


def test_create_challenge_requires_login():
    response = TestClient(app).post(
        "/api/challenges",
        json=_challenge_payload(),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/paypal/login"
