"""工具結果的 output projection + credential 遮罩（design D8 / spec assistant-data-boundary）。

v1：allowlist 作用於物件頂層欄位；list-of-objects 對每個元素套用同一 allowlist
（list_test_cases 等端點回傳陣列）；`{items: [...]}` envelope 會投影 items 內元素。
credential 遮罩不論巢狀深度，只要找到 `test_data` 陣列即套用 `redact_credential_test_data`。
截斷永遠在 projection/遮罩之後執行。
"""

from __future__ import annotations

import json
from typing import Any

from app.models.test_case import redact_credential_test_data


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


def truncate_result(data: Any, max_chars: int) -> Any:
    text = json.dumps(data, ensure_ascii=False)
    if len(text) <= max_chars:
        return data
    return {"truncated": True, "preview": text[: max(0, max_chars - 32)]}


def project_and_redact(raw: Any, allowlist: tuple[str, ...], max_chars: int) -> Any:
    projected = apply_projection(raw, allowlist)
    redacted = apply_credential_redaction(projected)
    return truncate_result(redacted, max_chars)


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
