"""`Settings.from_env_and_file` 的載入行為測試：public_base_url 優先序、
container runtime 的 localhost 警告與 SQLite 儲存風險 fail-fast、Jira env 覆蓋。

原本住在 `test_qdrant_client_service.py`；Qdrant 支援移除
（change: remove-qdrant-support）後搬到此檔。
"""

import pytest

from app.config import Settings


def test_settings_prefers_public_base_url_env_over_legacy_app_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tcrt.example.com")
    monkeypatch.setenv("APP_BASE_URL", "https://legacy.example.com")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n  port: 9999\n  public_base_url: https://config.example.com\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.app.public_base_url == "https://tcrt.example.com"
    assert loaded.app.get_base_url() == "https://tcrt.example.com"


def test_settings_falls_back_to_configured_public_base_url(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n  port: 9999\n  public_base_url: https://config.example.com\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.app.get_base_url() == "https://config.example.com"


def test_settings_warns_when_container_runtime_uses_localhost_services(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("APP_ENV", "docker")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "mysql+asyncmy://tcrt:pw@localhost:3306/tcrt_main")
    # 這裡測的是 localhost URL 警告，不是 SQLite 儲存風險檢查——明確承認風險避免
    # 被 _fail_fast_if_sqlite_without_volume_ack 擋下來。
    monkeypatch.setenv("SQLITE_CONTAINER_STORAGE_ACK", "1")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "app:\n  port: 9999\n",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        Settings.from_env_and_file(str(config_path))

    assert "DATABASE_URL" in caplog.text
    assert "PUBLIC_BASE_URL" in caplog.text


def test_settings_fails_fast_on_sqlite_in_container_without_ack(tmp_path, monkeypatch):
    """P0 回歸測試：容器內用 SQLite 又沒有明確承認風險時必須直接炸開，而不是靜默開機——
    容器沒掛 volume 時，SQLite 檔案存在可寫層，容器重建/重新部署會靜默遺失所有資料。"""
    monkeypatch.setenv("APP_ENV", "docker")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_case_repo.db")
    monkeypatch.delenv("SQLITE_CONTAINER_STORAGE_ACK", raising=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("app:\n  port: 9999\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="SQLITE_CONTAINER_STORAGE_ACK"):
        Settings.from_env_and_file(str(config_path))


def test_settings_allows_sqlite_in_container_with_explicit_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "docker")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_case_repo.db")
    monkeypatch.setenv("SQLITE_CONTAINER_STORAGE_ACK", "1")
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tcrt.example.com")

    config_path = tmp_path / "config.yaml"
    config_path.write_text("app:\n  port: 9999\n", encoding="utf-8")

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.app.database_url.startswith("sqlite")


def test_settings_does_not_fail_fast_on_sqlite_outside_container(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_case_repo.db")
    monkeypatch.delenv("SQLITE_CONTAINER_STORAGE_ACK", raising=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("app:\n  port: 9999\n", encoding="utf-8")

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.app.database_url.startswith("sqlite")


def test_settings_reads_jira_values_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JIRA_SERVER_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_USERNAME", "qa.user")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_CA_CERT_PATH", "/etc/certs/jira.crt")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "jira:\n"
        "  server_url: https://old.example.com\n"
        "  username: old-user\n"
        "  api_token: old-token\n"
        "  ca_cert_path: old.crt\n",
        encoding="utf-8",
    )

    loaded = Settings.from_env_and_file(str(config_path))
    assert loaded.jira.server_url == "https://jira.example.com"
    assert loaded.jira.username == "qa.user"
    assert loaded.jira.api_token == "secret-token"
    assert loaded.jira.ca_cert_path == "/etc/certs/jira.crt"
