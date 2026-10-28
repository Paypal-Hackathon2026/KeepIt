from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user
from app.models.challenge import ChallengeCreate, ChallengeOut
from app.services.challenge_service import create_challenge

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

