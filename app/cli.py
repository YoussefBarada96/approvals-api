"""Admin command line.

Create the first admin (there's no API for it, since only admins can grant
admin rights):

    python -m app.cli create-admin --email admin@example.com --name "Ada Admin"

The password is prompted for, or read from ADMIN_PASSWORD when set (useful
with `docker compose run`).

Load demo data for trying the API (development only):

    python -m app.cli seed-demo
"""

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Awaitable

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.models import ApprovalGroup, User, Workflow
from app.schemas.workflows import StepIn, WorkflowCreate
from app.services.users import EmailAlreadyRegistered, create_user
from app.services.workflows import create_workflow

DEMO_PASSWORD = "demo-password-123"
DEMO_WORKFLOW = "Purchase order"
# (email, full name, is_admin, group)
DEMO_USERS = [
    ("admin@example.com", "Ada Admin", True, None),
    ("alice@example.com", "Alice Requester", False, None),
    ("mo@example.com", "Mo Manager", False, "Managers"),
    ("fay@example.com", "Fay Finance", False, "Finance"),
]


class AlreadySeeded(Exception):
    pass


async def create_admin(email: str, full_name: str, password: str) -> None:
    async with SessionLocal() as session:
        await create_user(
            session, email=email, full_name=full_name, password=password, is_admin=True
        )
        await session.commit()


async def seed_demo(password: str = DEMO_PASSWORD) -> None:
    """Two approver groups, one person in each, a requester, an admin, and a
    two-step workflow: Manager review (24h), then Finance review (48h)."""
    async with SessionLocal() as session:
        if await session.scalar(select(Workflow.id).where(Workflow.name == DEMO_WORKFLOW)):
            raise AlreadySeeded

        users: dict[str, User] = {}
        for email, full_name, is_admin, _ in DEMO_USERS:
            users[email] = await create_user(
                session, email=email, full_name=full_name, password=password, is_admin=is_admin
            )
        groups = {
            name: ApprovalGroup(
                name=name,
                members=[users[email] for email, _, _, group in DEMO_USERS if group == name],
            )
            for name in ("Managers", "Finance")
        }
        session.add_all(groups.values())
        await session.flush()

        await create_workflow(
            session,
            WorkflowCreate(
                name=DEMO_WORKFLOW,
                description="Purchases over the team budget",
                steps=[
                    StepIn(
                        name="Manager review",
                        approver_group_id=groups["Managers"].id,
                        sla_hours=24,
                    ),
                    StepIn(
                        name="Finance review", approver_group_id=groups["Finance"].id, sla_hours=48
                    ),
                ],
            ),
            users["admin@example.com"],
        )
        await session.commit()


async def _run(job: Awaitable[None]) -> None:
    try:
        await job
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an admin user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    commands.add_parser("seed-demo", help="load demo users, groups and a workflow")
    args = parser.parse_args(argv)

    if args.command == "seed-demo":
        return _seed_demo_command()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 1
    try:
        asyncio.run(_run(create_admin(args.email, args.name, password)))
    except EmailAlreadyRegistered:
        print(f"{args.email} is already registered.", file=sys.stderr)
        return 1
    print(f"Created admin {args.email}")
    return 0


def _seed_demo_command() -> int:
    # The demo password is published in this file, so never seed it anywhere real.
    if get_settings().app_env != "development":
        print("seed-demo only runs with APP_ENV=development.", file=sys.stderr)
        return 1
    try:
        asyncio.run(_run(seed_demo()))
    except (AlreadySeeded, EmailAlreadyRegistered):
        print("Demo data (or one of its users) already exists; nothing changed.", file=sys.stderr)
        return 1
    print(f"Seeded demo data. Every demo user's password is {DEMO_PASSWORD!r}:")
    for email, full_name, is_admin, group in DEMO_USERS:
        role = "admin" if is_admin else f"approver in {group}" if group else "requester"
        print(f"  {email:<20} {full_name} ({role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
