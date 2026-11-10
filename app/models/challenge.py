from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID
from typing import Literal


from pydantic import BaseModel, Field, field_validator, model_validator, AnyHttpUrl

from zoneinfo import ZoneInfo
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
    voting_deadline: datetime | None = None
    verification_mode: Literal["ai", "vote"] = Field(
        default="ai",
        description="Verification mode: 'ai' (AI Arbiter) or 'vote' (Group vote only)",
    )

    @field_validator("join_deadline", "proof_deadline", "voting_deadline")
    @classmethod
    def must_be_in_future(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is not None:
            v=v.astimezone(timezone.utc)
        else:
            v=v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("Deadline must be in the future")
        return v

    @model_validator(mode="after")
    def validate_deadlines(self) -> "ChallengeCreate":
        if self.proof_deadline <= self.join_deadline:
            raise ValueError("proof_deadline must be later than join_deadline")
        if self.voting_deadline is None:
            self.voting_deadline = self.proof_deadline + timedelta(days=1)
        elif self.voting_deadline <= self.proof_deadline:
            raise ValueError("voting_deadline must be later than proof_deadline")
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
    voting_deadline: datetime | None = None
    verification_mode: Literal["ai", "vote"] = Field(
        default="ai",
        description="Verification mode: 'ai' (AI Arbiter) or 'vote' (Group vote only)",
    )

class ChallengeJoinOut(BaseModel):
    payment_id: UUID
    paypal_order_id: str
    approve_url: AnyHttpUrl
    amount_minor: int
    status: Literal["created"]


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
    voting_deadline: datetime | None = None
    verification_mode: Literal["ai", "vote"] = Field(
        default="ai",
        description="Verification mode: 'ai' (AI Arbiter) or 'vote' (Group vote only)",
    )


class ChallengeDetailOut(ChallengeOut):
    pool_minor: int
    participants: list[ParticipantOut]
