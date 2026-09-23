import uuid
from datetime import UTC, datetime

import pytest

from app.pagination import decode_cursor, encode_cursor
from app.services.errors import InvalidInput


def test_cursor_roundtrip_keeps_microseconds():
    created_at = datetime(2026, 9, 23, 14, 5, 9, 123456, tzinfo=UTC)
    request_id = uuid.uuid4()

    assert decode_cursor(encode_cursor(created_at, request_id)) == (created_at, request_id)


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64-json!",
        "",
        # Valid base64 JSON, wrong contents:
        encode_cursor(datetime(2026, 1, 1, tzinfo=UTC), uuid.uuid4())[:-4],
        "eyJjIjogIjIwMjYtMDEtMDEifQ",  # {"c": "2026-01-01"}: no id, no timezone
    ],
)
def test_malformed_cursor_rejected(cursor):
    with pytest.raises(InvalidInput):
        decode_cursor(cursor)
