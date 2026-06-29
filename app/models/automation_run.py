from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.database_models import AutomationRunStatus, AutomationRunTrigger


class AutomationRunCreate(BaseModel):
    workflow_id: Optional[str] = Field(None, max_length=200)
    branch: Optional[str] = Field(None, max_length=200)
    runner_label: Optional[str] = Field(None, max_length=100)
    inputs: dict[str, str] = Field(default_factory=dict)


class AutomationRunResponse(BaseModel):
    id: int
    team_id: int
    automation_script_id: Optional[int] = None
    script_group_id: Optional[int] = None
    script_group_name: Optional[str] = None
    test_run_set_id: Optional[int] = None
    provider_id: int
    external_run_id: Optional[str] = None
    external_run_url: Optional[str] = None
    status: AutomationRunStatus
    triggered_by: AutomationRunTrigger
    triggered_by_user_id: Optional[str] = None
    triggered_by_webhook_id: Optional[int] = None
    tcrt_correlation_id: str
    ci_correlation_id: Optional[str] = None
    workflow_id: str
    branch: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    runner_label: Optional[str] = None
    environment: Optional[str] = None
    report_url: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error_summary: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AutomationRunListResponse(BaseModel):
    items: list[AutomationRunResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None
