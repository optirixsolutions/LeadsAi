"""Opaque keyset cursors: base64 of JSON `[sort_value, id]`."""

import base64
import json
import uuid
from typing import Any

from app.core.errors import AppError


class InvalidCursorError(AppError):
    code = "invalid_cursor"


def encode_cursor(value: Any, ident: uuid.UUID) -> str:
    raw = json.dumps([value, str(ident)], default=str, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[Any, uuid.UUID]:
    try:
        value, ident = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return value, uuid.UUID(ident)
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise InvalidCursorError("Invalid pagination cursor") from exc
