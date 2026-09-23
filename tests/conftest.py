import asyncio
import os
from collections.abc import Iterator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.main import app

# A separate database from development, because the migration tests drop and
# recreate the whole schema.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://approvals:approvals@localhost:5432/approvals_test",
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _database_reachable(url: str) -> bool:
    async def ping() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(asyncio.wait_for(ping(), timeout=5))
    except Exception:
        return False
    return True


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Tests that need Postgres use this fixture. Locally they're skipped when
    no database is running; CI sets REQUIRE_DATABASE=1 so they fail instead."""
    if not _database_reachable(TEST_DATABASE_URL):
        message = f"test database not reachable at {TEST_DATABASE_URL}"
        if os.environ.get("REQUIRE_DATABASE") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return TEST_DATABASE_URL


@pytest.fixture
def alembic_config(test_database_url: str) -> Config:
    config = Config("alembic.ini")
    # ConfigParser treats "%" as interpolation, so escape it.
    config.set_main_option("sqlalchemy.url", test_database_url.replace("%", "%%"))
    return config
