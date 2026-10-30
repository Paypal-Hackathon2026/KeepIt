from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from app.deps import current_user
from app.services.payment_service import cancel_payment, complete_payment

router = APIRouter(tags=["paypal"])
@router.get("/paypal/return")
def paypal_return(token: str, user: dict = Depends(current_user)):
    """Handle PayPal return after payment approval."""
    payment = complete_payment(paypal_order_id=token, user_id=user["id"])
    return RedirectResponse(
        url=f"/challenges/{payment['challenge_id']}?payment=success",
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
        url=f"/challenges/{payment['challenge_id']}?payment={message}",
        status_code=303,
    )
