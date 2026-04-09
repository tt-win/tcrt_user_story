"""Shared JSON serialisation helpers for QA AI Helper modules."""

from __future__ import annotations

import base64
import json
import zlib
from copy import deepcopy
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_JSON_ZLIB_PREFIX = "__qa_ai_helper_zlib__:"
DB_JSON_COMPRESS_THRESHOLD = 32 * 1024


# ---------------------------------------------------------------------------
# Compact JSON helpers
# ---------------------------------------------------------------------------


def json_compact_dumps(value: Any) -> str:
    """Compact JSON serialisation (no whitespace, non-ASCII preserved).

    Unlike :func:`json_compact_dumps_nullable`, this always returns a ``str``
    (``None`` is serialised as the JSON literal ``"null"``).
    """
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_compact_dumps_nullable(value: Any) -> Optional[str]:
    """Same as :func:`json_compact_dumps` but passes ``None`` through."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_safe_loads(value: Optional[str], default: Any) -> Any:
    """Deserialise JSON with a fallback *default* (deep-copied for safety)."""
    if not value:
        return deepcopy(default)
    try:
        return json.loads(value)
    except Exception:
        return deepcopy(default)


# ---------------------------------------------------------------------------
# DB storage helpers (zlib-compressed JSON)
# ---------------------------------------------------------------------------


def json_storage_dumps(
    value: Any,
    *,
    compress_threshold: int = DB_JSON_COMPRESS_THRESHOLD,
) -> Optional[str]:
    """Serialise *value* to JSON, optionally zlib-compressing large payloads."""
    raw = json_compact_dumps_nullable(value)
    if raw is None:
        return None
    if len(raw) < compress_threshold:
        return raw
    compressed = zlib.compress(raw.encode("utf-8"), level=6)
    encoded = base64.b64encode(compressed).decode("ascii")
    candidate = f"{DB_JSON_ZLIB_PREFIX}{encoded}"
    return candidate if len(candidate) < len(raw) else raw


def json_storage_loads(value: Optional[str], default: Any) -> Any:
    """Deserialise JSON produced by :func:`json_storage_dumps`."""
    if not value:
        return deepcopy(default)
    raw = value
    if isinstance(value, str) and value.startswith(DB_JSON_ZLIB_PREFIX):
        encoded = value[len(DB_JSON_ZLIB_PREFIX) :]
        try:
            raw = zlib.decompress(base64.b64decode(encoded.encode("ascii"))).decode("utf-8")
        except Exception:
            return deepcopy(default)
    return json_safe_loads(raw, default)
