from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


ENCRYPTION_KEY_ENV = "AUTOMATION_PROVIDER_ENCRYPTION_KEY"
ENVELOPE_VERSION = 1


class CredentialEncryptionError(ValueError):
    """Raised when provider credentials cannot be encrypted or decrypted."""


def _load_key() -> bytes:
    raw_key = (get_settings().automation_provider.encryption_key or "").strip()
    if not raw_key:
        raise CredentialEncryptionError(
            f"automation_provider.encryption_key (或環境變數 {ENCRYPTION_KEY_ENV}) "
            "is required for automation provider credentials"
        )
    try:
        key = base64.b64decode(raw_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CredentialEncryptionError(
            f"{ENCRYPTION_KEY_ENV} must be a base64-encoded 32-byte key"
        ) from exc
    if len(key) != 32:
        raise CredentialEncryptionError(
            f"{ENCRYPTION_KEY_ENV} must decode to exactly 32 bytes"
        )
    return key


def fingerprint_credentials(credentials: dict[str, Any] | None) -> str | None:
    if not credentials:
        return None
    for key in sorted(credentials.keys()):
        value = credentials[key]
        if isinstance(value, str) and value:
            suffix = value[-4:] if len(value) >= 4 else value
            return f"{key}:***{suffix}"
    return "***set"


def encrypt_credentials(credentials: dict[str, Any] | None) -> str | None:
    if not credentials:
        return None

    key = _load_key()
    nonce = os.urandom(12)
    plaintext = json.dumps(credentials, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    envelope = {
        "v": ENVELOPE_VERSION,
        "alg": "AES-256-GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "fingerprint": fingerprint_credentials(credentials),
    }
    return json.dumps(envelope, ensure_ascii=False, sort_keys=True)


def normalize_credentials_payload(credentials: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop blank credential fields so edit forms can omit secrets safely."""
    if credentials is None:
        return None
    normalized = {
        key: value
        for key, value in credentials.items()
        if value is not None and value != ""
    }
    return normalized or None


def merge_credentials(
    stored_credentials: dict[str, Any],
    credential_updates: dict[str, Any] | None,
) -> dict[str, Any]:
    if not credential_updates:
        return dict(stored_credentials)
    return {**stored_credentials, **credential_updates}


def decrypt_credentials(encrypted: str | None) -> dict[str, Any]:
    if not encrypted:
        return {}

    key = _load_key()
    try:
        envelope = json.loads(encrypted)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        data = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise CredentialEncryptionError("Failed to decrypt automation provider credentials") from exc

    if not isinstance(data, dict):
        raise CredentialEncryptionError("Decrypted automation provider credentials must be an object")
    return data


def encrypted_credentials_fingerprint(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        envelope = json.loads(encrypted)
    except json.JSONDecodeError:
        return None
    fingerprint = envelope.get("fingerprint")
    return fingerprint if isinstance(fingerprint, str) and fingerprint else None


# --- Single secret value helpers (automation environment / script env vars) ---
# These reuse the same AES-256-GCM envelope as provider credentials by wrapping
# the value as {"value": <str>}. Used by AutomationEnvironmentService so secret
# parameter values are encrypted at rest and never round-tripped in plaintext.


def value_fingerprint(value: str | None) -> str | None:
    """Short fingerprint for a plaintext secret value, e.g. ``***wxyz``."""
    if not value:
        return None
    suffix = value[-4:] if len(value) >= 4 else value
    return f"***{suffix}"


def encrypt_value(value: str | None) -> str | None:
    """Encrypt a single secret value into an envelope string (or None if blank)."""
    if value is None or value == "":
        return None
    return encrypt_credentials({"value": value})


def decrypt_value(encrypted: str | None) -> str | None:
    """Decrypt a single secret value envelope back to plaintext (or None)."""
    if not encrypted:
        return None
    data = decrypt_credentials(encrypted)
    value = data.get("value")
    return value if isinstance(value, str) else None


def encrypted_value_fingerprint(encrypted: str | None) -> str | None:
    """Fingerprint (``***wxyz``) read from a stored secret value envelope."""
    fingerprint = encrypted_credentials_fingerprint(encrypted)
    if fingerprint and fingerprint.startswith("value:"):
        return fingerprint[len("value:"):]
    return fingerprint
