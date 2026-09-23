from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# pool_pre_ping checks a pooled connection is still alive before handing it out,
# so a database restart doesn't surface as errors on the next few requests.
engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed afterwards."""
    async with SessionLocal() as session:
        yield session
