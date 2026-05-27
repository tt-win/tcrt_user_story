from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.database_models import AutomationScriptLinkType


class AutomationScriptLinkCreate(BaseModel):
    test_case_id: int
    link_type: AutomationScriptLinkType = AutomationScriptLinkType.COVERS
    note: Optional[str] = None


class AutomationScriptLinkUpdate(BaseModel):
    link_type: Optional[AutomationScriptLinkType] = None
    note: Optional[str] = None


class AutomationScriptLinkResponse(BaseModel):
    id: int
    team_id: int
    automation_script_id: int
    test_case_id: int
    link_type: AutomationScriptLinkType
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class LinkedAutomationSummary(BaseModel):
    script_id: int
    name: str
    script_format: str
    link_type: AutomationScriptLinkType
    # Marker-sync / ai-suggest:<id> / numeric user id (or null for legacy rows).
    # The case detail Automation panel uses this to render a link source badge.
    created_by: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_at: Optional[datetime] = None
    last_run_url: Optional[str] = None
    report_url: Optional[str] = None

    model_config = ConfigDict(use_enum_values=True)
