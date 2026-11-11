from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote_plus
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.deps import current_user
from app.services.challenge_service import get_challenge_by_id
from app.services.evidence import (
    MAX_ATTEMPTS,
    get_pending_votes_for_user,
    get_voting_feed,
    cast_vote,
)
from app.routes.helpers import _find_participant, _prepare_challenge_view
from app.templating import templates

router = APIRouter()


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

    user_tz = request.cookies.get("user_timezone")
    _prepare_challenge_view(challenge, user_tz)

    participants = challenge.get("participants", [])
    my_participant = _find_participant(challenge, user["id"])
    has_paid = bool(my_participant and my_participant.get("paid"))
    if not has_paid:
        raise HTTPException(status_code=403, detail="Only paid participants can access voting")

    verification_mode = challenge.get("verification_mode") or "ai"
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
    voting_started = is_after_join and challenge.get("status") != "open"
    voting_open = voting_started and challenge.get("status") in ("active", "voting")
    user_tz = request.cookies.get("user_timezone")
    feed = get_voting_feed(
        str(challenge_id),
        str(user["id"]),
        participants,
        verification_mode=verification_mode,
        user_tz=user_tz,
    )
    if not feed:
        feed = get_pending_votes_for_user(
            str(challenge_id), str(user["id"]), participants, verification_mode=verification_mode, user_tz=user_tz
        )

    if feed and verification_mode != "vote":
        feed = [
            ev for ev in feed
            if (
                ev.get("status") == "needs_vote"
                or (
                    ev.get("status") in ("approved", "rejected")
                    and ev.get("status") not in (
                        "auto_approved", "auto-approved", "auto approved",
                        "auto_rejected", "auto-rejected", "auto rejected",
                        "pending"
                    )
                    and (ev.get("total_votes", 0) > 0 or ev.get("yes_count", 0) > 0 or ev.get("no_count", 0) > 0)
                )
            )
        ]

    pending_votes = [
        ev for ev in feed
        if not ev.get("is_me")
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
            "voting_started": voting_started,
            "vote_success": vote == "success",
            "vote_error": vote_error,
            "max_attempts": max_attempts,
        },
    )


@router.post("/evidence/{evidence_id}/vote")
async def vote_on_evidence(
    evidence_id: UUID,
    request: Request,
    user: Annotated[dict, Depends(current_user)],
    approve: bool | None = Form(None),
    return_to: str | None = Form(None),
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

    def _split_anchor(url: str) -> tuple[str, str]:
        """Split a URL into (path, '#anchor') parts, stripping any query string."""
        no_query = url.split("?")[0]
        if "#" in no_query:
            path, anchor = no_query.split("#", 1)
            return path, f"#{anchor}"
        return no_query, ""

    try:
        result = cast_vote(str(evidence_id), str(user["id"]), approve)
    except HTTPException as e:
        accept = request.headers.get("accept", "")
        content_type = request.headers.get("content-type", "")
        if "application/json" in accept or "application/json" in content_type:
            raise
        if return_to and str(return_to).startswith("/challenges/"):
            base_path, anchor = _split_anchor(str(return_to))
            return RedirectResponse(
                url=f"{base_path}?vote_error={quote_plus(str(e.detail))}{anchor}",
                status_code=303,
            )
        raise
    except ValueError as e:
        accept = request.headers.get("accept", "")
        content_type = request.headers.get("content-type", "")
        if "application/json" in accept or "application/json" in content_type:
            raise HTTPException(status_code=400, detail=str(e))
        if return_to and str(return_to).startswith("/challenges/"):
            base_path, anchor = _split_anchor(str(return_to))
            return RedirectResponse(
                url=f"{base_path}?vote_error={quote_plus(str(e))}{anchor}",
                status_code=303,
            )
        raise HTTPException(status_code=400, detail=str(e))

    challenge_id = result["challenge_id"]

    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "application/json" in accept or "application/json" in content_type:
        return result

    if return_to and str(return_to).startswith("/challenges/"):
        base_path, anchor = _split_anchor(str(return_to))
        return RedirectResponse(
            url=f"{base_path}?vote=success{anchor}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/challenges/{challenge_id}?vote=success",
        status_code=303,
    )
