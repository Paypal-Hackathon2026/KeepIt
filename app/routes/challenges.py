from uuid import UUID
from typing import Annotated
from fastapi import APIRouter, Depends, status, HTTPException

from app.dependencies import get_current_user
from app.models.challenge import ChallengeCreate, ChallengeOut, ChallengeDetailOut, ChallengeSummaryOut
from app.services.challenge_service import create_challenge, get_challenge_by_id, get_user_challenges

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


@router.post(
    "",
    response_model=ChallengeOut,
    status_code=status.HTTP_201_CREATED,
)
def create(
    payload: ChallengeCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new challenge and auto-register the creator as a participant."""
    challenge = create_challenge(payload, creator_id=user["id"])
    return challenge


@router.get(
    "",
    response_model=list[ChallengeSummaryOut],
    status_code=status.HTTP_200_OK,
)
def list_my_challenges(
    user: Annotated[dict, Depends(get_current_user)]
):
    """
    Return challenges the current user participates in (with title, status, and pool).
    """
    return get_user_challenges(user_id=user["id"])


@router.get(
    "/{challenge_id}",
    response_model=ChallengeDetailOut,
    status_code=status.HTTP_200_OK,
)
def get_challenge_details(
    challenge_id: UUID,
):
    """
    Return challenge details, participants (paid/unpaid), and pool in minor units.
    """
    challenge = get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Challenge not found",
        )
    return challenge