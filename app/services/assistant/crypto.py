"""Assistant 專用敏感執行參數加密（AES-256-GCM，versioned envelope）。

**與 Automation Provider 加密金鑰完全獨立**（design D3/D8）：使用
``settings.ai.assistant.payload_encryption_key``，不重用
``app.services.automation.provider_credential_service`` 的金鑰或 envelope 實例，
僅仿其 envelope 格式慣例。

AAD 綁定 ``execution_key`` + ``tool_name``，防止 envelope 被搬移到另一個
execution/tool 情境下重放解密。
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENVELOPE_VERSION = 1
_ALG = "AES-256-GCM"
_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16


class AssistantPayloadEncryptionError(RuntimeError):
    """金鑰缺失、格式錯誤或加解密失敗。"""


def _decode_key(raw_key: str) -> bytes:
    raw_key = (raw_key or "").strip()
    if not raw_key:
        raise AssistantPayloadEncryptionError("Assistant payload encryption key 未設定")
    try:
        key = base64.b64decode(raw_key, validate=True)
    except Exception as exc:  # noqa: BLE001 - normalize all decode failures
        raise AssistantPayloadEncryptionError(
            "Assistant payload encryption key 不是合法 base64"
        ) from exc
    if len(key) != _KEY_BYTES:
        raise AssistantPayloadEncryptionError(
            f"Assistant payload encryption key 長度需為 {_KEY_BYTES} bytes，實際 {len(key)}"
        )
    return key


def is_payload_encryption_configured(raw_key: str | None) -> bool:
    """availability 檢查用：金鑰是否可解出合法 32-byte key（design D8）。"""
    if not raw_key:
        return False
    try:
        _decode_key(raw_key)
        return True
    except AssistantPayloadEncryptionError:
        return False


def _aad(execution_key: str, tool_name: str) -> bytes:
    return f"{execution_key}:{tool_name}".encode("utf-8")


def _key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def encrypt_sensitive_payload(
    *, raw_key: str, execution_key: str, tool_name: str, payload: dict[str, Any]
) -> str:
    """回傳 JSON 序列化的 versioned envelope 字串，供 ``execution_payload_json`` 欄位保存。"""
    key = _decode_key(raw_key)
    nonce = _generate_nonce()
    plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    sealed = AESGCM(key).encrypt(nonce, plaintext, _aad(execution_key, tool_name))
    ciphertext, tag = sealed[:-_TAG_BYTES], sealed[-_TAG_BYTES:]
    envelope = {
        "version": ENVELOPE_VERSION,
        "alg": _ALG,
        "key_id": _key_id(key),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True)


def decrypt_sensitive_payload(
    *, raw_key: str, execution_key: str, tool_name: str, envelope_json: str
) -> dict[str, Any]:
    """解密到呼叫端記憶體；呼叫端負責用完即釋放參照（confirm 流程於 Tx A 前完成解密）。"""
    key = _decode_key(raw_key)
    try:
        envelope = json.loads(envelope_json)
        if envelope.get("version") != ENVELOPE_VERSION or envelope.get("alg") != _ALG:
            raise AssistantPayloadEncryptionError("未知的 envelope 版本或演算法")
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        tag = base64.b64decode(envelope["tag"], validate=True)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext + tag, _aad(execution_key, tool_name))
        return json.loads(plaintext.decode("utf-8"))
    except AssistantPayloadEncryptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize all decrypt failures
        raise AssistantPayloadEncryptionError("sensitive payload 解密失敗") from exc


def _generate_nonce() -> bytes:
    import os

    return os.urandom(_NONCE_BYTES)
