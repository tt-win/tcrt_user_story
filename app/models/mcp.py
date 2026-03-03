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
