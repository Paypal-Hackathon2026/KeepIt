import secrets
import string
from decimal import Decimal

from fastapi import HTTPException

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
