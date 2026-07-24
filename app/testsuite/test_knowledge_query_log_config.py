"""Unit tests for knowledge query log config flags."""

from __future__ import annotations

import pytest

from app.config import AuditConfig, Settings


def test_audit_config_knowledge_query_log_defaults() -> None:
    c = AuditConfig()
    assert c.knowledge_query_log_enabled is True
    assert c.knowledge_query_log_retention_days == 30
    assert c.knowledge_query_log_max_size_chars == 16384
    assert c.knowledge_query_log_batch_size == 50


def test_audit_config_knowledge_query_log_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_ENABLED", "false")
    c = AuditConfig.from_env()
    assert c.knowledge_query_log_enabled is False


def test_audit_config_knowledge_query_log_retention_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNOWLEDGE_QUERY_LOG_RETENTION_DAYS", "7")
    c = AuditConfig.from_env()
    assert c.knowledge_query_log_retention_days == 7


def test_settings_exposes_knowledge_query_log_config() -> None:
    s = Settings()
    assert hasattr(s, "audit")
    assert s.audit.knowledge_query_log_enabled is True
    assert s.audit.knowledge_query_log_retention_days == 30
