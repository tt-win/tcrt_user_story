from __future__ import annotations

from datetime import date

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


class AutomationCoverageCaseRow(AutomationCoverageCaseItem):
    """One case in the paginated explorer: coverage status + linked scripts."""

    status: str  # "primary" | "covers" | "uncovered"
    links: list[AutomationCoverageLinkItem] = []


class AutomationCoverageCasesPage(BaseModel):
    items: list[AutomationCoverageCaseRow]
    total: int
    skip: int
    limit: int
    has_next: bool


class AutomationCoverageGroupItem(BaseModel):
    group: str
    total: int
    covered: int
    primary: int


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
    by_group: list[AutomationCoverageGroupItem]
    by_format: dict[str, int]
    trend: list[AutomationCoverageTrendPoint]

    model_config = ConfigDict(from_attributes=True)
