"""
Rewritten QA AI Helper API / service contracts.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


TCG_TICKET_PATTERN = re.compile(r"^[A-Z]+-\d+$")


def _validate_counter_value(value: str, field_name: str) -> str:
    normalized = (value or "").strip()
    if len(normalized) != 3 or not normalized.isdigit():
        raise ValueError(f"{field_name} 必須為三位數（例如 010）")
    number = int(normalized)
    if number < 10 or number > 990 or number % 10 != 0:
        raise ValueError(f"{field_name} 必須為 010~990 且以 10 遞增")
    return normalized


class QAAIHelperLocale(str, Enum):
    ZH_TW = "zh-TW"
    ZH_CN = "zh-CN"
    EN = "en"


class QAAIHelperPhase(str, Enum):
    INTAKE = "intake"
    PLANNED = "planned"
    GENERATED = "generated"
    VALIDATED = "validated"
    COMMITTED = "committed"
    FAILED = "failed"


class QAAIHelperSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QAAIHelperCanonicalRevisionStatus(str, Enum):
    EDITABLE = "editable"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class QAAIHelperPlannedRevisionStatus(str, Enum):
    EDITABLE = "editable"
    LOCKED = "locked"
    STALE = "stale"


class QAAIHelperDraftSetStatus(str, Enum):
    ACTIVE = "active"
    OUTDATED = "outdated"
    DISCARDED = "discarded"
    COMMITTED = "committed"


class QAAIHelperRequirementDeltaType(str, Enum):
    ADD = "add"
    DELETE = "delete"
    MODIFY = "modify"


class QAAIHelperApplicabilityStatus(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    MANUAL_EXEMPT = "manual_exempt"


class QAAIHelperRunStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class QAAIHelperCounterSettings(BaseModel):
    middle: str = Field("010", description="middle 起始號，三位數且 10 遞增")
    tail: str = Field("010", description="tail 起始號，三位數且 10 遞增")

    @field_validator("middle")
    @classmethod
    def _validate_middle(cls, value: str) -> str:
        return _validate_counter_value(value, "middle")

    @field_validator("tail")
    @classmethod
    def _validate_tail(cls, value: str) -> str:
        return _validate_counter_value(value, "tail")


class QAAIHelperSourceBlock(BaseModel):
    block_id: str
    source_type: str
    language: Optional[str] = None
    title: Optional[str] = None
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QAAIHelperExtensionSeedHint(BaseModel):
    category: str = "happy"
    title_hint: str
    precondition_hints: List[str] = Field(default_factory=list)
    step_hints: List[str] = Field(default_factory=list)
    expected_hints: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("category", "title_hint")
    @classmethod
    def _validate_non_empty_string(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("extension seed hint 欄位不可為空")
        return normalized


class QAAIHelperTeamExtensionHint(BaseModel):
    scenario_key: Optional[str] = None
    traits: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    seed_hints: List[QAAIHelperExtensionSeedHint] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("scenario_key")
    @classmethod
    def _normalize_optional_scenario_key(cls, value: Optional[str]) -> Optional[str]:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("traits", "constraints")
    @classmethod
    def _normalize_list_items(cls, value: List[str]) -> List[str]:
        return [str(item).strip() for item in value if str(item).strip()]


class QAAIHelperCanonicalContent(BaseModel):
    user_story_narrative: str = Field(..., alias="userStoryNarrative")
    criteria: str
    technical_specifications: str = Field(..., alias="technicalSpecifications")
    acceptance_criteria: str = Field(..., alias="acceptanceCriteria")
    assumptions: List[str] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator(
        "user_story_narrative",
        "criteria",
        "technical_specifications",
        "acceptance_criteria",
    )
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("canonical 區塊內容不可為空")
        return normalized


class QAAIHelperSessionCreateRequest(BaseModel):
    target_test_case_set_id: int = Field(..., description="目標 Test Case Set ID")
    ticket_key: Optional[str] = Field(None, description="Jira ticket key")
    include_comments: bool = Field(False, description="是否抓取 Jira comments")
    output_locale: QAAIHelperLocale = Field(QAAIHelperLocale.ZH_TW)
    canonical_language: Optional[QAAIHelperLocale] = Field(
        None,
        description="canonical planning language",
    )
    counter_settings: QAAIHelperCounterSettings = Field(
        default_factory=QAAIHelperCounterSettings
    )

    @field_validator("ticket_key")
    @classmethod
    def _normalize_ticket_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            return None
        if normalized.isdigit():
            normalized = f"TCG-{normalized}"
        elif normalized.startswith("TCG") and "-" not in normalized:
            normalized = f"TCG-{normalized[3:]}"
        if not TCG_TICKET_PATTERN.match(normalized):
            raise ValueError("ticket_key 格式錯誤，請使用 TCG-12345")
        return normalized


class QAAIHelperCanonicalRevisionCreateRequest(BaseModel):
    canonical_language: QAAIHelperLocale
    content: QAAIHelperCanonicalContent
    counter_settings: QAAIHelperCounterSettings


class QAAIHelperPlanningOverride(BaseModel):
    row_key: str
    status: QAAIHelperApplicabilityStatus
    reason: Optional[str] = None

    @field_validator("row_key")
    @classmethod
    def _validate_row_key(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("row_key 不可為空")
        return normalized


class QAAIHelperRequirementDeltaCreateRequest(BaseModel):
    delta_type: QAAIHelperRequirementDeltaType
    target_scope: str
    target_requirement_key: Optional[str] = None
    target_scenario_key: Optional[str] = None
    proposed_content: Dict[str, Any] = Field(default_factory=dict)
    reason: str

    @field_validator("target_scope", "reason")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("必要欄位不可為空")
        return normalized


class QAAIHelperPlanningLockRequest(BaseModel):
    planned_revision_id: int


class QAAIHelperDraftBody(BaseModel):
    title: str
    priority: str = "Medium"
    preconditions: List[str] = Field(default_factory=list)
    steps: List[str] = Field(default_factory=list)
    expected_results: List[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("title 不可為空")
        return normalized


class QAAIHelperDraftUpdateRequest(BaseModel):
    item_key: str
    body: QAAIHelperDraftBody


class QAAIHelperTicketFetchRequest(BaseModel):
    ticket_key: Optional[str] = None
    include_comments: Optional[bool] = None


class QAAIHelperPlanRequest(BaseModel):
    canonical_revision_id: Optional[int] = None
    selected_references: Optional[Dict[str, Any]] = None
    team_extensions: List[QAAIHelperTeamExtensionHint] = Field(default_factory=list)


class QAAIHelperPlanningOverrideApplyRequest(BaseModel):
    overrides: List[QAAIHelperPlanningOverride] = Field(default_factory=list)
    selected_references: Optional[Dict[str, Any]] = None
    counter_settings: Optional[QAAIHelperCounterSettings] = None
    team_extensions: List[QAAIHelperTeamExtensionHint] = Field(default_factory=list)


class QAAIHelperGenerateRequest(BaseModel):
    section_ids: List[str] = Field(default_factory=list)
    row_group_keys: List[str] = Field(default_factory=list)
    confirm_exhaustive: bool = False
    force_regenerate: bool = False


class QAAIHelperSessionResponse(BaseModel):
    id: int
    team_id: int
    created_by_user_id: Optional[int] = None
    target_test_case_set_id: int
    ticket_key: Optional[str] = None
    include_comments: bool = False
    output_locale: QAAIHelperLocale
    canonical_language: Optional[QAAIHelperLocale] = None
    current_phase: QAAIHelperPhase
    status: QAAIHelperSessionStatus
    active_canonical_revision_id: Optional[int] = None
    active_planned_revision_id: Optional[int] = None
    active_draft_set_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperCanonicalRevisionResponse(BaseModel):
    id: int
    session_id: int
    revision_number: int
    status: QAAIHelperCanonicalRevisionStatus
    canonical_language: QAAIHelperLocale
    content: Dict[str, Any]
    counter_settings: Dict[str, Any]
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperPlannedRevisionResponse(BaseModel):
    id: int
    session_id: int
    canonical_revision_id: int
    revision_number: int
    status: QAAIHelperPlannedRevisionStatus
    matrix: Dict[str, Any]
    seed_map: Dict[str, Any] = Field(default_factory=dict)
    applicability_overrides: Dict[str, Any]
    selected_references: Dict[str, Any]
    counter_settings: Dict[str, Any]
    impact_summary: Dict[str, Any]
    locked_at: Optional[datetime] = None
    locked_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperDraftSetResponse(BaseModel):
    id: int
    session_id: int
    planned_revision_id: int
    status: QAAIHelperDraftSetStatus
    generation_mode: Optional[str] = None
    model_name: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    committed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperDraftItemResponse(BaseModel):
    id: int
    item_key: str
    seed_id: Optional[str] = None
    testcase_id: Optional[str] = None
    body: Dict[str, Any]
    trace: Dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class QAAIHelperDraftSetDetailResponse(QAAIHelperDraftSetResponse):
    drafts: List[QAAIHelperDraftItemResponse] = Field(default_factory=list)


class QAAIHelperSessionListItemResponse(BaseModel):
    session: QAAIHelperSessionResponse
    canonical_revision: Optional[QAAIHelperCanonicalRevisionResponse] = None
    planned_revision: Optional[QAAIHelperPlannedRevisionResponse] = None
    draft_set: Optional[QAAIHelperDraftSetResponse] = None


class QAAIHelperSessionListResponse(BaseModel):
    items: List[QAAIHelperSessionListItemResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class QAAIHelperWorkspaceResponse(BaseModel):
    session: QAAIHelperSessionResponse
    source_payload: Dict[str, Any] = Field(default_factory=dict)
    canonical_validation: Dict[str, Any] = Field(default_factory=dict)
    canonical_revision: Optional[QAAIHelperCanonicalRevisionResponse] = None
    planned_revision: Optional[QAAIHelperPlannedRevisionResponse] = None
    draft_set: Optional[QAAIHelperDraftSetDetailResponse] = None
    latest_validation_run: Optional[Dict[str, Any]] = None


class QAAIHelperDeleteResponse(BaseModel):
    deleted: bool
    session_id: int


class QAAIHelperCommitResponse(BaseModel):
    created_count: int
    updated_count: int
    committed_draft_set_id: int
