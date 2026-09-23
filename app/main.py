from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.db import engine
from app.routes import auth, groups, health, requests, users, workflows
from app.services.errors import DomainError


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


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(groups.router)
app.include_router(workflows.router)
app.include_router(requests.router)
