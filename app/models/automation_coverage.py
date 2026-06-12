from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AutomationCoverageCaseItem(BaseModel):
    test_case_id: int
    test_case_number: str
    title: str


class AutomationCoverageLinkItem(BaseModel):
    script_id: int
    script_name: str
    ref_repo: str = ""
    ref_path: str
    link_type: str


class AutomationCoverageCoveredCaseItem(AutomationCoverageCaseItem):
    links: list[AutomationCoverageLinkItem]


class AutomationCoverageGroupItem(BaseModel):
    group: str
    total: int
    covered: int
    primary: int


class AutomationCoverageStaleScriptItem(BaseModel):
    script_id: int
    name: str
    script_format: str
    ref_path: str
    last_run_at: Optional[datetime] = None
    days_since_last_run: Optional[int] = None


class AutomationCoverageTrendPoint(BaseModel):
    date: date
    with_primary_link: int
    with_any_link: int
    uncovered_count: int
    coverage_rate: float


class AutomationCoverageResponse(BaseModel):
    total_test_cases: int
    with_primary_link: int
    with_covers_link: int
    with_any_link: int
    uncovered_count: int
    uncovered_sample: list[AutomationCoverageCaseItem]
    covered_cases: list[AutomationCoverageCoveredCaseItem]
    by_group: list[AutomationCoverageGroupItem]
    stale_scripts: list[AutomationCoverageStaleScriptItem]
    by_format: dict[str, int]
    trend: list[AutomationCoverageTrendPoint]

    model_config = ConfigDict(from_attributes=True)
