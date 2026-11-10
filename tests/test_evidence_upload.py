from unittest.mock import Mock
from uuid import uuid4

import pytest
from PIL import UnidentifiedImageError
from starlette.testclient import TestClient

from app.deps import current_user
from app.main import app
from app.routes import challenge_pages


MOCK_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "paypal_user_id": "PP-TEST-USER",
    "display_name": "Test User",
    "paypal_email": "test@example.com",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, current_user, lambda: MOCK_USER)
    return TestClient(app)


def _challenge(challenge_id, participant):
    return {
        "id": challenge_id,
        "title": "Test challenge",
        "criteria": "Complete the task",
        "proof_code": "TEST1234",
        "status": "open",
        "verification_mode": "ai",
        "participants": [participant] if participant else [],
    }


def _reject_non_image(*args, **kwargs):
    raise UnidentifiedImageError()


@pytest.mark.parametrize(
    "participant",
    [
        None,
        {
            "user_id": MOCK_USER["id"],
            "paid": False,
            "outcome": "pending",
        },
    ],
    ids=["not-a-participant", "unpaid-participant"],
)
def test_upload_evidence_requires_paid_participant(
    client,
    monkeypatch,
    participant,
):
    challenge_id = uuid4()
    monkeypatch.setattr(
        challenge_pages,
        "get_challenge_by_id",
        lambda challenge_id: _challenge(challenge_id, participant),
    )
    monkeypatch.setattr(
        challenge_pages,
        "save_evidence",
        lambda *args, **kwargs: pytest.fail("Evidence should not be saved"),
    )

    response = client.post(
        f"/challenges/{challenge_id}/evidence",
        files={"photo": ("proof.jpg", b"image-data", "image/jpeg")},
    )

    assert response.status_code == 403


def test_upload_evidence_rejects_file_over_15_mb(client, monkeypatch):
    challenge_id = uuid4()
    participant = {
        "user_id": MOCK_USER["id"],
        "paid": True,
        "outcome": "pending",
    }
    monkeypatch.setattr(
        challenge_pages,
        "get_challenge_by_id",
        lambda challenge_id: _challenge(challenge_id, participant),
    )
    monkeypatch.setattr(challenge_pages, "get_my_evidence", lambda *args: [])
    save_mock = Mock()
    monkeypatch.setattr(challenge_pages, "save_evidence", save_mock)

    response = client.post(
        f"/challenges/{challenge_id}/evidence",
        files={
            "photo": (
                "large.jpg",
                b"x" * (challenge_pages.MAX_UPLOAD_BYTES + 1),
                "image/jpeg",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/challenges/{challenge_id}?proof_error=too_big"
    )
    save_mock.assert_not_called()


def test_upload_evidence_rejects_non_image(client, monkeypatch):
    challenge_id = uuid4()
    participant = {
        "user_id": MOCK_USER["id"],
        "paid": True,
        "outcome": "pending",
    }
    monkeypatch.setattr(
        challenge_pages,
        "get_challenge_by_id",
        lambda challenge_id: _challenge(challenge_id, participant),
    )
    monkeypatch.setattr(challenge_pages, "get_my_evidence", lambda *args: [])
    monkeypatch.setattr(
        challenge_pages,
        "save_evidence",
        _reject_non_image,
    )

    response = client.post(
        f"/challenges/{challenge_id}/evidence",
        files={"photo": ("not-image.jpg", b"not an image", "image/jpeg")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/challenges/{challenge_id}?proof_error=not_image"
    )


def test_upload_evidence_success_redirects_as_uploaded(client, monkeypatch):
    challenge_id = uuid4()
    participant = {
        "user_id": MOCK_USER["id"],
        "paid": True,
        "outcome": "pending",
    }
    jpeg = b"converted-jpeg"
    monkeypatch.setattr(
        challenge_pages,
        "get_challenge_by_id",
        lambda challenge_id: _challenge(challenge_id, participant),
    )
    monkeypatch.setattr(challenge_pages, "get_my_evidence", lambda *args: [])
    monkeypatch.setattr(
        challenge_pages,
        "save_evidence",
        lambda *args, **kwargs: ({"id": "evidence-1", "attempt": 1}, jpeg),
    )
    monkeypatch.setattr(challenge_pages, "judge", lambda *args: (object(), "test-model"))
    monkeypatch.setattr(challenge_pages, "save_verdict", lambda *args: {})
    monkeypatch.setattr(challenge_pages, "decide", lambda verdict: "auto_approved")
    mock_set_status = Mock()
    monkeypatch.setattr(challenge_pages, "set_status", mock_set_status)
    mock_mark_verified = Mock()
    monkeypatch.setattr(challenge_pages, "mark_verified", mock_mark_verified)

    response = client.post(
        f"/challenges/{challenge_id}/evidence",
        files={"photo": ("proof.jpg", b"image-data", "image/jpeg")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/challenges/{challenge_id}?proof=auto_approved"
    )
    mock_set_status.assert_called_once_with("evidence-1", "auto_approved")
    mock_mark_verified.assert_called_once_with(str(challenge_id), MOCK_USER["id"])
