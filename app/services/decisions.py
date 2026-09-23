"""The request state machine: approve, reject and withdraw.

    pending --approve (last step)--> approved
    pending --reject-------------->  rejected
    pending --withdraw------------>  withdrawn
    pending --approve (not last)-->  pending, next step activated

Every transition runs in one transaction: the step changes, the request
update and the audit event are committed together or not at all.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.models import (
    ApprovalRequest,
    AuditAction,
    AuditEvent,
    RequestStatus,
    RequestStep,
    StepStatus,
    User,
)
from app.services.errors import Conflict, Forbidden
from app.services.requests import activate_step, utcnow


async def approve(
    session: AsyncSession,
    request: ApprovalRequest,
    user: User,
    *,
    expected_version: int,
    comment: str | None,
) -> ApprovalRequest:
    step = _begin_decision(request, user, expected_version)
    now = utcnow()
    _record_decision(step, StepStatus.APPROVED, user, now, comment)

    next_step = _step_at(request, step.position + 1)
    if next_step is not None:
        activate_step(next_step, now)
    else:
        _finish(request, RequestStatus.APPROVED, now)

    _add_audit(
        session,
        request,
        user,
        AuditAction.APPROVED,
        step,
        comment,
        {"request_completed": next_step is None},
    )
    await _save(session, request, now)
    return request


async def reject(
    session: AsyncSession,
    request: ApprovalRequest,
    user: User,
    *,
    expected_version: int,
    comment: str,
) -> ApprovalRequest:
    step = _begin_decision(request, user, expected_version)
    now = utcnow()
    _record_decision(step, StepStatus.REJECTED, user, now, comment)
    _finish(request, RequestStatus.REJECTED, now)
    _add_audit(session, request, user, AuditAction.REJECTED, step, comment)
    await _save(session, request, now)
    return request


async def withdraw(
    session: AsyncSession,
    request: ApprovalRequest,
    user: User,
    *,
    expected_version: int,
    comment: str | None,
) -> ApprovalRequest:
    _require_pending(request)
    if request.requester_id != user.id:
        raise Forbidden("Only the requester can withdraw a request")
    _check_version(request, expected_version)

    now = utcnow()
    step = _active_step(request)
    _finish(request, RequestStatus.WITHDRAWN, now)
    _add_audit(session, request, user, AuditAction.WITHDRAWN, step, comment)
    await _save(session, request, now)
    return request


def _begin_decision(request: ApprovalRequest, user: User, expected_version: int) -> RequestStep:
    """Checks shared by approve and reject. Returns the step being decided."""
    _require_pending(request)
    step = _active_step(request)

    # Separation of duties.
    if request.requester_id == user.id:
        raise Forbidden("You can't decide on your own request")
    if step.approver_group_id not in {group.id for group in user.groups}:
        raise Forbidden("Only members of this step's approver group can decide on it")
    if any(s.decided_by_id == user.id for s in request.steps):
        raise Forbidden("You already approved an earlier step of this request")

    _check_version(request, expected_version)
    return step


def _require_pending(request: ApprovalRequest) -> None:
    if request.status != RequestStatus.PENDING:
        raise Conflict(f"Request is already {request.status}")


def _check_version(request: ApprovalRequest, expected_version: int) -> None:
    # The client sends the version it was looking at. If anything changed
    # since (another approver acted, the requester withdrew), refuse rather
    # than apply a decision made on out-of-date information.
    if request.version != expected_version:
        raise Conflict(
            f"Request has changed since you loaded it (now version {request.version}); "
            "reload it and try again"
        )


def _active_step(request: ApprovalRequest) -> RequestStep:
    return next(s for s in request.steps if s.status == StepStatus.ACTIVE)


def _step_at(request: ApprovalRequest, position: int) -> RequestStep | None:
    return next((s for s in request.steps if s.position == position), None)


def _record_decision(
    step: RequestStep, status: StepStatus, user: User, now: datetime, comment: str | None
) -> None:
    step.status = status
    step.decided_by_id = user.id
    step.decided_at = now
    step.comment = comment


def _finish(request: ApprovalRequest, status: RequestStatus, now: datetime) -> None:
    request.status = status
    request.completed_at = now
    for step in request.steps:
        if step.status in (StepStatus.ACTIVE, StepStatus.WAITING):
            step.status = StepStatus.CANCELLED


def _add_audit(
    session: AsyncSession,
    request: ApprovalRequest,
    user: User,
    action: AuditAction,
    step: RequestStep,
    comment: str | None,
    data: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            request_id=request.id,
            actor_id=user.id,
            action=action,
            step_position=step.position,
            comment=comment,
            data=data or {},
        )
    )


async def _save(session: AsyncSession, request: ApprovalRequest, now: datetime) -> None:
    # Always touch the request row, even when only a step changed. That makes
    # SQLAlchemy issue "UPDATE ... WHERE id = :id AND version = :loaded" and
    # bump the version, which is what catches two decisions racing each other.
    request.updated_at = now
    try:
        await session.flush()
    except StaleDataError as exc:
        # Another transaction updated the request after we loaded it, even
        # though our version check passed. Nothing of ours is kept.
        await session.rollback()
        raise Conflict("Request was changed by someone else at the same time; reload it") from exc
