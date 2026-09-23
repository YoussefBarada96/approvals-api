import uuid

from fastapi import APIRouter, status

from app.deps import AdminUser, CurrentUser, SessionDep
from app.schemas.workflows import StepsReplace, WorkflowCreate, WorkflowOut, WorkflowUpdate
from app.services import workflows

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("")
async def list_workflows(
    user: CurrentUser, session: SessionDep, include_inactive: bool = False
) -> list[WorkflowOut]:
    """Active workflows. Admins can pass include_inactive=true to see all."""
    items = await workflows.list_workflows(
        session, include_inactive=include_inactive and user.is_admin
    )
    return [WorkflowOut.model_validate(w) for w in items]


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: uuid.UUID, _: CurrentUser, session: SessionDep) -> WorkflowOut:
    return WorkflowOut.model_validate(await workflows.get_workflow(session, workflow_id))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workflow(
    body: WorkflowCreate, admin: AdminUser, session: SessionDep
) -> WorkflowOut:
    workflow = await workflows.create_workflow(session, body, admin)
    await session.commit()
    return WorkflowOut.model_validate(workflow)


@router.patch("/{workflow_id}")
async def update_workflow(
    workflow_id: uuid.UUID, body: WorkflowUpdate, _: AdminUser, session: SessionDep
) -> WorkflowOut:
    """Rename, edit the description, or deactivate. Workflows are deactivated
    rather than deleted, because past requests still reference them."""
    workflow = await workflows.update_workflow(session, workflow_id, body)
    await session.commit()
    return WorkflowOut.model_validate(workflow)


@router.put("/{workflow_id}/steps")
async def replace_steps(
    workflow_id: uuid.UUID, body: StepsReplace, _: AdminUser, session: SessionDep
) -> WorkflowOut:
    workflow = await workflows.replace_steps(session, workflow_id, body.steps)
    await session.commit()
    return WorkflowOut.model_validate(workflow)
