import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.config import get_settings

# Argon2id with pwdlib's recommended parameters.
password_hash = PasswordHash.recommended()

# Verified against when an email isn't registered, so a failed login takes the
# same time whether or not the account exists (no user enumeration by timing).
_DUMMY_HASH = password_hash.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash). new_hash is set when the stored hash uses
    outdated parameters and should be replaced, so hashes upgrade on login."""
    return password_hash.verify_and_update(password, hashed)


def burn_password_check(password: str) -> None:
    password_hash.verify(password, _DUMMY_HASH)


class InvalidToken(Exception):
    pass


def create_access_token(user_id: uuid.UUID, expires_in: timedelta | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    expires_in = expires_in or timedelta(minutes=settings.access_token_expire_minutes)
    claims = {"sub": str(user_id), "iat": now, "exp": now + expires_in}
    return jwt.encode(claims, settings.jwt_secret.get_secret_value(), settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            # Pin the algorithm: never let the token header choose it.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidToken from exc
