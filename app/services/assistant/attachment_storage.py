"""聊天附檔暫存的安全路徑處理（spec assistant-conversations「聊天附檔暫存與並發冪等」）。

重用既有 `app/services/attachment_storage.py` 的 root 目錄與 containment helper；本模組只負責
在 `assistant_tmp/{conversation_key}/` 下產生 server-random stored name，不使用原始檔名，
也不持久化機器絕對路徑（DB 只存相對 attachments root 的 `relative_path`）。
"""

from __future__ import annotations

import secrets
from pathlib import Path

from app.services.attachment_storage import (
    ensure_within_root,
    get_attachments_root_dir,
    resolve_relative_attachment_path,
)

ASSISTANT_TMP_SUBDIR = "assistant_tmp"


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
