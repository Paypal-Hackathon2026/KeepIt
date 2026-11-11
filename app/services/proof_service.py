import logging

from app.services.arbiter import decide, judge, save_verdict
from app.services.evidence import (
    MAX_ATTEMPTS,
    mark_forfeited,
    mark_verified,
    save_evidence,
    send_to_vote,
    set_status,
)

logger = logging.getLogger(__name__)


def process_proof(challenge: dict, user_id: str, data: bytes) -> str:
    verification_mode = challenge.get("verification_mode", "ai")
    max_attempts = 1 if verification_mode == "vote" else MAX_ATTEMPTS
    initial_status = "needs_vote" if verification_mode == "vote" else "pending"

    evidence, jpeg = save_evidence(
        str(challenge["id"]),
        str(user_id),
        data,
        status=initial_status,
        max_attempts=max_attempts,
    )

    if verification_mode == "vote":
        return "needs_vote"

    try:
        verdict, model = judge(
            jpeg,
            challenge["title"],
            challenge["criteria"],
            challenge["proof_code"],
        )
        save_verdict(evidence["id"], verdict, model)
        status = decide(verdict)
        set_status(evidence["id"], status)
        if status == "auto_approved":
            mark_verified(str(challenge["id"]), str(user_id))
        elif status in ("rejected", "auto_rejected") and evidence["attempt"] == max_attempts:
            mark_forfeited(str(challenge["id"]), str(user_id))
    except Exception as exc:
        logger.exception("AI Arbiter check failed for evidence %s: %s", evidence.get("id"), exc)
        send_to_vote(evidence["id"])
        return "sent_to_vote"

    return status
