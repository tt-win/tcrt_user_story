"""Unified Knowledge Retrieval & RAG Service Layer (v6.0 Approved Architecture).

Provides team-isolated, fault-tolerant RAG retrieval for AI Assistant and QA AI Helper.
Features:
- Concurrency limiting via asyncio.Semaphore(20) & Circuit Breaker.
- Team isolation via Qdrant search-time Payload Filters & Cypher parameters.
- 2.5s Async Timeout with graceful 0-shot fallback.
- Database-level payload projection & generator-based safe markdown truncation.
- 知識圖譜 / RAG 查詢觀測性記錄（openspec: log-knowledge-graph-queries）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Generator, Iterable, Optional

from app.services.knowledge import get_hybrid_search, is_knowledge_graph_enabled
from app.services.knowledge.hybrid_search_service import KnowledgeSearchResult
from app.audit.database import (
    KnowledgeQueryOperation,
    KnowledgeQuerySource,
    KnowledgeQueryStatus,
)

LOGGER = logging.getLogger(__name__)


def _status_to_enum(status: Any) -> Any:
    """將字串狀態映射為 KnowledgeQueryStatus 列舉。"""
    if isinstance(status, KnowledgeQueryStatus):
        return status
    if isinstance(status, str):
        s = status.lower()
        if s == "success":
            return KnowledgeQueryStatus.SUCCESS
        if s == "degraded":
            return KnowledgeQueryStatus.DEGRADED
    return KnowledgeQueryStatus.DEGRADED

# Global concurrency semaphore & circuit breaker state
_RAG_SEMAPHORE = asyncio.Semaphore(20)
_CONSECUTIVE_FAILURES = 0
_CIRCUIT_BREAKER_TRIPPED_UNTIL = 0.0
_CIRCUIT_BREAKER_COOL_DOWN = 30.0  # seconds

# Outer budget for embedding + multi-collection Qdrant + light graph expansion.
_SEARCH_TIMEOUT_SECONDS = 2.5


def safe_truncate_text(text: str, max_tokens: int = 300) -> str:
    """Safely truncate text to max_tokens and close unclosed Markdown code blocks."""
    if not text:
        return ""

    # Simple heuristic: 1 token ~ 3.5 chars
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    # Check for unclosed code block (```)
    code_block_count = truncated.count("```")
    suffix = "\n... [Truncated]"
    if code_block_count % 2 != 0:
        suffix = "\n```\n... [Truncated]"

    return truncated + suffix


def _is_circuit_open() -> bool:
    """Return True if circuit breaker is currently tripped (open)."""
    global _CIRCUIT_BREAKER_TRIPPED_UNTIL
    if _CIRCUIT_BREAKER_TRIPPED_UNTIL > 0:
        if time.time() < _CIRCUIT_BREAKER_TRIPPED_UNTIL:
            return True
        # Cool down expired, reset
        _CIRCUIT_BREAKER_TRIPPED_UNTIL = 0.0
    return False


def _record_success() -> None:
    """Record successful call and reset failure counter."""
    global _CONSECUTIVE_FAILURES
    _CONSECUTIVE_FAILURES = 0


def _record_failure() -> None:
    """Record failure and trip circuit breaker if threshold reached."""
    global _CONSECUTIVE_FAILURES, _CIRCUIT_BREAKER_TRIPPED_UNTIL
    _CONSECUTIVE_FAILURES += 1
    if _CONSECUTIVE_FAILURES >= 3:
        LOGGER.warning("Knowledge RAG Circuit Breaker tripped for 30s due to 3 consecutive failures")
        _CIRCUIT_BREAKER_TRIPPED_UNTIL = time.time() + _CIRCUIT_BREAKER_COOL_DOWN


def _build_search_options(
    *,
    top_k: int,
    score_threshold: float,
    primary_team_id: int | None,
    allowed_team_ids: list[int] | None,
    collections: list[str] | None,
    team_id: int | None = None,
) -> dict[str, Any]:
    """Build hybrid_search options without passing nulls that break Pydantic defaults."""
    options: dict[str, Any] = {
        "top_k": top_k,
        "score_threshold": score_threshold,
    }
    if primary_team_id is not None:
        options["primary_team_id"] = primary_team_id
    if team_id is not None:
        options["team_id"] = team_id
    if allowed_team_ids is not None:
        options["allowed_team_ids"] = allowed_team_ids
    if collections:
        options["collections"] = collections
    return options


class KnowledgeRetrievalService:
    """Unified team-isolated RAG retrieval service."""

    def __init__(self) -> None:
        pass

    async def search_knowledge(
        self,
        query: str,
        team_id: int | None = None,
        allowed_team_ids: list[int] | None = None,
        primary_team_id: int | None = None,
        collections: list[str] | None = None,
        top_k: int = 10,
        score_threshold: float = 0.55,
        *,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Perform authorized hybrid knowledge search across Qdrant & Neo4j with Dual-Route Retrieval.

        Returns degraded response on timeout/failure without throwing exceptions.
        Callers (assistant) MUST treat status=degraded as a signal to fall back to SQL tools.

        ``context`` 為觀測性上下文（openspec: log-knowledge-graph-queries）：
        - ``source``：KnowledgeQuerySource（預設 ``assistant``）
        - ``user_id`` / ``username``：發起者
        - ``conversation_id`` / ``turn_key``：對話／回合識別
        - ``llm_tool_call_id``：助手工具呼叫 id（用於交叉索引既有 journal）
        """
        # ---- diagnostics collected across the whole method body ----
        diag: dict[str, Any] = {
            "dual_route": False,
            "primary_results": 0,
            "cross_results": 0,
            "graph_expanded": False,
            "graph_timed_out": False,
            "circuit_breaker_open": False,
            "concurrent_capacity_exhausted": False,
            "degrade_reason": None,
        }
        started = time.time()
        result: dict[str, Any] = {}  # filled by each return path; fallback default
        clean_query = (query or "").strip()
        try:
            if not is_knowledge_graph_enabled():
                diag["degrade_reason"] = "kg_disabled"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Knowledge graph service is not enabled.",
                    "fallback_recommended": True,
                }
                return result

            if _is_circuit_open():
                diag["circuit_breaker_open"] = True
                diag["degrade_reason"] = "circuit_open"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Knowledge RAG circuit breaker is open (service busy or recovering).",
                    "fallback_recommended": True,
                }
                return result

            if _RAG_SEMAPHORE.locked():
                LOGGER.warning("RAG concurrency limit reached (20 requests in progress); failing fast")
                diag["concurrent_capacity_exhausted"] = True
                diag["degrade_reason"] = "concurrent_capacity_exhausted"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Knowledge RAG service is currently experiencing high load.",
                    "fallback_recommended": True,
                }
                return result

            if not clean_query:
                diag["degrade_reason"] = "empty_query"
                result = {"status": "success", "results": [], "fallback_recommended": False}
                return result

            # Resolve primary and allowed teams
            effective_primary = primary_team_id if primary_team_id is not None else team_id
            safe_primary_id = int(effective_primary) if effective_primary is not None else None

            safe_allowed_ids: list[int] | None = None
            if allowed_team_ids is not None:
                safe_allowed_ids = [int(t) for t in allowed_team_ids if t is not None]
                # Explicit empty authorized set → no cross-team / no scan
                if not safe_allowed_ids:
                    diag["degrade_reason"] = "no_authorized_teams"
                    result = {
                        "status": "success",
                        "results": [],
                        "message": "No accessible teams for knowledge search.",
                        "fallback_recommended": False,
                    }
                    return result

            try:
                async with _RAG_SEMAPHORE:
                    hybrid_svc = get_hybrid_search()

                    # Dual-Route Retrieval: Route 1 (Primary Team) + Route 2 (Authorized Cross-Team)
                    if safe_primary_id is not None and safe_allowed_ids is not None:
                        diag["dual_route"] = True
                        cross_team_ids = [t for t in safe_allowed_ids if t != safe_primary_id]

                        task_primary = hybrid_svc.hybrid_search(
                            query=clean_query,
                            options=_build_search_options(
                                top_k=max(3, top_k // 2),
                                score_threshold=score_threshold,
                                primary_team_id=safe_primary_id,
                                allowed_team_ids=[safe_primary_id],
                                collections=collections,
                            ),
                        )
                        task_cross = (
                            hybrid_svc.hybrid_search(
                                query=clean_query,
                                options=_build_search_options(
                                    top_k=max(3, top_k // 2),
                                    score_threshold=score_threshold,
                                    primary_team_id=None,
                                    allowed_team_ids=cross_team_ids,
                                    collections=collections,
                                ),
                            )
                            if cross_team_ids
                            else asyncio.sleep(0, result=[])
                        )

                        res_primary, res_cross = await asyncio.wait_for(
                            asyncio.gather(task_primary, task_cross),
                            timeout=_SEARCH_TIMEOUT_SECONDS,
                        )
                        # Merge & deduplicate (primary first for stable ranking preference)
                        seen: set[tuple[str, str]] = set()
                        merged_results: list[KnowledgeSearchResult] = []
                        for r in list(res_primary) + list(res_cross):
                            key = (r.entity_type, r.entity_id)
                            if key not in seen:
                                seen.add(key)
                                merged_results.append(r)
                        results = merged_results[:top_k]
                        diag["primary_results"] = len(res_primary)
                        diag["cross_results"] = len(res_cross)
                    else:
                        # Global / single-scope path: one hybrid call with full allowed set
                        results = await asyncio.wait_for(
                            hybrid_svc.hybrid_search(
                                query=clean_query,
                                options=_build_search_options(
                                    top_k=min(top_k, 20),
                                    score_threshold=score_threshold,
                                    primary_team_id=safe_primary_id,
                                    allowed_team_ids=safe_allowed_ids,
                                    collections=collections,
                                    team_id=team_id if safe_primary_id is None else None,
                                ),
                            ),
                            timeout=_SEARCH_TIMEOUT_SECONDS,
                        )
                        diag["primary_results"] = len(results)

                    _record_success()
                    processed_results = list(self._process_results_generator(results))
                    # Empty success is a real miss (graph ok, no hits) — LLM may still try SQL
                    # keyword search, but it is not a hard degrade.
                    result = {
                        "status": "success",
                        "results": processed_results,
                        "fallback_recommended": len(processed_results) == 0,
                    }
                    return result
            except asyncio.TimeoutError:
                LOGGER.warning(
                    "Knowledge search query timed out (>%.1fs): %s",
                    _SEARCH_TIMEOUT_SECONDS,
                    clean_query,
                )
                diag["graph_timed_out"] = True
                diag["degrade_reason"] = "timeout"
                _record_failure()
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Knowledge search timed out.",
                    "fallback_recommended": True,
                }
                return result
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Knowledge search failed: %s", exc, exc_info=True)
                diag["degrade_reason"] = f"exception:{type(exc).__name__}"
                _record_failure()
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": f"Knowledge search unavailable: {exc}",
                    "fallback_recommended": True,
                }
                return result
        finally:
            # 觀測性記錄：恰一筆，且在 semaphore 釋放後／斷路器 except 之外（design.md D2）。
            try:
                await self._safe_record_search(
                    context=context,
                    query_text=clean_query,
                    team_id=team_id,
                    primary_team_id=primary_team_id if primary_team_id is not None else team_id,
                    allowed_team_ids=allowed_team_ids,
                    top_k=top_k,
                    score_threshold=score_threshold,
                    result=result,
                    diag=diag,
                    duration_ms=int((time.time() - started) * 1000),
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("search_knowledge: 觀測性記錄失敗（已吞）：%s", exc, exc_info=True)

    async def analyze_impact(
        self,
        entity_type: str,
        entity_id: str,
        team_id: int | None = None,
        depth: int = 2,
        *,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Perform team-scoped impact analysis via graph traversal.

        ``context`` 為觀測性上下文（同 search_knowledge）。"""
        diag: dict[str, Any] = {
            "dual_route": False,
            "graph_expanded": True,
            "graph_timed_out": False,
            "degrade_reason": None,
        }
        started = time.time()
        result: dict[str, Any] = {}
        safe_entity_id = str(entity_id).strip()
        try:
            if not is_knowledge_graph_enabled():
                diag["degrade_reason"] = "kg_disabled"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Knowledge graph service is not enabled.",
                    "fallback_recommended": True,
                }
                return result

            safe_team_id = int(team_id) if team_id is not None else None

            try:
                results = await asyncio.wait_for(
                    get_hybrid_search().impact_analysis(
                        entity_type=entity_type,
                        entity_id=safe_entity_id,
                        depth=depth,
                    ),
                    timeout=_SEARCH_TIMEOUT_SECONDS,
                )
                # Filter results by team_id if team_id is specified
                filtered_results = []
                for item in results:
                    if safe_team_id is not None and "team_id" in item.get("metadata", {}):
                        if item["metadata"]["team_id"] != safe_team_id:
                            continue
                    filtered_results.append(item)

                result = {
                    "status": "success",
                    "results": filtered_results,
                    "fallback_recommended": False,
                }
                return result
            except asyncio.TimeoutError:
                diag["graph_timed_out"] = True
                diag["degrade_reason"] = "timeout"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": "Impact analysis timed out.",
                    "fallback_recommended": True,
                }
                return result
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Impact analysis failed for %s/%s: %s", entity_type, entity_id, exc)
                diag["degrade_reason"] = f"exception:{type(exc).__name__}"
                result = {
                    "status": "degraded",
                    "results": [],
                    "message": f"Impact analysis unavailable: {exc}",
                    "fallback_recommended": True,
                }
                return result
        finally:
            try:
                await self._safe_record_impact(
                    context=context,
                    entity_type=entity_type,
                    entity_id=safe_entity_id,
                    team_id=team_id,
                    result=result,
                    diag=diag,
                    duration_ms=int((time.time() - started) * 1000),
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("analyze_impact: 觀測性記錄失敗（已吞）：%s", exc, exc_info=True)

    async def _safe_record_search(
        self,
        *,
        context: Optional[dict[str, Any]],
        query_text: str,
        team_id: Optional[int],
        primary_team_id: Optional[int],
        allowed_team_ids: Optional[list[int]],
        top_k: int,
        score_threshold: float,
        result: dict[str, Any],
        diag: dict[str, Any],
        duration_ms: int,
    ) -> None:
        from app.services.knowledge import get_query_log_service
        from app.audit.database import KnowledgeQuerySource

        ctx = context or {}
        source = ctx.get("source") or KnowledgeQuerySource.ASSISTANT
        try:
            processed = result.get("results") or []
            await get_query_log_service().record(
                source=source,
                operation=KnowledgeQueryOperation.SEARCH,
                status=_status_to_enum(result.get("status")),
                query_text=query_text,
                user_id=ctx.get("user_id"),
                username=ctx.get("username"),
                conversation_id=ctx.get("conversation_id"),
                turn_key=ctx.get("turn_key"),
                llm_tool_call_id=ctx.get("llm_tool_call_id"),
                primary_team_id=primary_team_id,
                allowed_team_ids=list(allowed_team_ids) if allowed_team_ids else None,
                top_k=top_k,
                score_threshold=score_threshold,
                fallback_recommended=result.get("fallback_recommended"),
                degrade_reason=diag.get("degrade_reason"),
                duration_ms=duration_ms,
                result_count=len(processed) if isinstance(processed, list) else None,
                process=diag,
                results_summary=processed if isinstance(processed, list) else None,
                error=result.get("message") if result.get("status") == "degraded" else None,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("search_knowledge record: %s", exc, exc_info=True)

    async def _safe_record_impact(
        self,
        *,
        context: Optional[dict[str, Any]],
        entity_type: str,
        entity_id: str,
        team_id: Optional[int],
        result: dict[str, Any],
        diag: dict[str, Any],
        duration_ms: int,
    ) -> None:
        from app.services.knowledge import get_query_log_service
        from app.audit.database import KnowledgeQuerySource

        ctx = context or {}
        source = ctx.get("source") or KnowledgeQuerySource.ASSISTANT
        try:
            processed = result.get("results") or []
            await get_query_log_service().record(
                source=source,
                operation=KnowledgeQueryOperation.IMPACT,
                status=_status_to_enum(result.get("status")),
                query_text=f"{entity_type}:{entity_id}",
                user_id=ctx.get("user_id"),
                username=ctx.get("username"),
                conversation_id=ctx.get("conversation_id"),
                turn_key=ctx.get("turn_key"),
                llm_tool_call_id=ctx.get("llm_tool_call_id"),
                primary_team_id=team_id,
                allowed_team_ids=None,
                top_k=None,
                score_threshold=None,
                fallback_recommended=result.get("fallback_recommended"),
                degrade_reason=diag.get("degrade_reason"),
                duration_ms=duration_ms,
                result_count=len(processed) if isinstance(processed, list) else None,
                process=diag,
                results_summary=processed if isinstance(processed, list) else None,
                error=result.get("message") if result.get("status") == "degraded" else None,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("analyze_impact record: %s", exc, exc_info=True)

    async def build_rag_context_for_qa_helper(
        self,
        jira_ticket: str | None = None,
        requirement_text: str | None = None,
        team_id: int | None = None,
        top_k: int = 5,
    ) -> str:
        """Assemble grounded prompt context for QA AI Helper generation.

        Returns a concise markdown string (<= 2000 tokens) or empty string on degradation.
        """
        query_parts = []
        if jira_ticket:
            query_parts.append(f"Jira Ticket: {jira_ticket}")
        if requirement_text:
            query_parts.append(requirement_text[:200])

        if not query_parts:
            return ""

        combined_query = " ".join(query_parts)
        res = await self.search_knowledge(
            query=combined_query,
            team_id=team_id,
            top_k=top_k,
            score_threshold=0.55,
            context={"source": KnowledgeQuerySource.QA_HELPER.value},
        )

        hits = res.get("results", [])
        if not hits:
            return ""

        context_lines = [
            "### Relevant Historical Context & Test References (Grounding)",
            "The following relevant historical test cases and USM features were retrieved from the knowledge base:",
        ]

        total_chars = 0
        max_total_chars = 7500  # ~2000 tokens limit

        for h in hits:
            title = h.get("title", "")
            snippet = h.get("snippet", "")
            source = h.get("entity_type", "reference")
            meta = h.get("metadata", {}) or {}
            t_id = meta.get("team_id", h.get("team_id", "unknown"))
            t_name = meta.get("team_name", h.get("team_name", f"Team-{t_id}"))
            line = f'<knowledge_source team_id="{t_id}" team_name="{t_name}" type="{source}" title="{title}">\n{snippet}\n</knowledge_source>'

            if total_chars + len(line) > max_total_chars:
                break
            context_lines.append(line)
            total_chars += len(line)

        return "\n".join(context_lines)

    @staticmethod
    def _process_results_generator(
        results: Iterable[KnowledgeSearchResult],
    ) -> Generator[dict[str, Any], None, None]:
        """Yield processed and safely truncated result dictionaries using Python Generator."""
        for r in results:
            item = r.model_dump()
            item["snippet"] = safe_truncate_text(item.get("snippet", ""), max_tokens=300)
            meta = item.get("metadata", {}) or {}
            t_id = meta.get("team_id", "unknown")
            t_name = meta.get("team_name", f"Team-{t_id}")
            item["team_id"] = t_id
            item["team_name"] = t_name
            item["xml_snippet"] = f'<knowledge_source team_id="{t_id}" team_name="{t_name}">\n{item["snippet"]}\n</knowledge_source>'
            yield item
