import logging
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import HTTPException

from app.db import supabase
from app.services.images import to_jpeg

logger = logging.getLogger(__name__)

BUCKET = "evidence"
MAX_ATTEMPTS = 3

def count_attempts(challenge_id: str, user_id: str) -> int:
    result = (
        supabase.table("evidence")
        .select("id")
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .execute()
    )
    return len(result.data)


def get_challenge_max_attempts(challenge_id: str) -> int:
    try:
        chal_res = (
            supabase.table("challenges")
            .select("verification_mode")
            .eq("id", str(challenge_id))
            .execute()
        )
        if chal_res.data and chal_res.data[0].get("verification_mode") == "vote":
            return 1
    except Exception:
        pass
    return MAX_ATTEMPTS


def save_evidence(
    challenge_id: str,
    user_id: str,
    photo: bytes,
    status: str = "pending",
    max_attempts: int | None = None,
) -> tuple[dict, bytes]:
    if max_attempts is None:
        max_attempts = get_challenge_max_attempts(challenge_id)

    attempt = count_attempts(challenge_id, user_id) + 1
    if attempt > max_attempts:
        raise ValueError(f"You have already used all {max_attempts} attempts.")

    jpeg = to_jpeg(photo)
    path = f"{challenge_id}/{user_id}/{attempt}.jpg"
    
    supabase.storage.from_(BUCKET).upload(
        path, jpeg, {"content-type": "image/jpeg", "upsert": "true"}
    )

    result = (
        supabase.table("evidence")
        .insert({
            "challenge_id": challenge_id,
            "user_id": user_id,
            "attempt": attempt,
            "storage_path": path,
            "status": status,
        })
        .execute()
    )
    return result.data[0], jpeg


def send_to_vote(evidence_id: str) -> None:
    supabase.table("evidence").update({"status": "needs_vote"}).eq("id", evidence_id).execute()

def get_my_evidence(challenge_id: str, user_id: str) -> list[dict]:
    try:
        result = (
            supabase.table("evidence")
            .select("attempt, status, storage_path, created_at, verdicts(verified, confidence, reasoning, fraud_flags)")
            .eq("challenge_id", challenge_id)
            .eq("user_id", user_id)
            .order("attempt", desc=True)
            .execute()
        )
    except Exception:
        result = (
            supabase.table("evidence")
            .select("attempt, status, storage_path, verdicts(verified, confidence, reasoning, fraud_flags)")
            .eq("challenge_id", challenge_id)
            .eq("user_id", user_id)
            .order("attempt", desc=True)
            .execute()
        )

    attempts = result.data or []
    for row in attempts:
        try:
            signed_url = supabase.storage.from_(BUCKET).create_signed_url(
                row["storage_path"], 3600
            )
            row["photo_url"] = signed_url.get("signedURL") or signed_url.get("signedUrl")
        except Exception:
            row["photo_url"] = None
        row["verdict"] = row["verdicts"][0] if row["verdicts"] else None

    return attempts

def set_status(evidence_id: str, status: str) -> None:
    supabase.table("evidence").update({"status": status}).eq("id", evidence_id).execute()
    
def mark_verified(challenge_id: str, user_id: str) -> None:
    (
        supabase.table("participants")
        .update({"outcome": "verified"})
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .execute()
    )
    
def mark_forfeited(challenge_id: str, user_id: str) -> None:
    (
        supabase.table("participants")
        .update({"outcome": "forfeited"})
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .execute()
    )


def mark_pending(challenge_id: str, user_id: str) -> None:
    (
        supabase.table("participants")
        .update({"outcome": "pending"})
        .eq("challenge_id", challenge_id)
        .eq("user_id", user_id)
        .execute()
    )


def _make_initials(name: str) -> str:
    if not name:
        return "P"
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def _format_timestamp(value, user_tz: str | None = None) -> str:
    """Turn an ISO datetime string or datetime object into a readable local string (YYYY-MM-DD HH:MM)."""
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return str(value).replace("T", " ")[:16]
    if isinstance(value, datetime):
        tz = None
        if user_tz:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(user_tz.strip())
            except Exception:
                tz = None
        if tz is not None:
            if value.tzinfo is not None:
                value = value.astimezone(tz)
            else:
                value = value.replace(tzinfo=timezone.utc).astimezone(tz)
        elif value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value).replace("T", " ")[:16]


def get_voting_feed(
    challenge_id: str,
    user_id: str,
    participants: list[dict] | None = None,
    verification_mode: str | None = None,
    user_tz: str | None = None,
) -> list[dict]:
    """
    Returns submitted evidence for a challenge chronologically formatted for
    the voting view.
    Includes both the current user's evidence (is_me=True, shown on right)
    and other participants' evidence (is_me=False, shown on left with voting options).
    For AI arbiter challenges (verification_mode != 'vote'), only evidence sent to community
    voting is included (they stay in the feed even after receiving community approved/rejected status).
    Photos auto-approved or rejected directly by the AI arbiter are excluded.
    For group vote challenges, all submitted photos are included and stay in the feed.
    """
    try:
        raw_items = []
        try:
            query = (
                supabase.table("evidence")
                .select("id, challenge_id, user_id, attempt, storage_path, status, created_at")
                .eq("challenge_id", challenge_id)
            )
            ordered_query = query.order("created_at", desc=False)
            res = ordered_query.execute()
            if res and isinstance(res.data, list):
                raw_items = res.data
            else:
                res = query.execute()
                raw_items = res.data or []
        except Exception:
            query = (
                supabase.table("evidence")
                .select("id, challenge_id, user_id, attempt, storage_path, status")
                .eq("challenge_id", challenge_id)
            )
            res = query.execute()
            raw_items = res.data or []

        if not raw_items:
            return []

        if not verification_mode:
            try:
                c_res = (
                    supabase.table("challenges")
                    .select("verification_mode")
                    .eq("id", challenge_id)
                    .execute()
                )
                if c_res.data and isinstance(c_res.data, list):
                    verification_mode = c_res.data[0].get("verification_mode") or "ai"
            except Exception:
                verification_mode = "ai"

        is_vote_only = (verification_mode == "vote")
        if is_vote_only:
            # For vote-only challenges, all submitted photos are shown
            items = list(raw_items)
        else:
            # Filter out auto_approved, auto_rejected and pending photos from AI arbiter voting feed
            items = [
                item for item in raw_items
                if item.get("status") not in (
                    "auto_approved", "auto-approved", "auto approved",
                    "auto_rejected", "auto-rejected", "auto rejected",
                    "pending"
                )
            ]
        if not items:
            return []

        # Sort strictly chronologically by created_at; fallback to attempt/id if created_at is absent
        def _sort_key(x):
            ca = x.get("created_at")
            if isinstance(ca, datetime):
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=timezone.utc)
                return (ca.isoformat(), x.get("attempt", 1), str(x.get("id", "")))
            if isinstance(ca, str) and ca:
                return (ca, x.get("attempt", 1), str(x.get("id", "")))
            return ("", x.get("attempt", 1), str(x.get("id", "")))

        items.sort(key=_sort_key)

        names_map = {}
        if participants:
            for p in participants:
                names_map[str(p.get("user_id"))] = p.get("display_name") or "Participant"

        missing_ids = [str(item["user_id"]) for item in items if str(item["user_id"]) not in names_map]
        if missing_ids:
            try:
                prof_res = (
                    supabase.table("profiles")
                    .select("id, display_name")
                    .in_("id", missing_ids)
                    .execute()
                )
                for prof in (prof_res.data or []):
                    names_map[str(prof["id"])] = prof.get("display_name") or "Participant"
            except Exception:
                pass

        evidence_ids = [item["id"] for item in items]
        try:
            votes_res = (
                supabase.table("votes")
                .select("evidence_id, voter_id, approve")
                .in_("evidence_id", evidence_ids)
                .execute()
            )
            all_votes = votes_res.data or []
        except Exception:
            all_votes = []

        votes_by_ev = defaultdict(list)
        for v in all_votes:
            votes_by_ev[str(v.get("evidence_id"))].append(v)

        result_items = []
        for item in items:
            ev_id = str(item["id"])
            st = str(item.get("status", "")).strip().lower()
            ev_votes = votes_by_ev[ev_id]
            total_votes = len(ev_votes)

            if not is_vote_only:
                # In AI arbiter challenges, ONLY show:
                # - 'needs_vote'
                # - 'approved' with community votes
                # - 'rejected' with community votes
                if st in (
                    "auto_approved", "auto-approved", "auto approved",
                    "auto_rejected", "auto-rejected", "auto rejected",
                    "pending"
                ):
                    continue
                if st in ("approved", "rejected") and total_votes == 0:
                    continue
                if st not in ("needs_vote", "approved", "rejected"):
                    continue

            try:
                signed_url = supabase.storage.from_(BUCKET).create_signed_url(
                    item["storage_path"], 3600
                )
                item["photo_url"] = signed_url.get("signedURL") or signed_url.get("signedUrl")
            except Exception:
                item["photo_url"] = None

            is_me = (str(item.get("user_id")) == str(user_id))
            item["is_me"] = is_me

            author_name = "You" if is_me else names_map.get(str(item.get("user_id")), "Participant")
            item["author_name"] = author_name
            item["avatar_initials"] = _make_initials(author_name if not is_me else "You")
            created_at_raw = item.get("created_at")
            item["created_at"] = created_at_raw
            item["created_at_fmt"] = _format_timestamp(created_at_raw, user_tz) if created_at_raw else None
            item["total_votes"] = total_votes
            item["yes_count"] = sum(1 for v in ev_votes if v.get("approve"))
            item["no_count"] = sum(1 for v in ev_votes if not v.get("approve"))
            item["my_vote"] = next(
                (v["approve"] for v in ev_votes if str(v.get("voter_id")) == str(user_id)),
                None,
            )
            result_items.append(item)

        return result_items
    except Exception as e:
        logger.exception("Error in get_voting_feed: %s", e)
        return []


def get_pending_votes_for_user(
    challenge_id: str,
    user_id: str,
    participants: list[dict] | None = None,
    verification_mode: str | None = None,
    user_tz: str | None = None,
) -> list[dict]:
    feed = get_voting_feed(
        challenge_id, user_id, participants, verification_mode=verification_mode, user_tz=user_tz
    )
    return [ev for ev in feed if not ev.get("is_me")]


def cast_vote(evidence_id: str, voter_id: str, approve: bool) -> dict:
    ev_res = (
        supabase.table("evidence")
        .select("id, challenge_id, user_id, attempt, status, storage_path")
        .eq("id", evidence_id)
        .execute()
    )
    if not ev_res.data:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence = ev_res.data[0]
    challenge_id = str(evidence["challenge_id"])
    author_id = str(evidence["user_id"])

    if str(voter_id) == author_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot vote on your own evidence",
        )

    # Check if challenge allows voting
    verification_mode = "ai"
    try:
        chal_res = (
            supabase.table("challenges")
            .select("id, status, voting_deadline, proof_deadline, verification_mode, join_deadline")
            .eq("id", challenge_id)
            .execute()
        )
        if chal_res.data and isinstance(chal_res.data, list):
            chal_data = chal_res.data[0]
            if isinstance(chal_data, dict):
                verification_mode = chal_data.get("verification_mode", "ai")
                now = datetime.now(timezone.utc)
                if chal_data.get("status") == "open":
                    raise HTTPException(
                        status_code=400,
                        detail="Voting has not started yet (join deadline has not passed)",
                    )
                join_dl = chal_data.get("join_deadline")
                if isinstance(join_dl, str):
                    try:
                        join_dl = datetime.fromisoformat(join_dl.replace("Z", "+00:00"))
                    except Exception:
                        join_dl = None
                if isinstance(join_dl, datetime):
                    if join_dl.tzinfo is None:
                        join_dl = join_dl.replace(tzinfo=timezone.utc)
                    if now < join_dl:
                        raise HTTPException(
                            status_code=400,
                            detail="Voting has not started yet (join deadline has not passed)",
                        )
                if chal_data.get("status") in ("closed", "settling", "settled", "cancelled"):
                    raise HTTPException(
                        status_code=400,
                        detail="Voting is closed for this challenge",
                    )
                voting_dl = chal_data.get("voting_deadline")
                if isinstance(voting_dl, str):
                    try:
                        voting_dl = datetime.fromisoformat(voting_dl.replace("Z", "+00:00"))
                    except Exception:
                        voting_dl = None
                if isinstance(voting_dl, datetime):
                    if voting_dl.tzinfo is None:
                        voting_dl = voting_dl.replace(tzinfo=timezone.utc)
                    if now >= voting_dl:
                        raise HTTPException(
                            status_code=400,
                            detail="Voting is closed for this challenge (voting deadline has passed)",
                        )
    except HTTPException:
        raise
    except Exception:
        pass

    if verification_mode != "vote" and evidence.get("status") in ("auto_approved", "auto_rejected"):
        raise HTTPException(
            status_code=400,
            detail="Voting is not open for this evidence (status is not needs_vote)",
        )

    voter_res = (
        supabase.table("participants")
        .select("user_id, paid")
        .eq("challenge_id", challenge_id)
        .eq("user_id", voter_id)
        .execute()
    )
    if not voter_res.data or not voter_res.data[0].get("paid"):
        raise HTTPException(
            status_code=403,
            detail="Only paid participants can vote",
        )

    # Upsert voter's vote
    supabase.table("votes").upsert({
        "evidence_id": evidence_id,
        "challenge_id": challenge_id,
        "voter_id": voter_id,
        "approve": approve,
    }).execute()

    # Get paid participants count
    paid_parts_res = (
        supabase.table("participants")
        .select("user_id, paid")
        .eq("challenge_id", challenge_id)
        .eq("paid", True)
        .execute()
    )
    paid_participants = paid_parts_res.data or []
    total_paid = len(paid_participants)

    # Get all votes for this evidence
    votes_res = (
        supabase.table("votes")
        .select("voter_id, approve")
        .eq("evidence_id", evidence_id)
        .execute()
    )
    votes = votes_res.data or []
    total_votes = len(votes)
    yes_votes = sum(1 for v in votes if v.get("approve"))
    no_votes = sum(1 for v in votes if not v.get("approve"))

    eligible_voters = [p for p in paid_participants if str(p.get("user_id")) != author_id]
    n_eligible = len(eligible_voters)

    # Quorum rule:
    # 1. At least 50% of registered & paid participants of the challenge must participate
    # 2. Must always be at least 3 participants in the challenge
    is_valid = (total_paid >= 3) and (total_votes >= total_paid * 0.5)

    new_status = "needs_vote"
    if is_valid and n_eligible > 0:
        if total_votes >= n_eligible:
            # All eligible participants have voted:
            # yes votes > no votes -> approved
            # yes votes = no votes -> rejected
            new_status = "approved" if yes_votes > no_votes else "rejected"
        elif yes_votes > (n_eligible / 2):
            new_status = "approved"
        elif no_votes >= (n_eligible / 2):
            new_status = "rejected"

    if new_status != evidence.get("status"):
        set_status(evidence_id, new_status)
        if new_status == "approved":
            mark_verified(challenge_id, author_id)
        elif new_status == "rejected":
            mark_forfeited(challenge_id, author_id)
        else:
            mark_pending(challenge_id, author_id)

    current_status = new_status

    return {
        "evidence_id": evidence_id,
        "challenge_id": challenge_id,
        "voter_id": voter_id,
        "approve": approve,
        "status": current_status,
        "total_votes": total_votes,
        "yes_votes": yes_votes,
        "no_votes": no_votes,
        "total_paid": total_paid,
        "quorum_reached": is_valid,
    }

    
    