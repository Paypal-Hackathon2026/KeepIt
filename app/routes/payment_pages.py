from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import current_user
from app.services.challenge_service import get_challenge_by_id
from app.services.payment_service import join_challenge
from app.templating import templates

router = APIRouter()


@router.post("/challenges/{challenge_id}/pay")
def pay_for_challenge(
    challenge_id: UUID,
    user: Annotated[dict, Depends(current_user)],
):
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if challenge.get("status") != "open":
        raise HTTPException(status_code=400, detail="Joining this challenge is closed (join deadline has passed)")

    result = join_challenge(challenge_id=str(challenge_id), user_id=str(user["id"]))
    return RedirectResponse(url=result["approve_url"], status_code=303)


@router.get("/challenges/{challenge_id}/payment/success")
def payment_success(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    return templates.TemplateResponse(
        request,
        "payment_success.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        },
    )


@router.get("/challenges/{challenge_id}/payment/cancelled")
def payment_cancel(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    return templates.TemplateResponse(
        request,
        "payment_cancel.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        },
    )


@router.get("/challenges/{challenge_id}/payment/already_completed")
def payment_already_completed(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    return templates.TemplateResponse(
        request,
        "payment_already_completed.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        },
    )
