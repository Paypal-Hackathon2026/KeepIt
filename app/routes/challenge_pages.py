from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, File, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from PIL import Image, UnidentifiedImageError

from app.deps import current_user
from app.db import supabase
from app.models.challenge import ChallengeCreate
from app.services.challenge_service import (
    create_challenge,
    get_challenge_by_id,
    get_user_challenges,
)
from app.templating import templates
from app.services.payment_service import join_challenge
from app.services.evidence import (
    MAX_ATTEMPTS,
    get_my_evidence,
    get_pending_votes_for_user,
    get_voting_feed,
    cast_vote,
    save_evidence,
    send_to_vote,
    set_status,
    mark_verified,
    mark_forfeited
)
from app.services.arbiter import judge, save_verdict, decide
from app.services.settlement_service import settle

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PROOF_ERRORS = {
    "too_big": "Photo is too big (max 15 MB).",
    "not_image": "This file is not a photo. Try again.",
    "no_attempts": "You have already used all allowed attempts.",
    "closed": "You can't upload more photos for this challenge.",
}

router = APIRouter()

@router.get("/challenges/new")
def new_challenge_page(request: Request, user: dict = Depends(current_user)):
    return templates.TemplateResponse(request, "new_challenge.html",
                                       {"user": user, "errors": {}, "values": {"verification_mode": "ai", "voting_deadline": ""}})
@router.post("/challenges/new")
def created_challenge(request: Request,
                      title: str = Form(""),
                      criteria: str = Form(""),
                      entry_fee_pln: str = Form(""),
                      join_deadline: str = Form(""),
                      proof_deadline: str = Form(""),
                      voting_deadline: str = Form(""),
                      verification_mode: str = Form("ai"),
                      user: dict = Depends(current_user)):
    values = {
        "title": title,
        "criteria": criteria,
        "entry_fee_pln": entry_fee_pln,
        "join_deadline": join_deadline,
        "proof_deadline": proof_deadline,
        "voting_deadline": voting_deadline,
        "verification_mode": verification_mode,
    }

    try:
        create_kwargs = {
            "title": title,
            "criteria": criteria,
            "entry_fee_pln": entry_fee_pln,
            "join_deadline": join_deadline,
            "proof_deadline": proof_deadline,
            "verification_mode": verification_mode,
        }
        if voting_deadline:
            create_kwargs["voting_deadline"] = voting_deadline
        challenge_data = ChallengeCreate(**create_kwargs)
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
                errors["general"]=msg
        return templates.TemplateResponse(request, "new_challenge.html",
                                             {"user": user, "errors": errors, "values": values},
                                             status_code=422,)
    try:
        new_challenge = create_challenge(challenge_data, creator_id=user["id"])
    except HTTPException as e:
        return templates.TemplateResponse(
            request,
            "new_challenge.html",
            {"user": user, "errors": {"general": e.detail}, "values": values},
            status_code=500,
        )
    return RedirectResponse(url=f"/challenges/{new_challenge['id']}", status_code=303)
    

def _format_deadline(value) -> str:
    """
    Turn an ISO datetime string or datetime object into a readable string.
    """
    if not value:
        return ""
    s = str(value).replace("T", " ")
    return s[:16]


def _prepare_challenge_view(challenge: dict) -> dict:
    """
    Format deadline and participant timestamps for display.
    """
    challenge["join_deadline_fmt"] = _format_deadline(challenge.get("join_deadline"))
    challenge["proof_deadline_fmt"] = _format_deadline(challenge.get("proof_deadline"))
    challenge["voting_deadline_fmt"] = _format_deadline(challenge.get("voting_deadline"))
    for p in challenge.get("participants", []):
        p["joined_at_fmt"] = _format_deadline(p.get("joined_at"))
    return challenge


@router.get("/challenges")
def my_challenges_page(request: Request, user: Annotated[dict, Depends(current_user)]):
    
    challenges = get_user_challenges(user_id=user["id"])
    
    for c in challenges:
        c["join_deadline_fmt"] = _format_deadline(c.get("join_deadline"))
        c["proof_deadline_fmt"] = _format_deadline(c.get("proof_deadline"))
        c["voting_deadline_fmt"] = _format_deadline(c.get("voting_deadline"))

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
    proof: str | None = None,
    proof_error: str | None = None,
    vote: str | None = None,
    vote_error: str | None = None,
):
    
    challenge = get_challenge_by_id(challenge_id)
    
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    _prepare_challenge_view(challenge)

    participants = challenge.get("participants", [])
    my_participant = next(
        (p for p in participants if str(p.get("user_id")) == str(user["id"])),
        None,
    )
    has_paid = bool(my_participant and my_participant.get("paid"))
    attempts = get_my_evidence(str(challenge_id), str(user["id"])) if has_paid else []
    voting_open = challenge.get("status") not in ("closed", "settling", "settled", "cancelled")
    pending_votes = (
        get_pending_votes_for_user(str(challenge_id), str(user["id"]), participants)
        if (has_paid and voting_open)
        else []
    )
    unvoted_count = (
        sum(1 for ev in pending_votes if ev.get("my_vote") is None)
        if voting_open
        else 0
    )
    verification_mode = challenge.get("verification_mode", "ai")
    max_attempts = 1 if verification_mode == "vote" else MAX_ATTEMPTS

    ALLOWED_STATUSES = ["active", "closed", "voting"]
    creator_id = challenge.get("creator_id")
    is_owner = bool(creator_id and str(creator_id) == str(user.get("id")))
    paid_participants = [p for p in participants if p.get("paid")]
    all_resolved = bool(paid_participants) and all(p.get("outcome") != "pending" for p in paid_participants)
    can_settle = is_owner and (challenge.get("status") in ALLOWED_STATUSES) and all_resolved

    return templates.TemplateResponse(
        request,
        "challenge_detail.html",
        {
            "user": user,
            "challenge": challenge,
            "has_paid": has_paid,
            "voting_open": voting_open,
            "is_participant": my_participant is not None,
            "my_outcome": my_participant.get("outcome") if my_participant else None,
            "proof_error": PROOF_ERRORS.get(proof_error),
            "proof_uploaded": proof in ("uploaded", "needs_vote", "auto_approved"),
            "proof_status": proof,
            "proof_result": proof,
            "proof_sent_to_vote": proof == "sent_to_vote",
            "attempts": attempts,
            "pending_votes": pending_votes,
            "unvoted_count": unvoted_count,
            "vote_success": vote == "success",
            "vote_error": vote_error,
            "max_attempts": max_attempts,
            "can_settle": can_settle,
        },
    )


@router.get("/challenges/{challenge_id}/state")
def challenge_state_fragment(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    _prepare_challenge_view(challenge)

    return templates.TemplateResponse(
        request,
        "challenge_state.html",
        {
            "user": user,
            "challenge": challenge,
        },
    )
@router.post("/challenges/{challenge_id}/pay")
def pay_for_challenge(
    challenge_id: UUID,
    user: dict = Depends(current_user),
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

    if me.get("outcome") != "pending":
        return RedirectResponse(f"{back}?proof_error=closed", status_code=303)

    now = datetime.now(timezone.utc)
    proof_dl = challenge.get("proof_deadline")
    if isinstance(proof_dl, str):
        proof_dl = datetime.fromisoformat(proof_dl.replace("Z", "+00:00"))
    if proof_dl and proof_dl.tzinfo is None:
        proof_dl = proof_dl.replace(tzinfo=timezone.utc)

    if (proof_dl and now >= proof_dl) or challenge.get("status") not in ("open", "active"):
        return RedirectResponse(f"{back}?proof_error=closed", status_code=303)

    data = photo.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return RedirectResponse(f"{back}?proof_error=too_big", status_code=303)

    verification_mode = challenge.get("verification_mode", "ai")
    max_attempts = 1 if verification_mode == "vote" else MAX_ATTEMPTS
    paid_participants = [p for p in challenge.get("participants", []) if p.get("paid")]

    if verification_mode == "vote":
        if len(paid_participants) <= 1:
            initial_status = "auto_approved"
            proof_param = "proof=auto_approved"
        else:
            initial_status = "needs_vote"
            proof_param = "proof=needs_vote"
    else:
        initial_status = "pending"
        proof_param = "proof=uploaded"

    try:
        evidence, jpeg = save_evidence(
            str(challenge_id),
            str(user["id"]),
            data,
            status=initial_status,
            max_attempts=max_attempts,
        )
    except ValueError:
        return RedirectResponse(f"{back}?proof_error=no_attempts", status_code=303)
    except (UnidentifiedImageError, Image.DecompressionBombError):
        return RedirectResponse(f"{back}?proof_error=not_image", status_code=303)

    if verification_mode == "vote":
        if initial_status == "auto_approved":
            mark_verified(str(challenge_id), str(user["id"]))
        return RedirectResponse(f"{back}?{proof_param}", status_code=303)

    try:
        verdict, model = judge(jpeg, challenge["title"], challenge["criteria"], challenge["proof_code"])
        save_verdict(evidence["id"], verdict, model)
        status = decide(verdict)
        set_status(evidence["id"], status)
        if status == "auto_approved":
            mark_verified(str(challenge_id), str(user["id"]))
        elif status == "rejected" and evidence["attempt"] == MAX_ATTEMPTS:
            mark_forfeited(str(challenge_id), str(user["id"]))
    except Exception:
        send_to_vote(evidence["id"])
        return RedirectResponse(f"{back}?proof=sent_to_vote", status_code=303)

    return RedirectResponse(f"{back}?proof={status}", status_code=303)
@router.post("/challenges/{challenge_id}/settle")
def settle_challenge(
    challenge_id: UUID,
    user: dict = Depends(current_user),
):
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if str(challenge.get("creator_id")) != str(user.get("id")):
        raise HTTPException(status_code=403, detail="Only the challenge creator can settle the challenge")
    settle(challenge_id)
    return RedirectResponse(url=f"/challenges/{challenge_id}", status_code=303)


@router.get("/challenges/{challenge_id}/voting")
def voting_page(
    challenge_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    vote: str | None = None,
    vote_error: str | None = None,
):
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    _prepare_challenge_view(challenge)

    participants = challenge.get("participants", [])
    my_participant = next(
        (p for p in participants if str(p.get("user_id")) == str(user["id"])),
        None,
    )
    has_paid = bool(my_participant and my_participant.get("paid"))
    if not has_paid:
        raise HTTPException(status_code=403, detail="Only paid participants can access voting")

    verification_mode = challenge.get("verification_mode", "ai")
    voting_open = challenge.get("status") not in ("closed", "settling", "settled", "cancelled")
    feed = get_voting_feed(
        str(challenge_id),
        str(user["id"]),
        participants,
        verification_mode=verification_mode,
    )
    if verification_mode != "vote" and feed:
        feed = [ev for ev in feed if ev.get("status") == "needs_vote"]
    elif not feed:
        feed = get_pending_votes_for_user(str(challenge_id), str(user["id"]), participants)

    pending_votes = [
        ev for ev in feed
        if not ev.get("is_me") and ev.get("status", "needs_vote") == "needs_vote"
    ]
    unvoted_count = (
        sum(1 for ev in pending_votes if ev.get("my_vote") is None)
        if voting_open
        else 0
    )
    max_attempts = 1 if verification_mode == "vote" else MAX_ATTEMPTS

    return templates.TemplateResponse(
        request,
        "voting.html",
        {
            "user": user,
            "challenge": challenge,
            "feed": feed,
            "pending_votes": pending_votes,
            "unvoted_count": unvoted_count,
            "voting_open": voting_open,
            "vote_success": vote == "success",
            "vote_error": vote_error,
            "max_attempts": max_attempts,
        },
    )


@router.post("/evidence/{evidence_id}/vote")
async def vote_on_evidence(
    evidence_id: UUID,
    request: Request,
    approve: bool | None = Form(None),
    return_to: str | None = Form(None),
    user: dict = Depends(current_user),
):
    if approve is None:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
                approve = bool(body.get("approve"))
                return_to = body.get("return_to")
            except Exception:
                raise HTTPException(status_code=422, detail="Invalid JSON body")
        else:
            form = await request.form()
            raw_val = form.get("approve")
            return_to = form.get("return_to") or return_to
            if raw_val is None:
                raise HTTPException(status_code=422, detail="approve field is required")
            if isinstance(raw_val, str):
                approve = raw_val.lower() in ("true", "1", "yes")
            else:
                approve = bool(raw_val)

    try:
        result = cast_vote(str(evidence_id), str(user["id"]), approve)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    challenge_id = result["challenge_id"]

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "application/json" in accept or "application/json" in content_type:
        return result

    if return_to and str(return_to).startswith("/challenges/"):
        target_path = str(return_to).split("?")[0]
        return RedirectResponse(
            url=f"{target_path}?vote=success",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/challenges/{challenge_id}?vote=success",
        status_code=303,
    )
