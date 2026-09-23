"""Initial schema: users, groups, workflows, requests and the audit trail.

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def in_list(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "approval_groups",
        uuid_pk(),
        sa.Column("name", sa.String(100), nullable=False),
        created_at(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_approval_groups_name")),
    )

    op.create_table(
        "group_memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_group_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["approval_groups.id"],
            name=op.f("fk_group_memberships_group_id_approval_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id", name=op.f("pk_group_memberships")),
    )

    op.create_table(
        "workflows",
        uuid_pk(),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        created_at(),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], name=op.f("fk_workflows_created_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflows")),
        sa.UniqueConstraint("name", name=op.f("uq_workflows_name")),
    )

    op.create_table(
        "workflow_steps",
        uuid_pk(),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("approver_group_id", sa.Uuid(), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_workflow_steps_position_positive")),
        sa.CheckConstraint("sla_hours > 0", name=op.f("ck_workflow_steps_sla_hours_positive")),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_workflow_steps_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approver_group_id"],
            ["approval_groups.id"],
            name=op.f("fk_workflow_steps_approver_group_id_approval_groups"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_steps")),
        sa.UniqueConstraint(
            "workflow_id", "position", name=op.f("uq_workflow_steps_workflow_id_position")
        ),
    )

    op.create_table(
        "approval_requests",
        uuid_pk(),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        created_at(),
        sa.CheckConstraint(
            in_list("status", ["pending", "approved", "rejected", "withdrawn"]),
            name=op.f("ck_approval_requests_request_status"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("fk_approval_requests_workflow_id_workflows"),
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"], ["users.id"], name=op.f("fk_approval_requests_requester_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
    )
    op.create_index(op.f("ix_approval_requests_workflow_id"), "approval_requests", ["workflow_id"])
    op.create_index(
        op.f("ix_approval_requests_requester_id"), "approval_requests", ["requester_id"]
    )
    op.create_index(op.f("ix_approval_requests_status"), "approval_requests", ["status"])

    op.create_table(
        "request_steps",
        uuid_pk(),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("approver_group_id", sa.Uuid(), nullable=False),
        sa.Column("sla_hours", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="waiting", nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.CheckConstraint("position >= 1", name=op.f("ck_request_steps_position_positive")),
        sa.CheckConstraint("sla_hours > 0", name=op.f("ck_request_steps_sla_hours_positive")),
        sa.CheckConstraint(
            in_list("status", ["waiting", "active", "approved", "rejected", "cancelled"]),
            name=op.f("ck_request_steps_step_status"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["approval_requests.id"],
            name=op.f("fk_request_steps_request_id_approval_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approver_group_id"],
            ["approval_groups.id"],
            name=op.f("fk_request_steps_approver_group_id_approval_groups"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"], ["users.id"], name=op.f("fk_request_steps_decided_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_steps")),
        sa.UniqueConstraint(
            "request_id", "position", name=op.f("uq_request_steps_request_id_position")
        ),
    )
    op.create_index(
        "ix_request_steps_overdue",
        "request_steps",
        ["due_at"],
        postgresql_where=sa.text("status = 'active' AND escalated_at IS NULL"),
    )
    op.create_index(
        "ix_request_steps_active_group",
        "request_steps",
        ["approver_group_id"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("step_position", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        created_at(),
        sa.CheckConstraint(
            in_list("action", ["submitted", "approved", "rejected", "withdrawn", "escalated"]),
            name=op.f("ck_audit_events_audit_action"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["approval_requests.id"],
            name=op.f("fk_audit_events_request_id_approval_requests"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_audit_events_actor_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_request_id_id", "audit_events", ["request_id", "id"])

    # Make the audit trail append-only at the database level.
    op.execute(
        """
        CREATE FUNCTION audit_events_forbid_changes() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_forbid_changes()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_forbid_changes()")
    op.drop_table("audit_events")
    op.drop_table("request_steps")
    op.drop_table("approval_requests")
    op.drop_table("workflow_steps")
    op.drop_table("workflows")
    op.drop_table("group_memberships")
    op.drop_table("approval_groups")
    op.drop_table("users")
