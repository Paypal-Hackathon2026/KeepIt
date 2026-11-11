from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PROOF_ERRORS = {
    "too_big": "Photo is too big (max 15 MB).",
    "not_image": "This file is not a photo. Try again.",
    "no_attempts": "You have already used all allowed attempts.",
    "closed": "You can't upload more photos for this challenge.",
    "needs_vote": "Your photo has been sent to other participants for voting. You cannot upload more photos.",
}


def _format_deadline(value, user_tz: str | None = None) -> str:
    """
    Turn an ISO datetime string or datetime object into a readable string in the user's local time.
    """
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            s = str(value).replace("T", " ")
            return s[:16]
    if isinstance(value, datetime):
        tz = None
        if user_tz:
            try:
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
    s = str(value).replace("T", " ")
    return s[:16]


def _prepare_challenge_view(challenge: dict, user_tz: str | None = None) -> dict:
    """
    Format deadline and participant timestamps for display.
    """
    challenge["join_deadline_fmt"] = _format_deadline(challenge.get("join_deadline"), user_tz)
    challenge["proof_deadline_fmt"] = _format_deadline(challenge.get("proof_deadline"), user_tz)
    challenge["voting_deadline_fmt"] = _format_deadline(challenge.get("voting_deadline"), user_tz)
    for participant in challenge.get("participants", []):
        participant["joined_at_fmt"] = _format_deadline(participant.get("joined_at"), user_tz)
    return challenge


def _find_participant(challenge: dict, user_id) -> dict | None:
    return next(
        (
            participant
            for participant in challenge.get("participants", [])
            if str(participant.get("user_id")) == str(user_id)
        ),
        None,
    )
