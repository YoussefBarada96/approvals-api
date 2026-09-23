"""SLA escalation: find active steps past their deadline and flag them.

Postgres is the job queue. Overdue steps are claimed with
SELECT ... FOR UPDATE SKIP LOCKED, so any number of workers can run side by
side: each skips rows another worker has locked instead of waiting for them
or escalating them twice.
"""

from datetime import datetime

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditEvent, RequestStep, StepStatus


async def claim_overdue(
    session: AsyncSession, *, now: datetime, batch_size: int
) -> list[RequestStep]:
    """Lock and return up to batch_size overdue steps, oldest deadline first.
    The locks are held until the caller's transaction ends."""
    query = (
        select(RequestStep)
        .where(
            # Inlined rather than bound as a parameter: Postgres can only use
            # the partial index "WHERE status = 'active' AND escalated_at IS
            # NULL" when it can see the literal value at planning time.
            RequestStep.status == literal(StepStatus.ACTIVE.value, literal_execute=True),
            RequestStep.escalated_at.is_(None),
            RequestStep.due_at <= now,
        )
        .order_by(RequestStep.due_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    return list(await session.scalars(query))


async def escalate_overdue(session: AsyncSession, *, now: datetime, batch_size: int = 50) -> int:
    """Escalate one batch and commit. Returns how many steps were escalated.

    Marking the step and writing its audit event happen in one transaction,
    and claimed rows must have escalated_at IS NULL, so each step is
    escalated exactly once even if a worker crashes mid-batch.
    """
    steps = await claim_overdue(session, now=now, batch_size=batch_size)
    for step in steps:
        # Only the step is touched, not the request row, so escalation doesn't
        # bump the request's version and invalidate an approver's in-flight
        # decision.
        step.escalated_at = now
        session.add(
            AuditEvent(
                request_id=step.request_id,
                actor_id=None,  # the system
                action=AuditAction.ESCALATED,
                step_position=step.position,
                data={
                    "approver_group_id": str(step.approver_group_id),
                    "due_at": step.due_at.isoformat(),
                    "overdue_seconds": int((now - step.due_at).total_seconds()),
                },
            )
        )
    await session.commit()
    return len(steps)
