from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from sqlalchemy import Column, Integer, JSON, MetaData, Table, Text, create_engine, inspect, text


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "db_cross_migrate.py"
    spec = importlib.util.spec_from_file_location("db_cross_migrate", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_run_job_copies_rows_between_sqlite_databases(tmp_path: Path) -> None:
    module = _load_script_module()
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"

    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        with source_engine.begin() as connection:
            connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(
                text(
                    "CREATE TABLE child ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_id INTEGER NOT NULL, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(parent_id) REFERENCES parent(id)"
                    ")"
                )
            )
            connection.execute(text("INSERT INTO parent (id, name) VALUES (1, 'p1'), (2, 'p2')"))
            connection.execute(
                text(
                    "INSERT INTO child (id, parent_id, name) VALUES "
                    "(10, 1, 'c1'), (11, 2, 'c2')"
                )
            )

        with target_engine.begin() as connection:
            connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(
                text(
                    "CREATE TABLE child ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_id INTEGER NOT NULL, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(parent_id) REFERENCES parent(id)"
                    ")"
                )
            )

        job = module.TransferJob(
            name="sqlite-copy",
            source_url=_sqlite_url(source_path),
            target_url=_sqlite_url(target_path),
            chunk_size=1,
        )
        summary = module.run_job(job, module.Logger(quiet=True))

        assert summary["status"] == "completed"
        assert [item["table"] for item in summary["tables"]] == ["parent", "child"]

        with target_engine.connect() as connection:
            parent_rows = connection.execute(text("SELECT id, name FROM parent ORDER BY id")).fetchall()
            child_rows = connection.execute(
                text("SELECT id, parent_id, name FROM child ORDER BY id")
            ).fetchall()

        assert parent_rows == [(1, "p1"), (2, "p2")]
        assert child_rows == [(10, 1, "c1"), (11, 2, "c2")]
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_run_job_reset_target_replaces_existing_rows(tmp_path: Path) -> None:
    module = _load_script_module()
    source_path = tmp_path / "source_reset.db"
    target_path = tmp_path / "target_reset.db"

    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        for engine in (source_engine, target_engine):
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))

        with source_engine.begin() as connection:
            connection.execute(text("INSERT INTO demo (id, name) VALUES (1, 'source')"))

        with target_engine.begin() as connection:
            connection.execute(text("INSERT INTO demo (id, name) VALUES (9, 'stale')"))

        job = module.TransferJob(
            name="sqlite-reset",
            source_url=_sqlite_url(source_path),
            target_url=_sqlite_url(target_path),
            reset_target=True,
        )
        module.run_job(job, module.Logger(quiet=True))

        with target_engine.connect() as connection:
            rows = connection.execute(text("SELECT id, name FROM demo ORDER BY id")).fetchall()

        assert rows == [(1, "source")]
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_load_jobs_from_config(tmp_path: Path) -> None:
    module = _load_script_module()
    config_path = tmp_path / "db_cross_migrate.yaml"
    config_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  chunk_size: 500",
                "  reset_target: true",
                "jobs:",
                "  - name: main",
                "    source_url: sqlite:///./source.db",
                "    target_url: sqlite:///./target.db",
                "    exclude_tables:",
                "      - alembic_version",
                "      - migration_history",
            ]
        ),
        encoding="utf-8",
    )

    jobs = module.load_jobs_from_config(config_path)

    assert len(jobs) == 1
    assert jobs[0].name == "main"
    assert jobs[0].chunk_size == 500
    assert jobs[0].reset_target is True
    assert jobs[0].exclude_tables == ["alembic_version", "migration_history"]


def test_resolve_table_order_honors_target_only_foreign_keys() -> None:
    module = _load_script_module()
    source_path = Path("/tmp/source-order.db")
    target_path = Path("/tmp/target-order.db")
    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        with source_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE test_case_sets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE test_case_sections ("
                    "id INTEGER PRIMARY KEY, "
                    "test_case_set_id INTEGER NOT NULL, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(test_case_set_id) REFERENCES test_case_sets(id)"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE test_cases ("
                    "id INTEGER PRIMARY KEY, "
                    "test_case_set_id INTEGER NOT NULL, "
                    "test_case_section_id INTEGER, "
                    "name TEXT NOT NULL"
                    ")"
                )
            )

        with target_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE test_case_sets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
                    )
            )
            connection.execute(
                text(
                    "CREATE TABLE test_case_sections ("
                    "id INTEGER PRIMARY KEY, "
                    "test_case_set_id INTEGER NOT NULL, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(test_case_set_id) REFERENCES test_case_sets(id)"
                    ")"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE test_cases ("
                    "id INTEGER PRIMARY KEY, "
                    "test_case_set_id INTEGER NOT NULL, "
                    "test_case_section_id INTEGER, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(test_case_set_id) REFERENCES test_case_sets(id), "
                    "FOREIGN KEY(test_case_section_id) REFERENCES test_case_sections(id)"
                    ")"
                )
            )

        source_metadata, selected_tables = module.reflect_selected_metadata(
            source_engine,
            include_tables=[],
            exclude_tables=[],
        )
        target_metadata, _ = module.reflect_selected_metadata(
            target_engine,
            include_tables=selected_tables,
            exclude_tables=[],
        )

        order = module.resolve_table_order(
            source_metadata,
            target_metadata,
            selected_tables,
            allow_cycles=False,
        )

        assert order.index("test_case_sections") < order.index("test_cases")
    finally:
        source_engine.dispose()
        target_engine.dispose()
        source_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)


def test_copy_table_data_sorts_self_referential_rows() -> None:
    module = _load_script_module()
    source_path = Path("/tmp/source-self-ref.db")
    target_path = Path("/tmp/target-self-ref.db")
    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        with source_engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE test_case_sections ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_section_id INTEGER, "
                    "name TEXT NOT NULL"
                    ")"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO test_case_sections (id, parent_section_id, name) VALUES "
                    "(63, 69, 'child-a'), "
                    "(64, 69, 'child-b'), "
                    "(69, NULL, 'parent')"
                )
            )

        with target_engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.execute(
                text(
                    "CREATE TABLE test_case_sections ("
                    "id INTEGER PRIMARY KEY, "
                    "parent_section_id INTEGER, "
                    "name TEXT NOT NULL, "
                    "FOREIGN KEY(parent_section_id) REFERENCES test_case_sections(id)"
                    ")"
                )
            )

        source_metadata, selected_tables = module.reflect_selected_metadata(
            source_engine,
            include_tables=[],
            exclude_tables=[],
        )
        target_metadata, _ = module.reflect_selected_metadata(
            target_engine,
            include_tables=selected_tables,
            exclude_tables=[],
        )

        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            target_connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            copied = module.copy_table_data(
                source_connection,
                target_connection,
                source_metadata.tables["test_case_sections"],
                target_metadata.tables["test_case_sections"],
                chunk_size=10,
            )

        assert copied == 3
        with target_engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, parent_section_id, name "
                    "FROM test_case_sections ORDER BY id"
                )
            ).fetchall()
        assert rows == [
            (63, 69, "child-a"),
            (64, 69, "child-b"),
            (69, None, "parent"),
        ]
    finally:
        source_engine.dispose()
        target_engine.dispose()
        source_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)


def test_mysql_text_type_for_size_and_widen_plan() -> None:
    module = _load_script_module()
    metadata = MetaData()
    target_table = Table(
        "ai_tc_helper_drafts",
        metadata,
        Column("payload_json", Text, nullable=True),
        Column("markdown", Text, nullable=True),
    )

    assert module._mysql_text_type_for_size(65535) == "TEXT"
    assert module._mysql_text_type_for_size(65536) == "MEDIUMTEXT"

    plans = module._plan_mysql_text_widenings(
        target_table,
        {
            "payload_json": 131335,
            "markdown": 1024,
        },
    )

    assert plans == [
        {
            "column_name": "payload_json",
            "required_bytes": 131335,
            "current_capacity": 65535,
            "target_type": "MEDIUMTEXT",
            "nullable": True,
        }
    ]


def test_copy_table_data_serializes_json_values_when_target_is_text(tmp_path: Path) -> None:
    module = _load_script_module()
    source_path = tmp_path / "source-json.db"
    target_path = tmp_path / "target-json.db"
    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        source_metadata = MetaData()
        Table(
            "user_story_maps",
            source_metadata,
            Column("id", Integer, primary_key=True),
            Column("nodes", JSON, nullable=True),
            Column("edges", JSON, nullable=True),
        )
        source_metadata.create_all(source_engine)

        target_metadata = MetaData()
        Table(
            "user_story_maps",
            target_metadata,
            Column("id", Integer, primary_key=True),
            Column("nodes", Text, nullable=True),
            Column("edges", Text, nullable=True),
        )
        target_metadata.create_all(target_engine)

        with source_engine.begin() as connection:
            connection.execute(
                source_metadata.tables["user_story_maps"].insert(),
                [
                    {
                        "id": 1,
                        "nodes": [{"id": "node-1", "title": "Login"}],
                        "edges": [{"source": "node-1", "target": "node-2"}],
                    }
                ],
            )

        reflected_source, _ = module.reflect_selected_metadata(
            source_engine,
            include_tables=["user_story_maps"],
            exclude_tables=[],
        )
        reflected_target, _ = module.reflect_selected_metadata(
            target_engine,
            include_tables=["user_story_maps"],
            exclude_tables=[],
        )

        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            copied = module.copy_table_data(
                source_connection,
                target_connection,
                reflected_source.tables["user_story_maps"],
                reflected_target.tables["user_story_maps"],
                chunk_size=10,
            )

        assert copied == 1
        with target_engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, nodes, edges FROM user_story_maps ORDER BY id")
            ).fetchall()

        assert rows == [
            (
                1,
                json.dumps([{"id": "node-1", "title": "Login"}], ensure_ascii=False),
                json.dumps([{"source": "node-1", "target": "node-2"}], ensure_ascii=False),
            )
        ]
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_copy_table_data_repairs_missing_test_case_set_with_default_section(tmp_path: Path) -> None:
    module = _load_script_module()
    source_path = tmp_path / "source-repair.db"
    target_path = tmp_path / "target-repair.db"
    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        with source_engine.begin() as connection:
            connection.execute(text("CREATE TABLE test_cases (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, test_case_set_id INTEGER, test_case_section_id INTEGER, title TEXT NOT NULL)"))
            connection.execute(
                text(
                    "INSERT INTO test_cases (id, team_id, test_case_set_id, test_case_section_id, title) VALUES "
                    "(1, 7, NULL, NULL, 'needs repair')"
                )
            )

        with target_engine.begin() as connection:
            connection.execute(text("CREATE TABLE test_case_sets (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, name TEXT NOT NULL, is_default INTEGER NOT NULL)"))
            connection.execute(text("CREATE TABLE test_case_sections (id INTEGER PRIMARY KEY, test_case_set_id INTEGER NOT NULL, name TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE test_cases (id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, test_case_set_id INTEGER NOT NULL, test_case_section_id INTEGER, title TEXT NOT NULL)"))
            connection.execute(
                text(
                    "INSERT INTO test_case_sets (id, team_id, name, is_default) VALUES "
                    "(70, 7, 'Default-7', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO test_case_sections (id, test_case_set_id, name) VALUES "
                    "(700, 70, 'Unassigned')"
                )
            )

        source_metadata, _ = module.reflect_selected_metadata(
            source_engine,
            include_tables=["test_cases"],
            exclude_tables=[],
        )
        target_metadata, _ = module.reflect_selected_metadata(
            target_engine,
            include_tables=["test_cases"],
            exclude_tables=[],
        )

        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            copied = module.copy_table_data(
                source_connection,
                target_connection,
                source_metadata.tables["test_cases"],
                target_metadata.tables["test_cases"],
                chunk_size=10,
                logger=module.Logger(quiet=True),
            )

        assert copied == 1
        with target_engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, team_id, test_case_set_id, test_case_section_id, title "
                    "FROM test_cases"
                )
            ).fetchall()
        assert rows == [(1, 7, 70, 700, "needs repair")]
    finally:
        source_engine.dispose()
        target_engine.dispose()


def test_resolve_jobs_applies_cli_overrides_for_config(tmp_path: Path) -> None:
    module = _load_script_module()
    config_path = tmp_path / "db_cross_migrate.yaml"
    config_path.write_text(
        "\n".join(
            [
                "defaults:",
                "  chunk_size: 500",
                "  reset_target: false",
                "jobs:",
                "  - name: main",
                "    source_url: sqlite:///./source.db",
                "    target_url: sqlite:///./target.db",
            ]
        ),
        encoding="utf-8",
    )

    args = module.parse_args(
        [
            "--config",
            str(config_path),
            "--reset-target",
            "--chunk-size",
            "7",
        ]
    )
    jobs = module.resolve_jobs(args)

    assert len(jobs) == 1
    assert jobs[0].reset_target is True
    assert jobs[0].chunk_size == 7


def test_copy_table_data_skips_orphan_test_run_item_history(tmp_path: Path) -> None:
    module = _load_script_module()
    source_path = tmp_path / "source-history.db"
    target_path = tmp_path / "target-history.db"
    source_engine = create_engine(_sqlite_url(source_path), future=True)
    target_engine = create_engine(_sqlite_url(target_path), future=True)

    try:
        with source_engine.begin() as connection:
            connection.execute(text("CREATE TABLE test_run_item_result_history (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, change_source TEXT)"))
            connection.execute(
                text(
                    "INSERT INTO test_run_item_result_history (id, item_id, change_source) VALUES "
                    "(1, 10, 'valid'), "
                    "(2, 99, 'orphan')"
                )
            )

        with target_engine.begin() as connection:
            connection.execute(text("CREATE TABLE test_run_items (id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE test_run_item_result_history (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, change_source TEXT, FOREIGN KEY(item_id) REFERENCES test_run_items(id))"))
            connection.execute(text("INSERT INTO test_run_items (id) VALUES (10)"))

        source_metadata, _ = module.reflect_selected_metadata(
            source_engine,
            include_tables=["test_run_item_result_history"],
            exclude_tables=[],
        )
        target_metadata, _ = module.reflect_selected_metadata(
            target_engine,
            include_tables=["test_run_item_result_history"],
            exclude_tables=[],
        )

        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            copied = module.copy_table_data(
                source_connection,
                target_connection,
                source_metadata.tables["test_run_item_result_history"],
                target_metadata.tables["test_run_item_result_history"],
                chunk_size=10,
                logger=module.Logger(quiet=True),
            )

        assert copied == 1
        with target_engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, item_id, change_source FROM test_run_item_result_history ORDER BY id")
            ).fetchall()
        assert rows == [(1, 10, "valid")]
    finally:
        source_engine.dispose()
        target_engine.dispose()
