import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ApprovalRequest,
    AuditAction,
    AuditEvent,
    RequestStatus,
    RequestStep,
    StepStatus,
    User,
)
from app.pagination import decode_cursor, encode_cursor
from app.schemas.requests import RequestCreate
from app.services.errors import InvalidInput, NotFound
from app.services.workflows import get_workflow


def utcnow() -> datetime:
    return datetime.now(UTC)


async def submit_request(
    session: AsyncSession, body: RequestCreate, requester: User
) -> ApprovalRequest:
    workflow = await get_workflow(session, body.workflow_id)
    if not workflow.is_active:
        raise InvalidInput("Workflow is not active")

    now = utcnow()
    # Copy the workflow's steps onto the request. Step 1 starts immediately
    # and gets its deadline; the others wait their turn.
    steps = [
        RequestStep(
            position=step.position,
            name=step.name,
            approver_group_id=step.approver_group_id,
            sla_hours=step.sla_hours,
            status=StepStatus.WAITING,
        )
        for step in workflow.steps
    ]
    activate_step(steps[0], now)

    request = ApprovalRequest(
        workflow_id=workflow.id,
        requester_id=requester.id,
        title=body.title,
        details=body.details,
        steps=steps,
    )
    session.add(request)
    await session.flush()

    session.add(
        AuditEvent(
            request_id=request.id,
            actor_id=requester.id,
            action=AuditAction.SUBMITTED,
            data={"workflow_id": str(workflow.id), "workflow_name": workflow.name},
        )
    )
    await session.flush()
    return request


def activate_step(step: RequestStep, now: datetime) -> None:
    step.status = StepStatus.ACTIVE
    step.activated_at = now
    step.due_at = now + timedelta(hours=step.sla_hours)


def can_view(user: User, request: ApprovalRequest) -> bool:
    """Requester, admins, and members of any group with a step on the request."""
    if user.is_admin or request.requester_id == user.id:
        return True
    group_ids = {group.id for group in user.groups}
    return any(step.approver_group_id in group_ids for step in request.steps)


async def get_visible_request(
    session: AsyncSession, request_id: uuid.UUID, user: User
) -> ApprovalRequest:
    request = await session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == request_id)
        .options(selectinload(ApprovalRequest.steps))
    )
    # 404 rather than 403 for requests the user can't see, so ids can't be
    # probed to learn which requests exist.
    if request is None or not can_view(user, request):
        raise NotFound("Request not found")
    return request


async def list_requests(
    session: AsyncSession,
    user: User,
    *,
    limit: int,
    cursor: str | None = None,
    status: RequestStatus | None = None,
    workflow_id: uuid.UUID | None = None,
    mine: bool = False,
    assigned_to_me: bool = False,
) -> tuple[list[ApprovalRequest], str | None]:
    group_ids = [group.id for group in user.groups]
    query = select(ApprovalRequest).options(selectinload(ApprovalRequest.steps))

    # Same visibility rule as can_view(), expressed in SQL.
    if not user.is_admin:
        query = query.where(
            or_(
                ApprovalRequest.requester_id == user.id,
                _has_step(RequestStep.approver_group_id.in_(group_ids)),
            )
        )
    if status is not None:
        query = query.where(ApprovalRequest.status == status)
    if workflow_id is not None:
        query = query.where(ApprovalRequest.workflow_id == workflow_id)
    if mine:
        query = query.where(ApprovalRequest.requester_id == user.id)
    if assigned_to_me:
        # Requests this user could approve right now, applying the same
        # separation-of-duties rules as the approve endpoint.
        query = query.where(
            _has_step(
                RequestStep.status == StepStatus.ACTIVE,
                RequestStep.approver_group_id.in_(group_ids),
            ),
            ApprovalRequest.requester_id != user.id,
            ~_has_step(RequestStep.decided_by_id == user.id),
        )
    if cursor is not None:
        created_at, request_id = decode_cursor(cursor)
        query = query.where(
            tuple_(ApprovalRequest.created_at, ApprovalRequest.id) < tuple_(created_at, request_id)
        )

    # Fetch one extra row to learn whether another page exists.
    rows = list(
        await session.scalars(
            query.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc()).limit(
                limit + 1
            )
        )
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return page, next_cursor


def _has_step(*conditions):
    return exists().where(RequestStep.request_id == ApprovalRequest.id, *conditions)


async def get_history(session: AsyncSession, request: ApprovalRequest) -> list[AuditEvent]:
    events = await session.scalars(
        select(AuditEvent).where(AuditEvent.request_id == request.id).order_by(AuditEvent.id)
    )
    return list(events)
