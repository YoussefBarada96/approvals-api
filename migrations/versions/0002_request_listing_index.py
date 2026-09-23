"""Index approval_requests for keyset pagination.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_approval_requests_created_at_id", "approval_requests", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_approval_requests_created_at_id", table_name="approval_requests")
