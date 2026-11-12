from types import SimpleNamespace
from copy import deepcopy
import pytest
from uuid import uuid4
from fastapi import HTTPException

from app.services import settlement_service


class FakeTable:
    def __init__(self, data=None):
        self.rows = deepcopy(data) if data is not None else []
        self._filters = []
        self._is_single = False
        self._pending_update = None
        self.upserted_rows = []

    def select(self, *args, **kwargs):
        return self

    def eq(self, field, value):
        self._filters.append((field, value, "eq"))
        return self

    def in_(self, field, values):
        self._filters.append((field, values, "in"))
        return self

    def maybe_single(self):
        self._is_single = True
        return self

    def single(self):
        self._is_single = True
        return self

    def _matches(self, row):
        for f in self._filters:
            field, val, op = f
            if op == "in":
                if row.get(field) not in val:
                    return False
            elif op == "eq":
                if row.get(field) != val:
                    return False
        return True

    def update(self, payload):
        self._pending_update = payload
        return self

    def upsert(self, payload, on_conflict=None):
        rows_to_add = payload if isinstance(payload, list) else [payload]
        for r in rows_to_add:
            self.upserted_rows.append(deepcopy(r))
            found = False
            for rx in self.rows:
                if rx.get("user_id") == r.get("user_id") and rx.get("challenge_id") == r.get("challenge_id"):
                    rx.update(r)
                    if "id" not in rx:
                        rx["id"] = str(uuid4())
                    found = True
                    break
            if not found:
                item = deepcopy(r)
                if "id" not in item:
                    item["id"] = str(uuid4())
                self.rows.append(item)
        return self

    def execute(self):
        matching = [r for r in self.rows if self._matches(r)]

        if self._pending_update is not None:
            updated = []
            for r in matching:
                r.update(self._pending_update)
                updated.append(deepcopy(r))
            self._pending_update = None
            self._filters = []
            return SimpleNamespace(data=updated)

        matched = [deepcopy(r) for r in matching]
        self._filters = []
        if self._is_single:
            self._is_single = False
            return SimpleNamespace(data=matched[0] if matched else None)
        return SimpleNamespace(data=matched)


class FakeDB:
    def __init__(self, challenges=None, participants=None, evidence=None, payouts=None):
        self.tables = {
            "challenges": FakeTable(challenges),
            "participants": FakeTable(participants),
            "evidence": FakeTable(evidence),
            "payouts": FakeTable(payouts),
        }

    def table(self, name: str):
        if name not in self.tables:
            raise ValueError(f"Table {name} not found")
        return self.tables[name]


def test_nonexistent_challenge(monkeypatch):
    fake_db = FakeDB(challenges=[])
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    with pytest.raises(HTTPException) as exc_info:
        settlement_service.settle(uuid4())
    assert exc_info.value.status_code == 404


def test_challenge_wrong_status(monkeypatch):
    for wrong_status in ("draft", "cancelled", "settling"):
        ch_id = str(uuid4())
        fake_db = FakeDB(challenges=[{"id": ch_id, "status": wrong_status, "entry_fee_minor": 1000}])
        monkeypatch.setattr(settlement_service, "supabase", fake_db)

        with pytest.raises(HTTPException) as exc_info:
            settlement_service.settle(ch_id)
        assert exc_info.value.status_code == 409


def test_no_paid_participants_marks_settled(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [{"challenge_id": ch_id, "user_id": "user-1", "paid": False, "outcome": "pending"}]
    fake_db = FakeDB(challenges=challenges, participants=participants)
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    result = settlement_service.settle(ch_id)
    assert result == {"settled": True, "payouts": 0}
    assert fake_db.tables["challenges"].rows[0]["status"] == "settled"


def test_unresolved_participants_before_close_rejected(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "voting", "entry_fee_minor": 1000}]
    participants = [{"challenge_id": ch_id, "user_id": "user-1", "paid": True, "outcome": "pending"}]
    fake_db = FakeDB(challenges=challenges, participants=participants)
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    with pytest.raises(HTTPException) as exc_info:
        settlement_service.settle(ch_id)
    assert exc_info.value.status_code == 409


def test_concurrent_settlement_rejected_if_already_settling(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [{"challenge_id": ch_id, "user_id": "user-1", "paid": True, "outcome": "verified"}]
    fake_db = FakeDB(challenges=challenges, participants=participants)
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    orig_execute = fake_db.tables["challenges"].execute
    def mock_execute():
        if fake_db.tables["challenges"]._pending_update == {"status": "settling"}:
            fake_db.tables["challenges"]._pending_update = None
            fake_db.tables["challenges"]._filters = []
            return SimpleNamespace(data=[])
        return orig_execute()
    fake_db.tables["challenges"].execute = mock_execute

    with pytest.raises(HTTPException) as exc_info:
        settlement_service.settle(ch_id)
    assert exc_info.value.status_code == 409


def test_unresolved_evidence_refunds_all_as_forfeited(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [
        {"challenge_id": ch_id, "user_id": "u1", "paid": True, "outcome": "verified", "profiles": {"paypal_email": "u1@test.com"}},
        {"challenge_id": ch_id, "user_id": "u2", "paid": True, "outcome": "pending", "profiles": {"paypal_email": "u2@test.com"}},
    ]
    evidence = [{"id": "ev-1", "challenge_id": ch_id, "status": "needs_vote"}]
    fake_db = FakeDB(challenges=challenges, participants=participants, evidence=evidence)
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    monkeypatch.setattr(
        settlement_service,
        "create_paypal_batch",
        lambda cid, items: {"batch_header": {"payout_batch_id": "BATCH-REFUND"}}
    )

    result = settlement_service.settle(ch_id)
    assert result["status"] == "settling"
    for p in fake_db.tables["participants"].rows:
        assert p["outcome"] == "forfeited"


def test_pending_participants_marked_forfeited_after_deadline(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [
        {"challenge_id": ch_id, "user_id": "u1", "paid": True, "outcome": "verified", "profiles": {"paypal_email": "u1@test.com"}},
        {"challenge_id": ch_id, "user_id": "u2", "paid": True, "outcome": "pending", "profiles": {"paypal_email": "u2@test.com"}},
    ]
    fake_db = FakeDB(challenges=challenges, participants=participants, evidence=[])
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    monkeypatch.setattr(
        settlement_service,
        "create_paypal_batch",
        lambda cid, items: {"batch_header": {"payout_batch_id": "BATCH-1"}}
    )

    result = settlement_service.settle(ch_id)
    assert result["status"] == "settling"
    u2 = next(p for p in fake_db.tables["participants"].rows if p["user_id"] == "u2")
    assert u2["outcome"] == "forfeited"


def test_settle_success_and_saves_payouts(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [
        {"challenge_id": ch_id, "user_id": "u1", "paid": True, "outcome": "verified", "profiles": {"paypal_email": "u1@test.com"}},
        {"challenge_id": ch_id, "user_id": "u2", "paid": True, "outcome": "forfeited", "profiles": {"paypal_email": "u2@test.com"}},
    ]
    fake_db = FakeDB(challenges=challenges, participants=participants, evidence=[], payouts=[])
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    sent_batch = {}
    def mock_create_batch(cid, items):
        sent_batch["cid"] = cid
        sent_batch["items"] = items
        return {"batch_header": {"payout_batch_id": "BATCH-OK"}}

    monkeypatch.setattr(settlement_service, "create_paypal_batch", mock_create_batch)

    result = settlement_service.settle(ch_id)
    assert result["status"] == "settling"
    assert result["paypal_batch_id"] == "BATCH-OK"
    assert len(fake_db.tables["payouts"].upserted_rows) == 1
    assert fake_db.tables["payouts"].upserted_rows[0]["user_id"] == "u1"
    assert fake_db.tables["payouts"].upserted_rows[0]["amount_minor"] == 2000


def test_already_paid_participants_are_not_paid_twice(monkeypatch):
    ch_id = str(uuid4())
    challenges = [{"id": ch_id, "status": "closed", "entry_fee_minor": 1000}]
    participants = [
        {"challenge_id": ch_id, "user_id": "u1", "paid": True, "outcome": "verified", "profiles": {"paypal_email": "u1@test.com"}},
    ]
    existing_payouts = [{"id": "p-1", "challenge_id": ch_id, "user_id": "u1", "status": "success", "amount_minor": 1000}]
    fake_db = FakeDB(challenges=challenges, participants=participants, evidence=[], payouts=existing_payouts)
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    result = settlement_service.settle(ch_id)
    assert result == {"settled": True, "payouts": 0}
    assert fake_db.tables["challenges"].rows[0]["status"] == "settled"


def test_paypal_failure_restores_challenge_status(monkeypatch):
    ch_id = str(uuid4())
    original_status = "closed"
    challenges = [{"id": ch_id, "status": original_status, "entry_fee_minor": 1000}]
    participants = [
        {"challenge_id": ch_id, "user_id": "u1", "paid": True, "outcome": "verified", "profiles": {"paypal_email": "u1@test.com"}},
    ]
    fake_db = FakeDB(challenges=challenges, participants=participants, evidence=[], payouts=[])
    monkeypatch.setattr(settlement_service, "supabase", fake_db)

    def mock_fail_batch(cid, items):
        raise RuntimeError("PayPal network timeout")

    monkeypatch.setattr(settlement_service, "create_paypal_batch", mock_fail_batch)

    with pytest.raises(HTTPException) as exc_info:
        settlement_service.settle(ch_id)

    assert exc_info.value.status_code == 502
    assert "Paypal Payouts failed" in exc_info.value.detail
    assert fake_db.tables["challenges"].rows[0]["status"] == original_status