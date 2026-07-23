"""Unit tests for EmbeddingService SQLite cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import EmbeddingConfig
from app.services.knowledge.embedding_service import EmbeddingService


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "embedding_cache.db"


def make_service(cache_path: Path, dimensions: int = 1024) -> EmbeddingService:
    cfg = EmbeddingConfig(model="test-model", dimensions=dimensions, cache_path=str(cache_path))
    return EmbeddingService(cfg)


def test_cache_init_creates_db(cache_dir: Path) -> None:
    svc = make_service(cache_dir)
    assert cache_dir.exists()
    assert svc.get_cached("hello") is None


def test_cache_set_and_get(cache_dir: Path) -> None:
    svc = make_service(cache_dir)
    emb = [0.1] * 1024
    svc.set_cached("hello world", emb)
    result = svc.get_cached("hello world")
    assert result == emb


def test_cache_different_content_different_keys(cache_dir: Path) -> None:
    svc = make_service(cache_dir)
    svc.set_cached("hello", [0.1] * 1024)
    svc.set_cached("world", [0.2] * 1024)
    assert svc.get_cached("hello") == [0.1] * 1024
    assert svc.get_cached("world") == [0.2] * 1024
    assert svc.get_cached("missing") is None


def test_cache_key_includes_model(cache_dir: Path) -> None:
    """Changing model invalidates cache."""
    svc_a = make_service(cache_dir, dimensions=1024)
    svc_b = EmbeddingService(EmbeddingConfig(model="different-model", dimensions=1024, cache_path=str(cache_dir)))
    svc_a.set_cached("text", [0.1] * 1024)
    # svc_b has different model, should miss
    assert svc_b.get_cached("text") is None


def test_cache_key_includes_dimensions(cache_dir: Path) -> None:
    """Changing dimensions invalidates cache."""
    svc_a = make_service(cache_dir, dimensions=1024)
    svc_b = EmbeddingService(EmbeddingConfig(model="same", dimensions=768, cache_path=str(cache_dir)))
    svc_a.set_cached("text", [0.1] * 1024)
    # svc_b has different dimensions, should miss
    assert svc_b.get_cached("text") is None


def test_cache_overwrite_same_key(cache_dir: Path) -> None:
    svc = make_service(cache_dir)
    svc.set_cached("key", [0.1] * 1024)
    svc.set_cached("key", [0.5] * 1024)
    assert svc.get_cached("key") == [0.5] * 1024


def test_truncate_long_text() -> None:
    cfg = EmbeddingConfig(model="m", dimensions=4, max_tokens_per_text=10, cache_path="")
    svc = EmbeddingService(cfg)
    # 10 tokens * 4 chars = 40 chars max
    long_text = "x" * 100
    truncated = svc._truncate(long_text)
    assert len(truncated) == 40


def test_close_clears_resources(cache_dir: Path) -> None:
    svc = make_service(cache_dir)
    svc.set_cached("text", [0.1] * 1024)
    # close() should not raise
    import asyncio

    asyncio.run(svc.close())
    # cache should be cleared from memory
    assert svc._cache_conn is None
