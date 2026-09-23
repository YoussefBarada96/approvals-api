import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey


class Workflow(UUIDPrimaryKey, CreatedAt, Base):
    """A reusable template: an ordered list of approval steps."""

    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))

    steps: Mapped[list["WorkflowStep"]] = relationship(
        back_populates="workflow",
        order_by="WorkflowStep.position",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class WorkflowStep(UUIDPrimaryKey, Base):
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "position"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("sla_hours > 0", name="sla_hours_positive"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"))
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(100))
    approver_group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approval_groups.id"))
    sla_hours: Mapped[int]

    workflow: Mapped[Workflow] = relationship(back_populates="steps", lazy="raise")
