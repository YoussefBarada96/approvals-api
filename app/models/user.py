from sqlalchemy import Column, ForeignKey, String, Table, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAt, UUIDPrimaryKey

group_memberships = Table(
    "group_memberships",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("approval_groups.id", ondelete="CASCADE"), primary_key=True),
)


class User(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(default=True, server_default=true())

    # lazy="raise": with async SQLAlchemy an implicit lazy load would fail at
    # runtime anyway, so make every relationship load explicit (selectinload).
    groups: Mapped[list["ApprovalGroup"]] = relationship(
        secondary=group_memberships, back_populates="members", lazy="raise"
    )


class ApprovalGroup(UUIDPrimaryKey, CreatedAt, Base):
    """A set of people who can approve a step, e.g. "Finance" or "Managers"."""

    __tablename__ = "approval_groups"

    name: Mapped[str] = mapped_column(String(100), unique=True)

    members: Mapped[list[User]] = relationship(
        secondary=group_memberships, back_populates="groups", lazy="raise"
    )
