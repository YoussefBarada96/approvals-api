import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi import status as http_status

from app.deps import CurrentUser, SessionDep
from app.models import RequestStatus
from app.schemas.requests import (
    AuditEventOut,
    DecisionIn,
    RejectIn,
    RequestCreate,
    RequestOut,
    RequestPage,
    RequestSummary,
)
from app.services import decisions, requests

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("", status_code=http_status.HTTP_201_CREATED)
async def submit_request(body: RequestCreate, user: CurrentUser, session: SessionDep) -> RequestOut:
    request = await requests.submit_request(session, body, user)
    await session.commit()
    return RequestOut.model_validate(request)


@router.get("")
async def list_requests(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
    status: RequestStatus | None = None,
    workflow_id: uuid.UUID | None = None,
    mine: bool = False,
    assigned_to_me: bool = False,
) -> RequestPage:
    """Requests visible to you, newest first.

    - `mine=true`: only requests you submitted.
    - `assigned_to_me=true`: requests waiting on a decision you're allowed to make.
    - Pass the previous response's `next_cursor` as `cursor` for the next page.
    """
    items, next_cursor = await requests.list_requests(
        session,
        user,
        limit=limit,
        cursor=cursor,
        status=status,
        workflow_id=workflow_id,
        mine=mine,
        assigned_to_me=assigned_to_me,
    )
    return RequestPage(
        items=[RequestSummary.from_request(r) for r in items], next_cursor=next_cursor
    )


@router.get("/{request_id}")
async def get_request(request_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RequestOut:
    return RequestOut.model_validate(await requests.get_visible_request(session, request_id, user))


@router.get("/{request_id}/history")
async def get_history(
    request_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[AuditEventOut]:
    request = await requests.get_visible_request(session, request_id, user)
    return [AuditEventOut.model_validate(e) for e in await requests.get_history(session, request)]


@router.post("/{request_id}/approve")
async def approve(
    request_id: uuid.UUID, body: DecisionIn, user: CurrentUser, session: SessionDep
) -> RequestOut:
    """Approve the current step. Approving the last step approves the request."""
    request = await requests.get_visible_request(session, request_id, user)
    await decisions.approve(
        session, request, user, expected_version=body.version, comment=body.comment
    )
    await session.commit()
    return RequestOut.model_validate(request)


@router.post("/{request_id}/reject")
async def reject(
    request_id: uuid.UUID, body: RejectIn, user: CurrentUser, session: SessionDep
) -> RequestOut:
    """Reject the request at its current step. A comment is required."""
    request = await requests.get_visible_request(session, request_id, user)
    await decisions.reject(
        session, request, user, expected_version=body.version, comment=body.comment
    )
    await session.commit()
    return RequestOut.model_validate(request)


@router.post("/{request_id}/withdraw")
async def withdraw(
    request_id: uuid.UUID, body: DecisionIn, user: CurrentUser, session: SessionDep
) -> RequestOut:
    """The requester cancels their own pending request."""
    request = await requests.get_visible_request(session, request_id, user)
    await decisions.withdraw(
        session, request, user, expected_version=body.version, comment=body.comment
    )
    await session.commit()
    return RequestOut.model_validate(request)
