from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.database_models import AutomationWebhookDirection


class AutomationWebhookCreate(BaseModel):
    direction: AutomationWebhookDirection
    name: str = Field(..., min_length=1, max_length=100)
    target_url: Optional[str] = Field(None, max_length=500)
    events: list[str] = Field(default_factory=list)
    script_group_id: Optional[int] = None
    is_active: bool = True


class AutomationWebhookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    target_url: Optional[str] = Field(None, max_length=500)
    events: Optional[list[str]] = None
    script_group_id: Optional[int] = None
    is_active: Optional[bool] = None


class AutomationWebhookCreateResponse(BaseModel):
    id: int
    token: str
    secret: str


class AutomationWebhookTestPingResponse(BaseModel):
    status: str
    status_code: Optional[int] = None
    duration_ms: int
    message: str


class AutomationWebhookResponse(BaseModel):
    id: int
    team_id: int
    direction: AutomationWebhookDirection
    name: str
    token_fingerprint: str
    secret_fingerprint: Optional[str] = None
    target_url: Optional[str] = None
    events: list[str] = Field(default_factory=list)
    script_group_id: Optional[int] = None
    is_active: bool
    last_triggered_at: Optional[datetime] = None
    last_status: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AutomationWebhookDeliveryResponse(BaseModel):
    id: int
    team_id: int
    webhook_id: int
    event: str
    delivery_id: str
    target_url: str
    status: str
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AutomationWebhookDeliveryListResponse(BaseModel):
    items: list[AutomationWebhookDeliveryResponse]


class AutomationWebhookReplayResponse(BaseModel):
    status: str
    delivery: AutomationWebhookDeliveryResponse
