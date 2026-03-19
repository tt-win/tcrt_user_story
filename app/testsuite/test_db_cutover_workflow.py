from __future__ import annotations

import json
from pathlib import Path

from app.db_cutover_workflow import (
    build_workflow_target,
    compare_rehearsal_summaries,
    extract_json_payload,
    redact_environment,
    render_markdown_summary,
)


def test_build_workflow_target_for_sqlite_uses_isolated_files(tmp_path: Path) -> None:
    target = build_workflow_target("sqlite", tmp_path)

    assert target.name == "sqlite"
    assert target.compose_file is None
    assert target.environment["DATABASE_URL"].startswith("sqlite:///")
    assert target.environment["AUDIT_DATABASE_URL"].endswith("/audit.db")
    assert target.environment["USM_DATABASE_URL"].endswith("/userstorymap.db")


def test_extract_json_payload_ignores_database_init_banner() -> None:
    output = """
============================================================
🗃️  資料庫 Bootstrap 系統（Alembic）
============================================================
{
  "targets": [
    {"target": "main", "ready": true}
  ]
}
"""

    payload = extract_json_payload(output)

    assert payload["targets"][0]["target"] == "main"
    assert payload["targets"][0]["ready"] is True


def test_compare_rehearsal_summaries_detects_row_count_mismatch() -> None:
    baseline = {
        "verification": {
            "targets": [
                {
                    "target": "main",
                    "current_revision": "abc",
                    "required_tables": {"users": True},
                    "critical_row_counts": {"users": 1},
                },
                {
                    "target": "audit",
                    "current_revision": "def",
                    "required_tables": {"audit_logs": True},
                    "critical_row_counts": {"audit_logs": 0},
                },
                {
                    "target": "usm",
                    "current_revision": "ghi",
                    "required_tables": {"user_story_maps": True},
                    "critical_row_counts": {"user_story_maps": 0},
                },
            ]
        }
    }
    current = {
        "verification": {
            "targets": [
                {
                    "target": "main",
                    "current_revision": "abc",
                    "required_tables": {"users": True},
                    "critical_row_counts": {"users": 2},
                },
                {
                    "target": "audit",
                    "current_revision": "def",
                    "required_tables": {"audit_logs": True},
                    "critical_row_counts": {"audit_logs": 0},
                },
                {
                    "target": "usm",
                    "current_revision": "ghi",
                    "required_tables": {"user_story_maps": True},
                    "critical_row_counts": {"user_story_maps": 0},
                },
            ]
        }
    }

    comparison = compare_rehearsal_summaries(current, baseline)

    assert comparison["matches"] is False
    main_target = next(item for item in comparison["targets"] if item["target"] == "main")
    assert main_target["matches"] is False
    assert main_target["critical_row_counts"][0]["baseline"] == 1
    assert main_target["critical_row_counts"][0]["current"] == 2


def test_redact_environment_hides_passwords_and_secret() -> None:
    redacted = redact_environment(
        {
            "DATABASE_URL": "mysql+asyncmy://tcrt:tcrt@127.0.0.1:33060/tcrt_main",
            "SYNC_DATABASE_URL": "postgresql+psycopg://foo:bar@127.0.0.1:5433/db",
            "AUDIT_DATABASE_URL": "sqlite:////tmp/audit.db",
            "USM_DATABASE_URL": "sqlite:////tmp/usm.db",
            "JWT_SECRET_KEY": "secret",
            "HOST": "127.0.0.1",
            "PORT": "9999",
            "SERVER_PID_FILE": "/tmp/server.pid",
        }
    )

    assert redacted["DATABASE_URL"] == "mysql+asyncmy://tcrt:***@127.0.0.1:33060/tcrt_main"
    assert redacted["SYNC_DATABASE_URL"] == "postgresql+psycopg://foo:***@127.0.0.1:5433/db"
    assert redacted["JWT_SECRET_KEY"] == "<redacted>"


def test_render_markdown_summary_includes_comparison_and_health() -> None:
    summary = {
        "target": "mysql",
        "mode": "rehearsal",
        "success": True,
        "run_dir": "/tmp/db-cutover/run",
        "generated_at": "2026-03-18T10:00:00+00:00",
        "environment": {"DATABASE_URL": "mysql+asyncmy://tcrt:***@127.0.0.1:33060/tcrt_main"},
        "guardrails": {"passed": True, "violations": []},
        "steps": {
            "preflight": {"returncode": 0},
            "bootstrap": {"returncode": 0},
            "verify": {"returncode": 0},
        },
        "verification": {
            "targets": [
                {
                    "target": "main",
                    "ready": True,
                    "current_revision": "abc",
                    "head_revision": "abc",
                    "critical_row_counts": {"users": 0},
                }
            ]
        },
        "health_check": {"ok": True, "url": "http://127.0.0.1:19999/health"},
        "comparison": {"matches": True, "targets": [{"target": "main", "matches": True}]},
        "baseline_summary_path": "/tmp/base/summary.json",
    }

    rendered = render_markdown_summary(summary)

    assert "# DB Cutover Workflow Summary" in rendered
    assert "- health: `ok`" in rendered
    assert "- baseline: `/tmp/base/summary.json`" in rendered
    assert "- main: `match`" in rendered
