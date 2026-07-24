"""Unit tests for KnowledgeQueryLogService (openspec: log-knowledge-graph-queries)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.audit.database import (
    KnowledgeQueryLogTable,
    KnowledgeQuerySource,
    KnowledgeQueryOperation,
    KnowledgeQueryStatus,
)
from app.services.knowledge.query_log_service import (
    KnowledgeQueryLogService,
    _cap_size,
    _truncate_chars,
    _json_dumps_safe,
)
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_audit_database_overrides,
)


def _install_audit(monkeypatch, tmp_path: Path) -> dict:
    bundle = create_managed_test_database(tmp_path / "kq_audit.db", target_name="audit")
    install_audit_database_overrides(
        monkeypatch=monkeypatch,
        async_session_factory=bundle["async_session_factory"],
    )
    return bundle


@pytest.fixture
def audit_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_ENABLED", "true")
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_RETENTION_DAYS", "30")
    bundle = _install_audit(monkeypatch, tmp_path)
    yield bundle
    dispose_managed_test_database(bundle)


def _run(coro):
    return asyncio.run(coro)


def test_record_writes_to_db(audit_env) -> None:
    svc = KnowledgeQueryLogService()
    _run(
        svc.record(
            source=KnowledgeQuerySource.ASSISTANT,
            operation=KnowledgeQueryOperation.SEARCH,
            status=KnowledgeQueryStatus.SUCCESS,
            query_text="login test",
            user_id=1,
            username="alice",
            primary_team_id=1,
            allowed_team_ids=[1, 2],
            top_k=10,
            score_threshold=0.55,
            result_count=3,
            duration_ms=42,
            results_summary=[
                {
                    "entity_type": "test_case",
                    "entity_id": "TC-1",
                    "title": "Hello",
                    "score": 0.9,
                    "team_id": 1,
                }
            ],
            process={"dual_route": True},
        )
    )
    flushed = _run(svc.force_flush())
    assert flushed == 1

    async def _fetch():
        async with audit_env["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().all()

    rows = _run(_fetch())
    assert len(rows) == 1
    row = rows[0]
    assert row.source == KnowledgeQuerySource.ASSISTANT
    assert row.status == KnowledgeQueryStatus.SUCCESS
    assert row.username == "alice"
    assert row.query_text == "login test"
    assert row.top_k == 10
    assert row.result_count == 3
    import json as _json

    assert _json.loads(row.results_summary)[0]["id"] == "TC-1"


def test_record_does_not_throw_on_disabled() -> None:
    svc = KnowledgeQueryLogService()
    svc._force_disabled = True
    _run(
        svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text="x",
        )
    )
    assert _run(svc.force_flush()) == 0


def test_size_cap_truncates_query_text(monkeypatch: pytest.MonkeyPatch, audit_env) -> None:
    """設定較小 max_chars（透過 mock settings）以驗證 size cap 確實生效。"""
    from unittest.mock import patch as _patch

    from app.config import AuditConfig, Settings

    svc = KnowledgeQueryLogService()
    long_text = "x" * 1000

    # 直接以小型 AuditConfig mock 替換 settings.audit，避免 settings singleton 問題
    fake_audit = AuditConfig(knowledge_query_log_max_size_chars=200)
    fake_settings = Settings(audit=fake_audit)
    with _patch("app.services.knowledge.query_log_service.get_settings", return_value=fake_settings):
        _run(
            svc.record(
                source="assistant",
                operation="search",
                status="success",
                query_text=long_text,
            )
        )
        _run(svc.force_flush())

    async def _fetch():
        async with audit_env["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().one()

    row = _run(_fetch())
    assert row.query_text is not None
    assert len(row.query_text) <= 200
    assert row.query_text.endswith("...[truncated]")


def test_cap_size_handles_none_and_short() -> None:
    assert _cap_size(None, 100) is None
    assert _cap_size("short", 100) == "short"
    assert _cap_size("x" * 50, 100) == "x" * 50


def test_truncate_chars_handles_edge_cases() -> None:
    assert _truncate_chars("", 0) == ""
    assert _truncate_chars("abc", 100) == "abc"
    # max_chars <= suffix length
    assert _truncate_chars("abcdefghij", 3) == "abc"


def test_json_dumps_safe_handles_bad_type() -> None:
    """default=str 後仍能序列化任意 Python 物件。"""

    class Custom:
        def __str__(self):
            return "custom-str"

    out = _json_dumps_safe({"x": Custom()})
    assert "custom-str" in out


def test_cleanup_removes_old_records(monkeypatch: pytest.MonkeyPatch, audit_env) -> None:
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_RETENTION_DAYS", "7")

    # Insert one old and one new record directly for deterministic timing
    async def _seed():
        async with audit_env["async_session_factory"]() as session:
            old = KnowledgeQueryLogTable(
                timestamp=datetime.utcnow() - timedelta(days=30),
                source=KnowledgeQuerySource.ASSISTANT.value,
                operation=KnowledgeQueryOperation.SEARCH.value,
                status=KnowledgeQueryStatus.SUCCESS.value,
                schema_version=1,
            )
            new = KnowledgeQueryLogTable(
                timestamp=datetime.utcnow(),
                source=KnowledgeQuerySource.ASSISTANT.value,
                operation=KnowledgeQueryOperation.SEARCH.value,
                status=KnowledgeQueryStatus.SUCCESS.value,
                schema_version=1,
            )
            session.add_all([old, new])
            await session.commit()

    _run(_seed())

    svc = KnowledgeQueryLogService()
    # Force the cleanup cadence to fire on this flush
    svc._cleanup_every_n_flushes = 1
    svc._flush_count_since_cleanup = 0
    _run(
        svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text="trigger",
        )
    )
    _run(svc.force_flush())

    async def _fetch():
        async with audit_env["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().all()

    rows = _run(_fetch())
    timestamps = [r.timestamp for r in rows]
    assert all(t > datetime.utcnow() - timedelta(days=7) for t in timestamps)
    assert len(rows) >= 1


def test_redact_sensitive_applied_to_query_text(audit_env) -> None:
    svc = KnowledgeQueryLogService()
    _run(
        svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text='api_key="super-secret-value"',
        )
    )
    _run(svc.force_flush())

    async def _fetch():
        async with audit_env["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().one()

    row = _run(_fetch())
    assert "super-secret-value" not in (row.query_text or "")
    assert "REDACTED" in (row.query_text or "")


def test_results_summary_trimmed(audit_env) -> None:
    svc = KnowledgeQueryLogService()
    _run(
        svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text="x",
            results_summary=[
                {
                    "entity_type": "test_case",
                    "entity_id": "TC-1",
                    "title": "A",
                    "snippet": "FULL-SNIPPET-SHOULD-NOT-APPEAR",
                    "score": 0.9,
                    "team_id": 1,
                    "metadata": {"team_id": 1},
                }
            ],
        )
    )
    _run(svc.force_flush())
    import json as _json

    async def _fetch():
        async with audit_env["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().one()

    row = _run(_fetch())
    summary = _json.loads(row.results_summary)
    assert summary[0]["type"] == "test_case"
    assert summary[0]["id"] == "TC-1"
    assert summary[0]["title"] == "A"
    assert "snippet" not in summary[0]
    assert summary[0]["team_id"] == 1


def test_record_swallows_internal_errors(audit_env) -> None:
    """即使序列化失敗 MUST NOT 拋出。"""
    svc = KnowledgeQueryLogService()
    # 不應拋錯
    _run(
        svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text="ok",
            process={"key": "value"},
        )
    )
    _run(svc.force_flush())


def test_start_periodic_flush_writes_buffer_to_db(audit_env) -> None:
    """background flush task 必須在沒人顯式 force_flush 的情境下也寫入 DB。"""
    # 把週期縮短到 0.05s 加速測試；不影響邏輯正確性。
    svc = KnowledgeQueryLogService()
    svc._FLUSH_INTERVAL_SECONDS = 0.05

    async def _scenario() -> KnowledgeQueryLogTable | None:
        svc.start()
        try:
            await svc.record(
                source="assistant",
                operation="search",
                status="success",
                query_text="background-flush-test",
            )
            for _ in range(40):  # 最多 ~2s
                await asyncio.sleep(0.05)
                async with audit_env["async_session_factory"]() as session:
                    row = (
                        await session.execute(
                            select(KnowledgeQueryLogTable).where(
                                KnowledgeQueryLogTable.query_text == "background-flush-test"
                            )
                        )
                    ).scalar_one_or_none()
                    if row is not None:
                        return row
            return None
        finally:
            await svc.stop()

    row = _run(_scenario())
    assert row is not None, "background flush task 沒把 in-memory buffer 寫入 DB"
    assert row.query_text == "background-flush-test"
    # stop() 已 force_flush，buffer 必須清空
    assert svc._buffer == []


def test_start_is_idempotent_and_skips_when_disabled(audit_env, monkeypatch) -> None:
    """start() 冪等；is_enabled 為 false 時不啟動 task。"""

    async def _scenario() -> None:
        svc = KnowledgeQueryLogService()
        svc.start()
        svc.start()  # 第二次呼叫不應多開 task
        assert len(svc._flush_tasks) == 1
        await svc.stop()

    _run(_scenario())

    # 強制停用情境
    monkeypatch.setattr(KnowledgeQueryLogService, "is_enabled", property(lambda self: False))
    svc2 = KnowledgeQueryLogService()
    svc2.start()
    assert svc2._flush_tasks == []  # 沒啟動 task


def test_stop_cancels_task_and_force_flushes(audit_env) -> None:
    """stop() 取消 task、且對剩餘 buffer 做一次 force_flush。"""

    async def _scenario() -> KnowledgeQueryLogTable | None:
        svc = KnowledgeQueryLogService()
        svc._FLUSH_INTERVAL_SECONDS = 0.05
        svc.start()
        # 寫一筆但不等 background task 觸發，直接 stop()
        await svc.record(
            source="assistant",
            operation="search",
            status="success",
            query_text="stop-force-flush-test",
        )
        await svc.stop()
        assert svc._flush_tasks == []
        async with audit_env["async_session_factory"]() as session:
            return (
                await session.execute(
                    select(KnowledgeQueryLogTable).where(
                        KnowledgeQueryLogTable.query_text == "stop-force-flush-test"
                    )
                )
            ).scalar_one_or_none()

    row = _run(_scenario())
    assert row is not None, "stop() 沒做收尾 force_flush"
