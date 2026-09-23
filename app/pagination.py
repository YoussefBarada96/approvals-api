"""Opaque cursors for keyset pagination.

A cursor records the sort key of the last item on a page. The next page
continues from strictly after it, with "WHERE (created_at, id) < (:c, :i)".
Unlike OFFSET, this stays fast however deep you page, and rows inserted
while someone is paging can't shift items into the next page twice.
"""

import base64
import json
import uuid
from datetime import datetime

from app.services.errors import InvalidInput


def encode_cursor(created_at: datetime, id: uuid.UUID) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "i": str(id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        created_at = datetime.fromisoformat(data["c"])
        if created_at.tzinfo is None:
            raise ValueError("timezone missing")
        return created_at, uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidInput("Invalid cursor") from exc
