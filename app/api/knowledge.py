"""Knowledge graph REST API (optional).

Endpoints:
  GET  /api/knowledge/search
  GET  /api/knowledge/impact/{entity_type}/{entity_id}
  POST /api/knowledge/backfill  (admin only)
  GET  /api/knowledge/health
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user, require_admin
from app.audit.database import (
    KnowledgeQueryOperation,
    KnowledgeQuerySource,
    KnowledgeQueryStatus,
)
from app.services.knowledge import (
    is_knowledge_graph_enabled,
    get_knowledge_graph_config,
    get_hybrid_search,
    get_query_log_service,
    get_write_service,
)

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


async def _require_admin_dep(_user: Any = Depends(require_admin())) -> Any:
    return _user


async def _record_api_search(
    *,
    user: Any,
    query_text: str,
    top_k: int,
    score_threshold: float | None,
    team_id: int | None,
    result_payload: dict[str, Any],
    started: float,
    error: str | None = None,
) -> None:
    """admin /api/knowledge/search 端點專用：guard 一筆記錄。"""
    try:
        results = result_payload.get("results") or []
        await get_query_log_service().record(
            source=KnowledgeQuerySource.API,
            operation=KnowledgeQueryOperation.SEARCH,
            status=(
                KnowledgeQueryStatus.SUCCESS
                if error is None
                else KnowledgeQueryStatus.DEGRADED
            ),
            query_text=query_text,
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            primary_team_id=team_id,
            top_k=top_k,
            score_threshold=score_threshold,
            result_count=len(results) if isinstance(results, list) else None,
            duration_ms=int((__import__("time").time() - started) * 1000),
            process={"endpoint": "search", "via": "api"},
            results_summary=results if isinstance(results, list) else None,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("/api/knowledge/search 觀測性記錄失敗（已吞）：%s", exc, exc_info=True)


async def _record_api_impact(
    *,
    user: Any,
    entity_type: str,
    entity_id: str,
    team_id: int | None,
    result_payload: dict[str, Any],
    started: float,
    error: str | None = None,
) -> None:
    try:
        results = result_payload.get("results") or []
        await get_query_log_service().record(
            source=KnowledgeQuerySource.API,
            operation=KnowledgeQueryOperation.IMPACT,
            status=(
                KnowledgeQueryStatus.SUCCESS
                if error is None
                else KnowledgeQueryStatus.DEGRADED
            ),
            query_text=f"{entity_type}:{entity_id}",
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
            primary_team_id=team_id,
            result_count=len(results) if isinstance(results, list) else None,
            duration_ms=int((__import__("time").time() - started) * 1000),
            process={"endpoint": "impact", "via": "api"},
            results_summary=results if isinstance(results, list) else None,
            error=error,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("/api/knowledge/impact 觀測性記錄失敗（已吞）：%s", exc, exc_info=True)


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    top_k: int = Query(20, ge=1, le=100),
    collections: str | None = Query(None, description="Comma-separated collection names"),
    team_id: int | None = Query(None),
    _user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Hybrid search across Qdrant + Neo4j."""
    import time as _time

    started = _time.time()
    if not is_knowledge_graph_enabled():
        await _record_api_search(
            user=_user,
            query_text=q,
            top_k=top_k,
            score_threshold=None,
            team_id=team_id,
            result_payload={"results": []},
            started=started,
            error="knowledge_graph_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge graph is not enabled",
        )
    colls = [c.strip() for c in collections.split(",")] if collections else None
    # Note: team_id filtering enforced inside HybridSearch via options
    search_svc = get_hybrid_search()
    try:
        results = await search_svc.hybrid_search(
            query=q,
            options={
                "top_k": top_k,
                "team_id": team_id,
                "collections": colls,
            },
        )
    except Exception as exc:  # noqa: BLE001
        await _record_api_search(
            user=_user,
            query_text=q,
            top_k=top_k,
            score_threshold=None,
            team_id=team_id,
            result_payload={"results": []},
            started=started,
            error=f"exception:{type(exc).__name__}",
        )
        raise
    payload = {"results": [r.model_dump() for r in results]}
    await _record_api_search(
        user=_user,
        query_text=q,
        top_k=top_k,
        score_threshold=None,
        team_id=team_id,
        result_payload=payload,
        started=started,
    )
    return payload


@router.get("/impact/{entity_type}/{entity_id}")
async def impact(
    entity_type: str,
    entity_id: str,
    depth: int = Query(2, ge=1, le=5),
    _user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    """Impact analysis: find affected entities via graph traversal."""
    import time as _time

    started = _time.time()
    if not is_knowledge_graph_enabled():
        await _record_api_impact(
            user=_user,
            entity_type=entity_type,
            entity_id=entity_id,
            team_id=None,
            result_payload={"results": []},
            started=started,
            error="knowledge_graph_disabled",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge graph is not enabled",
        )
    search_svc = get_hybrid_search()
    try:
        results = await search_svc.impact_analysis(
            entity_type=entity_type,
            entity_id=entity_id,
            depth=depth,
        )
    except Exception as exc:  # noqa: BLE001
        await _record_api_impact(
            user=_user,
            entity_type=entity_type,
            entity_id=entity_id,
            team_id=None,
            result_payload={"results": []},
            started=started,
            error=f"exception:{type(exc).__name__}",
        )
        raise
    payload = {"results": results}
    await _record_api_impact(
        user=_user,
        entity_type=entity_type,
        entity_id=entity_id,
        team_id=None,
        result_payload=payload,
        started=started,
    )
    return payload


@router.post("/backfill", deprecated=True)
async def backfill(
    entity: str = Query("all", pattern="^(test_cases|usm_nodes|all)$"),
    _admin: Any = Depends(_require_admin_dep),
) -> dict[str, Any]:
    """Trigger initial bulk load (admin only) — DEPRECATED.

    This endpoint used to be a placeholder that returned ``"queued"`` without
    actually running the backfill, which is misleading.  It is kept only to
    return an explicit error so that any old client / script using it sees
    the deprecation rather than a silent no-op.

    The actual backfill must be started via the CLI:

        uv run python -m app.services.knowledge backfill --entity <type>

    See ``app/services/knowledge/data_sources.py`` for the data source
    implementation.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /api/knowledge/backfill is deprecated and disabled. "
            "Run backfill via the CLI: "
            "uv run python -m app.services.knowledge backfill --entity <test_cases|usm_nodes|all>"
        ),
    )


@router.get("/backfill/progress")
async def backfill_progress(
    entity: str = Query(..., pattern="^(test_cases|usm_nodes)$"),
    _admin: Any = Depends(_require_admin_dep),
) -> dict[str, Any]:
    """Get current backfill progress."""
    write_svc = get_write_service()
    progress = write_svc._load_progress(entity)
    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No backfill progress for {entity}",
        )
    return {
        "entity_type": progress.entity_type,
        "processed_count": progress.processed_count,
        "total_count": progress.total_count,
        "last_processed_id": progress.last_processed_id,
        "status": progress.status,
        "started_at": progress.started_at,
        "updated_at": progress.updated_at,
    }


@router.get("/health")
async def health(
    _admin: Any = Depends(_require_admin_dep),
) -> dict[str, Any]:
    """Knowledge graph health check (admin only).

    Returns overall status plus per-component health and the Qdrant / Neo4j
    connection details, plus the current backfill progress for both entity
    types so the Super Admin tab can render a single GET.

    Opt-in contract: when the feature is disabled via
    ``KNOWLEDGE_GRAPH_ENABLED=false`` (or any other gate in
    ``is_knowledge_graph_enabled``), this endpoint MUST NOT attempt any
    outbound connection to Qdrant / Neo4j. It returns ``enabled=false`` with
    placeholder component statuses.
    """
    enabled = is_knowledge_graph_enabled()
    kg_config = get_knowledge_graph_config()
    response: dict[str, Any] = {
        "status": "disabled" if not enabled else "unknown",
        "enabled": enabled,
        "generated_at": _now_iso(),
        "components": {
            "qdrant": {
                "status": "disabled" if not enabled else "unknown",
                "url": kg_config.qdrant.url,
                "collections": [],
                "configured_collections": {
                    "test_cases": kg_config.qdrant.collection_test_cases,
                    "usm_nodes": kg_config.qdrant.collection_usm_nodes,
                },
            },
            "neo4j": {
                "status": "disabled" if not enabled else "not_configured"
                if not kg_config.neo4j.uri
                else "unknown",
                "uri": kg_config.neo4j.uri or "",
                "database": kg_config.neo4j.database,
            },
            "embedding": {
                "status": "disabled" if not enabled else "configured",
                "provider": kg_config.embedding.provider,
                "model": kg_config.embedding.model,
                "dimensions": kg_config.embedding.dimensions,
            },
        },
        "backfill": {"test_cases": None, "usm_nodes": None},
    }
    if not enabled:
        return response

    # Feature is enabled — perform actual health checks.
    import asyncio

    from app.services.knowledge import get_neo4j_client, get_qdrant_client

    qdrant = get_qdrant_client()
    neo4j = get_neo4j_client()

    async def _list_qdrant() -> list[str]:
        healthy = await qdrant.health_check()
        if not healthy:
            return []
        return await qdrant.list_collections()

    async def _check_neo4j() -> bool | None:
        if not kg_config.neo4j.uri:
            return None
        return await neo4j.health_check()

    # Run Qdrant (health + list) and Neo4j health in parallel.
    qdrant_healthy_result, qdrant_collections, neo4j_healthy = await asyncio.gather(
        qdrant.health_check(), _list_qdrant(), _check_neo4j()
    )
    qdrant_healthy = qdrant_healthy_result

    overall = "healthy"
    if not qdrant_healthy:
        overall = "unhealthy"
    elif neo4j_healthy is False:
        overall = "degraded"
    response["status"] = overall
    response["components"]["qdrant"]["status"] = (
        "healthy" if qdrant_healthy else "unhealthy"
    )
    response["components"]["qdrant"]["collections"] = qdrant_collections
    response["components"]["neo4j"]["status"] = (
        "healthy"
        if neo4j_healthy
        else "unhealthy"
        if neo4j_healthy is False
        else "not_configured"
    )

    # Backfill progress (read-only file read — safe regardless of upstream).
    write_svc = get_write_service()
    backfill_progress: dict[str, Any] = {}
    for entity in ("test_cases", "usm_nodes"):
        progress = write_svc._load_progress(entity)
        if progress is not None:
            backfill_progress[entity] = {
                "entity_type": progress.entity_type,
                "processed_count": progress.processed_count,
                "total_count": progress.total_count,
                "last_processed_id": progress.last_processed_id,
                "status": progress.status,
                "started_at": progress.started_at,
                "updated_at": progress.updated_at,
            }
        else:
            backfill_progress[entity] = None
    response["backfill"] = backfill_progress
    return response


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
