import asyncio

import pytest

from app import cli
from app.config import get_settings
from tests.conftest import login


@pytest.fixture
def seeded(db):
    asyncio.run(cli._run(cli.seed_demo()))


def test_seed_demo_creates_a_working_scenario(client, seeded):
    alice = login(client, "alice@example.com", cli.DEMO_PASSWORD)
    mo = login(client, "mo@example.com", cli.DEMO_PASSWORD)

    workflow = client.get("/workflows", headers=alice).json()[0]
    request = client.post(
        "/requests", json={"workflow_id": workflow["id"], "title": "Monitor"}, headers=alice
    ).json()
    approved = client.post(f"/requests/{request['id']}/approve", json={"version": 1}, headers=mo)

    assert workflow["name"] == cli.DEMO_WORKFLOW
    assert [g["name"] for g in client.get("/users/me", headers=mo).json()["groups"]] == ["Managers"]
    assert approved.status_code == 200
    assert approved.json()["steps"][1]["status"] == "active"


def test_seed_demo_refuses_to_run_twice(seeded):
    with pytest.raises(cli.AlreadySeeded):
        asyncio.run(cli._run(cli.seed_demo()))


def test_seed_demo_refused_outside_development(monkeypatch, capsys):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "s" * 48)
    get_settings.cache_clear()
    try:
        assert cli.main(["seed-demo"]) == 1
    finally:
        get_settings.cache_clear()
    assert "APP_ENV=development" in capsys.readouterr().err


def test_create_admin(client, db, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "a-strong-admin-password")

    assert cli.main(["create-admin", "--email", "boss@example.com", "--name", "Boss"]) == 0

    me = client.get(
        "/users/me", headers=login(client, "boss@example.com", "a-strong-admin-password")
    )
    assert me.json()["is_admin"] is True
