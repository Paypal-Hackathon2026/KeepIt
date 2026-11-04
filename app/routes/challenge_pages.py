from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, File, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from PIL import Image, UnidentifiedImageError

from app.deps import current_user
from app.models.challenge import ChallengeCreate
from app.services.challenge_service import (
    create_challenge,
    get_challenge_by_id,
    get_user_challenges,
)
from app.templating import templates
from app.services.payment_service import join_challenge
from app.services.evidence import save_evidence

MAX_UPLOAD_BYTES = 15 * 1024 * 1024

router = APIRouter()

@router.get("/challenges/new")
def new_challenge_page(request: Request, user: dict = Depends(current_user)):
    return templates.TemplateResponse(request, "new_challenge.html",
                                       {"user": user, "errors": {}, "values": {}})
@router.post("/challenges/new")
def created_challenge(request: Request,
                      title: str = Form(""),
                      criteria: str = Form(""),
                      entry_fee_pln: str = Form(""),
                      join_deadline: str = Form(""),
                      proof_deadline: str = Form(""),
                      user: dict = Depends(current_user)):
    values = {
        "title": title,
        "criteria": criteria,
        "entry_fee_pln": entry_fee_pln,
        "join_deadline": join_deadline,
        "proof_deadline": proof_deadline
    }

    try:
        challenge_data = ChallengeCreate(title=title, criteria=criteria, entry_fee_pln=entry_fee_pln, join_deadline=join_deadline, proof_deadline=proof_deadline)
    except ValidationError as e:
        errors={}
        for error in e.errors():
            loc=error["loc"]
            msg=error["msg"]
            if msg.startswith("Value error, "):
                msg=msg.replace("Value error, ", "")
            if loc:
                field_name=str(loc[0])
                errors[field_name]=msg
            else:
                errors["proof_deadline"]=msg
        return templates.TemplateResponse(request, "new_challenge.html",
                                             {"user": user, "errors": errors, "values": values},
                                             status_code=422,)
    new_challenge = create_challenge(challenge_data,creator_id=user["id"])
    return RedirectResponse(url=f"/challenges/{new_challenge['id']}", status_code=303)
    

def _format_deadline(value) -> str:
    """
    Turn an ISO datetime string or datetime object into a readable string.
    """
    if not value:
        return ""
    s = str(value).replace("T", " ")
    return s[:16]

@router.get("/challenges")
def my_challenges_page(request: Request, user: Annotated[dict, Depends(current_user)]):
    
    challenges = get_user_challenges(user_id=user["id"])
    
    for c in challenges:
        c["join_deadline_fmt"] = _format_deadline(c.get("join_deadline"))
        c["proof_deadline_fmt"] = _format_deadline(c.get("proof_deadline"))

    return templates.TemplateResponse(
        request,
        "challenges.html",
        {"user": user, "challenges": challenges},
    )


@router.get("/challenges/{challenge_id}")
def challenge_detail_page(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    
    challenge = get_challenge_by_id(challenge_id)
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    challenge["join_deadline_fmt"] = _format_deadline(challenge.get("join_deadline"))
    challenge["proof_deadline_fmt"] = _format_deadline(challenge.get("proof_deadline"))

    participants = challenge.get("participants", [])
    my_participant = next(
        (p for p in participants if str(p.get("user_id")) == str(user["id"])),
        None,
    )
    has_paid = bool(my_participant and my_participant.get("paid"))

    return templates.TemplateResponse(
        request,
        "challenge_detail.html",
        {
            "user": user,
            "challenge": challenge,
            "has_paid": has_paid,
            "is_participant": my_participant is not None,
        },
    )
@router.post("/challenges/{challenge_id}/pay")
def pay_for_challenge(
    challenge_id: UUID,
    user: dict = Depends(current_user),
):
    result = join_challenge(challenge_id=str(challenge_id), user_id=str(user["id"]))
    return RedirectResponse(url=result["approve_url"], status_code=303)

@router.get("/challenges/{challenge_id}/payment/success")
def payment_success(
    challenge_id: UUID,
    request: Request,
    user: dict = Depends(current_user)):
    return templates.TemplateResponse(
        request,
        "payment_success.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        })
@router.get("/challenges/{challenge_id}/payment/cancelled")
def payment_cancel(
    challenge_id:UUID,
    request: Request,
    user: dict = Depends(current_user)):
    return templates.TemplateResponse(
        request,
        "payment_cancel.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        })
@router.get("/challenges/{challenge_id}/payment/already_completed")
def payment_already_completed(
    challenge_id:UUID,
    request: Request,
    user: dict = Depends(current_user)):
    return templates.TemplateResponse(
        request,
        "payment_already_completed.html",
        {
            "user": user,
            "challenge_id": challenge_id,
        })
    
@router.post("/challenges/{challenge_id}/evidence")
def upload_evidence(
    challenge_id: UUID,
    photo: UploadFile = File(...),
    user: dict = Depends(current_user),
):
    back = f"/challenges/{challenge_id}"

    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    me = next(
        (p for p in challenge.get("participants", [])
         if str(p.get("user_id")) == str(user["id"])),
        None,
    )
    if not me or not me.get("paid"):
        raise HTTPException(status_code=403, detail="Only paid participants can upload proof")

    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return RedirectResponse(f"{back}?proof_error=too_big", status_code=303)

    try:
        save_evidence(str(challenge_id), str(user["id"]), data)
    except ValueError:
        return RedirectResponse(f"{back}?proof_error=no_attempts", status_code=303)
    except (UnidentifiedImageError, Image.DecompressionBombError):
        return RedirectResponse(f"{back}?proof_error=not_image", status_code=303)

    return RedirectResponse(f"{back}?proof=uploaded", status_code=303)