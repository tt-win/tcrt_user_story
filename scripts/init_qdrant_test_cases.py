#!/usr/bin/env python3
"""Initialize the Qdrant test-case collection from the project ``.env``.

This script is a guarded wrapper around the canonical knowledge backfill CLI.
It parses ``<project-root>/.env`` with python-dotenv, validates and displays only
non-secret targets, then starts the existing ``test_cases`` backfill in a child
process. It never sources the dotenv file as shell code.

Usage:
    uv run python scripts/init_qdrant_test_cases.py --dry-run
    uv run python scripts/init_qdrant_test_cases.py --yes
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"

REQUIRED_ENV_NAMES = (
    "DATABASE_URL",
    "KNOWLEDGE_GRAPH_ENABLED",
    "QDRANT_URL",
    "QDRANT_COLLECTION_TEST_CASES",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
)

POSITIVE_INTEGER_ENV_NAMES = (
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_BATCH_SIZE",
    "EMBEDDING_CONCURRENCY",
    "KNOWLEDGE_BACKFILL_BATCH_SIZE",
)


class InitConfigError(ValueError):
    """Raised when the project dotenv file is missing required safe inputs."""


@dataclass(frozen=True)
class InitSummary:
    env_path: Path
    database_target: str
    qdrant_target: str
    collection: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    backfill_batch_size: int


def _non_empty(values: Mapping[str, str], name: str) -> str:
    return values.get(name, "").strip()


def _validate_http_url(value: str, name: str) -> None:
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise InitConfigError(f"{name} 必須是有效的 http:// 或 https:// URL")


def _parse_positive_integer(values: Mapping[str, str], name: str) -> int:
    raw = _non_empty(values, name)
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise InitConfigError(f"{name} 必須是正整數") from exc
    if parsed <= 0:
        raise InitConfigError(f"{name} 必須是正整數")
    return parsed


def _redact_url(value: str) -> str:
    """Return a target-only URL without credentials, query, or fragment."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme.startswith("sqlite"):
            filename = Path(parsed.path).name or "<database>"
            return f"{parsed.scheme}:///{filename}"
        if not parsed.scheme or not parsed.hostname:
            return "<invalid-url>"
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        port = f":{parsed.port}" if parsed.port is not None else ""
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{host}{port}{path}"
    except ValueError:
        return "<invalid-url>"


def load_project_env(env_path: Path) -> tuple[dict[str, str], InitSummary]:
    """Parse and validate the exact project dotenv file without logging secrets."""
    if not env_path.is_file():
        raise InitConfigError(f"找不到專案環境檔：{env_path}")

    try:
        parsed_values = dotenv_values(env_path, interpolate=True)
    except OSError as exc:
        raise InitConfigError(f"無法讀取專案環境檔：{env_path}") from exc

    values = {
        name: value
        for name, value in parsed_values.items()
        if name is not None and value is not None
    }
    missing = [name for name in REQUIRED_ENV_NAMES if not _non_empty(values, name)]
    if missing:
        raise InitConfigError(f".env 缺少必要變數：{', '.join(missing)}")

    if _non_empty(values, "KNOWLEDGE_GRAPH_ENABLED").lower() != "true":
        raise InitConfigError("KNOWLEDGE_GRAPH_ENABLED 必須在 .env 明確設為 true")

    for name in POSITIVE_INTEGER_ENV_NAMES:
        if name in values and _non_empty(values, name):
            _parse_positive_integer(values, name)

    qdrant_url = _non_empty(values, "QDRANT_URL")
    _validate_http_url(qdrant_url, "QDRANT_URL")

    provider = _non_empty(values, "EMBEDDING_PROVIDER").lower()
    embedding_base_url = _non_empty(values, "EMBEDDING_BASE_URL")
    embedding_api_key = _non_empty(values, "EMBEDDING_API_KEY")
    if embedding_base_url:
        _validate_http_url(embedding_base_url, "EMBEDDING_BASE_URL")
    if provider == "openrouter" and not embedding_api_key:
        raise InitConfigError("EMBEDDING_PROVIDER=openrouter 時，.env 必須設定 EMBEDDING_API_KEY")
    if provider == "openai" and not embedding_base_url and not embedding_api_key:
        raise InitConfigError(
            "使用 OpenAI 官方端點時，.env 必須設定 EMBEDDING_API_KEY；"
            "無金鑰的本機服務請設定 EMBEDDING_BASE_URL"
        )
    if provider not in {"openrouter", "openai"} and not embedding_base_url:
        raise InitConfigError(
            "自訂 EMBEDDING_PROVIDER 必須在 .env 同時設定 EMBEDDING_BASE_URL"
        )

    dimensions = _parse_positive_integer(values, "EMBEDDING_DIMENSIONS")
    backfill_batch_size = (
        _parse_positive_integer(values, "KNOWLEDGE_BACKFILL_BATCH_SIZE")
        if _non_empty(values, "KNOWLEDGE_BACKFILL_BATCH_SIZE")
        else 100
    )
    summary = InitSummary(
        env_path=env_path,
        database_target=_redact_url(_non_empty(values, "DATABASE_URL")),
        qdrant_target=_redact_url(qdrant_url),
        collection=_non_empty(values, "QDRANT_COLLECTION_TEST_CASES"),
        embedding_provider=provider,
        embedding_model=_non_empty(values, "EMBEDDING_MODEL"),
        embedding_dimensions=dimensions,
        backfill_batch_size=backfill_batch_size,
    )
    return values, summary


def print_summary(summary: InitSummary) -> None:
    print("Qdrant Test Case 初始化設定：")
    print(f"  .env: {summary.env_path}")
    print(f"  來源資料庫: {summary.database_target}（帳密已隱藏）")
    print(f"  Qdrant: {summary.qdrant_target}（帳密與 query 已隱藏）")
    print(f"  Collection: {summary.collection}")
    print(
        "  Embedding: "
        f"{summary.embedding_provider} / {summary.embedding_model} / "
        f"{summary.embedding_dimensions} 維"
    )
    print(f"  Backfill batch size: {summary.backfill_batch_size}")
    print("  動作: 建立缺少的 collection，並 upsert 全部 Test Case；不會刪除既有 points。")


def _build_child_env(values: Mapping[str, str]) -> dict[str, str]:
    child_env = dict(os.environ)
    child_env.update(values)
    child_env["PYTHONUNBUFFERED"] = "1"
    return child_env


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="從專案根目錄 .env 初始化 Qdrant Test Case 向量資料"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="只驗證並顯示去識別化設定，不連線或寫入",
    )
    mode.add_argument(
        "--yes",
        action="store_true",
        help="確認依顯示的目標執行 Qdrant backfill",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env_path: Path = PROJECT_ENV_PATH,
    run_command: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> int:
    args = _build_parser().parse_args(argv)
    try:
        env_values, summary = load_project_env(env_path)
    except InitConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return 2

    print_summary(summary)
    if args.dry_run:
        print("Dry run 完成：未連線資料庫、Embedding API 或 Qdrant。")
        return 0
    if not args.yes:
        print(
            "已停止：先用 --dry-run 檢查目標，確認後再加上 --yes 執行。",
            file=sys.stderr,
        )
        return 2

    command = [
        sys.executable,
        "-m",
        "app.services.knowledge",
        "backfill",
        "--entity",
        "test_cases",
    ]
    completed = run_command(
        command,
        cwd=PROJECT_ROOT,
        env=_build_child_env(env_values),
        check=False,
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
