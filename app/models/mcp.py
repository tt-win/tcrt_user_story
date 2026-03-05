"""MCP 專用資料模型。"""

from __future__ import annotations

from datetime import datetime
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
