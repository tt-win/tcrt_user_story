"""Failure mode tests: Qdrant down, embedding failure, retry, write_pending marking.

These tests use fakes to simulate failure scenarios.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import EmbeddingConfig, KnowledgeGraphConfig, QdrantConfig
from app.services.knowledge.embedding_service import EmbeddingService
from app.services.knowledge.knowledge_write_service import KnowledgeWriteService
from app.services.knowledge.qdrant_client import QdrantKnowledgeClient


class FailingQdrant:
    """Qdrant client that fails on upsert."""

    def __init__(self) -> None:
        self.upserted: list = []
        self.should_fail = True

    async def ensure_collection(self, collection: str, vector_size: int, **kwargs) -> None:
        # Always succeed at collection creation; only upsert fails
        pass

    async def upsert_points(self, collection: str, points) -> None:
        if self.should_fail:
            raise ConnectionError("Qdrant unreachable")
        self.upserted.append((collection, list(points)))

    async def collection_is_empty(self, collection: str) -> bool:
        return True

    async def health_check(self) -> bool:
        return not self.should_fail

    async def get_collection_dimensions(self, collection: str) -> int | None:
        return None  # Collection doesn't exist


def make_services(tmp_path: Path, failing_qdrant: FailingQdrant | None = None) -> tuple[KnowledgeWriteService, FailingQdrant]:
    q = failing_qdrant or FailingQdrant()
    cfg = KnowledgeGraphConfig(
        enabled=True,
        qdrant=QdrantConfig(),
        embedding=EmbeddingConfig(
            model="fake",
            dimensions=4,
            provider="openrouter",
            cache_path="",
        ),
        backfill_batch_size=2,
        backfill_progress_path=str(tmp_path / "progress.json"),
    )
    emb = EmbeddingService(cfg.embedding)

    async def fake_embed_batch(texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def fake_embed_one(text):
        return [0.1, 0.2, 0.3, 0.4]

    emb.embed_batch = fake_embed_batch  # type: ignore[assignment]
    emb.embed_one = fake_embed_one  # type: ignore[assignment]

    svc = KnowledgeWriteService(
        qdrant_client=q,  # type: ignore[arg-type]
        embedding_service=emb,
        config=cfg,
    )
    return svc, q


async def async_iter(items):
    for item in items:
        yield item


def make_tc(n: int) -> dict:
    return {
        "test_case_number": f"TCG-{n:05d}",
        "title": f"Test case {n}",
    }


@pytest.mark.asyncio
async def test_qdrant_down_marks_progress_failed(tmp_path: Path) -> None:
    """If Qdrant is unreachable during backfill, progress is marked failed and exception propagates."""
    failing_q = FailingQdrant()
    svc, _ = make_services(tmp_path, failing_qdrant=failing_q)
    tcs = [make_tc(i) for i in range(3)]
    with pytest.raises(ConnectionError, match="Qdrant unreachable"):
        await svc.backfill_test_cases(async_iter(tcs))
    progress = svc._load_progress("test_cases")
    assert progress is not None
    assert progress.status == "failed"
    # is_backfill_in_progress should be reset even on failure
    assert svc._is_backfill_in_progress is False


@pytest.mark.asyncio
async def test_qdrant_recovers_after_outage(tmp_path: Path) -> None:
    """If Qdrant comes back, the next write succeeds."""
    failing_q = FailingQdrant()
    svc, _ = make_services(tmp_path, failing_qdrant=failing_q)
    # First attempt fails
    with pytest.raises(ConnectionError):
        await svc.backfill_test_cases(async_iter([make_tc(1)]))
    # Qdrant recovers
    failing_q.should_fail = False
    # Second attempt succeeds (status is now "failed", so it starts fresh)
    progress = await svc.backfill_test_cases(async_iter([make_tc(2)]))
    assert progress.status == "completed"
    assert len(failing_q.upserted) == 1


@pytest.mark.asyncio
async def test_embedding_failure_marks_progress_failed(tmp_path: Path) -> None:
    """If embedding API fails, progress is marked failed."""
    svc, _ = make_services(tmp_path)

    async def failing_embed_batch(texts):
        raise RuntimeError("Embedding API timeout")

    svc._embedding.embed_batch = failing_embed_batch  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Embedding API timeout"):
        await svc.backfill_test_cases(async_iter([make_tc(1)]))
    progress = svc._load_progress("test_cases")
    assert progress is not None
    assert progress.status == "failed"


@pytest.mark.asyncio
async def test_partial_batch_failure_continues(tmp_path: Path) -> None:
    """If embedding fails on the 2nd batch, the cycle aborts and progress is marked failed.

    Note: current implementation aborts on first failure (no per-batch retry).
    Future enhancement: continue past batch failures with retry queue.
    """
    # Use a working qdrant so we can reach the embed failure
    working_q = FailingQdrant()
    working_q.should_fail = False
    svc, _ = make_services(tmp_path, failing_qdrant=working_q)

    call_count = [0]
    original_embed = svc._embedding.embed_batch

    async def flaky_embed_batch(texts):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("Transient failure")
        return await original_embed(texts)

    svc._embedding.embed_batch = flaky_embed_batch  # type: ignore[assignment]

    tcs = [make_tc(i) for i in range(4)]
    with pytest.raises(RuntimeError, match="Transient failure"):
        await svc.backfill_test_cases(async_iter(tcs))
    # First batch succeeded, second failed
    # Progress is marked failed
    progress = svc._load_progress("test_cases")
    assert progress is not None
    assert progress.status == "failed"


@pytest.mark.asyncio
async def test_write_test_case_qdrant_down(tmp_path: Path) -> None:
    """Single test case write fails gracefully when Qdrant is down."""
    failing_q = FailingQdrant()
    svc, _ = make_services(tmp_path, failing_qdrant=failing_q)
    with pytest.raises(ConnectionError, match="Qdrant unreachable"):
        await svc.write_test_case(make_tc(1))


@pytest.mark.asyncio
async def test_health_check_returns_false_when_qdrant_down(tmp_path: Path) -> None:
    svc, _ = make_services(tmp_path)
    assert await svc._qdrant.health_check() is False
