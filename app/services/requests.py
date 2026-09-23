import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ApprovalRequest,
    AuditAction,
    AuditEvent,
    RequestStep,
    StepStatus,
    User,
)
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
    _activate(steps[0], now)

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


def _activate(step: RequestStep, now: datetime) -> None:
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


async def get_history(session: AsyncSession, request: ApprovalRequest) -> list[AuditEvent]:
    events = await session.scalars(
        select(AuditEvent).where(AuditEvent.request_id == request.id).order_by(AuditEvent.id)
    )
    return list(events)
