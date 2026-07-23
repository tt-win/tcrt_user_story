"""Unit tests for knowledge graph config."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from app.config import (
    EmbeddingConfig,
    KnowledgeGraphConfig,
    Neo4jConfig,
    QdrantConfig,
    Settings,
)


def test_neo4j_config_defaults() -> None:
    c = Neo4jConfig()
    assert c.uri == ""
    assert c.username == "neo4j"
    assert c.password == ""
    assert c.database == "neo4j"
    assert c.max_connection_pool_size == 50
    assert c.connection_timeout == 30


def test_qdrant_config_defaults() -> None:
    c = QdrantConfig()
    assert c.url == ""
    assert c.timeout == 30
    assert c.prefer_grpc is False
    assert c.grpc_use_tls is False
    assert c.collection_jira_references == "jira_references"
    assert c.collection_test_cases == "test_cases"
    assert c.collection_usm_nodes == "usm_nodes"


def test_embedding_config_defaults() -> None:
    c = EmbeddingConfig()
    assert c.model == ""
    assert c.dimensions == 1024
    assert c.provider == "openrouter"
    assert c.api_key == ""
    assert c.batch_size == 100
    assert c.max_tokens_per_text == 8000
    assert c.cache_path == "/tmp/embedding_cache.db"


def test_knowledge_graph_config_defaults() -> None:
    c = KnowledgeGraphConfig()
    assert c.enabled is False
    assert c.sync_interval_minutes == 30
    assert c.backfill_batch_size == 100
    assert c.backfill_progress_path == "data/knowledge_backfill_progress.json"


def test_from_env_qdrant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://q.example:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    c = QdrantConfig.from_env()
    assert c.url == "http://q.example:6333"
    assert c.api_key == "secret"


def test_from_env_embedding_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "k-123")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    c = EmbeddingConfig.from_env()
    assert c.api_key == "k-123"
    assert c.model == "text-embedding-3-small"


def test_from_env_neo4j(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://n.example:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "p")
    c = Neo4jConfig.from_env()
    assert c.uri == "bolt://n.example:7687"
    assert c.password == "p"


def test_settings_includes_knowledge_graph() -> None:
    s = Settings()
    assert hasattr(s, "knowledge_graph")
    assert isinstance(s.knowledge_graph, KnowledgeGraphConfig)
    assert s.knowledge_graph.enabled is False


def test_skip_block_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When knowledge_graph.enabled=false, no placeholder expansion for that block."""
    # Make sure env doesn't have these vars
    for var in [
        "KNOWLEDGE_GRAPH_ENABLED",
        "NEO4J_PASSWORD",
        "QDRANT_API_KEY",
        "EMBEDDING_API_KEY",
    ]:
        monkeypatch.delenv(var, raising=False)

    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """
knowledge_graph:
  enabled: false
  neo4j:
    password: "${NEO4J_PASSWORD}"
  qdrant:
    api_key: "${QDRANT_API_KEY}"
  embedding:
    api_key: "${EMBEDDING_API_KEY}"
"""
    )
    # Should NOT raise even though env vars are unset
    s = Settings.from_env_and_file(str(config_yaml))
    assert s.knowledge_graph.enabled is False
    # Default empty values since YAML block was skipped
    assert s.knowledge_graph.neo4j.password == ""
    assert s.knowledge_graph.qdrant.api_key == ""
    assert s.knowledge_graph.embedding.api_key == ""


def test_graceful_degradation_missing_qdrant_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When enabled=true but QDRANT_URL is missing, no crash at config load."""
    monkeypatch.setenv("KNOWLEDGE_GRAPH_ENABLED", "true")
    monkeypatch.delenv("QDRANT_URL", raising=False)

    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("app:\n  port: 9999\n")
    # Should NOT raise at config load (the is_knowledge_graph_enabled check happens at runtime)
    s = Settings.from_env_and_file(str(config_yaml))
    assert s.knowledge_graph.enabled is True
    assert s.knowledge_graph.qdrant.url == ""


def test_from_env_and_file_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env vars override YAML file values for knowledge_graph."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """
knowledge_graph:
  enabled: true
  sync_interval_minutes: 60
"""
    )
    monkeypatch.setenv("KNOWLEDGE_SYNC_INTERVAL_MINUTES", "15")
    s = Settings.from_env_and_file(str(config_yaml))
    assert s.knowledge_graph.sync_interval_minutes == 15
