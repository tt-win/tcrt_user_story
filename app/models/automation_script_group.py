from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.automation_run import AutomationRunResponse
from app.models.database_models import AutomationScriptFormat, AutomationScriptGroupJobType


class AutomationScriptGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    script_ids: list[int] = Field(..., min_length=1)


class AutomationScriptGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    script_ids: Optional[list[int]] = Field(None, min_length=1)


class AutomationScriptGroupRunRequest(BaseModel):
    branch: Optional[str] = Field(None, min_length=1, max_length=200)
    runner_label: Optional[str] = Field(None, max_length=100)
    inputs: dict[str, str] = Field(default_factory=dict)


class AutomationScriptGroupScriptResponse(BaseModel):
    id: int
    name: str
    script_format: AutomationScriptFormat
    ref_path: str
    ref_branch: str

    model_config = ConfigDict(use_enum_values=True)


class AutomationScriptGroupResponse(BaseModel):
    id: int
    team_id: int
    name: str
    description: Optional[str] = None
    script_ids: list[int] = Field(default_factory=list)
    script_paths: list[str] = Field(default_factory=list)
    script_count: int = 0
    ci_job_name: Optional[str] = None
    ci_job_type: Optional[AutomationScriptGroupJobType] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    scripts: list[AutomationScriptGroupScriptResponse] = Field(default_factory=list)
    # Non-fatal, user-facing notices from the last write (e.g. a rename that
    # discarded the suite's old Allure report). Empty on reads / no-op updates.
    warnings: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AutomationScriptGroupListResponse(BaseModel):
    items: list[AutomationScriptGroupResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


class AutomationScriptGroupBatchProposal(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    script_paths: list[str] = Field(..., min_length=1)
    # Repo (owner/repo) the proposed scripts belong to. Lets path resolution
    # disambiguate when several repos share the same ref_path. "" = any/legacy.
    ref_repo: str = ""


class AutomationScriptGroupBatchCreateRequest(BaseModel):
    proposals: list[AutomationScriptGroupBatchProposal] = Field(..., min_length=1)


class AutomationScriptGroupBatchCreateItem(BaseModel):
    name: str
    status: str  # "created" | "skipped" | "failed"
    group_id: Optional[int] = None
    message: Optional[str] = None


class AutomationScriptGroupBatchCreateResponse(BaseModel):
    created: int
    skipped: int
    failed: int
    items: list[AutomationScriptGroupBatchCreateItem]
