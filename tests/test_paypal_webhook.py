import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.routes import paypal as paypal_routes
from app.services import paypal as paypal_services


class FakePaymentsTable:
    def __init__(self, payment=None):
        self.payment = payment
        self.update_payload = None
        self.filter_field = None
        self.filter_val = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, field, val):
        self.filter_field = field
        self.filter_val = val
        return self

    def in_(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.update_payload = payload
        if self.payment:
            self.payment.update(payload)
        return self

    def execute(self):
        if self.payment is None:
            return SimpleNamespace(data=[])
        if self.filter_field and self.filter_val:
            # Check if match
            if self.payment.get(self.filter_field) != self.filter_val:
                return SimpleNamespace(data=[])
        return SimpleNamespace(data=[self.payment])


class FakeParticipantsTable:
    def __init__(self):
        self.update_payload = None
        self.updated = False

    def update(self, payload):
        self.update_payload = payload
        self.updated = True
        return self

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[{"challenge_id": "challenge-1", "user_id": "user-1", "paid": True}])


class FakeWebhookEventsTable:
    def __init__(self):
        self.saved = []
        self.existing = set()
        self.lookup_event_id = None

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        self.lookup_event_id = args[1]
        return self

    def maybe_single(self):
        return self

    def insert(self, payload):
        self.saved.append(payload)
        self.existing.add(payload["event_id"])
        return self

    def upsert(self, payload, on_conflict=None):
        self.saved.append(payload)
        self.existing.add(payload["event_id"])
        return self

    def execute(self):
        if self.lookup_event_id is not None:
            event_id = self.lookup_event_id
            self.lookup_event_id = None
            if event_id in self.existing:
                return SimpleNamespace(data={"event_id": event_id})
            return SimpleNamespace(data=None)
        return SimpleNamespace(data=self.saved)


class FakeSupabase:
    def __init__(self, payment=None):
        self.payments = FakePaymentsTable(payment)
        self.participants = FakeParticipantsTable()
        self.webhook_events = FakeWebhookEventsTable()

    def table(self, name):
        if name == "payments":
            return self.payments
        if name == "participants":
            return self.participants
        if name == "webhook_events":
            return self.webhook_events
        raise AssertionError(f"Unexpected table: {name}")


def test_handle_payment_capture_completed_marks_participant_paid(monkeypatch):
    payment = {
        "id": "payment-1",
        "challenge_id": "challenge-1",
        "user_id": "user-1",
        "status": "created",
        "paypal_order_id": "order-1",
        "paypal_capture_id": None,
    }
    fake_supabase = FakeSupabase(payment)
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)

    result = paypal_routes.handle_payment_capture_completed({
        "id": "capture-1",
        "supplementary_data": {"related_ids": {"order_id": "order-1"}},
        "custom_id": "challenge-1:user-1",
    })

    assert result["status"] == "captured"
    assert result["paypal_capture_id"] == "capture-1"
    assert fake_supabase.participants.updated is True
    assert fake_supabase.participants.update_payload == {"paid": True}


def test_handle_payment_capture_completed_already_captured_is_idempotent(monkeypatch):
    payment = {
        "id": "payment-1",
        "challenge_id": "challenge-1",
        "user_id": "user-1",
        "status": "captured",
        "paypal_order_id": "order-1",
        "paypal_capture_id": "capture-1",
    }
    fake_supabase = FakeSupabase(payment)
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)

    result = paypal_routes.handle_payment_capture_completed({
        "id": "capture-1",
        "supplementary_data": {"related_ids": {"order_id": "order-1"}},
    })

    assert result["status"] == "captured"
    assert fake_supabase.payments.update_payload is None
    assert fake_supabase.participants.updated is False


def test_handle_payment_capture_completed_matches_by_custom_id(monkeypatch):
    payment = {
        "id": "payment-2",
        "challenge_id": "challenge-2",
        "user_id": "user-2",
        "status": "created",
        "paypal_order_id": "order-2",
        "paypal_capture_id": None,
    }
    fake_supabase = FakeSupabase(payment)
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)

    result = paypal_routes.handle_payment_capture_completed({
        "id": "capture-2",
        "custom_id": "challenge-2:user-2",
    })

    assert result["status"] == "captured"
    assert result["paypal_capture_id"] == "capture-2"
    assert fake_supabase.participants.updated is True


def test_handle_payment_capture_completed_payment_not_found_raises_404(monkeypatch):
    fake_supabase = FakeSupabase(None)
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)

    with pytest.raises(HTTPException) as exc_info:
        paypal_routes.handle_payment_capture_completed({
            "id": "capture-nonexistent",
            "supplementary_data": {"related_ids": {"order_id": "order-nonexistent"}},
        })
    assert exc_info.value.status_code == 404


def test_save_webhook_event_if_new_ignores_duplicate_event_id(monkeypatch):
    fake_supabase = FakeSupabase({
        "id": "payment-1",
        "challenge_id": "challenge-1",
        "user_id": "user-1",
        "status": "created",
        "paypal_order_id": "order-1",
        "paypal_capture_id": None,
    })
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)

    first = paypal_routes.save_webhook_event_if_new({
        "id": "evt-123",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": "capture-1"},
    })
    second = paypal_routes.save_webhook_event_if_new({
        "id": "evt-123",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": "capture-1"},
    })

    assert first is True
    assert second is False


def test_verify_webhook_signature_missing_headers():
    raw_body = b'{"id": "evt-1"}'
    headers = {"paypal-auth-algo": "SHA256withRSA"}
    # Missing transmission_id, cert_url, transmission_sig, transmission_time
    assert paypal_services.verify_webhook_signature(raw_body, headers) is False


def test_verify_webhook_signature_success(monkeypatch):
    monkeypatch.setattr(paypal_services, "get_access_token", lambda: "mock-token")

    class MockResponse:
        status_code = 200

        def json(self):
            return {"verification_status": "SUCCESS"}

    monkeypatch.setattr(paypal_services.httpx, "post", lambda *args, **kwargs: MockResponse())

    raw_body = b'{"id": "evt-1"}'
    headers = {
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert.pem",
        "PAYPAL-TRANSMISSION-ID": "trans-1",
        "PAYPAL-TRANSMISSION-SIG": "sig-1",
        "PAYPAL-TRANSMISSION-TIME": "2026-11-03T12:00:00Z",
    }
    assert paypal_services.verify_webhook_signature(raw_body, headers) is True


def test_verify_webhook_signature_failure(monkeypatch):
    monkeypatch.setattr(paypal_services, "get_access_token", lambda: "mock-token")

    class MockResponse:
        status_code = 200

        def json(self):
            return {"verification_status": "FAILURE"}

    monkeypatch.setattr(paypal_services.httpx, "post", lambda *args, **kwargs: MockResponse())

    raw_body = b'{"id": "evt-1"}'
    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/cert.pem",
        "paypal-transmission-id": "trans-1",
        "paypal-transmission-sig": "sig-1",
        "paypal-transmission-time": "2026-11-03T12:00:00Z",
    }
    assert paypal_services.verify_webhook_signature(raw_body, headers) is False


def test_webhook_route_invalid_payload(monkeypatch):
    client = TestClient(app)
    response = client.post(
        "/paypal/webhook",
        content="not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook payload"}


def test_webhook_route_missing_id(monkeypatch):
    client = TestClient(app)
    response = client.post(
        "/paypal/webhook",
        json={"event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Missing webhook event id"}


def test_webhook_route_invalid_signature(monkeypatch):
    client = TestClient(app)
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)
    monkeypatch.setattr(paypal_routes, "verify_webhook_signature", lambda body, headers: False)

    response = client.post(
        "/paypal/webhook",
        json={"id": "evt-bad-sig", "event_type": "PAYMENT.CAPTURE.COMPLETED"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid webhook signature"}
    # Verify unverified event was not saved into DB
    assert len(fake_supabase.webhook_events.saved) == 0


def test_webhook_route_valid_capture_and_deduplication(monkeypatch):
    client = TestClient(app)
    payment = {
        "id": "payment-1",
        "challenge_id": "challenge-1",
        "user_id": "user-1",
        "status": "created",
        "paypal_order_id": "order-1",
        "paypal_capture_id": None,
    }
    fake_supabase = FakeSupabase(payment)
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)
    monkeypatch.setattr(paypal_routes, "verify_webhook_signature", lambda body, headers: True)

    payload = {
        "id": "evt-test-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "capture-1",
            "supplementary_data": {"related_ids": {"order_id": "order-1"}},
        },
    }

    # First delivery: processed
    resp1 = client.post("/paypal/webhook", json=payload)
    assert resp1.status_code == 200
    assert resp1.json() == {"status": "processed"}
    assert payment["status"] == "captured"
    assert payment["paypal_capture_id"] == "capture-1"
    assert fake_supabase.participants.updated is True
    assert len(fake_supabase.webhook_events.saved) == 1

    # Reset participant update flag to test idempotency
    fake_supabase.participants.updated = False
    fake_supabase.payments.update_payload = None

    # Redelivery of same event: duplicate, no db update
    resp2 = client.post("/paypal/webhook", json=payload)
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "duplicate"}
    assert fake_supabase.payments.update_payload is None
    assert fake_supabase.participants.updated is False
    assert len(fake_supabase.webhook_events.saved) == 1


def test_webhook_route_unhandled_event_type_ignored(monkeypatch):
    client = TestClient(app)
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(paypal_routes, "supabase", fake_supabase)
    monkeypatch.setattr(paypal_routes, "verify_webhook_signature", lambda body, headers: True)

    payload = {
        "id": "evt-other-1",
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {"id": "order-1"},
    }

    resp = client.post("/paypal/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
    assert len(fake_supabase.webhook_events.saved) == 1
