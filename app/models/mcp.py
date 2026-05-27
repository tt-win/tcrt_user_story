"""MCP 專用資料模型。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPMachinePrincipal(BaseModel):
    """經 machine token 驗證後的機器身分。"""

    credential_id: int
    credential_name: str
    permission: str = Field("mcp_read")
    allow_all_teams: bool = False
    team_scope_ids: List[int] = Field(default_factory=list)

    def can_access_team(self, team_id: int) -> bool:
        if self.allow_all_teams:
            return True
        return team_id in self.team_scope_ids


class MCPTeamItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    status: str
    test_case_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    is_lark_configured: bool = False
    is_jira_configured: bool = False


class MCPTeamsResponse(BaseModel):
    total: int
    items: List[MCPTeamItem] = Field(default_factory=list)


class MCPTestCaseSetItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_default: bool = False
    test_case_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPPageMeta(BaseModel):
    skip: int
    limit: int
    total: int
    has_next: bool


class MCPTeamTestCasesResponse(BaseModel):
    team_id: int
    filters: Dict[str, Any]
    sets: List[MCPTestCaseSetItem] = Field(default_factory=list)
    test_cases: List[Dict[str, Any]] = Field(default_factory=list)
    page: MCPPageMeta


class MCPLinkedAutomationSummary(BaseModel):
    """Per-test-case linked automation script summary (reverse view)."""

    script_id: int
    name: str
    script_format: str
    ref_path: Optional[str] = None
    link_type: str
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_url: Optional[str] = None
    report_url: Optional[str] = None


class MCPTestCaseDetailItem(BaseModel):
    id: int
    record_id: str
    test_case_number: str
    title: str
    priority: str
    test_result: Optional[str] = None
    assignee: Optional[str] = None
    tcg: List[str] = Field(default_factory=list)
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    test_case_set_id: int
    test_case_section_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    test_results_files: List[Dict[str, Any]] = Field(default_factory=list)
    user_story_map: List[Dict[str, Any]] = Field(default_factory=list)
    parent_record: List[Dict[str, Any]] = Field(default_factory=list)
    raw_fields: Optional[Dict[str, Any]] = None
    test_data: List[Dict[str, Any]] = Field(default_factory=list)
    linked_automation_scripts: List[MCPLinkedAutomationSummary] = Field(default_factory=list)


class MCPTestCaseDetailResponse(BaseModel):
    team_id: int
    test_case: MCPTestCaseDetailItem


class MCPCrossTeamTestCaseItem(BaseModel):
    team_id: int
    team_name: str
    match_type: str
    test_case: Dict[str, Any]


class MCPTestCaseLookupResponse(BaseModel):
    filters: Dict[str, Any]
    items: List[MCPCrossTeamTestCaseItem] = Field(default_factory=list)
    page: MCPPageMeta


class MCPTestRunSetItem(BaseModel):
    id: int
    name: str
    status: str
    test_runs: List[Dict[str, Any]] = Field(default_factory=list)


class MCPAdhocRunItem(BaseModel):
    id: int
    name: str
    status: str
    total_test_cases: int = 0
    executed_cases: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPTeamTestRunsResponse(BaseModel):
    team_id: int
    filters: Dict[str, Any]
    sets: List[MCPTestRunSetItem] = Field(default_factory=list)
    unassigned: List[Dict[str, Any]] = Field(default_factory=list)
    adhoc: List[MCPAdhocRunItem] = Field(default_factory=list)
    summary: Dict[str, int]



class MCPTestCaseSectionItem(BaseModel):
    id: int
    test_case_set_id: int
    parent_section_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    level: int
    sort_order: int = 0
    test_case_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPTeamTestCaseSectionsResponse(BaseModel):
    team_id: int
    filters: Dict[str, Any]
    sections: List[MCPTestCaseSectionItem] = Field(default_factory=list)
    total: int


class MCPAutomationScriptItem(BaseModel):
    """Team-wide automation script entry for MCP listing."""

    id: int
    name: str
    script_format: str
    ref_path: str
    ref_branch: Optional[str] = None
    description: Optional[str] = None
    preferred_runner_label: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    linked_test_case_count: int = 0
    linked_test_case_numbers: List[str] = Field(default_factory=list)
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPTeamAutomationScriptsResponse(BaseModel):
    team_id: int
    items: List[MCPAutomationScriptItem] = Field(default_factory=list)
    page: MCPPageMeta


class MCPAutomationRunItem(BaseModel):
    id: int
    automation_script_id: Optional[int] = None
    script_group_id: Optional[int] = None
    workflow_id: str
    branch: str
    status: str
    triggered_by: str
    triggered_by_user_id: Optional[str] = None
    external_run_id: Optional[str] = None
    external_run_url: Optional[str] = None
    report_url: Optional[str] = None
    runner_label: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    tcrt_correlation_id: str
    error_summary: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPTeamAutomationRunsResponse(BaseModel):
    team_id: int
    items: List[MCPAutomationRunItem] = Field(default_factory=list)
    page: MCPPageMeta


class MCPAutomationCoverageSummary(BaseModel):
    total_test_cases: int
    with_primary_link: int
    with_covers_link: int
    with_any_link: int
    uncovered_count: int
    by_format: Dict[str, int] = Field(default_factory=dict)


class MCPAutomationCoverageUncoveredCase(BaseModel):
    test_case_id: int
    test_case_number: Optional[str] = None
    title: Optional[str] = None


class MCPAutomationCoverageStaleScript(BaseModel):
    script_id: int
    name: str
    script_format: Optional[str] = None
    ref_path: Optional[str] = None
    last_run_at: Optional[datetime] = None
    days_since_last_run: Optional[int] = None


class MCPAutomationCoverageTrendPoint(BaseModel):
    date: date
    with_primary_link: int
    with_any_link: int
    uncovered_count: int
    coverage_rate: float


class MCPTeamAutomationCoverageResponse(BaseModel):
    team_id: int
    summary: MCPAutomationCoverageSummary
    uncovered_sample: List[MCPAutomationCoverageUncoveredCase] = Field(default_factory=list)
    stale_scripts: List[MCPAutomationCoverageStaleScript] = Field(default_factory=list)
    trend: List[MCPAutomationCoverageTrendPoint] = Field(default_factory=list)
