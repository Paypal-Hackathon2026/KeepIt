from datetime import datetime, timezone, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import current_user
from app.models.challenge import ChallengeCreate
from app.services.challenge_service import (
    create_challenge,
    get_challenge_by_id,
    get_user_challenges,
)
from app.services.challenge_filters import (
    CHALLENGE_STATUSES,
    filter_and_sort_challenges,
    relevant_deadline,
)
from app.services.evidence import (
    MAX_ATTEMPTS,
    get_my_evidence,
    get_pending_votes_for_user,
)
from app.services.settlement_service import settle
from app.routes.helpers import (
    PROOF_ERRORS,
    _find_participant,
    _format_deadline,
    _prepare_challenge_view,
)
from app.templating import templates

router = APIRouter()


def _to_utc(
    dt_local_str: str,
    dt_utc_str: str = "",
    tz_offset_str: str = "",
    tz_name_str: str = "",
) -> datetime | None:
    if not dt_local_str and not dt_utc_str:
        return None
    if dt_utc_str and dt_utc_str.strip():
        try:
            return datetime.fromisoformat(dt_utc_str.strip().replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            pass

    if not dt_local_str or not dt_local_str.strip():
        return None

    try:
        dt = datetime.fromisoformat(dt_local_str.strip().replace("Z", "+00:00"))
    except Exception:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    if tz_offset_str and tz_offset_str.strip():
        try:
            offset_mins = int(tz_offset_str.strip())
            tz = timezone(timedelta(minutes=-offset_mins))
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        except Exception:
            pass

    if tz_name_str and tz_name_str.strip():
        try:
            tz = ZoneInfo(tz_name_str.strip())
            return dt.replace(tzinfo=tz).astimezone(timezone.utc)
        except Exception:
            pass
    return dt.replace(tzinfo=timezone.utc)


@router.get("/challenges/new")
def new_challenge_page(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
):
    return templates.TemplateResponse(
        request,
        "new_challenge.html",
        {"user": user, "errors": {}, "values": {"verification_mode": "ai", "voting_deadline": ""}},
    )


@router.post("/challenges/new")
def created_challenge(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    title: str = Form(""),
    criteria: str = Form(""),
    entry_fee_pln: str = Form(""),
    join_deadline: str = Form(""),
    proof_deadline: str = Form(""),
    voting_deadline: str = Form(""),
    verification_mode: str = Form("ai"),
    user_timezone: str = Form(""),
    tz_offset_minutes: str = Form(""),
    join_deadline_utc: str = Form(""),
    proof_deadline_utc: str = Form(""),
    voting_deadline_utc: str = Form(""),
):
    values = {
        "title": title,
        "criteria": criteria,
        "entry_fee_pln": entry_fee_pln,
        "join_deadline": join_deadline,
        "proof_deadline": proof_deadline,
        "voting_deadline": voting_deadline,
        "verification_mode": verification_mode,
        "user_timezone": user_timezone,
    }

    try:
        parsed_join = _to_utc(join_deadline, join_deadline_utc, tz_offset_minutes, user_timezone) or join_deadline
        parsed_proof = _to_utc(proof_deadline, proof_deadline_utc, tz_offset_minutes, user_timezone) or proof_deadline
        parsed_voting = _to_utc(voting_deadline, voting_deadline_utc, tz_offset_minutes, user_timezone) if voting_deadline else None
        create_kwargs = {
            "title": title,
            "criteria": criteria,
            "entry_fee_pln": entry_fee_pln,
            "join_deadline": parsed_join,
            "proof_deadline": parsed_proof,
            "verification_mode": verification_mode,
        }
        if parsed_voting:
            create_kwargs["voting_deadline"] = parsed_voting
        challenge_data = ChallengeCreate(**create_kwargs)
    except ValidationError as e:
        errors = {}
        for error in e.errors():
            loc = error["loc"]
            msg = error["msg"]
            if msg.startswith("Value error, "):
                msg = msg.replace("Value error, ", "")
            if loc:
                field_name = str(loc[0])
                errors[field_name] = msg
            else:
                errors["general"] = msg
        return templates.TemplateResponse(
            request,
            "new_challenge.html",
            {"user": user, "errors": errors, "values": values},
            status_code=422,
        )
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


@router.get("/challenges")
def my_challenges_page(
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    status: str = "all",
    mode: str = "all",
    sort: str = "deadline",
):
    user_tz = request.cookies.get("user_timezone")
    all_challenges = get_user_challenges(user_id=user["id"])
    counts = {
        challenge_status: sum(
            1 for challenge in all_challenges
            if challenge.get("status") == challenge_status
        )
        for challenge_status in CHALLENGE_STATUSES
    }
    now = datetime.now(timezone.utc)
    challenges = filter_and_sort_challenges(
        all_challenges, status, mode, sort, now
    )

    for challenge in challenges:
        challenge["join_deadline_fmt"] = _format_deadline(
            challenge.get("join_deadline"), user_tz
        )
        challenge["proof_deadline_fmt"] = _format_deadline(
            challenge.get("proof_deadline"), user_tz
        )
        challenge["voting_deadline_fmt"] = _format_deadline(
            challenge.get("voting_deadline"), user_tz
        )
        challenge["deadline_label"], deadline = relevant_deadline(
            challenge, now
        )
        challenge["deadline_iso"] = deadline
        challenge["deadline_fmt"] = _format_deadline(deadline, user_tz)

    return templates.TemplateResponse(
        request,
        "challenges.html",
        {
            "user": user,
            "challenges": challenges,
            "counts": counts,
            "total_count": len(all_challenges),
            "status": status if status in ("all", *counts) else "all",
            "mode": mode if mode in ("all", "ai", "vote") else "all",
            "sort": sort if sort in ("deadline", "newest", "pool") else "deadline",
        },
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

    user_tz = request.cookies.get("user_timezone")
    _prepare_challenge_view(challenge, user_tz)

    participants = challenge.get("participants", [])
    my_participant = _find_participant(challenge, user["id"])
    has_paid = bool(my_participant and my_participant.get("paid"))
    attempts = get_my_evidence(str(challenge_id), str(user["id"])) if has_paid else []
    verification_mode = challenge.get("verification_mode", "ai")
    now = datetime.now(timezone.utc)
    join_dl = challenge.get("join_deadline")
    if isinstance(join_dl, str):
        try:
            join_dl = datetime.fromisoformat(join_dl.replace("Z", "+00:00"))
        except Exception:
            join_dl = None
    if isinstance(join_dl, datetime) and join_dl.tzinfo is None:
        join_dl = join_dl.replace(tzinfo=timezone.utc)
    is_after_join = (not join_dl) or (now >= join_dl)
    voting_open = is_after_join and challenge.get("status") in ("active", "voting")
    user_tz = request.cookies.get("user_timezone")
    pending_votes = (
        get_pending_votes_for_user(
            str(challenge_id), str(user["id"]), participants, verification_mode=verification_mode, user_tz=user_tz
        )
        if (has_paid and voting_open)
        else []
    )
    unvoted_count = (
        sum(1 for ev in pending_votes if ev.get("my_vote") is None)
        if voting_open
        else 0
    )
    max_attempts = 1 if verification_mode == "vote" else MAX_ATTEMPTS
    has_needs_vote = any(a.get("status") == "needs_vote" for a in attempts)
    allowed_statuses = ["active", "closed", "voting"]
    creator_id = challenge.get("creator_id")
    is_owner = bool(creator_id and str(creator_id) == str(user.get("id")))
    paid_participants = [p for p in participants if p.get("paid")]
    all_resolved = bool(paid_participants) and all(p.get("outcome") != "pending" for p in paid_participants)
    payouts = challenge.get("payouts", [])
    has_failed_payouts = any(p.get("status") == "failed" for p in payouts)
    can_settle = is_owner and (challenge.get("status") in allowed_statuses) and (all_resolved or challenge.get("status") == "closed") or (challenge.get("status") == "closed" and has_failed_payouts)

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
            "proof_uploaded": proof in ("uploaded", "needs_vote", "auto_approved", "auto_rejected"),
            "proof_status": proof,
            "proof_result": proof,
            "proof_sent_to_vote": proof == "sent_to_vote",
            "attempts": attempts,
            "pending_votes": pending_votes,
            "unvoted_count": unvoted_count,
            "vote_success": vote == "success",
            "vote_error": vote_error,
            "max_attempts": max_attempts,
            "has_needs_vote": has_needs_vote,
            "can_settle": can_settle,
            "has_failed_payouts": has_failed_payouts,
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

    user_tz = request.cookies.get("user_timezone")
    _prepare_challenge_view(challenge, user_tz)
    payouts = challenge.get("payouts", [])
    has_failed_payouts = any(p.get("status") == "failed" for p in payouts)

    return templates.TemplateResponse(
        request,
        "challenge_state.html",
        {
            "user": user,
            "challenge": challenge,
            "has_failed_payouts": has_failed_payouts,
        },
    )


@router.post("/challenges/{challenge_id}/settle")
def settle_challenge(
    challenge_id: UUID,
    user: Annotated[dict, Depends(current_user)],
):
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if str(challenge.get("creator_id")) != str(user.get("id")):
        raise HTTPException(status_code=403, detail="Only the challenge creator can settle the challenge")
    settle(challenge_id)
    return RedirectResponse(url=f"/challenges/{challenge_id}", status_code=303)
