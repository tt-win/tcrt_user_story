"""Runtime 設定快照（/api/admin/system-runtime-settings）契約測試。

openspec: add-system-runtime-settings-viewer
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.audit import ActionType, ResourceType, audit_service
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database_models import User
from app.services.system_runtime_settings import (
    db_endpoint_from_url,
    normalize_public_base_url,
    resolve_web_concurrency,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_audit_database_overrides,
    install_main_database_overrides,
)
from app.utils.system_log_buffer import (
    install_system_log_handler,
    reset_system_log_handler,
)

SETTINGS_URL = "/api/admin/system-runtime-settings"


@pytest.fixture
def runtime_settings_env(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "runtime_main.db")
    audit_bundle = create_managed_test_database(tmp_path / "runtime_audit.db", target_name="audit")

    with main_bundle["sync_session_factory"]() as session:
        super_user = User(
            username="rt-super",
            email="rt-super@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        normal_user = User(
            username="rt-normal",
            email="rt-normal@example.com",
            hashed_password="x",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        session.add_all([super_user, normal_user])
        session.commit()
        super_id, normal_id = super_user.id, normal_user.id

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=main_bundle["async_engine"],
        async_session_factory=main_bundle["async_session_factory"],
    )
    install_audit_database_overrides(
        monkeypatch=monkeypatch,
        async_session_factory=audit_bundle["async_session_factory"],
    )
    permission_service.cache._cache.clear()
    reset_system_log_handler()

    yield {"super_id": super_id, "normal_id": normal_id}

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)
    permission_service.cache._cache.clear()
    reset_system_log_handler()
    dispose_managed_test_database(audit_bundle)
    dispose_managed_test_database(main_bundle)


def _login_as(user_id: int, username: str, role: UserRole) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=user_id, username=username, role=role
    )


def _login_super(env) -> None:
    _login_as(env["super_id"], "rt-super", UserRole.SUPER_ADMIN)


class TestAuthAndSchema:
    def test_anonymous_rejected(self, runtime_settings_env):
        client = TestClient(app)
        resp = client.get(SETTINGS_URL)
        assert resp.status_code in (401, 403)
        assert "web_concurrency_source" not in resp.text

    def test_non_super_admin_rejected(self, runtime_settings_env):
        _login_as(runtime_settings_env["normal_id"], "rt-normal", UserRole.USER)
        client = TestClient(app)
        resp = client.get(SETTINGS_URL)
        assert resp.status_code == 403
        assert "web_concurrency_source" not in resp.text

    def test_openapi_excludes_endpoint(self, runtime_settings_env):
        _login_super(runtime_settings_env)
        client = TestClient(app)
        paths = client.get("/openapi.json").json()["paths"]
        assert SETTINGS_URL not in paths
        assert not any("system-runtime-settings" in path for path in paths)


class TestSnapshotContract:
    def test_exact_key_sets_and_headers(self, runtime_settings_env):
        _login_super(runtime_settings_env)
        client = TestClient(app)
        resp = client.get(SETTINGS_URL)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        payload = resp.json()
        assert set(payload) == {
            "generated_at",
            "pid",
            "worker_instance_id",
            "process",
            "database",
            "app",
            "log_viewer",
        }
        assert set(payload["process"]) == {
            "configured_web_concurrency",
            "inferred_default_web_concurrency",
            "web_concurrency_source",
            "worker_count_note_code",
        }
        assert set(payload["database"]) == {"main", "audit", "usm"}
        for endpoint in payload["database"].values():
            assert set(endpoint) == {"engine", "driver", "host", "port", "database"}
        assert set(payload["app"]) == {"public_base_url", "enable_auth", "auth_enabled_source"}
        assert set(payload["log_viewer"]) == {
            "buffer_size",
            "max_streams",
            "max_message_chars",
            "subscriber_queue_size",
            "keepalive_seconds",
            "stream_max_lifetime_seconds",
        }
        # generated_at：UTC ISO-8601 秒精度 + Z
        assert payload["generated_at"].endswith("Z") and len(payload["generated_at"]) == 20
        assert isinstance(payload["pid"], int)
        assert payload["process"]["worker_count_note_code"] == "not_actual_worker_count"
        assert payload["app"]["auth_enabled_source"] == "settings"
        assert isinstance(payload["app"]["enable_auth"], bool)
        for value in payload["log_viewer"].values():
            assert isinstance(value, int)
        # 禁止鍵：不得有 url / url_redacted / note
        text = resp.text
        assert '"url"' not in text and '"url_redacted"' not in text and '"note"' not in text

    def test_mysql_url_structured_without_secret_and_query(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.setattr(
            settings.app,
            "database_url",
            "mysql+asyncmy://user:s3cretpw@dbhost:3306/tcrt_main?token=abc&ssl_key=/x",
        )
        resp = TestClient(app).get(SETTINGS_URL)
        main = resp.json()["database"]["main"]
        assert main == {
            "engine": "mysql",
            "driver": "asyncmy",
            "host": "dbhost",
            "port": 3306,
            "database": "tcrt_main",
        }
        assert "s3cretpw" not in resp.text
        assert "token=abc" not in resp.text and "ssl_key" not in resp.text

    def test_postgres_alias_and_inferred_default(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        monkeypatch.setattr(
            settings.app, "database_url", "postgres://user:secret@dbhost:5432/tcrt_main"
        )
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["database"]["main"]["engine"] == "postgresql"
        assert payload["process"]["configured_web_concurrency"] is None
        assert payload["process"]["inferred_default_web_concurrency"] == 5
        assert payload["process"]["web_concurrency_source"] == "inferred_default"

    def test_malformed_db_url_still_200(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.setattr(settings.audit, "database_url", "not a url at all")
        resp = TestClient(app).get(SETTINGS_URL)
        assert resp.status_code == 200
        assert resp.json()["database"]["audit"] == {
            "engine": "other",
            "driver": None,
            "host": None,
            "port": None,
            "database": None,
        }

    def test_sqlite_path_not_leaked(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.setattr(
            settings.app, "database_url", "sqlite:////var/lib/tcrt/data/test_case_repo.db"
        )
        resp = TestClient(app).get(SETTINGS_URL)
        main = resp.json()["database"]["main"]
        assert main["engine"] == "sqlite"
        assert main["database"] == "test_case_repo.db"
        assert "/var/lib/tcrt" not in resp.text

    def test_public_base_url_sanitized(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.setenv("PUBLIC_BASE_URL", "https://user:pass@example.com:443/app?x=1#y")
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["app"]["public_base_url"] == "https://example.com:443/app"

    def test_public_base_url_invalid_is_null(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.setenv("PUBLIC_BASE_URL", "ftp://example.com/x")
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["app"]["public_base_url"] is None

    def test_public_base_url_unset_is_null_not_localhost_fallback(
        self, runtime_settings_env, monkeypatch
    ):
        """未設定時 MUST 為 null，不得帶入 get_base_url 的 localhost fallback。"""
        _login_super(runtime_settings_env)
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        monkeypatch.setattr(settings.app, "public_base_url", None)
        monkeypatch.setattr(settings.app, "base_url", None)
        resp = TestClient(app).get(SETTINGS_URL)
        assert resp.json()["app"]["public_base_url"] is None
        assert "localhost" not in resp.text

    def test_public_base_url_from_config_when_env_unset(self, runtime_settings_env, monkeypatch):
        _login_super(runtime_settings_env)
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        monkeypatch.setattr(settings.app, "public_base_url", "https://tcrt.example.com/base")
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["app"]["public_base_url"] == "https://tcrt.example.com/base"

    def test_worker_instance_id_null_without_handler(self, runtime_settings_env):
        _login_super(runtime_settings_env)
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["worker_instance_id"] is None
        assert payload["process"]["worker_count_note_code"] == "not_actual_worker_count"

    def test_worker_instance_id_from_installed_handler(self, runtime_settings_env):
        _login_super(runtime_settings_env)
        handler = install_system_log_handler(100, 500, 50)
        payload = TestClient(app).get(SETTINGS_URL).json()
        assert payload["worker_instance_id"] == handler.worker_instance_id


class TestWebConcurrency:
    @pytest.mark.parametrize(
        ("raw", "expected_configured", "expected_source"),
        [
            ("2", 2, "configured"),
            ("", None, "inferred_default"),
            (None, None, "inferred_default"),
            ("   ", None, "invalid_configured"),
            ("0", None, "invalid_configured"),
            ("-1", None, "invalid_configured"),
            ("abc", None, "invalid_configured"),
            (" 2 ", None, "invalid_configured"),
        ],
    )
    def test_env_semantics_over_api(
        self, runtime_settings_env, monkeypatch, raw, expected_configured, expected_source
    ):
        _login_super(runtime_settings_env)
        if raw is None:
            monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        else:
            monkeypatch.setenv("WEB_CONCURRENCY", raw)
        process = TestClient(app).get(SETTINGS_URL).json()["process"]
        assert process["configured_web_concurrency"] == expected_configured
        assert process["web_concurrency_source"] == expected_source
        assert isinstance(process["inferred_default_web_concurrency"], int)


class TestAudit:
    async def _call_endpoint(self, env):
        """直接呼叫 endpoint 以斷言 audit 一級參數。"""
        from fastapi import Request

        import app.api.admin as admin_module

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": SETTINGS_URL,
                "query_string": b"",
                "headers": [(b"user-agent", b"pytest-ua")],
                "client": ("9.8.7.6", 4321),
            }
        )
        user = SimpleNamespace(id=env["super_id"], username="rt-super", role=UserRole.SUPER_ADMIN)
        return await admin_module.get_system_runtime_settings(request=request, current_user=user)

    async def test_audit_first_class_fields_and_details_boundary(
        self, runtime_settings_env, monkeypatch
    ):
        calls = []

        async def fake_log_action(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(audit_service, "log_action", fake_log_action)
        response = await self._call_endpoint(runtime_settings_env)
        assert response.status_code == 200
        assert len(calls) == 1
        call = calls[0]
        assert call["action_type"] == ActionType.READ
        assert call["resource_type"] == ResourceType.SYSTEM
        assert call["resource_id"] == "system-runtime-settings"
        assert call["ip_address"] == "9.8.7.6"
        assert call["user_agent"] == "pytest-ua"
        # details 邊界：恰好 pid + worker_instance_id，不含快照本體
        assert set(call["details"]) == {"pid", "worker_instance_id"}
        assert "web_concurrency_source" not in json.dumps(call["details"])

    async def test_audit_failure_still_200(self, runtime_settings_env, monkeypatch):
        async def broken_log_action(**kwargs):
            raise RuntimeError("audit down")

        monkeypatch.setattr(audit_service, "log_action", broken_log_action)
        response = await self._call_endpoint(runtime_settings_env)
        assert response.status_code == 200
        payload = json.loads(response.body)
        assert set(payload) == {
            "generated_at",
            "pid",
            "worker_instance_id",
            "process",
            "database",
            "app",
            "log_viewer",
        }


class TestAssemblerUnits:
    """assembler 純函式單元測試（不經 HTTP）。"""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (
                "mysql+asyncmy://u:p@h:3306/db?x=1",
                {"engine": "mysql", "driver": "asyncmy", "host": "h", "port": 3306, "database": "db"},
            ),
            (
                "mysql://u:p@h/db",
                {"engine": "mysql", "driver": None, "host": "h", "port": None, "database": "db"},
            ),
            (
                "postgres+asyncpg://u:p@h:5432/db",
                {
                    "engine": "postgresql",
                    "driver": "asyncpg",
                    "host": "h",
                    "port": 5432,
                    "database": "db",
                },
            ),
            (
                "postgresql://u:p@h/db",
                {"engine": "postgresql", "driver": None, "host": "h", "port": None, "database": "db"},
            ),
            (
                "sqlite+aiosqlite:///./data/app.db",
                {
                    "engine": "sqlite",
                    "driver": "aiosqlite",
                    "host": None,
                    "port": None,
                    "database": "app.db",
                },
            ),
            (
                "oracle://u:p@h:1521/db",
                {"engine": "other", "driver": None, "host": "h", "port": 1521, "database": "db"},
            ),
            (
                None,
                {"engine": "other", "driver": None, "host": None, "port": None, "database": None},
            ),
        ],
    )
    def test_db_endpoint_from_url(self, url, expected):
        assert db_endpoint_from_url(url) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://user:pass@example.com:443/app?x=1#y", "https://example.com:443/app"),
            ("HTTP://Example.COM/app/", "http://example.com/app/"),
            ("https://example.com", "https://example.com"),
            ("http://10.0.0.1:9999", "http://10.0.0.1:9999"),
            ("/app", None),
            ("//host/path", None),
            ("ftp://example.com", None),
            ("http:///nohost", None),
            ("http://example.com:99999", None),
            ("http://example.com:abc", None),
            ("", None),
            (None, None),
            ("not a url", None),
        ],
    )
    def test_normalize_public_base_url(self, raw, expected):
        assert normalize_public_base_url(raw) == expected

    def test_resolve_web_concurrency_no_strip(self):
        # 純空白非空：對齊 shell -z，不得當成空字串 fallback
        assert resolve_web_concurrency("   ") == (None, "invalid_configured")
        assert resolve_web_concurrency("") == (None, "inferred_default")
        assert resolve_web_concurrency(None) == (None, "inferred_default")
        assert resolve_web_concurrency("3") == (3, "configured")


class TestInferredConcurrencyHelper:
    """啟動腳本共用 helper：從 resolved settings（env + config.yaml）推導預設。

    子行程以 tmp cwd 執行，隔離 repo 根目錄的 `.env`／`config.yaml`。
    """

    def _run_helper(self, tmp_path, config_yaml: str, extra_env: dict | None = None) -> str:
        import subprocess
        import sys

        repo_root = Path(__file__).resolve().parents[2]
        helper = repo_root / "scripts" / "print_inferred_web_concurrency.py"
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_yaml, encoding="utf-8")
        env = {
            **os.environ,
            "APP_CONFIG_PATH": str(config_path),
            "PYTHONPATH": str(repo_root),
        }
        env.pop("DATABASE_URL", None)
        if extra_env:
            env.update(extra_env)
        # app/config.py 的 load_dotenv() 以 config.py 檔案位置向上找 .env（與 cwd 無關），
        # 會把 repo 根目錄 .env 的 DATABASE_URL 灌進子行程；在 import 前 stub 掉以隔離。
        bootstrap = (
            "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
            f"import runpy; runpy.run_path({str(helper)!r}, run_name='__main__')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", bootstrap],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    @pytest.mark.parametrize(
        ("db_url", "expected"),
        [
            ("mysql+asyncmy://u:p@h:3306/db", "5"),
            ("postgres://u:p@h:5432/db", "5"),
            ("postgresql+asyncpg://u:p@h:5432/db", "5"),
            ("sqlite:///./x.db", "1"),
        ],
    )
    def test_config_only_engine(self, tmp_path, db_url, expected):
        """DB 僅設定於 config.yaml（無 DATABASE_URL env）也要推導正確引擎預設。"""
        assert self._run_helper(tmp_path, f"app:\n  database_url: {db_url}\n") == expected

    def test_env_database_url_overrides_config(self, tmp_path):
        value = self._run_helper(
            tmp_path,
            "app:\n  database_url: sqlite:///./x.db\n",
            extra_env={"DATABASE_URL": "mysql+asyncmy://u:p@h:3306/db"},
        )
        assert value == "5"


_ENV_UNSET = object()

_FAKE_UV = """#!/bin/sh
# 測試替身：攔截啟動腳本的 uv 呼叫，回報 uvicorn 子行程實際看到的 env 與參數
case "$*" in
    *print_inferred_web_concurrency*) echo 5; exit 0 ;;
    *database_init*) exit 0 ;;
    *uvicorn*)
        echo "child_WEB_CONCURRENCY=${WEB_CONCURRENCY-__UNSET__}"
        echo "child_args=$*"
        exit 0 ;;
    *) exit 0 ;;
esac
"""


class TestStartupScriptsPreserveWebConcurrencyEnv:
    """啟動腳本不得覆寫 WEB_CONCURRENCY 本身（openspec verify 回饋）。

    已 export 的空字串若被覆寫成推導值，uvicorn 子行程會看到數字，
    runtime settings API 便誤報 configured 而非 inferred_default。
    """

    def _fake_bin(self, tmp_path) -> Path:
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        uv = fake_bin / "uv"
        uv.write_text(_FAKE_UV, encoding="utf-8")
        uv.chmod(0o755)
        return fake_bin

    def _base_env(self, tmp_path, web_concurrency) -> dict:
        env = {**os.environ, "PATH": f"{self._fake_bin(tmp_path)}:{os.environ['PATH']}"}
        env.pop("WEB_CONCURRENCY", None)
        if web_concurrency is not _ENV_UNSET:
            env["WEB_CONCURRENCY"] = web_concurrency
        return env

    def _run_entrypoint(self, tmp_path, web_concurrency) -> str:
        import subprocess

        repo_root = Path(__file__).resolve().parents[2]
        env = self._base_env(tmp_path, web_concurrency)
        env["SKIP_DATABASE_BOOTSTRAP"] = "1"
        result = subprocess.run(
            ["/bin/sh", str(repo_root / "docker" / "app-entrypoint.sh")],
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    @pytest.mark.parametrize(
        ("web_concurrency", "expected_child", "expect_workers"),
        [
            (_ENV_UNSET, "child_WEB_CONCURRENCY=__UNSET__", "--workers 5"),
            ("", "child_WEB_CONCURRENCY=", "--workers 5"),
            ("3", "child_WEB_CONCURRENCY=3", "--workers 3"),
        ],
        ids=["unset", "exported-empty", "explicit"],
    )
    def test_entrypoint_child_env_and_workers(
        self, tmp_path, web_concurrency, expected_child, expect_workers
    ):
        stdout = self._run_entrypoint(tmp_path, web_concurrency)
        lines = stdout.splitlines()
        assert expected_child in lines, stdout
        child_args = next(line for line in lines if line.startswith("child_args="))
        assert expect_workers in child_args

    @pytest.mark.parametrize(
        ("web_concurrency", "expected_child", "expect_workers"),
        [
            (_ENV_UNSET, "child_WEB_CONCURRENCY=__UNSET__", "--workers 5"),
            ("", "child_WEB_CONCURRENCY=", "--workers 5"),
        ],
        ids=["unset", "exported-empty"],
    )
    def test_start_sh_child_env_and_workers(
        self, tmp_path, web_concurrency, expected_child, expect_workers
    ):
        import subprocess
        import time

        repo_root = Path(__file__).resolve().parents[2]
        workdir = tmp_path / "run"
        workdir.mkdir()
        log_path = workdir / "server.log"
        env = self._base_env(tmp_path, web_concurrency)
        env.update(
            {
                "UVICORN_RELOAD": "0",
                "PORT": "65123",
                "SERVER_PID_FILE": str(workdir / "server.pid"),
                "SERVER_LOG": str(log_path),
            }
        )
        result = subprocess.run(
            ["/bin/bash", str(repo_root / "start.sh")],
            capture_output=True,
            text=True,
            env=env,
            cwd=workdir,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        # fake uvicorn 由 nohup 背景執行：輪詢 log 直到輸出落地
        deadline = time.monotonic() + 10
        content = ""
        while time.monotonic() < deadline:
            content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            if "child_args=" in content:
                break
            time.sleep(0.1)
        lines = content.splitlines()
        assert expected_child in lines, content
        child_args = next(line for line in lines if line.startswith("child_args="))
        assert expect_workers in child_args
