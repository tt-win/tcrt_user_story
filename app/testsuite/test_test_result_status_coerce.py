"""coerce_test_result_status maps assistant aliases to canonical DB enums."""

from __future__ import annotations

import pytest

from app.models.lark_types import TestResultStatus, coerce_test_result_status


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Passed", TestResultStatus.PASSED),
        ("pass", TestResultStatus.PASSED),
        ("PASS", TestResultStatus.PASSED),
        ("fail", TestResultStatus.FAILED),
        ("Failed", TestResultStatus.FAILED),
        ("blocked", TestResultStatus.NOT_AVAILABLE),
        ("skipped", TestResultStatus.SKIP),
        ("Skip", TestResultStatus.SKIP),
        (TestResultStatus.RETEST, TestResultStatus.RETEST),
    ],
)
def test_coerce_test_result_aliases(raw, expected):
    assert coerce_test_result_status(raw) == expected


def test_coerce_rejects_unknown():
    with pytest.raises(ValueError, match="invalid test_result"):
        coerce_test_result_status("maybe")
