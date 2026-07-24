"""Tests for KnowledgeRetrievalService in-method query logging
(openspec: log-knowledge-graph-queries)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.audit.database import (
    KnowledgeQueryLogTable,
    KnowledgeQuerySource,
    KnowledgeQueryOperation,
    KnowledgeQueryStatus,
)
from app.services.knowledge import get_query_log_service
from app.services.knowledge.hybrid_search_service import KnowledgeSearchResult
from app.services.knowledge.retrieval_service import (
    KnowledgeRetrievalService,
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


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def audit_env(monkeypatch, tmp_path):
    from app.services.knowledge import query_log_service as svc_mod

    svc_mod.reset_query_log_service_for_test()
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_ENABLED", "true")
    bundle = _install_audit(monkeypatch, tmp_path)
    yield bundle
    dispose_managed_test_database(bundle)
    svc_mod.reset_query_log_service_for_test()


def _fetch_records(bundle) -> list:
    async def _fetch():
        async with bundle["async_session_factory"]() as session:
            return (await session.execute(select(KnowledgeQueryLogTable))).scalars().all()

    return _run(_fetch())


def _parse_process(row) -> dict:
    import json as _json

    raw = row.process
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    return _json.loads(raw)


def test_disabled_records_no_row(audit_env, monkeypatch) -> None:
    """KG 未啟用時 MUST NOT 記錄到 DB。"""
    svc = KnowledgeRetrievalService()
    # query log disabled
    qlog = get_query_log_service()
    qlog._force_disabled = True
    try:
        with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=False):
            res = _run(svc.search_knowledge("login"))
        assert res["status"] == "degraded"
    finally:
        qlog._force_disabled = False
    _run(qlog.force_flush())
    assert _fetch_records(audit_env) == []


def test_kg_disabled_records_degraded_with_reason(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=False):
        res = _run(svc.search_knowledge("login"))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].status == KnowledgeQueryStatus.DEGRADED
    assert rows[0].degrade_reason == "kg_disabled"
    assert rows[0].source == KnowledgeQuerySource.ASSISTANT


def test_circuit_open_records_degraded(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=True):
            res = _run(svc.search_knowledge("login"))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "circuit_open"
    assert _parse_process(rows[0])["circuit_breaker_open"] is True


def test_concurrent_capacity_exhausted_records_degraded(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            with patch("app.services.knowledge.retrieval_service._RAG_SEMAPHORE") as sem:
                sem.locked.return_value = True
                res = _run(svc.search_knowledge("login"))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "concurrent_capacity_exhausted"


def test_empty_query_records_success(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            res = _run(svc.search_knowledge("   "))
    assert res["status"] == "success"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "empty_query"
    assert rows[0].result_count == 0


def test_no_authorized_teams_records_success(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            res = _run(svc.search_knowledge("x", allowed_team_ids=[]))
    assert res["status"] == "success"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "no_authorized_teams"


def test_success_records_one(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    mock_result = KnowledgeSearchResult(
        entity_type="test_case",
        entity_id="TC-101",
        title="Login Test",
        snippet="x" * 100,
        score=0.9,
        metadata={"team_id": 1, "team_name": "Core"},
    )
    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.return_value = [mock_result]
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
                res = _run(
                    svc.search_knowledge(
                        "login",
                        team_id=1,
                        context={
                            "user_id": 42,
                            "username": "alice",
                            "conversation_id": "conv-1",
                            "turn_key": "turn-7",
                            "llm_tool_call_id": "tool-1",
                        },
                    )
                )
    assert res["status"] == "success"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    row = rows[0]
    assert row.status == KnowledgeQueryStatus.SUCCESS
    assert row.user_id == 42
    assert row.username == "alice"
    assert row.conversation_id == "conv-1"
    assert row.turn_key == "turn-7"
    assert row.llm_tool_call_id == "tool-1"
    assert row.result_count == 1
    assert row.operation == KnowledgeQueryOperation.SEARCH


def test_dual_route_records_once(audit_env) -> None:
    """dual-route 內部多次底層呼叫 MUST 只記錄一筆。"""
    svc = KnowledgeRetrievalService()
    res1 = KnowledgeSearchResult(entity_type="test_case", entity_id="TC-1", title="P", score=0.9, metadata={"team_id": 1})
    res2 = KnowledgeSearchResult(entity_type="test_case", entity_id="TC-2", title="C", score=0.8, metadata={"team_id": 2})
    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.side_effect = [[res1], [res2]]
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
                res = _run(
                    svc.search_knowledge("x", primary_team_id=1, allowed_team_ids=[1, 2])
                )
    assert res["status"] == "success"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    proc = _parse_process(rows[0])
    assert proc["dual_route"] is True
    assert proc["primary_results"] == 1
    assert proc["cross_results"] == 1
    # 合併去重後筆數
    assert rows[0].result_count == 2


def test_timeout_records_degraded(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()

    async def slow(*args, **kwargs):
        await asyncio.sleep(5.0)
        return []

    mock_hybrid.hybrid_search.side_effect = slow
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
                res = _run(svc.search_knowledge("login", team_id=1))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "timeout"
    # 重要：timeout MUST NOT 觸發 _record_failure（finally 在 try/except 之外）
    # 不可能直接 assert，但可驗證 process 紀錄正確
    assert _parse_process(rows[0])["graph_timed_out"] is True


def test_record_failure_does_not_propagate(audit_env) -> None:
    """記錄拋錯 MUST NOT 影響查詢結果。"""
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.return_value = [
        KnowledgeSearchResult(
            entity_type="test_case", entity_id="TC-1", title="X", snippet="y", score=0.5,
        )
    ]
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service._is_circuit_open", return_value=False):
            with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
                with patch.object(
                    get_query_log_service(), "record", side_effect=RuntimeError("boom")
                ):
                    res = _run(svc.search_knowledge("login", team_id=1))
    # 查詢仍正常回傳
    assert res["status"] == "success"
    assert len(res["results"]) == 1


def test_analyze_impact_success(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()
    mock_hybrid.impact_analysis.return_value = [
        {"entity_type": "test_case", "entity_id": "TC-1", "metadata": {"team_id": 1}}
    ]
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = _run(
                svc.analyze_impact("test_case", "TC-1", team_id=1, context={"user_id": 7})
            )
    assert res["status"] == "success"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].operation == KnowledgeQueryOperation.IMPACT
    assert rows[0].user_id == 7


def test_analyze_impact_kg_disabled(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=False):
        res = _run(svc.analyze_impact("test_case", "TC-1"))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "kg_disabled"


def test_analyze_impact_timeout(audit_env) -> None:
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()

    async def slow(*args, **kwargs):
        await asyncio.sleep(5.0)
        return []

    mock_hybrid.impact_analysis.side_effect = slow
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = _run(svc.analyze_impact("test_case", "TC-1"))
    assert res["status"] == "degraded"
    _run(get_query_log_service().force_flush())
    rows = _fetch_records(audit_env)
    assert len(rows) == 1
    assert rows[0].degrade_reason == "timeout"
