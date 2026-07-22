"""伺服器生成識別碼與決定性 fingerprint 計算。

所有 at-most-once / 冪等 / 稽核鍵均由此模組產生，避免各處各自造字串。
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any


def generate_conversation_key() -> str:
    """32-hex，conversation 的不可重用權威識別（見 design D5、D9）。"""
    return secrets.token_hex(16)


def generate_turn_key() -> str:
    """32-hex turn 識別；confirm continuation 的 client_message_id 需以此為基礎控制長度。"""
    return secrets.token_hex(16)


def generate_execution_key() -> str:
    """32-hex（token_hex(16)），pending action / journal 的 at-most-once 主鍵（design D3）。

    固定長度確保 ``"confirm:" + execution_key``（40 字元）不超過 client_message_id 的 64 字元上限。
    """
    return secrets.token_hex(16)


def confirm_client_message_id(execution_key: str) -> str:
    """confirm continuation turn 的 deterministic client_message_id（design D3）。"""
    return f"confirm:{execution_key}"


def derive_llm_tool_call_id_for_execution(execution_key: str) -> str:
    """write 工具的 server-normalized tool-call id，與 execution_key 一一對應。"""
    return f"call_{execution_key}"


def generate_llm_tool_call_id() -> str:
    """read 工具（無 pending/execution_key）用的 server-normalized tool-call id。"""
    return f"call_{secrets.token_hex(16)}"


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def compute_request_fingerprint(text: str, attachment_digests: list[str] | None) -> str:
    """SHA-256 hex digest，涵蓋 normalized 文字與已排序附件雜湊（spec assistant-conversations）。"""
    normalized_text = (text or "").strip()
    payload = {"text": normalized_text, "attachments": sorted(attachment_digests or [])}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def compute_confirmation_fingerprint(
    *,
    canonical_summary: dict,
    stable_target_identity: Any,
    destructive_membership_digest: Any = None,
) -> str:
    """SHA-256 hex digest，輸入僅限 canonical summary + 穩定目標身分（spec assistant-action-confirmation）。

    MUST NOT 只 hash UI 摘要本身——必須含 stable_target_identity/version，
    否則同名替換或 row-id 重用可繞過 stale 檢查。
    """
    payload = {
        "canonical_summary": canonical_summary,
        "stable_target_identity": stable_target_identity,
        "destructive_membership_digest": destructive_membership_digest,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def compute_sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
