"""Super Admin log viewer API（/api/admin/system-logs*）契約測試。"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import app.api.admin as admin_module
from app.audit import ActionType, ResourceType, audit_service
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole
from app.auth.permission_service import permission_service
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database_models import User
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

SNAPSHOT_URL = "/api/admin/system-logs"
STREAM_URL = "/api/admin/system-logs/stream"


@pytest.fixture
def log_api_env(tmp_path, monkeypatch):
    main_bundle = create_managed_test_database(tmp_path / "log_api_main.db")
    audit_bundle = create_managed_test_database(tmp_path / "log_api_audit.db", target_name="audit")

    with main_bundle["sync_session_factory"]() as session:
        super_user = User(
            username="log-super",
            email="log-super@example.com",
            hashed_password="x",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_verified=True,
        )
        normal_user = User(
            username="log-normal",
            email="log-normal@example.com",
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
    handler = install_system_log_handler(100, 500, 50)
    monkeypatch.setattr(settings.log_viewer, "keepalive_seconds", 1)
    # TestClient 關閉串流不會立即取消 server generator，context 退出會等 generator
    # 跑到 lifetime 屆滿——保持短生命週期讓每個串流測試最多等 ~3 秒
    monkeypatch.setattr(settings.log_viewer, "stream_max_lifetime_seconds", 3)
    monkeypatch.setattr(admin_module, "_active_log_streams", 0)

    yield {"super_id": super_id, "normal_id": normal_id, "handler": handler}

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
    _login_as(env["super_id"], "log-super", UserRole.SUPER_ADMIN)


def _emit(message: str, level: int = logging.INFO, name: str = "app.test") -> None:
    from app.utils.system_log_buffer import get_system_log_handler

    record = logging.LogRecord(name, level, __file__, 0, message, None, None)
    get_system_log_handler().emit(record)


class TestSnapshotAuth:
    def test_anonymous_rejected(self, log_api_env):
        client = TestClient(app)
        resp = client.get(SNAPSHOT_URL)
        assert resp.status_code in (401, 403)
        assert "entries" not in resp.text

    def test_non_super_admin_rejected(self, log_api_env):
        _login_as(log_api_env["normal_id"], "log-normal", UserRole.USER)
        client = TestClient(app)
        assert client.get(SNAPSHOT_URL).status_code == 403
        with client.stream("GET", STREAM_URL) as resp:
            assert resp.status_code == 403


class TestSnapshot:
    def test_ok_with_headers_and_fields(self, log_api_env):
        _login_super(log_api_env)
        _emit("hello snapshot")
        client = TestClient(app)
        resp = client.get(SNAPSHOT_URL)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert resp.headers["pragma"] == "no-cache"
        payload = resp.json()
        assert payload["worker_instance_id"] == log_api_env["handler"].worker_instance_id
        assert payload["pid"] and payload["oldest_seq"] == 1 and payload["latest_seq"] == 1
        entry = payload["entries"][0]
        assert entry["message"] == "hello snapshot"
        assert entry["level"] == "INFO" and entry["logger_name"] == "app.test"
        assert entry["seq"] == 1 and entry["timestamp"] and entry["pid"]

    def test_level_is_minimum_threshold_and_logger_prefix(self, log_api_env):
        _login_super(log_api_env)
        _emit("info-msg", logging.INFO, "app.a")
        _emit("warn-msg", logging.WARNING, "app.a")
        _emit("error-msg", logging.ERROR, "uvicorn.access")
        client = TestClient(app)
        warn_up = client.get(SNAPSHOT_URL, params={"level": "WARNING"}).json()
        assert [e["message"] for e in warn_up["entries"]] == ["warn-msg", "error-msg"]
        app_only = client.get(SNAPSHOT_URL, params={"logger": "app."}).json()
        assert [e["message"] for e in app_only["entries"]] == ["info-msg", "warn-msg"]

    def test_limit_is_tail_and_clamped(self, log_api_env):
        _login_super(log_api_env)
        for i in range(10):
            _emit(f"m{i}")
        client = TestClient(app)
        tail = client.get(SNAPSHOT_URL, params={"limit": 3}).json()
        assert [e["message"] for e in tail["entries"]] == ["m7", "m8", "m9"]
        clamped = client.get(SNAPSHOT_URL, params={"limit": 999999}).json()
        assert len(clamped["entries"]) == 10  # clamp 到上限但不報錯

    def test_snapshot_redacts_secrets(self, log_api_env):
        _login_super(log_api_env)
        _emit("login password=hunter2 done")
        client = TestClient(app)
        body = client.get(SNAPSHOT_URL).json()
        assert "hunter2" not in json.dumps(body)
        assert "***REDACTED***" in body["entries"][0]["message"]

    def test_openapi_excludes_system_log_endpoints(self, log_api_env):
        _login_super(log_api_env)
        client = TestClient(app)
        paths = client.get("/openapi.json").json()["paths"]
        assert SNAPSHOT_URL not in paths
        assert STREAM_URL not in paths


def _fake_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": STREAM_URL,
            "query_string": b"",
            "headers": [(b"user-agent", b"pytest-ua")],
            "client": ("1.2.3.4", 1234),
        }
    )


def _super_user(env) -> SimpleNamespace:
    return SimpleNamespace(id=env["super_id"], username="log-super", role=UserRole.SUPER_ADMIN)


async def _open_stream(env, since_seq=None, instance_id=None):
    """直接呼叫 endpoint：Starlette TestClient 會把 ASGI app 跑完才回傳 response，
    無法對無限 SSE 串流做即時讀取，故串流內容測試改為迭代 body_iterator。"""
    response = await admin_module.stream_system_logs(
        request=_fake_request(),
        since_seq=since_seq,
        instance_id=instance_id,
        current_user=_super_user(env),
    )
    return _StreamReader(response), response


def _parse_frame(text: str):
    event: dict = {"event": None, "id": None, "data": None}
    data_lines = []
    has_field = False
    for line in text.split("\n"):
        if not line or line.startswith(":"):
            continue
        key, _, value = line.partition(":")
        value = value.lstrip()
        has_field = True
        if key == "event":
            event["event"] = value
        elif key == "id":
            event["id"] = int(value)
        elif key == "data":
            data_lines.append(value)
    if not has_field:
        return None  # keep-alive comment frame
    raw = "\n".join(data_lines)
    event["data"] = json.loads(raw) if raw else None
    return event


class _StreamReader:
    def __init__(self, response):
        self.iterator = response.body_iterator
        self.buffer = ""
        self.pending: list = []

    async def read_events(self, count: int, timeout: float = 5.0, max_frames: int = 50):
        events = []
        frames_seen = 0
        while len(events) < count:
            while self.pending and len(events) < count:
                events.append(self.pending.pop(0))
            if len(events) >= count:
                break
            chunk = await asyncio.wait_for(self.iterator.__anext__(), timeout)
            self.buffer += chunk
            while "\n\n" in self.buffer:
                frame_text, self.buffer = self.buffer.split("\n\n", 1)
                frames_seen += 1
                assert frames_seen <= max_frames, f"讀了 {frames_seen} frames 仍未湊滿 {count} 個事件"
                parsed = _parse_frame(frame_text)
                if parsed is not None:
                    self.pending.append(parsed)
        return events

    async def aclose(self):
        await self.iterator.aclose()


class TestStream:
    async def test_meta_replay_and_live_push(self, log_api_env):
        for i in range(3):
            _emit(f"old{i}")
        reader, response = await _open_stream(log_api_env)
        try:
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["pragma"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            assert response.media_type == "text/event-stream"
            events = await reader.read_events(4)
            meta, logs = events[0], events[1:]
            assert meta["event"] == "meta"
            assert meta["data"]["worker_instance_id"] == log_api_env["handler"].worker_instance_id
            assert meta["data"]["oldest_seq"] == 1 and meta["data"]["latest_seq"] == 3
            assert [e["data"]["message"] for e in logs] == ["old0", "old1", "old2"]
            assert [e["id"] for e in logs] == [1, 2, 3]
            _emit("live!")
            live = (await reader.read_events(1))[0]
            assert live["event"] == "log" and live["data"]["message"] == "live!"
            assert live["data"]["seq"] == 4
        finally:
            await reader.aclose()

    async def test_resume_with_valid_cursor(self, log_api_env):
        for i in range(5):
            _emit(f"m{i}")
        instance = log_api_env["handler"].worker_instance_id
        reader, _ = await _open_stream(log_api_env, since_seq="2", instance_id=instance)
        try:
            events = await reader.read_events(4)
            assert events[0]["event"] == "meta"
            assert all(e["event"] == "log" for e in events[1:])
            assert [e["data"]["seq"] for e in events[1:]] == [3, 4, 5]
        finally:
            await reader.aclose()

    @pytest.mark.parametrize(
        "params",
        [
            {"since_seq": "3"},  # 缺 instance_id
            {"since_seq": "3", "instance_id": "someone-else"},  # instance 不符
            {"since_seq": "abc", "instance_id": "__REAL__"},  # 非整數不得 422
            {"since_seq": "-1", "instance_id": "__REAL__"},  # 負數
            {"since_seq": "9999", "instance_id": "__REAL__"},  # 超前 → reset
        ],
    )
    async def test_cursor_reset_full_replay(self, log_api_env, params):
        for i in range(3):
            _emit(f"m{i}")
        if params.get("instance_id") == "__REAL__":
            params["instance_id"] = log_api_env["handler"].worker_instance_id
        reader, _ = await _open_stream(log_api_env, **params)
        try:
            events = await reader.read_events(4)
            assert events[0]["event"] == "meta"
            assert [e["data"]["seq"] for e in events[1:]] == [1, 2, 3]  # 全量回放、無 gap
        finally:
            await reader.aclose()

    async def test_non_integer_since_seq_not_422_over_http(self, log_api_env):
        """HTTP 層驗證：非整數 since_seq 不得被 FastAPI 提前 422（TestClient 會
        等串流跑完，故以 1 秒 lifetime 讓回應快速完結，只斷言狀態碼）。"""
        _login_super(log_api_env)
        settings.log_viewer.stream_max_lifetime_seconds = 1
        client = TestClient(app)
        for value in ("abc", "-1"):
            resp = client.get(STREAM_URL, params={"since_seq": value})
            assert resp.status_code == 200, value

    async def test_gap_only_when_data_actually_lost(self, log_api_env):
        # 小 buffer 讓最舊資料被淘汰：buffer_size=5、emit 8 → 剩 seq 4..8
        reset_system_log_handler()
        handler = install_system_log_handler(5, 500, 50)
        log_api_env["handler"] = handler
        for i in range(8):
            _emit(f"m{i}")
        instance = handler.worker_instance_id

        # since_seq=1 < oldest-1=3 → gap，lost = 4 - 1 - 1 = 2
        reader, _ = await _open_stream(log_api_env, since_seq="1", instance_id=instance)
        try:
            events = await reader.read_events(7)
            assert events[0]["event"] == "meta"
            assert events[1]["event"] == "gap" and events[1]["data"]["lost_count"] == 2
            assert [e["data"]["seq"] for e in events[2:]] == [4, 5, 6, 7, 8]
        finally:
            await reader.aclose()

        # since_seq=3 = oldest-1 → 恰可完整涵蓋，不送 gap
        reader, _ = await _open_stream(log_api_env, since_seq="3", instance_id=instance)
        try:
            events = await reader.read_events(6)
            assert all(e["event"] != "gap" for e in events)
            assert [e["data"]["seq"] for e in events[1:]] == [4, 5, 6, 7, 8]
        finally:
            await reader.aclose()

    async def test_empty_buffer_boundaries(self, log_api_env):
        reader, _ = await _open_stream(log_api_env)
        try:
            meta = (await reader.read_events(1))[0]
            assert meta["event"] == "meta"
            assert meta["data"]["oldest_seq"] is None and meta["data"]["latest_seq"] is None
            _emit("first-live")
            live = (await reader.read_events(1))[0]
            assert live["event"] == "log" and live["data"]["seq"] == 1
        finally:
            await reader.aclose()

    async def test_stream_redacts_secrets(self, log_api_env):
        _emit("Authorization: Bearer super-secret-token-abc")
        reader, _ = await _open_stream(log_api_env)
        try:
            events = await reader.read_events(2)
            assert "super-secret-token-abc" not in json.dumps(events[1]["data"])
        finally:
            await reader.aclose()

    async def test_429_when_slots_exhausted(self, log_api_env, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(admin_module, "_active_log_streams", settings.log_viewer.max_streams)
        with pytest.raises(HTTPException) as exc_info:
            await _open_stream(log_api_env)
        assert exc_info.value.status_code == 429

    async def test_slot_released_after_disconnect(self, log_api_env):
        reader, _ = await _open_stream(log_api_env)
        await reader.read_events(1)
        assert admin_module._active_log_streams == 1
        await reader.aclose()
        assert admin_module._active_log_streams == 0  # disconnect 後 slot 釋放
        reader, _ = await _open_stream(log_api_env)  # 可再連
        await reader.read_events(1)
        await reader.aclose()

    async def test_lifetime_end_event(self, log_api_env, monkeypatch):
        monkeypatch.setattr(settings.log_viewer, "stream_max_lifetime_seconds", 1)
        reader, _ = await _open_stream(log_api_env)
        try:
            events = await reader.read_events(2, max_frames=10)
            assert events[0]["event"] == "meta"
            assert events[1]["event"] == "end" and events[1]["data"]["reason"] == "lifetime"
        finally:
            await reader.aclose()


class TestStreamAudit:
    async def test_subscribe_failure_releases_slot(self, log_api_env, monkeypatch):
        monkeypatch.setattr(
            log_api_env["handler"],
            "subscribe",
            lambda: (_ for _ in ()).throw(RuntimeError("subscribe failed")),
        )
        reader, _ = await _open_stream(log_api_env)

        with pytest.raises(RuntimeError, match="subscribe failed"):
            await reader.iterator.__anext__()
        assert admin_module._active_log_streams == 0

    async def test_cancel_during_audit_releases_slot(self, log_api_env, monkeypatch):
        audit_started = asyncio.Event()

        async def blocked_log_action(**kwargs):
            audit_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(audit_service, "log_action", blocked_log_action)
        open_task = asyncio.create_task(_open_stream(log_api_env))
        await audit_started.wait()
        assert admin_module._active_log_streams == 1

        open_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await open_task
        assert admin_module._active_log_streams == 0

    async def test_audit_written_on_stream_open(self, log_api_env, monkeypatch):
        calls = []

        async def fake_log_action(**kwargs):
            calls.append(kwargs)

        monkeypatch.setattr(audit_service, "log_action", fake_log_action)
        reader, _ = await _open_stream(log_api_env, since_seq="7")
        await reader.read_events(1)
        await reader.aclose()
        assert len(calls) == 1
        call = calls[0]
        assert call["action_type"] == ActionType.READ
        assert call["resource_type"] == ResourceType.SYSTEM
        assert call["resource_id"] == "system-logs-stream"
        assert call["details"]["since_seq"] == "7"
        assert call["details"]["worker_instance_id"] == log_api_env["handler"].worker_instance_id
        assert call["user_id"] == log_api_env["super_id"]
        assert call["ip_address"] == "1.2.3.4"
        assert call["user_agent"] == "pytest-ua"

    async def test_audit_failure_does_not_block_stream(self, log_api_env, monkeypatch):
        async def broken_log_action(**kwargs):
            raise RuntimeError("audit down")

        monkeypatch.setattr(audit_service, "log_action", broken_log_action)
        _emit("still-works")
        reader, _ = await _open_stream(log_api_env)
        try:
            events = await reader.read_events(2)
            assert events[1]["data"]["message"] == "still-works"
        finally:
            await reader.aclose()


class TestPageSmoke:
    def test_system_logs_page_renders(self):
        client = TestClient(app)
        resp = client.get("/system-logs")
        assert resp.status_code == 200
        assert 'id="logOutput"' in resp.text
        assert "/static/js/system-logs-core.js" in resp.text
        assert "/static/js/system-logs.js" in resp.text
        assert "/static/css/system-logs.css" in resp.text

    def test_system_logs_page_has_tabs_shell(self):
        """Logs / Runtime Settings 分頁殼層（openspec: add-system-runtime-settings-viewer）。"""
        client = TestClient(app)
        html = client.get("/system-logs").text
        assert 'id="logsTabBtn"' in html and 'id="runtimeSettingsTabBtn"' in html
        assert 'data-bs-toggle="tab"' in html
        # 預設顯示 Logs 分頁；兩個 panel 皆可聚焦（tabindex="0"）
        assert 'id="logsTabPane"' in html and 'id="runtimeSettingsTabPane"' in html
        assert html.count('role="tabpanel"') == 2
        assert html.count('tabindex="0"') >= 2
        assert 'id="rtsRefreshBtn"' in html and 'id="rtsContent"' in html

    def test_static_assets_exist(self):
        client = TestClient(app)
        for path in (
            "/static/js/system-logs-core.js",
            "/static/js/system-logs.js",
            "/static/css/system-logs.css",
        ):
            assert client.get(path).status_code == 200, path
