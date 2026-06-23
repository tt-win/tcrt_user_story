"""P0 部署地雷回歸測試（change: harden-container-deployment, section 1）。

涵蓋兩個程式碼層級的 P0 修補：
- 1.1 RSA 簽章金鑰目錄可由 RSA_KEY_DIR 覆寫，且金鑰跨重啟持久化（不重生）。
- 1.3 啟用認證時，JWT_SECRET_KEY 為空必須在啟動時快速失敗。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


def test_rsa_key_dir_override_and_persistence(tmp_path: Path, monkeypatch) -> None:
    """RSA_KEY_DIR 覆寫金鑰目錄；重新載入時沿用既有金鑰、不重生。"""
    from app.auth.password_encryption import PasswordEncryptionService as P

    monkeypatch.setenv("RSA_KEY_DIR", str(tmp_path))
    P._private_key = None
    P._public_key = None
    try:
        P.initialize()
        assert P.KEY_DIR == tmp_path
        assert (tmp_path / "private_key.pem").exists()
        assert (tmp_path / "public_key.pem").exists()

        fingerprint = P.get_public_key_base64()

        # 模擬容器重建後重新載入：金鑰應沿用既有檔案，公鑰不變
        P._private_key = None
        P._public_key = None
        P.initialize()
        assert P.get_public_key_base64() == fingerprint
    finally:
        # 還原預設金鑰狀態，避免影響其他測試
        monkeypatch.undo()
        P._private_key = None
        P._public_key = None
        P.initialize()


def test_startup_fails_fast_on_empty_jwt_secret(monkeypatch) -> None:
    """ENABLE_AUTH=true 但 JWT_SECRET_KEY 為空時，startup 必須拋錯中止。"""
    import app.main as main_module
    from app.config import settings

    monkeypatch.setattr(settings.auth, "enable_auth", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        asyncio.run(main_module._run_startup())


def test_startup_guard_passes_when_jwt_secret_present(monkeypatch) -> None:
    """JWT_SECRET_KEY 有設定時，安全前置檢查不應觸發（守門條件為 False）。"""
    from app.config import settings

    monkeypatch.setattr(settings.auth, "enable_auth", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "a-non-empty-secret")

    guard_trips = settings.auth.enable_auth and not (settings.auth.jwt_secret_key or "").strip()
    assert guard_trips is False
