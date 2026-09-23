"""Background worker that escalates overdue approval steps.

    python -m app.worker

Runs until SIGTERM or SIGINT, finishing the current batch before exiting.
Safe to run as several replicas (see app.services.escalations).
"""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, engine
from app.services.escalations import escalate_overdue
from app.services.requests import utcnow

log = logging.getLogger("app.worker")


async def run_worker(
    stop: asyncio.Event,
    *,
    poll_seconds: float,
    batch_size: int,
    session_factory: Callable[[], AsyncSession] = SessionLocal,
) -> None:
    log.info("worker started (poll every %ss, batch size %s)", poll_seconds, batch_size)
    while not stop.is_set():
        try:
            async with session_factory() as session:
                escalated = await escalate_overdue(session, now=utcnow(), batch_size=batch_size)
        except Exception:
            # A database blip shouldn't kill the worker; try again next tick.
            log.exception("escalation batch failed")
            escalated = 0

        if escalated:
            log.info("escalated %s overdue step(s)", escalated)
        if escalated == batch_size:
            continue  # probably more waiting: drain the backlog without sleeping

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
    log.info("worker stopped")


async def main() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Not supported on Windows, where Ctrl+C still stops the process.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await run_worker(
            stop,
            poll_seconds=settings.worker_poll_seconds,
            batch_size=settings.worker_batch_size,
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
