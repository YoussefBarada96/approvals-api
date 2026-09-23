import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ApprovalGroup, User, Workflow, WorkflowStep
from app.schemas.workflows import StepIn, WorkflowCreate, WorkflowUpdate
from app.services.errors import Conflict, InvalidInput, NotFound


async def get_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> Workflow:
    workflow = await session.scalar(
        select(Workflow).where(Workflow.id == workflow_id).options(selectinload(Workflow.steps))
    )
    if workflow is None:
        raise NotFound("Workflow not found")
    return workflow


async def list_workflows(session: AsyncSession, *, include_inactive: bool) -> list[Workflow]:
    query = select(Workflow).options(selectinload(Workflow.steps)).order_by(Workflow.name)
    if not include_inactive:
        query = query.where(Workflow.is_active)
    return list(await session.scalars(query))


async def create_workflow(session: AsyncSession, body: WorkflowCreate, admin: User) -> Workflow:
    await _check_groups_exist(session, body.steps)
    workflow = Workflow(
        name=body.name,
        description=body.description,
        created_by_id=admin.id,
        steps=_build_steps(body.steps),
    )
    session.add(workflow)
    await _flush_or_conflict(session)
    return workflow


async def update_workflow(
    session: AsyncSession, workflow_id: uuid.UUID, body: WorkflowUpdate
) -> Workflow:
    workflow = await get_workflow(session, workflow_id)
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(workflow, field, value)
    await _flush_or_conflict(session)
    return workflow


async def replace_steps(
    session: AsyncSession, workflow_id: uuid.UUID, steps: list[StepIn]
) -> Workflow:
    """Replace every step. Requests already submitted keep their own copy of
    the old steps, so this only affects requests submitted afterwards."""
    workflow = await get_workflow(session, workflow_id)
    await _check_groups_exist(session, steps)
    # Delete the old rows before inserting the new ones. In one flush the unit
    # of work would insert first and trip the (workflow_id, position) unique
    # constraint.
    workflow.steps.clear()
    await session.flush()
    workflow.steps.extend(_build_steps(steps))
    await session.flush()
    return workflow


def _build_steps(steps: list[StepIn]) -> list[WorkflowStep]:
    return [
        WorkflowStep(
            position=position,
            name=step.name,
            approver_group_id=step.approver_group_id,
            sla_hours=step.sla_hours,
        )
        for position, step in enumerate(steps, start=1)
    ]


async def _check_groups_exist(session: AsyncSession, steps: list[StepIn]) -> None:
    wanted = {step.approver_group_id for step in steps}
    found = set(await session.scalars(select(ApprovalGroup.id).where(ApprovalGroup.id.in_(wanted))))
    missing = wanted - found
    if missing:
        raise InvalidInput(f"Unknown approver group(s): {', '.join(sorted(map(str, missing)))}")


async def _flush_or_conflict(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        # Groups are checked beforehand, so the only expected violation is
        # the unique workflow name.
        raise Conflict("A workflow with this name exists") from exc
