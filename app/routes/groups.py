import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, SessionDep, require_admin
from app.models import ApprovalGroup, User, group_memberships
from app.schemas.users import GroupCreate, GroupOut

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get("")
async def list_groups(_: CurrentUser, session: SessionDep) -> list[GroupOut]:
    groups = await session.scalars(select(ApprovalGroup).order_by(ApprovalGroup.name))
    return [GroupOut.model_validate(g) for g in groups]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_group(body: GroupCreate, session: SessionDep) -> GroupOut:
    group = ApprovalGroup(name=body.name)
    session.add(group)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "A group with this name exists") from None
    return GroupOut.model_validate(group)


async def _ensure_group_and_user(session: SessionDep, group_id: uuid.UUID, user_id: uuid.UUID):
    if await session.get(ApprovalGroup, group_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if await session.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")


@router.put(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def add_member(group_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep) -> Response:
    """Idempotent: adding someone who is already a member is not an error."""
    await _ensure_group_and_user(session, group_id, user_id)
    await session.execute(
        insert(group_memberships)
        .values(group_id=group_id, user_id=user_id)
        .on_conflict_do_nothing()
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def remove_member(group_id: uuid.UUID, user_id: uuid.UUID, session: SessionDep) -> Response:
    await _ensure_group_and_user(session, group_id, user_id)
    await session.execute(
        delete(group_memberships).where(
            group_memberships.c.group_id == group_id, group_memberships.c.user_id == user_id
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
