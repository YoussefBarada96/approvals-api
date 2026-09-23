import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _not_blank(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_not_blank)]

MAX_SLA_HOURS = 24 * 90


class StepIn(BaseModel):
    name: Name
    approver_group_id: uuid.UUID
    sla_hours: int = Field(ge=1, le=MAX_SLA_HOURS)


# Steps are given in order; positions (1, 2, 3...) are assigned from it.
Steps = Annotated[list[StepIn], Field(min_length=1, max_length=20)]


class WorkflowCreate(BaseModel):
    name: Name
    description: str = Field(default="", max_length=2000)
    steps: Steps


class WorkflowUpdate(BaseModel):
    """PATCH body: only the fields that are sent are changed."""

    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class StepsReplace(BaseModel):
    steps: Steps


class WorkflowStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    name: str
    approver_group_id: uuid.UUID
    sla_hours: int


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    is_active: bool
    created_at: datetime
    steps: list[WorkflowStepOut]
