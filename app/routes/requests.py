import uuid

from fastapi import APIRouter, status

from app.deps import CurrentUser, SessionDep
from app.schemas.requests import AuditEventOut, RequestCreate, RequestOut
from app.services import requests

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_request(body: RequestCreate, user: CurrentUser, session: SessionDep) -> RequestOut:
    request = await requests.submit_request(session, body, user)
    await session.commit()
    return RequestOut.model_validate(request)


@router.get("/{request_id}")
async def get_request(request_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RequestOut:
    return RequestOut.model_validate(await requests.get_visible_request(session, request_id, user))


@router.get("/{request_id}/history")
async def get_history(
    request_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[AuditEventOut]:
    request = await requests.get_visible_request(session, request_id, user)
    return [AuditEventOut.model_validate(e) for e in await requests.get_history(session, request)]
