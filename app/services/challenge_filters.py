from datetime import datetime, timezone

CHALLENGE_STATUSES = ("open", "active", "settling", "settled", "cancelled")
CHALLENGE_MODES = ("ai", "vote")


def _parse_challenge_datetime(value: datetime | str | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def relevant_deadline(challenge: dict, now: datetime) -> tuple[str, str | None]:
    status = challenge.get("status")
    if status == "open":
        label, deadline = "Join by", challenge.get("join_deadline")
    elif status == "active":
        proof_deadline = challenge.get("proof_deadline")
        parsed_proof_deadline = _parse_challenge_datetime(proof_deadline)
        if parsed_proof_deadline and parsed_proof_deadline > now:
            label, deadline = "Proof due", proof_deadline
        else:
            label, deadline = "Voting ends", challenge.get("voting_deadline")
    elif status in ("settling", "settled", "cancelled"):
        label, deadline = "Ended", challenge.get("proof_deadline")
    else:
        return "", None

    if isinstance(deadline, datetime):
        deadline = deadline.isoformat()
    return label, deadline


def filter_and_sort_challenges(
    challenges: list[dict],
    status: str,
    mode: str,
    sort: str,
    now: datetime,
) -> list[dict]:
    if status not in ("all", *CHALLENGE_STATUSES):
        status = "all"
    if mode not in ("all", *CHALLENGE_MODES):
        mode = "all"
    if sort not in ("deadline", "newest", "pool"):
        sort = "deadline"

    filtered = [
        challenge
        for challenge in challenges
        if (status == "all" or challenge.get("status") == status)
        and (
            mode == "all"
            or challenge.get("verification_mode", "ai") == mode
        )
    ]

    if sort == "newest":
        return sorted(
            filtered,
            key=lambda challenge: _parse_challenge_datetime(
                challenge.get("created_at")
            )
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    if sort == "pool":
        return sorted(
            filtered,
            key=lambda challenge: challenge.get("pool_minor", 0) or 0,
            reverse=True,
        )

    status_order = {value: index for index, value in enumerate(CHALLENGE_STATUSES)}

    def deadline_sort_key(challenge: dict) -> tuple[int, float]:
        challenge_status = challenge.get("status")
        status_index = status_order.get(challenge_status, len(status_order))
        if challenge_status in ("open", "active"):
            _, deadline = relevant_deadline(challenge, now)
            parsed_deadline = _parse_challenge_datetime(deadline)
            return (
                status_index,
                parsed_deadline.timestamp()
                if parsed_deadline
                else float("inf"),
            )
        parsed_deadline = _parse_challenge_datetime(challenge.get("proof_deadline"))
        return (
            status_index,
            -parsed_deadline.timestamp()
            if parsed_deadline
            else float("inf"),
        )

    return sorted(filtered, key=deadline_sort_key)
