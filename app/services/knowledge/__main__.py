"""CLI entry point for knowledge graph backfill.

Usage:
    uv run python -m app.services.knowledge backfill --entity test_cases
    uv run python -m app.services.knowledge backfill --entity usm_nodes
    uv run python -m app.services.knowledge backfill --entity all

資料來源：app.services.knowledge.data_sources.fetch_test_cases / fetch_usm_nodes。
兩者皆走 AccessBoundary，不在 CLI 內直接開 session。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.db_access.main import get_main_access_boundary
from app.db_access.usm import get_usm_access_boundary
from app.services.knowledge import (
    get_write_service,
    is_knowledge_graph_enabled,
)
from app.services.knowledge.data_sources import (
    fetch_test_cases,
    fetch_usm_nodes,
)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def run_backfill(entity: str) -> int:
    if not is_knowledge_graph_enabled():
        print(
            "Knowledge graph is not enabled. Set KNOWLEDGE_GRAPH_ENABLED=true.",
            file=sys.stderr,
        )
        return 1

    write_svc = get_write_service()
    batch_size = write_svc._config.backfill_batch_size
    rc = 0

    if entity in ("test_cases", "all"):
        print(f"Backfilling test_cases (batch_size={batch_size})...")
        boundary = get_main_access_boundary()
        progress = await write_svc.backfill_test_cases(
            fetch_test_cases(boundary, batch_size=batch_size)
        )
        print(
            f"  Done: {progress.processed_count} processed, status={progress.status}"
        )
        if progress.status == "failed":
            rc = 2

    if entity in ("usm_nodes", "all"):
        print(f"Backfilling usm_nodes (batch_size={batch_size})...")
        boundary = get_usm_access_boundary()
        progress = await write_svc.backfill_usm_nodes(
            fetch_usm_nodes(boundary, batch_size=batch_size)
        )
        print(
            f"  Done: {progress.processed_count} processed, status={progress.status}"
        )
        if progress.status == "failed":
            rc = 2

    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Knowledge graph backfill CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    bf = sub.add_parser("backfill", help="Run initial bulk load")
    bf.add_argument(
        "--entity",
        choices=["test_cases", "usm_nodes", "all"],
        default="all",
        help="Entity type to backfill (default: all)",
    )

    args = parser.parse_args(argv)
    _setup_logging()

    if args.command == "backfill":
        return asyncio.run(run_backfill(args.entity))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
