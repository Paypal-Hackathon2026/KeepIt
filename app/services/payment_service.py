from fastapi import HTTPException
from app.db import supabase
from app.services.paypal import capture_order, create_order
from datetime import datetime, timezone
import httpx


def join_challenge(challenge_id: str, user_id: str) -> dict:
    challenge_response = (
    supabase.table("challenges")
    .select("id, entry_fee_minor, status, join_deadline")
    .eq("id", challenge_id)
    .single()
    .execute()
    )
    if not challenge_response.data:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge_response.data["status"] != "open":
        raise HTTPException(status_code=409, detail="Challenge is not open")
    if datetime.fromisoformat(
        challenge_response.data["join_deadline"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=409,
            detail="Joining deadline has passed",
        )
    participant_response = (
    supabase.table("participants")
    .select("challenge_id,user_id,paid")
    .eq("challenge_id", challenge_id)
    .eq("user_id", user_id)
    .maybe_single()
    .execute()
    )
    if participant_response.data:
        participant = participant_response.data
    else:
        insert_response = (
        supabase.table("participants")
        .insert({"challenge_id": challenge_id, "user_id": user_id, "paid": False})
            .execute()
        )
        participant = insert_response.data[0]
    if participant["paid"]:
        raise HTTPException(
            status_code=409,
            detail="User has already joined the challenge and paid",
        )
    payments_response = (
    supabase.table("payments")
    .select(
        "id, amount_minor, paypal_order_id, status"
    )
    .eq("challenge_id", challenge_id)
    .eq("user_id", user_id)
    .in_("status", ["created", "captured"])
    .execute()
    )
    for payment in payments_response.data or []:
        if payment["status"]=="captured":
            raise HTTPException(
                status_code=409,
                detail="User has already joined the challenge and paid",
            )
        if payment["status"]=="created":
            raise HTTPException(
                status_code=409,
                detail=f"A payment is already in progress",)

    try:
        order = create_order(
            challenge_id=challenge_id,
            user_id=user_id,
            entry_fee_minor=challenge_response.data["entry_fee_minor"],
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="PayPal order creation failed",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="PayPal is unavailable",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="PayPal returned an invalid response",
        ) from exc
    approve_url = order["approve_url"]
    paypal_order_id = order["paypal_order_id"]
    payment_response=(
        supabase.table("payments")
        .insert({
            "challenge_id": challenge_id,
            "user_id": user_id,
            "amount_minor": challenge_response.data["entry_fee_minor"],
            "paypal_order_id": paypal_order_id,
            "status": "created",
        })
        .execute()
    )
    payment=payment_response.data[0]
    return {
        "payment_id": payment["id"],
        "paypal_order_id": payment["paypal_order_id"],
        "approve_url":    approve_url,
        "amount_minor": payment["amount_minor"],
        "status": payment["status"],
    }


def _mark_participant_paid(payment: dict) -> dict:
    participant_update = (
        supabase.table("participants")
        .update({"paid": True})
        .eq("challenge_id", payment["challenge_id"])
        .eq("user_id", payment["user_id"])
        .execute()
    )
    if not participant_update.data:
        raise RuntimeError("Participant was not marked as paid")
    return payment


def complete_payment(paypal_order_id: str, user_id: str) -> dict:
    payment_response = (
        supabase.table("payments")
        .select("id, challenge_id, user_id, amount_minor, paypal_order_id, status")
        .eq("paypal_order_id", paypal_order_id)
        .single()
        .execute()
    )
    if not payment_response.data:
        raise HTTPException(status_code=404, detail="Payment not found")
    payment = payment_response.data
    if payment["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="Payment was cancelled")
    if payment["status"] == "captured":
        return _mark_participant_paid(payment)

    capture_id = capture_order(paypal_order_id)["capture_id"]
    if not capture_id:
        raise HTTPException(status_code=500, detail="Failed to capture payment")

    payment_update = (
        supabase.table("payments")
        .update({
            "status": "captured",
            "paypal_capture_id": capture_id,
        })
        .eq("id", payment["id"])
        .eq("status", "created")
        .execute()
    )
    if not payment_update.data:
        current_payment_response = (
            supabase.table("payments")
            .select(
                "id, challenge_id, user_id, amount_minor, "
                "paypal_order_id, status"
            )
            .eq("paypal_order_id", paypal_order_id)
            .single()
            .execute()
        )
        if not current_payment_response.data:
            raise HTTPException(status_code=404, detail="Payment not found")
        payment = current_payment_response.data
        if payment["status"] == "captured":
            return _mark_participant_paid(payment)
        if payment["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="Payment was cancelled")
        raise HTTPException(status_code=409, detail="Payment update failed")

    payment["status"] = "captured"
    payment["paypal_capture_id"] = capture_id
    return _mark_participant_paid(payment)


def cancel_payment(paypal_order_id: str, user_id: str) -> dict:
    payment_response = (
        supabase.table("payments")
        .select("id, challenge_id, user_id, status")
        .eq("paypal_order_id", paypal_order_id)
        .single()
        .execute()
    )
    if not payment_response.data:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment = payment_response.data
    if payment["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment["status"] == "created":
        update_response = (
            supabase.table("payments")
            .update({"status": "cancelled"})
            .eq("id", payment["id"])
            .eq("status", "created")
            .execute()
        )
        if update_response.data:
            payment["status"] = "cancelled"
        else:
            current_payment_response = (
                supabase.table("payments")
                .select("id, challenge_id, user_id, status")
                .eq("id", payment["id"])
                .single()
                .execute()
            )
            if not current_payment_response.data:
                raise HTTPException(status_code=404, detail="Payment not found")
            payment = current_payment_response.data

    return payment
