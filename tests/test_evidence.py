from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import evidence


def test_save_evidence_stores_attempt_number_and_storage_path(monkeypatch):
    challenge_id = "challenge-1"
    user_id = "user-1"
    evidence_row = {
        "id": "evidence-1",
        "challenge_id": challenge_id,
        "user_id": user_id,
        "attempt": 3,
        "storage_path": f"{challenge_id}/{user_id}/3.jpg",
        "status": "pending",
    }
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": "evidence-1"}, {"id": "evidence-2"}])
    )
    mock_supabase.table.return_value.insert.return_value.execute.return_value = (
        SimpleNamespace(data=[evidence_row])
    )
    monkeypatch.setattr(evidence, "supabase", mock_supabase)
    monkeypatch.setattr(evidence, "to_jpeg", lambda photo: b"jpeg-data")

    result, jpeg = evidence.save_evidence(
        challenge_id,
        user_id,
        b"source-image",
        max_attempts=3,
    )

    assert result == evidence_row
    assert jpeg == b"jpeg-data"
    mock_supabase.storage.from_.assert_called_once_with("evidence")
    mock_supabase.storage.from_.return_value.upload.assert_called_once_with(
        f"{challenge_id}/{user_id}/3.jpg",
        b"jpeg-data",
        {"content-type": "image/jpeg", "upsert": "true"},
    )
    mock_supabase.table.return_value.insert.assert_called_once_with(
        {
            "challenge_id": challenge_id,
            "user_id": user_id,
            "attempt": 3,
            "storage_path": f"{challenge_id}/{user_id}/3.jpg",
            "status": "pending",
        }
    )


def test_save_evidence_rejects_fourth_attempt(monkeypatch):
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[{"id": f"evidence-{attempt}"} for attempt in range(1, 4)])
    )
    monkeypatch.setattr(evidence, "supabase", mock_supabase)
    monkeypatch.setattr(
        evidence,
        "to_jpeg",
        lambda photo: pytest.fail("Image conversion should not run after the attempt limit"),
    )

    with pytest.raises(ValueError, match="already used all 3 attempts"):
        evidence.save_evidence(
            "challenge-1",
            "user-1",
            b"source-image",
            max_attempts=3,
        )

    mock_supabase.storage.from_.return_value.upload.assert_not_called()
    mock_supabase.table.return_value.insert.assert_not_called()
