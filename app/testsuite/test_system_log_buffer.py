"""Super Admin log viewer 捕捉層（ring buffer handler / redact / config）測試。"""

import asyncio
import logging
import threading

import pytest

from app.config import LogViewerConfig
from app.utils.system_log_buffer import (
    REDACTION_MARKER,
    TRUNCATION_MARKER,
    RingBufferLogHandler,
    install_system_log_handler,
    redact_sensitive,
    reset_system_log_handler,
)


@pytest.fixture(autouse=True)
def _clean_handler_state():
    reset_system_log_handler()
    yield
    reset_system_log_handler()


def _make_record(msg: str, level: int = logging.INFO, name: str = "test") -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 0, msg, None, None)


def _handler(buffer_size=5, max_chars=100, queue_size=3) -> RingBufferLogHandler:
    return RingBufferLogHandler(buffer_size, max_chars, queue_size)


class _CountingLoopProxy:
    """包一層 event loop 以計數 call_soon_threadsafe 排程次數。"""

    def __init__(self, loop):
        self._loop = loop
        self.scheduled = 0

    def call_soon_threadsafe(self, *args, **kwargs):
        self.scheduled += 1
        return self._loop.call_soon_threadsafe(*args, **kwargs)

    def __getattr__(self, item):
        return getattr(self._loop, item)


class TestRingBuffer:
    def test_capacity_eviction(self):
        h = _handler(buffer_size=3)
        for i in range(5):
            h.emit(_make_record(f"m{i}"))
        entries, oldest, latest = h.snapshot()
        assert [e["message"] for e in entries] == ["m2", "m3", "m4"]
        assert (oldest, latest) == (3, 5)

    def test_truncation_marker(self):
        h = _handler(max_chars=10)
        h.emit(_make_record("x" * 50))
        entries, _, _ = h.snapshot()
        assert entries[0]["message"] == "x" * 10 + TRUNCATION_MARKER

    def test_emit_never_raises(self, monkeypatch):
        h = _handler()
        monkeypatch.setattr(h, "format", lambda record: (_ for _ in ()).throw(RuntimeError("boom")))
        h.emit(_make_record("m"))  # 不得拋出
        assert h.snapshot()[0] == []

    def test_snapshot_filters_and_tail_limit(self):
        h = _handler(buffer_size=20)
        for i in range(10):
            level = logging.WARNING if i % 2 else logging.INFO
            name = "uvicorn.access" if i < 5 else "app.core"
            record = _make_record(f"m{i}", level=level, name=name)
            h.emit(record)
        warn_only, _, _ = h.snapshot(level="WARNING")
        assert all(e["level"] == "WARNING" for e in warn_only) and len(warn_only) == 5
        app_only, _, _ = h.snapshot(logger_prefix="app.")
        assert [e["message"] for e in app_only] == ["m5", "m6", "m7", "m8", "m9"]
        # tail 語意：取最新 N 筆再依 seq 遞增排序，而非最舊 N 筆
        tail, _, _ = h.snapshot(limit=3)
        assert [e["message"] for e in tail] == ["m7", "m8", "m9"]

    def test_cross_thread_emit_with_concurrent_snapshot(self):
        h = _handler(buffer_size=10000, queue_size=10000)
        errors = []

        def writer():
            try:
                for i in range(2000):
                    h.emit(_make_record(f"w{i}"))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for _ in range(200):
            h.snapshot()  # 與 append 併發，不得拋出
        for t in threads:
            t.join()
        assert not errors
        entries, _, _ = h.snapshot()
        assert len(entries) == 8000
        seqs = [e["seq"] for e in entries]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


class TestSubscription:
    async def test_pending_bounded_and_no_loop_exception(self):
        captured = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda lp, ctx: captured.append(ctx))
        try:
            h = _handler(queue_size=3)
            sub, replay, replay_latest = h.subscribe()
            assert replay == [] and replay_latest == 0
            for i in range(10):
                h.emit(_make_record(f"m{i}"))
            await asyncio.sleep(0)  # 讓 wakeup callback 執行
            batch = h.take_batch(sub)
            assert [e["message"] for e in batch] == ["m7", "m8", "m9"]  # 滿即淘汰最舊
            assert captured == []  # event loop exception handler 不得收到例外
            h.unsubscribe(sub)
        finally:
            loop.set_exception_handler(None)

    async def test_single_outstanding_wakeup(self):
        h = _handler(buffer_size=100, queue_size=100)
        sub, _, _ = h.subscribe()
        proxy = _CountingLoopProxy(sub.loop)
        sub.loop = proxy
        for i in range(50):  # event loop 未 yield 期間大量 emit
            h.emit(_make_record(f"m{i}"))
        assert proxy.scheduled == 1  # 至多一個 outstanding wakeup，不隨筆數成長
        await asyncio.sleep(0)
        assert len(h.take_batch(sub)) == 50
        h.unsubscribe(sub)

    async def test_emit_between_wakeup_and_drain(self):
        """callback 已執行（event 已 set）但 generator 尚未取 batch 期間持續 emit。"""
        h = _handler(buffer_size=100, queue_size=5)
        sub, _, _ = h.subscribe()
        proxy = _CountingLoopProxy(sub.loop)
        sub.loop = proxy
        h.emit(_make_record("first"))
        await asyncio.sleep(0)  # wakeup callback 執行，event set、flag 仍為 True
        assert sub.wake_event.is_set()
        for i in range(20):
            h.emit(_make_record(f"late{i}"))
        assert proxy.scheduled == 1  # flag 未清，不重複排程
        assert len(sub.pending) <= 5  # pending 有界
        batch = h.take_batch(sub)
        assert batch and batch[-1]["message"] == "late19"  # generator 最終取得資料
        h.emit(_make_record("after-drain"))
        assert proxy.scheduled == 2  # flag 清除後的新 emit 觸發下一次喚醒
        h.unsubscribe(sub)

    async def test_atomic_subscribe_no_loss_no_dup(self):
        h = _handler(buffer_size=100000, queue_size=100000)
        stop = threading.Event()

        def writer():
            i = 0
            while not stop.is_set():
                h.emit(_make_record(f"w{i}"))
                i += 1

        t = threading.Thread(target=writer)
        t.start()
        try:
            for _ in range(20):  # 反覆在寫入洪流中訂閱
                sub, replay, replay_latest = h.subscribe()
                await asyncio.sleep(0.01)
                batch = h.take_batch(sub)
                h.unsubscribe(sub)
                replay_seqs = [e["seq"] for e in replay]
                live_seqs = [e["seq"] for e in batch if e["seq"] > replay_latest]
                assert all(s <= replay_latest for s in replay_seqs)
                combined = replay_seqs + live_seqs
                assert len(set(combined)) == len(combined)  # 無重複
                if live_seqs:  # 分界前後接續，無遺失
                    assert live_seqs[0] == replay_latest + 1
                    assert live_seqs == list(range(live_seqs[0], live_seqs[-1] + 1))
        finally:
            stop.set()
            t.join()

    async def test_unsubscribe_stops_delivery(self):
        h = _handler()
        sub, _, _ = h.subscribe()
        h.unsubscribe(sub)
        h.emit(_make_record("m"))
        assert h.subscriber_count() == 0 and len(sub.pending) == 0


class TestRedaction:
    @pytest.mark.parametrize(
        "text,leaked",
        [
            ("Authorization: Bearer abc123token", "abc123token"),
            ("jwt eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM", "eyJhbGciOi"),
            ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSM", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.SflKxwRJSM"),
            ("password=hunter2", "hunter2"),
            ("PASSWORD=HUNTER2", "HUNTER2"),
            ("url ?token=sekrit&next=1", "sekrit"),
            ('{"access_token": "aaa111"}', "aaa111"),
            ('{"password": "hello world"}', "hello world"),
            ("{'api_key': 'bbb222'}", "bbb222"),
            ("{'secret': 'alpha beta'}", "alpha beta"),
            ("client_secret: ccc333", "ccc333"),
            ("refresh_token=ddd444;", "ddd444"),
            ("authorization=Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ],
    )
    def test_secret_shapes_are_redacted(self, text, leaked):
        result = redact_sensitive(text)
        assert leaked not in result and REDACTION_MARKER in result

    def test_plain_text_untouched(self):
        text = "GET /api/health 200 OK user=alice"
        assert redact_sensitive(text) == text


class TestInstall:
    def test_idempotent_mount_and_capture_once(self):
        install_system_log_handler(100, 100, 10)
        h = install_system_log_handler(100, 100, 10)
        root = logging.getLogger()
        assert sum(1 for x in root.handlers if isinstance(x, RingBufferLogHandler)) == 1
        before = len(h.snapshot()[0])
        logging.getLogger("app.something").warning("once")
        entries, _, _ = h.snapshot()
        assert len(entries) == before + 1  # 恰好捕捉一次

    def test_uvicorn_logger_no_propagate_captured_once(self):
        access = logging.getLogger("uvicorn.access")
        old_propagate, old_handlers = access.propagate, list(access.handlers)
        try:
            access.propagate = False
            access.setLevel(logging.INFO)
            h = install_system_log_handler(100, 100, 10)
            assert sum(1 for x in access.handlers if isinstance(x, RingBufferLogHandler)) == 1
            before = len(h.snapshot()[0])
            access.info("GET / 200")
            assert len(h.snapshot()[0]) == before + 1
        finally:
            access.propagate = old_propagate
            access.handlers = old_handlers

    def test_uvicorn_logger_propagating_not_double_attached(self):
        error_logger = logging.getLogger("uvicorn.error")
        old_propagate, old_handlers = error_logger.propagate, list(error_logger.handlers)
        try:
            error_logger.propagate = True
            error_logger.handlers = []
            h = install_system_log_handler(100, 100, 10)
            assert not any(isinstance(x, RingBufferLogHandler) for x in error_logger.handlers)
            before = len(h.snapshot()[0])
            error_logger.warning("server thing")
            assert len(h.snapshot()[0]) == before + 1  # 經 root 捕捉一次
        finally:
            error_logger.propagate = old_propagate
            error_logger.handlers = old_handlers

    def test_stdout_handlers_untouched(self):
        root = logging.getLogger()
        recorder = logging.Handler()
        seen = []
        recorder.emit = lambda record: seen.append(record.getMessage())
        root.addHandler(recorder)
        try:
            install_system_log_handler(100, 100, 10)
            logging.getLogger("app.x").warning("passthrough")
            assert seen == ["passthrough"]  # 既有 handler 收到的格式與數量不變
        finally:
            root.removeHandler(recorder)


class TestConfigBounds:
    def test_defaults_without_env(self, monkeypatch):
        for env, *_ in LogViewerConfig.FIELD_BOUNDS:
            monkeypatch.delenv(env, raising=False)
        c = LogViewerConfig.from_env()
        assert c.buffer_size == 2000 and c.keepalive_seconds == 15

    @pytest.mark.parametrize(
        "env,value,field,expected",
        [
            ("LOG_VIEWER_BUFFER_SIZE", "abc", "buffer_size", 2000),
            ("LOG_VIEWER_BUFFER_SIZE", "-5", "buffer_size", 2000),
            ("LOG_VIEWER_BUFFER_SIZE", "999999", "buffer_size", 2000),
            ("LOG_VIEWER_KEEPALIVE_SECONDS", "1", "keepalive_seconds", 15),
            ("LOG_VIEWER_STREAM_MAX_LIFETIME_SECONDS", "10", "stream_max_lifetime_seconds", 900),
            ("LOG_VIEWER_MAX_STREAMS", "0", "max_streams", 3),
        ],
    )
    def test_invalid_or_out_of_range_falls_back(self, monkeypatch, env, value, field, expected):
        monkeypatch.setenv(env, value)
        assert getattr(LogViewerConfig.from_env(), field) == expected

    def test_within_range_accepted(self, monkeypatch):
        monkeypatch.setenv("LOG_VIEWER_KEEPALIVE_SECONDS", "5")
        monkeypatch.setenv("LOG_VIEWER_STREAM_MAX_LIFETIME_SECONDS", "60")
        c = LogViewerConfig.from_env()
        assert c.keepalive_seconds == 5 and c.stream_max_lifetime_seconds == 60

    def test_legal_fields_but_aggregate_budget_exceeded(self, monkeypatch):
        # 單欄位皆合法，但 20000 × 65536 遠超 2^25 → 容量欄位整組回落預設
        monkeypatch.setenv("LOG_VIEWER_BUFFER_SIZE", "20000")
        monkeypatch.setenv("LOG_VIEWER_MAX_MESSAGE_CHARS", "65536")
        monkeypatch.setenv("LOG_VIEWER_KEEPALIVE_SECONDS", "30")
        c = LogViewerConfig.from_env()
        assert c.buffer_size == 2000 and c.max_message_chars == 4096
        assert c.keepalive_seconds == 30  # 時間欄位不受容量回落影響

    def test_subscriber_side_budget(self, monkeypatch):
        # 2 × 10 × 10000 × 4096 > 2^25 → 回落
        monkeypatch.setenv("LOG_VIEWER_MAX_STREAMS", "10")
        monkeypatch.setenv("LOG_VIEWER_SUBSCRIBER_QUEUE_SIZE", "10000")
        c = LogViewerConfig.from_env()
        assert c.max_streams == 3 and c.subscriber_queue_size == 1000
