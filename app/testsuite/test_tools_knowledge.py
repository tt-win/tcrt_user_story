"""Unit tests for AI Assistant knowledge tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.assistant.tools_catalog import ALL_TOOLS
from app.services.assistant.tools_knowledge import TOOLS as KNOWLEDGE_TOOLS


def test_knowledge_tools_catalog_registration() -> None:
    tool_names = [t.name for t in ALL_TOOLS]
    assert "get_test_case_global" in tool_names
    assert "search_knowledge" in tool_names
    assert "search_test_cases_global" in tool_names
    assert "analyze_knowledge_impact" in tool_names


def test_knowledge_tools_spec() -> None:
    for tool in KNOWLEDGE_TOOLS:
        assert tool.permission.name == "READ"
        assert tool.execution_mode == "local"
        assert tool.team_check == "none"


def test_knowledge_tools_are_global_discovery() -> None:
    """Global conversations only expose discovery tools (READ + team_check=none)."""
    from app.services.assistant.tool_registry import ToolRegistry

    registry = ToolRegistry(list(ALL_TOOLS))
    discovery_names = {t.name for t in registry.discovery_only()}
    assert "get_test_case_global" in discovery_names
    assert "search_knowledge" in discovery_names
    assert "search_test_cases_global" in discovery_names


@pytest.mark.asyncio
async def test_run_local_search_knowledge_tool() -> None:
    from app.services.assistant.tool_executor import ToolExecutor

    executor = ToolExecutor(app=MagicMock(), main_boundary=MagicMock(), config=MagicMock(), registry=MagicMock())
    mock_retrieval = AsyncMock()
    mock_retrieval.search_knowledge.return_value = {
        "status": "success",
        "results": [{"title": "Sample TC"}],
    }

    tool = [t for t in KNOWLEDGE_TOOLS if t.name == "search_knowledge"][0]

    with patch("app.services.knowledge.get_retrieval_service", return_value=mock_retrieval):
        status, payload = await executor._run_local_read_tool(
            tool, {"query": "login"}, team_id=5
        )
        assert status == 200
        assert payload["status"] == "success"
        assert payload["results"] == [{"title": "Sample TC"}]
        call_kwargs = mock_retrieval.search_knowledge.call_args.kwargs
        assert call_kwargs["query"] == "login"
        assert call_kwargs["primary_team_id"] == 5
        assert call_kwargs["allowed_team_ids"] == []  # fail-closed when user_id omitted
        assert call_kwargs["context"]["source"] == "assistant"


@pytest.mark.asyncio
async def test_search_knowledge_tool_projection_keeps_fallback_flag() -> None:
    """LLM must see fallback_recommended to decide SQL fallback."""
    from app.services.assistant.projection import project_and_redact
    from app.services.assistant.tools_knowledge import TOOLS as KTOOLS

    tool = next(t for t in KTOOLS if t.name == "search_knowledge")
    raw = {
        "status": "degraded",
        "results": [],
        "message": "Knowledge search timed out.",
        "fallback_recommended": True,
        "secret": "drop-me",
    }
    projected = project_and_redact(raw, tool.projection, max_chars=4000)
    assert projected["status"] == "degraded"
    assert projected["fallback_recommended"] is True
    assert projected["message"] == "Knowledge search timed out."
    assert "secret" not in projected


@pytest.mark.asyncio
async def test_run_local_search_knowledge_resolves_allowed_teams() -> None:
    from app.services.assistant.tool_executor import ToolExecutor

    executor = ToolExecutor(app=MagicMock(), main_boundary=MagicMock(), config=MagicMock(), registry=MagicMock())
    mock_retrieval = AsyncMock()
    mock_retrieval.search_knowledge.return_value = {"status": "success", "results": []}
    tool = [t for t in KNOWLEDGE_TOOLS if t.name == "search_knowledge"][0]

    with (
        patch("app.services.knowledge.get_retrieval_service", return_value=mock_retrieval),
        patch(
            "app.services.assistant.tool_executor.permission_service.get_user_accessible_teams",
            new=AsyncMock(return_value=[1, 2, 3]),
        ),
    ):
        status, payload = await executor._run_local_read_tool(
            tool, {"query": "品牌推送"}, team_id=None, user_id=42
        )
        assert status == 200
        call_kwargs = mock_retrieval.search_knowledge.call_args.kwargs
        assert call_kwargs["query"] == "品牌推送"
        assert call_kwargs["primary_team_id"] is None
        assert call_kwargs["allowed_team_ids"] == [1, 2, 3]
        assert call_kwargs["context"]["user_id"] == 42
        assert call_kwargs["context"]["source"] == "assistant"


@pytest.mark.asyncio
async def test_run_local_search_test_cases_global_uses_run_read() -> None:
    """Regression: must use main_boundary.run_read (session() does not exist)."""
    from app.services.assistant.tool_executor import ToolExecutor

    row = SimpleNamespace(
        test_case_number="TC-100",
        title="品牌推送通知",
        priority=SimpleNamespace(value="P1"),
        team_id=7,
        team_name="Growth",
        test_case_set_id=11,
        set_name="Marketing",
    )
    main_boundary = MagicMock()
    main_boundary.run_read = AsyncMock(return_value=[row])

    executor = ToolExecutor(app=MagicMock(), main_boundary=main_boundary, config=MagicMock(), registry=MagicMock())
    tool = [t for t in KNOWLEDGE_TOOLS if t.name == "search_test_cases_global"][0]

    with patch(
        "app.services.assistant.tool_executor.permission_service.get_user_accessible_teams",
        new=AsyncMock(return_value=[7, 8]),
    ):
        status, payload = await executor._run_local_read_tool(
            tool, {"query": "品牌推送"}, team_id=None, user_id=1
        )

    assert status == 200
    assert payload["status"] == "success"
    assert payload["total"] == 1
    assert payload["results"][0]["team_name"] == "Growth"
    assert payload["results"][0]["title"] == "品牌推送通知"
    assert payload["results"][0]["set_id"] == 11
    main_boundary.run_read.assert_awaited_once()
    assert not hasattr(main_boundary, "session") or not getattr(main_boundary, "session").called


@pytest.mark.asyncio
async def test_run_local_search_test_cases_global_empty_access_fail_closed() -> None:
    from app.services.assistant.tool_executor import ToolExecutor

    main_boundary = MagicMock()
    main_boundary.run_read = AsyncMock()
    executor = ToolExecutor(app=MagicMock(), main_boundary=main_boundary, config=MagicMock(), registry=MagicMock())
    tool = [t for t in KNOWLEDGE_TOOLS if t.name == "search_test_cases_global"][0]

    with patch(
        "app.services.assistant.tool_executor.permission_service.get_user_accessible_teams",
        new=AsyncMock(return_value=[]),
    ):
        status, payload = await executor._run_local_read_tool(
            tool, {"query": "品牌推送"}, user_id=1
        )

    assert status == 200
    assert payload == {"status": "success", "results": [], "total": 0}
    main_boundary.run_read.assert_not_called()


@pytest.mark.asyncio
async def test_search_knowledge_fail_closed_without_user_id() -> None:
    """Red-team: missing user_id must not unscoped-scan all teams."""
    from app.services.assistant.tool_executor import ToolExecutor

    mock_retrieval = AsyncMock()
    mock_retrieval.search_knowledge.return_value = {
        "status": "success",
        "results": [],
        "fallback_recommended": False,
    }
    executor = ToolExecutor(app=MagicMock(), main_boundary=MagicMock(), config=MagicMock(), registry=MagicMock())
    tool = [t for t in KNOWLEDGE_TOOLS if t.name == "search_knowledge"][0]
    with patch("app.services.knowledge.get_retrieval_service", return_value=mock_retrieval):
        await executor._run_local_read_tool(tool, {"query": "品牌推送"}, team_id=None, user_id=None)
    call_kwargs = mock_retrieval.search_knowledge.call_args.kwargs
    assert call_kwargs["query"] == "品牌推送"
    assert call_kwargs["primary_team_id"] is None
    assert call_kwargs["allowed_team_ids"] == []


def test_knowledge_envelope_soft_truncate_keeps_fallback_flag() -> None:
    from app.services.assistant.projection import project_and_redact
    from app.services.assistant.tools_knowledge import TOOLS as KTOOLS

    tool = next(t for t in KTOOLS if t.name == "search_knowledge")
    fat = {
        "status": "success",
        "fallback_recommended": False,
        "results": [
            {
                "entity_type": "test_case",
                "entity_id": f"TC-{i}",
                "title": "x" * 200,
                "snippet": "y" * 200,
                "team_id": 1,
                "team_name": "PAD",
                "score": 0.9,
            }
            for i in range(40)
        ],
    }
    projected = project_and_redact(fat, tool.projection, max_chars=800)
    assert projected.get("status") == "success"
    assert "fallback_recommended" in projected
    assert projected.get("truncated") is True
    assert len(projected.get("results") or []) < 40


def test_ensure_tool_routing_rules_injects_soft_routing() -> None:
    from app.services.assistant.content_store import ensure_tool_routing_rules, assemble_system_prompt_text

    stale = "You are the TCRT assistant.\n\n{{SKILL_CATALOG}}\n"
    fixed = ensure_tool_routing_rules(stale)
    assert "get_test_case_global" in fixed
    assert "search_knowledge" in fixed
    assert "simplest tool" in fixed
    # Must NOT re-introduce forced knowledge-first only path
    assert "must call `search_knowledge` first" not in fixed
    assembled = assemble_system_prompt_text(stale, "| skill | desc |")
    assert "get_test_case_global" in assembled
    assert "skill" in assembled


@pytest.mark.asyncio
async def test_run_local_get_test_case_global() -> None:
    """Simple number lookup returns full steps without knowledge graph."""
    from types import SimpleNamespace

    from app.services.assistant.tool_executor import ToolExecutor

    row = SimpleNamespace(
        id=99,
        test_case_number="TCG-134380.010.010",
        title="頁面加載完成",
        priority=SimpleNamespace(value="Medium"),
        precondition="已登入",
        steps="1. 開啟頁面\n2. 等待 loading",
        expected_result="頁面顯示完成",
        team_id=5,
        test_case_set_id=10,
        set_name="TP-4674 品牌推送服務",
        team_name="PAD",
        section_name="",
    )
    main_boundary = MagicMock()
    main_boundary.run_read = AsyncMock(return_value=row)
    executor = ToolExecutor(app=MagicMock(), main_boundary=main_boundary, config=MagicMock(), registry=MagicMock())
    tool = next(t for t in KNOWLEDGE_TOOLS if t.name == "get_test_case_global")

    with patch(
        "app.services.assistant.tool_executor.permission_service.get_user_accessible_teams",
        new=AsyncMock(return_value=[5]),
    ):
        status, payload = await executor._run_local_read_tool(
            tool, {"test_case_number": "TCG-134380.010.010"}, user_id=1
        )

    assert status == 200
    assert payload["found"] is True
    assert payload["steps"] == "1. 開啟頁面\n2. 等待 loading"
    assert payload["expected_result"] == "頁面顯示完成"
    assert payload["team_name"] == "PAD"
    main_boundary.run_read.assert_awaited_once()
