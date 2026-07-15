"""Tests for audit retention scheduling and bounded retry buffer (harden-app-token-security)."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# `app.audit.__init__` exports the `audit_service` instance, which shadows the
# submodule of the same name on attribute access; import_module resolves the real module.
audit_service_module = importlib.import_module("app.audit.audit_service")
from app.audit import audit_service as audit_service_singleton
from app.audit.audit_service import AuditService
from app.audit.models import ActionType, AuditLogCreate, ResourceType
from app.services.scheduler import TaskScheduler


def _make_record(i: int) -> AuditLogCreate:
    return AuditLogCreate(
        user_id=1,
        username="tester",
        role="app-token",
        action_type=ActionType.READ,
        resource_type=ResourceType.SYSTEM,
        resource_id=f"res-{i}",
    )


def test_retry_buffer_is_bounded_on_flush_failure(monkeypatch):
    service = AuditService()
    service.config.max_buffer_size = 10

    # Force the DB write to fail so records are re-queued into the retry buffer.
    class _BoomManager:
        def get_session(self):
            raise RuntimeError("audit DB down")

    monkeypatch.setattr(audit_service_module, "audit_db_manager", _BoomManager())

    service._batch_buffer = [_make_record(i) for i in range(50)]
    asyncio.run(service._flush_batch())

    assert len(service._batch_buffer) == 10
    # Newest records are retained (oldest dropped).
    assert service._batch_buffer[-1].resource_id == "res-49"


def test_audit_cleanup_service_is_registered():
    scheduler = TaskScheduler()
    assert "audit_cleanup" in scheduler.service_registry
    definition = scheduler.service_registry["audit_cleanup"]
    assert asyncio.iscoroutinefunction(definition.runner)


def test_audit_cleanup_runner_invokes_cleanup(monkeypatch):
    scheduler = TaskScheduler()

    called = {}

    async def _fake_cleanup():
        called["ran"] = True
        return 7

    monkeypatch.setattr(audit_service_singleton, "cleanup_old_records", _fake_cleanup)

    result = asyncio.run(scheduler._run_audit_cleanup())
    assert called.get("ran") is True
    assert result["success"] is True
    assert result["deleted_count"] == 7
