"""Assistant API 的 Pydantic request/response models（spec assistant-conversations 等）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class AvailabilityResponse(BaseModel):
    enabled: bool


class ConversationCreateRequest(BaseModel):
    scope_type: Literal["global", "team"]
    team_id: Optional[int] = None
    title: Optional[str] = None


class ConversationBatchDeleteRequest(BaseModel):
    conversation_ids: list[int] = Field(..., min_items=1)


class ConversationBatchDeleteResponse(BaseModel):
    deleted_count: int
    deleted_ids: list[int]


class ConversationResponse(BaseModel):
    id: int
    conversation_key: str
    scope_type: str
    team_id: Optional[int]
    source_team_id: Optional[int]
    title: Optional[str]
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime

    class Config:
        from_attributes = True


class AttachmentSummary(BaseModel):
    attachment_index: int
    original_name: str
    content_type: Optional[str]
    size_bytes: int


class MessageHistoryItem(BaseModel):
    turn_seq: int
    turn_key: str
    turn_status: str
    message_seq: int
    role: str
    content: Optional[str]
    tool_name: Optional[str]
    llm_tool_call_id: Optional[str]
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_result: Optional[dict[str, Any]] = None
    tool_outcome: Optional[str] = None
    pending_action: Optional[dict[str, Any]] = None
    attachments: Optional[list[AttachmentSummary]] = None


class MessageHistoryResponse(BaseModel):
    messages: list[MessageHistoryItem]
    active_turn: Optional[dict[str, Any]] = None


class ActionAckResponse(BaseModel):
    """cancel 等不需串流回應的確認端點共用回應。"""

    action_id: int
    status: str


class StopAckResponse(BaseModel):
    turn_key: str
    cancel_requested: bool = True


class ErrorDetail(BaseModel):
    code: str
    message: str = Field(default="")
