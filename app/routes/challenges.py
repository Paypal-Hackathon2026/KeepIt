from fastapi import APIRouter, Depends, status
from uuid import UUID
from app.deps import current_user
from app.models.challenge import ChallengeCreate, ChallengeOut, ChallengeJoinOut
from app.services.challenge_service import create_challenge

from app.services.payment_service import join_challenge

router = APIRouter(prefix="/api/challenges", tags=["challenges"])


@router.post(
    "",
    response_model=ChallengeOut,
    status_code=status.HTTP_201_CREATED,
)
def create(
    payload: ChallengeCreate,
    user: dict = Depends(current_user),
):
    """Create a new challenge and auto-register the creator as a participant."""
    challenge = create_challenge(payload, creator_id=user["id"])
    return challenge

@router.post(
    "/{challenge_id}/join",
    response_model=ChallengeJoinOut,
    status_code=status.HTTP_201_CREATED,
)
def join(challenge_id: UUID, user: dict = Depends(current_user)):
    """Join a challenge."""
    return join_challenge(challenge_id, user["id"])
