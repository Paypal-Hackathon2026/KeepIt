import secrets
import string
from decimal import Decimal

from fastapi import HTTPException
from uuid import UUID

from app.models.challenge import ChallengeCreate
from app.db import supabase

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


def create_challenge(payload: ChallengeCreate, creator_id: str) -> dict:
    """
    Create a new challenge and register the creator as the first participant.

    Both inserts run inside a single Postgres function (RPC) so they are
    atomic — if the participant insert fails, the challenge insert is
    rolled back automatically.

    Returns the created challenge row.
    """
    result = supabase.rpc(
        "create_challenge_with_participant",
        {
            "p_creator_id": creator_id,
            "p_title": payload.title,
            "p_criteria": payload.criteria,
            "p_entry_fee_minor": _pln_to_minor(payload.entry_fee_pln),
            "p_proof_code": _generate_proof_code(),
            "p_join_deadline": payload.join_deadline.isoformat(),
            "p_proof_deadline": payload.proof_deadline.isoformat(),
        },
    ).execute()

    if not result.data:
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
