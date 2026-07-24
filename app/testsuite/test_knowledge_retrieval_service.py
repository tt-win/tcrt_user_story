"""Unit tests for KnowledgeRetrievalService and safe_truncate_text."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.knowledge.hybrid_search_service import KnowledgeSearchResult
from app.services.knowledge.retrieval_service import (
    KnowledgeRetrievalService,
    safe_truncate_text,
)


def test_safe_truncate_text_normal() -> None:
    text = "Short text"
    assert safe_truncate_text(text, max_tokens=100) == "Short text"


def test_safe_truncate_text_over_limit() -> None:
    text = "A" * 500
    truncated = safe_truncate_text(text, max_tokens=10)  # max_chars = 40
    assert len(truncated) < 500
    assert "... [Truncated]" in truncated


def test_safe_truncate_text_unclosed_code_block() -> None:
    text = "Here is some code:\n```python\ndef hello():\n    pass\n" + "x" * 500
    truncated = safe_truncate_text(text, max_tokens=10)
    assert "\n```\n... [Truncated]" in truncated


@pytest.mark.asyncio
async def test_search_knowledge_disabled() -> None:
    svc = KnowledgeRetrievalService()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=False):
        res = await svc.search_knowledge("login")
        assert res["status"] == "degraded"
        assert res["results"] == []


@pytest.mark.asyncio
async def test_search_knowledge_success() -> None:
    svc = KnowledgeRetrievalService()
    mock_result = KnowledgeSearchResult(
        entity_type="test_case",
        entity_id="TC-101",
        title="Test Login Functionality",
        snippet="User should be able to login with valid credentials.",
        score=0.88,
        metadata={"team_id": 1, "team_name": "Core"},
    )

    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.return_value = [mock_result]

    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge("login", team_id=1)
            assert res["status"] == "success"
            assert res["fallback_recommended"] is False
            assert len(res["results"]) == 1
            assert res["results"][0]["entity_id"] == "TC-101"
            assert res["results"][0]["title"] == "Test Login Functionality"
            # Must not pass collections=None into hybrid (Pydantic ValidationError)
            call_opts = mock_hybrid.hybrid_search.await_args.kwargs["options"]
            assert "collections" not in call_opts or call_opts.get("collections") is not None


@pytest.mark.asyncio
async def test_search_knowledge_global_path_no_collections_none() -> None:
    """Global assistant path: primary=None + allowed teams must not pass collections=None."""
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.return_value = []

    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge(
                "品牌推送",
                primary_team_id=None,
                allowed_team_ids=[1, 2, 3],
            )
            assert res["status"] == "success"
            assert res["fallback_recommended"] is True  # empty results
            opts = mock_hybrid.hybrid_search.await_args.kwargs["options"]
            assert "collections" not in opts
            assert opts["allowed_team_ids"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_search_knowledge_empty_allowed_teams() -> None:
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()
    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge("品牌推送", allowed_team_ids=[])
            assert res["status"] == "success"
            assert res["results"] == []
            mock_hybrid.hybrid_search.assert_not_called()


@pytest.mark.asyncio
async def test_search_knowledge_embedding_error_degrades() -> None:
    from app.services.knowledge.embedding_service import EmbeddingError

    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.side_effect = EmbeddingError("embedding down")

    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge("品牌推送", allowed_team_ids=[1])
            assert res["status"] == "degraded"
            assert res["fallback_recommended"] is True
            assert res["results"] == []


@pytest.mark.asyncio
async def test_search_knowledge_timeout_degrades() -> None:
    svc = KnowledgeRetrievalService()
    mock_hybrid = AsyncMock()

    async def slow_search(*args, **kwargs):
        await asyncio.sleep(5.0)
        return []

    mock_hybrid.hybrid_search.side_effect = slow_search

    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge("login")
            assert res["status"] == "degraded"
            assert res["fallback_recommended"] is True
            assert res["results"] == []


@pytest.mark.asyncio
async def test_build_rag_context_for_qa_helper() -> None:
    svc = KnowledgeRetrievalService()
    mock_result = KnowledgeSearchResult(
        entity_type="test_case",
        entity_id="TC-202",
        title="Payment Checkout Flow",
        snippet="Verify payment gateway processing.",
        score=0.92,
    )

    with patch.object(svc, "search_knowledge", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = {
            "status": "success",
            "results": [mock_result.model_dump()],
        }
        context = await svc.build_rag_context_for_qa_helper(
            jira_ticket="PAY-100",
            requirement_text="Checkout page",
            team_id=1,
        )
        assert "Payment Checkout Flow" in context
        assert "Historical Context" in context


@pytest.mark.asyncio
async def test_search_knowledge_dual_route() -> None:
    svc = KnowledgeRetrievalService()
    res1 = KnowledgeSearchResult(entity_type="test_case", entity_id="TC-1", title="Primary Case", score=0.9, metadata={"team_id": 1})
    res2 = KnowledgeSearchResult(entity_type="test_case", entity_id="TC-2", title="Cross Team Case", score=0.85, metadata={"team_id": 2})

    mock_hybrid = AsyncMock()
    mock_hybrid.hybrid_search.side_effect = [[res1], [res2]]

    with patch("app.services.knowledge.retrieval_service.is_knowledge_graph_enabled", return_value=True):
        with patch("app.services.knowledge.retrieval_service.get_hybrid_search", return_value=mock_hybrid):
            res = await svc.search_knowledge(
                "checkout",
                primary_team_id=1,
                allowed_team_ids=[1, 2],
            )
            assert res["status"] == "success"
            assert len(res["results"]) == 2
            assert res["results"][0]["entity_id"] == "TC-1"
            assert res["results"][1]["entity_id"] == "TC-2"
            assert "xml_snippet" in res["results"][0]

