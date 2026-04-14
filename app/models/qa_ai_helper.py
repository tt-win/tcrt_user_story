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


class QAAIHelperSessionScreen(str, Enum):
    TICKET_CONFIRMATION = "ticket_confirmation"
    VERIFICATION_PLANNING = "verification_planning"
    SEED_REVIEW = "seed_review"
    TESTCASE_REVIEW = "testcase_review"
    SET_SELECTION = "set_selection"
    COMMIT_RESULT = "commit_result"
    FAILED = "failed"


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


class QAAIHelperRequirementPlanStatus(str, Enum):
    DRAFT = "draft"
    LOCKED = "locked"
    SUPERSEDED = "superseded"


class QAAIHelperSeedSetStatus(str, Enum):
    DRAFT = "draft"
    LOCKED = "locked"
    SUPERSEDED = "superseded"
    CONSUMED = "consumed"


class QAAIHelperTestcaseDraftSetStatus(str, Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"


class QAAIHelperVerificationCategory(str, Enum):
    API = "API"
    UI = "UI"
    FUNCTIONAL = "功能驗證"
    OTHER = "其他"


class QAAIHelperCoverageCategory(str, Enum):
    HAPPY_PATH = "Happy Path"
    ERROR_HANDLING = "Error Handling"
    EDGE_TEST_CASE = "Edge Test Case"
    PERMISSION = "Permission"


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
    ticket_key: str = Field(..., description="Jira ticket key")
    output_locale: QAAIHelperLocale = Field(QAAIHelperLocale.ZH_TW)

    @field_validator("ticket_key")
    @classmethod
    def _normalize_ticket_key(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ticket_key 不可為空")
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


class QAAIHelperTestcaseGenerateRequest(BaseModel):
    force_regenerate: bool = False


class QAAIHelperTestcaseDraftUpdateRequest(BaseModel):
    body: QAAIHelperDraftBody


class QAAIHelperTestcaseDraftSelectionRequest(BaseModel):
    selected_for_commit: bool


class QAAIHelperTestcaseSectionSelectionRequest(BaseModel):
    selected: bool


class QAAIHelperTestcaseSetSelectionRequest(BaseModel):
    testcase_draft_set_id: int


class QAAIHelperNewTestCaseSetPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("name 不可為空")
        return normalized

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QAAIHelperCommitRequest(BaseModel):
    testcase_draft_set_id: int
    selected_draft_ids: List[int] = Field(default_factory=list)
    target_test_case_set_id: Optional[int] = None
    new_test_case_set_payload: Optional[QAAIHelperNewTestCaseSetPayload] = None

    @field_validator("selected_draft_ids")
    @classmethod
    def _validate_selected_draft_ids(cls, value: List[int]) -> List[int]:
        normalized = [int(item) for item in value if int(item) > 0]
        if not normalized:
            raise ValueError("selected_draft_ids 至少需要一筆")
        return normalized


class QAAIHelperTicketFetchRequest(BaseModel):
    ticket_key: Optional[str] = None
    include_comments: Optional[bool] = None


class QAAIHelperTicketReparseRequest(BaseModel):
    raw_ticket_markdown: str

    @field_validator("raw_ticket_markdown")
    @classmethod
    def _validate_markdown(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("raw_ticket_markdown 不可為空")
        return normalized


class QAAIHelperNoTicketSessionRequest(BaseModel):
    """無需求單模式：使用者提供 section 標頭（取代 ticket number），直接進入需求驗證規劃。"""

    section_header: str
    output_locale: Optional[str] = "zh-TW"

    @field_validator("section_header")
    @classmethod
    def _validate_section_header(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("section_header 不可為空")
        return normalized


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


class QAAIHelperCheckConditionPayload(BaseModel):
    id: Optional[int] = None
    condition_text: str = ""
    coverage_tag: Optional[QAAIHelperCoverageCategory] = None

    @field_validator("condition_text")
    @classmethod
    def _normalize_condition_text(cls, value: str) -> str:
        return (value or "").strip()


class QAAIHelperVerificationItemPayload(BaseModel):
    id: Optional[int] = None
    category: QAAIHelperVerificationCategory = QAAIHelperVerificationCategory.FUNCTIONAL
    summary: str = ""
    detail: Dict[str, Any] = Field(default_factory=dict)
    check_conditions: List[QAAIHelperCheckConditionPayload] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _normalize_summary(cls, value: str) -> str:
        return (value or "").strip()


class QAAIHelperPlanSectionPayload(BaseModel):
    id: Optional[int] = None
    section_key: Optional[str] = None
    section_id: Optional[str] = None
    section_title: str = ""
    given: List[str] = Field(default_factory=list)
    when: List[str] = Field(default_factory=list)
    then: List[str] = Field(default_factory=list)
    verification_items: List[QAAIHelperVerificationItemPayload] = Field(default_factory=list)

    @field_validator("section_title")
    @classmethod
    def _normalize_section_title(cls, value: str) -> str:
        return (value or "").strip()


class QAAIHelperRequirementPlanSaveRequest(BaseModel):
    section_start_number: str = Field("010", description="section 起始號，三位數且 10 遞增")
    sections: List[QAAIHelperPlanSectionPayload] = Field(default_factory=list)
    autosave: bool = False

    @field_validator("section_start_number")
    @classmethod
    def _validate_section_start_number(cls, value: str) -> str:
        return _validate_counter_value(value, "section_start_number")


class QAAIHelperSeedItemReviewUpdateRequest(BaseModel):
    included_for_testcase_generation: Optional[bool] = None
    comment_text: Optional[str] = None

    @field_validator("comment_text")
    @classmethod
    def _normalize_comment_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class QAAIHelperSeedSectionInclusionRequest(BaseModel):
    included: bool = True


class QAAIHelperSeedRefineItemRequest(BaseModel):
    seed_item_id: int
    comment_text: str

    @field_validator("comment_text")
    @classmethod
    def _normalize_comment_text(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("comment_text 不可為空")
        return normalized


class QAAIHelperSeedRefineRequest(BaseModel):
    items: List[QAAIHelperSeedRefineItemRequest] = Field(default_factory=list)


class QAAIHelperSessionResponse(BaseModel):
    id: int
    team_id: int
    created_by_user_id: Optional[int] = None
    target_test_case_set_id: Optional[int] = None
    selected_target_test_case_set_id: Optional[int] = None
    ticket_key: Optional[str] = None
    include_comments: bool = False
    output_locale: QAAIHelperLocale
    canonical_language: Optional[QAAIHelperLocale] = None
    current_phase: Optional[QAAIHelperPhase] = None
    current_screen: Optional[QAAIHelperSessionScreen] = None
    status: QAAIHelperSessionStatus
    active_canonical_revision_id: Optional[int] = None
    active_planned_revision_id: Optional[int] = None
    active_draft_set_id: Optional[int] = None
    active_ticket_snapshot_id: Optional[int] = None
    active_requirement_plan_id: Optional[int] = None
    active_seed_set_id: Optional[int] = None
    active_testcase_draft_set_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperTicketSnapshotResponse(BaseModel):
    id: int
    session_id: int
    status: str
    raw_ticket_markdown: str
    structured_requirement: Dict[str, Any] = Field(default_factory=dict)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperScreenGuardResponse(BaseModel):
    current_screen: Optional[QAAIHelperSessionScreen] = None
    allowed_next_screens: List[QAAIHelperSessionScreen] = Field(default_factory=list)
    can_restart: bool = False
    can_reopen: bool = False
    next_screen_on_restart: str = "ticket_input"

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
    testcase_id: Optional[str] = None
    body: Dict[str, Any]
    trace: Dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class QAAIHelperDraftSetDetailResponse(QAAIHelperDraftSetResponse):
    drafts: List[QAAIHelperDraftItemResponse] = Field(default_factory=list)


class QAAIHelperCheckConditionResponse(BaseModel):
    id: int
    condition_text: str
    coverage_tag: QAAIHelperCoverageCategory
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperVerificationItemResponse(BaseModel):
    id: int
    category: QAAIHelperVerificationCategory
    summary: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    display_order: int
    check_conditions: List[QAAIHelperCheckConditionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperPlanSectionResponse(BaseModel):
    id: int
    section_key: str
    section_id: str
    section_title: str
    given: List[str] = Field(default_factory=list)
    when: List[str] = Field(default_factory=list)
    then: List[str] = Field(default_factory=list)
    display_order: int
    verification_items: List[QAAIHelperVerificationItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperRequirementPlanResponse(BaseModel):
    id: int
    session_id: int
    ticket_snapshot_id: int
    revision_number: int
    status: QAAIHelperRequirementPlanStatus
    section_start_number: str
    criteria_reference: Dict[str, Any] = Field(default_factory=dict)
    technical_reference: Dict[str, Any] = Field(default_factory=dict)
    autosave_summary: Dict[str, Any] = Field(default_factory=dict)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    sections: List[QAAIHelperPlanSectionResponse] = Field(default_factory=list)
    locked_at: Optional[datetime] = None
    locked_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperSeedItemResponse(BaseModel):
    id: int
    seed_set_id: int
    plan_section_id: Optional[int] = None
    verification_item_id: Optional[int] = None
    section_key: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    verification_item_summary: Optional[str] = None
    verification_category: Optional[QAAIHelperVerificationCategory] = None
    check_condition_refs: List[int] = Field(default_factory=list)
    coverage_tags: List[str] = Field(default_factory=list)
    seed_reference_key: str
    seed_summary: str
    seed_body: Dict[str, Any] = Field(default_factory=dict)
    comment_text: Optional[str] = None
    is_ai_generated: bool = True
    user_edited: bool = False
    included_for_testcase_generation: bool = True
    display_order: int = 0
    last_refined_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperSeedSetResponse(BaseModel):
    id: int
    session_id: int
    requirement_plan_id: int
    status: QAAIHelperSeedSetStatus
    generation_round: int
    source_type: str
    model_name: Optional[str] = None
    generated_seed_count: int = 0
    included_seed_count: int = 0
    adoption_rate: float = 0.0
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    seed_items: List[QAAIHelperSeedItemResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperTestcaseDraftItemResponse(BaseModel):
    id: int
    testcase_draft_set_id: int
    seed_item_id: int
    seed_reference_key: str
    assigned_testcase_id: Optional[str] = None
    plan_section_id: Optional[int] = None
    verification_item_id: Optional[int] = None
    section_key: Optional[str] = None
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    verification_item_summary: Optional[str] = None
    verification_category: Optional[QAAIHelperVerificationCategory] = None
    body: Dict[str, Any] = Field(default_factory=dict)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    is_ai_generated: bool = True
    user_edited: bool = False
    selected_for_commit: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QAAIHelperTestcaseDraftSetResponse(BaseModel):
    id: int
    session_id: int
    seed_set_id: int
    status: QAAIHelperTestcaseDraftSetStatus
    model_name: Optional[str] = None
    generated_testcase_count: int = 0
    selected_for_commit_count: int = 0
    adoption_rate: float = 0.0
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    committed_at: Optional[datetime] = None
    drafts: List[QAAIHelperTestcaseDraftItemResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


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


class QAAIHelperTokenUsageResponse(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @field_validator("prompt_tokens", "completion_tokens", "total_tokens", mode="before")
    @classmethod
    def _normalize_non_negative_int(cls, value: Any) -> int:
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return number if number >= 0 else 0


class QAAIHelperLLMUsageEventResponse(BaseModel):
    stage: str
    event_name: str
    model_name: Optional[str] = None
    usage: QAAIHelperTokenUsageResponse = Field(default_factory=QAAIHelperTokenUsageResponse)
    duration_ms: int = 0
    created_at: Optional[datetime] = None

    @field_validator("duration_ms", mode="before")
    @classmethod
    def _normalize_duration(cls, value: Any) -> int:
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return number if number >= 0 else 0


class QAAIHelperLLMUsageSummaryResponse(BaseModel):
    total: QAAIHelperTokenUsageResponse = Field(default_factory=QAAIHelperTokenUsageResponse)
    by_stage: Dict[str, QAAIHelperTokenUsageResponse] = Field(default_factory=dict)
    latest: Optional[QAAIHelperLLMUsageEventResponse] = None


class QAAIHelperWorkspaceResponse(BaseModel):
    session: QAAIHelperSessionResponse
    ticket_snapshot: Optional[QAAIHelperTicketSnapshotResponse] = None
    screen_guard: Optional[QAAIHelperScreenGuardResponse] = None
    source_payload: Dict[str, Any] = Field(default_factory=dict)
    llm_usage: QAAIHelperLLMUsageSummaryResponse = Field(default_factory=QAAIHelperLLMUsageSummaryResponse)
    canonical_validation: Dict[str, Any] = Field(default_factory=dict)
    requirement_plan: Optional[QAAIHelperRequirementPlanResponse] = None
    seed_set: Optional[QAAIHelperSeedSetResponse] = None
    testcase_draft_set: Optional[QAAIHelperTestcaseDraftSetResponse] = None
    canonical_revision: Optional[QAAIHelperCanonicalRevisionResponse] = None
    planned_revision: Optional[QAAIHelperPlannedRevisionResponse] = None
    draft_set: Optional[QAAIHelperDraftSetDetailResponse] = None
    latest_validation_run: Optional[Dict[str, Any]] = None
    commit_result: Optional["QAAIHelperCommitResultResponse"] = None


class QAAIHelperDeleteResponse(BaseModel):
    deleted: bool
    session_id: int


class QAAIHelperRestartResponse(BaseModel):
    reset: bool
    session_id: int
    next_screen: str = "ticket_input"


class QAAIHelperCommitDraftResultResponse(BaseModel):
    testcase_draft_id: int
    seed_item_id: Optional[int] = None
    seed_reference_key: Optional[str] = None
    assigned_testcase_id: Optional[str] = None
    status: str
    reason: Optional[str] = None
    test_case_id: Optional[int] = None


class QAAIHelperCommitResultResponse(BaseModel):
    testcase_draft_set_id: int
    target_test_case_set_id: Optional[int] = None
    target_test_case_set_name: Optional[str] = None
    created_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    created_test_case_ids: List[str] = Field(default_factory=list)
    failed_drafts: List[QAAIHelperCommitDraftResultResponse] = Field(default_factory=list)
    skipped_drafts: List[QAAIHelperCommitDraftResultResponse] = Field(default_factory=list)
    draft_results: List[QAAIHelperCommitDraftResultResponse] = Field(default_factory=list)
    target_set_link_available: bool = False
    target_set_link: Optional[str] = None
    committed_at: Optional[datetime] = None


class QAAIHelperCommitResponse(BaseModel):
    created_count: int
    updated_count: int = 0
    committed_draft_set_id: Optional[int] = None


QAAIHelperWorkspaceResponse.model_rebuild()
