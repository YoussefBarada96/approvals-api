from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.deps import SessionDep
from app.schemas.users import Token, UserCreate, UserOut
from app.security import create_access_token
from app.services.users import EmailAlreadyRegistered, authenticate, create_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, session: SessionDep) -> UserOut:
    try:
        user = await create_user(
            session, email=body.email, full_name=body.full_name, password=body.password
        )
    except EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from None
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/token")
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    """OAuth2 password flow. The form's "username" field takes the email, which
    is what makes the Authorize button on /docs work."""
    user = await authenticate(session, form.username, form.password)
    if user is None:
        # Same response for unknown email and wrong password.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await session.commit()  # persists an upgraded password hash, if any
    return Token(access_token=create_access_token(user.id))
