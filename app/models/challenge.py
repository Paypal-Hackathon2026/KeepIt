from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ChallengeCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    criteria: str = Field(..., min_length=10)
    entry_fee_pln: Decimal = Field(
        ...,
        gt=0,
        decimal_places=2,
        description="Entry fee in PLN (e.g. 10.50)",
    )
    join_deadline: datetime
    proof_deadline: datetime

    @field_validator("join_deadline", "proof_deadline")
    @classmethod
    def must_be_in_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("Deadline must be in the future")
        return v

    @model_validator(mode="after")
    def proof_after_join(self) -> "ChallengeCreate":
        if self.proof_deadline <= self.join_deadline:
            raise ValueError("proof_deadline must be later than join_deadline")
        return self


class ChallengeOut(BaseModel):
    id: UUID
    creator_id: UUID
    title: str
    criteria: str
    entry_fee_minor: int
    proof_code: str
    status: str
    join_deadline: datetime
    proof_deadline: datetime


class ParticipantOut(BaseModel):
    user_id: UUID
    display_name: str | None = None
    paid: bool
    outcome: str
    joined_at: datetime


class ChallengeSummaryOut(BaseModel):
    id: UUID
    title: str
    status: str
    entry_fee_minor: int
    pool_minor: int
    join_deadline: datetime
    proof_deadline: datetime


class ChallengeDetailOut(ChallengeOut):
    pool_minor: int
    participants: list[ParticipantOut]