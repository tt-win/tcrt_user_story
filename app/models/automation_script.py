from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.database_models import AutomationScriptFormat


class AutomationScriptBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    script_format: AutomationScriptFormat = AutomationScriptFormat.OTHER
    ref_path: str = Field(..., min_length=1, max_length=500)
    ref_branch: str = Field(..., min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)
    preferred_runner_label: Optional[str] = Field(None, max_length=100)


class AutomationScriptCreate(AutomationScriptBase):
    provider_id: int
    cached_content: Optional[str] = None
    cached_content_etag: Optional[str] = None


class AutomationScriptUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    script_format: Optional[AutomationScriptFormat] = None
    tags: Optional[list[str]] = None
    preferred_runner_label: Optional[str] = Field(None, max_length=100)


class AutomationScriptResponse(AutomationScriptBase):
    id: int
    team_id: int
    provider_id: int
    ref_repo: str = ""
    cached_content: Optional[str] = None
    cached_content_etag: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    linked_test_case_count: int = 0
    # Per-test entries + tcrt markers, parsed from cached_content on read.
    test_entries: list[dict[str, Any]] = Field(default_factory=list)
    marker_warnings: list[dict[str, Any]] = Field(default_factory=list)
    # Per-script declared variables (module-level TCRT_VARS) + parse warnings,
    # parsed from cached_content on read. Drives the Script view "Configure
    # variables" entry. See manage-automation-environment-configs.
    declared_vars: list[dict[str, Any]] = Field(default_factory=list)
    var_warnings: list[dict[str, Any]] = Field(default_factory=list)
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AutomationScriptListResponse(BaseModel):
    items: list[AutomationScriptResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


class AutomationScriptSyncRequest(BaseModel):
    provider_id: Optional[int] = None
    branch: Optional[str] = Field(None, min_length=1, max_length=200)


class RepoContractResponse(BaseModel):
    manifest_path: str
    manifest_found: bool
    manifest_etag: Optional[str] = None
    contract_status: str
    framework: Optional[str] = None
    effective_tests_path: str
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    support_paths: dict[str, str] = Field(default_factory=dict)
    missing_paths: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)


class AutomationScriptSyncResponse(BaseModel):
    provider_id: int
    branch: str
    scanned_path: str
    added: int
    updated: int
    removed: int
    total: int
    repo_contract: RepoContractResponse


class AILinkSuggestRequest(BaseModel):
    """Request body for `POST .../{script_id}/ai-link-suggestions`."""
    test_name: str = Field(..., min_length=1, max_length=200)
    limit: int = Field(5, ge=1, le=10)


class AILinkSuggestionItem(BaseModel):
    test_case_id: int
    test_case_number: str
    title: str
    confidence: float
    rationale: str


class AILinkSuggestResponse(BaseModel):
    suggestions: list[AILinkSuggestionItem]
    model: str
    prompt_version: str
    error_summary: Optional[str] = None


class AutomationScriptMetadata(BaseModel):
    tags: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
