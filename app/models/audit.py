import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, str_enum


class AuditAction(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ESCALATED = "escalated"


class AuditEvent(Base):
    """Append-only history of a request. A database trigger (see the initial
    migration) rejects UPDATE and DELETE, so the trail can't be rewritten even
    by a bug in the application."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_request_id_id", "request_id", "id"),)

    # A sequential id gives a stable ordering even for events in the same millisecond.
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_requests.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))  # None = system
    action: Mapped[AuditAction] = mapped_column(str_enum(AuditAction, "audit_action"))
    step_position: Mapped[int | None]
    comment: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
