#!/usr/bin/env python3
"""
Standalone cross-database data migration tool.

Design goals:
- Single script for SQLite / MySQL / PostgreSQL data transfer
- No dependency on app/* or project runtime components
- Supports CLI flags or YAML config file
- Assumes target schema is already initialized unless --create-target-schema is used
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml
from sqlalchemy import MetaData, create_engine, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.sqltypes import Text


DEFAULT_EXCLUDE_TABLES = ["alembic_version", "migration_history"]
MYSQL_TEXT_CAPACITIES = {
    "TINYTEXT": 255,
    "TEXT": 65535,
    "MEDIUMTEXT": 16777215,
    "LONGTEXT": 4294967295,
}


@dataclass
class TransferJob:
    name: str
    source_url: str
    target_url: str
    include_tables: list[str] = field(default_factory=list)
    exclude_tables: list[str] = field(default_factory=lambda: DEFAULT_EXCLUDE_TABLES.copy())
    chunk_size: int = 1000
    reset_target: bool = False
    create_target_schema: bool = False
    disable_constraints: bool = False
    dry_run: bool = False


class Logger:
    def __init__(self, *, verbose: bool = False, quiet: bool = False):
        self.verbose = verbose
        self.quiet = quiet

    def info(self, message: str) -> None:
        if not self.quiet:
            print(f"[INFO] {message}")

    def debug(self, message: str) -> None:
        if self.verbose and not self.quiet:
            print(f"[DEBUG] {message}")

    def warn(self, message: str) -> None:
        print(f"[WARN] {message}")

    def error(self, message: str) -> None:
        print(f"[ERROR] {message}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone cross-database migration tool")
    parser.add_argument("--config", help="YAML config path")
    parser.add_argument("--job", help="Only run the named job from config")
    parser.add_argument("--name", default=None, help="Single-run job name")
    parser.add_argument("--source-url", help="Source database URL")
    parser.add_argument("--target-url", help="Target database URL")
    parser.add_argument(
        "--include-tables",
        help="Comma-separated tables to include; default is all reflected tables",
    )
    parser.add_argument(
        "--exclude-tables",
        default=None,
        help="Comma-separated tables to exclude; default excludes alembic_version,migration_history",
    )
    parser.add_argument("--chunk-size", type=int, default=None, help="Bulk insert chunk size")
    parser.add_argument(
        "--reset-target",
        action="store_true",
        default=None,
        help="Delete target rows before copy",
    )
    parser.add_argument(
        "--create-target-schema",
        action="store_true",
        default=None,
        help="Create missing target tables from reflected source metadata",
    )
    parser.add_argument(
        "--disable-constraints",
        action="store_true",
        default=None,
        help="Temporarily disable target FK checks during reset/copy",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Validate and plan only; do not write data",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verbose", action="store_true")
    group.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def _parse_table_list(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [item.strip() for item in str(raw).split(",") if item.strip()]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_jobs_from_config(path: Path, only_job: str | None = None) -> list[TransferJob]:
    payload = _load_yaml(path)
    defaults = payload.get("defaults") or {}
    job_items = payload.get("jobs") or []
    jobs: list[TransferJob] = []

    for job_item in job_items:
        merged = {**defaults, **(job_item or {})}
        job = TransferJob(
            name=str(merged.get("name") or f"job-{len(jobs) + 1}"),
            source_url=str(merged["source_url"]),
            target_url=str(merged["target_url"]),
            include_tables=_parse_table_list(merged.get("include_tables")),
            exclude_tables=_parse_table_list(merged.get("exclude_tables")) or DEFAULT_EXCLUDE_TABLES.copy(),
            chunk_size=int(merged.get("chunk_size", 1000)),
            reset_target=bool(merged.get("reset_target", False)),
            create_target_schema=bool(merged.get("create_target_schema", False)),
            disable_constraints=bool(merged.get("disable_constraints", False)),
            dry_run=bool(merged.get("dry_run", False)),
        )
        if only_job and job.name != only_job:
            continue
        jobs.append(job)

    if only_job and not jobs:
        raise ValueError(f"找不到指定 job: {only_job}")
    return jobs


def build_single_job(args: argparse.Namespace) -> TransferJob:
    if not args.source_url or not args.target_url:
        raise ValueError("單次執行需要提供 --source-url 與 --target-url")
    return TransferJob(
        name=args.name or "default",
        source_url=args.source_url,
        target_url=args.target_url,
        include_tables=_parse_table_list(args.include_tables),
        exclude_tables=_parse_table_list(args.exclude_tables) or DEFAULT_EXCLUDE_TABLES.copy(),
        chunk_size=args.chunk_size if args.chunk_size is not None else 1000,
        reset_target=bool(args.reset_target),
        create_target_schema=bool(args.create_target_schema),
        disable_constraints=bool(args.disable_constraints),
        dry_run=bool(args.dry_run),
    )


def apply_cli_overrides_to_jobs(jobs: list[TransferJob], args: argparse.Namespace) -> list[TransferJob]:
    include_tables = _parse_table_list(args.include_tables) if args.include_tables is not None else None
    exclude_tables = _parse_table_list(args.exclude_tables) if args.exclude_tables is not None else None

    for job in jobs:
        if include_tables is not None:
            job.include_tables = include_tables.copy()
        if exclude_tables is not None:
            job.exclude_tables = exclude_tables.copy() or DEFAULT_EXCLUDE_TABLES.copy()
        if args.chunk_size is not None:
            job.chunk_size = args.chunk_size
        if args.reset_target:
            job.reset_target = True
        if args.create_target_schema:
            job.create_target_schema = True
        if args.disable_constraints:
            job.disable_constraints = True
        if args.dry_run:
            job.dry_run = True
    return jobs


def resolve_jobs(args: argparse.Namespace) -> list[TransferJob]:
    if args.config:
        jobs = load_jobs_from_config(Path(args.config), only_job=args.job)
        return apply_cli_overrides_to_jobs(jobs, args)
    return [build_single_job(args)]


def build_engine(database_url: str) -> Engine:
    engine_kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        engine_kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": 30,
        }
    return create_engine(database_url, **engine_kwargs)


def reflect_selected_metadata(
    engine: Engine,
    *,
    include_tables: list[str],
    exclude_tables: list[str],
) -> tuple[MetaData, list[str]]:
    inspector = inspect(engine)
    existing = inspector.get_table_names()
    excluded = {name.lower() for name in exclude_tables}
    included = {name.lower() for name in include_tables}

    selected = [
        table_name
        for table_name in existing
        if table_name.lower() not in excluded
        and (not included or table_name.lower() in included)
    ]
    metadata = MetaData()
    metadata.reflect(bind=engine, only=selected)
    return metadata, selected


def resolve_table_order(
    source_metadata: MetaData,
    target_metadata: MetaData,
    selected_tables: list[str],
    *,
    allow_cycles: bool,
) -> list[str]:
    dependency_map: dict[str, set[str]] = {}
    reverse_map: dict[str, set[str]] = {name: set() for name in selected_tables}

    for table_name in selected_tables:
        dependencies: set[str] = set()
        for metadata in (source_metadata, target_metadata):
            table = metadata.tables[table_name]
            dependencies.update(
                fk.column.table.name
                for fk in table.foreign_keys
                if fk.column.table.name in selected_tables and fk.column.table.name != table_name
            )
        dependency_map[table_name] = dependencies
        for dependency in dependencies:
            reverse_map[dependency].add(table_name)

    ready = deque(sorted(name for name, dependencies in dependency_map.items() if not dependencies))
    ordered: list[str] = []
    remaining = {name: set(dependencies) for name, dependencies in dependency_map.items()}

    while ready:
        current = ready.popleft()
        ordered.append(current)
        for dependant in sorted(reverse_map[current]):
            remaining[dependant].discard(current)
            if not remaining[dependant]:
                ready.append(dependant)

    if len(ordered) == len(selected_tables):
        return ordered

    cyclic_tables = sorted(set(selected_tables) - set(ordered))
    if not allow_cycles:
        raise RuntimeError(
            "偵測到循環外鍵依賴，請改用 --disable-constraints 或拆分 table 執行。"
            f" cycle={cyclic_tables}"
        )
    return ordered + cyclic_tables


def validate_target_tables(
    source_metadata: MetaData,
    target_metadata: MetaData,
    selected_tables: list[str],
) -> list[str]:
    warnings: list[str] = []
    target_table_names = set(target_metadata.tables)
    missing_tables = [name for name in selected_tables if name not in target_table_names]
    if missing_tables:
        raise RuntimeError(f"目標資料庫缺少 tables: {missing_tables}")

    for table_name in selected_tables:
        source_table = source_metadata.tables[table_name]
        target_table = target_metadata.tables[table_name]
        source_columns = set(source_table.c.keys())
        target_columns = set(target_table.c.keys())

        missing_required_columns = []
        for column in target_table.columns:
            if column.name in source_columns:
                continue
            has_default = (
                column.default is not None
                or column.server_default is not None
                or column.autoincrement is True
                or getattr(column, "identity", None) is not None
            )
            if not column.nullable and not has_default:
                missing_required_columns.append(column.name)

        if missing_required_columns:
            raise RuntimeError(
                f"目標 table {table_name} 有來源缺少且必填的欄位: {missing_required_columns}"
            )

        extra_source_columns = sorted(source_columns - target_columns)
        if extra_source_columns:
            warnings.append(
                f"table {table_name} 的來源欄位 {extra_source_columns} 不存在於目標，搬移時會忽略。"
            )

    return warnings


def _mysql_text_capacity(column) -> int | None:
    type_name = column.type.__class__.__name__.upper()
    if type_name in MYSQL_TEXT_CAPACITIES:
        return MYSQL_TEXT_CAPACITIES[type_name]
    if isinstance(column.type, Text):
        return MYSQL_TEXT_CAPACITIES["TEXT"]
    return None


def _mysql_text_type_for_size(required_bytes: int) -> str:
    for type_name, capacity in MYSQL_TEXT_CAPACITIES.items():
        if required_bytes <= capacity:
            return type_name
    raise RuntimeError(
        f"MySQL 無法容納 {required_bytes} bytes 的文字欄位內容；已超過 LONGTEXT 上限。"
    )


def _measure_source_text_sizes(
    source_connection: Connection,
    source_table,
    candidate_column_names: list[str],
) -> dict[str, int]:
    if not candidate_column_names:
        return {}

    max_lengths = {column_name: 0 for column_name in candidate_column_names}
    query = select(*(source_table.c[column_name] for column_name in candidate_column_names))
    result = source_connection.execution_options(stream_results=True).execute(query)

    for row in result:
        for column_name in candidate_column_names:
            value = row._mapping[column_name]
            if value is None:
                continue
            if isinstance(value, bytes):
                byte_length = len(value)
            elif isinstance(value, str):
                byte_length = len(value.encode("utf-8"))
            else:
                byte_length = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            if byte_length > max_lengths[column_name]:
                max_lengths[column_name] = byte_length

    return max_lengths


def _plan_mysql_text_widenings(target_table, max_lengths: dict[str, int]) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for column_name, required_bytes in max_lengths.items():
        target_column = target_table.c.get(column_name)
        if target_column is None:
            continue
        current_capacity = _mysql_text_capacity(target_column)
        if current_capacity is None or required_bytes <= current_capacity:
            continue
        target_type = _mysql_text_type_for_size(required_bytes)
        plans.append(
            {
                "column_name": column_name,
                "required_bytes": required_bytes,
                "current_capacity": current_capacity,
                "target_type": target_type,
                "nullable": bool(target_column.nullable),
            }
        )
    return plans


def ensure_mysql_text_capacity(
    source_connection: Connection,
    target_connection: Connection,
    source_table,
    target_table,
    logger: Logger,
) -> list[dict[str, Any]]:
    if target_connection.engine.dialect.name != "mysql":
        return []

    candidate_column_names = [
        column.name
        for column in target_table.columns
        if column.name in source_table.c and _mysql_text_capacity(column) is not None
    ]
    max_lengths = _measure_source_text_sizes(source_connection, source_table, candidate_column_names)
    plans = _plan_mysql_text_widenings(target_table, max_lengths)
    if not plans:
        return []

    preparer = target_connection.engine.dialect.identifier_preparer
    quoted_table_name = preparer.quote(target_table.name)
    for plan in plans:
        quoted_column_name = preparer.quote(plan["column_name"])
        nullable_sql = "NULL" if plan["nullable"] else "NOT NULL"
        ddl = (
            f"ALTER TABLE {quoted_table_name} "
            f"MODIFY COLUMN {quoted_column_name} {plan['target_type']} {nullable_sql}"
        )
        logger.warn(
            f"MySQL 目標欄位 {target_table.name}.{plan['column_name']} "
            f"容量不足（{plan['current_capacity']} bytes < {plan['required_bytes']} bytes），"
            f"自動升級為 {plan['target_type']}"
        )
        target_connection.exec_driver_sql(ddl)
    return plans


def _ordered_select(table) -> Any:
    query = table.select()
    primary_keys = list(table.primary_key.columns)
    if primary_keys:
        query = query.order_by(*primary_keys)
    return query


def _self_referential_fk_specs(*tables) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    specs: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()

    for table in tables:
        primary_key_names = tuple(column.name for column in table.primary_key.columns)
        for foreign_key_constraint in table.foreign_key_constraints:
            if foreign_key_constraint.referred_table is not table:
                continue
            constrained_columns = tuple(column.name for column in foreign_key_constraint.columns)
            referred_columns = tuple(element.column.name for element in foreign_key_constraint.elements)
            if referred_columns != primary_key_names:
                continue
            spec = (constrained_columns, referred_columns)
            if spec in seen:
                continue
            seen.add(spec)
            specs.append(spec)

    return specs


def _sort_rows_for_self_references(
    rows: list[Any],
    primary_key_names: tuple[str, ...],
    self_reference_specs: list[tuple[tuple[str, ...], tuple[str, ...]]],
) -> list[Any]:
    if not rows or not self_reference_specs:
        return rows

    rows_by_key = {
        tuple(row._mapping[column_name] for column_name in primary_key_names): row
        for row in rows
    }
    dependency_map: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
    reverse_map: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {
        row_key: set() for row_key in rows_by_key
    }

    for row_key, row in rows_by_key.items():
        dependencies: set[tuple[Any, ...]] = set()
        for constrained_columns, _referred_columns in self_reference_specs:
            dependency_key = tuple(row._mapping[column_name] for column_name in constrained_columns)
            if any(value is None for value in dependency_key):
                continue
            if dependency_key == row_key:
                continue
            if dependency_key in rows_by_key:
                dependencies.add(dependency_key)
        dependency_map[row_key] = dependencies
        for dependency_key in dependencies:
            reverse_map[dependency_key].add(row_key)

    ready = deque(sorted(row_key for row_key, dependencies in dependency_map.items() if not dependencies))
    ordered_keys: list[tuple[Any, ...]] = []
    remaining = {row_key: set(dependencies) for row_key, dependencies in dependency_map.items()}

    while ready:
        current = ready.popleft()
        ordered_keys.append(current)
        for dependant in sorted(reverse_map[current]):
            remaining[dependant].discard(current)
            if not remaining[dependant]:
                ready.append(dependant)

    if len(ordered_keys) == len(rows):
        return [rows_by_key[row_key] for row_key in ordered_keys]

    cyclic_keys = sorted(set(rows_by_key) - set(ordered_keys))
    raise RuntimeError(
        "偵測到同表自參照循環依賴，請改用 --disable-constraints 或先清理資料。"
        f" rows={cyclic_keys[:20]}"
    )


def _build_test_case_repair_context(target_connection: Connection) -> dict[str, Any]:
    section_to_set: dict[int, int] = {}
    for row in target_connection.exec_driver_sql(
        "SELECT id, test_case_set_id FROM test_case_sections"
    ):
        section_to_set[int(row[0])] = int(row[1])

    default_by_team: dict[int, dict[str, int | None]] = {}
    for row in target_connection.exec_driver_sql(
        """
        SELECT s.team_id, s.id AS set_id, sec.id AS section_id
        FROM test_case_sets s
        LEFT JOIN test_case_sections sec
          ON sec.test_case_set_id = s.id
         AND sec.name = 'Unassigned'
        WHERE s.is_default = 1
        """
    ):
        default_by_team[int(row[0])] = {
            "set_id": int(row[1]),
            "section_id": int(row[2]) if row[2] is not None else None,
        }

    return {
        "section_to_set": section_to_set,
        "default_by_team": default_by_team,
    }


def _repair_test_cases_payload(
    payload: list[dict[str, Any]],
    target_connection: Connection,
    context_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    repair_context = context_cache.get("test_cases")
    if repair_context is None:
        repair_context = _build_test_case_repair_context(target_connection)
        context_cache["test_cases"] = repair_context

    repaired_missing_set = 0
    repaired_missing_section = 0
    for row in payload:
        if row.get("test_case_set_id") is not None:
            continue

        section_id = row.get("test_case_section_id")
        if section_id is not None:
            derived_set_id = repair_context["section_to_set"].get(int(section_id))
            if derived_set_id is None:
                raise RuntimeError(
                    "test_cases.test_case_set_id 缺值，但無法從 test_case_section_id "
                    f"{section_id} 反推出對應 set。"
                )
            row["test_case_set_id"] = derived_set_id
            repaired_missing_set += 1
            continue

        team_id = row.get("team_id")
        if team_id is None:
            raise RuntimeError("test_cases 缺少 team_id，無法自動修補 test_case_set_id")
        default_entry = repair_context["default_by_team"].get(int(team_id))
        if not default_entry:
            raise RuntimeError(
                f"team_id={team_id} 找不到 default test case set，無法修補 test_cases.test_case_set_id"
            )
        row["test_case_set_id"] = default_entry["set_id"]
        repaired_missing_set += 1
        if row.get("test_case_section_id") is None and default_entry.get("section_id") is not None:
            row["test_case_section_id"] = default_entry["section_id"]
            repaired_missing_section += 1

    return payload, {
        "repaired_missing_set": repaired_missing_set,
        "repaired_missing_section": repaired_missing_section,
    }


def _load_primary_key_values(
    target_connection: Connection,
    table_name: str,
    primary_key_column_names: tuple[str, ...],
    context_cache: dict[str, Any],
) -> set[tuple[Any, ...]]:
    cache_key = ("pk_values", table_name, primary_key_column_names)
    if cache_key in context_cache:
        return context_cache[cache_key]

    quoted_table = target_connection.engine.dialect.identifier_preparer.quote(table_name)
    quoted_columns = ", ".join(
        target_connection.engine.dialect.identifier_preparer.quote(name)
        for name in primary_key_column_names
    )
    rows = target_connection.exec_driver_sql(
        f"SELECT {quoted_columns} FROM {quoted_table}"
    ).fetchall()
    values = {tuple(row) for row in rows}
    context_cache[cache_key] = values
    return values


def _filter_test_run_item_result_history_payload(
    payload: list[dict[str, Any]],
    target_connection: Connection,
    context_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    existing_item_ids = _load_primary_key_values(
        target_connection,
        "test_run_items",
        ("id",),
        context_cache,
    )
    filtered_payload: list[dict[str, Any]] = []
    skipped_orphan_item_refs = 0

    for row in payload:
        item_id = row.get("item_id")
        if item_id is not None and (item_id,) not in existing_item_ids:
            skipped_orphan_item_refs += 1
            continue
        filtered_payload.append(row)

    return filtered_payload, {
        "skipped_orphan_item_refs": skipped_orphan_item_refs,
    }


def _dedup_users_payload_case_insensitive(
    payload: list[dict[str, Any]],
    context_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Deduplicate users by case-insensitive username, keeping the most complete record.

    SQLite allows 'nikki' and 'Nikki' as separate rows, but MySQL's unique index
    is case-insensitive by default, causing duplicate key errors.

    Completeness score: lark_user_id present (+3), is_verified (+2), last_login_at (+1),
    more recent updated_at as tiebreaker.

    Dropped user IDs are stored in context_cache["dropped_user_ids"] so downstream
    tables referencing users.id can filter out orphan rows.
    """

    def _completeness(row: dict[str, Any]) -> tuple:
        score = 0
        if row.get("lark_user_id"):
            score += 3
        if row.get("is_verified"):
            score += 2
        if row.get("last_login_at"):
            score += 1
        updated = row.get("updated_at") or row.get("created_at")
        return (score, updated or "")

    seen: dict[str, dict[str, Any]] = {}  # username_lower → best row
    losers: dict[str, dict[str, Any]] = {}  # username_lower → dropped row
    duplicates_dropped = 0
    for row in payload:
        username_lower = (row.get("username") or "").strip().lower()
        if not username_lower:
            continue
        if username_lower in seen:
            existing = seen[username_lower]
            if _completeness(row) > _completeness(existing):
                losers[username_lower] = existing
                seen[username_lower] = row
            else:
                losers[username_lower] = row
            duplicates_dropped += 1
        else:
            seen[username_lower] = row

    dropped_ids: set[int] = set()
    for loser_row in losers.values():
        uid = loser_row.get("id")
        if uid is not None:
            dropped_ids.add(int(uid))

    context_cache["dropped_user_ids"] = dropped_ids

    deduped = list(seen.values())
    return deduped, {"case_insensitive_username_dedup": duplicates_dropped}


def _filter_orphan_user_refs(
    payload: list[dict[str, Any]],
    context_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter out rows whose user_id was dropped during users dedup."""
    dropped_ids: set[int] = context_cache.get("dropped_user_ids") or set()
    if not dropped_ids:
        return payload, {}
    filtered = []
    skipped = 0
    for row in payload:
        uid = row.get("user_id")
        if uid is not None and int(uid) in dropped_ids:
            skipped += 1
            continue
        filtered.append(row)
    return filtered, {"skipped_dropped_user_refs": skipped}


# Tables that have a user_id FK referencing users.id
_TABLES_WITH_USER_FK = frozenset({
    "active_sessions",
    "user_team_permissions",
    "ai_tc_helper_sessions",
})


def repair_payload_for_target(
    table_name: str,
    payload: list[dict[str, Any]],
    target_connection: Connection,
    context_cache: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if table_name == "users":
        return _dedup_users_payload_case_insensitive(payload, context_cache)
    if table_name in _TABLES_WITH_USER_FK:
        return _filter_orphan_user_refs(payload, context_cache)
    if table_name == "test_cases":
        return _repair_test_cases_payload(payload, target_connection, context_cache)
    if table_name == "test_run_item_result_history":
        return _filter_test_run_item_result_history_payload(
            payload,
            target_connection,
            context_cache,
        )
    return payload, {}


def copy_table_data(
    source_connection: Connection,
    target_connection: Connection,
    source_table,
    target_table,
    *,
    chunk_size: int,
    logger: Logger | None = None,
    shared_context: dict[str, Any] | None = None,
) -> int:
    transferable_columns = [column.name for column in target_table.columns if column.name in source_table.c]
    if not transferable_columns:
        return 0

    repair_totals: dict[str, int] = {}
    context_cache: dict[str, Any] = shared_context if shared_context is not None else {}

    def _apply_repairs(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        repaired_payload, repair_counts = repair_payload_for_target(
            target_table.name,
            payload,
            target_connection,
            context_cache,
        )
        for key, value in repair_counts.items():
            repair_totals[key] = repair_totals.get(key, 0) + int(value or 0)
        return repaired_payload

    self_reference_specs = _self_referential_fk_specs(source_table, target_table)
    if self_reference_specs:
        primary_key_names = tuple(column.name for column in source_table.primary_key.columns)
        rows = source_connection.execute(_ordered_select(source_table)).fetchall()
        ordered_rows = _sort_rows_for_self_references(rows, primary_key_names, self_reference_specs)
        copied_rows = 0
        for offset in range(0, len(ordered_rows), chunk_size):
            batch = ordered_rows[offset : offset + chunk_size]
            payload = _apply_repairs([
                {column_name: row._mapping[column_name] for column_name in transferable_columns}
                for row in batch
            ])
            if payload:
                target_connection.execute(target_table.insert(), payload)
                copied_rows += len(payload)
        if logger and repair_totals:
            logger.warn(
                f"table {target_table.name} 自動修補資料："
                + ", ".join(f"{key}={value}" for key, value in sorted(repair_totals.items()) if value)
            )
        return copied_rows

    result = source_connection.execution_options(stream_results=True).execute(_ordered_select(source_table))
    copied_rows = 0
    while True:
        rows = result.fetchmany(chunk_size)
        if not rows:
            break
        payload = _apply_repairs([
            {column_name: row._mapping[column_name] for column_name in transferable_columns}
            for row in rows
        ])
        target_connection.execute(target_table.insert(), payload)
        copied_rows += len(payload)
    if logger and repair_totals:
        logger.warn(
            f"table {target_table.name} 自動修補資料："
            + ", ".join(f"{key}={value}" for key, value in sorted(repair_totals.items()) if value)
        )
    return copied_rows


def reset_target_data(target_connection: Connection, target_metadata: MetaData, ordered_tables: list[str]) -> None:
    for table_name in reversed(ordered_tables):
        target_connection.execute(target_metadata.tables[table_name].delete())


@contextmanager
def constraint_override(connection: Connection) -> Iterator[None]:
    dialect_name = connection.engine.dialect.name
    if dialect_name == "sqlite":
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            yield
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        return

    if dialect_name == "mysql":
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        try:
            yield
        finally:
            connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
        return

    if dialect_name == "postgresql":
        connection.exec_driver_sql("SET session_replication_role = replica")
        try:
            yield
        finally:
            connection.exec_driver_sql("SET session_replication_role = origin")
        return

    yield


def run_job(job: TransferJob, logger: Logger) -> dict[str, Any]:
    logger.info(f"開始執行 job={job.name}")
    source_engine = build_engine(job.source_url)
    target_engine = build_engine(job.target_url)

    try:
        source_metadata, selected_tables = reflect_selected_metadata(
            source_engine,
            include_tables=job.include_tables,
            exclude_tables=job.exclude_tables,
        )
        if not selected_tables:
            raise RuntimeError(f"job={job.name} 沒有可搬移的 tables")

        if job.create_target_schema:
            logger.info(f"job={job.name} 先建立目標缺少的 schema")
            source_metadata.create_all(target_engine)

        target_metadata, _ = reflect_selected_metadata(
            target_engine,
            include_tables=selected_tables,
            exclude_tables=[],
        )
        warnings = validate_target_tables(source_metadata, target_metadata, selected_tables)
        for message in warnings:
            logger.warn(message)

        ordered_tables = resolve_table_order(
            source_metadata,
            target_metadata,
            selected_tables,
            allow_cycles=job.disable_constraints,
        )
        summary = {
            "job": job.name,
            "source_url": job.source_url,
            "target_url": job.target_url,
            "tables": [],
            "reset_target": job.reset_target,
            "create_target_schema": job.create_target_schema,
            "disable_constraints": job.disable_constraints,
            "dry_run": job.dry_run,
        }

        if job.dry_run:
            summary["table_order"] = ordered_tables
            summary["status"] = "dry_run"
            return summary

        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            guard = constraint_override(target_connection) if job.disable_constraints else nullcontext()
            with guard:
                if job.reset_target:
                    logger.info(f"job={job.name} 清空目標資料")
                    reset_target_data(target_connection, target_metadata, ordered_tables)

                shared_context: dict[str, Any] = {}
                for table_name in ordered_tables:
                    source_table = source_metadata.tables[table_name]
                    target_table = target_metadata.tables[table_name]
                    widen_plans = ensure_mysql_text_capacity(
                        source_connection,
                        target_connection,
                        source_table,
                        target_table,
                        logger,
                    )
                    if widen_plans:
                        summary.setdefault("schema_adjustments", []).append(
                            {
                                "table": table_name,
                                "actions": widen_plans,
                            }
                        )
                    copied_rows = copy_table_data(
                        source_connection,
                        target_connection,
                        source_table,
                        target_table,
                        chunk_size=job.chunk_size,
                        logger=logger,
                        shared_context=shared_context,
                    )
                    logger.info(f"job={job.name} 搬移 {table_name}: {copied_rows} rows")
                    summary["tables"].append(
                        {
                            "table": table_name,
                            "rows": copied_rows,
                        }
                    )

        summary["status"] = "completed"
        return summary
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = Logger(verbose=args.verbose, quiet=args.quiet)

    try:
        jobs = resolve_jobs(args)
        summaries = [run_job(job, logger) for job in jobs]
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            logger.error(str(exc))
        return 1

    if args.json:
        print(json.dumps({"status": "ok", "jobs": summaries}, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(json.dumps({"status": "ok", "jobs": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
