"""Adoption metric helpers for QA AI Helper V3."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict


def compute_adoption_rate(adopted_count: int, generated_count: int) -> float:
    generated = max(int(generated_count or 0), 0)
    adopted = max(int(adopted_count or 0), 0)
    if generated <= 0:
        return 0.0
    return round(adopted / generated, 4)


def _read_flag(item: Any, key: str) -> bool:
    if isinstance(item, Mapping):
        return bool(item.get(key))
    return bool(getattr(item, key, False))


def summarize_seed_adoption(seed_items: Iterable[Any]) -> Dict[str, Any]:
    items = list(seed_items)
    generated_seed_count = len(items)
    included_seed_count = sum(
        1 for item in items if _read_flag(item, "included_for_testcase_generation")
    )
    return {
        "generated_seed_count": generated_seed_count,
        "included_seed_count": included_seed_count,
        "seed_adoption_rate": compute_adoption_rate(
            included_seed_count,
            generated_seed_count,
        ),
    }


def summarize_testcase_adoption(testcase_drafts: Iterable[Any]) -> Dict[str, Any]:
    items = list(testcase_drafts)
    generated_testcase_count = len(items)
    selected_for_commit_count = sum(
        1 for item in items if _read_flag(item, "selected_for_commit")
    )
    return {
        "generated_testcase_count": generated_testcase_count,
        "selected_for_commit_count": selected_for_commit_count,
        "testcase_adoption_rate": compute_adoption_rate(
            selected_for_commit_count,
            generated_testcase_count,
        ),
    }
