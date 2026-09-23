import uuid
from datetime import timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.security import (
    InvalidToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("a-long-enough-password")

    assert hashed != "a-long-enough-password"
    assert hashed.startswith("$argon2id$")
    assert verify_password("a-long-enough-password", hashed)[0]
    assert not verify_password("wrong-password", hashed)[0]


def test_access_token_roundtrip():
    user_id = uuid.uuid4()

    assert decode_access_token(create_access_token(user_id)) == user_id


def test_expired_token_rejected():
    token = create_access_token(uuid.uuid4(), expires_in=timedelta(seconds=-1))

    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_token_signed_with_other_secret_rejected():
    token = jwt.encode({"sub": str(uuid.uuid4()), "iat": 0, "exp": 2**40}, "x" * 32, "HS256")

    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_unsigned_token_rejected():
    # The classic "alg: none" attack: a token with no signature at all.
    token = jwt.encode({"sub": str(uuid.uuid4()), "iat": 0, "exp": 2**40}, None, "none")

    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_token_without_expiry_rejected():
    settings = get_settings()
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "iat": 0},
        settings.jwt_secret.get_secret_value(),
        settings.jwt_algorithm,
    )

    with pytest.raises(InvalidToken):
        decode_access_token(token)


def test_dev_secret_refused_outside_development():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env="production")


def test_short_or_empty_secret_refused():
    # An empty JWT_SECRET= line in .env must not mean "sign with an empty key".
    for secret in ("", "too-short"):
        with pytest.raises(ValidationError):
            Settings(jwt_secret=secret)


def test_real_secret_accepted_outside_development():
    settings = Settings(app_env="production", jwt_secret="s" * 48)

    assert settings.jwt_secret.get_secret_value() == "s" * 48
