import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import AuditAction, RequestStatus, StepStatus

MAX_DETAILS_BYTES = 10_000


class RequestCreate(BaseModel):
    workflow_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    # Free-form context for approvers, e.g. {"amount": 4200, "vendor": "Acme"}.
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("details")
    @classmethod
    def limit_details_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_DETAILS_BYTES:
            raise ValueError(f"must be at most {MAX_DETAILS_BYTES} bytes as JSON")
        return value


class RequestStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    name: str
    approver_group_id: uuid.UUID
    sla_hours: int
    status: StepStatus
    activated_at: datetime | None
    due_at: datetime | None
    escalated_at: datetime | None
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    comment: str | None


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    requester_id: uuid.UUID
    title: str
    details: dict[str, Any]
    status: RequestStatus
    # Sent back when acting on the request, so a decision made on a stale
    # view of it is rejected (optimistic locking).
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    steps: list[RequestStepOut]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: AuditAction
    actor_id: uuid.UUID | None
    step_position: int | None
    comment: str | None
    data: dict[str, Any]
    created_at: datetime


class DecisionIn(BaseModel):
    # The version of the request the user was looking at when they decided.
    version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(DecisionIn):
    # A rejection must say why.
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
