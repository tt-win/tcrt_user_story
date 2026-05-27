from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.database_models import AutomationSmartScanStatus


class AutomationSmartScanStartResponse(BaseModel):
    scan_run_id: int
    status: AutomationSmartScanStatus
    status_url: str

    model_config = ConfigDict(use_enum_values=True)


class AutomationSmartScanRunResponse(BaseModel):
    id: int
    team_id: int
    provider_id: int
    status: AutomationSmartScanStatus
    scan_config_hash: str
    progress: dict[str, Any] = Field(default_factory=dict)
    result: Optional[dict[str, Any]] = None
    error_summary: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)
