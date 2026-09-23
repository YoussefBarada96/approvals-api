import asyncio

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine


def test_migrations_upgrade_and_downgrade_cleanly(alembic_config):
    # Run the full cycle twice: a downgrade that leaves something behind
    # makes the second upgrade fail.
    for _ in range(2):
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, "head")


def test_migrations_match_models(alembic_config):
    command.upgrade(alembic_config, "head")
    # Fails if autogenerate would produce a new migration, i.e. someone
    # changed a model without writing the migration for it.
    command.check(alembic_config)


def test_audit_events_are_append_only(alembic_config, test_database_url):
    command.upgrade(alembic_config, "head")

    async def scenario() -> None:
        engine = create_async_engine(test_database_url)
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await _insert_audit_event(conn)
                    for statement in (
                        "UPDATE audit_events SET comment = 'rewritten'",
                        "DELETE FROM audit_events",
                    ):
                        with pytest.raises(DBAPIError, match="append-only"):
                            async with conn.begin_nested():
                                await conn.execute(text(statement))
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


async def _insert_audit_event(conn) -> None:
    user_id = await conn.scalar(
        text(
            "INSERT INTO users (email, full_name, hashed_password) "
            "VALUES ('audit@example.com', 'Audit Test', 'x') RETURNING id"
        )
    )
    workflow_id = await conn.scalar(
        text("INSERT INTO workflows (name, created_by_id) VALUES ('Audit test', :u) RETURNING id"),
        {"u": user_id},
    )
    request_id = await conn.scalar(
        text(
            "INSERT INTO approval_requests (workflow_id, requester_id, title, version) "
            "VALUES (:w, :u, 'Test request', 1) RETURNING id"
        ),
        {"w": workflow_id, "u": user_id},
    )
    await conn.execute(
        text(
            "INSERT INTO audit_events (request_id, actor_id, action) VALUES (:r, :u, 'submitted')"
        ),
        {"r": request_id, "u": user_id},
    )
