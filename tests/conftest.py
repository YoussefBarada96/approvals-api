import asyncio
import os
from collections.abc import Callable, Iterator

import pytest

# A separate database from development, because the tests drop, recreate and
# truncate tables. Point the app at it before anything imports app.config.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://approvals:approvals@localhost:5432/approvals_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import pool, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.users import create_user  # noqa: E402

DEFAULT_PASSWORD = "correct-horse-battery"


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Entering the client runs the app's lifespan; leaving it disposes the
    # engine, so no pooled connection outlives this test's event loop.
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def run_sql(url: str, fn: Callable) -> object:
    """Run an async callback against its own short-lived engine."""

    async def runner():
        engine = create_async_engine(url, poolclass=pool.NullPool)
        try:
            async with engine.begin() as conn:
                return await fn(conn)
        finally:
            await engine.dispose()

    return asyncio.run(runner())


def _database_reachable(url: str) -> bool:
    async def ping() -> None:
        engine = create_async_engine(url, poolclass=pool.NullPool)
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


@pytest.fixture(scope="session")
def migrated_database(test_database_url: str) -> str:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    return test_database_url


@pytest.fixture
def db(migrated_database: str, alembic_config: Config) -> str:
    """An up-to-date schema with every table empty."""
    # The migration tests may have downgraded the schema; bring it back.
    command.upgrade(alembic_config, "head")
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    run_sql(migrated_database, lambda conn: conn.execute(text(f"TRUNCATE {tables} CASCADE")))
    return migrated_database


@pytest.fixture
def make_user(db: str) -> Callable:
    def factory(
        email: str = "user@example.com",
        *,
        full_name: str = "Test User",
        password: str = DEFAULT_PASSWORD,
        is_admin: bool = False,
    ):
        async def insert(conn):
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                user = await create_user(
                    session, email=email, full_name=full_name, password=password, is_admin=is_admin
                )
                return user.id

        return run_sql(db, insert)

    return factory


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict[str, str]:
    response = client.post("/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient, make_user: Callable) -> dict[str, str]:
    make_user("admin@example.com", full_name="Ada Admin", is_admin=True)
    return login(client, "admin@example.com")


@pytest.fixture
def user_headers(client: TestClient, make_user: Callable) -> dict[str, str]:
    make_user("user@example.com")
    return login(client, "user@example.com")
