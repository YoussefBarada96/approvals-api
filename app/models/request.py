import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey, str_enum


class RequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class StepStatus(StrEnum):
    WAITING = "waiting"  # an earlier step hasn't been decided yet
    ACTIVE = "active"  # the step currently awaiting a decision
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"  # the request ended before this step was reached


class ApprovalRequest(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "approval_requests"

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[RequestStatus] = mapped_column(
        str_enum(RequestStatus, "request_status"),
        default=RequestStatus.PENDING,
        server_default=RequestStatus.PENDING.value,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None]

    # Optimistic locking: SQLAlchemy adds "AND version = <loaded value>" to every
    # UPDATE and bumps it. If two approvers act at once, the second UPDATE
    # matches no rows and raises StaleDataError instead of silently overwriting.
    version: Mapped[int] = mapped_column()
    # eager_defaults: read server-generated values (created_at, updated_at)
    # back with RETURNING, so accessing them later needs no extra query, which
    # async SQLAlchemy can't do implicitly.
    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}

    steps: Mapped[list["RequestStep"]] = relationship(
        back_populates="request",
        order_by="RequestStep.position",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class RequestStep(UUIDPrimaryKey, Base):
    """One step of one request. Name, group and SLA are copied from the
    workflow when the request is submitted, so later edits to the workflow
    don't change requests that are already in flight."""

    __tablename__ = "request_steps"
    __table_args__ = (
        UniqueConstraint("request_id", "position"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("sla_hours > 0", name="sla_hours_positive"),
        # The SLA worker's query: active steps past their deadline, not yet escalated.
        Index(
            "ix_request_steps_overdue",
            "due_at",
            postgresql_where=text("status = 'active' AND escalated_at IS NULL"),
        ),
        # "Assigned to me": active steps for the groups a user belongs to.
        Index(
            "ix_request_steps_active_group",
            "approver_group_id",
            postgresql_where=text("status = 'active'"),
        ),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE")
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    approver_group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_groups.id"))
    sla_hours: Mapped[int]
    status: Mapped[StepStatus] = mapped_column(
        str_enum(StepStatus, "step_status"),
        default=StepStatus.WAITING,
        server_default=StepStatus.WAITING.value,
    )
    activated_at: Mapped[datetime | None]
    due_at: Mapped[datetime | None]
    escalated_at: Mapped[datetime | None]
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None]
    comment: Mapped[str | None] = mapped_column(Text)

    request: Mapped[ApprovalRequest] = relationship(back_populates="steps", lazy="raise")
