"""
JIRA Test Case Helper API 資料模型
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HelperLocale(str, Enum):
    ZH_TW = "zh-TW"
    ZH_CN = "zh-CN"
    EN = "en"


class HelperPhase(str, Enum):
    INIT = "init"
    REQUIREMENT = "requirement"
    ANALYSIS = "analysis"
    PRETESTCASE = "pretestcase"
    TESTCASE = "testcase"
    COMMIT = "commit"
    FAILED = "failed"


class HelperPhaseStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    COMPLETED = "completed"
    FAILED = "failed"


class HelperSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HelperSessionStartRequest(BaseModel):
    test_case_set_id: Optional[int] = Field(None, description="目標 Test Case Set ID")
    create_set_name: Optional[str] = Field(None, description="若建立新 Set，填入名稱")
    create_set_description: Optional[str] = Field(
        None, description="若建立新 Set，填入描述"
    )
    review_locale: Optional[HelperLocale] = Field(
        None, description="需求整理檢視語系（未填則沿用 output_locale）"
    )
    output_locale: HelperLocale = Field(
        HelperLocale.ZH_TW, description="最終 Test Case 產出語系"
    )
    initial_middle: str = Field("010", description="middle 起始號，三位數且 10 遞增")
    enable_qdrant_context: bool = Field(
        True, description="是否啟用向量檢索輔助上下文"
    )

    @field_validator("create_set_name")
    @classmethod
    def _normalize_set_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("create_set_description")
    @classmethod
    def _normalize_set_description(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("initial_middle")
    @classmethod
    def _validate_initial_middle(cls, value: str) -> str:
        normalized = (value or "").strip()
        if len(normalized) != 3 or not normalized.isdigit():
            raise ValueError("initial_middle 必須為三位數（例如 010）")
        number = int(normalized)
        if number < 10 or number > 990 or number % 10 != 0:
            raise ValueError("initial_middle 必須為 010~990 且以 10 遞增")
        return normalized

    @model_validator(mode="after")
    def _validate_target_set(self) -> "HelperSessionStartRequest":
        has_existing_set = self.test_case_set_id is not None
        has_new_set = bool(self.create_set_name)
        if has_existing_set == has_new_set:
            raise ValueError("請擇一提供 test_case_set_id 或 create_set_name")
        return self


class HelperSessionUpdateRequest(BaseModel):
    review_locale: Optional[HelperLocale] = None
    output_locale: Optional[HelperLocale] = None
    current_phase: Optional[HelperPhase] = None
    phase_status: Optional[HelperPhaseStatus] = None
    status: Optional[HelperSessionStatus] = None
    last_error: Optional[str] = None


class HelperSessionListItemResponse(BaseModel):
    id: int
    team_id: int
    created_by_user_id: int
    target_test_case_set_id: int
    ticket_key: Optional[str] = None
    session_label: str
    current_phase: HelperPhase
    phase_status: HelperPhaseStatus
    status: HelperSessionStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HelperSessionListResponse(BaseModel):
    items: List[HelperSessionListItemResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    has_more: bool = False


class HelperSessionBulkDeleteRequest(BaseModel):
    session_ids: List[int] = Field(default_factory=list)

    @field_validator("session_ids")
    @classmethod
    def _normalize_session_ids(cls, value: List[int]) -> List[int]:
        normalized: List[int] = []
        seen = set()
        for item in value or []:
            number = int(item)
            if number <= 0:
                continue
            if number in seen:
                continue
            normalized.append(number)
            seen.add(number)
        if not normalized:
            raise ValueError("session_ids 不可為空")
        return normalized


class HelperSessionClearRequest(BaseModel):
    include_active: bool = Field(True, description="是否包含 active session")


class HelperSessionDeleteResponse(BaseModel):
    requested_count: int
    deleted_count: int
    deleted_session_ids: List[int] = Field(default_factory=list)


class HelperDraftUpsertRequest(BaseModel):
    markdown: Optional[str] = Field(None, description="可編輯 Markdown 內容")
    payload: Optional[Dict[str, Any]] = Field(None, description="結構化 JSON 內容")
    increment_version: bool = Field(True, description="是否自動遞增版本號")


class HelperTicketFetchRequest(BaseModel):
    ticket_key: str = Field(..., description="JIRA Ticket Key，例如 TCG-12345")

    @field_validator("ticket_key")
    @classmethod
    def _normalize_ticket_key(cls, value: str) -> str:
        normalized = (value or "").strip().upper()
        if not normalized:
            raise ValueError("ticket_key 不可為空")
        return normalized


class HelperNormalizeRequest(BaseModel):
    force: bool = Field(False, description="是否強制重新整理需求內容")


class HelperAnalyzeRequest(BaseModel):
    requirement_markdown: Optional[str] = Field(
        None, description="使用者修訂後的需求 Markdown"
    )
    user_notes: Optional[str] = Field(None, description="分析補充註記")
    retry: bool = Field(False, description="是否重試分析流程")
    override_incomplete_requirement: bool = Field(
        False,
        description="當 requirement 格式不完整時，是否確認仍要繼續流程",
    )


class HelperGenerateRequest(BaseModel):
    pretestcase_payload: Optional[Dict[str, Any]] = Field(
        None, description="使用者修訂後的 pre-testcase JSON"
    )
    retry: bool = Field(False, description="是否重試 testcase 產生流程")


class HelperCommitTestCaseItem(BaseModel):
    id: str = Field(..., description="完整 Test Case 編號")
    t: str = Field(..., description="標題")
    pre: List[str] = Field(default_factory=list, description="前置條件清單")
    s: List[str] = Field(default_factory=list, description="步驟清單")
    exp: List[str] = Field(default_factory=list, description="預期結果清單")
    priority: str = Field("Medium", description="優先級")
    section_path: Optional[str] = Field(None, description="目標 section path")
    section_id: Optional[int] = Field(None, description="目標 section id")

    @field_validator("id", "t")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("必要欄位不可為空")
        return normalized


class HelperCommitRequest(BaseModel):
    testcases: Optional[List[HelperCommitTestCaseItem]] = Field(
        None, description="最終確認後的 testcase 清單；未填則使用 session draft"
    )


class HelperDraftResponse(BaseModel):
    phase: str
    version: int
    markdown: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HelperSessionResponse(BaseModel):
    id: int
    team_id: int
    created_by_user_id: int
    target_test_case_set_id: int
    ticket_key: Optional[str] = None
    session_label: str
    review_locale: HelperLocale
    output_locale: HelperLocale
    initial_middle: str
    current_phase: HelperPhase
    phase_status: HelperPhaseStatus
    status: HelperSessionStatus
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    drafts: List[HelperDraftResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class HelperTicketSummaryResponse(BaseModel):
    ticket_key: str
    summary: str
    description: str
    components: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class HelperStageResultResponse(BaseModel):
    session: HelperSessionResponse
    stage: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    markdown: Optional[str] = None
    usage: Dict[str, Any] = Field(default_factory=dict)
