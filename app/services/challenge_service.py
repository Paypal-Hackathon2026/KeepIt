import logging
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from uuid import UUID

from app.models.challenge import ChallengeCreate
from app.db import supabase
logger = logging.getLogger(__name__)

PROOF_CODE_LENGTH = 8
PROOF_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_proof_code() -> str:
    """Generate a random alphanumeric proof code."""
    return "".join(
        secrets.choice(PROOF_CODE_ALPHABET) for _ in range(PROOF_CODE_LENGTH)
    )


def _pln_to_minor(pln: Decimal) -> int:
    """Convert PLN (Decimal) to the smallest unit (grosz).

    Uses Decimal arithmetic to avoid floating-point rounding errors.
    """
    return int(pln * Decimal("100"))


def _calculate_pool_minor(entry_fee_minor: int, participants: list[dict]) -> int:
    """
    Calculate total paid pool in minor units (grosze).
    """
    paid_count = sum(1 for p in participants if p.get("paid"))
    return entry_fee_minor * paid_count


def calculate_challenge_status(challenge: dict, now: datetime | None = None) -> str:
    """
    Calculate timeline-driven status for a challenge based on its deadlines:
      - open:    now < join_deadline
      - active:  join_deadline <= now < proof_deadline
      - voting:  proof_deadline <= now < voting_deadline
      - closed:  now >= voting_deadline

    Terminal/payout states ('settling', 'settled', 'cancelled') are preserved.
    """
    current_status = challenge.get("status")
    if current_status in ("settling", "settled", "cancelled"):
        return current_status

    if now is None:
        now = datetime.now(timezone.utc)

    join_dl = challenge.get("join_deadline")
    proof_dl = challenge.get("proof_deadline")
    voting_dl = challenge.get("voting_deadline")

    if isinstance(join_dl, str):
        join_dl = datetime.fromisoformat(join_dl.replace("Z", "+00:00"))
    if isinstance(proof_dl, str):
        proof_dl = datetime.fromisoformat(proof_dl.replace("Z", "+00:00"))
    if isinstance(voting_dl, str):
        voting_dl = datetime.fromisoformat(voting_dl.replace("Z", "+00:00"))

    if join_dl and join_dl.tzinfo is None:
        join_dl = join_dl.replace(tzinfo=timezone.utc)
    if proof_dl and proof_dl.tzinfo is None:
        proof_dl = proof_dl.replace(tzinfo=timezone.utc)
    if voting_dl and voting_dl.tzinfo is None:
        voting_dl = voting_dl.replace(tzinfo=timezone.utc)

    if voting_dl is None and proof_dl is not None:
        voting_dl = proof_dl

    if join_dl and now < join_dl:
        return "open"
    elif proof_dl and now < proof_dl:
        return "active"
    elif voting_dl and now < voting_dl:
        return "voting"
    else:
        return "closed"


def sync_challenge_status(challenge: dict) -> dict:
    """
    Update challenge status in database if deadline progression changed it.
    """
    if not isinstance(challenge, dict):
        return challenge

    expected_status = calculate_challenge_status(challenge)
    if expected_status != challenge.get("status"):
        try:
            supabase.table("challenges").update({"status": expected_status}).eq("id", str(challenge["id"])).execute()
        except Exception as e:
            logger.debug("Failed to update challenge status in db: %s", e)
        challenge["status"] = expected_status
    return challenge


def create_challenge(payload: ChallengeCreate, creator_id: str) -> dict:
    """
    Create a new challenge and register the creator as the first participant.

    Both inserts run inside a single Postgres function (RPC) so they are
    atomic — if the participant insert fails, the challenge insert is
    rolled back automatically.

    Returns the created challenge row.
    """
    try:
        rpc_params = {
            "p_creator_id": creator_id,
            "p_title": payload.title,
            "p_criteria": payload.criteria,
            "p_entry_fee_minor": _pln_to_minor(payload.entry_fee_pln),
            "p_proof_code": _generate_proof_code(),
            "p_join_deadline": payload.join_deadline.isoformat(),
            "p_proof_deadline": payload.proof_deadline.isoformat(),
            "p_verification_mode": payload.verification_mode,
            "p_voting_deadline": payload.voting_deadline.isoformat() if payload.voting_deadline else None,
        }
        try:
            result = supabase.rpc(
                "create_challenge_with_participant",
                rpc_params,
            ).execute()
        except Exception as rpc_err:
            if "p_voting_deadline" in str(rpc_err) or "function" in str(rpc_err).lower():
                rpc_params_fallback = dict(rpc_params)
                del rpc_params_fallback["p_voting_deadline"]
                result = supabase.rpc(
                    "create_challenge_with_participant",
                    rpc_params_fallback,
                ).execute()
            else:
                raise
    except Exception as exc:
        logger.exception("Failed to execute create_challenge_with_participant RPC: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Database error creating challenge: {exc}",
        ) from exc

    if not result.data:
        logger.error("create_challenge_with_participant returned empty data")
        raise HTTPException(
            status_code=500,
            detail="Failed to create challenge in database",
        )

    return result.data

def get_user_challenges(user_id: str) -> list[dict]:
    """
    Return all challenges the user participates in with their calculated pool in minor units.
    """
    user_participations = (
        supabase.table("participants")
        .select("challenge_id")
        .eq("user_id", user_id)
        .execute()
    )
    user_participations_challenge_ids = [row["challenge_id"] for row in user_participations.data]

    if not user_participations_challenge_ids:
        return []

    user_participations_challenge_details = (
        supabase.table("challenges")
        .select("*, participants(paid)")
        .in_("id", user_participations_challenge_ids)
        .execute()
    )

    results = []
    for row in user_participations_challenge_details.data:
        sync_challenge_status(row)
        participants = row.get("participants", [])
        row["pool_minor"] = _calculate_pool_minor(row["entry_fee_minor"], participants)
        results.append(row)

    return results


def get_challenge_by_id(challenge_id: UUID) -> dict | None:
    """
    Fetch a single challenge by ID with its participants and calculated pool.
    Returns None if the challenge does not exist.
    """
    challenges_details = (
        supabase.table("challenges")
        .select("*, participants(user_id, paid, outcome, joined_at, profiles(display_name))")
        .eq("id", str(challenge_id))
        .execute()
    )

    if not challenges_details.data:
        return None

    challenge = challenges_details.data[0]
    sync_challenge_status(challenge)
    raw_participants = challenge.get("participants", [])

    participants = [
        {
            "user_id": p["user_id"],
            "display_name": (p.get("profiles", {})).get("display_name"),
            "paid": p["paid"],
            "outcome": p["outcome"],
            "joined_at": p["joined_at"],
        }
        for p in raw_participants
    ]

    challenge["participants"] = participants
    challenge["pool_minor"] = _calculate_pool_minor(challenge["entry_fee_minor"], participants)
    

    return challenge
