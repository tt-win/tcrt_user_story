#!/usr/bin/env python3
"""Lightweight benchmark for rewritten QA AI Helper deterministic planning."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.services.qa_ai_helper_planner import QAAIHelperPlanner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark rewritten QA AI Helper planning flow")
    parser.add_argument(
        "--payload",
        type=Path,
        help="JSON payload path containing canonical content. If omitted, built-in sample is used.",
    )
    parser.add_argument("--iterations", type=int, default=10, help="Benchmark iteration count")
    parser.add_argument("--ticket-key", default="TCG-BENCH", help="Synthetic ticket key")
    return parser.parse_args()


def default_payload() -> dict[str, Any]:
    return {
        "userStoryNarrative": (
            "As a QA user\n"
            "I want to benchmark deterministic planning\n"
            "So that I can estimate local runtime"
        ),
        "criteria": (
            "- Detail page opens in a new tab\n"
            "- Current status is displayed\n"
            "- Date filter supports today, yesterday, and last 7 days"
        ),
        "technicalSpecifications": (
            "- API path: /detail/view\n"
            "- Date format: yyyy-MM-dd\n"
            "- Pagination default: 10"
        ),
        "acceptanceCriteria": (
            "Scenario 1: Open detail page\n"
            "Given the user is on the list page\n"
            "When the user clicks the detail name\n"
            "Then the detail page opens in a new tab\n"
            "And the tab title matches the entity name\n\n"
            "Scenario 2: Display status and filters\n"
            "Given the user is on the detail page\n"
            "When the page is loaded\n"
            "Then the current status is displayed\n"
            "And the updated date uses yyyy-MM-dd\n"
            "And the date filter supports today"
        ),
        "assumptions": [],
        "unknowns": [],
    }


def load_payload(path: Path | None) -> dict[str, Any]:
    if path is None:
        return default_payload()
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    payload = load_payload(args.payload)
    planner = QAAIHelperPlanner()
    durations_ms: list[float] = []
    result_summary: dict[str, Any] | None = None

    for _ in range(max(args.iterations, 1)):
        start = time.perf_counter()
        result_summary = planner.build_plan(
            ticket_key=args.ticket_key,
            canonical_revision_id=1,
            canonical_language="zh-TW",
            content=payload,
            counter_settings={"middle": "010", "tail": "010"},
        )
        durations_ms.append((time.perf_counter() - start) * 1000)

    sections = len((result_summary or {}).get("sections", []))
    generation_items = len((result_summary or {}).get("generation_items", []))
    print(
        json.dumps(
            {
                "iterations": len(durations_ms),
                "min_ms": round(min(durations_ms), 2),
                "avg_ms": round(statistics.mean(durations_ms), 2),
                "max_ms": round(max(durations_ms), 2),
                "sections": sections,
                "generation_items": generation_items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
