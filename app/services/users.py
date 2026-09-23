from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security import burn_password_check, hash_password, verify_password


class EmailAlreadyRegistered(Exception):
    pass


async def create_user(
    session: AsyncSession, *, email: str, full_name: str, password: str, is_admin: bool = False
) -> User:
    """Adds a user and flushes it. The caller commits."""
    user = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hash_password(password),
        is_admin=is_admin,
        groups=[],
    )
    session.add(user)
    # Rely on the unique constraint rather than checking first: a
    # "SELECT then INSERT" check can race with a concurrent registration.
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyRegistered(email) from exc
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        burn_password_check(password)
        return None

    valid, new_hash = verify_password(password, user.hashed_password)
    if not valid or not user.is_active:
        return None
    if new_hash:
        user.hashed_password = new_hash
    return user
