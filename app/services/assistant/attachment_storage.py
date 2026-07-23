"""聊天附檔暫存的安全路徑處理（spec assistant-conversations「聊天附檔暫存與並發冪等」）。

重用既有 `app/services/attachment_storage.py` 的 root 目錄與 containment helper；本模組只負責
在 `assistant_tmp/{conversation_key}/` 下產生 server-random stored name，不使用原始檔名，
也不持久化機器絕對路徑（DB 只存相對 attachments root 的 `relative_path`）。

此外提供把 assistant 暫存檔複製到 test-case staging 目錄的 helper，讓 `create_test_case`
能在同一 confirm 動作中連附件一起建立。
"""

from __future__ import annotations

import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.attachment_storage import (
    build_attachment_metadata,
    ensure_within_root,
    get_attachments_root_dir,
    resolve_relative_attachment_path,
)

ASSISTANT_TMP_SUBDIR = "assistant_tmp"
STAGING_SUBDIR = "staging"

_SAFE_RE = re.compile(r"[^A-Za-z0-9_.\-]+")


def assistant_tmp_dir(conversation_key: str) -> Path:
    root = get_attachments_root_dir().resolve()
    candidate = (root / ASSISTANT_TMP_SUBDIR / conversation_key).resolve()
    ensure_within_root(candidate, root)
    return candidate


def generate_stored_path(conversation_key: str) -> tuple[Path, str]:
    """回傳 `(絕對路徑, relative_path)`；stored name 為 server-random 32-hex，與原始檔名無關。"""
    root = get_attachments_root_dir().resolve()
    absolute = assistant_tmp_dir(conversation_key) / secrets.token_hex(16)
    ensure_within_root(absolute, root)
    return absolute, str(absolute.relative_to(root).as_posix())


def resolve_stored_path(relative_path: str) -> Path:
    return resolve_relative_attachment_path(relative_path)


def staging_dir(temp_upload_id: str) -> Path:
    """回傳 `attachments/staging/{temp_upload_id}/` 絕對路徑。"""
    root = get_attachments_root_dir().resolve()
    candidate = (root / STAGING_SUBDIR / temp_upload_id).resolve()
    ensure_within_root(candidate, root)
    return candidate


def stage_assistant_attachments(
    *,
    conversation_key: str,
    temp_upload_id: str,
    relative_paths: list[str],
    original_names: list[str],
    content_types: list[str | None],
) -> list[dict[str, Any]]:
    """把 assistant_tmp 下的暫存檔複製到 staging/{temp_upload_id}/，回傳 metadata list。

    此函式用於 `create_test_case` 想在一個 confirm 動作中連附件一起建立時：
    先把本 turn 的 assistant 暫存檔複製到 test case staging，再把 `temp_upload_id` 傳給
    create_test_case endpoint，讓 endpoint 搬移到最終 test case 附件路徑。
    """
    if len(relative_paths) != len(original_names) or len(relative_paths) != len(content_types):
        raise ValueError("relative_paths, original_names, content_types 長度必須相同")
    dest_dir = staging_dir(temp_upload_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = get_attachments_root_dir().resolve()

    ts_prefix = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    metas: list[dict[str, Any]] = []
    for rel, orig, ct in zip(relative_paths, original_names, content_types):
        src = resolve_relative_attachment_path(rel)
        safe = _SAFE_RE.sub("_", orig or "unnamed")
        stored_name = f"{ts_prefix}-{safe}"
        dest = dest_dir / stored_name
        shutil.copy2(src, dest)
        metas.append(
            build_attachment_metadata(
                root_dir=root,
                stored_path=dest,
                original_name=orig or "unnamed",
                stored_name=stored_name,
                size=dest.stat().st_size,
                content_type=ct or "application/octet-stream",
                uploaded_at=datetime.utcnow().isoformat(),
            )
        )
    return metas
