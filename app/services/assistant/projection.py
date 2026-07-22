"""工具結果的 output projection + credential 遮罩（design D8 / spec assistant-data-boundary）。

v1：allowlist 作用於物件頂層欄位；list-of-objects 對每個元素套用同一 allowlist
（list_test_cases 等端點回傳陣列）；`{items: [...]}` envelope 會投影 items 內元素。
credential 遮罩不論巢狀深度，只要找到 `test_data` 陣列即套用 `redact_credential_test_data`。
截斷永遠在 projection/遮罩之後執行；list 採 soft truncation envelope。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.models.test_case import redact_credential_test_data

_LIST_TRUNCATION_HINT = (
    "Result capped for context. Re-call with skip/limit or filters; prefer slim ref tools."
)


def apply_projection(data: Any, allowlist: tuple[str, ...]) -> Any:
    if not allowlist:
        return data
    if isinstance(data, list):
        return [
            {k: v for k, v in item.items() if k in allowlist} if isinstance(item, dict) else item
            for item in data
        ]
    if not isinstance(data, dict):
        return data
    projected = {k: v for k, v in data.items() if k in allowlist}
    # Common list envelope (e.g. with_meta list endpoints): project each row with the same allowlist.
    if "items" in data and isinstance(data["items"], list) and "items" not in allowlist:
        projected["items"] = apply_projection(data["items"], allowlist)
    return projected


def apply_credential_redaction(data: Any) -> Any:
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if key == "test_data" and isinstance(value, list):
                out[key] = redact_credential_test_data(value)
            else:
                out[key] = apply_credential_redaction(value)
        return out
    if isinstance(data, list):
        return [apply_credential_redaction(item) for item in data]
    return data


def _json_len(data: Any) -> int:
    return len(json.dumps(data, ensure_ascii=False))


def _list_envelope_meta(
    *,
    items: list[Any],
    source_count: int,
    truncated: bool,
    request_skip: int,
) -> dict[str, Any]:
    returned = len(items)
    return {
        "items": items,
        "truncated": truncated,
        "returned_count": returned,
        "source_count": source_count,
        "next_skip": max(0, int(request_skip)) + returned,
        "hint": _LIST_TRUNCATION_HINT,
    }


def soft_truncate_list(
    data: Any,
    max_chars: int,
    *,
    request_skip: int = 0,
) -> Any:
    """List-aware soft truncation: keep full leading rows under max_chars.

    Bare object lists and ``{items: [...]}`` envelopes become a stable envelope
    with truncation meta. Non-list payloads fall back to hard truncate.
    """
    if max_chars <= 0:
        return {"truncated": True, "preview": ""}

    items: Optional[list[Any]] = None
    passthrough: dict[str, Any] = {}
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
        passthrough = {k: v for k, v in data.items() if k != "items"}

    if items is None:
        return hard_truncate_result(data, max_chars)

    source_count = len(items)
    # Under budget: preserve original shape (bare list stays a list; existing envelopes keep
    # their non-items fields). Only wrap/truncate when the serialized form exceeds max_chars.
    if isinstance(data, list):
        if _json_len(data) <= max_chars:
            return data
    else:
        # dict envelope with items
        if _json_len(data) <= max_chars:
            return data

    kept: list[Any] = []
    for row in items:
        candidate = {**passthrough, **_list_envelope_meta(
            items=kept + [row],
            source_count=source_count,
            truncated=True,
            request_skip=request_skip,
        )}
        if _json_len(candidate) > max_chars:
            break
        kept.append(row)

    return {**passthrough, **_list_envelope_meta(
        items=kept,
        source_count=source_count,
        truncated=True,
        request_skip=request_skip,
    )}


def hard_truncate_result(data: Any, max_chars: int) -> Any:
    text = json.dumps(data, ensure_ascii=False)
    if len(text) <= max_chars:
        return data
    return {"truncated": True, "preview": text[: max(0, max_chars - 32)]}


def truncate_result(data: Any, max_chars: int, *, request_skip: int = 0) -> Any:
    """Public truncate entry: soft-list when applicable, else hard truncate."""
    if isinstance(data, list) or (isinstance(data, dict) and isinstance(data.get("items"), list)):
        return soft_truncate_list(data, max_chars, request_skip=request_skip)
    return hard_truncate_result(data, max_chars)


def project_and_redact(
    raw: Any,
    allowlist: tuple[str, ...],
    max_chars: int,
    *,
    request_skip: int = 0,
) -> Any:
    projected = apply_projection(raw, allowlist)
    redacted = apply_credential_redaction(projected)
    return truncate_result(redacted, max_chars, request_skip=request_skip)


_ERR_ALLOWLIST = ("status", "detail")


def project_error(status_code: int, detail: str) -> dict[str, Any]:
    """Return a stable user-safe error projection without upstream response bodies."""
    del detail
    if status_code == 401:
        safe_detail = "Your session expired. Please sign in again."
    elif status_code == 403:
        safe_detail = "You do not have permission to perform this action."
    elif status_code == 404:
        safe_detail = "The requested resource was not found."
    elif status_code == 409:
        safe_detail = "The resource changed. Review the latest state and retry."
    elif status_code == 422:
        safe_detail = "The request could not be validated."
    elif status_code >= 500:
        safe_detail = "The service could not complete the request."
    elif status_code <= 0:
        safe_detail = "The service could not be reached."
    else:
        safe_detail = "The request could not be completed."
    return {"status": status_code, "detail": safe_detail}
