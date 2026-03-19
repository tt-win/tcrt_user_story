from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audit.database import AuditLogTable
from app.audit.models import ActionType, AuditSeverity, ResourceType
from app.db_access.audit import get_audit_access_boundary
from app.db_access.guardrails import scan_db_access_guardrails
from app.db_access.usm import get_usm_access_boundary
from app.models.user_story_map_db import UserStoryMapDB
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_audit_database_overrides,
    install_usm_database_overrides,
)


def test_install_audit_database_overrides_supports_boundary_reads(
    tmp_path,
    monkeypatch,
):
    database_bundle = create_managed_test_database(
        tmp_path / "guardrail_audit.db",
        target_name="audit",
    )
    try:
        with database_bundle["sync_session_factory"]() as session:
            session.add(
                AuditLogTable(
                    user_id=1,
                    username="guardrail-admin",
                    role="SUPER_ADMIN",
                    action_type=ActionType.CREATE,
                    resource_type=ResourceType.TEST_CASE,
                    resource_id="TC-1",
                    team_id=1,
                    details="{}",
                    action_brief="seed",
                    severity=AuditSeverity.INFO,
                )
            )
            session.commit()

        install_audit_database_overrides(
            monkeypatch=monkeypatch,
            async_session_factory=database_bundle["async_session_factory"],
        )
        boundary = get_audit_access_boundary()

        async def _count_logs(session):
            result = await session.execute(select(func.count(AuditLogTable.id)))
            return int(result.scalar() or 0)

        assert asyncio.run(boundary.run_read(_count_logs)) == 1
    finally:
        dispose_managed_test_database(database_bundle)


def test_install_usm_database_overrides_supports_boundary_reads(
    tmp_path,
    monkeypatch,
):
    database_bundle = create_managed_test_database(
        tmp_path / "guardrail_usm.db",
        target_name="usm",
    )
    try:
        with database_bundle["sync_session_factory"]() as session:
            session.add(
                UserStoryMapDB(
                    team_id=1,
                    name="Guardrail Map",
                    description="",
                    nodes=[],
                    edges=[],
                )
            )
            session.commit()

        install_usm_database_overrides(
            monkeypatch=monkeypatch,
            async_engine=database_bundle["async_engine"],
            async_session_factory=database_bundle["async_session_factory"],
        )
        boundary = get_usm_access_boundary()

        async def _count_maps(session):
            result = await session.execute(select(func.count(UserStoryMapDB.id)))
            return int(result.scalar() or 0)

        assert asyncio.run(boundary.run_read(_count_maps)) == 1
    finally:
        dispose_managed_test_database(database_bundle)


def test_db_access_guardrails_have_no_unexpected_violations():
    violations = scan_db_access_guardrails(PROJECT_ROOT)

    assert violations == []
