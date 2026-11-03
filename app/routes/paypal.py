import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.db import supabase
from app.deps import current_user
from app.services.payment_service import cancel_payment, complete_payment
from app.services.paypal import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(tags=["paypal"])


def save_webhook_event_if_new(event: dict) -> bool:
    event_id = event.get("id")
    if not event_id:
        return False

    try:
        existing = (
            supabase.table("webhook_events")
            .select("event_id")
            .eq("event_id", event_id)
            .maybe_single()
            .execute()
        )
        if existing and existing.data:
            return False

        supabase.table("webhook_events").insert({
            "event_id": event_id,
            "event_type": event.get("event_type") or event.get("type") or "unknown",
            "payload": event,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as exc:
        err_msg = str(exc).lower()
        if "duplicate" in err_msg or "unique" in err_msg or "23505" in err_msg:
            return False
        raise


def handle_payment_capture_completed(resource: dict) -> dict:
    if not isinstance(resource, dict):
        resource = {}
    capture_id = resource.get("id")
    supp_data = resource.get("supplementary_data") or {}
    related_ids = supp_data.get("related_ids") or {}
    order_id = related_ids.get("order_id")
    custom_id = resource.get("custom_id")

    payment_response = None
    if capture_id:
        payment_response = (
            supabase.table("payments")
            .select("id, challenge_id, user_id, status, paypal_order_id, paypal_capture_id")
            .eq("paypal_capture_id", capture_id)
            .limit(1)
            .execute()
        )

    if not payment_response or not payment_response.data:
        if order_id:
            payment_response = (
                supabase.table("payments")
                .select("id, challenge_id, user_id, status, paypal_order_id, paypal_capture_id")
                .eq("paypal_order_id", order_id)
                .limit(1)
                .execute()
            )

    if not payment_response or not payment_response.data:
        if custom_id and ":" in custom_id:
            challenge_id, user_id = custom_id.split(":", 1)
            payment_response = (
                supabase.table("payments")
                .select("id, challenge_id, user_id, status, paypal_order_id, paypal_capture_id")
                .eq("challenge_id", challenge_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )

    if not payment_response or not payment_response.data:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment = payment_response.data[0]
    if payment.get("status") == "captured":
        return payment

    update_payload = {"status": "captured"}
    if capture_id:
        update_payload["paypal_capture_id"] = capture_id

    payment_update = (
        supabase.table("payments")
        .update(update_payload)
        .eq("id", payment["id"])
        .execute()
    )
    if payment_update and payment_update.data:
        payment = payment_update.data[0]
    else:
        payment["status"] = "captured"
        if capture_id:
            payment["paypal_capture_id"] = capture_id

    participant_update = (
        supabase.table("participants")
        .update({"paid": True})
        .eq("challenge_id", payment["challenge_id"])
        .eq("user_id", payment["user_id"])
        .execute()
    )
    if not participant_update or not participant_update.data:
        raise RuntimeError("Participant was not marked as paid")

    return payment


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request):
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        return JSONResponse({"detail": "Invalid webhook payload"}, status_code=400)

    if not isinstance(payload, dict) or not payload.get("id"):
        return JSONResponse({"detail": "Missing webhook event id"}, status_code=400)

    if not verify_webhook_signature(raw_body, dict(request.headers)):
        return JSONResponse({"detail": "Invalid webhook signature"}, status_code=400)

    try:
        if not save_webhook_event_if_new(payload):
            return JSONResponse({"status": "duplicate"}, status_code=200)

        event_type = payload.get("event_type") or payload.get("type")
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            handle_payment_capture_completed(payload.get("resource") or {})
            return JSONResponse({"status": "processed"}, status_code=200)

        return JSONResponse({"status": "ignored"}, status_code=200)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error handling webhook event: %s", exc)
        return JSONResponse({"detail": f"Internal error processing webhook: {exc}"}, status_code=500)


@router.get("/paypal/return")
def paypal_return(token: str, user: dict = Depends(current_user)):
    """Handle PayPal return after payment approval."""
    payment = complete_payment(paypal_order_id=token, user_id=user["id"])
    return RedirectResponse(
        url=f"/challenges/{payment['challenge_id']}/payment/success",
        status_code=303,
    )


@router.get("/paypal/cancel")
def paypal_cancel(token: str, user: dict = Depends(current_user)):
    """Handle PayPal payment cancellation."""
    payment = cancel_payment(paypal_order_id=token, user_id=user["id"])
    message = (
        "already_completed"
        if payment["status"] == "captured"
        else "cancelled"
    )
    return RedirectResponse(
        url=f"/challenges/{payment['challenge_id']}/payment/{message}",
        status_code=303,
    )
