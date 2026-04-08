from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.qa_ai_helper_metrics import (
    compute_adoption_rate,
    summarize_seed_adoption,
    summarize_testcase_adoption,
)


def test_compute_adoption_rate_returns_zero_when_generated_count_is_zero() -> None:
    assert compute_adoption_rate(3, 0) == 0.0


def test_summarize_seed_adoption_uses_included_seed_count_over_generated_seed_count() -> None:
    summary = summarize_seed_adoption(
        [
            {"included_for_testcase_generation": True},
            {"included_for_testcase_generation": False},
            {"included_for_testcase_generation": True},
        ]
    )

    assert summary == {
        "generated_seed_count": 3,
        "included_seed_count": 2,
        "seed_adoption_rate": 0.6667,
    }


def test_summarize_testcase_adoption_uses_selected_for_commit_count() -> None:
    summary = summarize_testcase_adoption(
        [
            {"selected_for_commit": True},
            {"selected_for_commit": False},
            {"selected_for_commit": False},
            {"selected_for_commit": True},
        ]
    )

    assert summary == {
        "generated_testcase_count": 4,
        "selected_for_commit_count": 2,
        "testcase_adoption_rate": 0.5,
    }
