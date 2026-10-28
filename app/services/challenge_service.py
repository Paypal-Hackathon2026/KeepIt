import secrets
import string

from app.models.challenge import ChallengeCreate
from app.supabase_client import supabase

PROOF_CODE_LENGTH = 8
PROOF_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _generate_proof_code() -> str:
    """Generate a random alphanumeric proof code."""
    return "".join(
        secrets.choice(PROOF_CODE_ALPHABET) for _ in range(PROOF_CODE_LENGTH)
    )


def _pln_to_minor(pln) -> int:
    """Convert PLN (Decimal/float) to the smallest unit (grosz)."""
    return int(round(float(pln) * 100))


def create_challenge(payload: ChallengeCreate, creator_id: str) -> dict:
    """
    Insert a new challenge and register the creator as the first participant.

    Returns the created challenge row.
    """
    challenge_data = {
        "creator_id": creator_id,
        "title": payload.title,
        "criteria": payload.criteria,
        "entry_fee_minor": _pln_to_minor(payload.entry_fee_pln),
        "proof_code": _generate_proof_code(),
        "join_deadline": payload.join_deadline.isoformat(),
        "proof_deadline": payload.proof_deadline.isoformat(),
    }

    challenge = (
        supabase.table("challenges")
        .insert(challenge_data)
        .execute()
    )

    challenge_row = challenge.data[0]

    # Auto-register the creator as a participant
    supabase.table("participants").insert(
        {
            "challenge_id": challenge_row["id"],
            "user_id": creator_id,
        }
    ).execute()

    return challenge_row

