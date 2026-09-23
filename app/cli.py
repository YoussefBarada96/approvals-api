"""Admin command line.

Create the first admin (there's no API for it, since only admins can grant
admin rights):

    python -m app.cli create-admin --email admin@example.com --name "Ada Admin"

The password is prompted for, or read from ADMIN_PASSWORD when set (useful
with `docker compose run`).
"""

import argparse
import asyncio
import getpass
import os
import sys

from app.db import SessionLocal, engine
from app.services.users import EmailAlreadyRegistered, create_user


async def create_admin(email: str, full_name: str, password: str) -> None:
    try:
        async with SessionLocal() as session:
            await create_user(
                session, email=email, full_name=full_name, password=password, is_admin=True
            )
            await session.commit()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create an admin user")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 1
    try:
        asyncio.run(create_admin(args.email, args.name, password))
    except EmailAlreadyRegistered:
        print(f"{args.email} is already registered.", file=sys.stderr)
        return 1
    print(f"Created admin {args.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
