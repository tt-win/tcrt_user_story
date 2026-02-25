"""
JIRA Ticket -> Test Case Helper 主要服務
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import run_sync
from app.models.database_models import (
    AITestCaseHelperDraft,
    AITestCaseHelperSession,
    Priority,
    SyncStatus,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.models.test_case_helper import (
    HelperAnalyzeRequest,
    HelperCommitRequest,
    HelperDraftResponse,
    HelperDraftUpsertRequest,
    HelperGenerateRequest,
    HelperLocale,
    HelperNormalizeRequest,
    HelperPhase,
    HelperPhaseStatus,
    HelperSessionResponse,
    HelperSessionStartRequest,
    HelperSessionStatus,
    HelperSessionUpdateRequest,
    HelperStageResultResponse,
    HelperTicketFetchRequest,
    HelperTicketSummaryResponse,
)
from app.services.jira_client import JiraClient
from app.services.jira_testcase_helper_llm_service import (
    JiraTestCaseHelperLLMService,
    get_jira_testcase_helper_llm_service,
)
from app.services.jira_testcase_helper_prompt_service import (
    JiraTestCaseHelperPromptService,
    get_jira_testcase_helper_prompt_service,
)
from app.services.qdrant_client import get_qdrant_client
from app.services.test_case_helper import (
    DraftPayloadAdapter,
    PretestcasePresenter,
    RequirementCompletenessValidator,
    RequirementIRBuilder,
    StructuredRequirementParser,
)
from app.services.test_case_set_service import TestCaseSetService

logger = logging.getLogger(__name__)


TCG_TICKET_PATTERN = re.compile(r"^[A-Z]+-\d+$")
TRUTHY_TEXT = {"y", "yes", "true", "1", "v", "✓", "✔"}
VALID_SEED_CATEGORIES = {"happy", "negative", "boundary"}
VALID_SEED_ASPECTS = {"happy", "edge", "error", "permission"}
NEGATIVE_CATEGORY_HINTS = (
    "錯誤",
    "失敗",
    "無效",
    "拒絕",
    "禁止",
    "異常",
    "逾時",
    "過期",
    "未授權",
    "權限不足",
    "invalid",
    "error",
    "fail",
    "forbidden",
    "denied",
    "unauthorized",
    "expired",
    "timeout",
    "not found",
)
BOUNDARY_CATEGORY_HINTS = (
    "邊界",
    "上限",
    "下限",
    "最大",
    "最小",
    "極限",
    "極值",
    "最長",
    "最短",
    "分頁",
    "跨頁",
    "捲動",
    "窄螢幕",
    "最小寬度",
    "limit",
    "max",
    "min",
    "boundary",
    "edge",
    "scroll",
    "pagination",
)
PERMISSION_CATEGORY_HINTS = (
    "權限",
    "角色",
    "未授權",
    "禁止",
    "permission",
    "role",
    "forbidden",
    "unauthorized",
    "denied",
    "acl",
    "rbac",
)
DEFAULT_FORBIDDEN_PATTERNS = (
    r"參考",
    r"REF\d+",
    r"同上",
    r"略",
    r"TBD",
    r"N/A",
    r"待補",
    r"TODO",
)
OBSERVABLE_KEYWORDS = (
    "欄位",
    "按鈕",
    "表格",
    "列表",
    "排序",
    "頁面",
    "提示",
    "toast",
    "modal",
    "狀態",
    "http",
    "status code",
    "response",
    "request",
    "payload",
    "error code",
    "schema",
    "資料表",
    "record",
    "log",
    "event",
    "audit",
    "queue",
)

PHASE_TRANSITIONS: Dict[str, set[str]] = {
    HelperPhase.INIT.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.REQUIREMENT.value: {
        HelperPhase.ANALYSIS.value,
        HelperPhase.REQUIREMENT.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.ANALYSIS.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.PRETESTCASE.value,
        HelperPhase.ANALYSIS.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.PRETESTCASE.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.TESTCASE.value,
        HelperPhase.PRETESTCASE.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.TESTCASE.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.COMMIT.value,
        HelperPhase.TESTCASE.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.COMMIT.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.COMMIT.value,
        HelperPhase.FAILED.value,
    },
    HelperPhase.FAILED.value: {
        HelperPhase.REQUIREMENT.value,
        HelperPhase.ANALYSIS.value,
        HelperPhase.PRETESTCASE.value,
        HelperPhase.TESTCASE.value,
        HelperPhase.COMMIT.value,
    },
}


def _now() -> datetime:
    return datetime.utcnow()


def _safe_json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _safe_json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_tcg_ticket_key(raw: str) -> str:
    normalized = (raw or "").strip().upper()
    if not normalized:
        raise ValueError("TCG 單號不可為空")

    if normalized.isdigit():
        normalized = f"TCG-{normalized}"
    elif normalized.startswith("TCG") and "-" not in normalized:
        normalized = f"TCG-{normalized[3:]}"
    elif normalized.startswith("TCG-"):
        suffix = normalized[4:]
        normalized = f"TCG-{suffix}"

    if not TCG_TICKET_PATTERN.match(normalized):
        raise ValueError("TCG 單號格式錯誤，請使用 TCG-12345")
    return normalized


def _locale_label(locale: str) -> str:
    mapping = {
        "zh-TW": "繁體中文",
        "zh-CN": "简体中文",
        "en": "English",
    }
    return mapping.get(locale, locale)


class JiraTestCaseHelperService:
    def __init__(
        self,
        db: AsyncSession,
        llm_service: Optional[JiraTestCaseHelperLLMService] = None,
        prompt_service: Optional[JiraTestCaseHelperPromptService] = None,
    ):
        self.db = db
        self.settings = get_settings()
        self.llm_service = llm_service or get_jira_testcase_helper_llm_service()
        self.prompt_service = prompt_service or get_jira_testcase_helper_prompt_service()
        self.payload_adapter = DraftPayloadAdapter()
        self.requirement_parser = StructuredRequirementParser()
        self.requirement_validator = RequirementCompletenessValidator()
        self.requirement_ir_builder = RequirementIRBuilder()
        self.pretestcase_presenter = PretestcasePresenter()

    # ---------- Session and draft base ----------
    def _check_phase_transition(self, current_phase: str, next_phase: str) -> None:
        allowed = PHASE_TRANSITIONS.get(current_phase, {next_phase})
        if next_phase not in allowed:
            raise ValueError(f"不合法的 phase transition: {current_phase} -> {next_phase}")

    def _set_session_phase(
        self,
        session: AITestCaseHelperSession,
        *,
        phase: HelperPhase,
        phase_status: HelperPhaseStatus,
        status: Optional[HelperSessionStatus] = None,
        last_error: Optional[str] = None,
        enforce_transition: bool = True,
    ) -> None:
        if enforce_transition:
            self._check_phase_transition(session.current_phase, phase.value)
        session.current_phase = phase.value
        session.phase_status = phase_status.value
        if status is not None:
            session.status = status.value
        session.last_error = last_error
        session.updated_at = _now()

    def _to_draft_response(self, draft: AITestCaseHelperDraft) -> HelperDraftResponse:
        raw_payload = _safe_json_loads(draft.payload_json, None)
        normalized_payload = self.payload_adapter.unwrap(raw_payload)
        return HelperDraftResponse(
            phase=draft.phase,
            version=draft.version,
            markdown=draft.markdown,
            payload=normalized_payload,
            updated_at=draft.updated_at,
        )

    def _to_session_response(
        self, session: AITestCaseHelperSession, drafts: List[AITestCaseHelperDraft]
    ) -> HelperSessionResponse:
        return HelperSessionResponse(
            id=session.id,
            team_id=session.team_id,
            created_by_user_id=session.created_by_user_id or 0,
            target_test_case_set_id=session.target_test_case_set_id,
            ticket_key=session.ticket_key,
            review_locale=HelperLocale(session.review_locale),
            output_locale=HelperLocale(session.output_locale),
            initial_middle=session.initial_middle,
            current_phase=HelperPhase(session.current_phase),
            phase_status=HelperPhaseStatus(session.phase_status),
            status=HelperSessionStatus(session.status),
            last_error=session.last_error,
            created_at=session.created_at,
            updated_at=session.updated_at,
            drafts=[self._to_draft_response(item) for item in drafts],
        )

    def _get_session_and_drafts_sync(
        self,
        sync_db: Session,
        *,
        team_id: int,
        session_id: int,
    ) -> Tuple[AITestCaseHelperSession, List[AITestCaseHelperDraft]]:
        session = (
            sync_db.query(AITestCaseHelperSession)
            .filter(
                AITestCaseHelperSession.id == session_id,
                AITestCaseHelperSession.team_id == team_id,
            )
            .first()
        )
        if not session:
            raise ValueError(f"找不到 helper session: {session_id}")

        drafts = (
            sync_db.query(AITestCaseHelperDraft)
            .filter(AITestCaseHelperDraft.session_id == session.id)
            .order_by(AITestCaseHelperDraft.phase.asc())
            .all()
        )
        return session, drafts

    def _get_or_create_draft_sync(
        self,
        sync_db: Session,
        *,
        session_id: int,
        phase: str,
    ) -> AITestCaseHelperDraft:
        draft = (
            sync_db.query(AITestCaseHelperDraft)
            .filter(
                AITestCaseHelperDraft.session_id == session_id,
                AITestCaseHelperDraft.phase == phase,
            )
            .first()
        )
        if draft:
            return draft

        draft = AITestCaseHelperDraft(
            session_id=session_id,
            phase=phase,
            version=1,
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(draft)
        sync_db.flush()
        return draft

    def _upsert_draft_sync(
        self,
        sync_db: Session,
        *,
        session_id: int,
        phase: str,
        markdown: Optional[str] = None,
        payload: Any = None,
        quality: Optional[Dict[str, Any]] = None,
        trace: Optional[Dict[str, Any]] = None,
        increment_version: bool = True,
    ) -> AITestCaseHelperDraft:
        draft = self._get_or_create_draft_sync(
            sync_db, session_id=session_id, phase=phase
        )
        if increment_version:
            draft.version += 1
        draft.markdown = markdown
        draft_payload = self.payload_adapter.wrap(
            phase=phase,
            data=payload,
            quality=quality,
            trace=trace,
        )
        draft.payload_json = _safe_json_dumps(draft_payload)
        draft.updated_at = _now()
        sync_db.flush()
        return draft

    def _build_default_drafts_sync(
        self, sync_db: Session, session_id: int
    ) -> List[AITestCaseHelperDraft]:
        phases = [
            "jira_ticket",
            "requirement",
            "requirement_ir",
            "analysis",
            "coverage",
            "pretestcase",
            "testcase",
            "audit",
            "final_testcases",
        ]
        drafts: List[AITestCaseHelperDraft] = []
        for phase in phases:
            drafts.append(
                self._get_or_create_draft_sync(
                    sync_db,
                    session_id=session_id,
                    phase=phase,
                )
            )
        return drafts

    async def start_session(
        self,
        *,
        team_id: int,
        user_id: int,
        request: HelperSessionStartRequest,
    ) -> HelperSessionResponse:
        target_set_id = request.test_case_set_id
        if request.create_set_name:
            set_service = TestCaseSetService(self.db)
            created_set = await set_service.create(
                team_id=team_id,
                name=request.create_set_name,
                description=request.create_set_description,
            )
            target_set_id = created_set.id

        if target_set_id is None:
            raise ValueError("缺少目標 Test Case Set")

        review_locale = request.review_locale.value if request.review_locale else request.output_locale.value

        def _create(sync_db: Session) -> HelperSessionResponse:
            test_set = (
                sync_db.query(TestCaseSet)
                .filter(
                    TestCaseSet.id == target_set_id,
                    TestCaseSet.team_id == team_id,
                )
                .first()
            )
            if not test_set:
                raise ValueError(f"Test Case Set 不存在: {target_set_id}")

            session = AITestCaseHelperSession(
                team_id=team_id,
                created_by_user_id=user_id,
                target_test_case_set_id=target_set_id,
                review_locale=review_locale,
                output_locale=request.output_locale.value,
                initial_middle=request.initial_middle,
                current_phase=HelperPhase.INIT.value,
                phase_status=HelperPhaseStatus.IDLE.value,
                status=HelperSessionStatus.ACTIVE.value,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(session)
            sync_db.flush()
            drafts = self._build_default_drafts_sync(sync_db, session.id)
            sync_db.commit()
            return self._to_session_response(session, drafts)

        return await run_sync(self.db, _create)

    async def get_session(self, *, team_id: int, session_id: int) -> HelperSessionResponse:
        def _get(sync_db: Session) -> HelperSessionResponse:
            session, drafts = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            return self._to_session_response(session, drafts)

        return await run_sync(self.db, _get)

    async def update_session(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperSessionUpdateRequest,
    ) -> HelperSessionResponse:
        def _update(sync_db: Session) -> HelperSessionResponse:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            if request.review_locale is not None:
                session.review_locale = request.review_locale.value
            if request.output_locale is not None:
                session.output_locale = request.output_locale.value
            if request.current_phase is not None:
                self._set_session_phase(
                    session,
                    phase=request.current_phase,
                    phase_status=request.phase_status or HelperPhaseStatus.IDLE,
                    status=request.status,
                    last_error=request.last_error,
                )
            else:
                if request.phase_status is not None:
                    session.phase_status = request.phase_status.value
                if request.status is not None:
                    session.status = request.status.value
                if request.last_error is not None:
                    session.last_error = request.last_error
                session.updated_at = _now()

            sync_db.commit()
            _, drafts = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            return self._to_session_response(session, drafts)

        return await run_sync(self.db, _update)

    async def upsert_draft(
        self,
        *,
        team_id: int,
        session_id: int,
        phase: str,
        request: HelperDraftUpsertRequest,
    ) -> HelperDraftResponse:
        phase_key = (phase or "").strip().lower()
        if not phase_key:
            raise ValueError("phase 不可為空")

        def _upsert(sync_db: Session) -> HelperDraftResponse:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            draft = self._upsert_draft_sync(
                sync_db,
                session_id=session.id,
                phase=phase_key,
                markdown=request.markdown,
                payload=request.payload,
                increment_version=request.increment_version,
            )
            sync_db.commit()
            return self._to_draft_response(draft)

        return await run_sync(self.db, _upsert)

    # ---------- JIRA stage ----------
    async def fetch_ticket(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperTicketFetchRequest,
    ) -> HelperTicketSummaryResponse:
        ticket_key = _parse_tcg_ticket_key(request.ticket_key)
        jira_client = JiraClient()
        issue = await asyncio.to_thread(
            jira_client.get_issue,
            ticket_key,
            [
                "summary",
                "description",
                "components",
                "status",
                "issuetype",
                "priority",
            ],
        )
        if not issue:
            raise ValueError(f"JIRA 找不到 ticket: {ticket_key}")

        fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
        summary = str(fields.get("summary") or "").strip()
        description = str(fields.get("description") or "").strip()
        components = [
            str(item.get("name") or "").strip()
            for item in (fields.get("components") or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        server_url = (self.settings.jira.server_url or "").rstrip("/")
        ticket_url = f"{server_url}/browse/{ticket_key}" if server_url else None

        payload = {
            "ticket_key": ticket_key,
            "summary": summary,
            "description": description,
            "components": components,
            "url": ticket_url,
            "raw": issue,
        }

        def _persist(sync_db: Session) -> None:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            session.ticket_key = ticket_key
            self._set_session_phase(
                session,
                phase=HelperPhase.REQUIREMENT,
                phase_status=HelperPhaseStatus.IDLE,
                status=HelperSessionStatus.ACTIVE,
                enforce_transition=True,
            )
            self._upsert_draft_sync(
                sync_db,
                session_id=session.id,
                phase="jira_ticket",
                markdown=None,
                payload=payload,
                increment_version=True,
            )
            sync_db.commit()

        await run_sync(self.db, _persist)
        return HelperTicketSummaryResponse(**payload)

    # ---------- LLM: requirement normalization ----------
    def _build_requirement_normalization_prompt(
        self,
        *,
        review_locale: str,
        ticket_key: str,
        summary: str,
        description: str,
        components: Sequence[str],
    ) -> str:
        components_text = ", ".join([item for item in components if item]) or "N/A"
        review_label = _locale_label(review_locale)
        return (
            "你是資深 QA 需求整理助手。\n"
            f"請把以下 JIRA 內容整理成一份可編輯 Markdown，輸出語言使用 {review_label}。\n"
            "目標：將非結構化的描述轉換為結構清晰、語意明確的規格文件，供後續測試分析使用。\n\n"
            "【基本規則】\n"
            "1. 只做內容辨識、統整、格式化，不要新增不存在的需求。\n"
            "2. 若內容有多語系，請統一語言並保留關鍵名詞。\n"
            "3. 保留 User Story、AC、Scenario 的層級結構。\n\n"
            "【資料結構化規則】（關鍵）\n"
            "1. **欄位定義轉清單**：若原文包含「欄位列表」、「參數定義」或「複雜表格」（如 TCG-93178 的 Reference），**請勿使用 Markdown Table**。請將其轉換為「結構化清單」格式（如下例），以避免表格跑版或錯位。\n"
            "   [範例]\n"
            "   ### 欄位名稱\n"
            "   - 新增欄位 (New): Yes/No\n"
            "   - 可排序 (Sortable): Yes/No\n"
            "   - 邏輯: ...\n"
            "2. **屬性顯性化**：將表格中的簡寫符號（如 'v'、'✓'、打勾）轉換為明確的 'Yes'；空白轉換為 'No'。\n"
            "3. **修復斷行**：若原文是 Excel 複製貼上的破碎文字，請根據邏輯將標題與數值重新對齊，合併為單一物件描述。\n"
            "4. **邏輯保留**：若有「2025xxxx edited」等變更註記，必須保留在該欄位的描述中。\n\n"
            "【輸出限制】\n"
            "輸出僅限 Markdown，不要 code fence。\n\n"
            f"Ticket: {ticket_key}\n"
            f"Summary: {summary}\n"
            f"Components: {components_text}\n\n"
            "Description:\n"
            f"{description or '(empty)'}\n"
        )

    @staticmethod
    def _build_json_repair_prompt(
        *,
        review_language: str,
        stage_name: str,
        schema_example: str,
        raw_content: str,
    ) -> str:
        payload = (raw_content or "").strip()
        if len(payload) > 12000:
            payload = payload[:12000] + "\n...(truncated by system)..."
        return (
            f"你是 JSON 修復器。請使用 {review_language}。\n"
            f"目標：把以下 {stage_name} 內容修復為「可被 JSON.parse 成功解析」的單一 JSON 物件。\n"
            "必須遵守：\n"
            "- 只輸出 JSON，不能有 Markdown、code fence、說明文字\n"
            "- 修復缺逗號、未關閉字串、尾逗號、字串中的未跳脫換行\n"
            "- 不可杜撰新需求；只做語法修復與最小必要結構補全\n"
            "- 若字串內需要換行，使用 \\\\n\n"
            f"Schema 參考:\n{schema_example}\n\n"
            "待修復內容：\n"
            f"{payload}\n"
        )

    @staticmethod
    def _build_json_regenerate_prompt(
        *,
        original_prompt: str,
        review_language: str,
        stage_name: str,
        schema_example: str,
    ) -> str:
        return (
            f"{original_prompt}\n\n"
            "【系統補充要求】\n"
            f"- 你上一輪 {stage_name} 輸出可能因 token 長度被截斷或 JSON 格式錯誤。\n"
            f"- 請使用 {review_language}，從頭重新輸出「完整且可解析」的單一 JSON 物件。\n"
            "- 嚴禁輸出 Markdown/code fence/前後說明文字。\n"
            "- 嚴禁省略逗號、尾逗號、未關閉字串、未跳脫換行。\n"
            "- 若內容過長，優先縮短句子，不可刪除條目，不可輸出片段。\n"
            "- 只輸出 JSON。\n\n"
            f"Schema 參考:\n{schema_example}\n"
        )

    @staticmethod
    def _is_likely_truncated_finish_reason(finish_reason: Optional[str]) -> bool:
        normalized = str(finish_reason or "").strip().lower()
        return normalized in {
            "length",
            "max_tokens",
            "max_output_tokens",
            "token_limit",
        }

    def _resolve_stage_model_for_log(
        self,
        stage: Literal["analysis", "coverage", "testcase", "audit"],
    ) -> str:
        stage_for_lookup = "analysis" if stage == "coverage" else stage
        resolver = getattr(self.llm_service, "resolve_stage_model_id", None)
        if callable(resolver):
            try:
                resolved = str(resolver(stage_for_lookup) or "").strip()
                if resolved:
                    return resolved
            except Exception:
                pass
        stage_cfg = getattr(self.settings.ai.jira_testcase_helper.models, stage_for_lookup, None)
        configured = str(getattr(stage_cfg, "model", "") or "").strip()
        if configured:
            return configured
        return "unknown"

    def _log_stage_model_call(
        self,
        *,
        stage: Literal["analysis", "coverage", "testcase", "audit"],
        stage_name: str,
        call_label: str,
        max_tokens: Optional[int] = None,
    ) -> None:
        logger.info(
            "%s %s 呼叫 LLM: stage=%s model=%s max_tokens=%s",
            stage_name,
            call_label,
            stage,
            self._resolve_stage_model_for_log(stage),
            max_tokens if max_tokens is not None else "unset(default)",
        )

    async def _call_stage_preferring_json(
        self,
        *,
        stage: Literal["analysis", "coverage", "testcase", "audit"],
        prompt: str,
        max_tokens: Optional[int] = None,
    ) -> Any:
        call_kwargs: Dict[str, Any] = {
            "stage": stage,
            "prompt": prompt,
            "expect_json": True,
        }
        if max_tokens is not None:
            call_kwargs["max_tokens"] = max_tokens
        try:
            return await self.llm_service.call_stage(**call_kwargs)
        except TypeError as exc:
            # 測試替身可能尚未實作 expect_json 參數，向下相容。
            if "expect_json" not in str(exc):
                raise
            fallback_kwargs: Dict[str, Any] = {"stage": stage, "prompt": prompt}
            if max_tokens is not None:
                fallback_kwargs["max_tokens"] = max_tokens
            return await self.llm_service.call_stage(**fallback_kwargs)

    async def _call_json_stage_with_retry(
        self,
        *,
        stage: Literal["analysis", "coverage", "testcase", "audit"],
        prompt: str,
        review_language: str,
        stage_name: str,
        schema_example: str,
    ) -> Dict[str, Any]:
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        cost = 0.0
        cost_note = ""
        response_id: Optional[str] = None
        regenerate_applied = False
        repair_applied = False

        def _accumulate(result: Any) -> None:
            nonlocal usage, cost, cost_note, response_id
            usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0)
                + result.usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0)
                + result.usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
                + result.usage.get("total_tokens", 0),
            }
            cost += float(result.cost or 0.0)
            response_id = result.response_id or response_id
            if cost_note or result.cost_note:
                cost_note = "（含未知費用）"

        async def _call_stage_with_empty_tolerance(
            *,
            prompt_text: str,
            call_label: str,
        ) -> Optional[Any]:
            self._log_stage_model_call(
                stage=stage,
                stage_name=stage_name,
                call_label=call_label,
            )
            try:
                result = await self._call_stage_preferring_json(
                    stage=stage,
                    prompt=prompt_text,
                )
            except RuntimeError as exc:
                if "OpenRouter 回傳內容為空" not in str(exc):
                    raise
                logger.warning("%s %s 發生空內容回應，將進入補救流程", stage_name, call_label)
                return None
            _accumulate(result)
            return result

        parsed: Any = None
        parse_error: Optional[ValueError] = None

        first_result = await _call_stage_with_empty_tolerance(
            prompt_text=prompt,
            call_label="初次呼叫",
        )
        first_finish_reason = (
            getattr(first_result, "finish_reason", None)
            if first_result is not None
            else None
        )
        first_truncated = self._is_likely_truncated_finish_reason(first_finish_reason)
        if first_result is None:
            parse_error = ValueError("OpenRouter 回傳內容為空")
        else:
            try:
                parsed = JiraTestCaseHelperLLMService.parse_json_payload(first_result.content)
            except ValueError as first_exc:
                parse_error = first_exc
        if first_truncated:
            parse_error = parse_error or ValueError("LLM 回應可能因長度截斷")

        regenerate_result: Optional[Any] = None
        if parse_error is not None:
            regenerate_applied = True
            regenerate_prompt = self._build_json_regenerate_prompt(
                original_prompt=prompt,
                review_language=review_language,
                stage_name=stage_name,
                schema_example=schema_example,
            )
            regenerate_result = await _call_stage_with_empty_tolerance(
                prompt_text=regenerate_prompt,
                call_label="完整重生呼叫",
            )
            if regenerate_result is None:
                parse_error = ValueError("OpenRouter 回傳內容為空")
            else:
                try:
                    parsed = JiraTestCaseHelperLLMService.parse_json_payload(
                        regenerate_result.content
                    )
                    parse_error = None
                except ValueError as regenerate_exc:
                    parse_error = regenerate_exc
                if self._is_likely_truncated_finish_reason(
                    getattr(regenerate_result, "finish_reason", None)
                ):
                    parse_error = parse_error or ValueError("LLM 回應可能因長度截斷")

        if parse_error is not None:
            repair_applied = True
            logger.warning("%s 重生後仍解析失敗，改用 JSON repair: %s", stage_name, parse_error)
            repair_prompt = self._build_json_repair_prompt(
                review_language=review_language,
                stage_name=stage_name,
                schema_example=schema_example,
                raw_content=(
                    regenerate_result.content
                    if regenerate_result is not None
                    else (first_result.content if first_result is not None else "{}")
                ),
            )
            repair_result = await _call_stage_with_empty_tolerance(
                prompt_text=repair_prompt,
                call_label="JSON repair 呼叫",
            )
            if repair_result is None:
                raise ValueError(f"{stage_name} 回傳 JSON 解析失敗: OpenRouter 回傳內容為空")
            try:
                parsed = JiraTestCaseHelperLLMService.parse_json_payload(repair_result.content)
            except ValueError as repair_exc:
                raise ValueError(f"{stage_name} 回傳 JSON 解析失敗: {repair_exc}") from repair_exc

        if not isinstance(parsed, dict):
            raise ValueError(f"{stage_name} 回傳 JSON 結構錯誤")

        return {
            "payload_raw": parsed,
            "usage": usage,
            "cost": cost,
            "cost_note": cost_note,
            "response_id": response_id,
            "regenerate_applied": regenerate_applied,
            "repair_applied": repair_applied,
        }

    @staticmethod
    def _merge_stage_call_metrics(
        base_call: Dict[str, Any],
        extra_call: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(base_call or {})
        base_usage = dict(merged.get("usage") or {})
        extra_usage = dict(extra_call.get("usage") or {})
        merged["usage"] = {
            "prompt_tokens": int(base_usage.get("prompt_tokens", 0))
            + int(extra_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(base_usage.get("completion_tokens", 0))
            + int(extra_usage.get("completion_tokens", 0)),
            "total_tokens": int(base_usage.get("total_tokens", 0))
            + int(extra_usage.get("total_tokens", 0)),
        }
        merged["cost"] = float(merged.get("cost") or 0.0) + float(
            extra_call.get("cost") or 0.0
        )
        merged["cost_note"] = (
            "（含未知費用）"
            if merged.get("cost_note") or extra_call.get("cost_note")
            else ""
        )
        merged["response_id"] = extra_call.get("response_id") or merged.get("response_id")
        merged["regenerate_applied"] = bool(merged.get("regenerate_applied")) or bool(
            extra_call.get("regenerate_applied")
        )
        merged["repair_applied"] = bool(merged.get("repair_applied")) or bool(
            extra_call.get("repair_applied")
        )
        return merged

    @staticmethod
    def _extract_coverage_payload(raw_payload: Any) -> Dict[str, Any]:
        if isinstance(raw_payload, dict) and isinstance(raw_payload.get("coverage"), dict):
            return raw_payload.get("coverage") or {}
        if not isinstance(raw_payload, dict):
            return {}
        has_seed = isinstance(raw_payload.get("seed"), list)
        has_sec = isinstance(raw_payload.get("sec"), list)
        has_trace = isinstance(raw_payload.get("trace"), dict)
        if has_seed or has_sec or has_trace:
            return raw_payload
        return {}

    @staticmethod
    def _to_text_list(raw_value: Any) -> List[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            return [stripped] if stripped else []
        return []

    @staticmethod
    def _normalize_bool_value(raw_value: Any) -> bool:
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, (int, float)):
            return raw_value != 0
        normalized = str(raw_value or "").strip().lower()
        return normalized in TRUTHY_TEXT

    @staticmethod
    def _normalize_fixed_lr(raw_value: Any) -> str:
        normalized = str(raw_value or "").strip().lower()
        if normalized in {"left", "l", "左"}:
            return "left"
        if normalized in {"right", "r", "右"}:
            return "right"
        return "none"

    @staticmethod
    def _normalize_trace_payload(raw_value: Any) -> Dict[str, str]:
        if isinstance(raw_value, dict):
            source = str(raw_value.get("source") or "").strip()
            snippet = str(raw_value.get("snippet") or "").strip()
            row = str(raw_value.get("row") or "").strip()
            result = {
                "source": source or "unknown",
                "snippet": snippet,
            }
            if row:
                result["row"] = row
            return result
        return {"source": "unknown", "snippet": ""}

    @staticmethod
    def _compact_text(value: Any, limit: int = 240) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    @staticmethod
    def _strip_inline_markdown(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
        value = re.sub(r"__(.+?)__", r"\1", value)
        value = re.sub(r"`(.+?)`", r"\1", value)
        value = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", value)
        value = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", value)
        return value

    def _extract_inline_format_markers(
        self,
        *,
        text: str,
        src_id: str,
        start_index: int,
    ) -> List[Dict[str, str]]:
        markers: List[Dict[str, str]] = []
        idx = int(start_index)
        for pattern, marker in [
            (r"\*\*(.+?)\*\*", "BOLD"),
            (r"__(.+?)__", "BOLD"),
            (r"`(.+?)`", "CODE"),
            (r"(?<!\*)\*([^*\n]+)\*(?!\*)", "ITALIC"),
            (r"(?<!_)_([^_\n]+)_(?!_)", "ITALIC"),
        ]:
            for matched in re.finditer(pattern, str(text or "")):
                content = self._compact_text(matched.group(1), limit=160)
                if not content:
                    continue
                markers.append(
                    {
                        "pid": f"FMT-{idx:03d}",
                        "k": "fmt",
                        "m": marker,
                        "v": content,
                        "src": src_id,
                    }
                )
                idx += 1
        return markers

    @staticmethod
    def _split_chunk_sentences(raw_text: Any) -> List[str]:
        text = str(raw_text or "").replace("\r", "\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        merged = "\n".join(lines)
        segments = re.split(r"(?<=[。！？!?；;])\s+|\n+", merged)
        result: List[str] = []
        for segment in segments:
            normalized = re.sub(r"\s+", " ", str(segment or "").strip())
            if normalized:
                result.append(normalized)
        return result

    def _build_requirement_source_packets(
        self,
        requirement_markdown: str,
        *,
        ticket_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        lines = [str(line).rstrip() for line in str(requirement_markdown or "").splitlines()]
        packets: List[Dict[str, Any]] = []
        format_packets: List[Dict[str, str]] = []
        chunks: List[Dict[str, Any]] = []
        text_idx = 1
        table_idx = 1
        format_idx = 1
        idx = 0

        chunk_id_counter: Dict[str, int] = {}

        def _append_chunk(chunk_id: str, title: str, content: Any) -> None:
            sentences = self._split_chunk_sentences(content)
            if not sentences:
                return
            base_id = str(chunk_id or "chunk").strip() or "chunk"
            next_count = chunk_id_counter.get(base_id, 0) + 1
            chunk_id_counter[base_id] = next_count
            resolved_chunk_id = base_id if next_count == 1 else f"{base_id}_{next_count:03d}"
            chunks.append(
                {
                    "chunk_id": resolved_chunk_id,
                    "title": str(title or resolved_chunk_id).strip() or resolved_chunk_id,
                    "sentences": [
                        {"sid": sid, "text": sentence} for sid, sentence in enumerate(sentences)
                    ],
                }
            )

        def _split_table_row(line: str) -> List[str]:
            stripped = line.strip()
            if stripped.startswith("|"):
                stripped = stripped[1:]
            if stripped.endswith("|"):
                stripped = stripped[:-1]
            return [self._compact_text(cell.strip(), limit=180) for cell in stripped.split("|")]

        def _is_separator(line: str) -> bool:
            normalized = line.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
            return not normalized

        while idx < len(lines):
            line = lines[idx]
            if (
                idx + 1 < len(lines)
                and "|" in line
                and "|" in lines[idx + 1]
                and _is_separator(lines[idx + 1])
            ):
                headers = _split_table_row(line)
                row_idx = idx + 2
                rows: List[List[str]] = []
                while row_idx < len(lines):
                    row_line = lines[row_idx]
                    if "|" not in row_line:
                        break
                    row_cells = _split_table_row(row_line)
                    if row_cells:
                        rows.append(row_cells)
                    row_idx += 1
                table_pid = f"TBL-{table_idx:03d}"
                packets.append(
                    {
                        "pid": table_pid,
                        "k": "tbl",
                        "h": headers,
                        "r": rows,
                    }
                )
                flat_cells = headers + [cell for row in rows for cell in row]
                for cell in flat_cells:
                    markers = self._extract_inline_format_markers(
                        text=cell,
                        src_id=table_pid,
                        start_index=format_idx,
                    )
                    format_idx += len(markers)
                    format_packets.extend(markers)
                table_idx += 1
                idx = row_idx
                continue

            plain = self._compact_text(self._strip_inline_markdown(line), limit=400)
            if plain:
                text_pid = f"TXT-{text_idx:03d}"
                packets.append(
                    {
                        "pid": text_pid,
                        "k": "txt",
                        "v": plain,
                    }
                )
                markers = self._extract_inline_format_markers(
                    text=line,
                    src_id=text_pid,
                    start_index=format_idx,
                )
                format_idx += len(markers)
                format_packets.extend(markers)
                text_idx += 1
            idx += 1

        ticket = ticket_payload if isinstance(ticket_payload, dict) else {}
        _append_chunk("desc", "Description", ticket.get("description") or requirement_markdown)
        _append_chunk("ac", "Acceptance Criteria", ticket.get("acceptance_criteria"))

        comments_raw = ticket.get("comments") if isinstance(ticket.get("comments"), list) else []
        for comment_idx, comment in enumerate(comments_raw, start=1):
            if isinstance(comment, dict):
                comment_text = (
                    comment.get("body")
                    or comment.get("text")
                    or comment.get("content")
                    or comment.get("comment")
                    or ""
                )
            else:
                comment_text = str(comment or "")
            _append_chunk(f"comment_{comment_idx:03d}", "Comment", comment_text)

        attachments_raw = (
            ticket.get("attachments_metadata")
            if isinstance(ticket.get("attachments_metadata"), list)
            else []
        )
        for attachment_idx, attachment in enumerate(attachments_raw, start=1):
            if isinstance(attachment, dict):
                attachment_text = " | ".join(
                    [
                        str(attachment.get("title") or "").strip(),
                        str(attachment.get("name") or "").strip(),
                        str(attachment.get("summary") or "").strip(),
                        str(attachment.get("description") or "").strip(),
                    ]
                ).strip(" |")
            else:
                attachment_text = str(attachment or "")
            _append_chunk(f"attachment_{attachment_idx:03d}", "Attachment", attachment_text)

        links_raw = ticket.get("links") if isinstance(ticket.get("links"), list) else []
        for link_idx, link in enumerate(links_raw, start=1):
            if isinstance(link, dict):
                link_text = " | ".join(
                    [
                        str(link.get("title") or "").strip(),
                        str(link.get("url") or "").strip(),
                        str(link.get("description") or "").strip(),
                    ]
                ).strip(" |")
            else:
                link_text = str(link or "")
            _append_chunk(f"link_{link_idx:03d}", "Link", link_text)

        for packet in packets:
            if not isinstance(packet, dict):
                continue
            packet_kind = str(packet.get("k") or "").strip()
            if packet_kind == "txt":
                _append_chunk(packet.get("pid") or "txt", "Requirement Text", packet.get("v"))
            elif packet_kind == "tbl":
                header_text = " | ".join(
                    [str(item).strip() for item in (packet.get("h") or []) if str(item).strip()]
                )
                row_text = " ".join(
                    " | ".join(str(cell).strip() for cell in row if str(cell).strip())
                    for row in (packet.get("r") or [])
                    if isinstance(row, list)
                )
                _append_chunk(
                    packet.get("pid") or "tbl",
                    "Requirement Table",
                    f"{header_text}\n{row_text}".strip(),
                )

        packets.extend(format_packets)
        return {
            "packets": packets,
            "chunks": chunks,
            "meta": {
                "packet_count": len(packets),
                "text_count": len([p for p in packets if p.get("k") == "txt"]),
                "table_count": len([p for p in packets if p.get("k") == "tbl"]),
                "format_count": len([p for p in packets if p.get("k") == "fmt"]),
                "chunk_count": len(chunks),
                "sentence_count": sum(
                    len(chunk.get("sentences") or [])
                    for chunk in chunks
                    if isinstance(chunk, dict)
                ),
            },
        }

    def _parse_reference_columns_from_markdown(
        self,
        requirement_markdown: str,
    ) -> List[Dict[str, Any]]:
        lines = [str(line).rstrip() for line in str(requirement_markdown or "").splitlines()]
        if not lines:
            return []

        def _split_table_row(line: str) -> List[str]:
            stripped = line.strip()
            if stripped.startswith("|"):
                stripped = stripped[1:]
            if stripped.endswith("|"):
                stripped = stripped[:-1]
            return [cell.strip() for cell in stripped.split("|")]

        def _is_separator(line: str) -> bool:
            normalized = line.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")
            return not normalized

        def _find_value(
            row_map: Dict[str, str],
            *,
            keys: Sequence[str],
        ) -> str:
            for key in keys:
                for header, value in row_map.items():
                    if key in header:
                        return value
            return ""

        result: List[Dict[str, Any]] = []
        index = 0
        while index + 2 < len(lines):
            header_line = lines[index]
            separator_line = lines[index + 1]
            if "|" not in header_line or "|" not in separator_line or not _is_separator(separator_line):
                index += 1
                continue

            headers = _split_table_row(header_line)
            if len(headers) < 2:
                index += 1
                continue

            row_index = index + 2
            parsed_any_row = False
            while row_index < len(lines):
                row_line = lines[row_index]
                if "|" not in row_line:
                    break
                cells = _split_table_row(row_line)
                if len(cells) < 2:
                    row_index += 1
                    continue
                while len(cells) < len(headers):
                    cells.append("")
                row_map = {
                    str(headers[col]).strip().lower(): str(cells[col]).strip()
                    for col in range(min(len(headers), len(cells)))
                }

                column_name = _find_value(
                    row_map,
                    keys=["欄位", "column", "field", "name", "項目", "title"],
                ) or cells[0]
                column_name = str(column_name or "").strip()
                if column_name:
                    format_rules = []
                    format_value = _find_value(row_map, keys=["format", "格式", "style", "樣式"])
                    if format_value:
                        format_rules = [
                            item.strip()
                            for item in re.split(r"[;,，、\n]", format_value)
                            if item.strip()
                        ]

                    result.append(
                        {
                            "rid": f"REF-{len(result) + 1:03d}",
                            "column": column_name,
                            "new_column": self._normalize_bool_value(
                                _find_value(row_map, keys=["new", "新增"])
                            ),
                            "sortable": self._normalize_bool_value(
                                _find_value(row_map, keys=["sortable", "排序"])
                            ),
                            "fixed_lr": self._normalize_fixed_lr(
                                _find_value(row_map, keys=["fixed", "固定", "lr"])
                            ),
                            "format_rules": format_rules,
                            "cross_page_param": _find_value(
                                row_map, keys=["cross", "跨頁", "param", "參數"]
                            ),
                            "edit_note": _find_value(
                                row_map, keys=["edit", "備註", "註記", "note"]
                            ),
                            "expected": self._to_text_list(
                                _find_value(row_map, keys=["expected", "預期", "result"])
                            ),
                            "trace": {
                                "source": "reference_table_markdown",
                                "row": str(row_index - index - 1),
                                "snippet": row_line.strip(),
                            },
                        }
                    )
                    parsed_any_row = True
                row_index += 1

            index = row_index if parsed_any_row else (index + 1)
        return result

    @staticmethod
    def _build_chunks_index(source_chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        index: List[Dict[str, Any]] = []
        for chunk in source_chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            sentence_count = len(
                [item for item in (chunk.get("sentences") or []) if isinstance(item, dict)]
            )
            if sentence_count <= 0:
                continue
            index.append(
                {
                    "chunk_id": chunk_id,
                    "title": str(chunk.get("title") or chunk_id).strip() or chunk_id,
                    "sentence_count": sentence_count,
                }
            )
        return index

    def _first_chunk_source_ref(
        self,
        source_chunks: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        for chunk in source_chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            sentences = [
                item for item in (chunk.get("sentences") or []) if isinstance(item, dict)
            ]
            if not chunk_id or not sentences:
                continue
            first_sentence = str(sentences[0].get("text") or "").strip()
            return [
                {
                    "chunk_id": chunk_id,
                    "sentence_ids": [0],
                    "quote": self._compact_text(first_sentence, limit=200),
                }
            ]
        return [{"chunk_id": "desc", "sentence_ids": [0], "quote": ""}]

    def _match_source_refs_by_snippet(
        self,
        *,
        source_chunks: Sequence[Dict[str, Any]],
        snippet: str,
    ) -> List[Dict[str, Any]]:
        normalized_snippet = self._compact_text(snippet, limit=300)
        if not normalized_snippet:
            return self._first_chunk_source_ref(source_chunks)
        lowered_snippet = normalized_snippet.lower()
        for chunk in source_chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            sentences = [
                item for item in (chunk.get("sentences") or []) if isinstance(item, dict)
            ]
            for sentence in sentences:
                text = str(sentence.get("text") or "").strip()
                if not text:
                    continue
                sid = int(sentence.get("sid") or 0)
                lowered_text = text.lower()
                if lowered_snippet in lowered_text or lowered_text in lowered_snippet:
                    return [
                        {
                            "chunk_id": chunk_id,
                            "sentence_ids": [max(0, sid)],
                            "quote": self._compact_text(text, limit=200),
                        }
                    ]
        return self._first_chunk_source_ref(source_chunks)

    def _normalize_source_refs(
        self,
        *,
        raw_source_refs: Any,
        source_chunks: Sequence[Dict[str, Any]],
        fallback_snippet: str = "",
    ) -> List[Dict[str, Any]]:
        chunk_index = {
            str(item.get("chunk_id") or "").strip(): int(item.get("sentence_count") or 0)
            for item in self._build_chunks_index(source_chunks)
            if isinstance(item, dict)
        }
        normalized_refs: List[Dict[str, Any]] = []
        if isinstance(raw_source_refs, list):
            for ref in raw_source_refs:
                if not isinstance(ref, dict):
                    continue
                chunk_id = str(ref.get("chunk_id") or "").strip()
                sentence_ids_raw = ref.get("sentence_ids")
                if isinstance(sentence_ids_raw, list):
                    sentence_ids = [
                        int(v)
                        for v in sentence_ids_raw
                        if str(v).strip().isdigit()
                    ]
                elif str(sentence_ids_raw or "").strip().isdigit():
                    sentence_ids = [int(sentence_ids_raw)]
                else:
                    sentence_ids = []
                if not chunk_id or not sentence_ids:
                    continue
                sentence_count = chunk_index.get(chunk_id, 0)
                if sentence_count <= 0:
                    continue
                bounded_sentence_ids = [
                    sid for sid in sentence_ids if 0 <= sid < sentence_count
                ]
                if not bounded_sentence_ids:
                    continue
                normalized_refs.append(
                    {
                        "chunk_id": chunk_id,
                        "sentence_ids": self._unique_preserve(
                            [str(sid) for sid in bounded_sentence_ids]
                        ),
                        "quote": self._compact_text(ref.get("quote"), limit=200),
                    }
                )
        if normalized_refs:
            result: List[Dict[str, Any]] = []
            for ref in normalized_refs:
                sentence_ids = [
                    int(value)
                    for value in (ref.get("sentence_ids") or [])
                    if str(value).strip().isdigit()
                ]
                result.append(
                    {
                        "chunk_id": str(ref.get("chunk_id") or "").strip(),
                        "sentence_ids": sentence_ids,
                        "quote": str(ref.get("quote") or "").strip(),
                    }
                )
            return result
        return self._match_source_refs_by_snippet(
            source_chunks=source_chunks,
            snippet=fallback_snippet,
        )

    def _normalize_ir_coverage_map(
        self,
        *,
        source_chunks: Sequence[Dict[str, Any]],
        covered_refs: Sequence[Dict[str, Any]],
        raw_coverage_map: Any,
    ) -> List[Dict[str, Any]]:
        covered_lookup: Dict[Tuple[str, int], List[str]] = {}
        for ref in covered_refs:
            if not isinstance(ref, dict):
                continue
            chunk_id = str(ref.get("chunk_id") or "").strip()
            sentence_ids = [
                int(v)
                for v in (ref.get("sentence_ids") or [])
                if str(v).strip().isdigit()
            ]
            if not chunk_id:
                continue
            for sid in sentence_ids:
                key = (chunk_id, sid)
                covered_lookup.setdefault(key, []).append("inferred_source_ref")

        normalized_existing: Dict[Tuple[str, int], Dict[str, Any]] = {}
        if isinstance(raw_coverage_map, list):
            for row in raw_coverage_map:
                if not isinstance(row, dict):
                    continue
                chunk_id = str(row.get("chunk_id") or "").strip()
                sentence_id_raw = row.get("sentence_id")
                if not chunk_id or not str(sentence_id_raw).strip().isdigit():
                    continue
                sentence_id = int(sentence_id_raw)
                status = str(row.get("status") or "").strip().lower()
                if status not in {"covered", "ignored"}:
                    continue
                payload: Dict[str, Any] = {
                    "chunk_id": chunk_id,
                    "sentence_id": sentence_id,
                    "status": status,
                }
                if status == "covered":
                    covered_by = row.get("covered_by")
                    if isinstance(covered_by, list):
                        payload["covered_by"] = [
                            str(item).strip() for item in covered_by if str(item).strip()
                        ] or ["model_output"]
                    else:
                        payload["covered_by"] = ["model_output"]
                else:
                    ignored_reason = str(row.get("ignored_reason") or "").strip().lower()
                    payload["ignored_reason"] = (
                        ignored_reason
                        if ignored_reason
                        in {
                            "template",
                            "discussion",
                            "duplicate",
                            "history",
                            "non_requirement",
                            "broken_text",
                            "unknown",
                        }
                        else "non_requirement"
                    )
                normalized_existing[(chunk_id, sentence_id)] = payload

        normalized: List[Dict[str, Any]] = []
        for chunk in source_chunks:
            if not isinstance(chunk, dict):
                continue
            chunk_id = str(chunk.get("chunk_id") or "").strip()
            if not chunk_id:
                continue
            sentences = [
                item for item in (chunk.get("sentences") or []) if isinstance(item, dict)
            ]
            for sentence in sentences:
                sid = int(sentence.get("sid") or 0)
                key = (chunk_id, sid)
                existing = normalized_existing.get(key)
                if existing is not None:
                    normalized.append(existing)
                    continue
                covered_by = covered_lookup.get(key) or []
                if covered_by:
                    normalized.append(
                        {
                            "chunk_id": chunk_id,
                            "sentence_id": sid,
                            "status": "covered",
                            "covered_by": self._unique_preserve(covered_by),
                        }
                    )
                else:
                    normalized.append(
                        {
                            "chunk_id": chunk_id,
                            "sentence_id": sid,
                            "status": "ignored",
                            "ignored_reason": "non_requirement",
                        }
                    )
        return normalized

    def _normalize_requirement_ir_payload(
        self,
        payload: Dict[str, Any],
        *,
        ticket_key: str,
        summary: str,
        components: Sequence[str],
        requirement_markdown: str,
        source_chunks: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        normalized_payload = payload if isinstance(payload, dict) else {}
        normalized_source_chunks = [
            chunk for chunk in (source_chunks or []) if isinstance(chunk, dict)
        ]

        def _make_id(prefix: str, index: int) -> str:
            return f"{prefix}-{index:03d}"

        def _compact_refs(raw_refs: Any, fallback_snippet: str) -> List[Dict[str, Any]]:
            refs = self._normalize_source_refs(
                raw_source_refs=raw_refs,
                source_chunks=normalized_source_chunks,
                fallback_snippet=fallback_snippet,
            )
            return refs or self._first_chunk_source_ref(normalized_source_chunks)

        def _append_covered_refs(
            target: List[Dict[str, Any]],
            refs: Sequence[Dict[str, Any]],
        ) -> None:
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                chunk_id = str(ref.get("chunk_id") or "").strip()
                sentence_ids = [
                    int(v)
                    for v in (ref.get("sentence_ids") or [])
                    if str(v).strip().isdigit()
                ]
                if not chunk_id or not sentence_ids:
                    continue
                target.append(
                    {
                        "chunk_id": chunk_id,
                        "sentence_ids": self._unique_preserve(
                            [str(v) for v in sentence_ids]
                        ),
                        "quote": str(ref.get("quote") or "").strip(),
                    }
                )

        ticket_raw = (
            normalized_payload.get("ticket")
            if isinstance(normalized_payload.get("ticket"), dict)
            else {}
        )
        ticket = {
            "key": str(ticket_raw.get("key") or ticket_key or "").strip(),
            "summary": str(ticket_raw.get("summary") or summary or "").strip(),
            "components": [
                str(item).strip()
                for item in (ticket_raw.get("components") or list(components) or [])
                if str(item).strip()
            ],
        }

        scenarios_raw = normalized_payload.get("scenarios")
        scenarios: List[Dict[str, Any]] = []
        if isinstance(scenarios_raw, list):
            for row in scenarios_raw:
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("rid") or "").strip() or f"REQ-{len(scenarios) + 1:03d}"
                group = str(row.get("g") or row.get("group") or "").strip() or "未分類"
                title = str(row.get("t") or row.get("title") or "").strip()
                ac = self._to_text_list(row.get("ac") or row.get("acceptance"))
                rules = self._to_text_list(row.get("rules"))
                data_points = self._to_text_list(
                    row.get("data_points") or row.get("dataPoints")
                )
                expected = self._to_text_list(row.get("expected") or row.get("exp"))
                src_markers = self._to_text_list(row.get("src"))
                if not title and not ac and not rules and not expected:
                    continue
                trace_payload = self._normalize_trace_payload(row.get("trace"))
                if src_markers and trace_payload.get("source") == "unknown":
                    trace_payload = {
                        "source": "packet_markers",
                        "snippet": "|".join(src_markers[:8]),
                    }
                source_refs = _compact_refs(
                    row.get("source_refs"),
                    trace_payload.get("snippet")
                    or title
                    or " ".join(ac[:2])
                    or " ".join(rules[:2])
                    or " ".join(expected[:2]),
                )
                scenarios.append(
                    {
                        "rid": rid,
                        "g": group,
                        "t": title or "未命名需求",
                        "ac": ac,
                        "rules": rules,
                        "data_points": data_points,
                        "expected": expected,
                        "source_refs": source_refs,
                        "trace": trace_payload,
                    }
                )

        if not scenarios:
            candidate_lines = [
                str(line).strip()
                for line in str(requirement_markdown or "").splitlines()
                if str(line).strip()
            ]
            fallback_title = (
                str(summary or "").strip()
                or (candidate_lines[0] if candidate_lines else "需求整理")
            )
            scenarios = [
                {
                    "rid": "REQ-001",
                    "g": "未分類",
                    "t": fallback_title,
                    "ac": candidate_lines[:6],
                    "rules": [],
                    "data_points": [],
                    "expected": [],
                    "trace": {
                        "source": "fallback_requirement_text",
                        "snippet": fallback_title[:200],
                    },
                    "source_refs": _compact_refs(None, fallback_title),
                }
            ]

        references_raw = normalized_payload.get("reference_columns")
        if not isinstance(references_raw, list):
            references_raw = normalized_payload.get("referenceColumns")
        references: List[Dict[str, Any]] = []
        if isinstance(references_raw, list):
            for row in references_raw:
                if not isinstance(row, dict):
                    continue
                column_name = str(
                    row.get("column")
                    or row.get("name")
                    or row.get("title")
                    or row.get("t")
                    or ""
                ).strip()
                if not column_name:
                    continue
                rid = str(row.get("rid") or "").strip() or f"REF-{len(references) + 1:03d}"
                src_markers = self._to_text_list(row.get("src"))
                trace_payload = self._normalize_trace_payload(row.get("trace"))
                if src_markers and trace_payload.get("source") == "unknown":
                    trace_payload = {
                        "source": "packet_markers",
                        "snippet": "|".join(src_markers[:8]),
                    }
                source_refs = _compact_refs(
                    row.get("source_refs"),
                    trace_payload.get("snippet") or column_name,
                )
                references.append(
                    {
                        "rid": rid,
                        "column": column_name,
                        "new_column": self._normalize_bool_value(
                            row.get("new_column")
                            if "new_column" in row
                            else row.get("new")
                        ),
                        "sortable": self._normalize_bool_value(row.get("sortable")),
                        "fixed_lr": self._normalize_fixed_lr(row.get("fixed_lr")),
                        "format_rules": self._to_text_list(
                            row.get("format_rules") or row.get("format") or row.get("style")
                        ),
                        "cross_page_param": str(row.get("cross_page_param") or "").strip(),
                        "edit_note": str(
                            row.get("edit_note") or row.get("note") or row.get("edited") or ""
                        ).strip(),
                        "expected": self._to_text_list(
                            row.get("expected") or row.get("exp")
                        ),
                        "source_refs": source_refs,
                        "trace": trace_payload,
                    }
                )

        if not references:
            references = self._parse_reference_columns_from_markdown(requirement_markdown)
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                if not reference.get("source_refs"):
                    reference["source_refs"] = _compact_refs(
                        None,
                        str(reference.get("column") or ""),
                    )

        notes = self._to_text_list(normalized_payload.get("notes"))
        trace_index: List[Dict[str, str]] = []
        for item in scenarios:
            trace_index.append(
                {
                    "rid": str(item.get("rid") or ""),
                    "kind": "scenario",
                    "name": str(item.get("t") or ""),
                }
            )
        for item in references:
            trace_index.append(
                {
                    "rid": str(item.get("rid") or ""),
                    "kind": "reference_column",
                    "name": str(item.get("column") or ""),
                }
            )

        actors: List[Dict[str, Any]] = []
        raw_actors = normalized_payload.get("actors")
        if isinstance(raw_actors, list):
            for index, actor in enumerate(raw_actors, start=1):
                if not isinstance(actor, dict):
                    continue
                name = str(actor.get("name") or "").strip()
                actor_type = str(actor.get("type") or "user").strip().lower()
                if actor_type not in {"user", "admin", "system", "external"}:
                    actor_type = "user"
                source_refs = _compact_refs(
                    actor.get("source_refs"),
                    name or "actor",
                )
                actors.append(
                    {
                        "actor_id": str(actor.get("actor_id") or "").strip()
                        or _make_id("ACTOR", index),
                        "name": name or f"Actor {index}",
                        "type": actor_type,
                        "permissions": self._to_text_list(actor.get("permissions")),
                        "source_refs": source_refs,
                    }
                )
        if not actors:
            actors.append(
                {
                    "actor_id": "ACTOR-001",
                    "name": "Default User",
                    "type": "user",
                    "permissions": [],
                    "source_refs": _compact_refs(None, ticket.get("summary") or ticket["key"]),
                }
            )

        entities: List[Dict[str, Any]] = []
        for index, reference in enumerate(references, start=1):
            column_name = str(reference.get("column") or "").strip() or f"欄位{index}"
            source_refs = _compact_refs(
                reference.get("source_refs"),
                column_name,
            )
            entities.append(
                {
                    "entity_id": _make_id("ENT", index),
                    "name": f"Reference::{column_name}",
                    "fields": [
                        {
                            "field_id": _make_id("FIELD", index),
                            "name": column_name,
                            "data_type": "string",
                            "constraints": self._to_text_list(reference.get("format_rules")),
                            "source_refs": source_refs,
                        }
                    ],
                    "source_refs": source_refs,
                }
            )
        if not entities:
            entities.append(
                {
                    "entity_id": "ENT-001",
                    "name": "TicketRequirement",
                    "fields": [
                        {
                            "field_id": "FIELD-001",
                            "name": "description",
                            "data_type": "string",
                            "constraints": [],
                            "source_refs": _compact_refs(None, ticket.get("summary")),
                        }
                    ],
                    "source_refs": _compact_refs(None, ticket.get("summary")),
                }
            )

        flows: List[Dict[str, Any]] = []
        for index, scenario in enumerate(scenarios, start=1):
            source_refs = _compact_refs(
                scenario.get("source_refs"),
                str(scenario.get("t") or ""),
            )
            step_texts = (
                self._to_text_list(scenario.get("ac"))
                + self._to_text_list(scenario.get("rules"))
                + self._to_text_list(scenario.get("expected"))
            )
            if not step_texts:
                step_texts = [str(scenario.get("t") or "需求步驟").strip()]
            steps: List[Dict[str, Any]] = []
            for step_index, step_text in enumerate(step_texts, start=1):
                steps.append(
                    {
                        "step_id": _make_id("STEP", ((index - 1) * 20) + step_index),
                        "action": step_text,
                        "expected_outcome": step_text,
                        "variants": [],
                        "source_refs": source_refs,
                    }
                )
            flows.append(
                {
                    "flow_id": _make_id("FLOW", index),
                    "name": str(scenario.get("t") or "").strip() or f"Flow {index}",
                    "actor_ids": [actors[0]["actor_id"]],
                    "preconditions": [],
                    "steps": steps,
                    "postconditions": [],
                    "source_refs": source_refs,
                }
            )

        rules: List[Dict[str, Any]] = []
        for scenario in scenarios:
            related_flow = next(
                (
                    flow.get("flow_id")
                    for flow in flows
                    if str(flow.get("name") or "").strip()
                    == str(scenario.get("t") or "").strip()
                ),
                "",
            )
            for statement in self._to_text_list(scenario.get("rules")):
                source_refs = _compact_refs(
                    scenario.get("source_refs"),
                    statement,
                )
                rules.append(
                    {
                        "rule_id": _make_id("RULE", len(rules) + 1),
                        "type": "other",
                        "statement": statement,
                        "scope": "cross",
                        "related_entity_ids": [],
                        "related_flow_ids": [related_flow] if related_flow else [],
                        "acceptance_criteria_hint": "",
                        "source_refs": source_refs,
                    }
                )
        for reference in references:
            column_name = str(reference.get("column") or "").strip()
            source_refs = _compact_refs(reference.get("source_refs"), column_name)
            if reference.get("sortable"):
                rules.append(
                    {
                        "rule_id": _make_id("RULE", len(rules) + 1),
                        "type": "sorting",
                        "statement": f"{column_name} 需支援排序",
                        "scope": "frontend",
                        "related_entity_ids": [],
                        "related_flow_ids": [],
                        "acceptance_criteria_hint": "",
                        "source_refs": source_refs,
                    }
                )
            if str(reference.get("fixed_lr") or "none").strip().lower() in {"left", "right"}:
                rules.append(
                    {
                        "rule_id": _make_id("RULE", len(rules) + 1),
                        "type": "ui_display",
                        "statement": (
                            f"{column_name} 為固定欄位（{reference.get('fixed_lr')}），"
                            "水平捲動時需保持可見"
                        ),
                        "scope": "frontend",
                        "related_entity_ids": [],
                        "related_flow_ids": [],
                        "acceptance_criteria_hint": "",
                        "source_refs": source_refs,
                    }
                )
            for expected_line in self._to_text_list(reference.get("expected")):
                rules.append(
                    {
                        "rule_id": _make_id("RULE", len(rules) + 1),
                        "type": "ui_display",
                        "statement": expected_line,
                        "scope": "frontend",
                        "related_entity_ids": [],
                        "related_flow_ids": [],
                        "acceptance_criteria_hint": "",
                        "source_refs": source_refs,
                    }
                )

        non_functional: List[Dict[str, Any]] = []
        for note in notes:
            lowered = note.lower()
            category = ""
            if any(keyword in lowered for keyword in ["效能", "performance", "latency", "timeout"]):
                category = "performance"
            elif any(keyword in lowered for keyword in ["安全", "security", "權限", "auth"]):
                category = "security"
            elif any(keyword in lowered for keyword in ["相容", "compat", "browser"]):
                category = "compatibility"
            if not category:
                continue
            non_functional.append(
                {
                    "nfr_id": _make_id("NFR", len(non_functional) + 1),
                    "category": category,
                    "statement": note,
                    "metric": "N/A",
                    "source_refs": _compact_refs(None, note),
                }
            )

        out_of_scope: List[Dict[str, Any]] = []
        for raw_item in normalized_payload.get("out_of_scope") or []:
            if not isinstance(raw_item, dict):
                continue
            item = str(raw_item.get("item") or "").strip()
            reason = str(raw_item.get("reason") or "").strip()
            if not item or not reason:
                continue
            out_of_scope.append(
                {
                    "item": item,
                    "reason": reason,
                    "source_refs": _compact_refs(raw_item.get("source_refs"), item),
                }
            )

        open_questions: List[Dict[str, Any]] = []
        for raw_item in normalized_payload.get("open_questions") or []:
            if not isinstance(raw_item, dict):
                continue
            question = str(raw_item.get("question") or "").strip()
            impact = str(raw_item.get("impact") or "").strip().lower()
            if impact not in {"blocks_testing", "reduces_coverage", "minor"}:
                impact = "minor"
            if not question:
                continue
            open_questions.append(
                {
                    "question": question,
                    "impact": impact,
                    "source_refs": _compact_refs(raw_item.get("source_refs"), question),
                }
            )
        if not open_questions:
            for scenario in scenarios:
                title = str(scenario.get("t") or "").strip()
                if "?" not in title and "？" not in title:
                    continue
                open_questions.append(
                    {
                        "question": title,
                        "impact": "minor",
                        "source_refs": _compact_refs(
                            scenario.get("source_refs"),
                            title,
                        ),
                    }
                )

        ambiguities: List[Dict[str, Any]] = []
        for raw_item in normalized_payload.get("ambiguities") or []:
            if not isinstance(raw_item, dict):
                continue
            issue = str(raw_item.get("issue") or "").strip()
            candidates = self._to_text_list(raw_item.get("candidates"))
            if not issue or not candidates:
                continue
            ambiguities.append(
                {
                    "issue": issue,
                    "candidates": candidates,
                    "source_refs": _compact_refs(raw_item.get("source_refs"), issue),
                }
            )

        covered_refs: List[Dict[str, Any]] = []
        for item in scenarios:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in references:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in actors:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in entities:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
            for field in item.get("fields") or []:
                if isinstance(field, dict):
                    _append_covered_refs(covered_refs, field.get("source_refs") or [])
        for item in flows:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
            for step in item.get("steps") or []:
                if isinstance(step, dict):
                    _append_covered_refs(covered_refs, step.get("source_refs") or [])
        for item in rules:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in non_functional:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in out_of_scope:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in open_questions:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])
        for item in ambiguities:
            _append_covered_refs(covered_refs, item.get("source_refs") or [])

        chunks_index = self._build_chunks_index(normalized_source_chunks)
        coverage_map = self._normalize_ir_coverage_map(
            source_chunks=normalized_source_chunks,
            covered_refs=covered_refs,
            raw_coverage_map=normalized_payload.get("coverage_map"),
        )
        ticket_meta = {
            "ticket_id": ticket["key"] or ticket_key or "UNKNOWN",
            "summary": ticket["summary"] or summary or "N/A",
            "components": ticket["components"],
            "labels": self._to_text_list(ticket_raw.get("labels")),
            "platforms": self._to_text_list(ticket_raw.get("platforms")),
        }

        return {
            "ir_version": "1.0",
            "ticket_meta": ticket_meta,
            "chunks_index": chunks_index,
            "actors": actors,
            "entities": entities,
            "flows": flows,
            "rules": rules,
            "non_functional": non_functional,
            "out_of_scope": out_of_scope,
            "open_questions": open_questions,
            "ambiguities": ambiguities,
            "coverage_map": coverage_map,
            # legacy keys (保留既有下游流程相容)
            "ticket": ticket,
            "scenarios": scenarios,
            "reference_columns": references,
            "notes": notes,
            "trace_index": trace_index,
        }

    async def build_requirement_ir(
        self,
        *,
        session_data: HelperSessionResponse,
        ticket_payload: Dict[str, Any],
        requirement_markdown: str,
        similar_cases: str,
        structured_requirement: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        helper_cfg = self.settings.ai.jira_testcase_helper
        review_language = _locale_label(session_data.review_locale.value)
        ticket_key = session_data.ticket_key or str(ticket_payload.get("ticket_key") or "")
        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_components = ", ".join(ticket_payload.get("components") or []) or "N/A"
        source_packets = self._build_requirement_source_packets(
            requirement_markdown,
            ticket_payload=ticket_payload,
        )
        source_packets_json = json.dumps(
            source_packets,
            ensure_ascii=False,
            separators=(",", ":"),
        )

        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        cost = 0.0
        cost_note = ""
        response_id: Optional[str] = None
        repair_applied = False
        regenerate_applied = False
        fallback_applied = False
        fallback_reason = ""
        ir_payload_raw: Dict[str, Any] = {}

        if helper_cfg.enable_ir_first:
            prompt = self.prompt_service.render_machine_stage_prompt(
                "requirement_ir",
                {
                    "review_language": review_language,
                    "ticket_key": ticket_key,
                    "ticket_summary": ticket_summary,
                    "ticket_components": ticket_components,
                    "source_packets_json": source_packets_json,
                },
            )
            try:
                ir_call = await self._call_json_stage_with_retry(
                    stage="analysis",
                    prompt=prompt,
                    review_language=review_language,
                    stage_name="Requirement IR",
                    schema_example='{"ir_version":"1.0","ticket_meta":{"ticket_id":"TCG-123","summary":"..."},"chunks_index":[{"chunk_id":"desc","title":"Description","sentence_count":2}],"actors":[{"actor_id":"ACTOR-001","name":"User","type":"user","source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}],"entities":[{"entity_id":"ENT-001","name":"Reference::關聯帳號","fields":[{"field_id":"FIELD-001","name":"關聯帳號","source_refs":[{"chunk_id":"desc","sentence_ids":[1]}]}],"source_refs":[{"chunk_id":"desc","sentence_ids":[1]}]}],"flows":[{"flow_id":"FLOW-001","name":"登入流程","actor_ids":["ACTOR-001"],"preconditions":[],"steps":[{"step_id":"STEP-001","action":"輸入帳密","expected_outcome":"可送出登入","source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}],"postconditions":[],"source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}],"rules":[{"rule_id":"RULE-001","type":"validation","statement":"OTP 過期需阻擋","scope":"cross","source_refs":[{"chunk_id":"desc","sentence_ids":[1]}]}],"non_functional":[],"out_of_scope":[],"open_questions":[],"ambiguities":[],"coverage_map":[{"chunk_id":"desc","sentence_id":0,"status":"covered","covered_by":["FLOW-001"]}]}',
                )
                usage = dict(ir_call.get("usage") or {})
                cost = float(ir_call.get("cost") or 0.0)
                cost_note = str(ir_call.get("cost_note") or "")
                response_id = ir_call.get("response_id")
                repair_applied = bool(ir_call.get("repair_applied"))
                regenerate_applied = bool(ir_call.get("regenerate_applied"))
                ir_payload_raw = ir_call.get("payload_raw") or {}
            except Exception as exc:
                # Requirement IR 失敗時不讓整條 analyze 流程中斷，直接降級使用 deterministic IR。
                fallback_applied = True
                fallback_reason = str(exc)
                logger.warning(
                    "Requirement IR 呼叫失敗，改用 deterministic IR fallback: %s",
                    exc,
                )
                ir_payload_raw = {}

        requirement_ir = self._normalize_requirement_ir_payload(
            ir_payload_raw,
            ticket_key=ticket_key,
            summary=ticket_summary,
            components=ticket_payload.get("components") or [],
            requirement_markdown=requirement_markdown,
            source_chunks=source_packets.get("chunks") or [],
        )
        requirement_ir = self.requirement_ir_builder.merge_with_structured_requirement(
            requirement_ir=requirement_ir,
            structured_requirement=structured_requirement,
        )
        return {
            "requirement_ir": requirement_ir,
            "source_packets": source_packets,
            "usage": usage,
            "cost": cost,
            "cost_note": cost_note,
            "response_id": response_id,
            "repair_applied": repair_applied,
            "regenerate_applied": regenerate_applied,
            "fallback_applied": fallback_applied,
            "fallback_reason": fallback_reason,
            "enabled": bool(helper_cfg.enable_ir_first),
        }

    async def normalize_requirement(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperNormalizeRequest,
    ) -> HelperStageResultResponse:
        session_data = await self.get_session(team_id=team_id, session_id=session_id)
        ticket_draft = next(
            (item for item in session_data.drafts if item.phase == "jira_ticket"),
            None,
        )
        ticket_payload = ticket_draft.payload if ticket_draft and ticket_draft.payload else {}
        ticket_key = session_data.ticket_key or str(ticket_payload.get("ticket_key") or "")
        summary = str(ticket_payload.get("summary") or "")
        description = str(ticket_payload.get("description") or "")
        components = ticket_payload.get("components") or []

        if not ticket_key:
            raise ValueError("請先提供 TCG 單號並讀取 JIRA ticket")

        prompt = self._build_requirement_normalization_prompt(
            review_locale=session_data.review_locale.value,
            ticket_key=ticket_key,
            summary=summary,
            description=description,
            components=components,
        )
        self._log_stage_model_call(
            stage="analysis",
            stage_name="Requirement normalization",
            call_label="初次呼叫",
        )

        llm_result = await self.llm_service.call_stage(
            stage="analysis",
            prompt=prompt,
        )
        normalized_markdown = llm_result.content.strip()
        if not normalized_markdown:
            raise RuntimeError("需求整理回應為空")

        usage_payload = {
            "usage": llm_result.usage,
            "cost": llm_result.cost,
            "cost_note": llm_result.cost_note,
            "response_id": llm_result.response_id,
            "ticket_key": ticket_key,
        }

        def _persist(sync_db: Session) -> HelperSessionResponse:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            self._set_session_phase(
                session,
                phase=HelperPhase.REQUIREMENT,
                phase_status=HelperPhaseStatus.WAITING_CONFIRM,
                status=HelperSessionStatus.ACTIVE,
            )
            self._upsert_draft_sync(
                sync_db,
                session_id=session.id,
                phase="requirement",
                markdown=normalized_markdown,
                payload=usage_payload,
                increment_version=True,
            )
            sync_db.commit()
            _, drafts = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            return self._to_session_response(session, drafts)

        updated_session = await run_sync(self.db, _persist)
        return HelperStageResultResponse(
            session=updated_session,
            stage="requirement",
            markdown=normalized_markdown,
            payload={"ticket_key": ticket_key},
            usage=llm_result.usage,
        )

    # ---------- Analysis/Coverage adapters ----------
    @staticmethod
    def _normalize_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        def _as_text_list(raw_value: Any) -> List[str]:
            if isinstance(raw_value, str):
                normalized = raw_value.strip()
                return [normalized] if normalized else []
            if isinstance(raw_value, list):
                return [str(value).strip() for value in raw_value if str(value).strip()]
            return []

        item_id = str(item.get("id") or "").strip()
        title = str(item.get("t") or "").strip()
        if not item_id and not title:
            return None
        det = _as_text_list(item.get("det") or item.get("details"))
        chk = _as_text_list(
            item.get("chk") or item.get("check_items") or item.get("checks")
        )
        exp = _as_text_list(item.get("exp") or item.get("expected"))
        rid_raw = item.get("rid") or item.get("trace_refs") or []
        if isinstance(rid_raw, str):
            rid = [rid_raw.strip()] if rid_raw.strip() else []
        elif isinstance(rid_raw, list):
            rid = [str(v).strip() for v in rid_raw if str(v).strip()]
        else:
            rid = []
        return {
            "id": item_id,
            "t": title,
            "det": det,
            "chk": chk,
            "exp": exp,
            "rid": rid,
        }

    def _normalize_analysis_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sections_raw = payload.get("sec") or []
        items_raw = payload.get("it") or []
        normalized_sections: List[Dict[str, Any]] = []
        flat_items: List[Dict[str, Any]] = []

        if isinstance(sections_raw, list):
            for section in sections_raw:
                if not isinstance(section, dict):
                    continue
                group = str(section.get("g") or "").strip() or "未分類"
                sec_items: List[Dict[str, Any]] = []
                for raw_item in section.get("it") or []:
                    if not isinstance(raw_item, dict):
                        continue
                    normalized = self._normalize_item(raw_item)
                    if normalized is None:
                        continue
                    sec_items.append(normalized)
                    flat_items.append(normalized)
                if sec_items:
                    normalized_sections.append({"g": group, "it": sec_items})

        if not flat_items and isinstance(items_raw, list):
            for raw_item in items_raw:
                if not isinstance(raw_item, dict):
                    continue
                normalized = self._normalize_item(raw_item)
                if normalized is None:
                    continue
                flat_items.append(normalized)
            if flat_items:
                normalized_sections = [{"g": "未分類", "it": flat_items}]

        if flat_items and not normalized_sections:
            normalized_sections = [{"g": "未分類", "it": flat_items}]

        return {"sec": normalized_sections, "it": flat_items}

    def _build_deterministic_analysis_from_ir(
        self,
        *,
        requirement_ir: Dict[str, Any],
    ) -> Dict[str, Any]:
        sections_map: Dict[str, List[Dict[str, Any]]] = {}

        for scenario in requirement_ir.get("scenarios") or []:
            if not isinstance(scenario, dict):
                continue
            group = str(scenario.get("g") or "").strip() or "未分類"
            title = str(scenario.get("t") or "").strip() or "需求條目"
            checks = self._unique_preserve(
                self._to_text_list(scenario.get("ac"))
                + self._to_text_list(scenario.get("rules"))
            )
            expected = self._to_text_list(scenario.get("expected"))
            rid = [str(scenario.get("rid") or "").strip()] if str(scenario.get("rid") or "").strip() else []
            sections_map.setdefault(group, []).append(
                {
                    "id": "",
                    "t": title,
                    "det": self._to_text_list(scenario.get("data_points")),
                    "chk": checks or [title],
                    "exp": expected or checks or [title],
                    "rid": rid,
                    "source_refs": scenario.get("source_refs") or [],
                }
            )

        for reference in requirement_ir.get("reference_columns") or []:
            if not isinstance(reference, dict):
                continue
            column = str(reference.get("column") or "").strip()
            rid = [str(reference.get("rid") or "").strip()] if str(reference.get("rid") or "").strip() else []
            checks = self._reference_semantics_det(reference)
            expected = self._to_text_list(reference.get("expected"))
            sections_map.setdefault("Reference", []).append(
                {
                    "id": "",
                    "t": self._normalize_ref_column_title(column),
                    "det": checks,
                    "chk": checks,
                    "exp": expected or checks,
                    "rid": rid,
                    "source_refs": reference.get("source_refs") or [],
                }
            )

        sections_payload = [
            {"g": group, "it": items}
            for group, items in sections_map.items()
            if items
        ]
        normalized = self._reindex_analysis_sections(sections_payload)
        return normalized

    @staticmethod
    def _unique_preserve(values: Sequence[str]) -> List[str]:
        result: List[str] = []
        seen: Set[str] = set()
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    @staticmethod
    def _rid_is_reference(rid: str) -> bool:
        normalized = str(rid or "").strip().upper()
        return normalized.startswith("REF-")

    @classmethod
    def _expand_reference_rid_tokens(
        cls,
        rid_values: Sequence[str],
        *,
        known_refs: Optional[Set[str]] = None,
    ) -> List[str]:
        expanded: List[str] = []
        normalized_known_refs = (
            {str(value).strip().upper() for value in known_refs if str(value).strip()}
            if known_refs
            else set()
        )
        for raw_value in rid_values:
            normalized = str(raw_value or "").strip()
            if not normalized:
                continue
            if not cls._rid_is_reference(normalized):
                expanded.append(normalized)
                continue
            extracted_refs = cls._unique_preserve(
                [item.strip().upper() for item in re.findall(r"REF-\d{3}", normalized.upper())]
            )
            if extracted_refs:
                if normalized_known_refs:
                    filtered = [
                        item for item in extracted_refs if item in normalized_known_refs
                    ]
                    expanded.extend(filtered or extracted_refs)
                else:
                    expanded.extend(extracted_refs)
                continue
            expanded.append(normalized.upper())
        return cls._unique_preserve(expanded)

    @staticmethod
    def _normalize_ref_column_title(column_name: str) -> str:
        return f"{str(column_name or '').strip() or '欄位'} 欄位檢核"

    @staticmethod
    def _normalize_seed_category(raw_value: Any) -> str:
        normalized = str(raw_value or "").strip().lower()
        if normalized in VALID_SEED_CATEGORIES:
            return normalized
        if normalized in {"positive", "normal", "success"}:
            return "happy"
        if normalized in {"error", "fail", "failed", "invalid"}:
            return "negative"
        if normalized in {"edge", "limit"}:
            return "boundary"
        return "happy"

    @staticmethod
    def _normalize_seed_aspect(raw_value: Any) -> str:
        normalized = str(raw_value or "").strip().lower()
        if normalized in VALID_SEED_ASPECTS:
            return normalized
        if normalized in {"positive", "normal", "success", "happy_path", "happy-path"}:
            return "happy"
        if normalized in {"boundary", "limit", "edge_case", "edge-case"}:
            return "edge"
        if normalized in {"negative", "fail", "failed", "invalid", "exception"}:
            return "error"
        if normalized in {"auth", "authorization", "forbidden", "unauthorized", "acl", "rbac"}:
            return "permission"
        return ""

    @staticmethod
    def _category_from_aspect(aspect: str) -> str:
        normalized = str(aspect or "").strip().lower()
        if normalized == "happy":
            return "happy"
        if normalized == "edge":
            return "boundary"
        if normalized in {"error", "permission"}:
            return "negative"
        return ""

    @staticmethod
    def _aspect_from_category(cat: str, texts: Optional[Sequence[str]] = None) -> str:
        normalized = str(cat or "").strip().lower()
        evidence = " ".join([str(text).strip().lower() for text in (texts or []) if str(text).strip()])
        if normalized == "happy":
            return "happy"
        if normalized == "boundary":
            return "edge"
        if normalized == "negative":
            if any(keyword in evidence for keyword in PERMISSION_CATEGORY_HINTS):
                return "permission"
            return "error"
        return ""

    @staticmethod
    def _infer_seed_aspect(texts: Sequence[str]) -> str:
        merged = " ".join([str(text).strip().lower() for text in texts if str(text).strip()])
        if not merged:
            return "happy"
        if any(keyword in merged for keyword in PERMISSION_CATEGORY_HINTS):
            return "permission"
        if any(keyword in merged for keyword in NEGATIVE_CATEGORY_HINTS):
            return "error"
        if any(keyword in merged for keyword in BOUNDARY_CATEGORY_HINTS):
            return "edge"
        return "happy"

    @staticmethod
    def _category_signal_scores(texts: Sequence[str]) -> Tuple[int, int]:
        merged = " ".join([str(text).strip().lower() for text in texts if str(text).strip()])
        if not merged:
            return 0, 0
        negative_score = sum(1 for keyword in NEGATIVE_CATEGORY_HINTS if keyword in merged)
        boundary_score = sum(1 for keyword in BOUNDARY_CATEGORY_HINTS if keyword in merged)
        return negative_score, boundary_score

    @classmethod
    def _infer_seed_category(cls, texts: Sequence[str]) -> str:
        negative_score, boundary_score = cls._category_signal_scores(texts)
        if negative_score > 0:
            return "negative"
        # boundary 需要更明確語義，避免一般條目被過度分類為 boundary。
        if boundary_score >= 2:
            return "boundary"
        return "happy"

    def _collect_seed_evidence_texts(
        self,
        *,
        seed: Dict[str, Any],
        analysis_item: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        texts: List[str] = [str(seed.get("t") or "").strip()]
        for key in ("chk", "exp", "pre_hint", "step_hint"):
            texts.extend(
                [str(item).strip() for item in (seed.get(key) or []) if str(item).strip()]
            )
        if isinstance(analysis_item, dict):
            texts.append(str(analysis_item.get("t") or "").strip())
            for key in ("det", "chk", "exp"):
                texts.extend(
                    [str(item).strip() for item in (analysis_item.get(key) or []) if str(item).strip()]
                )
        return [text for text in texts if text]

    def _rebalance_coverage_seed_categories(
        self,
        *,
        seeds: List[Dict[str, Any]],
        analysis_item_map: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not seeds:
            return seeds

        for seed in seeds:
            refs = [str(value).strip() for value in (seed.get("ref") or []) if str(value).strip()]
            analysis_item = analysis_item_map.get(refs[0]) if len(refs) == 1 else None
            evidence_texts = self._collect_seed_evidence_texts(seed=seed, analysis_item=analysis_item)
            explicit_aspect = (
                self._normalize_seed_aspect(seed.get("ax"))
                if bool(seed.get("_ax_explicit"))
                else ""
            )
            if explicit_aspect:
                mapped_cat = self._category_from_aspect(explicit_aspect)
                if mapped_cat:
                    seed["cat"] = mapped_cat
                seed["ax"] = explicit_aspect
                continue
            inferred = self._infer_seed_category(evidence_texts)
            current = self._normalize_seed_category(seed.get("cat"))
            # 只允許 happy 升級成更具體分類，避免把模型已給出的負向/邊界覆寫成 happy。
            if current == "happy" and inferred != "happy":
                seed["cat"] = inferred
            seed_aspect = self._aspect_from_category(str(seed.get("cat") or ""), evidence_texts)
            seed["ax"] = seed_aspect or self._infer_seed_aspect(evidence_texts)
        return seeds

    @staticmethod
    def _normalize_seed_ref_ids(ref_raw: Any) -> List[str]:
        values: List[str]
        if isinstance(ref_raw, list):
            values = [str(item).strip() for item in ref_raw if str(item).strip()]
        elif isinstance(ref_raw, str):
            normalized = ref_raw.strip()
            values = [normalized] if normalized else []
        else:
            values = []

        refs: List[str] = []
        for value in values:
            extracted = re.findall(r"\d{3}\.\d{3}", value)
            if extracted:
                refs.extend(extracted)
                continue
            refs.append(value)
        return JiraTestCaseHelperService._unique_preserve(refs)

    @staticmethod
    def _reference_semantics_det(reference: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        column_name = str(reference.get("column") or "").strip()
        if column_name:
            lines.append(f"欄位: {column_name}")
        sortable = "Yes" if bool(reference.get("sortable")) else "No"
        new_column = "Yes" if bool(reference.get("new_column")) else "No"
        fixed_lr = str(reference.get("fixed_lr") or "none").strip().lower() or "none"
        lines.append(f"new_column={new_column}, sortable={sortable}, fixed_lr={fixed_lr}")
        format_rules = [
            str(item).strip()
            for item in (reference.get("format_rules") or [])
            if str(item).strip()
        ]
        if format_rules:
            lines.append(f"format_rules={', '.join(format_rules)}")
        cross_page_param = str(reference.get("cross_page_param") or "").strip()
        if cross_page_param:
            lines.append(f"cross_page_param={cross_page_param}")
        edit_note = str(reference.get("edit_note") or "").strip()
        if edit_note:
            lines.append(f"edit_note={edit_note}")
        expected = [
            str(item).strip()
            for item in (reference.get("expected") or [])
            if str(item).strip()
        ]
        if expected:
            lines.append(f"expected={'; '.join(expected)}")
        return lines

    @classmethod
    def _reference_detailed_checks(
        cls,
        reference: Dict[str, Any],
    ) -> List[str]:
        column_name = str(reference.get("column") or "").strip() or "欄位"
        checks: List[str] = [f"確認「{column_name}」欄位存在且可見"]
        checks.append(
            f"確認「{column_name}」新增欄位屬性為 {'Yes' if bool(reference.get('new_column')) else 'No'}"
        )
        if bool(reference.get("sortable")):
            checks.append(f"確認「{column_name}」支援升冪/降冪排序操作")
        else:
            checks.append(f"確認「{column_name}」不可觸發排序")
        fixed_lr = str(reference.get("fixed_lr") or "none").strip().lower()
        if fixed_lr in {"left", "right"}:
            checks.append(f"確認「{column_name}」為固定{fixed_lr}欄，水平捲動時維持可見")
        format_rules = [
            str(item).strip()
            for item in (reference.get("format_rules") or [])
            if str(item).strip()
        ]
        for rule in format_rules:
            checks.append(f"確認「{column_name}」格式規則：{rule}")
        cross_page_param = str(reference.get("cross_page_param") or "").strip()
        if cross_page_param:
            checks.append(f"確認跨頁參數「{cross_page_param}」可正確帶入「{column_name}」")
        edit_note = str(reference.get("edit_note") or "").strip()
        if edit_note:
            checks.append(f"確認欄位備註與變更註記：{edit_note}")
        return cls._unique_preserve(checks)

    @classmethod
    def _reference_detailed_expected(
        cls,
        reference: Dict[str, Any],
    ) -> List[str]:
        column_name = str(reference.get("column") or "").strip() or "欄位"
        expected: List[str] = [
            f"「{column_name}」欄位顯示結果符合需求定義",
        ]
        if bool(reference.get("sortable")):
            expected.append(f"「{column_name}」排序結果可觀測且順序正確")
        fixed_lr = str(reference.get("fixed_lr") or "none").strip().lower()
        if fixed_lr in {"left", "right"}:
            expected.append(f"水平捲動時「{column_name}」固定在{fixed_lr}側且不被遮蔽")
        format_rules = [
            str(item).strip()
            for item in (reference.get("format_rules") or [])
            if str(item).strip()
        ]
        for rule in format_rules:
            expected.append(f"「{column_name}」輸出格式符合規則：{rule}")
        for item in (reference.get("expected") or []):
            text = str(item).strip()
            if text:
                expected.append(text)
        return cls._unique_preserve(expected)

    @classmethod
    def _reindex_analysis_sections(
        cls,
        sections: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rebuilt_sections: List[Dict[str, Any]] = []
        flat_items: List[Dict[str, Any]] = []
        for sec_idx, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                continue
            group = str(section.get("g") or "").strip() or "未分類"
            source_items = [
                item
                for item in (section.get("it") or [])
                if isinstance(item, dict)
            ]
            if not source_items:
                continue
            section_no = str(sec_idx * 10).zfill(3)
            section_items: List[Dict[str, Any]] = []
            for item_idx, item in enumerate(source_items, start=1):
                cloned = dict(item)
                cloned["id"] = f"{section_no}.{str(item_idx).zfill(3)}"
                cloned["t"] = str(cloned.get("t") or "").strip() or "未命名需求"
                cloned["det"] = cls._unique_preserve(
                    [str(v).strip() for v in (cloned.get("det") or []) if str(v).strip()]
                )
                cloned["chk"] = cls._unique_preserve(
                    [str(v).strip() for v in (cloned.get("chk") or []) if str(v).strip()]
                )
                cloned["exp"] = cls._unique_preserve(
                    [str(v).strip() for v in (cloned.get("exp") or []) if str(v).strip()]
                )
                cloned["rid"] = cls._unique_preserve(
                    [str(v).strip() for v in (cloned.get("rid") or []) if str(v).strip()]
                )
                section_items.append(cloned)
                flat_items.append(cloned)
            rebuilt_sections.append({"g": group, "it": section_items})
        return {"sec": rebuilt_sections, "it": flat_items}

    def _augment_analysis_with_ir(
        self,
        *,
        analysis_payload: Dict[str, Any],
        requirement_ir: Dict[str, Any],
    ) -> Dict[str, Any]:
        sections = [
            {
                "g": str(section.get("g") or "").strip() or "未分類",
                "it": [
                    dict(item)
                    for item in (section.get("it") or [])
                    if isinstance(item, dict)
                ],
            }
            for section in (analysis_payload.get("sec") or [])
            if isinstance(section, dict)
        ]
        if not sections:
            sections = [{"g": "未分類", "it": []}]

        ref_map: Dict[str, Dict[str, Any]] = {}
        for reference in requirement_ir.get("reference_columns", []) or []:
            if not isinstance(reference, dict):
                continue
            rid = str(reference.get("rid") or "").strip()
            if rid:
                ref_map[rid] = reference

        scenario_map: Dict[str, Dict[str, Any]] = {}
        for scenario in requirement_ir.get("scenarios", []) or []:
            if not isinstance(scenario, dict):
                continue
            rid = str(scenario.get("rid") or "").strip()
            if rid:
                scenario_map[rid] = scenario
        known_ref_ids: Set[str] = {rid.strip().upper() for rid in ref_map.keys() if rid.strip()}

        expanded_sections: List[Dict[str, Any]] = []
        covered_rids: Set[str] = set()
        for section in sections:
            group = str(section.get("g") or "").strip() or "未分類"
            expanded_items: List[Dict[str, Any]] = []
            for item in section.get("it", []) or []:
                rid_list = self._unique_preserve(
                    [str(v).strip() for v in (item.get("rid") or []) if str(v).strip()]
                )
                rid_list = self._expand_reference_rid_tokens(
                    rid_list,
                    known_refs=known_ref_ids,
                )
                ref_rids = [rid for rid in rid_list if self._rid_is_reference(rid)]
                non_ref_rids = [rid for rid in rid_list if not self._rid_is_reference(rid)]

                if ref_rids:
                    for ref_rid in ref_rids:
                        reference = ref_map.get(ref_rid, {})
                        title = str(item.get("t") or "").strip()
                        ref_title = self._normalize_ref_column_title(reference.get("column"))
                        if not title or "ref-" in title.lower() or "~" in title:
                            title = ref_title
                        elif reference.get("column") and str(reference.get("column")) not in title:
                            title = f"{title} / {reference.get('column')}"

                        detailed_checks = self._reference_detailed_checks(reference)
                        detailed_expected = self._reference_detailed_expected(reference)
                        det = self._unique_preserve(
                            [str(v).strip() for v in (item.get("det") or []) if str(v).strip()]
                            + self._reference_semantics_det(reference)
                        )
                        chk = self._unique_preserve(
                            [str(v).strip() for v in (item.get("chk") or []) if str(v).strip()]
                            + detailed_checks
                        )
                        exp = self._unique_preserve(
                            [str(v).strip() for v in (item.get("exp") or []) if str(v).strip()]
                            + detailed_expected
                        )
                        expanded_items.append(
                            {
                                "id": "",
                                "t": title,
                                "det": det,
                                "chk": chk,
                                "exp": exp,
                                "rid": self._unique_preserve(non_ref_rids + [ref_rid]),
                            }
                        )
                        covered_rids.add(ref_rid)
                    for non_ref in non_ref_rids:
                        covered_rids.add(non_ref)
                    continue

                expanded_items.append(
                    {
                        "id": "",
                        "t": str(item.get("t") or "").strip() or "未命名需求",
                        "det": self._unique_preserve(
                            [str(v).strip() for v in (item.get("det") or []) if str(v).strip()]
                        ),
                        "chk": self._unique_preserve(
                            [str(v).strip() for v in (item.get("chk") or []) if str(v).strip()]
                        ),
                        "exp": self._unique_preserve(
                            [str(v).strip() for v in (item.get("exp") or []) if str(v).strip()]
                        ),
                        "rid": rid_list,
                    }
                )
                covered_rids.update(rid_list)

            expanded_sections.append({"g": group, "it": expanded_items})

        section_by_group: Dict[str, Dict[str, Any]] = {
            str(section.get("g") or "").strip() or "未分類": section
            for section in expanded_sections
            if isinstance(section, dict)
        }

        for scenario in requirement_ir.get("scenarios", []) or []:
            if not isinstance(scenario, dict):
                continue
            rid = str(scenario.get("rid") or "").strip()
            if not rid or rid in covered_rids:
                continue
            group = str(scenario.get("g") or "").strip() or "未分類"
            target_section = section_by_group.get(group)
            if target_section is None:
                target_section = {"g": group, "it": []}
                expanded_sections.append(target_section)
                section_by_group[group] = target_section
            target_section["it"].append(
                {
                    "id": "",
                    "t": str(scenario.get("t") or "").strip() or "未命名需求",
                    "det": self._unique_preserve(
                        [str(v).strip() for v in (scenario.get("ac") or []) if str(v).strip()]
                        + [str(v).strip() for v in (scenario.get("rules") or []) if str(v).strip()]
                    ),
                    "chk": self._unique_preserve(
                        [str(v).strip() for v in (scenario.get("data_points") or []) if str(v).strip()]
                    ),
                    "exp": self._unique_preserve(
                        [str(v).strip() for v in (scenario.get("expected") or []) if str(v).strip()]
                    ),
                    "rid": [rid],
                }
            )
            covered_rids.add(rid)

        for reference in requirement_ir.get("reference_columns", []) or []:
            if not isinstance(reference, dict):
                continue
            rid = str(reference.get("rid") or "").strip()
            if not rid or rid in covered_rids:
                continue
            target_group = "Reference Columns"
            target_section = section_by_group.get(target_group)
            if target_section is None:
                target_section = {"g": target_group, "it": []}
                expanded_sections.append(target_section)
                section_by_group[target_group] = target_section
            target_section["it"].append(
                {
                    "id": "",
                    "t": self._normalize_ref_column_title(reference.get("column")),
                    "det": self._reference_semantics_det(reference),
                    "chk": self._reference_detailed_checks(reference),
                    "exp": self._reference_detailed_expected(reference),
                    "rid": [rid],
                }
            )
            covered_rids.add(rid)

        compact_sections = []
        for section in expanded_sections:
            if not (section.get("it") or []):
                continue
            compact_sections.append(section)
        return self._reindex_analysis_sections(compact_sections)

    @staticmethod
    def _build_item_group_map(analysis_payload: Dict[str, Any]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for section in analysis_payload.get("sec", []) or []:
            if not isinstance(section, dict):
                continue
            group = str(section.get("g") or "").strip() or "未分類"
            for item in section.get("it", []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if item_id:
                    mapping[item_id] = group
        return mapping

    def _normalize_seed(
        self,
        seed: Dict[str, Any],
        item_group_map: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        title = str(seed.get("t") or "").strip()
        if not title:
            return None

        refs = self._normalize_seed_ref_ids(seed.get("ref"))
        rid_raw = seed.get("rid") or []
        rid_values = (
            [str(v).strip() for v in rid_raw if str(v).strip()]
            if isinstance(rid_raw, list)
            else ([str(rid_raw).strip()] if str(rid_raw).strip() else [])
        )
        rid = self._expand_reference_rid_tokens(rid_values)

        group = str(seed.get("g") or "").strip()
        if not group and refs:
            group = item_group_map.get(refs[0], "")
        if not group:
            group = "未分類"

        chk_values = self._unique_preserve(self._to_text_list(seed.get("chk")))
        exp_values = self._unique_preserve(self._to_text_list(seed.get("exp")))
        pre_hint_values = self._unique_preserve(
            self._to_text_list(seed.get("pre_hint") or seed.get("pre"))
        )
        step_hint_values = self._unique_preserve(
            self._to_text_list(seed.get("step_hint") or seed.get("steps"))
        )
        evidence_texts = [title] + chk_values + exp_values + pre_hint_values + step_hint_values
        aspect = self._normalize_seed_aspect(seed.get("ax") or seed.get("aspect"))
        aspect_explicit = bool(aspect)
        if not aspect:
            raw_cat = self._normalize_seed_category(seed.get("cat"))
            aspect = self._aspect_from_category(raw_cat, evidence_texts)
        if not aspect:
            aspect = self._infer_seed_aspect(evidence_texts)
        mapped_cat = self._category_from_aspect(aspect)
        cat = mapped_cat or self._normalize_seed_category(seed.get("cat"))
        inferred_cat = self._infer_seed_category(evidence_texts)
        if cat == "happy" and inferred_cat != "happy":
            cat = inferred_cat
            if cat == "boundary":
                aspect = "edge"
            elif cat == "negative" and aspect == "happy":
                aspect = "error"
        st = str(seed.get("st") or "ok").strip().lower() or "ok"

        normalized: Dict[str, Any] = {
            "g": group,
            "t": title,
            "ax": aspect,
            "cat": cat,
            "st": st,
            "ref": refs,
            "rid": rid,
            "chk": chk_values,
            "exp": exp_values,
            "pre_hint": pre_hint_values,
            "step_hint": step_hint_values,
            "_ax_explicit": aspect_explicit,
        }
        sid = str(seed.get("sid") or "").strip()
        if sid:
            normalized["sid"] = sid
        if st == "assume" and str(seed.get("a") or "").strip():
            normalized["a"] = str(seed.get("a")).strip()
        if st == "ask" and str(seed.get("q") or "").strip():
            normalized["q"] = str(seed.get("q")).strip()
        return normalized

    def _normalize_coverage_payload(
        self,
        payload: Dict[str, Any],
        analysis_payload: Dict[str, Any],
        requirement_ir: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        seeds_raw = payload.get("seed") or []
        if not seeds_raw:
            sections_raw = payload.get("sec") or []
            if isinstance(sections_raw, list):
                collected: List[Dict[str, Any]] = []
                for section in sections_raw:
                    if not isinstance(section, dict):
                        continue
                    group = str(section.get("g") or "").strip()
                    for seed in section.get("seed") or []:
                        if not isinstance(seed, dict):
                            continue
                        if group and not seed.get("g"):
                            seed["g"] = group
                        collected.append(seed)
                seeds_raw = collected

        item_group_map = self._build_item_group_map(analysis_payload)
        analysis_item_map: Dict[str, Dict[str, Any]] = {
            str(item.get("id") or "").strip(): item
            for item in (analysis_payload.get("it") or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        reference_map: Dict[str, Dict[str, Any]] = {}
        if isinstance(requirement_ir, dict):
            for reference in requirement_ir.get("reference_columns") or []:
                if not isinstance(reference, dict):
                    continue
                rid = str(reference.get("rid") or "").strip()
                if rid:
                    reference_map[rid] = reference
        normalized_seeds: List[Dict[str, Any]] = []
        if isinstance(seeds_raw, list):
            for raw_seed in seeds_raw:
                if not isinstance(raw_seed, dict):
                    continue
                normalized = self._normalize_seed(raw_seed, item_group_map)
                if normalized is None:
                    continue
                normalized_seeds.append(normalized)

        single_ref_seeds: List[Dict[str, Any]] = []
        for seed in normalized_seeds:
            refs = [str(v).strip() for v in (seed.get("ref") or []) if str(v).strip()]
            if len(refs) <= 1:
                single_ref_seeds.append(seed)
                continue
            for ref in refs:
                cloned_seed = dict(seed)
                cloned_seed["ref"] = [ref]
                single_ref_seeds.append(cloned_seed)
        normalized_seeds = single_ref_seeds

        for seed in normalized_seeds:
            refs = [str(v).strip() for v in (seed.get("ref") or []) if str(v).strip()]
            if len(refs) != 1:
                continue
            canonical_group = str(item_group_map.get(refs[0]) or "").strip()
            if canonical_group:
                seed["g"] = canonical_group
            analysis_item = analysis_item_map.get(refs[0])
            if not analysis_item:
                continue
            analysis_rid = self._expand_reference_rid_tokens(
                [str(v).strip() for v in (analysis_item.get("rid") or []) if str(v).strip()]
            )
            existing_rid = [
                str(v).strip()
                for v in (seed.get("rid") or [])
                if str(v).strip() and not self._rid_is_reference(str(v))
            ]
            merged_rid = self._unique_preserve(existing_rid + analysis_rid)
            if merged_rid:
                seed["rid"] = merged_rid
            ref_rid = next(
                (value for value in merged_rid if self._rid_is_reference(value)),
                "",
            )
            reference = reference_map.get(ref_rid)
            if reference:
                detailed_checks = self._reference_detailed_checks(reference)
                detailed_expected = self._reference_detailed_expected(reference)
                seed["chk"] = self._unique_preserve(
                    self._to_text_list(seed.get("chk")) + detailed_checks
                )
                seed["exp"] = self._unique_preserve(
                    self._to_text_list(seed.get("exp")) + detailed_expected
                )
                seed["pre_hint"] = self._unique_preserve(
                    self._to_text_list(seed.get("pre_hint"))
                    + ["已準備包含該欄位的測試資料，且欄位值可觀測"]
                )
                seed["step_hint"] = self._unique_preserve(
                    self._to_text_list(seed.get("step_hint"))
                    + [
                        "執行欄位操作（顯示/排序/捲動）並記錄結果",
                        "逐一比對每項欄位規則是否符合預期",
                    ]
                )
                if not seed.get("source_refs"):
                    source_refs = reference.get("source_refs")
                    if isinstance(source_refs, list) and source_refs:
                        seed["source_refs"] = source_refs

        deduped_seeds: List[Dict[str, Any]] = []
        seen_seed_keys: Set[Tuple[Any, ...]] = set()
        for seed in normalized_seeds:
            dedupe_key = self._coverage_seed_dedupe_key(seed)
            if dedupe_key in seen_seed_keys:
                continue
            seen_seed_keys.add(dedupe_key)
            deduped_seeds.append(seed)
        normalized_seeds = deduped_seeds

        normalized_seeds = self._rebalance_coverage_seed_categories(
            seeds=normalized_seeds,
            analysis_item_map=analysis_item_map,
        )

        for index, seed in enumerate(normalized_seeds, start=1):
            seed.pop("_ax_explicit", None)
            seed["idx"] = index

        sections: List[Dict[str, Any]] = []
        group_index: Dict[str, int] = {}
        for seed in normalized_seeds:
            group = str(seed.get("g") or "").strip() or "未分類"
            if group not in group_index:
                group_index[group] = len(sections)
                sections.append({"g": group, "seed": []})
            sections[group_index[group]]["seed"].append(seed)
        trace_raw = payload.get("trace")
        trace = trace_raw if isinstance(trace_raw, dict) else {}
        return {"sec": sections, "seed": normalized_seeds, "trace": trace}

    def validate_coverage_completeness(
        self,
        *,
        analysis_payload: Dict[str, Any],
        coverage_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        analysis_ids: List[str] = []
        analysis_sections: Set[str] = set()
        for section in analysis_payload.get("sec", []) or []:
            if not isinstance(section, dict):
                continue
            group = str(section.get("g") or "").strip()
            if group:
                analysis_sections.add(group)
            for item in section.get("it", []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if item_id and item_id not in analysis_ids:
                    analysis_ids.append(item_id)

        if not analysis_ids:
            for item in analysis_payload.get("it", []) or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if item_id and item_id not in analysis_ids:
                    analysis_ids.append(item_id)

        covered_ids: Set[str] = set()
        coverage_sections: Set[str] = set()
        for section in coverage_payload.get("sec", []) or []:
            if not isinstance(section, dict):
                continue
            group = str(section.get("g") or "").strip()
            if group:
                coverage_sections.add(group)

        for seed in coverage_payload.get("seed", []) or []:
            if not isinstance(seed, dict):
                continue
            group = str(seed.get("g") or "").strip()
            if group:
                coverage_sections.add(group)
            refs = seed.get("ref") or []
            if isinstance(refs, list):
                covered_ids.update(str(ref).strip() for ref in refs if str(ref).strip())

        missing_ids = [item_id for item_id in analysis_ids if item_id not in covered_ids]
        missing_sections = sorted(
            section for section in analysis_sections if section not in coverage_sections
        )
        return {
            "analysis_item_count": len(analysis_ids),
            "covered_item_count": len([item for item in analysis_ids if item in covered_ids]),
            "missing_ids": missing_ids,
            "missing_sections": missing_sections,
            "is_complete": not missing_ids and not missing_sections,
        }

    def validate_coverage_aspects(
        self,
        *,
        coverage_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        required_aspects = sorted(VALID_SEED_ASPECTS)
        covered_aspects: Set[str] = set()
        aspect_counts: Dict[str, int] = {aspect: 0 for aspect in required_aspects}
        for seed in coverage_payload.get("seed", []) or []:
            if not isinstance(seed, dict):
                continue
            evidence_texts = [
                str(seed.get("t") or "").strip(),
                *[str(v).strip() for v in (seed.get("chk") or []) if str(v).strip()],
                *[str(v).strip() for v in (seed.get("exp") or []) if str(v).strip()],
                *[str(v).strip() for v in (seed.get("pre_hint") or []) if str(v).strip()],
                *[str(v).strip() for v in (seed.get("step_hint") or []) if str(v).strip()],
            ]
            aspect = self._normalize_seed_aspect(seed.get("ax") or seed.get("aspect"))
            if not aspect:
                cat = self._normalize_seed_category(seed.get("cat"))
                aspect = self._aspect_from_category(cat, evidence_texts)
            if not aspect:
                aspect = self._infer_seed_aspect(evidence_texts)
            if not aspect:
                continue
            covered_aspects.add(aspect)
            if aspect in aspect_counts:
                aspect_counts[aspect] += 1
        missing_aspects = [aspect for aspect in required_aspects if aspect not in covered_aspects]
        return {
            "required_aspects": required_aspects,
            "covered_aspects": sorted(covered_aspects),
            "missing_aspects": missing_aspects,
            "aspect_counts": aspect_counts,
            "is_complete": not missing_aspects,
        }

    @staticmethod
    def _variant_kind_from_seed_category(category: str) -> str:
        normalized = str(category or "").strip().lower()
        if normalized == "negative":
            return "negative"
        if normalized == "boundary":
            return "boundary"
        return "positive"

    @staticmethod
    def _trace_rule_ids_from_rid(rid_values: Sequence[str]) -> List[str]:
        return [
            str(value).strip()
            for value in rid_values
            if re.fullmatch(r"RULE-\d+", str(value).strip())
        ]

    @staticmethod
    def _trace_flow_ids_from_rid(rid_values: Sequence[str]) -> List[str]:
        return [
            str(value).strip()
            for value in rid_values
            if re.fullmatch(r"FLOW-\d+", str(value).strip())
        ]

    @staticmethod
    def _trace_entity_ids_from_rid(rid_values: Sequence[str]) -> List[str]:
        return [
            str(value).strip()
            for value in rid_values
            if re.fullmatch(r"ENT-\d+", str(value).strip())
        ]

    def _build_coverage_plan(
        self,
        *,
        ticket_id: str,
        requirement_ir: Dict[str, Any],
        analysis_payload: Dict[str, Any],
        coverage_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        analysis_item_map: Dict[str, Dict[str, Any]] = {
            str(item.get("id") or "").strip(): item
            for item in (analysis_payload.get("it") or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        scenario_ref_map: Dict[str, List[Dict[str, Any]]] = {}
        for row in requirement_ir.get("scenarios") or []:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("rid") or "").strip()
            source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
            if rid and source_refs:
                scenario_ref_map[rid] = source_refs
        for row in requirement_ir.get("reference_columns") or []:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("rid") or "").strip()
            source_refs = row.get("source_refs") if isinstance(row.get("source_refs"), list) else []
            if rid and source_refs:
                scenario_ref_map[rid] = source_refs

        def _seed_source_refs(seed: Dict[str, Any], analysis_item: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
            refs = seed.get("source_refs") if isinstance(seed.get("source_refs"), list) else []
            if refs:
                return refs
            rid_values = [str(value).strip() for value in (seed.get("rid") or []) if str(value).strip()]
            aggregated: List[Dict[str, Any]] = []
            for rid in rid_values:
                for ref in scenario_ref_map.get(rid, []):
                    if isinstance(ref, dict):
                        aggregated.append(ref)
            if aggregated:
                return aggregated
            if isinstance(analysis_item, dict):
                title = str(analysis_item.get("t") or "").strip()
                if title:
                    return self._match_source_refs_by_snippet(
                        source_chunks=self._convert_coverage_map_to_source_chunks(
                            requirement_ir.get("coverage_map") or []
                        ),
                        snippet=title,
                    )
            return []

        sections_by_name: Dict[str, Dict[str, Any]] = {}
        seed_rows = [
            row for row in (coverage_payload.get("seed") or []) if isinstance(row, dict)
        ]
        vi_counter = 1
        for seed in seed_rows:
            group = str(seed.get("g") or "").strip() or "未分類"
            section = sections_by_name.get(group)
            if section is None:
                section = {
                    "section_id": f"SEC-{str(len(sections_by_name) * 10 + 10).zfill(3)}",
                    "title": group,
                    "purpose": f"驗證 {group} 的功能規格",
                    "in_scope": {"flows": [], "rules": [], "entities": []},
                    "relevant_ir_ids": [],
                    "verification_items": [],
                }
                sections_by_name[group] = section

            refs = [str(value).strip() for value in (seed.get("ref") or []) if str(value).strip()]
            analysis_item = analysis_item_map.get(refs[0]) if len(refs) == 1 else None
            rid_values = [str(value).strip() for value in (seed.get("rid") or []) if str(value).strip()]
            if isinstance(analysis_item, dict):
                rid_values.extend(
                    [str(value).strip() for value in (analysis_item.get("rid") or []) if str(value).strip()]
                )
            rid_values = self._unique_preserve(rid_values)

            check_lines = self._unique_preserve(
                self._to_text_list(seed.get("chk"))
                + (self._to_text_list(analysis_item.get("chk")) if isinstance(analysis_item, dict) else [])
            )
            expected_lines = self._unique_preserve(
                self._to_text_list(seed.get("exp"))
                + (self._to_text_list(analysis_item.get("exp")) if isinstance(analysis_item, dict) else [])
            )
            expected_observable = expected_lines or check_lines or [str(seed.get("t") or "預期結果可觀測").strip()]
            setup_hints = self._unique_preserve(
                self._to_text_list(seed.get("pre_hint"))
                + (self._to_text_list(analysis_item.get("det")) if isinstance(analysis_item, dict) else [])
            ) or ["已準備符合需求的測試資料與權限"]
            action_hints = self._unique_preserve(
                self._to_text_list(seed.get("step_hint"))
                + check_lines
            ) or ["執行需求相關操作並記錄結果"]
            source_refs = _seed_source_refs(seed, analysis_item)
            if not source_refs:
                fallback_snippet = str(seed.get("t") or "").strip()
                source_refs = self._match_source_refs_by_snippet(
                    source_chunks=self._convert_coverage_map_to_source_chunks(
                        requirement_ir.get("coverage_map") or []
                    ),
                    snippet=fallback_snippet,
                )
            if not source_refs:
                source_refs = self._first_chunk_source_ref(
                    self._convert_coverage_map_to_source_chunks(requirement_ir.get("coverage_map") or [])
                )

            rule_ids = self._trace_rule_ids_from_rid(rid_values)
            flow_ids = self._trace_flow_ids_from_rid(rid_values)
            entity_ids = self._trace_entity_ids_from_rid(rid_values)

            if not flow_ids:
                for flow in requirement_ir.get("flows") or []:
                    if not isinstance(flow, dict):
                        continue
                    flow_name = str(flow.get("name") or "").strip()
                    if flow_name and flow_name in group:
                        flow_id = str(flow.get("flow_id") or "").strip()
                        if flow_id:
                            flow_ids.append(flow_id)
            flow_ids = self._unique_preserve(flow_ids)
            rule_ids = self._unique_preserve(rule_ids)
            entity_ids = self._unique_preserve(entity_ids)

            section["in_scope"]["flows"] = self._unique_preserve(
                section["in_scope"]["flows"] + flow_ids
            )
            section["in_scope"]["rules"] = self._unique_preserve(
                section["in_scope"]["rules"] + rule_ids
            )
            section["in_scope"]["entities"] = self._unique_preserve(
                section["in_scope"]["entities"] + entity_ids
            )
            section["relevant_ir_ids"] = self._unique_preserve(
                section["relevant_ir_ids"] + rid_values + rule_ids + flow_ids + entity_ids
            )
            section["verification_items"].append(
                {
                    "verification_item_id": f"VI-{str(vi_counter * 10).zfill(3)}",
                    "intent": str(seed.get("t") or "").strip()
                    or (str(analysis_item.get("t") or "").strip() if isinstance(analysis_item, dict) else "需求驗證"),
                    "setup_hints": setup_hints,
                    "action_hints": action_hints,
                    "data": {
                        "inputs": [
                            {
                                "name": "input",
                                "type": "string",
                                "example": check_lines[0] if check_lines else "sample",
                                "notes": "",
                            }
                        ],
                        "state": setup_hints,
                    },
                    "expected_observable": expected_observable,
                    "variants": [
                        {
                            "kind": self._variant_kind_from_seed_category(str(seed.get("cat") or "happy")),
                            "notes": str(seed.get("cat") or "happy"),
                        }
                    ],
                    "priority": "p1" if str(seed.get("cat") or "happy").lower() != "happy" else "p2",
                    "trace": {
                        "rule_ids": rule_ids,
                        "flow_ids": flow_ids,
                        "entity_ids": entity_ids,
                    },
                    "source_refs": source_refs or [],
                }
            )
            vi_counter += 1

        sections = list(sections_by_name.values())
        if not sections:
            sections = [
                {
                    "section_id": "SEC-010",
                    "title": "未分類",
                    "purpose": "補齊 coverage",
                    "in_scope": {"flows": [], "rules": [], "entities": []},
                    "relevant_ir_ids": [],
                    "verification_items": [],
                }
            ]

        max_vi_per_section = max(
            1,
            int(getattr(self.settings.ai.jira_testcase_helper, "max_vi_per_section", 12) or 12),
        )
        split_sections: List[Dict[str, Any]] = []
        section_seq = 1
        for section in sections:
            items = [
                item
                for item in (section.get("verification_items") or [])
                if isinstance(item, dict)
            ]
            if len(items) <= max_vi_per_section:
                section = dict(section)
                section["section_id"] = f"SEC-{str(section_seq * 10).zfill(3)}"
                section_seq += 1
                split_sections.append(section)
                continue
            base_title = str(section.get("title") or "未分類").strip() or "未分類"
            base_purpose = str(section.get("purpose") or "").strip()
            for chunk_index, start in enumerate(
                range(0, len(items), max_vi_per_section),
                start=1,
            ):
                chunk_items = items[start : start + max_vi_per_section]
                split_sections.append(
                    {
                        **section,
                        "section_id": f"SEC-{str(section_seq * 10).zfill(3)}",
                        "title": f"{base_title} #{chunk_index}",
                        "purpose": base_purpose or f"{base_title} 子區段 {chunk_index}",
                        "verification_items": chunk_items,
                    }
                )
                section_seq += 1
        sections = split_sections

        rule_to_items_map: Dict[str, List[str]] = {}
        flow_to_items_map: Dict[str, List[str]] = {}
        for section in sections:
            for item in section.get("verification_items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("verification_item_id") or "").strip()
                trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
                for rule_id in trace.get("rule_ids") or []:
                    normalized_rule = str(rule_id).strip()
                    if normalized_rule:
                        rule_to_items_map.setdefault(normalized_rule, []).append(item_id)
                for flow_id in trace.get("flow_ids") or []:
                    normalized_flow = str(flow_id).strip()
                    if normalized_flow:
                        flow_to_items_map.setdefault(normalized_flow, []).append(item_id)

        all_rule_ids = [
            str(rule.get("rule_id") or "").strip()
            for rule in (requirement_ir.get("rules") or [])
            if isinstance(rule, dict) and str(rule.get("rule_id") or "").strip()
        ]
        all_flow_ids = [
            str(flow.get("flow_id") or "").strip()
            for flow in (requirement_ir.get("flows") or [])
            if isinstance(flow, dict) and str(flow.get("flow_id") or "").strip()
        ]

        if sections:
            default_section = sections[0]
            for rule_id in all_rule_ids:
                if rule_to_items_map.get(rule_id):
                    continue
                vi_id = f"VI-{str(vi_counter * 10).zfill(3)}"
                vi_counter += 1
                default_section["verification_items"].append(
                    {
                        "verification_item_id": vi_id,
                        "intent": f"覆蓋規則 {rule_id}",
                        "setup_hints": ["準備符合規則的測試資料"],
                        "action_hints": [f"執行並驗證規則 {rule_id}"],
                        "data": {
                            "inputs": [
                                {
                                    "name": "rule_input",
                                    "type": "string",
                                    "example": rule_id,
                                    "notes": "",
                                }
                            ],
                            "state": ["資料存在且可被驗證"],
                        },
                        "expected_observable": [f"UI欄位/回應符合 {rule_id}"],
                        "variants": [{"kind": "positive", "notes": "deterministic_backfill"}],
                        "priority": "p1",
                        "trace": {
                            "rule_ids": [rule_id],
                            "flow_ids": [],
                            "entity_ids": [],
                        },
                        "source_refs": self._first_chunk_source_ref(
                            self._convert_coverage_map_to_source_chunks(
                                requirement_ir.get("coverage_map") or []
                            )
                        ),
                    }
                )
                rule_to_items_map[rule_id] = [vi_id]
            for flow_id in all_flow_ids:
                if flow_to_items_map.get(flow_id):
                    continue
                vi_id = f"VI-{str(vi_counter * 10).zfill(3)}"
                vi_counter += 1
                default_section["verification_items"].append(
                    {
                        "verification_item_id": vi_id,
                        "intent": f"覆蓋流程 {flow_id}",
                        "setup_hints": ["建立流程前置條件"],
                        "action_hints": [f"執行流程 {flow_id}"],
                        "data": {
                            "inputs": [
                                {
                                    "name": "flow_input",
                                    "type": "string",
                                    "example": flow_id,
                                    "notes": "",
                                }
                            ],
                            "state": ["流程可執行"],
                        },
                        "expected_observable": [f"流程 {flow_id} 可觀測結果符合需求"],
                        "variants": [{"kind": "positive", "notes": "deterministic_backfill"}],
                        "priority": "p1",
                        "trace": {
                            "rule_ids": [],
                            "flow_ids": [flow_id],
                            "entity_ids": [],
                        },
                        "source_refs": self._first_chunk_source_ref(
                            self._convert_coverage_map_to_source_chunks(
                                requirement_ir.get("coverage_map") or []
                            )
                        ),
                    }
                )
                flow_to_items_map[flow_id] = [vi_id]

        return {
            "coverage_version": "1.0",
            "ticket_id": ticket_id,
            "sections": sections,
            "traceability": {
                "rule_to_items": [
                    {
                        "rule_id": rule_id,
                        "verification_item_ids": self._unique_preserve(item_ids),
                    }
                    for rule_id, item_ids in rule_to_items_map.items()
                    if rule_id and item_ids
                ],
                "flow_to_items": [
                    {
                        "flow_id": flow_id,
                        "verification_item_ids": self._unique_preserve(item_ids),
                    }
                    for flow_id, item_ids in flow_to_items_map.items()
                    if flow_id and item_ids
                ],
            },
        }

    @staticmethod
    def _convert_coverage_map_to_source_chunks(
        coverage_map: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in coverage_map:
            if not isinstance(row, dict):
                continue
            chunk_id = str(row.get("chunk_id") or "").strip()
            sentence_id = row.get("sentence_id")
            if not chunk_id or not str(sentence_id).strip().isdigit():
                continue
            grouped.setdefault(
                chunk_id,
                {"chunk_id": chunk_id, "title": chunk_id, "sentences": []},
            )
            grouped[chunk_id]["sentences"].append(
                {"sid": int(sentence_id), "text": ""}
            )
        return list(grouped.values())

    def _build_deterministic_coverage_backfill(
        self,
        *,
        analysis_payload: Dict[str, Any],
        requirement_ir: Dict[str, Any],
        missing_ids: List[str],
        missing_sections: List[str],
    ) -> Dict[str, Any]:
        item_group_map = self._build_item_group_map(analysis_payload)
        analysis_item_map: Dict[str, Dict[str, Any]] = {}
        section_items_map: Dict[str, List[Dict[str, Any]]] = {}
        for section in analysis_payload.get("sec", []) or []:
            if not isinstance(section, dict):
                continue
            group = str(section.get("g") or "").strip() or "未分類"
            items = [
                item
                for item in (section.get("it") or [])
                if isinstance(item, dict)
            ]
            section_items_map[group] = items
            for item in items:
                item_id = str(item.get("id") or "").strip()
                if item_id:
                    analysis_item_map[item_id] = item

        ref_map: Dict[str, Dict[str, Any]] = {}
        for reference in requirement_ir.get("reference_columns", []) or []:
            if not isinstance(reference, dict):
                continue
            rid = str(reference.get("rid") or "").strip()
            if rid:
                ref_map[rid] = reference

        seeds: List[Dict[str, Any]] = []
        seeded_ids: Set[str] = set()
        for missing_id in missing_ids:
            item = analysis_item_map.get(missing_id)
            if not item:
                continue
            group = str(item_group_map.get(missing_id) or "未分類").strip() or "未分類"
            rid = self._unique_preserve(
                [str(v).strip() for v in (item.get("rid") or []) if str(v).strip()]
            )
            title = str(item.get("t") or "").strip() or "需求檢核"
            ref_rid = next((value for value in rid if self._rid_is_reference(value)), "")
            if ref_rid and ref_rid in ref_map:
                column_name = str(ref_map[ref_rid].get("column") or "").strip()
                if column_name:
                    title = self._normalize_ref_column_title(column_name)
            evidence_texts = [title] + self._to_text_list(item.get("det"))
            evidence_texts.extend(self._to_text_list(item.get("chk")))
            evidence_texts.extend(self._to_text_list(item.get("exp")))
            inferred_cat = self._infer_seed_category(evidence_texts)
            seeds.append(
                {
                    "g": group,
                    "t": title,
                    "cat": inferred_cat,
                    "st": "ok",
                    "ref": [missing_id],
                    "rid": rid,
                    "chk": self._unique_preserve(
                        [str(v).strip() for v in (item.get("chk") or []) if str(v).strip()]
                    ),
                    "exp": self._unique_preserve(
                        [str(v).strip() for v in (item.get("exp") or []) if str(v).strip()]
                    ),
                    "pre_hint": ["準備符合需求的測試資料與角色權限"],
                    "step_hint": [
                        "執行對應操作並觀察目標欄位/行為",
                        "驗證結果與需求一致",
                    ],
                }
            )
            seeded_ids.add(missing_id)

        for missing_section in missing_sections:
            section = str(missing_section or "").strip()
            if not section:
                continue
            for item in section_items_map.get(section, []):
                item_id = str(item.get("id") or "").strip()
                if not item_id or item_id in seeded_ids:
                    continue
                rid = self._unique_preserve(
                    [str(v).strip() for v in (item.get("rid") or []) if str(v).strip()]
                )
                title = str(item.get("t") or "").strip() or "需求檢核"
                evidence_texts = [title] + self._to_text_list(item.get("det"))
                evidence_texts.extend(self._to_text_list(item.get("chk")))
                evidence_texts.extend(self._to_text_list(item.get("exp")))
                seeds.append(
                    {
                        "g": section,
                        "t": title,
                        "cat": self._infer_seed_category(evidence_texts),
                        "st": "ok",
                        "ref": [item_id],
                        "rid": rid,
                        "chk": self._unique_preserve(
                            [
                                str(v).strip()
                                for v in (item.get("chk") or [])
                                if str(v).strip()
                            ]
                        ),
                        "exp": self._unique_preserve(
                            [
                                str(v).strip()
                                for v in (item.get("exp") or [])
                                if str(v).strip()
                            ]
                        ),
                        "pre_hint": ["準備符合需求的測試資料與角色權限"],
                        "step_hint": [
                            "執行對應操作並觀察目標欄位/行為",
                            "驗證結果與需求一致",
                        ],
                    }
                )
                seeded_ids.add(item_id)
                break

        return {
            "seed": seeds,
            "trace": {
                "strategy": "deterministic_backfill",
                "seed_count": len(seeds),
                "missing_ids_input": missing_ids,
                "missing_sections_input": missing_sections,
            },
        }

    @staticmethod
    def _coverage_seed_dedupe_key(seed: Dict[str, Any]) -> Tuple[Any, ...]:
        refs = tuple(sorted(str(item).strip() for item in (seed.get("ref") or []) if str(item).strip()))
        rid = tuple(sorted(str(item).strip() for item in (seed.get("rid") or []) if str(item).strip()))
        chk = tuple(sorted(str(item).strip() for item in (seed.get("chk") or []) if str(item).strip()))
        exp = tuple(sorted(str(item).strip() for item in (seed.get("exp") or []) if str(item).strip()))
        pre_hint = tuple(
            sorted(str(item).strip() for item in (seed.get("pre_hint") or []) if str(item).strip())
        )
        step_hint = tuple(
            sorted(str(item).strip() for item in (seed.get("step_hint") or []) if str(item).strip())
        )
        return (
            str(seed.get("g") or "").strip(),
            str(seed.get("t") or "").strip(),
            str(seed.get("ax") or "").strip().lower(),
            str(seed.get("cat") or "").strip().lower(),
            str(seed.get("st") or "ok").strip().lower(),
            refs,
            rid,
            chk,
            exp,
            pre_hint,
            step_hint,
            str(seed.get("a") or "").strip(),
            str(seed.get("q") or "").strip(),
        )

    def _merge_coverage_payload(
        self,
        *,
        base_payload: Dict[str, Any],
        backfill_payload: Dict[str, Any],
        analysis_payload: Dict[str, Any],
        requirement_ir: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        merged_seed_raw: List[Dict[str, Any]] = []
        seen_keys: Set[Tuple[Any, ...]] = set()
        for source_payload in [base_payload, backfill_payload]:
            for seed in source_payload.get("seed", []) or []:
                if not isinstance(seed, dict):
                    continue
                dedupe_key = self._coverage_seed_dedupe_key(seed)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                merged_seed_raw.append(dict(seed))

        merged_normalized = self._normalize_coverage_payload(
            {"seed": merged_seed_raw},
            analysis_payload,
            requirement_ir=requirement_ir,
        )
        return merged_normalized

    async def _call_coverage_with_retry(
        self,
        *,
        prompt: str,
        review_language: str,
        stage_name: str,
        schema_example: str,
    ) -> Dict[str, Any]:
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        cost = 0.0
        cost_note = ""
        response_id: Optional[str] = None
        regenerate_applied = False
        repair_applied = False

        def _accumulate(result: Any) -> None:
            nonlocal usage, cost, cost_note, response_id
            usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0)
                + result.usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0)
                + result.usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
                + result.usage.get("total_tokens", 0),
            }
            cost += float(result.cost or 0.0)
            response_id = result.response_id or response_id
            if cost_note or result.cost_note:
                cost_note = "（含未知費用）"

        async def _call_stage_with_empty_tolerance(
            *,
            prompt_text: str,
            call_label: str,
        ) -> Optional[Any]:
            self._log_stage_model_call(
                stage="coverage",
                stage_name=stage_name,
                call_label=call_label,
            )
            try:
                result = await self._call_stage_preferring_json(
                    stage="coverage",
                    prompt=prompt_text,
                )
            except RuntimeError as exc:
                if "OpenRouter 回傳內容為空" not in str(exc):
                    raise
                logger.warning("%s %s 發生空內容回應，將進入後續補救流程", stage_name, call_label)
                return None
            _accumulate(result)
            return result

        parsed: Any
        parse_error: Optional[ValueError] = None

        first_result = await _call_stage_with_empty_tolerance(
            prompt_text=prompt,
            call_label="初次呼叫",
        )
        first_finish_reason = (
            getattr(first_result, "finish_reason", None)
            if first_result is not None
            else None
        )
        first_truncated = self._is_likely_truncated_finish_reason(first_finish_reason)
        if first_result is None:
            parse_error = ValueError("OpenRouter 回傳內容為空")
        else:
            try:
                parsed = JiraTestCaseHelperLLMService.parse_json_payload(first_result.content)
            except ValueError as first_exc:
                parse_error = first_exc
        if first_truncated:
            parse_error = parse_error or ValueError("LLM 回應可能因長度截斷")

        regenerate_result: Optional[Any] = None
        if parse_error is not None:
            regenerate_applied = True
            logger.warning("%s JSON 解析失敗，先執行完整重生: %s", stage_name, parse_error)
            regenerate_result = await _call_stage_with_empty_tolerance(
                prompt_text=prompt,
                call_label="重生呼叫",
            )
            if regenerate_result is None:
                parse_error = ValueError("OpenRouter 回傳內容為空")
            else:
                try:
                    parsed = JiraTestCaseHelperLLMService.parse_json_payload(
                        regenerate_result.content
                    )
                    parse_error = None
                except ValueError as regenerate_exc:
                    parse_error = regenerate_exc
                if self._is_likely_truncated_finish_reason(
                    getattr(regenerate_result, "finish_reason", None)
                ):
                    parse_error = parse_error or ValueError("LLM 回應可能因長度截斷")

        if parse_error is not None:
            repair_applied = True
            logger.warning(
                "%s 重生後仍解析失敗，改用 JSON repair: %s",
                stage_name,
                parse_error,
            )
            repair_prompt = self._build_json_repair_prompt(
                review_language=review_language,
                stage_name=stage_name,
                schema_example=schema_example,
                raw_content=(
                    regenerate_result.content
                    if regenerate_result is not None
                    else (first_result.content if first_result is not None else "{}")
                ),
            )
            repair_result = await _call_stage_with_empty_tolerance(
                prompt_text=repair_prompt,
                call_label="JSON repair 呼叫",
            )
            if repair_result is None:
                logger.warning("%s JSON repair 仍為空內容，改採空 coverage payload 降級", stage_name)
                parsed = {
                    "seed": [],
                    "trace": {
                        "empty_response_fallback": True,
                    },
                }
            else:
                try:
                    parsed = JiraTestCaseHelperLLMService.parse_json_payload(
                        repair_result.content
                    )
                except ValueError as repair_exc:
                    raise ValueError(f"{stage_name} 回傳 JSON 解析失敗: {repair_exc}") from repair_exc

        if not isinstance(parsed, dict):
            raise ValueError(f"{stage_name} 回傳 JSON 結構錯誤")

        return {
            "payload_raw": parsed,
            "usage": usage,
            "cost": cost,
            "cost_note": cost_note,
            "response_id": response_id,
            "regenerate_applied": regenerate_applied,
            "repair_applied": repair_applied,
        }

    @staticmethod
    def _make_seq_no(index: int, base_start: int = 10) -> str:
        value = base_start + index * 10
        return str(value).zfill(3)

    @staticmethod
    def _parse_seq_base(initial_middle: str) -> int:
        try:
            base_start = int(str(initial_middle or "").strip())
        except (TypeError, ValueError):
            return 10
        if base_start < 10 or base_start > 990 or base_start % 10 != 0:
            return 10
        return base_start

    @staticmethod
    def _extract_middle_no_from_case_id(case_id: str) -> str:
        parts = [item.strip() for item in str(case_id or "").split(".") if item.strip()]
        if len(parts) < 2:
            return ""
        candidate = parts[-2]
        return candidate if re.fullmatch(r"\d{3}", candidate) else ""

    @classmethod
    def _normalize_section_path_with_middle(
        cls,
        *,
        section_path: str,
        case_id: str,
    ) -> str:
        normalized = str(section_path or "").strip() or "Unassigned"
        if normalized.lower() == "unassigned":
            return normalized

        middle_no = cls._extract_middle_no_from_case_id(case_id)
        if not middle_no:
            return normalized

        if "/" in normalized:
            parts = [item.strip() for item in normalized.split("/") if item.strip()]
            if not parts:
                return f"{middle_no} 未分類"
            first = re.sub(r"^\d{3}\s+", "", parts[0]).strip() or "未分類"
            rebuilt = [f"{middle_no} {first}"] + parts[1:]
            return "/".join(rebuilt)

        leaf = re.sub(r"^\d{3}\s+", "", normalized).strip() or "未分類"
        return f"{middle_no} {leaf}"

    def _normalize_stage1_payload_for_generation(
        self,
        *,
        stage1_payload: Dict[str, Any],
        initial_middle: str,
    ) -> Dict[str, Any]:
        payload = stage1_payload if isinstance(stage1_payload, dict) else {}
        source_entries: List[Dict[str, Any]] = []

        raw_entries = payload.get("en")
        if isinstance(raw_entries, list):
            source_entries.extend(item for item in raw_entries if isinstance(item, dict))

        if not source_entries:
            for section in payload.get("sec", []) or []:
                if not isinstance(section, dict):
                    continue
                group = str(section.get("g") or "").strip() or "未分類"
                for entry in section.get("en", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    merged = dict(entry)
                    if not str(merged.get("g") or "").strip():
                        merged["g"] = group
                    source_entries.append(merged)

        if not source_entries and isinstance(payload.get("coverage_plan"), dict):
            coverage_sections = payload["coverage_plan"].get("sections") or []
            if isinstance(coverage_sections, list):
                for section in coverage_sections:
                    if not isinstance(section, dict):
                        continue
                    group = str(section.get("title") or section.get("section_id") or "").strip() or "未分類"
                    for vi in section.get("verification_items") or []:
                        if not isinstance(vi, dict):
                            continue
                        source_entries.append(
                            {
                                "g": group,
                                "t": str(vi.get("intent") or "").strip(),
                                "cat": (
                                    "negative"
                                    if any(
                                        str(item.get("kind") or "").strip().lower() == "negative"
                                        for item in (vi.get("variants") or [])
                                        if isinstance(item, dict)
                                    )
                                    else (
                                        "boundary"
                                        if any(
                                            str(item.get("kind") or "").strip().lower() == "boundary"
                                            for item in (vi.get("variants") or [])
                                            if isinstance(item, dict)
                                        )
                                        else "happy"
                                    )
                                ),
                                "st": "ok",
                                "ref": [str(vi.get("verification_item_id") or "").strip()],
                                "rid": self._unique_preserve(
                                    [str(v).strip() for v in ((vi.get("trace") or {}).get("rule_ids") or []) if str(v).strip()]
                                    + [str(v).strip() for v in ((vi.get("trace") or {}).get("flow_ids") or []) if str(v).strip()]
                                    + [str(v).strip() for v in ((vi.get("trace") or {}).get("entity_ids") or []) if str(v).strip()]
                                ),
                                "chk": self._to_text_list(vi.get("action_hints")),
                                "exp": self._to_text_list(vi.get("expected_observable")),
                                "pre_hint": self._to_text_list(vi.get("setup_hints")),
                                "step_hint": self._to_text_list(vi.get("action_hints")),
                                "trace": {"source_refs": vi.get("source_refs") or []},
                            }
                        )

        normalized_entries: List[Dict[str, Any]] = []
        for idx, raw in enumerate(source_entries, start=1):
            refs = [
                str(item).strip()
                for item in (raw.get("ref") or [])
                if str(item).strip()
            ] if isinstance(raw.get("ref"), list) else []
            req_items = raw.get("req")
            req_list = req_items if isinstance(req_items, list) else []
            rid = [
                str(item).strip()
                for item in (raw.get("rid") or [])
                if str(item).strip()
            ] if isinstance(raw.get("rid"), list) else []

            entry: Dict[str, Any] = {
                "idx": idx,
                "g": str(raw.get("g") or "").strip() or "未分類",
                "t": str(raw.get("t") or "").strip(),
                "cat": self._normalize_seed_category(raw.get("cat")),
                "st": str(raw.get("st") or "ok").strip().lower() or "ok",
                "ref": refs,
                "rid": rid,
                "req": req_list,
                "chk": self._to_text_list(raw.get("chk")),
                "exp": self._to_text_list(raw.get("exp")),
                "pre_hint": self._to_text_list(raw.get("pre_hint")),
                "step_hint": self._to_text_list(raw.get("step_hint")),
                "requirement_key": str(raw.get("requirement_key") or "").strip(),
            }
            if isinstance(raw.get("requirement_context"), dict):
                entry["requirement_context"] = raw.get("requirement_context")
            raw_sid = str(raw.get("raw_sid") or "").strip()
            if raw_sid:
                entry["raw_sid"] = raw_sid
            assume_note = str(raw.get("a") or "").strip()
            ask_note = str(raw.get("q") or "").strip()
            if entry["st"] == "assume" and assume_note:
                entry["a"] = assume_note
            elif entry["st"] == "ask" and ask_note:
                entry["q"] = ask_note
            if isinstance(raw.get("trace"), dict):
                entry["trace"] = raw.get("trace")
            normalized_entries.append(entry)

        grouped_sections: List[Dict[str, Any]] = []
        section_index: Dict[str, int] = {}
        for entry in normalized_entries:
            group = str(entry.get("g") or "").strip() or "未分類"
            if group not in section_index:
                section_index[group] = len(grouped_sections)
                grouped_sections.append({"g": group, "en": []})
            grouped_sections[section_index[group]]["en"].append(entry)

        base_start = self._parse_seq_base(initial_middle)
        flattened_entries: List[Dict[str, Any]] = []
        for sec_idx, section in enumerate(grouped_sections):
            section_no = self._make_seq_no(sec_idx, base_start=base_start)
            section["sn"] = section_no
            section_entries: List[Dict[str, Any]] = []
            for entry_idx, entry in enumerate(section.get("en", []) or []):
                test_no = self._make_seq_no(entry_idx, base_start=base_start)
                cid = f"{section_no}.{test_no}"
                entry["sn"] = section_no
                entry["tn"] = test_no
                entry["cid"] = cid
                section_entries.append(entry)
                flattened_entries.append(entry)
            section["en"] = section_entries

        normalized_payload: Dict[str, Any] = {
            "sec": grouped_sections,
            "en": flattened_entries,
        }
        for key in ("lang", "user_notes", "coverage_plan"):
            if key in payload:
                normalized_payload[key] = payload.get(key)
        return normalized_payload

    def _build_stage1_entries(
        self,
        *,
        analysis_payload: Dict[str, Any],
        coverage_payload: Dict[str, Any],
        initial_middle: str,
        coverage_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        has_seed_entries = bool(
            isinstance(coverage_payload, dict)
            and isinstance(coverage_payload.get("seed"), list)
            and (coverage_payload.get("seed") or [])
        )
        plan_sections = (
            coverage_plan.get("sections")
            if isinstance(coverage_plan, dict)
            else []
        )
        if not has_seed_entries and isinstance(plan_sections, list) and plan_sections:
            base_start = self._parse_seq_base(initial_middle)
            sections: List[Dict[str, Any]] = []
            entries: List[Dict[str, Any]] = []
            for sec_idx, section in enumerate(plan_sections):
                if not isinstance(section, dict):
                    continue
                section_group = str(section.get("title") or section.get("section_id") or "未分類").strip()
                section_no = self._make_seq_no(sec_idx, base_start=base_start)
                section_entries: List[Dict[str, Any]] = []
                for entry_idx, vi in enumerate(section.get("verification_items") or []):
                    if not isinstance(vi, dict):
                        continue
                    test_no = self._make_seq_no(entry_idx, base_start=base_start)
                    cid = f"{section_no}.{test_no}"
                    variants = vi.get("variants") if isinstance(vi.get("variants"), list) else []
                    variant_kind = (
                        str(variants[0].get("kind") or "").strip().lower()
                        if variants and isinstance(variants[0], dict)
                        else "positive"
                    )
                    cat = "happy"
                    if variant_kind == "negative":
                        cat = "negative"
                    elif variant_kind == "boundary":
                        cat = "boundary"
                    trace = vi.get("trace") if isinstance(vi.get("trace"), dict) else {}
                    rid_values = self._unique_preserve(
                        [str(v).strip() for v in trace.get("rule_ids") or [] if str(v).strip()]
                        + [str(v).strip() for v in trace.get("flow_ids") or [] if str(v).strip()]
                        + [str(v).strip() for v in trace.get("entity_ids") or [] if str(v).strip()]
                    )
                    entry: Dict[str, Any] = {
                        "idx": len(entries) + 1,
                        "g": section_group,
                        "sn": section_no,
                        "tn": test_no,
                        "cid": cid,
                        "t": str(vi.get("intent") or "").strip() or "需求驗證",
                        "cat": cat,
                        "st": "ok",
                        "ref": [str(vi.get("verification_item_id") or "").strip()],
                        "rid": rid_values,
                        "req": [],
                        "chk": self._to_text_list(vi.get("action_hints")),
                        "exp": self._to_text_list(vi.get("expected_observable")),
                        "pre_hint": self._to_text_list(vi.get("setup_hints")),
                        "step_hint": self._to_text_list(vi.get("action_hints")),
                        "trace": {
                            "coverage_vi": str(vi.get("verification_item_id") or "").strip(),
                            "section_id": str(section.get("section_id") or "").strip(),
                            "source_refs": vi.get("source_refs") or [],
                        },
                    }
                    section_entries.append(entry)
                    entries.append(entry)
                if section_entries:
                    sections.append({"g": section_group, "sn": section_no, "en": section_entries})
            if sections:
                return {"sec": sections, "en": entries}

        item_map: Dict[str, Dict[str, Any]] = {}
        for item in analysis_payload.get("it", []) or []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id:
                item_map[item_id] = item

        raw_entries: List[Dict[str, Any]] = []
        for seed in coverage_payload.get("seed", []) or []:
            if not isinstance(seed, dict):
                continue
            refs = [
                str(v).strip()
                for v in (seed.get("ref") or [])
                if str(v).strip()
            ]
            requirements: List[Dict[str, Any]] = []
            for ref in refs:
                item = item_map.get(ref)
                if not item:
                    continue
                requirements.append(
                    {
                        "id": str(item.get("id") or "").strip(),
                        "t": str(item.get("t") or "").strip(),
                        "det": item.get("det") or [],
                        "chk": item.get("chk") or [],
                        "exp": item.get("exp") or [],
                        "rid": item.get("rid") or [],
                    }
                )

            seed_rid = [
                str(v).strip()
                for v in (seed.get("rid") or [])
                if str(v).strip()
            ]
            if not seed_rid:
                for req_item in requirements:
                    for rid in req_item.get("rid") or []:
                        rid_value = str(rid).strip()
                        if rid_value and rid_value not in seed_rid:
                            seed_rid.append(rid_value)

            entry: Dict[str, Any] = {
                "idx": seed.get("idx"),
                "g": str(seed.get("g") or "").strip() or "未分類",
                "t": str(seed.get("t") or "").strip(),
                "ax": str(seed.get("ax") or seed.get("aspect") or "").strip().lower(),
                "cat": str(seed.get("cat") or "").strip().lower(),
                "st": str(seed.get("st") or "ok").strip().lower(),
                "ref": refs,
                "rid": seed_rid,
                "req": requirements,
                "chk": self._to_text_list(seed.get("chk")),
                "exp": self._to_text_list(seed.get("exp")),
                "pre_hint": self._to_text_list(seed.get("pre_hint")),
                "step_hint": self._to_text_list(seed.get("step_hint")),
                "trace": {
                    "analysis_refs": refs,
                    "rid": seed_rid,
                    "aspect": str(seed.get("ax") or seed.get("aspect") or "").strip().lower(),
                },
            }
            if seed.get("sid"):
                entry["raw_sid"] = str(seed.get("sid") or "").strip()
            if seed.get("a"):
                entry["a"] = str(seed.get("a")).strip()
            if seed.get("q"):
                entry["q"] = str(seed.get("q")).strip()
            raw_entries.append(entry)

        sections: List[Dict[str, Any]] = []
        section_index: Dict[str, int] = {}
        for entry in raw_entries:
            group = str(entry.get("g") or "").strip() or "未分類"
            if group not in section_index:
                section_index[group] = len(sections)
                sections.append({"g": group, "en": []})
            sections[section_index[group]]["en"].append(entry)

        base_start = self._parse_seq_base(initial_middle)

        entries: List[Dict[str, Any]] = []
        for sec_idx, section in enumerate(sections):
            section_no = self._make_seq_no(sec_idx, base_start=base_start)
            section["sn"] = section_no
            sec_entries: List[Dict[str, Any]] = []
            for entry_idx, entry in enumerate(section.get("en", []) or []):
                test_no = self._make_seq_no(entry_idx, base_start=base_start)
                cid = f"{section_no}.{test_no}"
                entry["sn"] = section_no
                entry["tn"] = test_no
                entry["cid"] = cid
                sec_entries.append(entry)
                entries.append(entry)
            section["en"] = sec_entries

        return {"sec": sections, "en": entries}

    @staticmethod
    def _stage1_entries_markdown(stage1_payload: Dict[str, Any]) -> str:
        lines: List[str] = ["## Stage 1 條目（Analysis + Coverage）"]
        sections = stage1_payload.get("sec", []) or []
        if not sections:
            lines.append("（無資料）")
            return "\n".join(lines)

        for section in sections:
            if not isinstance(section, dict):
                continue
            section_no = str(section.get("sn") or "").strip()
            group = str(section.get("g") or "未分類").strip()
            header = f"{section_no} {group}".strip()
            lines.append(f"\n### {header}")
            for entry in section.get("en", []) or []:
                if not isinstance(entry, dict):
                    continue
                cid = str(entry.get("cid") or "").strip()
                title = str(entry.get("t") or "").strip()
                lines.append(f"- {cid} {title}".strip())
                cat = str(entry.get("cat") or "").strip()
                st = str(entry.get("st") or "").strip()
                refs = ",".join(entry.get("ref", []) or [])
                meta = [item for item in [cat, st, f"ref:{refs}" if refs else ""] if item]
                if meta:
                    lines.append(f"  {' | '.join(meta)}")
                chk_items = [str(v).strip() for v in (entry.get("chk") or []) if str(v).strip()]
                if chk_items:
                    lines.append("  - checks:")
                    for check in chk_items:
                        lines.append(f"    - {check}")
                exp_items = [str(v).strip() for v in (entry.get("exp") or []) if str(v).strip()]
                if exp_items:
                    lines.append("  - expected:")
                    for expected in exp_items:
                        lines.append(f"    - {expected}")
        return "\n".join(lines)

    @staticmethod
    def _build_similar_cases_text(
        points: Dict[str, Any],
        *,
        max_cases: int,
        max_length: int,
    ) -> str:
        result_lines: List[str] = []
        candidates: List[Dict[str, Any]] = []
        preferred_order = ["jira_references", "jira_referances", "test_cases", "usm_nodes"]
        source_keys = preferred_order + [
            key for key in points.keys() if key not in preferred_order
        ]
        for source_key in source_keys:
            for point in points.get(source_key, []) or []:
                payload = getattr(point, "payload", None) or {}
                text = (
                    str(payload.get("text") or payload.get("title") or payload.get("content") or "")
                    .strip()
                )
                if not text:
                    continue
                score = float(getattr(point, "score", 0.0) or 0.0)
                candidates.append(
                    {
                        "source": source_key,
                        "score": score,
                        "text": text[: max(50, max_length)],
                    }
                )

        candidates.sort(key=lambda item: item["score"], reverse=True)
        for idx, item in enumerate(candidates[:max_cases], start=1):
            result_lines.append(
                f"Similar Case {idx} [{item['source']} score={item['score']:.4f}]:\n{item['text']}"
            )
        return "\n\n".join(result_lines)

    @staticmethod
    def _build_section_query_text(
        *,
        ticket_key: str,
        ticket_summary: str,
        ticket_description: str,
        section_name: str,
        section_entries: List[Dict[str, Any]],
    ) -> str:
        lines: List[str] = [
            f"Ticket: {ticket_key}",
            f"Summary: {ticket_summary}",
            f"Section: {section_name}",
        ]
        description = str(ticket_description or "").strip()
        if description:
            lines.append(f"Description: {description[:1200]}")
        for entry in section_entries[:20]:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("t") or "").strip()
            checks = [
                str(value).strip()
                for value in (entry.get("chk") or [])
                if str(value).strip()
            ]
            expected = [
                str(value).strip()
                for value in (entry.get("exp") or [])
                if str(value).strip()
            ]
            if title:
                lines.append(f"- entry: {title}")
            if checks:
                lines.append(f"  checks: {'; '.join(checks[:8])}")
            if expected:
                lines.append(f"  expected: {'; '.join(expected[:8])}")
        return "\n".join(lines)

    async def _query_generation_similar_cases(
        self,
        *,
        ticket_key: str,
        ticket_summary: str,
        ticket_description: str,
        section_name: str,
        section_entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        helper_cfg = self.settings.ai.jira_testcase_helper
        query_text = self._build_section_query_text(
            ticket_key=ticket_key,
            ticket_summary=ticket_summary,
            ticket_description=ticket_description,
            section_name=section_name,
            section_entries=section_entries,
        ).strip()
        if not query_text:
            return {"text": "", "retrieved_refs": []}
        try:
            embedding = await self.llm_service.create_embedding(query_text[:4000])
            vector = list(embedding)
            qdrant_client = get_qdrant_client()
            points: Dict[str, Any] = {}

            jira_points = await qdrant_client.query_jira_referances_context(vector)
            points["jira_references"] = jira_points

            if hasattr(qdrant_client, "query_test_cases_context"):
                test_case_points = await qdrant_client.query_test_cases_context(vector)
                points["test_cases"] = test_case_points
            elif hasattr(qdrant_client, "query_points"):
                response = await qdrant_client.query_points(
                    collection_name=self.settings.qdrant.collection_test_cases,
                    query=vector,
                    limit=self.settings.qdrant.limit.test_cases,
                    with_payload=True,
                    with_vectors=False,
                )
                points["test_cases"] = response.points or []

            similar_text = self._build_similar_cases_text(
                points,
                max_cases=helper_cfg.similar_cases_count,
                max_length=helper_cfg.similar_cases_max_length,
            )
            retrieved_refs: List[Dict[str, Any]] = []
            for source_key in ["jira_references", "jira_referances", "test_cases"]:
                for point in points.get(source_key, []) or []:
                    payload = getattr(point, "payload", None) or {}
                    snippet = str(
                        payload.get("text")
                        or payload.get("title")
                        or payload.get("content")
                        or ""
                    ).strip()
                    if not snippet:
                        continue
                    collection = "jira_references" if source_key in {"jira_references", "jira_referances"} else "test_cases"
                    point_id = getattr(point, "id", None)
                    retrieved_refs.append(
                        {
                            "ref_id": str(point_id) if point_id is not None else "",
                            "collection": collection,
                            "score": float(getattr(point, "score", 0.0) or 0.0),
                            "snippet": snippet[:500],
                        }
                    )
            return {"text": similar_text, "retrieved_refs": retrieved_refs}
        except Exception as exc:
            logger.warning("Qdrant generation context 查詢失敗（section=%s）: %s", section_name, exc)
            return {"text": "", "retrieved_refs": []}

    async def analyze_and_build_pretestcase(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperAnalyzeRequest,
        override_actor: Optional[Dict[str, Any]] = None,
    ) -> HelperStageResultResponse:
        session_data = await self.get_session(team_id=team_id, session_id=session_id)
        ticket_draft = next(
            (item for item in session_data.drafts if item.phase == "jira_ticket"),
            None,
        )
        requirement_draft = next(
            (item for item in session_data.drafts if item.phase == "requirement"),
            None,
        )
        helper_cfg = self.settings.ai.jira_testcase_helper
        enable_ir_first = bool(helper_cfg.enable_ir_first)
        merged_analysis_coverage = True
        ticket_payload = ticket_draft.payload if ticket_draft and ticket_draft.payload else {}
        ticket_key = session_data.ticket_key or str(ticket_payload.get("ticket_key") or "")
        if not ticket_key:
            raise ValueError("請先提供 TCG 單號並讀取 JIRA ticket")

        ticket_description = str(ticket_payload.get("description") or "")
        requirement_markdown = (
            request.requirement_markdown
            if request.requirement_markdown is not None
            else (
                requirement_draft.markdown
                if requirement_draft and requirement_draft.markdown
                else ticket_description
            )
        )
        requirement_markdown = (requirement_markdown or "").strip()
        if not requirement_markdown:
            raise ValueError("需求內容為空，請先確認 JIRA 描述或補上需求內容")

        structured_requirement = self.requirement_parser.parse(requirement_markdown)
        requirement_validation = self.requirement_validator.validate(structured_requirement)
        contract_versions = self.prompt_service.get_contract_versions()
        override_trace: Dict[str, Any] = {}
        enforce_requirement_gate = request.requirement_markdown is not None

        if (
            enforce_requirement_gate
            and not requirement_validation.get("is_complete")
            and not request.override_incomplete_requirement
        ):
            logger.info(
                "[AI-HELPER][requirement-validation] ticket=%s status=warning missing_sections=%s missing_fields=%s quality_level=%s override=%s",
                ticket_key,
                requirement_validation.get("missing_sections", []),
                requirement_validation.get("missing_fields", []),
                requirement_validation.get("quality_level", "low"),
                False,
            )
            warning_payload = {
                "structured_requirement": structured_requirement,
                "requirement_validation": requirement_validation,
                "contract_versions": contract_versions,
                "requires_override": True,
                "warning": {
                    "code": "INCOMPLETE_REQUIREMENT",
                    "message": "Requirement 格式不完整，請先修正或確認仍要繼續。",
                    "missing_sections": requirement_validation.get("missing_sections", []),
                    "missing_fields": requirement_validation.get("missing_fields", []),
                    "quality_level": requirement_validation.get("quality_level", "low"),
                },
            }

            def _persist_warning(sync_db: Session) -> HelperSessionResponse:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="requirement",
                    markdown=requirement_markdown,
                    payload={
                        "review_locale": session.review_locale,
                        "structured_requirement": structured_requirement,
                        "requirement_validation": requirement_validation,
                        "contract_versions": contract_versions,
                    },
                    increment_version=request.requirement_markdown is not None,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.REQUIREMENT,
                    phase_status=HelperPhaseStatus.WAITING_CONFIRM,
                    status=HelperSessionStatus.ACTIVE,
                    last_error=None,
                    enforce_transition=False,
                )
                sync_db.commit()
                _, drafts = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                return self._to_session_response(session, drafts)

            warned_session = await run_sync(self.db, _persist_warning)
            return HelperStageResultResponse(
                session=warned_session,
                stage="requirement_validation_warning",
                payload=warning_payload,
                markdown=requirement_markdown,
                usage={},
            )

        if (
            enforce_requirement_gate
            and not requirement_validation.get("is_complete")
            and request.override_incomplete_requirement
        ):
            logger.info(
                "[AI-HELPER][requirement-validation] ticket=%s status=warning override=%s quality_level=%s missing_sections=%s missing_fields=%s actor=%s",
                ticket_key,
                True,
                requirement_validation.get("quality_level", "low"),
                requirement_validation.get("missing_sections", []),
                requirement_validation.get("missing_fields", []),
                str((override_actor or {}).get("username") or ""),
            )
            override_trace = {
                "override": True,
                "timestamp": _now().isoformat() + "Z",
                "actor": {
                    "user_id": str((override_actor or {}).get("user_id") or ""),
                    "username": str((override_actor or {}).get("username") or ""),
                },
                "missing_sections": requirement_validation.get("missing_sections", []),
                "missing_fields": requirement_validation.get("missing_fields", []),
                "quality_level": requirement_validation.get("quality_level", "low"),
            }

        similar_cases = ""
        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_components = ", ".join(ticket_payload.get("components") or []) or "N/A"
        review_language = _locale_label(session_data.review_locale.value)

        def _mark_running(sync_db: Session) -> None:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            self._set_session_phase(
                session,
                phase=HelperPhase.ANALYSIS,
                phase_status=HelperPhaseStatus.RUNNING,
                status=HelperSessionStatus.ACTIVE,
                enforce_transition=False,
            )
            sync_db.commit()

        await run_sync(self.db, _mark_running)

        try:
            requirement_ir_result = await self.build_requirement_ir(
                session_data=session_data,
                ticket_payload=ticket_payload,
                requirement_markdown=requirement_markdown,
                similar_cases=similar_cases,
                structured_requirement=structured_requirement,
            )
            requirement_ir_payload = requirement_ir_result.get("requirement_ir") or {}
            requirement_ir_json = json.dumps(
                requirement_ir_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            analysis_prompt = self.prompt_service.render_machine_stage_prompt(
                "analysis",
                {
                    "review_language": review_language,
                    "ticket_key": ticket_key,
                    "requirement_ir_json": requirement_ir_json,
                },
            )
            analysis_fallback_applied = False
            analysis_fallback_reason = ""
            analysis_call = await self._call_json_stage_with_retry(
                stage="analysis",
                prompt=analysis_prompt,
                review_language=review_language,
                stage_name="Analysis",
                schema_example='{"analysis":{"sec":[{"g":"功能名稱","it":[{"id":"010.001","t":"...","det":["..."],"chk":["..."],"exp":["..."],"rid":["REQ-001"],"source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}]}],"it":[{"id":"010.001","t":"...","det":["..."],"chk":["..."],"exp":["..."],"rid":["REQ-001"],"source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}]},"coverage":{"sec":[{"g":"功能名稱","seed":[{"g":"功能名稱","t":"...","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":["REQ-001"],"chk":["..."],"exp":["..."],"pre_hint":["..."],"step_hint":["..."],"source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}]}],"seed":[{"g":"功能名稱","t":"...","ax":"happy","cat":"happy","st":"ok","a":"","ref":["010.001"],"rid":["REQ-001"],"chk":["..."],"exp":["..."],"pre_hint":["..."],"step_hint":["..."],"source_refs":[{"chunk_id":"desc","sentence_ids":[0]}]}],"trace":{"analysis_item_count":1,"covered_item_count":1,"missing_ids":[],"missing_sections":[],"aspect_review":{"happy":"covered","edge":"covered","error":"covered","permission":"assume"}}}}',
            )
            analysis_result_payload = analysis_call.get("payload_raw") or {}
            if not isinstance(analysis_result_payload, dict):
                raise ValueError("Analysis 合併輸出格式錯誤：payload 必須為 JSON 物件")

            analysis_payload_raw = analysis_result_payload.get("analysis")
            coverage_payload_raw_from_analysis = analysis_result_payload.get("coverage")
            if not isinstance(analysis_payload_raw, dict):
                raise ValueError("Analysis 合併輸出缺少 analysis 物件")
            if not isinstance(coverage_payload_raw_from_analysis, dict):
                raise ValueError("Analysis 合併輸出缺少 coverage 物件")

            analysis_payload = self._normalize_analysis_payload(analysis_payload_raw)
            if enable_ir_first and not (analysis_payload.get("it") or []):
                raise ValueError("Analysis 合併輸出無有效 analysis item")

            coverage_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            coverage_cost = 0.0
            coverage_cost_note = ""
            coverage_response_id: Optional[str] = analysis_call.get("response_id")
            coverage_regenerate_applied = bool(analysis_call.get("regenerate_applied"))
            coverage_repair_applied = bool(analysis_call.get("repair_applied"))
            coverage_fallback_applied = False
            coverage_fallback_reason = ""
            coverage_payload: Dict[str, Any] = {"sec": [], "seed": [], "trace": {}}
            coverage_payload = self._normalize_coverage_payload(
                coverage_payload_raw_from_analysis,
                analysis_payload,
                requirement_ir=requirement_ir_payload,
            )
            merged_coverage_from_analysis = bool(coverage_payload.get("seed"))
            if not merged_coverage_from_analysis:
                raise ValueError("Analysis 合併輸出無有效 coverage.seed")

            analysis_coverage_retry_attempted = False
            analysis_coverage_retry_succeeded = False
            backfill_rounds = 0
            backfill_batch_count = 0
            deterministic_backfill_applied = False
            deterministic_backfill_seed_count = 0
            completeness = self.validate_coverage_completeness(
                analysis_payload=analysis_payload,
                coverage_payload=coverage_payload,
            )
            if enable_ir_first and not completeness.get("is_complete"):
                missing_ids = [
                    str(item_id).strip()
                    for item_id in (completeness.get("missing_ids") or [])
                    if str(item_id).strip()
                ]
                missing_sections = [
                    str(section).strip()
                    for section in (completeness.get("missing_sections") or [])
                    if str(section).strip()
                ]
                raise ValueError(
                    "Coverage 完整性檢查未通過: "
                    f"missing_ids={missing_ids}, missing_sections={missing_sections}"
                )

            aspect_completeness = self.validate_coverage_aspects(
                coverage_payload=coverage_payload
            )
            if not aspect_completeness.get("is_complete"):
                raise ValueError(
                    "Coverage 面向檢查未通過: "
                    f"missing_aspects={aspect_completeness.get('missing_aspects', [])}"
                )

            coverage_payload["trace"] = {
                **(coverage_payload.get("trace") if isinstance(coverage_payload.get("trace"), dict) else {}),
                "analysis_item_count": completeness.get("analysis_item_count", 0),
                "covered_item_count": completeness.get("covered_item_count", 0),
                "missing_ids": completeness.get("missing_ids", []),
                "missing_sections": completeness.get("missing_sections", []),
                "required_aspects": aspect_completeness.get("required_aspects", []),
                "covered_aspects": aspect_completeness.get("covered_aspects", []),
                "missing_aspects": aspect_completeness.get("missing_aspects", []),
                "aspect_counts": aspect_completeness.get("aspect_counts", {}),
                "requirement_quality_level": requirement_validation.get("quality_level"),
                "requirement_missing_sections": requirement_validation.get("missing_sections", []),
                "requirement_missing_fields": requirement_validation.get("missing_fields", []),
                "requirement_warning_override": bool(override_trace.get("override")),
                "backfill_rounds": backfill_rounds,
                "backfill_batch_count": backfill_batch_count,
                "deterministic_backfill_applied": deterministic_backfill_applied,
                "deterministic_backfill_seed_count": deterministic_backfill_seed_count,
                "coverage_fallback_applied": coverage_fallback_applied,
                "coverage_fallback_reason": coverage_fallback_reason,
                "analysis_coverage_retry_attempted": analysis_coverage_retry_attempted,
                "analysis_coverage_retry_succeeded": analysis_coverage_retry_succeeded,
                "merged_analysis_coverage": merged_analysis_coverage,
                "merged_coverage_from_analysis": merged_coverage_from_analysis,
            }

            logger.info(
                "[AI-HELPER][coverage] ticket=%s analysis_items=%s covered=%s missing_ids=%s missing_sections=%s missing_aspects=%s",
                ticket_key,
                completeness.get("analysis_item_count", 0),
                completeness.get("covered_item_count", 0),
                completeness.get("missing_ids", []),
                completeness.get("missing_sections", []),
                aspect_completeness.get("missing_aspects", []),
            )

            coverage_plan = self._build_coverage_plan(
                ticket_id=ticket_key,
                requirement_ir=requirement_ir_payload,
                analysis_payload=analysis_payload,
                coverage_payload=coverage_payload,
            )
            stage1_payload = self._build_stage1_entries(
                analysis_payload=analysis_payload,
                coverage_payload=coverage_payload,
                initial_middle=session_data.initial_middle,
                coverage_plan=coverage_plan,
            )
            stage1_payload = self.pretestcase_presenter.enrich_stage1_payload(
                stage1_payload=stage1_payload,
                analysis_payload=analysis_payload,
                requirement_ir=requirement_ir_payload,
                structured_requirement=structured_requirement,
            )
            stage1_payload["lang"] = session_data.review_locale.value
            stage1_payload["coverage_plan"] = coverage_plan
            stage1_payload["contract_versions"] = contract_versions
            if request.user_notes and request.user_notes.strip():
                stage1_payload["user_notes"] = request.user_notes.strip()
            stage1_markdown = self._stage1_entries_markdown(stage1_payload)

            total_usage = {
                "prompt_tokens": requirement_ir_result.get("usage", {}).get("prompt_tokens", 0)
                + analysis_call.get("usage", {}).get("prompt_tokens", 0)
                + coverage_usage.get("prompt_tokens", 0),
                "completion_tokens": requirement_ir_result.get("usage", {}).get(
                    "completion_tokens", 0
                )
                + analysis_call.get("usage", {}).get("completion_tokens", 0)
                + coverage_usage.get("completion_tokens", 0),
                "total_tokens": requirement_ir_result.get("usage", {}).get("total_tokens", 0)
                + analysis_call.get("usage", {}).get("total_tokens", 0)
                + coverage_usage.get("total_tokens", 0),
            }
            total_cost = (
                float(requirement_ir_result.get("cost") or 0.0)
                + float(analysis_call.get("cost") or 0.0)
                + coverage_cost
            )
            total_cost_note = (
                "（含未知費用）"
                if requirement_ir_result.get("cost_note")
                or analysis_call.get("cost_note")
                or coverage_cost_note
                else ""
            )

            def _persist_success(sync_db: Session) -> HelperSessionResponse:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="requirement",
                    markdown=requirement_markdown,
                    payload={
                        "review_locale": session.review_locale,
                        "structured_requirement": structured_requirement,
                        "requirement_validation": requirement_validation,
                        "override_trace": override_trace,
                        "contract_versions": contract_versions,
                    },
                    quality={
                        "quality_level": requirement_validation.get("quality_level"),
                        "is_complete": requirement_validation.get("is_complete", False),
                    },
                    trace={
                        "missing_sections": requirement_validation.get("missing_sections", []),
                        "missing_fields": requirement_validation.get("missing_fields", []),
                        "override": bool(override_trace.get("override")),
                    },
                    increment_version=request.requirement_markdown is not None,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="requirement_ir",
                    payload={
                        "requirement_ir": requirement_ir_payload,
                        "source_packets": requirement_ir_result.get("source_packets") or {},
                        "usage": requirement_ir_result.get("usage") or {},
                        "cost": requirement_ir_result.get("cost") or 0.0,
                        "cost_note": requirement_ir_result.get("cost_note") or "",
                        "response_id": requirement_ir_result.get("response_id"),
                        "repair_applied": requirement_ir_result.get("repair_applied", False),
                        "regenerate_applied": requirement_ir_result.get(
                            "regenerate_applied", False
                        ),
                        "fallback_applied": requirement_ir_result.get(
                            "fallback_applied", False
                        ),
                        "fallback_reason": requirement_ir_result.get(
                            "fallback_reason", ""
                        ),
                        "enabled": requirement_ir_result.get("enabled", True),
                        "structured_requirement": structured_requirement,
                        "contract_versions": contract_versions,
                    },
                    quality={
                        "quality_level": requirement_validation.get("quality_level"),
                        "is_complete": requirement_validation.get("is_complete", False),
                    },
                    trace={
                        "override": bool(override_trace.get("override")),
                    },
                    increment_version=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="analysis",
                    payload={
                        "analysis": analysis_payload,
                        "usage": analysis_call.get("usage") or {},
                        "cost": analysis_call.get("cost") or 0.0,
                        "cost_note": analysis_call.get("cost_note") or "",
                        "response_id": analysis_call.get("response_id"),
                        "repair_applied": analysis_call.get("repair_applied", False),
                        "regenerate_applied": analysis_call.get(
                            "regenerate_applied", False
                        ),
                        "fallback_applied": analysis_fallback_applied,
                        "fallback_reason": analysis_fallback_reason,
                        "requirement_ir_refs": [
                            item.get("rid") or []
                            for item in (analysis_payload.get("it") or [])
                            if isinstance(item, dict)
                        ],
                        "structured_requirement": structured_requirement,
                        "contract_versions": contract_versions,
                    },
                    trace={
                        "override": bool(override_trace.get("override")),
                        "quality_level": requirement_validation.get("quality_level"),
                    },
                    increment_version=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="coverage",
                    payload={
                        "coverage": coverage_payload,
                        "coverage_plan": coverage_plan,
                        "usage": coverage_usage,
                        "cost": coverage_cost,
                        "cost_note": coverage_cost_note,
                        "response_id": coverage_response_id,
                        "repair_applied": coverage_repair_applied,
                        "regenerate_applied": coverage_regenerate_applied,
                        "backfill_rounds": backfill_rounds,
                        "backfill_batch_count": backfill_batch_count,
                        "deterministic_backfill_applied": deterministic_backfill_applied,
                        "deterministic_backfill_seed_count": deterministic_backfill_seed_count,
                        "coverage_force_complete": False,
                        "coverage_fallback_applied": coverage_fallback_applied,
                        "coverage_fallback_reason": coverage_fallback_reason,
                        "analysis_coverage_retry_attempted": analysis_coverage_retry_attempted,
                        "analysis_coverage_retry_succeeded": analysis_coverage_retry_succeeded,
                        "merged_analysis_coverage": merged_analysis_coverage,
                        "merged_coverage_from_analysis": merged_coverage_from_analysis,
                        "completeness": completeness,
                        "contract_versions": contract_versions,
                    },
                    trace={
                        "requirement_validation": requirement_validation,
                        "override": bool(override_trace.get("override")),
                    },
                    increment_version=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="pretestcase",
                    markdown=stage1_markdown,
                    payload=stage1_payload,
                    quality={
                        "quality_level": requirement_validation.get("quality_level"),
                        "is_complete": requirement_validation.get("is_complete", False),
                    },
                    trace={
                        "requirement_warning_override": bool(override_trace.get("override")),
                        "missing_sections": requirement_validation.get("missing_sections", []),
                        "missing_fields": requirement_validation.get("missing_fields", []),
                    },
                    increment_version=True,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.PRETESTCASE,
                    phase_status=HelperPhaseStatus.WAITING_CONFIRM,
                    status=HelperSessionStatus.ACTIVE,
                    last_error=None,
                    enforce_transition=True,
                )
                sync_db.commit()
                _, drafts = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                return self._to_session_response(session, drafts)

            updated_session = await run_sync(self.db, _persist_success)
            return HelperStageResultResponse(
                session=updated_session,
                stage="analysis_coverage",
                payload={
                    "structured_requirement": structured_requirement,
                    "requirement_validation": requirement_validation,
                    "override_trace": override_trace,
                    "contract_versions": contract_versions,
                    "requirement_ir": requirement_ir_payload,
                    "source_packets": requirement_ir_result.get("source_packets") or {},
                    "analysis": analysis_payload,
                    "analysis_fallback_applied": analysis_fallback_applied,
                    "analysis_fallback_reason": analysis_fallback_reason,
                    "coverage": coverage_payload,
                    "coverage_plan": coverage_plan,
                    "merged_analysis_coverage": merged_analysis_coverage,
                    "merged_coverage_from_analysis": merged_coverage_from_analysis,
                    "pretestcase": stage1_payload,
                    "cost": total_cost,
                    "cost_note": total_cost_note,
                },
                markdown=stage1_markdown,
                usage=total_usage,
            )
        except Exception as exc:
            error_message = str(exc)

            def _persist_failed(sync_db: Session) -> None:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.ANALYSIS,
                    phase_status=HelperPhaseStatus.FAILED,
                    status=HelperSessionStatus.FAILED,
                    last_error=error_message,
                    enforce_transition=False,
                )
                sync_db.commit()

            await run_sync(self.db, _persist_failed)
            raise

    # ---------- Stage 2: testcase and audit ----------
    @staticmethod
    def _ensure_string_list(raw_value: Any) -> List[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            return [stripped] if stripped else []
        return []

    def _enforce_testcase_ids(
        self,
        *,
        testcases: List[Dict[str, Any]],
        entries: List[Dict[str, Any]],
        ticket_key: str,
    ) -> List[Dict[str, Any]]:
        aligned: List[Dict[str, Any]] = []
        source_cases = [item for item in testcases if isinstance(item, dict)]
        used_indexes: Set[int] = set()

        def _pick_case(entry: Dict[str, Any], expected_id: str, fallback_index: int) -> Dict[str, Any]:
            # 1) 優先用完整 id 對齊，避免模型改動排序造成條目錯配。
            for idx, candidate in enumerate(source_cases):
                if idx in used_indexes:
                    continue
                candidate_id = str(candidate.get("id") or "").strip()
                if candidate_id and candidate_id == expected_id:
                    used_indexes.add(idx)
                    return candidate

            cid = str(entry.get("cid") or "").strip()
            if cid:
                cid_suffix = f".{cid}"
                for idx, candidate in enumerate(source_cases):
                    if idx in used_indexes:
                        continue
                    candidate_id = str(candidate.get("id") or "").strip()
                    if candidate_id.endswith(cid_suffix):
                        used_indexes.add(idx)
                        return candidate

            # 2) 再用標題對齊（在 id 缺失時仍可維持前後連貫）。
            entry_title = str(entry.get("t") or "").strip()
            if entry_title:
                for idx, candidate in enumerate(source_cases):
                    if idx in used_indexes:
                        continue
                    candidate_title = str(candidate.get("t") or "").strip()
                    if candidate_title and candidate_title == entry_title:
                        used_indexes.add(idx)
                        return candidate

            # 3) 最後才依原順序遞補。
            if fallback_index < len(source_cases) and fallback_index not in used_indexes:
                used_indexes.add(fallback_index)
                return source_cases[fallback_index]

            for idx, candidate in enumerate(source_cases):
                if idx in used_indexes:
                    continue
                used_indexes.add(idx)
                return candidate
            return {}

        for index, entry in enumerate(entries):
            expected_id = f"{ticket_key}.{entry.get('cid', '')}".strip(".")
            testcase = _pick_case(entry, expected_id, index)
            group_name = str(entry.get("g") or "Unassigned").strip() or "Unassigned"
            section_no = str(entry.get("sn") or "").strip()
            section_path = f"{section_no} {group_name}".strip() if section_no else group_name
            testcase["id"] = expected_id
            testcase["t"] = str(testcase.get("t") or entry.get("t") or "").strip()
            testcase["pre"] = self._ensure_string_list(testcase.get("pre"))
            testcase["s"] = self._ensure_string_list(testcase.get("s"))
            testcase["exp"] = self._ensure_string_list(testcase.get("exp"))
            testcase["priority"] = str(testcase.get("priority") or "Medium").strip()
            testcase["section_path"] = section_path
            aligned.append(testcase)
        return aligned

    def _compiled_forbidden_patterns(self) -> List[re.Pattern[str]]:
        configured = getattr(self.settings.ai.jira_testcase_helper, "forbidden_patterns", None)
        raw_patterns = configured if isinstance(configured, list) and configured else list(DEFAULT_FORBIDDEN_PATTERNS)
        compiled: List[re.Pattern[str]] = []
        for pattern in raw_patterns:
            text = str(pattern or "").strip()
            if not text:
                continue
            try:
                compiled.append(re.compile(text, re.IGNORECASE))
            except re.error:
                logger.warning("忽略非法 forbidden pattern: %s", text)
        return compiled

    def _contains_forbidden_content(self, values: Sequence[str]) -> bool:
        patterns = self._compiled_forbidden_patterns()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    return True
        return False

    def _sanitize_testcase_phrase(self, value: Any, *, fallback: str) -> str:
        text = str(value or "").strip()
        if not text:
            return str(fallback or "").strip()
        sanitized = re.sub(r"(?i)\bTBD\b", "待確認", text)
        sanitized = re.sub(r"(?i)\bN/?A\b", "不適用", sanitized)
        sanitized = re.sub(r"(?i)\bREF[-_\s]?\d+\b", "需求條目", sanitized)
        sanitized = sanitized.replace("同上", "請依本條目條件")
        sanitized = sanitized.replace("略", "請完整描述")
        sanitized = sanitized.strip()
        if not sanitized:
            return str(fallback or "").strip()
        if self._contains_forbidden_content([sanitized]):
            return str(fallback or "").strip()
        return sanitized

    def _sanitize_testcase_phrases(
        self,
        values: Sequence[Any],
        *,
        fallback: str,
    ) -> List[str]:
        sanitized: List[str] = []
        for value in values:
            normalized = self._sanitize_testcase_phrase(value, fallback=fallback)
            if normalized:
                sanitized.append(normalized)
        return self._unique_preserve(sanitized)

    def _has_observable_expected(self, values: Sequence[str]) -> bool:
        for value in values:
            lowered = str(value or "").strip().lower()
            if not lowered:
                continue
            if any(keyword in lowered for keyword in OBSERVABLE_KEYWORDS):
                return True
        return False

    def _resolve_min_steps_required(self, testcase: Dict[str, Any]) -> int:
        helper_cfg = self.settings.ai.jira_testcase_helper
        testcase_type = str(testcase.get("type") or "").strip().lower()
        title = str(testcase.get("t") or "").strip().lower()
        if testcase_type == "api" or any(keyword in title for keyword in ["api", "http", "endpoint", "response"]):
            return max(1, int(getattr(helper_cfg, "api_min_steps", 2) or 2))
        return max(1, int(getattr(helper_cfg, "min_steps", 3) or 3))

    def _collect_testcase_quality_issues(
        self,
        *,
        testcase: Dict[str, Any],
        strict: bool,
    ) -> List[str]:
        issues: List[str] = []
        pre = self._ensure_string_list(testcase.get("pre"))
        steps = self._ensure_string_list(testcase.get("s"))
        exp = self._ensure_string_list(testcase.get("exp"))

        if not strict:
            if not steps:
                issues.append("缺少 steps")
            if not exp:
                issues.append("缺少 expected result")
            elif len(exp) != 1:
                issues.append("expected result 必須且只能有 1 筆")
            return issues

        helper_cfg = self.settings.ai.jira_testcase_helper
        min_preconditions = max(0, int(getattr(helper_cfg, "min_preconditions", 1) or 1))
        min_steps = self._resolve_min_steps_required(testcase)

        if len(pre) < min_preconditions:
            issues.append(f"precondition 數量不足（至少 {min_preconditions}）")
        if len(steps) < min_steps:
            issues.append(f"steps 數量不足（至少 {min_steps}）")
        if not exp:
            issues.append("缺少 expected result")
        elif len(exp) != 1:
            issues.append("expected result 必須且只能有 1 筆")
        if self._contains_forbidden_content(pre + steps + exp):
            issues.append("包含禁止詞（例如 REF/同上/TBD）")
        if exp and not self._has_observable_expected(exp):
            issues.append("expected result 缺少可觀測線索")
        return issues

    def _repair_testcase_from_entry(
        self,
        *,
        testcase: Dict[str, Any],
        entry: Dict[str, Any],
        ticket_key: str,
    ) -> Dict[str, Any]:
        deterministic = self._build_deterministic_testcase_from_entry(
            ticket_key=ticket_key,
            entry=entry,
        )
        repaired = dict(testcase) if isinstance(testcase, dict) else {}
        repaired["id"] = deterministic["id"]
        repaired["t"] = str(repaired.get("t") or deterministic["t"]).strip() or deterministic["t"]
        repaired["pre"] = self._ensure_string_list(repaired.get("pre")) or deterministic["pre"]
        repaired["s"] = self._ensure_string_list(repaired.get("s")) or deterministic["s"]
        repaired["exp"] = self._ensure_string_list(repaired.get("exp")) or deterministic["exp"]
        min_preconditions = max(
            0,
            int(getattr(self.settings.ai.jira_testcase_helper, "min_preconditions", 1) or 1),
        )
        min_steps = self._resolve_min_steps_required(repaired)
        if len(repaired["pre"]) < min_preconditions:
            repaired["pre"] = deterministic["pre"]
        if len(repaired["s"]) < min_steps:
            repaired["s"] = deterministic["s"]
            while len(repaired["s"]) < min_steps:
                repaired["s"].append("比對實際結果與需求條目描述")
        if len(repaired["exp"]) != 1:
            repaired["exp"] = deterministic["exp"]
        if self._contains_forbidden_content(repaired["pre"] + repaired["s"] + repaired["exp"]):
            repaired["pre"] = deterministic["pre"]
            repaired["s"] = deterministic["s"]
            repaired["exp"] = deterministic["exp"]
        if not self._has_observable_expected(repaired["exp"]):
            repaired["exp"] = [f"UI 欄位/回應可觀測結果：{repaired['exp'][0]}"]
        repaired["priority"] = str(repaired.get("priority") or deterministic.get("priority") or "Medium").strip() or "Medium"
        return repaired

    def _enforce_section_case_quality(
        self,
        *,
        ticket_key: str,
        section_entries: List[Dict[str, Any]],
        section_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        max_rounds = max(1, int(getattr(self.settings.ai.jira_testcase_helper, "max_repair_rounds", 3) or 3))
        aligned_cases = [
            dict(case) if isinstance(case, dict) else {}
            for case in section_cases
        ]
        for _ in range(max_rounds):
            changed = False
            for index, entry in enumerate(section_entries):
                expected_id = f"{ticket_key}.{str(entry.get('cid') or '').strip()}".strip(".")
                case = aligned_cases[index] if index < len(aligned_cases) else {}
                if index >= len(aligned_cases):
                    aligned_cases.append(case)
                case["id"] = expected_id
                issues = self._collect_testcase_quality_issues(testcase=case, strict=True)
                if not issues:
                    continue
                aligned_cases[index] = self._repair_testcase_from_entry(
                    testcase=case,
                    entry=entry,
                    ticket_key=ticket_key,
                )
                changed = True
            if not changed:
                break
        return aligned_cases

    def _validate_generated_testcases(
        self,
        *,
        testcases: List[Dict[str, Any]],
        strict: bool = False,
    ) -> List[Dict[str, Any]]:
        validated: List[Dict[str, Any]] = []
        for index, testcase in enumerate(testcases, start=1):
            if not isinstance(testcase, dict):
                raise ValueError(f"第 {index} 筆 testcase 格式錯誤")
            case_id = str(testcase.get("id") or "").strip()
            title = str(testcase.get("t") or "").strip()
            if not case_id:
                raise ValueError(f"第 {index} 筆 testcase 缺少 id")
            if not title:
                raise ValueError(f"第 {index} 筆 testcase 缺少標題")
            issues = self._collect_testcase_quality_issues(testcase=testcase, strict=strict)
            if issues:
                raise ValueError(f"第 {index} 筆 testcase 不符合規格: {'; '.join(issues)}")
            pre = self._ensure_string_list(testcase.get("pre"))
            steps = self._ensure_string_list(testcase.get("s"))
            exp = self._ensure_string_list(testcase.get("exp"))
            validated.append(
                {
                    "id": case_id,
                    "t": title,
                    "pre": pre,
                    "s": steps,
                    "exp": exp,
                    "priority": str(testcase.get("priority") or "Medium").strip() or "Medium",
                    "section_path": self._normalize_section_path_with_middle(
                        section_path=str(testcase.get("section_path") or "Unassigned").strip()
                        or "Unassigned",
                        case_id=case_id,
                    ),
                    "section_id": testcase.get("section_id"),
                }
            )
        return validated

    @staticmethod
    def _testcase_markdown(testcases: List[Dict[str, Any]]) -> str:
        lines: List[str] = ["## Generated Test Cases"]
        if not testcases:
            lines.append("（無資料）")
            return "\n".join(lines)
        for testcase in testcases:
            lines.append(f"\n### {testcase.get('id', '')} {testcase.get('t', '')}".strip())
            lines.append(f"- section: {testcase.get('section_path', 'Unassigned')}")
            lines.append("- precondition:")
            if testcase.get("pre"):
                for item in testcase["pre"]:
                    lines.append(f"  - {item}")
            else:
                lines.append("  - N/A")
            lines.append("- steps:")
            for idx, step in enumerate(testcase.get("s", []), start=1):
                lines.append(f"  {idx}. {step}")
            lines.append("- expected:")
            for item in testcase.get("exp", []):
                lines.append(f"  - {item}")
        return "\n".join(lines)

    @staticmethod
    def _group_stage1_sections(stage1_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        grouped_sections: List[Dict[str, Any]] = []
        sections_raw = stage1_payload.get("sec") or []
        if isinstance(sections_raw, list) and sections_raw:
            for section in sections_raw:
                if not isinstance(section, dict):
                    continue
                group = str(section.get("g") or "").strip() or "未分類"
                section_no = str(section.get("sn") or "").strip()
                entries = [
                    dict(item) for item in (section.get("en") or []) if isinstance(item, dict)
                ]
                if not entries:
                    continue
                grouped_sections.append({"g": group, "sn": section_no, "en": entries})
            if grouped_sections:
                return grouped_sections

        fallback_entries = [
            dict(item)
            for item in (stage1_payload.get("en") or [])
            if isinstance(item, dict)
        ]
        section_map: Dict[str, Dict[str, Any]] = {}
        for entry in fallback_entries:
            group = str(entry.get("g") or "").strip() or "未分類"
            section_no = str(entry.get("sn") or "").strip()
            if group not in section_map:
                section_map[group] = {"g": group, "sn": section_no, "en": []}
            if not section_map[group].get("sn") and section_no:
                section_map[group]["sn"] = section_no
            section_map[group]["en"].append(entry)
        return list(section_map.values())

    @staticmethod
    def _build_single_section_stage1_payload(
        stage1_payload: Dict[str, Any],
        section: Dict[str, Any],
    ) -> Dict[str, Any]:
        section_group = str(section.get("g") or "").strip() or "未分類"
        section_no = str(section.get("sn") or "").strip()
        section_entries = [
            dict(item) for item in (section.get("en") or []) if isinstance(item, dict)
        ]
        payload: Dict[str, Any] = {
            "sec": [
                {
                    "g": section_group,
                    "sn": section_no,
                    "en": section_entries,
                }
            ],
            "en": section_entries,
        }
        coverage_plan = stage1_payload.get("coverage_plan")
        if isinstance(coverage_plan, dict):
            section_plan = None
            for item in coverage_plan.get("sections") or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                if title and title == section_group:
                    section_plan = item
                    break
            if section_plan is not None:
                payload["coverage_plan"] = {
                    "coverage_version": coverage_plan.get("coverage_version"),
                    "ticket_id": coverage_plan.get("ticket_id"),
                    "sections": [section_plan],
                }
        for key in ("lang", "user_notes"):
            if key in stage1_payload:
                payload[key] = stage1_payload.get(key)
        return payload

    @staticmethod
    def _is_generated_testcase_complete(testcase: Dict[str, Any]) -> bool:
        if not isinstance(testcase, dict):
            return False
        title = str(testcase.get("t") or "").strip()
        if not title:
            return False
        steps = [
            str(step).strip()
            for step in (testcase.get("s") or [])
            if str(step).strip()
        ]
        if not steps:
            return False
        exp = [
            str(item).strip()
            for item in (testcase.get("exp") or [])
            if str(item).strip()
        ]
        return len(exp) == 1

    @staticmethod
    def _collect_incomplete_section_entries(
        section_entries: List[Dict[str, Any]],
        section_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        incomplete_entries: List[Dict[str, Any]] = []
        for index, entry in enumerate(section_entries):
            candidate = section_cases[index] if index < len(section_cases) else {}
            if not JiraTestCaseHelperService._is_generated_testcase_complete(candidate):
                incomplete_entries.append(entry)
        return incomplete_entries

    @staticmethod
    def _merge_supplement_cases(
        *,
        base_cases: List[Dict[str, Any]],
        supplement_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        supplement_map = {
            str(item.get("id") or "").strip(): item
            for item in supplement_cases
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        merged: List[Dict[str, Any]] = []
        for item in base_cases:
            item_id = str(item.get("id") or "").strip()
            supplement = supplement_map.get(item_id)
            if supplement and JiraTestCaseHelperService._is_generated_testcase_complete(supplement):
                merged.append(supplement)
            else:
                merged.append(item)
        return merged

    def _build_deterministic_testcase_from_entry(
        self,
        *,
        ticket_key: str,
        entry: Dict[str, Any],
    ) -> Dict[str, Any]:
        cid = str(entry.get("cid") or "").strip() or "000.000"
        case_id = f"{ticket_key}.{cid}".strip(".")
        title = str(entry.get("t") or "").strip() or "需求檢核"
        state = str(entry.get("st") or "ok").strip().lower()
        if state == "assume" and not title.startswith("[ASSUME]"):
            title = f"[ASSUME] {title}"
        elif state == "ask" and not title.startswith("[TBD]"):
            title = f"[TBD] {title}"

        checks = self._sanitize_testcase_phrases(
            [item for item in (entry.get("chk") or []) if str(item).strip()],
            fallback="檢查條目行為是否符合需求",
        )
        expected_hints = self._sanitize_testcase_phrases(
            [item for item in (entry.get("exp") or []) if str(item).strip()],
            fallback="系統回應與畫面呈現符合需求且結果可觀測",
        )
        pre_hints = self._sanitize_testcase_phrases(
            [item for item in (entry.get("pre_hint") or []) if str(item).strip()],
            fallback="已建立符合需求的測試資料與角色權限",
        )
        step_hints = self._sanitize_testcase_phrases(
            [item for item in (entry.get("step_hint") or []) if str(item).strip()],
            fallback="執行對應操作並檢查結果",
        )

        preconditions = pre_hints or [
            "已建立符合需求的測試資料（含正向與邊界資料）",
            "測試帳號與權限設定符合該條目驗證條件",
        ]
        steps = step_hints or []
        if not steps:
            steps = [
                "進入對應功能頁面並定位目標資料區塊",
                "依條目要求執行操作並記錄畫面與資料變化",
            ]
        for check in checks:
            steps.append(f"驗證：{check}")
        if len(steps) < 3:
            steps.append("比對實際結果與需求條目描述")
        steps = self._sanitize_testcase_phrases(
            steps,
            fallback="執行對應操作並檢查結果",
        )
        if len(steps) < 3:
            steps.extend(
                [
                    "執行對應操作並檢查結果",
                    "比對實際結果與需求條目描述",
                ]
            )
            steps = self._sanitize_testcase_phrases(
                steps,
                fallback="執行對應操作並檢查結果",
            )

        expected_result = (
            "；".join(expected_hints)
            if expected_hints
            else f"{str(entry.get('t') or '需求條目').strip()}符合需求描述"
        )
        if state == "assume":
            expected_result = f"{expected_result}（ASSUME：{str(entry.get('a') or '待確認假設').strip()}）"
        if state == "ask":
            expected_result = f"{expected_result}（待確認：{str(entry.get('q') or '待釐清問題').strip()}）"
        expected_result = self._sanitize_testcase_phrase(
            expected_result,
            fallback="系統回應與畫面呈現符合需求且結果可觀測",
        )

        return {
            "id": case_id,
            "t": title,
            "pre": preconditions,
            "s": steps,
            "exp": [expected_result],
            "priority": "Medium",
        }

    async def generate_testcases(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperGenerateRequest,
    ) -> HelperStageResultResponse:
        session_data = await self.get_session(team_id=team_id, session_id=session_id)
        ticket_key = session_data.ticket_key or ""
        if not ticket_key:
            raise ValueError("請先完成 ticket 讀取")

        pretestcase_draft = next(
            (item for item in session_data.drafts if item.phase == "pretestcase"),
            None,
        )
        if request.pretestcase_payload is not None:
            raw_stage1_payload = request.pretestcase_payload
        elif pretestcase_draft and pretestcase_draft.payload:
            raw_stage1_payload = pretestcase_draft.payload
        else:
            raw_stage1_payload = {}
        stage1_payload = self._normalize_stage1_payload_for_generation(
            stage1_payload=raw_stage1_payload,
            initial_middle=session_data.initial_middle,
        )

        entries = stage1_payload.get("en", []) if isinstance(stage1_payload, dict) else []
        if not isinstance(entries, list) or not entries:
            raise ValueError("pre-testcase 條目為空，無法產生 test case")

        ticket_draft = next(
            (item for item in session_data.drafts if item.phase == "jira_ticket"),
            None,
        )
        ticket_payload = ticket_draft.payload if ticket_draft and ticket_draft.payload else {}
        
        requirement_draft = next(
            (item for item in session_data.drafts if item.phase == "requirement"),
            None,
        )
        ticket_description = (
            requirement_draft.markdown
            if requirement_draft and requirement_draft.markdown
            else str(ticket_payload.get("description") or "")
        )

        helper_cfg = self.settings.ai.jira_testcase_helper
        testcase_force_complete = bool(
            getattr(helper_cfg, "testcase_force_complete", True)
        )
        output_language = _locale_label(session_data.output_locale.value)
        stage1_sections = self._group_stage1_sections(stage1_payload)
        if not stage1_sections:
            raise ValueError("pre-testcase 條目缺少 section 資訊，無法產生 test case")

        ticket_summary = str(ticket_payload.get("summary") or "")
        ticket_components = ", ".join(ticket_payload.get("components") or []) or "N/A"

        def _mark_running(sync_db: Session) -> None:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            self._set_session_phase(
                session,
                phase=HelperPhase.TESTCASE,
                phase_status=HelperPhaseStatus.RUNNING,
                status=HelperSessionStatus.ACTIVE,
                enforce_transition=False,
            )
            sync_db.commit()

        await run_sync(self.db, _mark_running)

        try:
            testcase_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            audit_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            testcase_cost = 0.0
            audit_cost = 0.0
            testcase_cost_note = ""
            audit_cost_note = ""
            testcase_response_id: Optional[str] = None
            audit_response_id: Optional[str] = None
            testcase_regenerate_applied = False
            testcase_repair_applied = False
            audit_regenerate_applied = False
            audit_repair_applied = False

            generated_testcases_all: List[Dict[str, Any]] = []
            audited_testcases_all: List[Dict[str, Any]] = []
            testcase_fallback_sections: List[Dict[str, str]] = []
            audit_fallback_sections: List[Dict[str, str]] = []

            def _merge_usage(base: Dict[str, int], delta: Dict[str, Any]) -> Dict[str, int]:
                return {
                    "prompt_tokens": int(base.get("prompt_tokens", 0))
                    + int((delta or {}).get("prompt_tokens", 0)),
                    "completion_tokens": int(base.get("completion_tokens", 0))
                    + int((delta or {}).get("completion_tokens", 0)),
                    "total_tokens": int(base.get("total_tokens", 0))
                    + int((delta or {}).get("total_tokens", 0)),
                }

            for section in stage1_sections:
                section_name = str(section.get("g") or "未分類").strip() or "未分類"
                section_no = str(section.get("sn") or "").strip()
                section_entries = [
                    dict(item) for item in (section.get("en") or []) if isinstance(item, dict)
                ]
                if not section_entries:
                    continue
                section_generated = [
                    self._build_deterministic_testcase_from_entry(
                        ticket_key=ticket_key,
                        entry=entry,
                    )
                    for entry in section_entries
                ]

                section_payload = self._build_single_section_stage1_payload(
                    stage1_payload=stage1_payload,
                    section=section,
                )
                section_stage1_json = json.dumps(
                    section_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                section_context_result = await self._query_generation_similar_cases(
                    ticket_key=ticket_key,
                    ticket_summary=ticket_summary,
                    ticket_description=ticket_description,
                    section_name=section_name,
                    section_entries=section_entries,
                )
                section_context = str(section_context_result.get("text") or "")
                section_retrieved_refs = (
                    section_context_result.get("retrieved_refs")
                    if isinstance(section_context_result.get("retrieved_refs"), list)
                    else []
                )

                try:
                    testcase_prompt = self.prompt_service.render_machine_stage_prompt(
                        "testcase",
                        {
                            "output_language": output_language,
                            "ticket_key": ticket_key,
                            "ticket_summary": ticket_summary,
                            "ticket_description": ticket_description,
                            "ticket_components": ticket_components,
                            "coverage_questions_json": section_stage1_json,
                            "similar_cases": section_context,
                            "section_name": section_name,
                            "section_no": section_no,
                            "retry_hint": (
                                "上一輪可能輸出不完整，請重新輸出本 section 全量 testcase JSON。"
                                if request.retry
                                else ""
                            ),
                        },
                    )
                    testcase_call = await self._call_json_stage_with_retry(
                        stage="testcase",
                        prompt=testcase_prompt,
                        review_language=output_language,
                        stage_name=f"Testcase ({section_name})",
                        schema_example='{"tc":[{"id":"TCG-123.010.010","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                    )
                    testcase_usage = _merge_usage(testcase_usage, testcase_call.get("usage") or {})
                    testcase_cost += float(testcase_call.get("cost") or 0.0)
                    testcase_response_id = testcase_call.get("response_id") or testcase_response_id
                    testcase_regenerate_applied = testcase_regenerate_applied or bool(
                        testcase_call.get("regenerate_applied")
                    )
                    testcase_repair_applied = testcase_repair_applied or bool(
                        testcase_call.get("repair_applied")
                    )
                    if testcase_cost_note or testcase_call.get("cost_note"):
                        testcase_cost_note = "（含未知費用）"

                    testcase_payload = testcase_call.get("payload_raw") or {}
                    raw_section_testcases = testcase_payload.get("tc", [])
                    if not isinstance(raw_section_testcases, list):
                        raise ValueError(f"Section {section_name} Testcase 回傳 JSON 結構錯誤")
                    generated_aligned = self._enforce_testcase_ids(
                        testcases=raw_section_testcases,
                        entries=section_entries,
                        ticket_key=ticket_key,
                    )
                    section_generated = self._merge_supplement_cases(
                        base_cases=section_generated,
                        supplement_cases=generated_aligned,
                    )

                    incomplete_entries = self._collect_incomplete_section_entries(
                        section_entries,
                        section_generated,
                    )
                    if incomplete_entries:
                        supplement_payload = self._build_single_section_stage1_payload(
                            stage1_payload=stage1_payload,
                            section={
                                "g": section_name,
                                "sn": section_no,
                                "en": incomplete_entries,
                            },
                        )
                        supplement_prompt = self.prompt_service.render_machine_stage_prompt(
                            "testcase_supplement",
                            {
                                "output_language": output_language,
                                "ticket_key": ticket_key,
                                "coverage_questions_json": json.dumps(
                                    supplement_payload,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                                "testcase_json": json.dumps(
                                    {"tc": section_generated},
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                                "similar_cases": section_context,
                                "section_name": section_name,
                                "section_no": section_no,
                                "retry_hint": "請補齊缺漏 testcase，並輸出完整 JSON。",
                            },
                        )
                        supplement_call = await self._call_json_stage_with_retry(
                            stage="testcase",
                            prompt=supplement_prompt,
                            review_language=output_language,
                            stage_name=f"Testcase supplement ({section_name})",
                            schema_example='{"tc":[{"id":"TCG-123.010.020","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                        )
                        testcase_usage = _merge_usage(
                            testcase_usage,
                            supplement_call.get("usage") or {},
                        )
                        testcase_cost += float(supplement_call.get("cost") or 0.0)
                        testcase_response_id = (
                            supplement_call.get("response_id") or testcase_response_id
                        )
                        testcase_regenerate_applied = testcase_regenerate_applied or bool(
                            supplement_call.get("regenerate_applied")
                        )
                        testcase_repair_applied = testcase_repair_applied or bool(
                            supplement_call.get("repair_applied")
                        )
                        if testcase_cost_note or supplement_call.get("cost_note"):
                            testcase_cost_note = "（含未知費用）"
                        supplement_raw = (
                            (supplement_call.get("payload_raw") or {}).get("tc") or []
                        )
                        supplement_aligned = self._enforce_testcase_ids(
                            testcases=supplement_raw if isinstance(supplement_raw, list) else [],
                            entries=incomplete_entries,
                            ticket_key=ticket_key,
                        )
                        section_generated = self._merge_supplement_cases(
                            base_cases=section_generated,
                            supplement_cases=supplement_aligned,
                        )
                except Exception as testcase_exc:
                    if not testcase_force_complete:
                        raise
                    testcase_fallback_sections.append(
                        {
                            "section": section_name,
                            "reason": str(testcase_exc),
                        }
                    )
                    logger.warning(
                        "Section %s Testcase 生成失敗，改採 deterministic fallback: %s",
                        section_name,
                        testcase_exc,
                    )

                section_generated = self._enforce_section_case_quality(
                    ticket_key=ticket_key,
                    section_entries=section_entries,
                    section_cases=section_generated,
                )
                try:
                    section_generated = self._validate_generated_testcases(
                        testcases=section_generated,
                        strict=True,
                    )
                except Exception as section_validation_exc:
                    if not testcase_force_complete:
                        raise
                    testcase_fallback_sections.append(
                        {
                            "section": section_name,
                            "reason": f"validation: {section_validation_exc}",
                        }
                    )
                    logger.warning(
                        "Section %s Testcase 校驗失敗，改採 deterministic fallback: %s",
                        section_name,
                        section_validation_exc,
                    )
                    section_generated = [
                        self._build_deterministic_testcase_from_entry(
                            ticket_key=ticket_key,
                            entry=entry,
                        )
                        for entry in section_entries
                    ]
                    section_generated = self._enforce_section_case_quality(
                        ticket_key=ticket_key,
                        section_entries=section_entries,
                        section_cases=section_generated,
                    )
                    try:
                        section_generated = self._validate_generated_testcases(
                            testcases=section_generated,
                            strict=True,
                        )
                    except Exception as fallback_validation_exc:
                        logger.warning(
                            "Section %s Testcase deterministic fallback 仍未通過嚴格校驗，降級基本校驗: %s",
                            section_name,
                            fallback_validation_exc,
                        )
                        section_generated = self._validate_generated_testcases(
                            testcases=section_generated,
                            strict=False,
                        )
                generated_testcases_all.extend(section_generated)

                section_audited = [
                    dict(item) for item in section_generated if isinstance(item, dict)
                ]
                try:
                    audit_prompt = self.prompt_service.render_machine_stage_prompt(
                        "audit",
                        {
                            "output_language": output_language,
                            "ticket_key": ticket_key,
                            "coverage_questions_json": section_stage1_json,
                            "testcase_json": json.dumps(
                                {"tc": section_generated},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            "similar_cases": section_context,
                            "section_name": section_name,
                            "section_no": section_no,
                            "retry_hint": (
                                "請補強細節並確保所有 testcase 完整輸出。"
                                if request.retry
                                else ""
                            ),
                        },
                    )
                    audit_call = await self._call_json_stage_with_retry(
                        stage="audit",
                        prompt=audit_prompt,
                        review_language=output_language,
                        stage_name=f"Audit ({section_name})",
                        schema_example='{"tc":[{"id":"TCG-123.010.010","t":"...","pre":["..."],"s":["..."],"exp":["..."]}]}',
                    )
                    audit_usage = _merge_usage(audit_usage, audit_call.get("usage") or {})
                    audit_cost += float(audit_call.get("cost") or 0.0)
                    audit_response_id = audit_call.get("response_id") or audit_response_id
                    audit_regenerate_applied = audit_regenerate_applied or bool(
                        audit_call.get("regenerate_applied")
                    )
                    audit_repair_applied = audit_repair_applied or bool(
                        audit_call.get("repair_applied")
                    )
                    if audit_cost_note or audit_call.get("cost_note"):
                        audit_cost_note = "（含未知費用）"

                    audit_payload = audit_call.get("payload_raw") or {}
                    audited_raw = audit_payload.get("tc", [])
                    if not isinstance(audited_raw, list):
                        raise ValueError(f"Section {section_name} Audit 回傳 JSON 結構錯誤")
                    audited_aligned = self._enforce_testcase_ids(
                        testcases=audited_raw,
                        entries=section_entries,
                        ticket_key=ticket_key,
                    )
                    section_audited = self._merge_supplement_cases(
                        base_cases=section_audited,
                        supplement_cases=audited_aligned,
                    )
                except Exception as audit_exc:
                    if not testcase_force_complete:
                        raise
                    audit_fallback_sections.append(
                        {
                            "section": section_name,
                            "reason": str(audit_exc),
                        }
                    )
                    logger.warning(
                        "Section %s Audit 失敗，改採 deterministic fallback: %s",
                        section_name,
                        audit_exc,
                    )

                section_audited = self._enforce_section_case_quality(
                    ticket_key=ticket_key,
                    section_entries=section_entries,
                    section_cases=section_audited,
                )
                try:
                    section_audited = self._validate_generated_testcases(
                        testcases=section_audited,
                        strict=True,
                    )
                except Exception as audit_validation_exc:
                    if not testcase_force_complete:
                        raise
                    audit_fallback_sections.append(
                        {
                            "section": section_name,
                            "reason": f"validation: {audit_validation_exc}",
                        }
                    )
                    logger.warning(
                        "Section %s Audit 校驗失敗，改採 deterministic fallback: %s",
                        section_name,
                        audit_validation_exc,
                    )
                    section_audited = [
                        self._build_deterministic_testcase_from_entry(
                            ticket_key=ticket_key,
                            entry=entry,
                        )
                        for entry in section_entries
                    ]
                    section_audited = self._enforce_section_case_quality(
                        ticket_key=ticket_key,
                        section_entries=section_entries,
                        section_cases=section_audited,
                    )
                    try:
                        section_audited = self._validate_generated_testcases(
                            testcases=section_audited,
                            strict=True,
                        )
                    except Exception as fallback_validation_exc:
                        logger.warning(
                            "Section %s Audit deterministic fallback 仍未通過嚴格校驗，降級基本校驗: %s",
                            section_name,
                            fallback_validation_exc,
                        )
                        section_audited = self._validate_generated_testcases(
                            testcases=section_audited,
                            strict=False,
                        )
                for testcase in section_audited:
                    testcase["retrieved_refs"] = section_retrieved_refs
                audited_testcases_all.extend(section_audited)

            if not audited_testcases_all:
                raise ValueError("未產生可審核的 Test Cases")

            markdown = self._testcase_markdown(audited_testcases_all)

            combined_usage = {
                "prompt_tokens": testcase_usage.get("prompt_tokens", 0)
                + audit_usage.get("prompt_tokens", 0),
                "completion_tokens": testcase_usage.get("completion_tokens", 0)
                + audit_usage.get("completion_tokens", 0),
                "total_tokens": testcase_usage.get("total_tokens", 0)
                + audit_usage.get("total_tokens", 0),
            }
            combined_cost = testcase_cost + audit_cost
            combined_cost_note = (
                "（含未知費用）" if testcase_cost_note or audit_cost_note else ""
            )

            def _persist_success(sync_db: Session) -> HelperSessionResponse:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                if request.pretestcase_payload is not None:
                    self._upsert_draft_sync(
                        sync_db,
                        session_id=session.id,
                        phase="pretestcase",
                        markdown=pretestcase_draft.markdown if pretestcase_draft else None,
                        payload=stage1_payload,
                        increment_version=True,
                    )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="testcase",
                    payload={
                        "tc": generated_testcases_all,
                        "usage": testcase_usage,
                        "cost": testcase_cost,
                        "cost_note": testcase_cost_note,
                        "response_id": testcase_response_id,
                        "regenerate_applied": testcase_regenerate_applied,
                        "repair_applied": testcase_repair_applied,
                        "testcase_force_complete": testcase_force_complete,
                        "fallback_sections": testcase_fallback_sections,
                    },
                    increment_version=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="audit",
                    payload={
                        "tc": audited_testcases_all,
                        "usage": audit_usage,
                        "cost": audit_cost,
                        "cost_note": audit_cost_note,
                        "response_id": audit_response_id,
                        "regenerate_applied": audit_regenerate_applied,
                        "repair_applied": audit_repair_applied,
                        "testcase_force_complete": testcase_force_complete,
                        "fallback_sections": audit_fallback_sections,
                    },
                    increment_version=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="final_testcases",
                    markdown=markdown,
                    payload={"tc": audited_testcases_all},
                    increment_version=True,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.TESTCASE,
                    phase_status=HelperPhaseStatus.WAITING_CONFIRM,
                    status=HelperSessionStatus.ACTIVE,
                    last_error=None,
                    enforce_transition=True,
                )
                sync_db.commit()
                _, drafts = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                return self._to_session_response(session, drafts)

            updated_session = await run_sync(self.db, _persist_success)
            return HelperStageResultResponse(
                session=updated_session,
                stage="testcase_audit",
                payload={
                    "tc": audited_testcases_all,
                    "cost": combined_cost,
                    "cost_note": combined_cost_note,
                    "testcase_force_complete": testcase_force_complete,
                    "testcase_fallback_sections": testcase_fallback_sections,
                    "audit_fallback_sections": audit_fallback_sections,
                },
                markdown=markdown,
                usage=combined_usage,
            )
        except Exception as exc:
            error_message = str(exc)

            def _persist_failed(sync_db: Session) -> None:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.TESTCASE,
                    phase_status=HelperPhaseStatus.FAILED,
                    status=HelperSessionStatus.FAILED,
                    last_error=error_message,
                    enforce_transition=False,
                )
                sync_db.commit()

            await run_sync(self.db, _persist_failed)
            raise

    # ---------- Commit ----------
    @staticmethod
    def _priority_from_text(raw_priority: str) -> Priority:
        normalized = (raw_priority or "Medium").strip().lower()
        mapping = {
            "high": Priority.HIGH,
            "medium": Priority.MEDIUM,
            "low": Priority.LOW,
        }
        return mapping.get(normalized, Priority.MEDIUM)

    @staticmethod
    def _join_markdown_lines(lines: Sequence[str], numbered: bool = False) -> str:
        if not lines:
            return ""
        cleaned = [str(item).strip() for item in lines if str(item).strip()]
        if numbered:
            return "\n".join([f"{idx}. {text}" for idx, text in enumerate(cleaned, start=1)])
        return "\n".join(cleaned)

    def _ensure_unassigned_section_sync(
        self, sync_db: Session, *, set_id: int
    ) -> TestCaseSection:
        unassigned = (
            sync_db.query(TestCaseSection)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.name == "Unassigned",
                TestCaseSection.parent_section_id.is_(None),
            )
            .first()
        )
        if unassigned:
            return unassigned

        max_sort = (
            sync_db.query(TestCaseSection.sort_order)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.parent_section_id.is_(None),
            )
            .order_by(TestCaseSection.sort_order.desc())
            .first()
        )
        next_sort = (max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0
        unassigned = TestCaseSection(
            test_case_set_id=set_id,
            name="Unassigned",
            description="未分配的測試案例",
            parent_section_id=None,
            level=1,
            sort_order=next_sort,
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(unassigned)
        sync_db.flush()
        return unassigned

    def _ensure_section_path_sync(
        self,
        sync_db: Session,
        *,
        set_id: int,
        section_path: str,
        fallback_section_id: int,
    ) -> int:
        names = [item.strip() for item in section_path.split("/") if item.strip()]
        if not names:
            return fallback_section_id
        if len(names) > 5:
            return fallback_section_id

        parent_id: Optional[int] = None
        current_level = 1
        for name in names:
            existing = (
                sync_db.query(TestCaseSection)
                .filter(
                    TestCaseSection.test_case_set_id == set_id,
                    TestCaseSection.parent_section_id == parent_id,
                    TestCaseSection.name == name,
                )
                .first()
            )
            if existing:
                parent_id = existing.id
                current_level = existing.level + 1
                continue

            max_sort = (
                sync_db.query(TestCaseSection.sort_order)
                .filter(
                    TestCaseSection.test_case_set_id == set_id,
                    TestCaseSection.parent_section_id == parent_id,
                )
                .order_by(TestCaseSection.sort_order.desc())
                .first()
            )
            next_sort = (max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0
            new_section = TestCaseSection(
                test_case_set_id=set_id,
                name=name,
                description=None,
                parent_section_id=parent_id,
                level=min(current_level, 5),
                sort_order=next_sort,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(new_section)
            sync_db.flush()
            parent_id = new_section.id
            current_level += 1

        return parent_id or fallback_section_id

    async def commit_testcases(
        self,
        *,
        team_id: int,
        session_id: int,
        request: HelperCommitRequest,
    ) -> Dict[str, Any]:
        session_data = await self.get_session(team_id=team_id, session_id=session_id)
        if request.testcases is not None:
            final_testcases = [
                {
                    "id": item.id,
                    "t": item.t,
                    "pre": item.pre,
                    "s": item.s,
                    "exp": item.exp,
                    "priority": item.priority,
                    "section_path": item.section_path,
                    "section_id": item.section_id,
                }
                for item in request.testcases
            ]
        else:
            final_draft = next(
                (item for item in session_data.drafts if item.phase == "final_testcases"),
                None,
            )
            payload = final_draft.payload if final_draft and final_draft.payload else {}
            final_testcases = payload.get("tc", []) if isinstance(payload, dict) else []

        if not isinstance(final_testcases, list) or not final_testcases:
            raise ValueError("找不到可提交的 test case")
        validated = self._validate_generated_testcases(testcases=final_testcases)

        def _mark_running(sync_db: Session) -> None:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            self._set_session_phase(
                session,
                phase=HelperPhase.COMMIT,
                phase_status=HelperPhaseStatus.RUNNING,
                status=HelperSessionStatus.ACTIVE,
                enforce_transition=False,
            )
            sync_db.commit()

        await run_sync(self.db, _mark_running)

        def _commit(sync_db: Session) -> Dict[str, Any]:
            session, _ = self._get_session_and_drafts_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
            target_set = (
                sync_db.query(TestCaseSet)
                .filter(
                    TestCaseSet.id == session.target_test_case_set_id,
                    TestCaseSet.team_id == team_id,
                )
                .first()
            )
            if not target_set:
                raise ValueError(
                    f"目標 Test Case Set 不存在: {session.target_test_case_set_id}"
                )

            created_numbers: List[str] = []
            section_fallback_count = 0

            try:
                unassigned = self._ensure_unassigned_section_sync(
                    sync_db,
                    set_id=target_set.id,
                )
                for testcase in validated:
                    section_id = testcase.get("section_id")
                    section_path = str(testcase.get("section_path") or "").strip()
                    resolved_section_id = section_id
                    if resolved_section_id is None:
                        resolved_section_id = self._ensure_section_path_sync(
                            sync_db,
                            set_id=target_set.id,
                            section_path=section_path,
                            fallback_section_id=unassigned.id,
                        )
                        if resolved_section_id == unassigned.id and section_path:
                            section_fallback_count += 1

                    model = TestCaseLocal(
                        team_id=team_id,
                        test_case_set_id=target_set.id,
                        test_case_section_id=resolved_section_id,
                        test_case_number=testcase["id"],
                        title=testcase["t"],
                        priority=self._priority_from_text(testcase.get("priority", "Medium")),
                        precondition=self._join_markdown_lines(testcase.get("pre", [])),
                        steps=self._join_markdown_lines(
                            testcase.get("s", []), numbered=True
                        ),
                        expected_result=self._join_markdown_lines(testcase.get("exp", [])),
                        tcg_json=_safe_json_dumps(
                            [session.ticket_key] if session.ticket_key else []
                        ),
                        sync_status=SyncStatus.SYNCED,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    sync_db.add(model)
                    created_numbers.append(testcase["id"])

                sync_db.flush()
                self._set_session_phase(
                    session,
                    phase=HelperPhase.COMMIT,
                    phase_status=HelperPhaseStatus.COMPLETED,
                    status=HelperSessionStatus.COMPLETED,
                    last_error=None,
                    enforce_transition=True,
                )
                self._upsert_draft_sync(
                    sync_db,
                    session_id=session.id,
                    phase="final_testcases",
                    markdown=self._testcase_markdown(validated),
                    payload={"tc": validated},
                    increment_version=request.testcases is not None,
                )
                sync_db.commit()
            except IntegrityError as exc:
                sync_db.rollback()
                raise ValueError(f"提交失敗，可能有重複 Test Case 編號: {exc}") from exc
            except Exception:
                sync_db.rollback()
                raise

            return {
                "created_count": len(created_numbers),
                "created_test_case_numbers": created_numbers,
                "target_test_case_set_id": target_set.id,
                "section_fallback_count": section_fallback_count,
            }

        try:
            result = await run_sync(self.db, _commit)
            return result
        except Exception as exc:
            error_message = str(exc)

            def _persist_failed(sync_db: Session) -> None:
                session, _ = self._get_session_and_drafts_sync(
                    sync_db,
                    team_id=team_id,
                    session_id=session_id,
                )
                self._set_session_phase(
                    session,
                    phase=HelperPhase.COMMIT,
                    phase_status=HelperPhaseStatus.FAILED,
                    status=HelperSessionStatus.FAILED,
                    last_error=error_message,
                    enforce_transition=False,
                )
                sync_db.commit()

            await run_sync(self.db, _persist_failed)
            raise
