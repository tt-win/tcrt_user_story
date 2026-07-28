"""Parity tests between /api/mcp/* and /api/app/* external read surfaces.

Tier A tests (marked ``xfail(strict=True)``) lock the canonical (post-fix)
behaviour; they fail while ``app_read`` still diverges and flip to xpass once
Phase 4 consolidates both namespaces onto ``app.services.external_read``.
Tier C compares full response shapes against a two-layer divergence allow-list.
The green scope/unit tests guard the authorization model and team-scope
boundary from day one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_token import AppTokenPrincipal
from app.services.external_read import list_teams_read, lookup_test_cases_read
from app.models.database_models import (
    AdHocRun,
    AdHocRunItem,
    AdHocRunSheet,
    MCPMachineCredential,
    MCPMachineCredentialStatus,
    Team,
    TeamAppToken,
    TeamAppTokenStatus,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
    TestRunConfig,
    TestRunSet,
    TestRunSetMembership,
    User,
)
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_run_config import TestRunStatus
from app.models.test_run_set import TestRunSetStatus
from app.testsuite.db_test_helpers import (
    create_managed_test_database,
    dispose_managed_test_database,
    install_main_database_overrides,
)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    database_bundle = create_managed_test_database(tmp_path / "test_external_read_parity.db")
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    yield TestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


def _seed_parity_data(session):
    # Team A: status deliberately NULL to exercise the D1 "active" fallback.
    # The ORM Column default (TeamStatus.ACTIVE) is applied even when status=None
    # is passed explicitly, so we force NULL via raw SQL after insert.
    from sqlalchemy import text as _sa_text

    team_a = Team(
        name="Parity Team A",
        description="Alpha",
        wiki_token="secret-a",
        test_case_table_id="tbl-a",
    )
    team_b = Team(
        name="Parity Team B",
        description="Beta",
        wiki_token="secret-b",
        test_case_table_id="tbl-b",
    )
    session.add_all([team_a, team_b])
    session.commit()
    session.execute(
        _sa_text("UPDATE teams SET status = NULL WHERE id = :tid"),
        {"tid": team_a.id},
    )
    session.commit()
    session.expire_all()

    # Default set hosting the ZKEY cases.
    default_set = TestCaseSet(
        team_id=team_a.id,
        name=f"Default-{team_a.id}",
        description="Default",
        is_default=True,
    )
    session.add(default_set)
    session.commit()

    # Cases inserted in order so ids are monotonic (c1 < c2 < c3).
    c1 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-QNUM-001",
        title="ZKEY alpha",
        priority=Priority.MEDIUM,
        test_case_set_id=default_set.id,
    )
    c2 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-PLAIN-002",
        title="ZKEY beta",
        priority=Priority.MEDIUM,
        tcg_json=json.dumps(["QNUM-9"]),
        test_case_set_id=default_set.id,
    )
    c3 = TestCaseLocal(
        team_id=team_a.id,
        test_case_number="TC-PLAIN-003",
        title="unrelated gamma",
        priority=Priority.MEDIUM,
        test_case_set_id=default_set.id,
    )
    session.add_all([c1, c2, c3])
    session.commit()

    # Sections across two sets (D25 anti-xpass): build late-sort set first.
    set_late_sort = TestCaseSet(
        team_id=team_a.id,
        name="SET-LATE-SORT",
        description="",
        is_default=False,
    )
    session.add(set_late_sort)
    session.commit()
    section_late = TestCaseSection(
        test_case_set_id=set_late_sort.id,
        name="late-sort",
        description="",
        level=1,
        sort_order=1,
    )
    session.add(section_late)
    session.commit()

    set_early_sort = TestCaseSet(
        team_id=team_a.id,
        name="SET-EARLY-SORT",
        description="",
        is_default=False,
    )
    session.add(set_early_sort)
    session.commit()
    section_early = TestCaseSection(
        test_case_set_id=set_early_sort.id,
        name="early-sort",
        description="",
        level=1,
        sort_order=0,
    )
    session.add(section_early)
    session.commit()

    # Team B guard data (scope isolation; no orphan fake test).
    set_b = TestCaseSet(
        team_id=team_b.id,
        name=f"Default-{team_b.id}",
        description="Default",
        is_default=True,
    )
    session.add(set_b)
    session.commit()
    tc_b = TestCaseLocal(
        team_id=team_b.id,
        test_case_number="TC-QNUM-B01",
        title="ZKEY teamb",
        priority=Priority.MEDIUM,
        test_case_set_id=set_b.id,
    )
    session.add(tc_b)
    session.commit()

    # Test runs — D32 & D34 share ACTIVE SET; members MUST both be terminal
    # (COMPLETED). Mixing ACTIVE would keep resolve() at "active" and break D32.
    set_active = TestRunSet(
        team_id=team_a.id,
        name="ACTIVE SET",
        description="",
        status=TestRunSetStatus.ACTIVE,
    )
    session.add(set_active)
    session.commit()

    config_in_set_b = TestRunConfig(
        team_id=team_a.id,
        name="IN-SET-CFG-B",
        status=TestRunStatus.COMPLETED,
        total_test_cases=1,
        executed_cases=1,
        passed_cases=1,
        failed_cases=0,
    )
    config_in_set = TestRunConfig(
        team_id=team_a.id,
        name="IN-SET-CFG",
        status=TestRunStatus.COMPLETED,
        total_test_cases=1,
        executed_cases=1,
        passed_cases=1,
        failed_cases=0,
    )
    session.add_all([config_in_set_b, config_in_set])
    session.commit()

    session.add_all(
        [
            TestRunSetMembership(
                team_id=team_a.id,
                set_id=set_active.id,
                config_id=config_in_set_b.id,
                position=0,
            ),
            TestRunSetMembership(
                team_id=team_a.id,
                set_id=set_active.id,
                config_id=config_in_set.id,
                position=1,
            ),
        ]
    )

    set_archived = TestRunSet(
        team_id=team_a.id,
        name="ARCHIVED SET",
        description="",
        status=TestRunSetStatus.ARCHIVED,
    )
    session.add(set_archived)
    session.commit()

    config_unassigned = TestRunConfig(
        team_id=team_a.id,
        name="UNASSIGNED-CFG",
        status=TestRunStatus.COMPLETED,
        total_test_cases=2,
        executed_cases=2,
        passed_cases=2,
        failed_cases=0,
    )
    session.add(config_unassigned)
    session.commit()

    # Adhoc: Active with 2 items (1 passed, 1 pending) → counts 2/1.
    adhoc_active = AdHocRun(
        team_id=team_a.id,
        name="Adhoc Active",
        status=TestRunStatus.ACTIVE,
    )
    adhoc_archived = AdHocRun(
        team_id=team_a.id,
        name="Adhoc Archived",
        status=TestRunStatus.ARCHIVED,
    )
    session.add_all([adhoc_active, adhoc_archived])
    session.flush()

    active_sheet = AdHocRunSheet(
        adhoc_run_id=adhoc_active.id,
        name="Sheet1",
        sort_order=0,
    )
    archived_sheet = AdHocRunSheet(
        adhoc_run_id=adhoc_archived.id,
        name="Sheet1",
        sort_order=0,
    )
    session.add_all([active_sheet, archived_sheet])
    session.flush()

    session.add_all(
        [
            AdHocRunItem(
                sheet_id=active_sheet.id,
                row_index=0,
                test_case_number="ADHOC-A-001",
                title="Active case passed",
                test_result=TestResultStatus.PASSED,
            ),
            AdHocRunItem(
                sheet_id=active_sheet.id,
                row_index=1,
                test_case_number="ADHOC-A-002",
                title="Active case pending",
                test_result=None,
            ),
            AdHocRunItem(
                sheet_id=archived_sheet.id,
                row_index=0,
                test_case_number="ADHOC-B-001",
                title="Archived case failed",
                test_result=TestResultStatus.FAILED,
            ),
        ]
    )

    # Credentials.
    user = User(
        username="parity_creator",
        email="parity@example.com",
        full_name="PC",
        role="admin",
        is_active=True,
        hashed_password="dummy",
    )
    session.add(user)
    session.commit()

    from app.auth.app_token_dependencies import generate_app_token

    raw_app_token, hash_app, prefix_app = generate_app_token()
    app_token = TeamAppToken(
        name="parity-read-token",
        owner_team_id=team_a.id,
        token_hash=hash_app,
        token_prefix=prefix_app,
        status=TeamAppTokenStatus.ACTIVE,
        scopes_json=json.dumps(["test_case:read", "test_run:read"]),
        expires_at=datetime.utcnow() + timedelta(days=90),
        created_by_user_id=user.id,
    )
    session.add(app_token)

    legacy_token = "parity_legacy_read_token"
    legacy_cred = MCPMachineCredential(
        name="parity-legacy-reader",
        token_hash=_hash_token(legacy_token),
        permission="mcp_read",
        status=MCPMachineCredentialStatus.ACTIVE,
        allow_all_teams=True,
        created_by_user_id=user.id,
    )
    session.add(legacy_cred)
    session.commit()

    return {
        "team_a_id": team_a.id,
        "team_b_id": team_b.id,
        "default_set_id": default_set.id,
        "set_late_sort_id": set_late_sort.id,
        "set_early_sort_id": set_early_sort.id,
        "set_active_id": set_active.id,
        "set_archived_id": set_archived.id,
        "case_ids": [c1.id, c2.id, c3.id],
        "section_late_id": section_late.id,
        "section_early_id": section_early.id,
        "config_in_set_id": config_in_set.id,
        "config_in_set_b_id": config_in_set_b.id,
        "config_unassigned_id": config_unassigned.id,
        "adhoc_active_id": adhoc_active.id,
        "adhoc_archived_id": adhoc_archived.id,
        "app_token": raw_app_token,
        "legacy_token": legacy_token,
    }


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Parity comparison helpers (Tier C)
# ---------------------------------------------------------------------------

PAYLOAD_ALLOWED_DIVERGENCE = frozenset(
    {"summary.sets", "summary.unassigned", "summary.adhoc"}
)

_IGNORED_PATH_SUFFIXES = ("created_at", "updated_at", "last_sync_at")


def _flatten_paths(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested JSON value into ``{dotted.path: leaf_value}``."""
    paths: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.update(_flatten_paths(value, path))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            path = f"{prefix}[{index}]"
            paths.update(_flatten_paths(value, path))
    else:
        paths[prefix] = obj
    return paths


def _diff_payloads(app_data: Any, mcp_data: Any) -> list[str]:
    """Return list of divergent paths outside the allow-list."""
    app_paths = _flatten_paths(app_data)
    mcp_paths = _flatten_paths(mcp_data)

    all_keys = set(app_paths) | set(mcp_paths)
    diffs: list[str] = []
    for key in sorted(all_keys):
        if key.endswith(_IGNORED_PATH_SUFFIXES):
            continue
        if key in PAYLOAD_ALLOWED_DIVERGENCE:
            continue
        if app_paths.get(key) != mcp_paths.get(key):
            diffs.append(key)
    return diffs


# ---------------------------------------------------------------------------
# Tier A — xfail(strict=True): canonical behaviour not yet implemented
# ---------------------------------------------------------------------------


class TestTierALookup:
    """D14–D20, D4: lookup and search divergences."""

    def test_lookup_second_page_not_empty(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY", "skip": 1, "limit": 1},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert len(resp.json()["items"]) == 1

    def test_lookup_total_is_match_count(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY", "limit": 1},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["page"]["total"] == 2

    def test_lookup_filters_are_anded(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY", "ticket": "NOSUCH"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["page"]["total"] == 0

    def test_lookup_q_covers_tcg(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "QNUM-9"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["page"]["total"] == 1

    def test_lookup_number_is_substring(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"test_case_number": "QNUM"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            ids = [item["test_case"]["id"] for item in resp.json()["items"]]
            assert seeded["case_ids"][0] in ids

    def test_lookup_order_is_created_desc_id_desc(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            ids = [item["test_case"]["id"] for item in resp.json()["items"]]
            c1, c2 = seeded["case_ids"][0], seeded["case_ids"][1]
            assert ids == [c2, c1]

    def test_lookup_unknown_team_returns_404(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY", "team_id": 999999},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 404


class TestTierATestCases:
    """D4, D5, D6, D7, D9: test-cases list divergences."""

    def test_search_covers_number_and_tcg(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                params={"search": "QNUM"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["page"]["total"] == 2

    def test_unknown_set_id_reports_not_found(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                params={"set_id": 999999},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["filters"]["set_not_found"] is True
            assert data["page"]["total"] == 3

    def test_strict_set_returns_404(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                params={"set_id": 999999, "strict_set": "true"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 404

    def test_set_id_zero_applies_unknown_set_semantics(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            headers = _bearer(seeded["app_token"])
            baseline = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                headers=headers,
            )
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                params={"set_id": 0},
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["filters"]["set_not_found"] is True
            assert data["page"]["total"] == baseline.json()["page"]["total"]

    def test_test_cases_order_is_created_desc(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            ids = [tc["id"] for tc in resp.json()["test_cases"]]
            assert ids == list(reversed(seeded["case_ids"]))

    def test_filters_include_set_not_found_keys(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-cases",
                params={"set_id": 999999},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            filters = resp.json()["filters"]
            assert "set_not_found" in filters
            assert "resolved_set_id" in filters


class TestTierASections:
    """D25: section ordering divergence."""

    def test_sections_order_is_set_level_sort_id(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            headers = _bearer(seeded["app_token"])
            app_resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-case-sections",
                headers=headers,
            )
            mcp_resp = client.get(
                f"/api/mcp/teams/{seeded['team_a_id']}/test-case-sections",
                headers=headers,
            )
            assert app_resp.status_code == 200
            assert mcp_resp.status_code == 200
            app_ids = [s["id"] for s in app_resp.json()["sections"]]
            mcp_ids = [s["id"] for s in mcp_resp.json()["sections"]]
            assert app_ids == mcp_ids
            assert app_ids[0] == seeded["section_late_id"]


class TestTierATestRuns:
    """D30–D36, D40, D1: test-runs and team status divergences."""

    def test_run_type_excludes_sets(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                params={"run_type": "adhoc"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            assert resp.json()["sets"] == []

    def test_archived_sets_excluded_by_default(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            set_ids = [s["id"] for s in resp.json()["sets"]]
            assert seeded["set_archived_id"] not in set_ids

    def test_archived_sets_included_when_requested(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                params={"include_archived": "true"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            data = resp.json()
            set_ids = [s["id"] for s in data["sets"]]
            assert seeded["set_archived_id"] in set_ids
            assert data["filters"]["include_archived"] is True

    def test_set_status_uses_resolver_not_raw(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            headers = _bearer(seeded["app_token"])
            mcp_resp = client.get(
                f"/api/mcp/teams/{seeded['team_a_id']}/test-runs",
                headers=headers,
            )
            app_resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                headers=headers,
            )
            mcp_sets = {s["id"]: s["status"] for s in mcp_resp.json()["sets"]}
            app_sets = {s["id"]: s["status"] for s in app_resp.json()["sets"]}
            # Guard: mcp must resolve ACTIVE SET to completed (seed sanity).
            assert mcp_sets[seeded["set_active_id"]] == "completed"
            # Post-fix: app must also resolve to completed.
            assert app_sets[seeded["set_active_id"]] == "completed"

    def test_summary_has_canonical_and_legacy_keys(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            summary = resp.json()["summary"]
            for key in ("set_count", "set_run_count", "unassigned_count", "adhoc_count", "total_runs"):
                assert key in summary
            for alias in ("sets", "unassigned", "adhoc"):
                assert alias in summary

    def test_adhoc_counts_are_computed(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_a_id']}/test-runs",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            adhoc = {a["id"]: a for a in resp.json()["adhoc"]}
            active = adhoc[seeded["adhoc_active_id"]]
            assert active["total_test_cases"] == 2
            assert active["executed_cases"] == 1

    def test_null_team_status_falls_back_to_active(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/teams",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            teams = {t["id"]: t for t in resp.json()["items"]}
            assert teams[seeded["team_a_id"]]["status"] == "active"

    def test_app_test_runs_mirrors_mcp_unified_filters(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            headers = _bearer(seeded["app_token"])
            team = seeded["team_a_id"]

            def _ids(payload, attr):
                return {item["id"] for item in payload[attr]}

            def _set_member_ids(payload):
                ids = []
                for s in payload["sets"]:
                    ids.extend(r["id"] for r in s["test_runs"])
                return set(ids)

            # (1) default
            app_d = client.get(f"/api/app/teams/{team}/test-runs", headers=headers).json()
            mcp_d = client.get(f"/api/mcp/teams/{team}/test-runs", headers=headers).json()
            assert _ids(app_d, "sets") == _ids(mcp_d, "sets")
            assert _ids(app_d, "unassigned") == _ids(mcp_d, "unassigned")
            assert _ids(app_d, "adhoc") == _ids(mcp_d, "adhoc")
            assert _set_member_ids(app_d) == _set_member_ids(mcp_d)
            # D34: first member is position=0 (IN-SET-CFG-B)
            active_set = next(s for s in app_d["sets"] if s["id"] == seeded["set_active_id"])
            assert active_set["test_runs"][0]["id"] == seeded["config_in_set_b_id"]

            # (2) status=completed — ACTIVE SET must appear (resolve completed)
            app_c = client.get(
                f"/api/app/teams/{team}/test-runs",
                params={"status": "completed"},
                headers=headers,
            ).json()
            mcp_c = client.get(
                f"/api/mcp/teams/{team}/test-runs",
                params={"status": "completed"},
                headers=headers,
            ).json()
            assert _ids(app_c, "sets") == _ids(mcp_c, "sets")
            assert seeded["set_active_id"] in _ids(app_c, "sets")

            # (3) run_type=adhoc, status=archived, include_archived=true
            params = {"run_type": "adhoc", "status": "archived", "include_archived": "true"}
            app_a = client.get(
                f"/api/app/teams/{team}/test-runs", params=params, headers=headers
            ).json()
            mcp_a = client.get(
                f"/api/mcp/teams/{team}/test-runs", params=params, headers=headers
            ).json()
            assert _ids(app_a, "adhoc") == _ids(mcp_a, "adhoc")


# ---------------------------------------------------------------------------
# Tier C — response-shape parity (xfail until Phase 4)
# ---------------------------------------------------------------------------


class TestTierCParity:
    def test_parity_response_shapes_match_allowlist(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            headers = _bearer(seeded["app_token"])
            team = seeded["team_a_id"]
            case_id = seeded["case_ids"][0]

            endpoints = [
                ("/api/app/teams", "/api/mcp/teams", {}),
                (
                    f"/api/app/teams/{team}/test-cases",
                    f"/api/mcp/teams/{team}/test-cases",
                    {"include_content": "false", "include_test_data": "false"},
                ),
                (
                    f"/api/app/teams/{team}/test-cases/{case_id}",
                    f"/api/mcp/teams/{team}/test-cases/{case_id}",
                    {},
                ),
                (
                    "/api/app/test-cases/lookup",
                    "/api/mcp/test-cases/lookup",
                    {
                        "q": "ZKEY",
                        "include_content": "false",
                        "include_test_data": "false",
                    },
                ),
                (
                    f"/api/app/teams/{team}/test-case-sections",
                    f"/api/mcp/teams/{team}/test-case-sections",
                    {},
                ),
                (
                    f"/api/app/teams/{team}/test-runs",
                    f"/api/mcp/teams/{team}/test-runs",
                    {},
                ),
            ]

            for app_path, mcp_path, params in endpoints:
                app_resp = client.get(app_path, params=params, headers=headers)
                mcp_resp = client.get(mcp_path, params=params, headers=headers)
                assert app_resp.status_code == mcp_resp.status_code, app_path
                diffs = _diff_payloads(app_resp.json(), mcp_resp.json())
                assert diffs == [], f"{app_path}: divergent paths {diffs}"


# ---------------------------------------------------------------------------
# Green guards — team scope (HTTP) and authorization model (unit)
# ---------------------------------------------------------------------------


class TestScopeGuards:
    def test_lookup_respects_team_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                "/api/app/test-cases/lookup",
                params={"q": "ZKEY"},
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 200
            team_ids = {item["team_id"] for item in resp.json()["items"]}
            assert seeded["team_b_id"] not in team_ids

    def test_list_respects_team_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_b_id']}/test-cases",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 403

    def test_detail_respects_team_scope(self, temp_db):
        with temp_db() as session:
            seeded = _seed_parity_data(session)
        with TestClient(app) as client:
            resp = client.get(
                f"/api/app/teams/{seeded['team_b_id']}/test-cases/1",
                headers=_bearer(seeded["app_token"]),
            )
            assert resp.status_code == 403


class TestAuthorizationModel:
    def test_accessible_team_ids_includes_owner_when_scope_empty(self):
        p = AppTokenPrincipal(
            credential_id=1,
            credential_name="t",
            owner_team_id=5,
            team_scope_ids=[],
            allow_all_teams=False,
            scopes=["test_case:read"],
        )
        assert p.accessible_team_ids() == {5}
        assert p.can_access_team(5) is True
        assert p.can_access_team(6) is False

    def test_mcp_mapping_includes_owner_in_scope(self):
        from app.auth.mcp_dependencies import _map_app_principal_to_machine

        p = AppTokenPrincipal(
            credential_id=1,
            credential_name="t",
            owner_team_id=5,
            team_scope_ids=[],
            allow_all_teams=False,
            scopes=["test_case:read"],
        )
        machine = _map_app_principal_to_machine(p)
        assert machine.team_scope_ids == [5]
        assert machine.allow_all_teams is False



# ---------------------------------------------------------------------------
# Empty-set contract (green) — direct canonical function calls
# ---------------------------------------------------------------------------


@pytest.fixture
def async_parity_db(tmp_path, monkeypatch):
    """Provides both sync and async session factories backed by the same DB."""
    database_bundle = create_managed_test_database(
        tmp_path / "test_external_read_parity.db"
    )
    TestingSessionLocal = database_bundle["sync_session_factory"]
    AsyncTestingSessionLocal = database_bundle["async_session_factory"]

    import app.main as app_main
    import app.models.user_story_map_db as usm_db_module

    install_main_database_overrides(
        monkeypatch=monkeypatch,
        app=app,
        get_db_dependency=get_db,
        async_engine=database_bundle["async_engine"],
        async_session_factory=AsyncTestingSessionLocal,
    )

    async def _noop_async(*args, **kwargs):
        return None

    monkeypatch.setattr(app_main, "init_audit_database", _noop_async)
    monkeypatch.setattr(app_main, "cleanup_audit_database", _noop_async)
    monkeypatch.setattr(app_main.audit_service, "force_flush", _noop_async)
    monkeypatch.setattr(usm_db_module, "init_usm_db", _noop_async)

    yield TestingSessionLocal, AsyncTestingSessionLocal

    app.dependency_overrides.pop(get_db, None)
    dispose_managed_test_database(database_bundle)


class TestEmptySetContract:
    async def test_empty_allowed_team_ids_list_teams(self, async_parity_db):
        TestingSessionLocal, AsyncTestingSessionLocal = async_parity_db
        with TestingSessionLocal() as session:
            _seed_parity_data(session)
        async with AsyncTestingSessionLocal() as db:
            result = await list_teams_read(db, allowed_team_ids=set())
        assert result.total == 0
        assert result.items == []

    async def test_empty_allowed_team_ids_lookup(self, async_parity_db):
        TestingSessionLocal, AsyncTestingSessionLocal = async_parity_db
        with TestingSessionLocal() as session:
            _seed_parity_data(session)
        async with AsyncTestingSessionLocal() as db:
            result = await lookup_test_cases_read(
                db,
                q="ZKEY",
                test_case_number=None,
                ticket=None,
                team_id=None,
                team_name=None,
                include_content=False,
                include_test_data=False,
                skip=0,
                limit=20,
                allowed_team_ids=set(),
            )
        assert result.page.total == 0
        assert result.items == []

    def test_allowed_team_ids_uses_is_none_not_truthiness(self):
        import ast

        src = Path("app/services/external_read/queries.py").read_text()
        # Skip the module docstring — it documents the anti-pattern by name.
        tree = ast.parse(src)
        module_doc = ast.get_docstring(tree)
        code = src.replace(module_doc, "", 1) if module_doc else src
        assert "if not allowed_team_ids" not in code
        assert "if allowed_team_ids:" not in code
        assert "is None" in code and "len(allowed_team_ids)" in code
        assert code.count("len(allowed_team_ids)") >= 2
