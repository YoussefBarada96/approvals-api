import asyncio
import uuid

import pytest
from sqlalchemy import pool, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload

from app.models import User
from app.services import decisions
from app.services.errors import Conflict
from app.services.requests import get_visible_request
from tests.conftest import add_member, login


def submit(client, headers, workflow_id):
    response = client.post(
        "/requests",
        json={"workflow_id": workflow_id, "title": "New laptop", "details": {"amount": 1800}},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def act(client, headers, request, action, comment=None, version=None):
    body = {"version": version or request["version"]}
    if comment is not None:
        body["comment"] = comment
    return client.post(f"/requests/{request['id']}/{action}", json=body, headers=headers)


def history_actions(client, headers, request_id):
    events = client.get(f"/requests/{request_id}/history", headers=headers).json()
    return [(e["action"], e["step_position"]) for e in events]


@pytest.fixture
def pending(client, user_headers, purchase_workflow):
    return submit(client, user_headers, purchase_workflow["id"])


def test_full_approval(client, user_headers, purchase_workflow, pending):
    after_manager = act(client, purchase_workflow["manager"], pending, "approve", "Looks fine")

    assert after_manager.status_code == 200
    body = after_manager.json()
    assert body["status"] == "pending"
    assert body["version"] == 2
    assert [s["status"] for s in body["steps"]] == ["approved", "active"]
    assert body["steps"][0]["comment"] == "Looks fine"
    assert body["steps"][1]["due_at"] is not None

    after_finance = act(client, purchase_workflow["finance_approver"], body, "approve")

    assert after_finance.status_code == 200
    done = after_finance.json()
    assert done["status"] == "approved"
    assert done["completed_at"] is not None
    assert [s["status"] for s in done["steps"]] == ["approved", "approved"]
    assert history_actions(client, user_headers, pending["id"]) == [
        ("submitted", None),
        ("approved", 1),
        ("approved", 2),
    ]


def test_reject_cancels_remaining_steps(client, user_headers, purchase_workflow, pending):
    response = act(client, purchase_workflow["manager"], pending, "reject", "Over budget")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert [s["status"] for s in body["steps"]] == ["rejected", "cancelled"]
    assert history_actions(client, user_headers, pending["id"])[-1] == ("rejected", 1)


def test_reject_requires_a_reason(client, purchase_workflow, pending):
    assert act(client, purchase_workflow["manager"], pending, "reject").status_code == 422
    assert act(client, purchase_workflow["manager"], pending, "reject", "  ").status_code == 422


def test_only_the_current_steps_group_can_decide(client, purchase_workflow, pending):
    # Finance's step hasn't started yet.
    response = act(client, purchase_workflow["finance_approver"], pending, "approve")

    assert response.status_code == 403


def test_admins_are_not_automatically_approvers(client, admin_headers, pending):
    assert act(client, admin_headers, pending, "approve").status_code == 403


def test_requester_cannot_approve_own_request(client, admin_headers, make_user, purchase_workflow):
    manager_id = make_user("self.approver@example.com")
    add_member(client, admin_headers, purchase_workflow["managers"], manager_id)
    headers = login(client, "self.approver@example.com")
    own = submit(client, headers, purchase_workflow["id"])

    response = act(client, headers, own, "approve")

    assert response.status_code == 403
    assert "own request" in response.json()["detail"]


def test_one_person_cannot_approve_two_steps(
    client, admin_headers, make_user, purchase_workflow, pending
):
    both_id = make_user("both@example.com")
    add_member(client, admin_headers, purchase_workflow["managers"], both_id)
    add_member(client, admin_headers, purchase_workflow["finance"], both_id)
    both = login(client, "both@example.com")

    after_step_1 = act(client, both, pending, "approve").json()
    response = act(client, both, after_step_1, "approve")

    assert response.status_code == 403
    assert "earlier step" in response.json()["detail"]


def test_stale_version_rejected_and_nothing_changes(
    client, user_headers, purchase_workflow, pending
):
    act(client, user_headers, pending, "withdraw")  # bumps the version to 2

    # The manager is still looking at version 1.
    response = act(client, purchase_workflow["manager"], pending, "approve", version=1)

    assert response.status_code == 409
    current = client.get(f"/requests/{pending['id']}", headers=user_headers).json()
    assert current["status"] == "withdrawn"
    assert current["steps"][0]["decided_by_id"] is None


def test_cannot_act_on_finished_request(client, purchase_workflow, pending):
    rejected = act(client, purchase_workflow["manager"], pending, "reject", "No").json()

    response = act(client, purchase_workflow["manager"], rejected, "approve")

    assert response.status_code == 409
    assert "already rejected" in response.json()["detail"]


def test_requester_withdraws(client, user_headers, pending):
    response = act(client, user_headers, pending, "withdraw", "Bought it myself")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "withdrawn"
    assert [s["status"] for s in body["steps"]] == ["cancelled", "cancelled"]
    assert history_actions(client, user_headers, pending["id"])[-1] == ("withdrawn", 1)


def test_only_requester_can_withdraw(client, purchase_workflow, pending):
    assert act(client, purchase_workflow["manager"], pending, "withdraw").status_code == 403


def test_outsiders_get_404(client, make_user, pending):
    make_user("bystander@example.com")
    bystander = login(client, "bystander@example.com")

    assert act(client, bystander, pending, "approve").status_code == 404
    assert act(client, bystander, pending, "withdraw").status_code == 404


def test_unknown_request_404(client, user_headers, db):
    fake = {"id": str(uuid.uuid4()), "version": 1}

    assert act(client, user_headers, fake, "approve").status_code == 404


def test_concurrent_approvals_only_one_wins(
    client, admin_headers, make_user, purchase_workflow, pending, db
):
    """Two managers load version 1 at the same moment and both approve. Both
    pass the version check in Python; the database's version check on UPDATE
    must stop the second one."""
    second_manager_id = make_user("manager2@example.com")
    add_member(client, admin_headers, purchase_workflow["managers"], second_manager_id)
    request_id = uuid.UUID(pending["id"])

    async def race() -> list[str]:
        engine = create_async_engine(db, poolclass=pool.NullPool)
        try:
            async with (
                AsyncSession(engine, expire_on_commit=False) as first,
                AsyncSession(engine, expire_on_commit=False) as second,
            ):
                sessions = [first, second]
                users = [
                    await _load_user(first, "manager@example.com"),
                    await _load_user(second, "manager2@example.com"),
                ]
                # Both load the request before either decides.
                loaded = [
                    await get_visible_request(s, request_id, u)
                    for s, u in zip(sessions, users, strict=True)
                ]
                outcomes = []
                for session, user, request in zip(sessions, users, loaded, strict=True):
                    try:
                        await decisions.approve(
                            session, request, user, expected_version=1, comment=None
                        )
                        await session.commit()
                        outcomes.append("approved")
                    except Conflict:
                        outcomes.append("conflict")
                return outcomes
        finally:
            await engine.dispose()

    assert asyncio.run(race()) == ["approved", "conflict"]

    events = client.get(f"/requests/{pending['id']}/history", headers=admin_headers).json()
    assert [e["action"] for e in events] == ["submitted", "approved"]  # no half-saved decision


async def _load_user(session: AsyncSession, email: str) -> User:
    return await session.scalar(
        select(User).where(User.email == email).options(selectinload(User.groups))
    )
