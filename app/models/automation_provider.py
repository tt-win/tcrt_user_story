from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.database_models import AutomationProviderSlot


class AutomationProviderBase(BaseModel):
    provider_slot: AutomationProviderSlot = Field(..., description="Provider slot: storage, ci, or result")
    provider_type: str = Field(..., min_length=1, max_length=60)
    name: str = Field(..., min_length=1, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class AutomationProviderCreate(AutomationProviderBase):
    credentials: Optional[dict[str, Any]] = None


class AutomationProviderUpdate(BaseModel):
    provider_slot: Optional[AutomationProviderSlot] = None
    provider_type: Optional[str] = Field(None, min_length=1, max_length=60)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    config: Optional[dict[str, Any]] = None
    credentials: Optional[dict[str, Any]] = None
    clear_credentials: bool = False
    is_active: Optional[bool] = None


class AutomationProviderResponse(AutomationProviderBase):
    id: int
    # team_id is None for org-scoped providers (CI / Result) served by the
    # system router; populated for team-scoped storage providers.
    team_id: Optional[int] = None
    credentials_set: bool
    credentials_fingerprint: Optional[str] = None
    last_health_check_at: Optional[datetime] = None
    last_health_status: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AutomationProviderTypeInfo(BaseModel):
    provider_type: str
    provider_slot: AutomationProviderSlot
    display_name: str
    config_schema: dict[str, Any]
    credential_schema: dict[str, Any]

    model_config = ConfigDict(use_enum_values=True)


class AutomationProviderHealthResponse(BaseModel):
    status: str
    message: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime


class AutomationProviderValidationResponse(BaseModel):
    valid: bool
    message: str
