import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.escalations import claim_overdue, escalate_overdue
from app.services.requests import utcnow
from app.worker import run_worker
from tests.conftest import run_sql

LATER = timedelta(hours=25)  # past the 24h deadline of the manager step


def submit(client, headers, workflow_id, title="Laptop"):
    response = client.post(
        "/requests", json={"workflow_id": workflow_id, "title": title}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def with_sessions(db: str, scenario: Callable[[async_sessionmaker], Awaitable]):
    async def runner():
        engine = create_async_engine(db, poolclass=pool.NullPool)
        try:
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(runner())


def escalate(db: str, *, at, batch_size: int = 50) -> int:
    async def scenario(sessions):
        async with sessions() as session:
            return await escalate_overdue(session, now=at, batch_size=batch_size)

    return with_sessions(db, scenario)


def test_overdue_step_escalated_once(client, db, user_headers, purchase_workflow):
    request = submit(client, user_headers, purchase_workflow["id"])

    assert escalate(db, at=utcnow() + LATER) == 1
    assert escalate(db, at=utcnow() + LATER) == 0  # already escalated

    body = client.get(f"/requests/{request['id']}", headers=user_headers).json()
    assert body["steps"][0]["escalated_at"] is not None
    assert body["steps"][1]["escalated_at"] is None
    assert body["version"] == 1  # escalation doesn't invalidate in-flight decisions

    events = client.get(f"/requests/{request['id']}/history", headers=user_headers).json()
    escalated = [e for e in events if e["action"] == "escalated"]
    assert len(escalated) == 1
    assert escalated[0]["actor_id"] is None
    assert escalated[0]["step_position"] == 1
    assert escalated[0]["data"]["overdue_seconds"] > 0


def test_steps_within_sla_left_alone(client, db, user_headers, purchase_workflow):
    submit(client, user_headers, purchase_workflow["id"])

    assert escalate(db, at=utcnow() + timedelta(hours=23)) == 0


def test_only_active_steps_escalated(client, db, user_headers, purchase_workflow):
    approved = submit(client, user_headers, purchase_workflow["id"], "Approved")
    withdrawn = submit(client, user_headers, purchase_workflow["id"], "Withdrawn")
    client.post(
        f"/requests/{approved['id']}/approve",
        json={"version": 1},
        headers=purchase_workflow["manager"],
    )
    client.post(f"/requests/{withdrawn['id']}/withdraw", json={"version": 1}, headers=user_headers)

    # 25h later: the approved request's finance step (48h SLA) isn't due yet,
    # and the withdrawn request has no active step at all.
    assert escalate(db, at=utcnow() + LATER) == 0
    # 49h later the finance step is overdue too.
    assert escalate(db, at=utcnow() + timedelta(hours=49)) == 1


def test_batches_oldest_deadline_first(client, db, user_headers, purchase_workflow):
    ids = [
        submit(client, user_headers, purchase_workflow["id"], title)["id"]
        for title in ("First", "Second", "Third")
    ]

    def escalated(request_id):
        request = client.get(f"/requests/{request_id}", headers=user_headers).json()
        return request["steps"][0]["escalated_at"] is not None

    assert escalate(db, at=utcnow() + LATER, batch_size=2) == 2
    assert [escalated(i) for i in ids] == [True, True, False]
    assert escalate(db, at=utcnow() + LATER, batch_size=2) == 1
    assert [escalated(i) for i in ids] == [True, True, True]


def test_concurrent_workers_skip_each_others_rows(client, db, user_headers, purchase_workflow):
    """Worker A has claimed a step and not committed yet. Worker B must take
    the other overdue step immediately rather than wait for A's lock or
    escalate A's step as well."""
    submit(client, user_headers, purchase_workflow["id"], "One")
    submit(client, user_headers, purchase_workflow["id"], "Two")
    now = utcnow() + LATER

    async def scenario(sessions):
        async with sessions() as worker_a, sessions() as worker_b:
            claimed_by_a = await claim_overdue(worker_a, now=now, batch_size=1)
            # Would hang until the timeout if SKIP LOCKED were missing.
            escalated_by_b = await asyncio.wait_for(
                escalate_overdue(worker_b, now=now, batch_size=10), timeout=5
            )
            await worker_a.rollback()
            return len(claimed_by_a), escalated_by_b

    assert with_sessions(db, scenario) == (1, 1)
    # A rolled back, so its step is still waiting to be escalated.
    assert escalate(db, at=now) == 1


def test_worker_loop_escalates_and_stops(client, db, user_headers, purchase_workflow):
    request = submit(client, user_headers, purchase_workflow["id"])
    run_sql(db, lambda conn: conn.execute(text("UPDATE request_steps SET due_at = now()")))

    async def scenario(sessions):
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(stop, poll_seconds=0.05, batch_size=10, session_factory=sessions)
        )
        try:
            for _ in range(100):
                async with sessions() as session:
                    count = await session.scalar(
                        text("SELECT count(*) FROM audit_events WHERE action = 'escalated'")
                    )
                if count:
                    break
                await asyncio.sleep(0.05)
        finally:
            stop.set()  # what SIGTERM does
            await asyncio.wait_for(worker, timeout=5)
        return count

    assert with_sessions(db, scenario) == 1
    body = client.get(f"/requests/{request['id']}", headers=user_headers).json()
    assert body["steps"][0]["escalated_at"] is not None


def test_worker_survives_a_failing_batch():
    """A database error in one batch is logged and the loop keeps going."""
    calls = 0

    class BrokenSession:
        async def __aenter__(self):
            nonlocal calls
            calls += 1
            raise ConnectionError("database unavailable")

        async def __aexit__(self, *exc):
            return False

    async def scenario():
        stop = asyncio.Event()
        worker = asyncio.create_task(
            run_worker(stop, poll_seconds=0.01, batch_size=10, session_factory=BrokenSession)
        )
        while calls < 3:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(worker, timeout=5)

    asyncio.run(scenario())
    assert calls >= 3
