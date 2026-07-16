from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

import app.db_cutover_workflow as db_cutover_workflow_module
from app.db_cutover_workflow import (
    CommandResult,
    build_workflow_target,
    compare_rehearsal_summaries,
    detect_non_empty_targets,
    extract_json_payload,
    parse_env_file,
    redact_environment,
    render_markdown_summary,
    resolve_migrate_endpoints,
    resolve_migrate_target_endpoints,
    run_cutover_workflow,
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


def test_run_command_redacts_database_urls_from_result_and_log(monkeypatch, tmp_path: Path) -> None:
    source_url = "postgresql+psycopg://reader:source-secret@source-db:5432/tcrt_main"
    target_url = "mysql+asyncmy://tcrt:target-secret@db:3306/tcrt_main"
    derived_sync_url = "mysql+pymysql://tcrt:target-secret@db:3306/tcrt_main"
    command = ["migrate", "--source-url", source_url]
    environment = {"DATABASE_URL": target_url, "JWT_SECRET_KEY": "jwt-secret"}

    monkeypatch.setattr(
        db_cutover_workflow_module.subprocess,
        "run",
        lambda *_args, **_kwargs: db_cutover_workflow_module.subprocess.CompletedProcess(
            command,
            0,
            stdout=f"source={source_url} target={derived_sync_url} jwt=jwt-secret",
            stderr=f"failed target={target_url}",
        ),
    )

    log_path = tmp_path / "migrate.log"
    result = db_cutover_workflow_module._run_command(
        command=command,
        environment=environment,
        log_path=log_path,
    )
    persisted = json.dumps(result.as_json()) + log_path.read_text(encoding="utf-8")

    assert "target-secret" not in persisted
    assert "source-secret" not in persisted
    assert "jwt-secret" not in persisted
    assert "mysql+pymysql://tcrt:***@db:3306/tcrt_main" in persisted


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


def test_render_markdown_summary_handles_early_failure_without_steps() -> None:
    """guardrails 失敗等早期中止情境：steps 尚未有 preflight/bootstrap/verify，不應 KeyError。"""
    summary = {
        "target": "sqlite",
        "mode": "migrate",
        "success": False,
        "run_dir": "/tmp/db-cutover/run",
        "generated_at": "2026-03-18T10:00:00+00:00",
        "environment": {},
        "guardrails": {},
        "steps": {},
        "verification": {},
        "health_check": None,
    }

    rendered = render_markdown_summary(summary)

    assert "- preflight: `rc=n/a`" in rendered
    assert "- passed: `no`" in rendered


def test_render_markdown_summary_includes_migration_and_env_summary() -> None:
    summary = {
        "target": "sqlite",
        "mode": "migrate",
        "success": True,
        "run_dir": "/tmp/db-cutover/run",
        "generated_at": "2026-03-18T10:00:00+00:00",
        "environment": {},
        "guardrails": {"passed": True, "violations": []},
        "steps": {
            "preflight": {"returncode": 0},
            "bootstrap": {"returncode": 0},
            "verify": {"returncode": 0},
        },
        "verification": {"targets": []},
        "health_check": {"ok": True, "url": "http://127.0.0.1:19997/health"},
        "migration": {
            "row_counts_match": True,
            "duration_seconds": 1.23,
            "jobs": [{"job": "main", "tables": [{"table": "teams", "rows": 1}], "row_counts_match": True}],
        },
        "env_summary": {"DATABASE_URL": "sqlite:///***"},
    }

    rendered = render_markdown_summary(summary)

    assert "## Migration" in rendered
    assert "- row_counts_match: `yes`" in rendered
    assert "- main: tables=`1`, rows=`1`, row_counts_match=`yes`" in rendered
    assert "## Env Summary" in rendered
    assert "- DATABASE_URL: `sqlite:///***`" in rendered


def test_parse_env_file_skips_comments_blank_lines_and_strips_quotes(tmp_path: Path) -> None:
    env_path = tmp_path / "target.env"
    env_path.write_text(
        "\n".join(
            [
                "# comment line",
                "",
                "DATABASE_URL=postgresql+asyncpg://tcrt:secret@db:5432/main",
                "SYNC_DATABASE_URL='postgresql+psycopg://tcrt:secret@db:5432/main'",
                '  AUDIT_DATABASE_URL = "postgresql+asyncpg://tcrt:secret@db:5432/audit"  ',
                "MALFORMED_LINE_NO_EQUALS",
            ]
        ),
        encoding="utf-8",
    )

    values = parse_env_file(env_path)

    assert values["DATABASE_URL"] == "postgresql+asyncpg://tcrt:secret@db:5432/main"
    assert values["SYNC_DATABASE_URL"] == "postgresql+psycopg://tcrt:secret@db:5432/main"
    assert values["AUDIT_DATABASE_URL"] == "postgresql+asyncpg://tcrt:secret@db:5432/audit"
    assert "MALFORMED_LINE_NO_EQUALS" not in values


def test_resolve_migrate_target_endpoints_requires_all_four_keys(tmp_path: Path) -> None:
    env_path = tmp_path / "incomplete.env"
    env_path.write_text("DATABASE_URL=sqlite:///x.db\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺少必要鍵"):
        resolve_migrate_target_endpoints(str(env_path), build_workflow_target("sqlite", tmp_path))


def test_resolve_migrate_target_endpoints_falls_back_to_disposable_target(tmp_path: Path) -> None:
    target = build_workflow_target("sqlite", tmp_path)

    values = resolve_migrate_target_endpoints(None, target)

    assert values == target.environment


def test_resolve_migrate_endpoints_rejects_same_database(monkeypatch, tmp_path: Path) -> None:
    shared_db = tmp_path / "shared.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{shared_db}")
    monkeypatch.setenv("SYNC_DATABASE_URL", f"sqlite:///{shared_db}")
    monkeypatch.setenv("AUDIT_DATABASE_URL", f"sqlite:///{tmp_path / 'audit.db'}")
    monkeypatch.setenv("USM_DATABASE_URL", f"sqlite:///{tmp_path / 'usm.db'}")

    env_path = tmp_path / "target.env"
    env_path.write_text(
        "\n".join(
            [
                f"DATABASE_URL=sqlite:///{shared_db}",
                f"SYNC_DATABASE_URL=sqlite:///{shared_db}",
                f"AUDIT_DATABASE_URL=sqlite:///{tmp_path / 'other-audit.db'}",
                f"USM_DATABASE_URL=sqlite:///{tmp_path / 'other-usm.db'}",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="拒絕執行"):
        resolve_migrate_endpoints(
            target=build_workflow_target("sqlite", tmp_path),
            target_env_file=str(env_path),
            source_env_file=None,
        )


def test_detect_non_empty_targets_reports_existing_rows(tmp_path: Path) -> None:
    main_db = tmp_path / "main.db"
    engine = create_engine(f"sqlite:///{main_db}", future=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO teams (name) VALUES ('demo')"))
    engine.dispose()

    from app.db_cutover_workflow import MigrateEndpoints

    endpoints = MigrateEndpoints(
        source={},
        target={
            "SYNC_DATABASE_URL": f"sqlite:///{main_db}",
            "AUDIT_DATABASE_URL": f"sqlite:///{tmp_path / 'audit.db'}",
            "USM_DATABASE_URL": f"sqlite:///{tmp_path / 'usm.db'}",
        },
    )

    non_empty = detect_non_empty_targets(endpoints)

    assert non_empty == {"main": [{"table": "teams", "rows": 1}]}


def test_detect_non_empty_targets_treats_missing_database_as_empty(tmp_path: Path) -> None:
    from app.db_cutover_workflow import MigrateEndpoints

    endpoints = MigrateEndpoints(
        source={},
        target={
            "SYNC_DATABASE_URL": f"sqlite:///{tmp_path / 'nonexistent-main.db'}",
            "AUDIT_DATABASE_URL": f"sqlite:///{tmp_path / 'nonexistent-audit.db'}",
            "USM_DATABASE_URL": f"sqlite:///{tmp_path / 'nonexistent-usm.db'}",
        },
    )

    assert detect_non_empty_targets(endpoints) == {}


def _fake_health_check(*, environment, pid_file, timeout_seconds, log_path):
    return {
        "start_command": CommandResult(command=["fake-start"], returncode=0, duration_seconds=0.01),
        "health": {"ok": True, "url": "http://fake/health", "status_code": 200, "body": "ok", "error": None},
    }


def _fake_guardrails_pass() -> dict:
    """既有 repo 目前有已知、與本次 migrate 邏輯無關的 guardrail 違規（見 Change A verification.md），
    這裡 bypass 掉，讓測試只驗證 migrate 流程本身，不與那個既有問題耦合。"""
    return {"passed": True, "message": "", "violations": []}


def _insert_demo_team(database_url: str, *, name: str) -> None:
    from sqlalchemy.orm import Session

    from app.models.database_models import Team

    engine = create_engine(database_url, future=True)
    try:
        with Session(engine) as session:
            session.add(Team(name=name, wiki_token=f"wiki-{name}", test_case_table_id=f"table-{name}"))
            session.commit()
    finally:
        engine.dispose()


def _bootstrap_source_databases(source_dir: Path) -> dict[str, str]:
    from app.db_migrations import upgrade_database

    main_url = f"sqlite:///{source_dir / 'main.db'}"
    audit_url = f"sqlite:///{source_dir / 'audit.db'}"
    usm_url = f"sqlite:///{source_dir / 'usm.db'}"
    upgrade_database(database_url=main_url, target_name="main")
    upgrade_database(database_url=audit_url, target_name="audit")
    upgrade_database(database_url=usm_url, target_name="usm")

    _insert_demo_team(main_url, name="demo-team")

    return {
        "DATABASE_URL": main_url,
        "SYNC_DATABASE_URL": main_url,
        "AUDIT_DATABASE_URL": audit_url,
        "USM_DATABASE_URL": usm_url,
    }


def test_migrate_mode_copies_source_data_into_disposable_sqlite_target(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_urls = _bootstrap_source_databases(source_dir)
    for key, value in source_urls.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(db_cutover_workflow_module, "_run_health_check", _fake_health_check)
    monkeypatch.setattr(db_cutover_workflow_module, "_run_guardrails", lambda: _fake_guardrails_pass())

    summary = run_cutover_workflow(
        target_name="sqlite",
        mode="migrate",
        output_root=tmp_path / "out",
        manage_services=False,
        keep_services=False,
        health_timeout=5,
    )

    assert summary["success"] is True, json.dumps(summary, ensure_ascii=False, indent=2)
    assert summary["migration"]["row_counts_match"] is True
    assert set(summary["env_summary"].keys()) == {
        "DATABASE_URL",
        "SYNC_DATABASE_URL",
        "AUDIT_DATABASE_URL",
        "USM_DATABASE_URL",
    }

    target_main_db = Path(summary["run_dir"]) / "test_case_repo.db"
    target_engine = create_engine(f"sqlite:///{target_main_db}", future=True)
    with target_engine.connect() as connection:
        target_team_names = [row[0] for row in connection.execute(text("SELECT name FROM teams"))]
    target_engine.dispose()
    assert target_team_names == ["demo-team"]

    source_engine = create_engine(source_urls["DATABASE_URL"], future=True)
    with source_engine.connect() as connection:
        source_team_names = [row[0] for row in connection.execute(text("SELECT name FROM teams"))]
    source_engine.dispose()
    assert source_team_names == ["demo-team"]


def test_migrate_mode_aborts_on_non_empty_target_without_force_reset(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_urls = _bootstrap_source_databases(source_dir)
    for key, value in source_urls.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(db_cutover_workflow_module, "_run_health_check", _fake_health_check)
    monkeypatch.setattr(db_cutover_workflow_module, "_run_guardrails", lambda: _fake_guardrails_pass())

    # 目標須是「已正確 bootstrap 過、已有業務資料」的既有系統（有 alembic_version 且在 head），
    # 而非未納管的裸表——否則會在 preflight 就先被判為 legacy_unmanaged，測不到非空防呆。
    output_root = tmp_path / "out"
    target_env_path = tmp_path / "target.env"
    existing_target_dir = tmp_path / "existing-target"
    existing_target_dir.mkdir()
    existing_main_db = existing_target_dir / "main.db"
    existing_audit_db = existing_target_dir / "audit.db"
    existing_usm_db = existing_target_dir / "usm.db"

    from app.db_migrations import upgrade_database

    upgrade_database(database_url=f"sqlite:///{existing_main_db}", target_name="main")
    upgrade_database(database_url=f"sqlite:///{existing_audit_db}", target_name="audit")
    upgrade_database(database_url=f"sqlite:///{existing_usm_db}", target_name="usm")
    _insert_demo_team(f"sqlite:///{existing_main_db}", name="stale-team")

    target_env_path.write_text(
        "\n".join(
            [
                f"DATABASE_URL=sqlite:///{existing_main_db}",
                f"SYNC_DATABASE_URL=sqlite:///{existing_main_db}",
                f"AUDIT_DATABASE_URL=sqlite:///{existing_audit_db}",
                f"USM_DATABASE_URL=sqlite:///{existing_usm_db}",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_cutover_workflow(
        target_name="sqlite",
        mode="migrate",
        output_root=output_root,
        manage_services=False,
        keep_services=False,
        health_timeout=5,
        target_env_file=str(target_env_path),
    )

    assert summary["success"] is False
    assert "non_empty_tables" in summary
    assert summary["non_empty_tables"]["main"] == [{"table": "teams", "rows": 1}]
    assert "bootstrap" not in summary["steps"]


def test_migrate_mode_force_reset_target_overwrites_existing_data(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_urls = _bootstrap_source_databases(source_dir)
    for key, value in source_urls.items():
        monkeypatch.setenv(key, value)

    monkeypatch.setattr(db_cutover_workflow_module, "_run_health_check", _fake_health_check)
    monkeypatch.setattr(db_cutover_workflow_module, "_run_guardrails", lambda: _fake_guardrails_pass())

    # 目標先走一次正常 bootstrap 建立官方 schema，再灌一列「既有」資料模擬曾經部署過的 production-like 目標。
    target_env_path = tmp_path / "target.env"
    existing_target_dir = tmp_path / "existing-target"
    existing_target_dir.mkdir()
    existing_main_db = existing_target_dir / "main.db"
    existing_audit_db = existing_target_dir / "audit.db"
    existing_usm_db = existing_target_dir / "usm.db"

    from app.db_migrations import upgrade_database

    upgrade_database(database_url=f"sqlite:///{existing_main_db}", target_name="main")
    upgrade_database(database_url=f"sqlite:///{existing_audit_db}", target_name="audit")
    upgrade_database(database_url=f"sqlite:///{existing_usm_db}", target_name="usm")

    _insert_demo_team(f"sqlite:///{existing_main_db}", name="stale-team")

    target_env_path.write_text(
        "\n".join(
            [
                f"DATABASE_URL=sqlite:///{existing_main_db}",
                f"SYNC_DATABASE_URL=sqlite:///{existing_main_db}",
                f"AUDIT_DATABASE_URL=sqlite:///{existing_audit_db}",
                f"USM_DATABASE_URL=sqlite:///{existing_usm_db}",
            ]
        ),
        encoding="utf-8",
    )

    summary = run_cutover_workflow(
        target_name="sqlite",
        mode="migrate",
        output_root=tmp_path / "out",
        manage_services=False,
        keep_services=False,
        health_timeout=5,
        target_env_file=str(target_env_path),
        force_reset_target=True,
    )

    assert summary["success"] is True, json.dumps(summary, ensure_ascii=False, indent=2)

    target_engine = create_engine(f"sqlite:///{existing_main_db}", future=True)
    with target_engine.connect() as connection:
        team_names = [row[0] for row in connection.execute(text("SELECT name FROM teams"))]
    target_engine.dispose()
    assert team_names == ["demo-team"]


def test_main_rejects_baseline_summary_with_migrate_mode(tmp_path: Path) -> None:
    from app.db_cutover_workflow import main

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")

    exit_code = main(["--target", "sqlite", "--mode", "migrate", "--baseline-summary", str(baseline_path)])

    assert exit_code == 1
