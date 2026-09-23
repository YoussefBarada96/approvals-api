import uuid
from datetime import timedelta

from sqlalchemy import text

from app.security import create_access_token
from tests.conftest import DEFAULT_PASSWORD, login, run_sql


def register(client, email="new@example.com", password=DEFAULT_PASSWORD, full_name="New User"):
    return client.post(
        "/auth/register", json={"email": email, "full_name": full_name, "password": password}
    )


def test_register_creates_user(client, db):
    response = register(client, email="New.Person@Example.com")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new.person@example.com"
    assert body["is_admin"] is False
    assert body["groups"] == []
    assert "password" not in body and "hashed_password" not in body


def test_register_rejects_duplicate_email_case_insensitively(client, db):
    register(client, email="dup@example.com")

    response = register(client, email="DUP@example.com")

    assert response.status_code == 409


def test_register_rejects_short_password(client, db):
    response = register(client, password="short")

    assert response.status_code == 422


def test_register_cannot_make_admin(client, db):
    response = client.post(
        "/auth/register",
        json={
            "email": "sneaky@example.com",
            "full_name": "Sneaky",
            "password": DEFAULT_PASSWORD,
            "is_admin": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["is_admin"] is False


def test_login_and_read_me(client, make_user):
    make_user("me@example.com", full_name="Me")

    response = client.get("/users/me", headers=login(client, "ME@example.com"))

    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_login_wrong_password_and_unknown_email_look_the_same(client, make_user):
    make_user("known@example.com")

    wrong_password = client.post(
        "/auth/token", data={"username": "known@example.com", "password": "not-the-password"}
    )
    unknown_email = client.post(
        "/auth/token", data={"username": "nobody@example.com", "password": "not-the-password"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_me_requires_token(client, db):
    response = client.get("/users/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_garbage_token(client, db):
    response = client.get("/users/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_me_rejects_expired_token(client, make_user):
    user_id = make_user("expired@example.com")
    token = create_access_token(user_id, expires_in=timedelta(seconds=-1))

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_token_for_deleted_user_rejected(client, db):
    token = create_access_token(uuid.uuid4())

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_deactivated_user_locked_out_immediately(client, db, make_user):
    make_user("leaver@example.com")
    headers = login(client, "leaver@example.com")

    run_sql(
        db,
        lambda conn: conn.execute(
            text("UPDATE users SET is_active = false WHERE email = 'leaver@example.com'")
        ),
    )

    # The token hasn't expired, but it stops working at once...
    assert client.get("/users/me", headers=headers).status_code == 401
    # ...and a new one can't be obtained.
    relogin = client.post(
        "/auth/token", data={"username": "leaver@example.com", "password": DEFAULT_PASSWORD}
    )
    assert relogin.status_code == 401
