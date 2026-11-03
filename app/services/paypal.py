import json
import logging
import time
from decimal import Decimal
from threading import Lock

import httpx

from app import config

logger = logging.getLogger(__name__)


_access_token: str | None = None
_access_token_expires_at: float = 0
_token_lock = Lock()


def get_access_token() -> str:
    global _access_token, _access_token_expires_at

    with _token_lock:
        if _access_token and time.time() < _access_token_expires_at - 60:
            return _access_token

        response = httpx.post(
            f"{config.PAYPAL_API_BASE}/v1/oauth2/token",
            auth=(config.PAYPAL_CLIENT_ID, config.PAYPAL_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
        response.raise_for_status()
        response_json = response.json()

        try:
            access_token = response_json["access_token"]
            expires_in = response_json["expires_in"]
        except KeyError as exc:
            raise RuntimeError(
                "Incomplete PayPal access token response"
            ) from exc

        _access_token = access_token
        _access_token_expires_at = time.time() + expires_in
        return _access_token



def create_order(challenge_id: str, user_id: str, entry_fee_minor: int) -> dict:
    access_token = get_access_token()
    amount = Decimal(entry_fee_minor) / Decimal("100")
    amount_string = f"{amount:.2f}"
    response = httpx.post(
        f"{config.PAYPAL_API_BASE}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": f"challenge-{challenge_id}-user-{user_id}",
                    "custom_id": f"{challenge_id}:{user_id}",
                    "amount": {
                        "currency_code": "PLN",
                        "value": amount_string
                    }
                }
            ],
            "application_context": {
                "return_url": f"{config.APP_URL}/paypal/return",
                "cancel_url": f"{config.APP_URL}/paypal/cancel",
                "user_action": "PAY_NOW"
            }
        },
        timeout=10
    )
    response.raise_for_status()
    resp = response.json()
    links = resp.get("links", [])
    for link in links:
        if link["rel"] == "approve":
            return {"approve_url": link["href"], "paypal_order_id": resp["id"]}    
    raise RuntimeError("No approve link found in PayPal order response")


def capture_order(order_id: str) -> dict:
    access_token = get_access_token()

    response = httpx.post(
        f"{config.PAYPAL_API_BASE}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    response.raise_for_status()
    response_json = response.json()

    if response_json.get("status") != "COMPLETED":
        raise RuntimeError(
            f"PayPal order not completed: {response_json.get('status')}"
        )

    try:
        capture = response_json["purchase_units"][0]["payments"]["captures"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("No capture found in PayPal order response") from exc

    if capture.get("status") != "COMPLETED":
        raise RuntimeError(
            f"PayPal capture not completed: {capture.get('status')}"
        )

    capture_id = capture.get("id")
    if not capture_id:
        raise RuntimeError("PayPal capture ID missing")

    return {"capture_id": capture_id, "response": response_json}


def verify_webhook_signature(raw_body: bytes, headers: dict) -> bool:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        return False

    normalized_headers = {str(k).lower(): v for k, v in headers.items()}
    auth_algo = normalized_headers.get("paypal-auth-algo")
    cert_url = normalized_headers.get("paypal-cert-url")
    transmission_id = normalized_headers.get("paypal-transmission-id")
    transmission_sig = normalized_headers.get("paypal-transmission-sig")
    transmission_time = normalized_headers.get("paypal-transmission-time")

    if not all([auth_algo, cert_url, transmission_id, transmission_sig, transmission_time]):
        return False

    webhook_id = getattr(config, "PAYPAL_WEBHOOK_ID", None)
    if not webhook_id:
        logger.error("PAYPAL_WEBHOOK_ID is not configured")
        return False

    verification_request = {
        "auth_algo": auth_algo,
        "cert_url": cert_url,
        "transmission_id": transmission_id,
        "transmission_sig": transmission_sig,
        "transmission_time": transmission_time,
        "webhook_id": webhook_id,
        "webhook_event": payload,
    }
    try:
        response = httpx.post(
            f"{config.PAYPAL_API_BASE}/v1/notifications/verify-webhook-signature",
            headers={
                "Authorization": f"Bearer {get_access_token()}",
                "Content-Type": "application/json",
            },
            json=verification_request,
            timeout=10,
        )
        if response.status_code >= 400:
            return False
        return response.json().get("verification_status") == "SUCCESS"
    except Exception as exc:
        logger.warning("Error verifying PayPal webhook signature: %s", exc)
        return False
