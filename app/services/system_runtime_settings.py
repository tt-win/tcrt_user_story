"""Super Admin runtime 設定快照 assembler（openspec: add-system-runtime-settings-viewer）。

固定 allowlist JSON 契約見 openspec specs/system-runtime-settings-viewer。
安全邊界：不輸出任何 URL 字串、query、userinfo、secret、檔案系統完整路徑。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from sqlalchemy.engine.url import make_url

# 依 main 正規化引擎推導的腳本預設 worker 數（對齊 docker/app-entrypoint.sh / start.sh）
INFERRED_WEB_CONCURRENCY_DEFAULTS = {"sqlite": 1, "mysql": 5, "postgresql": 5, "other": 1}

WORKER_COUNT_NOTE_CODE = "not_actual_worker_count"

# 整段字串必須是（可帶正負號的）整數；不先 strip，前後空白即不合法
_INT_PATTERN = re.compile(r"[+-]?\d+")


def db_endpoint_from_url(url_str: Optional[str]) -> dict[str, Any]:
    """DB URL → 結構化 DbEndpoint；解析失敗回 engine=other 且其餘欄位 null。

    - `postgres`／`postgres+*` 正規化為 `postgresql`（對齊部署腳本）
    - query 全部丟棄；SQLite database 僅 basename
    """
    endpoint: dict[str, Any] = {
        "engine": "other",
        "driver": None,
        "host": None,
        "port": None,
        "database": None,
    }
    if not url_str:
        return endpoint
    try:
        url = make_url(url_str)
        drivername = (url.drivername or "").lower()
    except Exception:
        # 盡力從 scheme 取 + 後段當 driver，其餘欄位保持 null
        scheme = url_str.split("://", 1)[0].lower()
        if "+" in scheme:
            endpoint["driver"] = scheme.split("+", 1)[1] or None
        return endpoint

    base, _, driver = drivername.partition("+")
    endpoint["driver"] = driver or None
    if base == "sqlite":
        endpoint["engine"] = "sqlite"
        if url.database:
            endpoint["database"] = os.path.basename(url.database) or None
        return endpoint
    if base == "mysql":
        endpoint["engine"] = "mysql"
    elif base in ("postgresql", "postgres"):
        endpoint["engine"] = "postgresql"
    else:
        endpoint["engine"] = "other"
    endpoint["host"] = url.host or None
    endpoint["port"] = url.port if url.port is not None else None
    endpoint["database"] = url.database or None
    return endpoint


def normalize_public_base_url(raw: Optional[str]) -> Optional[str]:
    """合法 http(s) URL 摘要：去 userinfo／query／fragment、保留 path；否則 None。

    合法定義（openspec design D3b）：scheme 僅 http/https、hostname 非空、
    port（若有）為 1–65535 整數。
    """
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        scheme = (parts.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None
        hostname = parts.hostname
        if not hostname:
            return None
        port = parts.port  # 非法 port 會拋 ValueError
        if port is not None and not (1 <= port <= 65535):
            return None
    except ValueError:
        return None
    host_out = f"[{hostname}]" if ":" in hostname else hostname
    port_out = f":{port}" if port is not None else ""
    return f"{scheme}://{host_out}{port_out}{parts.path}"


def configured_public_base_url() -> Optional[str]:
    """已設定的對外 base URL（env 優先，其次 config），未設定回 None。

    對齊 `AppConfig.get_base_url()` 的解析優先序，但快照是「設定視角」：
    未設定時 MUST 為 None，不得帶入 get_base_url 的 localhost fallback。
    """
    from app.config import settings

    for name in ("PUBLIC_BASE_URL", "APP_BASE_URL"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return settings.app.public_base_url or settings.app.base_url or None


def resolve_web_concurrency(raw: Optional[str]) -> tuple[Optional[int], str]:
    """對齊部署腳本 shell `-z` 語意（禁止先 strip 再判空）。

    - 未設或精確 ``""`` → (None, "inferred_default")
    - 整段可解析為整數且 >= 1 → (n, "configured")
    - 其他（純空白、0、負數、非整數）→ (None, "invalid_configured")
    """
    if raw is None or raw == "":
        return None, "inferred_default"
    if _INT_PATTERN.fullmatch(raw):
        value = int(raw)
        if value >= 1:
            return value, "configured"
    return None, "invalid_configured"


def build_runtime_settings_snapshot() -> dict[str, Any]:
    """組出固定 allowlist 快照（僅本請求 process 視角）。"""
    from app.config import settings
    from app.utils.system_log_buffer import get_system_log_handler

    handler = get_system_log_handler()
    main_endpoint = db_endpoint_from_url(settings.app.database_url)
    configured, source = resolve_web_concurrency(os.environ.get("WEB_CONCURRENCY"))
    log_viewer = settings.log_viewer
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pid": os.getpid(),
        "worker_instance_id": handler.worker_instance_id if handler else None,
        "process": {
            "configured_web_concurrency": configured,
            "inferred_default_web_concurrency": INFERRED_WEB_CONCURRENCY_DEFAULTS[
                main_endpoint["engine"]
            ],
            "web_concurrency_source": source,
            "worker_count_note_code": WORKER_COUNT_NOTE_CODE,
        },
        "database": {
            "main": main_endpoint,
            "audit": db_endpoint_from_url(settings.audit.database_url),
            "usm": db_endpoint_from_url(settings.usm.database_url),
        },
        "app": {
            "public_base_url": normalize_public_base_url(configured_public_base_url()),
            "enable_auth": settings.auth.enable_auth,
            "auth_enabled_source": "settings",
        },
        "log_viewer": {
            "buffer_size": log_viewer.buffer_size,
            "max_streams": log_viewer.max_streams,
            "max_message_chars": log_viewer.max_message_chars,
            "subscriber_queue_size": log_viewer.subscriber_queue_size,
            "keepalive_seconds": log_viewer.keepalive_seconds,
            "stream_max_lifetime_seconds": log_viewer.stream_max_lifetime_seconds,
        },
    }
