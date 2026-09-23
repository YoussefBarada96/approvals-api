from fastapi import APIRouter

from app.deps import CurrentUser
from app.schemas.users import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def read_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
