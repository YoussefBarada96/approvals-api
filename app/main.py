from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import engine
from app.routes import health


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # Close pooled database connections cleanly on shutdown.
    await engine.dispose()


app = FastAPI(
    title="Approvals API",
    version="0.1.0",
    description="Multi-step approval workflows with an audit trail and SLA escalation.",
    lifespan=lifespan,
)
app.include_router(health.router)
