"""Service layer for the rewritten QA AI Helper."""

from __future__ import annotations

import json
import logging
import time
import base64
import re
import zlib
from copy import deepcopy
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db_access.main import MainAccessBoundary, get_main_access_boundary
from app.models.database_models import (
    QAAIHelperCanonicalRevision,
    QAAIHelperCheckCondition,
    QAAIHelperCommitLink,
    QAAIHelperDraft,
    QAAIHelperDraftSet,
    QAAIHelperPlanSection,
    QAAIHelperPlannedRevision,
    QAAIHelperRequirementDelta,
    QAAIHelperRequirementPlan,
    QAAIHelperSession,
    QAAIHelperSeedItem,
    QAAIHelperSeedSet,
    QAAIHelperTelemetryEvent,
    QAAIHelperTestcaseDraft,
    QAAIHelperTestcaseDraftSet,
    QAAIHelperTicketSnapshot,
    QAAIHelperValidationRun,
    QAAIHelperVerificationItem,
    Priority,
    SyncStatus,
    Team,
    TestCaseLocal,
    TestCaseSection,
    TestCaseSet,
)
from app.models.qa_ai_helper import (
    QAAIHelperApplicabilityStatus,
    QAAIHelperCanonicalRevisionCreateRequest,
    QAAIHelperCanonicalRevisionResponse,
    QAAIHelperCanonicalRevisionStatus,
    QAAIHelperCheckConditionResponse,
    QAAIHelperCoverageCategory,
    QAAIHelperCommitDraftResultResponse,
    QAAIHelperCommitRequest,
    QAAIHelperCommitResultResponse,
    QAAIHelperCommitResponse,
    QAAIHelperDeleteResponse,
    QAAIHelperDraftItemResponse,
    QAAIHelperDraftSetDetailResponse,
    QAAIHelperDraftSetResponse,
    QAAIHelperDraftSetStatus,
    QAAIHelperDraftUpdateRequest,
    QAAIHelperGenerateRequest,
    QAAIHelperPhase,
    QAAIHelperPlannedRevisionResponse,
    QAAIHelperPlannedRevisionStatus,
    QAAIHelperPlanRequest,
    QAAIHelperPlanningLockRequest,
    QAAIHelperPlanningOverrideApplyRequest,
    QAAIHelperPlanSectionResponse,
    QAAIHelperNewTestCaseSetPayload,
    QAAIHelperRequirementDeltaCreateRequest,
    QAAIHelperRequirementDeltaType,
    QAAIHelperRequirementPlanResponse,
    QAAIHelperRequirementPlanSaveRequest,
    QAAIHelperRequirementPlanStatus,
    QAAIHelperRestartResponse,
    QAAIHelperRunStatus,
    QAAIHelperSeedItemResponse,
    QAAIHelperSeedItemReviewUpdateRequest,
    QAAIHelperSeedRefineRequest,
    QAAIHelperSeedSectionInclusionRequest,
    QAAIHelperSeedSetResponse,
    QAAIHelperSeedSetStatus,
    QAAIHelperSessionCreateRequest,
    QAAIHelperScreenGuardResponse,
    QAAIHelperSessionScreen,
    QAAIHelperSessionListItemResponse,
    QAAIHelperSessionListResponse,
    QAAIHelperSessionResponse,
    QAAIHelperSessionStatus,
    QAAIHelperTicketSnapshotResponse,
    QAAIHelperTicketFetchRequest,
    QAAIHelperTestcaseDraftSetResponse,
    QAAIHelperTestcaseDraftItemResponse,
    QAAIHelperTestcaseDraftSelectionRequest,
    QAAIHelperTestcaseDraftSetStatus,
    QAAIHelperTestcaseDraftUpdateRequest,
    QAAIHelperTestcaseGenerateRequest,
    QAAIHelperTestcaseSetSelectionRequest,
    QAAIHelperTestcaseSectionSelectionRequest,
    QAAIHelperVerificationCategory,
    QAAIHelperVerificationItemResponse,
    QAAIHelperWorkspaceResponse,
)
from app.services.jira_client import JiraClient
from app.services.qa_ai_helper_llm_service import (
    QAAIHelperLLMResult,
    get_qa_ai_helper_llm_service,
)
from app.services.qa_ai_helper_preclean_service import parse_ticket_to_requirement_payload
from app.services.qa_ai_helper_planner import QAAIHelperPlanner
from app.services.qa_ai_helper_prompt_service import get_qa_ai_helper_prompt_service
from app.services.qa_ai_helper_runtime import (
    build_repair_prompt_payload,
    post_merge_generation_outputs,
    validate_merged_drafts,
)
from app.services.qa_ai_helper_metrics import (
    summarize_seed_adoption,
    summarize_testcase_adoption,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
_DB_JSON_ZLIB_PREFIX = "__qa_ai_helper_zlib__:"
_DB_JSON_COMPRESS_THRESHOLD = 32 * 1024
_SESSION_SCREEN_TRANSITIONS: Dict[str | None, set[str]] = {
    None: {QAAIHelperSessionScreen.TICKET_CONFIRMATION.value},
    QAAIHelperSessionScreen.TICKET_CONFIRMATION.value: {
        QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
        QAAIHelperSessionScreen.FAILED.value,
    },
    QAAIHelperSessionScreen.VERIFICATION_PLANNING.value: {
        QAAIHelperSessionScreen.SEED_REVIEW.value,
        QAAIHelperSessionScreen.FAILED.value,
    },
    QAAIHelperSessionScreen.SEED_REVIEW.value: {
        QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
        QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
        QAAIHelperSessionScreen.FAILED.value,
    },
    QAAIHelperSessionScreen.TESTCASE_REVIEW.value: {
        QAAIHelperSessionScreen.SET_SELECTION.value,
        QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
        QAAIHelperSessionScreen.SEED_REVIEW.value,
        QAAIHelperSessionScreen.FAILED.value,
    },
    QAAIHelperSessionScreen.SET_SELECTION.value: {
        QAAIHelperSessionScreen.COMMIT_RESULT.value,
        QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
        QAAIHelperSessionScreen.FAILED.value,
    },
    QAAIHelperSessionScreen.COMMIT_RESULT.value: set(),
    QAAIHelperSessionScreen.FAILED.value: set(),
}
_SCENARIO_TITLE_PREFIX_PATTERN = re.compile(r"^Scenario\s+\d+\s*:\s*", re.IGNORECASE)


def _now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return deepcopy(default)
    try:
        return json.loads(value)
    except Exception:
        return deepcopy(default)


def _json_storage_dumps(
    value: Any,
    *,
    compress_threshold: int = _DB_JSON_COMPRESS_THRESHOLD,
) -> Optional[str]:
    raw = _json_dumps(value)
    if raw is None:
        return None
    if len(raw) < compress_threshold:
        return raw
    compressed = zlib.compress(raw.encode("utf-8"), level=6)
    encoded = base64.b64encode(compressed).decode("ascii")
    candidate = f"{_DB_JSON_ZLIB_PREFIX}{encoded}"
    return candidate if len(candidate) < len(raw) else raw


def _json_storage_loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return deepcopy(default)
    raw = value
    if isinstance(value, str) and value.startswith(_DB_JSON_ZLIB_PREFIX):
        encoded = value[len(_DB_JSON_ZLIB_PREFIX) :]
        try:
            raw = zlib.decompress(base64.b64decode(encoded.encode("ascii"))).decode("utf-8")
        except Exception:
            return deepcopy(default)
    return _json_loads(raw, default)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _coerce_jira_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_coerce_jira_text(item) for item in value if _coerce_jira_text(item))
    if isinstance(value, dict):
        text_parts: List[str] = []
        if isinstance(value.get("text"), str):
            text_parts.append(value["text"])
        for child in value.get("content") or []:
            child_text = _coerce_jira_text(child)
            if child_text:
                text_parts.append(child_text)
        if not text_parts:
            for key in ("value", "title", "name"):
                if isinstance(value.get(key), str) and value[key].strip():
                    text_parts.append(value[key].strip())
        return "\n".join(part for part in text_parts if part).strip()
    return str(value)


def _compose_verification_target_condition_text(
    summary: Any,
    condition_text: Any,
) -> str:
    target = str(summary or "").strip()
    condition = str(condition_text or "").strip()
    if target and condition:
        return target if target == condition else f"{target}：{condition}"
    return target or condition


def _priority_from_text(value: str) -> Priority:
    normalized = str(value or "").strip().lower()
    if normalized == "high":
        return Priority.HIGH
    if normalized == "low":
        return Priority.LOW
    return Priority.MEDIUM


def _join_lines(lines: Sequence[str], *, numbered: bool = False) -> str:
    normalized = [str(item).strip() for item in lines if str(item).strip()]
    if not numbered:
        return "\n".join(normalized)
    return "\n".join(f"{index + 1}. {line}" for index, line in enumerate(normalized))


def _jira_wiki_inline_to_md(text: str) -> str:
    """Convert Jira wiki inline formatting to Markdown within a single line."""
    # Bold: *text* → **text**
    text = re.sub(r"(?<![*\w])\*([^\s*](?:[^*]*[^\s*])?)\*(?![*\w])", r"**\1**", text)
    # Italic: _text_ → *text*
    text = re.sub(r"(?<![_\w])_([^\s_](?:[^_]*[^\s_])?)_(?![_\w])", r"*\1*", text)
    # Strikethrough: -text- → ~~text~~
    text = re.sub(r"(?<![-\w])-([^\s\-](?:[^-]*[^\s\-])?)-(?![-\w])", r"~~\1~~", text)
    # Monospace: {{text}} → `text`
    text = re.sub(r"\{\{(.+?)\}\}", r"`\1`", text)
    # Links: [text|url] → [text](url)
    text = re.sub(r"\[([^|\]]+)\|([^\]]+)\]", r"[\1](\2)", text)
    # Simple links: [url] → <url>
    text = re.sub(r"\[(https?://[^\]]+)\]", r"<\1>", text)
    return text


def _jira_wiki_to_markdown(text: str) -> str:
    """Convert Jira wiki markup to Markdown."""
    if not text or not text.strip():
        return text or ""
    lines = text.split("\n")
    result: List[str] = []
    in_code = False
    in_noformat = False
    in_quote = False

    for line in lines:
        stripped = line.strip()

        # --- code blocks ---
        if not in_noformat:
            if re.match(r"^\{code(?::[\w+]+)?\}$", stripped) and not in_code:
                lang_m = re.match(r"^\{code:(\w+)\}$", stripped)
                result.append(f"```{lang_m.group(1) if lang_m else ''}")
                in_code = True
                continue
            if stripped == "{code}" and in_code:
                result.append("```")
                in_code = False
                continue

        # --- noformat blocks ---
        if not in_code:
            if stripped == "{noformat}" and not in_noformat:
                result.append("```")
                in_noformat = True
                continue
            if stripped == "{noformat}" and in_noformat:
                result.append("```")
                in_noformat = False
                continue

        if in_code or in_noformat:
            result.append(line)
            continue

        # --- quote blocks ---
        if stripped == "{quote}" and not in_quote:
            in_quote = True
            continue
        if stripped == "{quote}" and in_quote:
            in_quote = False
            continue

        # --- horizontal rule ---
        if stripped == "----":
            result.append("---")
            continue

        # --- headings h1. … h6. ---
        hm = re.match(r"^h([1-6])\.\s+(.*)", stripped)
        if hm:
            lvl, title = int(hm.group(1)), hm.group(2)
            result.append(f"{'#' * lvl} {_jira_wiki_inline_to_md(title)}")
            continue

        # --- unordered list (* / ** / ***) ---
        ul = re.match(r"^(\*+)\s+(.*)", stripped)
        if ul:
            depth = len(ul.group(1))
            content = _jira_wiki_inline_to_md(ul.group(2))
            result.append(f"{'  ' * (depth - 1)}- {content}")
            continue

        # --- ordered list (# / ## / ###) ---
        ol = re.match(r"^(#+)\s+(.*)", stripped)
        if ol:
            depth = len(ol.group(1))
            content = _jira_wiki_inline_to_md(ol.group(2))
            result.append(f"{'  ' * (depth - 1)}1. {content}")
            continue

        # --- regular line ---
        converted = _jira_wiki_inline_to_md(stripped)
        if in_quote:
            result.append(f"> {converted}")
        else:
            result.append(converted)

    return "\n".join(result)


def _build_ticket_markdown(*, ticket_key: str, summary: str, description: str) -> str:
    heading = f"# {ticket_key}"
    if summary:
        heading = f"{heading} {summary.strip()}"
    lines = [heading.strip()]
    converted = _jira_wiki_to_markdown(description)
    if converted.strip():
        lines.extend(["", converted.strip()])
    return "\n".join(lines).strip()


class QAAIHelperService:
    def __init__(
        self,
        db: AsyncSession | None = None,
        *,
        main_boundary: MainAccessBoundary | None = None,
        planner: QAAIHelperPlanner | None = None,
        jira_client_factory: Callable[[], JiraClient] = JiraClient,
    ) -> None:
        self.db = db
        self.main_boundary = main_boundary or get_main_access_boundary()
        self.settings = get_settings()
        self.planner = planner or QAAIHelperPlanner()
        self.prompt_service = get_qa_ai_helper_prompt_service()
        self.llm_service = get_qa_ai_helper_llm_service()
        self.jira_client_factory = jira_client_factory

    def _require_main_boundary(self) -> MainAccessBoundary:
        if self.main_boundary is None:
            raise RuntimeError("QAAIHelperService requires a managed main boundary")
        return self.main_boundary

    async def _run_read(self, operation: Callable[[Session], T]) -> T:
        return await self._require_main_boundary().run_sync_read(operation)

    async def _run_write(self, operation: Callable[[Session], T]) -> T:
        return await self._require_main_boundary().run_sync_write(operation)

    def _persistable_plan_json(self, plan: Dict[str, Any]) -> str:
        return _json_storage_dumps(self.planner.build_persistable_plan(plan)) or "{}"

    def _coverage_index_for_plan(self, plan: Dict[str, Any]) -> Dict[str, List[str]]:
        coverage_index = plan.get("coverage_index")
        if isinstance(coverage_index, dict) and coverage_index:
            return {
                str(key): [str(item) for item in (value or []) if str(item).strip()]
                for key, value in coverage_index.items()
                if str(key).strip()
            }
        return self.planner.rebuild_coverage_index(plan.get("sections") or [])

    def _rebuild_full_plan_from_workspace(
        self,
        *,
        session: QAAIHelperSessionResponse,
        canonical_revision: QAAIHelperCanonicalRevisionResponse,
        planned_revision: QAAIHelperPlannedRevisionResponse,
    ) -> Dict[str, Any]:
        compact_plan = planned_revision.matrix or {}
        return self.planner.build_plan(
            ticket_key=session.ticket_key or "TCG-UNKNOWN",
            canonical_revision_id=canonical_revision.id,
            canonical_language=canonical_revision.canonical_language.value
            if hasattr(canonical_revision.canonical_language, "value")
            else str(canonical_revision.canonical_language),
            content=canonical_revision.content,
            counter_settings=planned_revision.counter_settings,
            applicability_overrides=planned_revision.applicability_overrides,
            selected_references=planned_revision.selected_references,
            team_extensions=compact_plan.get("team_extensions", []),
        )

    def _serialize_session(self, session: QAAIHelperSession) -> QAAIHelperSessionResponse:
        return QAAIHelperSessionResponse.model_validate(
            {
                "id": session.id,
                "team_id": session.team_id,
                "created_by_user_id": session.created_by_user_id,
                "target_test_case_set_id": session.target_test_case_set_id,
                "selected_target_test_case_set_id": session.selected_target_test_case_set_id,
                "ticket_key": session.ticket_key,
                "include_comments": session.include_comments,
                "output_locale": session.output_locale,
                "canonical_language": session.canonical_language,
                "current_phase": session.current_phase,
                "current_screen": session.current_screen,
                "status": session.status,
                "active_canonical_revision_id": session.active_canonical_revision_id,
                "active_planned_revision_id": session.active_planned_revision_id,
                "active_draft_set_id": session.active_draft_set_id,
                "active_ticket_snapshot_id": session.active_ticket_snapshot_id,
                "active_requirement_plan_id": session.active_requirement_plan_id,
                "active_seed_set_id": session.active_seed_set_id,
                "active_testcase_draft_set_id": session.active_testcase_draft_set_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
        )

    def _serialize_ticket_snapshot(
        self,
        snapshot: Optional[QAAIHelperTicketSnapshot],
    ) -> Optional[QAAIHelperTicketSnapshotResponse]:
        if snapshot is None:
            return None
        return QAAIHelperTicketSnapshotResponse.model_validate(
            {
                "id": snapshot.id,
                "session_id": snapshot.session_id,
                "status": snapshot.status,
                "raw_ticket_markdown": snapshot.raw_ticket_markdown,
                "structured_requirement": _json_storage_loads(
                    snapshot.structured_requirement_json,
                    {},
                ),
                "validation_summary": _json_storage_loads(
                    snapshot.validation_summary_json,
                    {},
                ),
                "created_at": snapshot.created_at,
                "updated_at": snapshot.updated_at,
            }
        )

    def _serialize_check_condition(
        self,
        condition: QAAIHelperCheckCondition,
    ) -> QAAIHelperCheckConditionResponse:
        return QAAIHelperCheckConditionResponse.model_validate(
            {
                "id": condition.id,
                "condition_text": condition.condition_text,
                "coverage_tag": condition.coverage_tag,
                "display_order": condition.display_order,
                "created_at": condition.created_at,
                "updated_at": condition.updated_at,
            }
        )

    def _serialize_verification_item(
        self,
        item: QAAIHelperVerificationItem,
    ) -> QAAIHelperVerificationItemResponse:
        conditions = sorted(
            item.check_conditions or [],
            key=lambda current: (current.display_order, current.id),
        )
        return QAAIHelperVerificationItemResponse.model_validate(
            {
                "id": item.id,
                "category": item.category,
                "summary": item.summary,
                "detail": _json_storage_loads(item.detail_json, {}),
                "display_order": item.display_order,
                "check_conditions": [
                    self._serialize_check_condition(condition) for condition in conditions
                ],
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )

    def _validate_requirement_plan_payload(
        self,
        *,
        sections: Sequence[QAAIHelperPlanSection],
    ) -> Dict[str, Any]:
        errors: List[Dict[str, Any]] = []
        section_count = 0
        verification_item_count = 0
        check_condition_count = 0

        for section in sorted(sections, key=lambda current: (current.display_order, current.id)):
            section_count += 1
            items = sorted(
                section.verification_items or [],
                key=lambda current: (current.display_order, current.id),
            )
            if not items:
                errors.append(
                    {
                        "code": "section_requires_verification_item",
                        "section_id": section.section_id,
                        "message": f"{section.section_id} 尚未新增任何驗證目標及檢查條件",
                    }
                )
            for item in items:
                verification_item_count += 1
                item_summary = str(item.summary or "").strip()
                if not item_summary:
                    errors.append(
                        {
                            "code": "verification_item_summary_required",
                            "section_id": section.section_id,
                            "verification_item_id": item.id,
                            "message": "驗證目標及檢查條件不可為空",
                        }
                    )

                conditions = sorted(
                    item.check_conditions or [],
                    key=lambda current: (current.display_order, current.id),
                )
                if not conditions:
                    errors.append(
                        {
                            "code": "verification_item_requires_condition",
                            "section_id": section.section_id,
                            "verification_item_id": item.id,
                            "message": "每個驗證目標及檢查條件都必須指定 Coverage",
                        }
                    )
                for condition in conditions:
                    check_condition_count += 1
                    if not str(condition.condition_text or "").strip():
                        errors.append(
                            {
                                "code": "check_condition_text_required",
                                "section_id": section.section_id,
                                "verification_item_id": item.id,
                                "check_condition_id": condition.id,
                                "message": "驗證目標及檢查條件不可為空",
                            }
                        )
                    if not str(condition.coverage_tag or "").strip():
                        errors.append(
                            {
                                "code": "check_condition_coverage_required",
                                "section_id": section.section_id,
                                "verification_item_id": item.id,
                                "check_condition_id": condition.id,
                                "message": "檢查條件必須指定 coverage 類型",
                            }
                        )

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "stats": {
                "section_count": section_count,
                "verification_item_count": verification_item_count,
                "check_condition_count": check_condition_count,
            },
        }

    def _serialize_requirement_plan(
        self,
        plan: Optional[QAAIHelperRequirementPlan],
    ) -> Optional[QAAIHelperRequirementPlanResponse]:
        if plan is None:
            return None
        sections = sorted(plan.sections or [], key=lambda current: (current.display_order, current.id))
        return QAAIHelperRequirementPlanResponse.model_validate(
            {
                "id": plan.id,
                "session_id": plan.session_id,
                "ticket_snapshot_id": plan.ticket_snapshot_id,
                "revision_number": plan.revision_number,
                "status": plan.status,
                "section_start_number": plan.section_start_number,
                "criteria_reference": _json_storage_loads(plan.criteria_reference_json, {}),
                "technical_reference": _json_storage_loads(plan.technical_reference_json, {}),
                "autosave_summary": _json_storage_loads(plan.autosave_summary_json, {}),
                "validation_summary": self._validate_requirement_plan_payload(sections=sections),
                "sections": [self._serialize_plan_section(section) for section in sections],
                "locked_at": plan.locked_at,
                "locked_by_user_id": plan.locked_by_user_id,
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
            }
        )

    def _serialize_seed_item(
        self,
        item: QAAIHelperSeedItem,
        *,
        display_order: int,
    ) -> QAAIHelperSeedItemResponse:
        plan_section = item.plan_section
        verification_item = item.verification_item
        seed_body = _json_storage_loads(item.seed_body_json, {})
        if isinstance(seed_body, str):
            seed_body = {"text": seed_body}
        elif not isinstance(seed_body, dict):
            seed_body = {"text": str(seed_body or "").strip()}
        return QAAIHelperSeedItemResponse.model_validate(
            {
                "id": item.id,
                "seed_set_id": item.seed_set_id,
                "plan_section_id": item.plan_section_id,
                "verification_item_id": item.verification_item_id,
                "section_key": getattr(plan_section, "section_key", None),
                "section_id": getattr(plan_section, "section_id", None),
                "section_title": getattr(plan_section, "section_title", None),
                "verification_item_summary": getattr(verification_item, "summary", None),
                "verification_category": getattr(verification_item, "category", None),
                "check_condition_refs": _json_storage_loads(item.check_condition_refs_json, []),
                "coverage_tags": _json_storage_loads(item.coverage_tags_json, []),
                "seed_reference_key": item.seed_reference_key,
                "seed_summary": item.seed_summary,
                "seed_body": seed_body,
                "comment_text": item.comment_text,
                "is_ai_generated": item.is_ai_generated,
                "user_edited": item.user_edited,
                "included_for_testcase_generation": item.included_for_testcase_generation,
                "display_order": display_order,
                "last_refined_at": item.updated_at,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )

    def _serialize_seed_set(
        self,
        seed_set: Optional[QAAIHelperSeedSet],
    ) -> Optional[QAAIHelperSeedSetResponse]:
        if seed_set is None:
            return None
        items = sorted(
            seed_set.seed_items or [],
            key=lambda current: (
                getattr(getattr(current, "plan_section", None), "display_order", 9999),
                getattr(getattr(current, "verification_item", None), "display_order", 9999),
                current.id,
            ),
        )
        return QAAIHelperSeedSetResponse.model_validate(
            {
                "id": seed_set.id,
                "session_id": seed_set.session_id,
                "requirement_plan_id": seed_set.requirement_plan_id,
                "status": seed_set.status,
                "generation_round": seed_set.generation_round,
                "source_type": seed_set.source_type,
                "model_name": seed_set.model_name,
                "generated_seed_count": int(seed_set.generated_seed_count or 0),
                "included_seed_count": int(seed_set.included_seed_count or 0),
                "adoption_rate": float(seed_set.adoption_rate or 0.0),
                "created_by_user_id": seed_set.created_by_user_id,
                "created_at": seed_set.created_at,
                "updated_at": seed_set.updated_at,
                "seed_items": [
                    self._serialize_seed_item(item, display_order=index)
                    for index, item in enumerate(items)
                ],
            }
        )

    def _validate_testcase_draft_body(
        self,
        *,
        draft: QAAIHelperTestcaseDraft,
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        errors: List[Dict[str, str]] = []
        title = str(body.get("title") or "").strip()
        steps = [str(value).strip() for value in (body.get("steps") or []) if str(value).strip()]
        expected_results = [
            str(value).strip()
            for value in (body.get("expected_results") or [])
            if str(value).strip()
        ]
        if not draft.seed_reference_key or draft.seed_item_id is None:
            errors.append(
                {
                    "code": "missing_seed_reference",
                    "message": "testcase draft 缺少 seed reference，無法提交",
                }
            )
        if not title:
            errors.append({"code": "missing_title", "message": "title 不可為空"})
        if not steps:
            errors.append({"code": "missing_steps", "message": "steps 至少需要一筆"})
        if not expected_results:
            errors.append(
                {
                    "code": "missing_expected_results",
                    "message": "expected results 至少需要一筆",
                }
            )
        return {
            "is_valid": not errors,
            "errors": errors,
            "error_count": len(errors),
        }

    def _serialize_testcase_draft_item(
        self,
        draft: QAAIHelperTestcaseDraft,
    ) -> QAAIHelperTestcaseDraftItemResponse:
        seed_item = draft.seed_item
        plan_section = getattr(seed_item, "plan_section", None)
        verification_item = getattr(seed_item, "verification_item", None)
        body = _json_storage_loads(draft.body_json, {})
        if not isinstance(body, dict):
            body = {}
        return QAAIHelperTestcaseDraftItemResponse.model_validate(
            {
                "id": draft.id,
                "testcase_draft_set_id": draft.testcase_draft_set_id,
                "seed_item_id": draft.seed_item_id,
                "seed_reference_key": draft.seed_reference_key,
                "assigned_testcase_id": draft.assigned_testcase_id,
                "plan_section_id": getattr(seed_item, "plan_section_id", None),
                "verification_item_id": getattr(seed_item, "verification_item_id", None),
                "section_key": getattr(plan_section, "section_key", None),
                "section_id": getattr(plan_section, "section_id", None),
                "section_title": getattr(plan_section, "section_title", None),
                "verification_item_summary": getattr(verification_item, "summary", None),
                "verification_category": getattr(verification_item, "category", None),
                "body": body,
                "validation_summary": self._validate_testcase_draft_body(
                    draft=draft,
                    body=body,
                ),
                "is_ai_generated": draft.is_ai_generated,
                "user_edited": draft.user_edited,
                "selected_for_commit": draft.selected_for_commit,
                "created_at": draft.created_at,
                "updated_at": draft.updated_at,
            }
        )

    def _serialize_testcase_draft_set(
        self,
        draft_set: Optional[QAAIHelperTestcaseDraftSet],
    ) -> Optional[QAAIHelperTestcaseDraftSetResponse]:
        if draft_set is None:
            return None
        drafts = sorted(
            draft_set.drafts or [],
            key=lambda current: (
                getattr(getattr(getattr(current, "seed_item", None), "plan_section", None), "display_order", 9999),
                getattr(getattr(getattr(current, "seed_item", None), "verification_item", None), "display_order", 9999),
                current.id,
            ),
        )
        return QAAIHelperTestcaseDraftSetResponse.model_validate(
            {
                "id": draft_set.id,
                "session_id": draft_set.session_id,
                "seed_set_id": draft_set.seed_set_id,
                "status": draft_set.status,
                "model_name": draft_set.model_name,
                "generated_testcase_count": int(draft_set.generated_testcase_count or 0),
                "selected_for_commit_count": int(draft_set.selected_for_commit_count or 0),
                "adoption_rate": float(draft_set.adoption_rate or 0.0),
                "created_by_user_id": draft_set.created_by_user_id,
                "created_at": draft_set.created_at,
                "updated_at": draft_set.updated_at,
                "committed_at": draft_set.committed_at,
                "drafts": [self._serialize_testcase_draft_item(draft) for draft in drafts],
            }
        )

    def _serialize_plan_section(
        self,
        section: QAAIHelperPlanSection,
    ) -> QAAIHelperPlanSectionResponse:
        items = sorted(
            section.verification_items or [],
            key=lambda current: (current.display_order, current.id),
        )
        return QAAIHelperPlanSectionResponse.model_validate(
            {
                "id": section.id,
                "section_key": section.section_key,
                "section_id": section.section_id,
                "section_title": section.section_title,
                "given": _json_storage_loads(section.given_json, []),
                "when": _json_storage_loads(section.when_json, []),
                "then": _json_storage_loads(section.then_json, []),
                "display_order": section.display_order,
                "verification_items": [
                    self._serialize_verification_item(item) for item in items
                ],
                "created_at": section.created_at,
                "updated_at": section.updated_at,
            }
        )

    def _allowed_next_screens(
        self,
        *,
        session: QAAIHelperSession,
        ticket_snapshot: Optional[QAAIHelperTicketSnapshot],
        requirement_plan: Optional[QAAIHelperRequirementPlan],
        seed_set: Optional[QAAIHelperSeedSet],
        testcase_draft_set: Optional[QAAIHelperTestcaseDraftSet],
    ) -> List[str]:
        current = session.current_screen or None
        allowed = _SESSION_SCREEN_TRANSITIONS.get(current, set())
        next_screens: List[str] = []
        if QAAIHelperSessionScreen.VERIFICATION_PLANNING.value in allowed:
            validation_summary = _json_storage_loads(
                ticket_snapshot.validation_summary_json if ticket_snapshot else None,
                {},
            )
            if bool(validation_summary.get("is_valid")):
                next_screens.append(QAAIHelperSessionScreen.VERIFICATION_PLANNING.value)
        if (
            QAAIHelperSessionScreen.SEED_REVIEW.value in allowed
            and requirement_plan is not None
            and requirement_plan.status == "locked"
        ):
            next_screens.append(QAAIHelperSessionScreen.SEED_REVIEW.value)
        if (
            QAAIHelperSessionScreen.TESTCASE_REVIEW.value in allowed
            and seed_set is not None
            and seed_set.status == "locked"
            and int(seed_set.included_seed_count or 0) > 0
        ):
            next_screens.append(QAAIHelperSessionScreen.TESTCASE_REVIEW.value)
        if (
            QAAIHelperSessionScreen.SET_SELECTION.value in allowed
            and testcase_draft_set is not None
            and int(testcase_draft_set.selected_for_commit_count or 0) > 0
        ):
            next_screens.append(QAAIHelperSessionScreen.SET_SELECTION.value)
        if (
            QAAIHelperSessionScreen.COMMIT_RESULT.value in allowed
            and session.selected_target_test_case_set_id is not None
        ):
            next_screens.append(QAAIHelperSessionScreen.COMMIT_RESULT.value)
        if QAAIHelperSessionScreen.FAILED.value in allowed:
            next_screens.append(QAAIHelperSessionScreen.FAILED.value)
        return next_screens

    def _build_screen_guard(
        self,
        *,
        session: QAAIHelperSession,
        ticket_snapshot: Optional[QAAIHelperTicketSnapshot],
        requirement_plan: Optional[QAAIHelperRequirementPlan],
        seed_set: Optional[QAAIHelperSeedSet],
        testcase_draft_set: Optional[QAAIHelperTestcaseDraftSet],
    ) -> QAAIHelperScreenGuardResponse:
        return QAAIHelperScreenGuardResponse.model_validate(
            {
                "current_screen": session.current_screen,
                "allowed_next_screens": self._allowed_next_screens(
                    session=session,
                    ticket_snapshot=ticket_snapshot,
                    requirement_plan=requirement_plan,
                    seed_set=seed_set,
                    testcase_draft_set=testcase_draft_set,
                ),
                "can_restart": (
                    session.status != QAAIHelperSessionStatus.COMPLETED.value
                    and session.current_screen != QAAIHelperSessionScreen.COMMIT_RESULT.value
                ),
            }
        )

    def _set_session_screen(
        self,
        session: QAAIHelperSession,
        next_screen: str,
        *,
        allow_same: bool = True,
        force: bool = False,
    ) -> None:
        current = session.current_screen or None
        if allow_same and current == next_screen:
            return
        if force:
            session.current_screen = next_screen
            return
        allowed = _SESSION_SCREEN_TRANSITIONS.get(current, set())
        if next_screen not in allowed:
            raise ValueError(f"不合法的 current_screen transition: {current or 'ticket_input'} -> {next_screen}")
        session.current_screen = next_screen

    def _serialize_canonical(
        self,
        revision: Optional[QAAIHelperCanonicalRevision],
    ) -> Optional[QAAIHelperCanonicalRevisionResponse]:
        if revision is None:
            return None
        return QAAIHelperCanonicalRevisionResponse.model_validate(
            {
                "id": revision.id,
                "session_id": revision.session_id,
                "revision_number": revision.revision_number,
                "status": revision.status,
                "canonical_language": revision.canonical_language,
                "content": _json_storage_loads(revision.content_json, {}),
                "counter_settings": _json_storage_loads(revision.counter_settings_json, {}),
                "created_by_user_id": revision.created_by_user_id,
                "created_at": revision.created_at,
                "updated_at": revision.updated_at,
            }
        )

    def _serialize_planned(
        self,
        revision: Optional[QAAIHelperPlannedRevision],
    ) -> Optional[QAAIHelperPlannedRevisionResponse]:
        if revision is None:
            return None
        return QAAIHelperPlannedRevisionResponse.model_validate(
            {
                "id": revision.id,
                "session_id": revision.session_id,
                "canonical_revision_id": revision.canonical_revision_id,
                "revision_number": revision.revision_number,
                "status": revision.status,
                "matrix": _json_storage_loads(revision.matrix_json, {}),
                "seed_map": _json_storage_loads(revision.seed_map_json, {}),
                "applicability_overrides": _json_storage_loads(
                    revision.applicability_overrides_json,
                    {},
                ),
                "selected_references": _json_storage_loads(
                    revision.selected_references_json,
                    {"section_references": {}},
                ),
                "counter_settings": _json_storage_loads(revision.counter_settings_json, {}),
                "impact_summary": _json_storage_loads(revision.impact_summary_json, {}),
                "locked_at": revision.locked_at,
                "locked_by_user_id": revision.locked_by_user_id,
                "created_at": revision.created_at,
                "updated_at": revision.updated_at,
            }
        )

    def _serialize_draft_set(
        self,
        draft_set: Optional[QAAIHelperDraftSet],
        *,
        include_drafts: bool = False,
    ) -> Optional[QAAIHelperDraftSetDetailResponse]:
        if draft_set is None:
            return None
        drafts = [
            QAAIHelperDraftItemResponse.model_validate(
                {
                    "id": draft.id,
                    "item_key": draft.item_key,
                    "seed_id": draft.seed_id,
                    "testcase_id": draft.testcase_id,
                    "body": _json_storage_loads(draft.body_json, {}),
                    "trace": _json_storage_loads(draft.trace_json, {}),
                    "version": draft.version,
                    "created_at": draft.created_at,
                    "updated_at": draft.updated_at,
                }
            )
            for draft in (draft_set.drafts or [])
        ]
        payload = {
            "id": draft_set.id,
            "session_id": draft_set.session_id,
            "planned_revision_id": draft_set.planned_revision_id,
            "status": draft_set.status,
            "generation_mode": draft_set.generation_mode,
            "model_name": draft_set.model_name,
            "summary": _json_storage_loads(draft_set.summary_json, {}),
            "created_by_user_id": draft_set.created_by_user_id,
            "created_at": draft_set.created_at,
            "updated_at": draft_set.updated_at,
            "committed_at": draft_set.committed_at,
            "drafts": drafts if include_drafts else [],
        }
        return QAAIHelperDraftSetDetailResponse.model_validate(payload)

    def _serialize_commit_result(
        self,
        event: Optional[QAAIHelperTelemetryEvent],
    ) -> Optional[QAAIHelperCommitResultResponse]:
        if event is None:
            return None
        payload = _json_storage_loads(event.payload_json, {})
        draft_results = [
            QAAIHelperCommitDraftResultResponse.model_validate(item)
            for item in (payload.get("draft_results") or [])
        ]
        return QAAIHelperCommitResultResponse.model_validate(
            {
                "testcase_draft_set_id": int(payload.get("testcase_draft_set_id") or 0),
                "target_test_case_set_id": payload.get("target_test_case_set_id"),
                "target_test_case_set_name": payload.get("target_test_case_set_name"),
                "created_count": int(payload.get("created_count") or 0),
                "failed_count": int(payload.get("failed_count") or 0),
                "skipped_count": int(payload.get("skipped_count") or 0),
                "created_test_case_ids": payload.get("created_test_case_ids") or [],
                "failed_drafts": [
                    item for item in draft_results if item.status == "failed"
                ],
                "skipped_drafts": [
                    item for item in draft_results if item.status == "skipped"
                ],
                "draft_results": draft_results,
                "target_set_link_available": bool(payload.get("target_set_link")),
                "target_set_link": payload.get("target_set_link"),
                "committed_at": event.created_at,
            }
        )

    def _build_workspace_response(
        self,
        session: QAAIHelperSession,
        ticket_snapshot: Optional[QAAIHelperTicketSnapshot],
        canonical_revision: Optional[QAAIHelperCanonicalRevision],
        planned_revision: Optional[QAAIHelperPlannedRevision],
        draft_set: Optional[QAAIHelperDraftSet],
        requirement_plan: Optional[QAAIHelperRequirementPlan],
        seed_set: Optional[QAAIHelperSeedSet],
        testcase_draft_set: Optional[QAAIHelperTestcaseDraftSet],
        latest_validation_run: Optional[QAAIHelperValidationRun],
        latest_commit_event: Optional[QAAIHelperTelemetryEvent],
    ) -> QAAIHelperWorkspaceResponse:
        canonical_content = _json_storage_loads(
            canonical_revision.content_json if canonical_revision else None,
            {},
        )
        canonical_validation = (
            self.planner.validate_canonical_content(canonical_content)
            if canonical_content
            else {}
        )
        return QAAIHelperWorkspaceResponse(
            session=self._serialize_session(session),
            ticket_snapshot=self._serialize_ticket_snapshot(ticket_snapshot),
            screen_guard=self._build_screen_guard(
                session=session,
                ticket_snapshot=ticket_snapshot,
                requirement_plan=requirement_plan,
                seed_set=seed_set,
                testcase_draft_set=testcase_draft_set,
            ),
            source_payload=_json_storage_loads(session.source_payload_json, {}),
            canonical_validation=canonical_validation,
            requirement_plan=self._serialize_requirement_plan(requirement_plan),
            seed_set=self._serialize_seed_set(seed_set),
            testcase_draft_set=self._serialize_testcase_draft_set(testcase_draft_set),
            canonical_revision=self._serialize_canonical(canonical_revision),
            planned_revision=self._serialize_planned(planned_revision),
            draft_set=self._serialize_draft_set(draft_set, include_drafts=True),
            latest_validation_run=(
                {
                    "id": latest_validation_run.id,
                    "run_type": latest_validation_run.run_type,
                    "status": latest_validation_run.status,
                    "summary": _json_storage_loads(latest_validation_run.summary_json, {}),
                    "errors": _json_storage_loads(latest_validation_run.errors_json, []),
                    "created_at": latest_validation_run.created_at,
                }
                if latest_validation_run is not None
                else None
            ),
            commit_result=self._serialize_commit_result(latest_commit_event),
        )

    def _load_workspace_sync(
        self,
        sync_db: Session,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        session = (
            sync_db.query(QAAIHelperSession)
            .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
            .first()
        )
        if session is None:
            raise ValueError("找不到 qa_ai_helper session")
        ticket_snapshot = (
            sync_db.query(QAAIHelperTicketSnapshot)
            .filter(QAAIHelperTicketSnapshot.id == session.active_ticket_snapshot_id)
            .first()
            if session.active_ticket_snapshot_id
            else None
        )
        canonical_revision = (
            sync_db.query(QAAIHelperCanonicalRevision)
            .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
            .first()
            if session.active_canonical_revision_id
            else None
        )
        planned_revision = (
            sync_db.query(QAAIHelperPlannedRevision)
            .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
            .first()
            if session.active_planned_revision_id
            else None
        )
        draft_set = (
            sync_db.query(QAAIHelperDraftSet)
            .filter(QAAIHelperDraftSet.id == session.active_draft_set_id)
            .first()
            if session.active_draft_set_id
            else None
        )
        requirement_plan = (
            sync_db.query(QAAIHelperRequirementPlan)
            .filter(QAAIHelperRequirementPlan.id == session.active_requirement_plan_id)
            .first()
            if session.active_requirement_plan_id
            else None
        )
        seed_set = (
            sync_db.query(QAAIHelperSeedSet)
            .filter(QAAIHelperSeedSet.id == session.active_seed_set_id)
            .first()
            if session.active_seed_set_id
            else None
        )
        testcase_draft_set = (
            sync_db.query(QAAIHelperTestcaseDraftSet)
            .filter(QAAIHelperTestcaseDraftSet.id == session.active_testcase_draft_set_id)
            .first()
            if session.active_testcase_draft_set_id
            else None
        )
        latest_validation_run = (
            sync_db.query(QAAIHelperValidationRun)
            .filter(QAAIHelperValidationRun.session_id == session.id)
            .order_by(QAAIHelperValidationRun.id.desc())
            .first()
        )
        latest_commit_event = (
            sync_db.query(QAAIHelperTelemetryEvent)
            .filter(
                QAAIHelperTelemetryEvent.session_id == session.id,
                QAAIHelperTelemetryEvent.stage == "commit",
                QAAIHelperTelemetryEvent.event_name == "result",
            )
            .order_by(QAAIHelperTelemetryEvent.id.desc())
            .first()
        )
        return self._build_workspace_response(
            session,
            ticket_snapshot,
            canonical_revision,
            planned_revision,
            draft_set,
            requirement_plan,
            seed_set,
            testcase_draft_set,
            latest_validation_run,
            latest_commit_event,
        )

    def _next_revision_number(
        self,
        sync_db: Session,
        model: Any,
        session_id: int,
    ) -> int:
        latest = (
            sync_db.query(model.revision_number)
            .filter(model.session_id == session_id)
            .order_by(model.revision_number.desc())
            .first()
        )
        return (latest[0] if latest else 0) + 1

    def _build_initial_sections_payload(
        self,
        *,
        ticket_key: str,
        structured_requirement: Dict[str, Any],
        section_start_number: str,
    ) -> List[Dict[str, Any]]:
        scenarios = structured_requirement.get("Acceptance Criteria") or []
        start_value = int(section_start_number)
        sections: List[Dict[str, Any]] = []
        for index, entry in enumerate(scenarios):
            scenario = entry.get("Scenario") if isinstance(entry, dict) else None
            if not isinstance(scenario, dict):
                continue
            scenario_name = str(scenario.get("name") or f"Scenario {index + 1}").strip()
            scenario_title = _SCENARIO_TITLE_PREFIX_PATTERN.sub("", scenario_name).strip() or scenario_name
            section_number = start_value + (index * 10)
            sections.append(
                {
                    "section_key": f"scenario-{index + 1:03d}",
                    "section_id": f"{ticket_key}.{section_number:03d}",
                    "section_title": scenario_title,
                    "given": [str(item).strip() for item in (scenario.get("Given") or []) if str(item).strip()],
                    "when": [str(item).strip() for item in (scenario.get("When") or []) if str(item).strip()],
                    "then": [str(item).strip() for item in (scenario.get("Then") or []) if str(item).strip()],
                    "verification_items": [],
                }
            )
        return sections

    def _create_requirement_plan_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
        ticket_snapshot: QAAIHelperTicketSnapshot,
        section_start_number: str = "010",
    ) -> QAAIHelperRequirementPlan:
        structured_requirement = _json_storage_loads(ticket_snapshot.structured_requirement_json, {})
        plan = QAAIHelperRequirementPlan(
            session_id=session.id,
            ticket_snapshot_id=ticket_snapshot.id,
            revision_number=self._next_revision_number(sync_db, QAAIHelperRequirementPlan, session.id),
            status=QAAIHelperRequirementPlanStatus.DRAFT.value,
            section_start_number=section_start_number,
            criteria_reference_json=_json_storage_dumps(structured_requirement.get("Criteria") or {}),
            technical_reference_json=_json_storage_dumps(
                structured_requirement.get("Technical Specifications") or {}
            ),
            autosave_summary_json=_json_storage_dumps(
                {
                    "mode": "initialize",
                    "saved_at": _now().isoformat(),
                    "section_count": len(structured_requirement.get("Acceptance Criteria") or []),
                }
            ),
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(plan)
        sync_db.flush()

        initial_sections = self._build_initial_sections_payload(
            ticket_key=session.ticket_key or "TCG-UNKNOWN",
            structured_requirement=structured_requirement,
            section_start_number=section_start_number,
        )
        self._replace_requirement_plan_sections_sync(
            sync_db,
            requirement_plan=plan,
            section_start_number=section_start_number,
            sections=initial_sections,
        )
        sync_db.flush()
        return plan

    def _replace_requirement_plan_sections_sync(
        self,
        sync_db: Session,
        *,
        requirement_plan: QAAIHelperRequirementPlan,
        section_start_number: str,
        sections: Sequence[Dict[str, Any]],
    ) -> None:
        for existing in list(requirement_plan.sections or []):
            sync_db.delete(existing)
        sync_db.flush()

        start_value = int(section_start_number)
        for section_index, section_payload in enumerate(sections):
            section_id = f"{requirement_plan.session.ticket_key}.{start_value + (section_index * 10):03d}"
            section = QAAIHelperPlanSection(
                requirement_plan_id=requirement_plan.id,
                section_key=str(section_payload.get("section_key") or f"scenario-{section_index + 1:03d}").strip(),
                section_id=section_id,
                section_title=str(section_payload.get("section_title") or "").strip() or section_id,
                given_json=_json_storage_dumps(section_payload.get("given") or []),
                when_json=_json_storage_dumps(section_payload.get("when") or []),
                then_json=_json_storage_dumps(section_payload.get("then") or []),
                display_order=section_index,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(section)
            sync_db.flush()

            verification_items = section_payload.get("verification_items") or []
            for item_index, item_payload in enumerate(verification_items):
                item = QAAIHelperVerificationItem(
                    plan_section_id=section.id,
                    category=str(item_payload.get("category") or QAAIHelperVerificationCategory.FUNCTIONAL.value),
                    summary=str(item_payload.get("summary") or "").strip(),
                    detail_json=_json_storage_dumps(item_payload.get("detail") or {}),
                    display_order=item_index,
                    created_at=_now(),
                    updated_at=_now(),
                )
                sync_db.add(item)
                sync_db.flush()

                check_conditions = item_payload.get("check_conditions") or []
                for condition_index, condition_payload in enumerate(check_conditions):
                    condition = QAAIHelperCheckCondition(
                        verification_item_id=item.id,
                        condition_text=str(condition_payload.get("condition_text") or "").strip(),
                        coverage_tag=str(condition_payload.get("coverage_tag") or "").strip(),
                        display_order=condition_index,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    sync_db.add(condition)

        requirement_plan.section_start_number = section_start_number
        requirement_plan.updated_at = _now()
        sync_db.flush()
        sync_db.expire(requirement_plan, ["sections"])

    def _seed_generation_items_from_plan(
        self,
        requirement_plan: QAAIHelperRequirementPlanResponse,
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        item_index = 0
        for section in requirement_plan.sections:
            for verification_item in section.verification_items:
                raw_conditions = [
                    {
                        "id": condition.id,
                        "condition_text": condition.condition_text,
                        "coverage_tag": condition.coverage_tag.value
                        if hasattr(condition.coverage_tag, "value")
                        else str(condition.coverage_tag),
                    }
                    for condition in verification_item.check_conditions
                ] or [
                    {
                        "id": None,
                        "condition_text": verification_item.summary,
                        "coverage_tag": QAAIHelperCoverageCategory.HAPPY_PATH.value,
                    }
                ]
                for condition_index, raw_condition in enumerate(raw_conditions):
                    combined_text = _compose_verification_target_condition_text(
                        verification_item.summary,
                        raw_condition.get("condition_text"),
                    )
                    coverage_tag = str(
                        raw_condition.get("coverage_tag")
                        or QAAIHelperCoverageCategory.HAPPY_PATH.value
                    ).strip() or QAAIHelperCoverageCategory.HAPPY_PATH.value
                    seed_reference_key = (
                        f"{section.section_id}.V{verification_item.display_order + 1:03d}.S{(condition_index + 1) * 10:03d}"
                    )
                    items.append(
                        {
                            "item_index": item_index,
                            "plan_section_id": section.id,
                            "section_key": section.section_key,
                            "section_id": section.section_id,
                            "section_title": section.section_title,
                            "verification_item_id": verification_item.id,
                            "verification_item_ref": f"verification-item-{verification_item.id}",
                            "verification_item_summary": combined_text,
                            "verification_category": (
                                verification_item.category.value
                                if hasattr(verification_item.category, "value")
                                else str(verification_item.category)
                            ),
                            "verification_detail": verification_item.detail,
                            "check_condition_ids": [raw_condition["id"]] if raw_condition.get("id") is not None else [],
                            "required_assertions": [
                                {
                                    "id": raw_condition.get("id"),
                                    "text": combined_text,
                                    "coverage_tag": coverage_tag,
                                }
                            ],
                            "coverage_tags": [coverage_tag],
                            "seed_reference_key": seed_reference_key,
                            "title_hint": combined_text,
                            "intent": combined_text,
                        }
                    )
                    item_index += 1
        return items

    def _seed_section_summary(
        self,
        requirement_plan: QAAIHelperRequirementPlanResponse,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "section_key": section.section_key,
                "section_id": section.section_id,
                "section_title": section.section_title,
                "verification_item_count": len(section.verification_items or []),
            }
            for section in requirement_plan.sections
        ]

    def _default_seed_output(self, generation_item: Dict[str, Any]) -> Dict[str, Any]:
        required_assertions = generation_item.get("required_assertions") or []
        first_assertion = required_assertions[0] if required_assertions else {}
        assertion_text = (
            str(first_assertion.get("text") or "").strip()
            if isinstance(first_assertion, dict)
            else ""
        )
        return {
            "item_index": int(generation_item.get("item_index") or 0),
            "seed_reference_key": str(generation_item.get("seed_reference_key") or "").strip(),
            "section_id": str(generation_item.get("section_id") or "").strip(),
            "verification_item_ref": str(generation_item.get("verification_item_ref") or "").strip(),
            "check_condition_ids": generation_item.get("check_condition_ids") or [],
            "seed_summary": str(
                generation_item.get("title_hint")
                or generation_item.get("verification_item_summary")
                or generation_item.get("seed_reference_key")
                or "Seed"
            ).strip(),
            "seed_body": assertion_text
            or str(generation_item.get("verification_item_summary") or "").strip()
            or "請依驗證項目執行測試",
            "coverage_tags": generation_item.get("coverage_tags")
            or [QAAIHelperCoverageCategory.HAPPY_PATH.value],
        }

    def _normalize_seed_output(
        self,
        generation_item: Dict[str, Any],
        output: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = self._default_seed_output(generation_item)
        if not isinstance(output, dict):
            return normalized
        normalized["seed_reference_key"] = str(
            output.get("seed_reference_key") or normalized["seed_reference_key"]
        ).strip()
        normalized["verification_item_ref"] = str(
            output.get("verification_item_ref") or normalized["verification_item_ref"]
        ).strip()
        normalized["seed_summary"] = str(
            output.get("seed_summary") or normalized["seed_summary"]
        ).strip()
        normalized["seed_body"] = str(output.get("seed_body") or normalized["seed_body"]).strip()
        coverage_tags = output.get("coverage_tags") or normalized["coverage_tags"]
        if not isinstance(coverage_tags, list):
            coverage_tags = [str(coverage_tags)]
        normalized["coverage_tags"] = [
            str(value).strip() for value in coverage_tags if str(value).strip()
        ] or normalized["coverage_tags"]
        condition_ids = output.get("check_condition_ids") or normalized["check_condition_ids"]
        normalized["check_condition_ids"] = [
            int(value) for value in condition_ids if str(value).strip().isdigit()
        ] or normalized["check_condition_ids"]
        return normalized

    def _refresh_seed_adoption_summary_sync(self, seed_set: QAAIHelperSeedSet) -> None:
        summary = summarize_seed_adoption(seed_set.seed_items or [])
        seed_set.generated_seed_count = int(summary["generated_seed_count"])
        seed_set.included_seed_count = int(summary["included_seed_count"])
        seed_set.adoption_rate = float(summary["seed_adoption_rate"])
        seed_set.updated_at = _now()

    def _mark_seed_review_dirty_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
        seed_set: QAAIHelperSeedSet,
    ) -> None:
        seed_set.status = QAAIHelperSeedSetStatus.DRAFT.value
        seed_set.updated_at = _now()
        self._refresh_seed_adoption_summary_sync(seed_set)
        self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)
        session.active_seed_set_id = seed_set.id
        self._set_session_screen(
            session,
            QAAIHelperSessionScreen.SEED_REVIEW.value,
            allow_same=True,
            force=True,
        )
        session.updated_at = _now()

    def _allocate_testcase_ids(
        self,
        seed_items: Sequence[QAAIHelperSeedItem],
    ) -> Dict[int, str]:
        grouped_by_section: Dict[str, List[QAAIHelperSeedItem]] = {}
        for seed_item in seed_items:
            section_id = str(getattr(getattr(seed_item, "plan_section", None), "section_id", "")).strip()
            if not section_id:
                continue
            grouped_by_section.setdefault(section_id, []).append(seed_item)

        allocations: Dict[int, str] = {}
        for section_id, items in grouped_by_section.items():
            group_map: Dict[int, List[QAAIHelperSeedItem]] = {}
            ordered_group_ids: List[int] = []
            for seed_item in sorted(
                items,
                key=lambda current: (
                    getattr(getattr(current, "verification_item", None), "display_order", 9999),
                    current.id,
                ),
            ):
                group_id = int(getattr(seed_item, "verification_item_id", 0) or 0)
                if group_id not in group_map:
                    group_map[group_id] = []
                    ordered_group_ids.append(group_id)
                group_map[group_id].append(seed_item)

            previous_last_tail: Optional[int] = None
            for group_index, group_id in enumerate(ordered_group_ids):
                default_start = 10 if group_index == 0 else group_index * 100
                current_start = default_start
                if previous_last_tail is not None and current_start <= previous_last_tail:
                    current_start = ((previous_last_tail // 100) + 1) * 100
                for item_index, seed_item in enumerate(group_map[group_id]):
                    tail = current_start + (item_index * 10)
                    allocations[seed_item.id] = f"{section_id}.{tail:03d}"
                    previous_last_tail = tail
        return allocations

    def _testcase_generation_items_from_seed_set(
        self,
        seed_set: QAAIHelperSeedSet,
    ) -> List[Dict[str, Any]]:
        included_seed_items = [
            item
            for item in (seed_set.seed_items or [])
            if item.included_for_testcase_generation
        ]
        ordered_seed_items = sorted(
            included_seed_items,
            key=lambda current: (
                getattr(getattr(current, "plan_section", None), "display_order", 9999),
                getattr(getattr(current, "verification_item", None), "display_order", 9999),
                current.id,
            ),
        )
        testcase_id_map = self._allocate_testcase_ids(ordered_seed_items)
        items: List[Dict[str, Any]] = []
        for item_index, seed_item in enumerate(ordered_seed_items):
            section = seed_item.plan_section
            verification_item = seed_item.verification_item
            seed_body = _json_storage_loads(seed_item.seed_body_json, {})
            if isinstance(seed_body, dict):
                seed_body_text = str(seed_body.get("text") or seed_body.get("summary") or "").strip()
            else:
                seed_body_text = str(seed_body or "").strip()
            check_condition_ids = _json_storage_loads(seed_item.check_condition_refs_json, [])
            check_conditions = []
            if verification_item is not None:
                check_conditions = [
                    {
                        "id": condition.id,
                        "text": _compose_verification_target_condition_text(
                            verification_item.summary,
                            condition.condition_text,
                        ),
                    }
                    for condition in sorted(
                        verification_item.check_conditions or [],
                        key=lambda current: (current.display_order, current.id),
                    )
                    if not check_condition_ids or condition.id in check_condition_ids
                ]
            body_title = str(seed_item.seed_summary or getattr(verification_item, "summary", "")).strip()
            items.append(
                {
                    "item_index": item_index,
                    "seed_item_id": seed_item.id,
                    "seed_reference_key": seed_item.seed_reference_key,
                    "assigned_testcase_id": testcase_id_map.get(seed_item.id, ""),
                    "section_key": getattr(section, "section_key", None),
                    "section_id": getattr(section, "section_id", None),
                    "section_title": getattr(section, "section_title", None),
                    "verification_item_id": getattr(seed_item, "verification_item_id", None),
                    "verification_item_ref": f"verification-item-{getattr(seed_item, 'verification_item_id', 0)}",
                    "verification_item_summary": getattr(verification_item, "summary", None),
                    "verification_category": (
                        verification_item.category.value
                        if verification_item is not None and hasattr(verification_item.category, "value")
                        else getattr(verification_item, "category", None)
                    ),
                    "title_hint": body_title,
                    "intent": body_title,
                    "priority": "Medium",
                    "precondition_hints": list(getattr(section, "given", []) or _json_storage_loads(getattr(section, "given_json", None), [])),
                    "step_hints": list(getattr(section, "when", []) or _json_storage_loads(getattr(section, "when_json", None), [])),
                    "expected_hints": [
                        str(condition.get("text") or "").strip()
                        for condition in check_conditions
                        if str(condition.get("text") or "").strip()
                    ] or ([seed_body_text] if seed_body_text else []),
                    "required_assertions": check_conditions,
                    "seed_body_text": seed_body_text,
                }
            )
        return items

    def _default_testcase_output(
        self,
        generation_item: Dict[str, Any],
    ) -> Dict[str, Any]:
        title = str(
            generation_item.get("title_hint")
            or generation_item.get("verification_item_summary")
            or generation_item.get("assigned_testcase_id")
            or "Generated testcase"
        ).strip()
        preconditions = [
            str(value).strip()
            for value in (generation_item.get("precondition_hints") or [])
            if str(value).strip()
        ]
        steps = [
            str(value).strip()
            for value in (generation_item.get("step_hints") or [])
            if str(value).strip()
        ]
        expected_results = [
            str(value).strip()
            for value in (generation_item.get("expected_hints") or [])
            if str(value).strip()
        ]
        if not preconditions:
            preconditions = ["已準備符合需求的測試資料"]
        if not steps:
            steps = ["執行對應驗證項目操作"]
        if not expected_results:
            expected_results = [
                str(generation_item.get("seed_body_text") or title or "系統符合預期結果").strip()
            ]
        return {
            "item_index": int(generation_item.get("item_index") or 0),
            "seed_reference_key": str(generation_item.get("seed_reference_key") or "").strip(),
            "title": title,
            "priority": str(generation_item.get("priority") or "Medium").strip() or "Medium",
            "preconditions": preconditions,
            "steps": steps,
            "expected_results": expected_results,
        }

    def _normalize_testcase_output(
        self,
        generation_item: Dict[str, Any],
        output: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = self._default_testcase_output(generation_item)
        if not isinstance(output, dict):
            return normalized
        normalized["seed_reference_key"] = str(
            output.get("seed_reference_key") or normalized["seed_reference_key"]
        ).strip()
        normalized["title"] = str(output.get("title") or normalized["title"]).strip()
        normalized["priority"] = str(output.get("priority") or normalized["priority"]).strip() or "Medium"
        for field in ("preconditions", "steps", "expected_results"):
            values = output.get(field) or normalized[field]
            if not isinstance(values, list):
                values = [str(values)]
            normalized[field] = [
                str(value).strip() for value in values if str(value).strip()
            ] or normalized[field]
        return normalized

    def _refresh_testcase_adoption_summary_sync(
        self,
        draft_set: QAAIHelperTestcaseDraftSet,
    ) -> None:
        summary = summarize_testcase_adoption(draft_set.drafts or [])
        draft_set.generated_testcase_count = int(summary["generated_testcase_count"])
        draft_set.selected_for_commit_count = int(summary["selected_for_commit_count"])
        draft_set.adoption_rate = float(summary["testcase_adoption_rate"])
        draft_set.updated_at = _now()

    def _mark_active_seed_sets_superseded_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
    ) -> None:
        seed_sets = (
            sync_db.query(QAAIHelperSeedSet)
            .filter(
                QAAIHelperSeedSet.session_id == session.id,
                QAAIHelperSeedSet.status.in_(["draft", "locked"]),
            )
            .all()
        )
        for seed_set in seed_sets:
            seed_set.status = "superseded"
            seed_set.updated_at = _now()
        session.active_seed_set_id = None

    def _mark_active_testcase_draft_sets_superseded_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
    ) -> None:
        testcase_draft_sets = (
            sync_db.query(QAAIHelperTestcaseDraftSet)
            .filter(
                QAAIHelperTestcaseDraftSet.session_id == session.id,
                QAAIHelperTestcaseDraftSet.status.in_(["draft", "reviewing"]),
            )
            .all()
        )
        for testcase_draft_set in testcase_draft_sets:
            testcase_draft_set.status = "superseded"
            testcase_draft_set.updated_at = _now()
        session.active_testcase_draft_set_id = None

    def _mark_active_drafts_outdated_sync(
        self,
        sync_db: Session,
        *,
        session_id: int,
    ) -> None:
        draft_sets = (
            sync_db.query(QAAIHelperDraftSet)
            .filter(
                QAAIHelperDraftSet.session_id == session_id,
                QAAIHelperDraftSet.status == QAAIHelperDraftSetStatus.ACTIVE.value,
            )
            .all()
        )
        for draft_set in draft_sets:
            draft_set.status = QAAIHelperDraftSetStatus.OUTDATED.value
            draft_set.updated_at = _now()

    def _persist_validation_run_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
        planned_revision_id: int,
        draft_set_id: Optional[int],
        run_type: str,
        status: str,
        summary: Dict[str, Any],
        errors: Sequence[Dict[str, Any]],
        user_id: Optional[int],
    ) -> QAAIHelperValidationRun:
        validation_run = QAAIHelperValidationRun(
            session_id=session.id,
            planned_revision_id=planned_revision_id,
            draft_set_id=draft_set_id,
            run_type=run_type,
            status=status,
            summary_json=_json_storage_dumps(summary),
            errors_json=_json_storage_dumps(list(errors)),
            created_by_user_id=user_id,
            created_at=_now(),
        )
        sync_db.add(validation_run)
        sync_db.flush()
        return validation_run

    def _persist_telemetry_sync(
        self,
        sync_db: Session,
        *,
        session: QAAIHelperSession,
        planned_revision_id: Optional[int],
        draft_set_id: Optional[int],
        user_id: Optional[int],
        stage: str,
        event_name: str,
        status: str,
        model_name: Optional[str],
        usage: Dict[str, int],
        duration_ms: int,
        payload: Optional[Dict[str, Any]],
        error_message: Optional[str] = None,
    ) -> None:
        sync_db.add(
            QAAIHelperTelemetryEvent(
                session_id=session.id,
                planned_revision_id=planned_revision_id,
                draft_set_id=draft_set_id,
                team_id=session.team_id,
                user_id=user_id,
                stage=stage,
                event_name=event_name,
                status=status,
                model_name=model_name,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                total_tokens=int(usage.get("total_tokens") or 0),
                duration_ms=duration_ms,
                payload_json=_json_storage_dumps(payload),
                error_message=error_message,
                created_at=_now(),
            )
        )

    def _ensure_ai_helper_root_section_sync(
        self,
        sync_db: Session,
        *,
        set_id: int,
    ) -> TestCaseSection:
        section = (
            sync_db.query(TestCaseSection)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.parent_section_id.is_(None),
                TestCaseSection.name == "QA AI Helper",
            )
            .first()
        )
        if section:
            return section
        max_sort = (
            sync_db.query(TestCaseSection.sort_order)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.parent_section_id.is_(None),
            )
            .order_by(TestCaseSection.sort_order.desc())
            .first()
        )
        section = TestCaseSection(
            test_case_set_id=set_id,
            name="QA AI Helper",
            description="由新版 QA AI Helper 產生的測試案例區段",
            parent_section_id=None,
            level=1,
            sort_order=(max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0,
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(section)
        sync_db.flush()
        return section

    def _ensure_commit_section_sync(
        self,
        sync_db: Session,
        *,
        set_id: int,
        parent_section_id: int,
        name: str,
    ) -> TestCaseSection:
        normalized_name = (name or "Generated").strip()[:100]
        existing = (
            sync_db.query(TestCaseSection)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.parent_section_id == parent_section_id,
                TestCaseSection.name == normalized_name,
            )
            .first()
        )
        if existing:
            return existing
        max_sort = (
            sync_db.query(TestCaseSection.sort_order)
            .filter(
                TestCaseSection.test_case_set_id == set_id,
                TestCaseSection.parent_section_id == parent_section_id,
            )
            .order_by(TestCaseSection.sort_order.desc())
            .first()
        )
        section = TestCaseSection(
            test_case_set_id=set_id,
            name=normalized_name,
            description=None,
            parent_section_id=parent_section_id,
            level=2,
            sort_order=(max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0,
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(section)
        sync_db.flush()
        return section

    def _create_test_case_set_sync(
        self,
        sync_db: Session,
        *,
        team_id: int,
        payload: QAAIHelperNewTestCaseSetPayload,
    ) -> TestCaseSet:
        existing = (
            sync_db.query(TestCaseSet)
            .filter(TestCaseSet.name == payload.name)
            .first()
        )
        if existing is not None:
            raise ValueError(f"Test Case Set 名稱已存在: {payload.name}")
        new_set = TestCaseSet(
            team_id=team_id,
            name=payload.name,
            description=payload.description,
            is_default=False,
            created_at=_now(),
            updated_at=_now(),
        )
        sync_db.add(new_set)
        sync_db.flush()
        sync_db.add(
            TestCaseSection(
                test_case_set_id=new_set.id,
                name="Unassigned",
                description="未分配的測試案例",
                parent_section_id=None,
                level=1,
                sort_order=0,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        sync_db.flush()
        return new_set

    async def start_session(
        self,
        *,
        team_id: int,
        user_id: int,
        request: QAAIHelperSessionCreateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        jira_issue = self.jira_client_factory().get_issue(
            request.ticket_key,
            fields=[
                "summary",
                "description",
                "comment",
            ],
        )
        if not jira_issue:
            raise RuntimeError(f"Jira 找不到 ticket: {request.ticket_key}")

        fields = jira_issue.get("fields") or {}
        summary = _coerce_jira_text(fields.get("summary"))
        description = _coerce_jira_text(fields.get("description"))
        raw_comments: List[str] = []
        raw_source_payload = self.planner.resolve_raw_sources(
            summary=summary,
            description=description,
            comments=raw_comments,
        )
        parser_payload = parse_ticket_to_requirement_payload(description, raw_comments)
        raw_ticket_markdown = _build_ticket_markdown(
            ticket_key=request.ticket_key,
            summary=summary,
            description=description,
        )

        def _create(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if team is None:
                raise ValueError(f"找不到 Team {team_id}")

            session = QAAIHelperSession(
                team_id=team_id,
                created_by_user_id=user_id,
                target_test_case_set_id=None,
                ticket_key=request.ticket_key,
                include_comments=False,
                output_locale=request.output_locale.value,
                canonical_language=None,
                current_phase=QAAIHelperPhase.INTAKE.value,
                status=QAAIHelperSessionStatus.ACTIVE.value,
                source_payload_json=_json_storage_dumps(raw_source_payload),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(session)
            sync_db.flush()
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TICKET_CONFIRMATION.value,
                allow_same=False,
            )

            validation_result = parser_payload.get("validation_result") or {}
            ticket_snapshot = QAAIHelperTicketSnapshot(
                session_id=session.id,
                status="validated" if bool(validation_result.get("is_valid")) else "loaded",
                raw_ticket_markdown=raw_ticket_markdown,
                structured_requirement_json=_json_storage_dumps(
                    parser_payload.get("structured_requirement") or {}
                ),
                validation_summary_json=_json_storage_dumps(validation_result),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(ticket_snapshot)
            sync_db.flush()

            session.active_ticket_snapshot_id = ticket_snapshot.id
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_create)

    async def list_sessions(
        self,
        *,
        team_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> QAAIHelperSessionListResponse:
        def _list(sync_db: Session) -> QAAIHelperSessionListResponse:
            query = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.team_id == team_id)
                .order_by(QAAIHelperSession.updated_at.desc(), QAAIHelperSession.id.desc())
            )
            total = query.count()
            sessions = query.offset(offset).limit(limit).all()
            items: List[QAAIHelperSessionListItemResponse] = []
            for session in sessions:
                canonical_revision = (
                    sync_db.query(QAAIHelperCanonicalRevision)
                    .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
                    .first()
                    if session.active_canonical_revision_id
                    else None
                )
                planned_revision = (
                    sync_db.query(QAAIHelperPlannedRevision)
                    .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
                    .first()
                    if session.active_planned_revision_id
                    else None
                )
                draft_set = (
                    sync_db.query(QAAIHelperDraftSet)
                    .filter(QAAIHelperDraftSet.id == session.active_draft_set_id)
                    .first()
                    if session.active_draft_set_id
                    else None
                )
                items.append(
                    QAAIHelperSessionListItemResponse(
                        session=self._serialize_session(session),
                        canonical_revision=self._serialize_canonical(canonical_revision),
                        planned_revision=self._serialize_planned(planned_revision),
                        draft_set=self._serialize_draft_set(draft_set),
                    )
                )
            return QAAIHelperSessionListResponse(
                items=items,
                total=total,
                limit=limit,
                offset=offset,
            )

        return await self._run_read(_list)

    async def get_workspace(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        return await self._run_read(
            lambda sync_db: self._load_workspace_sync(
                sync_db,
                team_id=team_id,
                session_id=session_id,
            )
        )

    async def delete_session(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperDeleteResponse:
        def _delete(sync_db: Session) -> QAAIHelperDeleteResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            sync_db.delete(session)
            return QAAIHelperDeleteResponse(deleted=True, session_id=session_id)

        return await self._run_write(_delete)

    async def restart_session(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperRestartResponse:
        def _restart(sync_db: Session) -> QAAIHelperRestartResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            if (
                session.status == QAAIHelperSessionStatus.COMPLETED.value
                or session.current_screen == QAAIHelperSessionScreen.COMMIT_RESULT.value
            ):
                raise ValueError("已完成的 session 不支援重新開始，請改用新的流程")
            sync_db.delete(session)
            return QAAIHelperRestartResponse(
                reset=True,
                session_id=session_id,
            )

        return await self._run_write(_restart)

    async def initialize_requirement_plan(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _initialize(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")

            ticket_snapshot = (
                sync_db.query(QAAIHelperTicketSnapshot)
                .filter(QAAIHelperTicketSnapshot.id == session.active_ticket_snapshot_id)
                .first()
                if session.active_ticket_snapshot_id
                else None
            )
            if ticket_snapshot is None:
                raise ValueError("找不到 ticket snapshot，請重新載入需求單")

            validation_summary = _json_storage_loads(ticket_snapshot.validation_summary_json, {})
            if not bool(validation_summary.get("is_valid")):
                raise ValueError("格式檢查未通過，暫時不能進入需求驗證項目分類與填充")

            requirement_plan = (
                sync_db.query(QAAIHelperRequirementPlan)
                .filter(QAAIHelperRequirementPlan.id == session.active_requirement_plan_id)
                .first()
                if session.active_requirement_plan_id
                else None
            )
            if requirement_plan is None or requirement_plan.status == QAAIHelperRequirementPlanStatus.SUPERSEDED.value:
                requirement_plan = self._create_requirement_plan_sync(
                    sync_db,
                    session=session,
                    ticket_snapshot=ticket_snapshot,
                )
                session.active_requirement_plan_id = requirement_plan.id

            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
                allow_same=True,
                force=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_initialize)

    async def save_requirement_plan(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperRequirementPlanSaveRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _save(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")

            ticket_snapshot = (
                sync_db.query(QAAIHelperTicketSnapshot)
                .filter(QAAIHelperTicketSnapshot.id == session.active_ticket_snapshot_id)
                .first()
                if session.active_ticket_snapshot_id
                else None
            )
            if ticket_snapshot is None:
                raise ValueError("找不到 ticket snapshot，請重新載入需求單")

            requirement_plan = (
                sync_db.query(QAAIHelperRequirementPlan)
                .filter(QAAIHelperRequirementPlan.id == session.active_requirement_plan_id)
                .first()
                if session.active_requirement_plan_id
                else None
            )
            if requirement_plan is None:
                requirement_plan = self._create_requirement_plan_sync(
                    sync_db,
                    session=session,
                    ticket_snapshot=ticket_snapshot,
                    section_start_number=request.section_start_number,
                )
                session.active_requirement_plan_id = requirement_plan.id

            if requirement_plan.status == QAAIHelperRequirementPlanStatus.LOCKED.value:
                raise ValueError("需求已鎖定，請先解開鎖定再編輯")

            self._replace_requirement_plan_sections_sync(
                sync_db,
                requirement_plan=requirement_plan,
                section_start_number=request.section_start_number,
                sections=[section.model_dump(mode="json") for section in request.sections],
            )
            validation_summary = self._validate_requirement_plan_payload(
                sections=requirement_plan.sections or [],
            )
            requirement_plan.status = QAAIHelperRequirementPlanStatus.DRAFT.value
            requirement_plan.locked_at = None
            requirement_plan.locked_by_user_id = None
            requirement_plan.autosave_summary_json = _json_storage_dumps(
                {
                    "mode": "autosave" if request.autosave else "manual",
                    "saved_at": _now().isoformat(),
                    "saved_by_user_id": user_id,
                    "section_count": validation_summary["stats"]["section_count"],
                    "verification_item_count": validation_summary["stats"]["verification_item_count"],
                    "check_condition_count": validation_summary["stats"]["check_condition_count"],
                    "error_count": len(validation_summary["errors"]),
                }
            )
            self._mark_active_seed_sets_superseded_sync(sync_db, session=session)
            self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)
            session.active_requirement_plan_id = requirement_plan.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
                allow_same=True,
                force=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_save)

    async def lock_requirement_plan(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _lock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            requirement_plan = (
                sync_db.query(QAAIHelperRequirementPlan)
                .filter(QAAIHelperRequirementPlan.id == session.active_requirement_plan_id)
                .first()
                if session.active_requirement_plan_id
                else None
            )
            if requirement_plan is None:
                raise ValueError("尚未建立需求驗證項目規劃")

            validation_summary = self._validate_requirement_plan_payload(
                sections=requirement_plan.sections or [],
            )
            if not validation_summary.get("is_valid"):
                first_messages = [
                    str(item.get("message") or item.get("code") or "").strip()
                    for item in (validation_summary.get("errors") or [])[:5]
                    if str(item.get("message") or item.get("code") or "").strip()
                ]
                raise ValueError(
                    "需求規劃尚未完成，無法鎖定："
                    + "；".join(first_messages or ["請補齊驗證項目與檢查條件"])
                )

            requirement_plan.status = QAAIHelperRequirementPlanStatus.LOCKED.value
            requirement_plan.locked_at = _now()
            requirement_plan.locked_by_user_id = user_id
            requirement_plan.updated_at = _now()
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_lock)

    async def unlock_requirement_plan(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _unlock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            requirement_plan = (
                sync_db.query(QAAIHelperRequirementPlan)
                .filter(QAAIHelperRequirementPlan.id == session.active_requirement_plan_id)
                .first()
                if session.active_requirement_plan_id
                else None
            )
            if requirement_plan is None:
                raise ValueError("尚未建立需求驗證項目規劃")

            requirement_plan.status = QAAIHelperRequirementPlanStatus.DRAFT.value
            requirement_plan.locked_at = None
            requirement_plan.locked_by_user_id = None
            requirement_plan.updated_at = _now()
            self._mark_active_seed_sets_superseded_sync(sync_db, session=session)
            self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.VERIFICATION_PLANNING.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_unlock)

    async def generate_seed_set(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        force_regenerate: bool = False,
    ) -> QAAIHelperWorkspaceResponse:
        read_snapshot = await self.get_workspace(team_id=team_id, session_id=session_id)
        requirement_plan = read_snapshot.requirement_plan
        if requirement_plan is None:
            raise ValueError("尚未建立 requirement plan")
        if requirement_plan.status != QAAIHelperRequirementPlanStatus.LOCKED:
            raise ValueError("需求尚未鎖定，無法產生 Test Case 種子")

        existing_seed_set = read_snapshot.seed_set
        if (
            existing_seed_set is not None
            and existing_seed_set.requirement_plan_id == requirement_plan.id
            and existing_seed_set.status
            in {
                QAAIHelperSeedSetStatus.DRAFT.value,
                QAAIHelperSeedSetStatus.LOCKED.value,
            }
            and not force_regenerate
        ):
            def _reuse(sync_db: Session) -> QAAIHelperWorkspaceResponse:
                session = (
                    sync_db.query(QAAIHelperSession)
                    .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                    .first()
                )
                if session is None:
                    raise ValueError("找不到 qa_ai_helper session")
                self._set_session_screen(
                    session,
                    QAAIHelperSessionScreen.SEED_REVIEW.value,
                    allow_same=True,
                )
                session.updated_at = _now()
                return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

            return await self._run_write(_reuse)

        generation_items = self._seed_generation_items_from_plan(requirement_plan)
        if not generation_items:
            raise ValueError("沒有可生成的驗證項目")

        output_locale = (
            read_snapshot.session.output_locale.value
            if hasattr(read_snapshot.session.output_locale, "value")
            else str(read_snapshot.session.output_locale)
        )
        prompt = self.prompt_service.render_stage_prompt(
            "seed",
            {
                "output_language": output_locale,
                "section_summary_json": _json_dumps(
                    self._seed_section_summary(requirement_plan)
                ),
                "requirement_plan_json": _json_dumps(
                    requirement_plan.model_dump(mode="json")
                ),
                "generation_items_json": _json_dumps(generation_items),
            },
        )
        llm_result = await self.llm_service.call_stage(
            stage="seed",
            prompt=prompt,
            max_tokens=max(1200, len(generation_items) * 220),
        )
        try:
            output_payload = json.loads(llm_result.content or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"seed 模型輸出非 JSON: {exc}") from exc
        model_outputs = output_payload.get("outputs") or []
        outputs_by_ref = {
            str(item.get("seed_reference_key") or "").strip(): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("seed_reference_key") or "").strip()
        }
        outputs_by_index = {
            int(item.get("item_index")): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("item_index") or "").strip().isdigit()
        }
        normalized_outputs = [
            self._normalize_seed_output(
                generation_item,
                outputs_by_ref.get(generation_item["seed_reference_key"])
                or outputs_by_index.get(generation_item["item_index"])
                or {},
            )
            for generation_item in generation_items
        ]

        def _persist(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            requirement_plan_row = (
                sync_db.query(QAAIHelperRequirementPlan)
                .filter(
                    QAAIHelperRequirementPlan.id == requirement_plan.id,
                    QAAIHelperRequirementPlan.session_id == session.id,
                )
                .first()
            )
            if requirement_plan_row is None:
                raise ValueError("找不到 requirement plan")
            if requirement_plan_row.status != QAAIHelperRequirementPlanStatus.LOCKED.value:
                raise ValueError("需求尚未鎖定，無法產生 Test Case 種子")

            self._mark_active_seed_sets_superseded_sync(sync_db, session=session)
            self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)

            latest_round = (
                sync_db.query(QAAIHelperSeedSet.generation_round)
                .filter(QAAIHelperSeedSet.session_id == session.id)
                .order_by(QAAIHelperSeedSet.generation_round.desc())
                .first()
            )
            seed_set = QAAIHelperSeedSet(
                session_id=session.id,
                requirement_plan_id=requirement_plan_row.id,
                status=QAAIHelperSeedSetStatus.DRAFT.value,
                generation_round=(latest_round[0] if latest_round and latest_round[0] is not None else 0)
                + 1,
                source_type="initial",
                model_name=llm_result.model_name,
                generated_seed_count=0,
                included_seed_count=0,
                adoption_rate=0.0,
                created_by_user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(seed_set)
            sync_db.flush()

            for generation_item, normalized_output in zip(generation_items, normalized_outputs):
                sync_db.add(
                    QAAIHelperSeedItem(
                        seed_set_id=seed_set.id,
                        plan_section_id=generation_item.get("plan_section_id"),
                        verification_item_id=generation_item.get("verification_item_id"),
                        check_condition_refs_json=_json_storage_dumps(
                            normalized_output.get("check_condition_ids") or []
                        ),
                        coverage_tags_json=_json_storage_dumps(
                            normalized_output.get("coverage_tags") or []
                        ),
                        seed_reference_key=normalized_output["seed_reference_key"],
                        seed_summary=normalized_output["seed_summary"],
                        seed_body_json=_json_storage_dumps(
                            {"text": normalized_output["seed_body"]}
                        ),
                        comment_text=None,
                        is_ai_generated=True,
                        user_edited=False,
                        included_for_testcase_generation=True,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
            sync_db.flush()
            sync_db.expire(seed_set, ["seed_items"])
            self._refresh_seed_adoption_summary_sync(seed_set)
            session.active_seed_set_id = seed_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.SEED_REVIEW.value,
                allow_same=True,
                force=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_persist)

    async def update_seed_item_review(
        self,
        *,
        team_id: int,
        session_id: int,
        seed_set_id: int,
        seed_item_id: int,
        request: QAAIHelperSeedItemReviewUpdateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == seed_set_id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            if seed_set.status == QAAIHelperSeedSetStatus.SUPERSEDED.value:
                raise ValueError("此 seed set 已失效")
            seed_item = (
                sync_db.query(QAAIHelperSeedItem)
                .filter(
                    QAAIHelperSeedItem.id == seed_item_id,
                    QAAIHelperSeedItem.seed_set_id == seed_set.id,
                )
                .first()
            )
            if seed_item is None:
                raise ValueError("找不到 seed item")

            changed = False
            if "included_for_testcase_generation" in request.model_fields_set:
                included = bool(request.included_for_testcase_generation)
                if seed_item.included_for_testcase_generation != included:
                    seed_item.included_for_testcase_generation = included
                    changed = True
            if "comment_text" in request.model_fields_set:
                comment_text = request.comment_text
                if (seed_item.comment_text or None) != comment_text:
                    seed_item.comment_text = comment_text
                    seed_item.user_edited = True
                    changed = True
            if changed:
                seed_item.updated_at = _now()
                self._mark_seed_review_dirty_sync(sync_db, session=session, seed_set=seed_set)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_update)

    async def update_seed_section_inclusion(
        self,
        *,
        team_id: int,
        session_id: int,
        seed_set_id: int,
        section_id: str,
        request: QAAIHelperSeedSectionInclusionRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == seed_set_id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            plan_section = (
                sync_db.query(QAAIHelperPlanSection)
                .filter(
                    QAAIHelperPlanSection.requirement_plan_id == seed_set.requirement_plan_id,
                    QAAIHelperPlanSection.section_id == section_id,
                )
                .first()
            )
            if plan_section is None:
                raise ValueError("找不到對應的 section")
            seed_items = (
                sync_db.query(QAAIHelperSeedItem)
                .filter(
                    QAAIHelperSeedItem.seed_set_id == seed_set.id,
                    QAAIHelperSeedItem.plan_section_id == plan_section.id,
                )
                .all()
            )
            changed = False
            for seed_item in seed_items:
                if seed_item.included_for_testcase_generation != request.included:
                    seed_item.included_for_testcase_generation = request.included
                    seed_item.updated_at = _now()
                    changed = True
            if changed:
                self._mark_seed_review_dirty_sync(sync_db, session=session, seed_set=seed_set)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_update)

    async def refine_seed_set(
        self,
        *,
        team_id: int,
        session_id: int,
        seed_set_id: int,
        request: QAAIHelperSeedRefineRequest,
    ) -> QAAIHelperWorkspaceResponse:
        if not request.items:
            raise ValueError("沒有可更新的 seed 註解")

        read_snapshot = await self.get_workspace(team_id=team_id, session_id=session_id)
        seed_set = read_snapshot.seed_set
        if seed_set is None or seed_set.id != seed_set_id:
            raise ValueError("找不到 seed set")
        if not seed_set.seed_items:
            raise ValueError("尚未產生任何 seed")

        dirty_by_id = {item.seed_item_id: item for item in request.items}
        current_seed_items = {item.id: item for item in seed_set.seed_items}
        missing_ids = [seed_item_id for seed_item_id in dirty_by_id if seed_item_id not in current_seed_items]
        if missing_ids:
            raise ValueError(f"找不到 seed item: {', '.join(str(item) for item in missing_ids)}")

        dirty_seed_items: List[Dict[str, Any]] = []
        dirty_comments: List[Dict[str, Any]] = []
        for item_index, seed_item_id in enumerate(dirty_by_id):
            seed_item = current_seed_items[seed_item_id]
            body = seed_item.seed_body or {}
            dirty_seed_items.append(
                {
                    "item_index": item_index,
                    "seed_item_id": seed_item.id,
                    "seed_reference_key": seed_item.seed_reference_key,
                    "section_id": seed_item.section_id,
                    "verification_item_ref": seed_item.verification_item_id,
                    "check_condition_ids": seed_item.check_condition_refs,
                    "coverage_tags": seed_item.coverage_tags,
                    "seed_summary": seed_item.seed_summary,
                    "seed_body": body.get("text") or json.dumps(body, ensure_ascii=False),
                }
            )
            dirty_comments.append(
                {
                    "seed_item_id": seed_item.id,
                    "seed_reference_key": seed_item.seed_reference_key,
                    "comment_text": dirty_by_id[seed_item_id].comment_text,
                }
            )

        output_locale = (
            read_snapshot.session.output_locale.value
            if hasattr(read_snapshot.session.output_locale, "value")
            else str(read_snapshot.session.output_locale)
        )
        prompt = self.prompt_service.render_stage_prompt(
            "seed_refine",
            {
                "output_language": output_locale,
                "seed_items_json": _json_dumps(dirty_seed_items),
                "seed_comments_json": _json_dumps(dirty_comments),
            },
        )
        llm_result = await self.llm_service.call_stage(
            stage="seed_refine",
            prompt=prompt,
            max_tokens=max(800, len(dirty_seed_items) * 220),
        )
        try:
            output_payload = json.loads(llm_result.content or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"seed refine 模型輸出非 JSON: {exc}") from exc
        model_outputs = output_payload.get("outputs") or []
        outputs_by_ref = {
            str(item.get("seed_reference_key") or "").strip(): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("seed_reference_key") or "").strip()
        }
        outputs_by_index = {
            int(item.get("item_index")): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("item_index") or "").strip().isdigit()
        }
        normalized_outputs = [
            self._normalize_seed_output(
                dirty_seed_item,
                outputs_by_ref.get(dirty_seed_item["seed_reference_key"])
                or outputs_by_index.get(dirty_seed_item["item_index"])
                or {},
            )
            for dirty_seed_item in dirty_seed_items
        ]

        def _persist(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set_row = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == seed_set_id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set_row is None:
                raise ValueError("找不到 seed set")

            for dirty_comment, normalized_output in zip(dirty_comments, normalized_outputs):
                seed_item = (
                    sync_db.query(QAAIHelperSeedItem)
                    .filter(
                        QAAIHelperSeedItem.id == dirty_comment["seed_item_id"],
                        QAAIHelperSeedItem.seed_set_id == seed_set_row.id,
                    )
                    .first()
                )
                if seed_item is None:
                    continue
                seed_item.comment_text = dirty_comment["comment_text"]
                seed_item.seed_summary = normalized_output["seed_summary"]
                seed_item.seed_body_json = _json_storage_dumps(
                    {"text": normalized_output["seed_body"]}
                )
                seed_item.coverage_tags_json = _json_storage_dumps(
                    normalized_output.get("coverage_tags") or []
                )
                seed_item.check_condition_refs_json = _json_storage_dumps(
                    normalized_output.get("check_condition_ids") or []
                )
                seed_item.user_edited = True
                seed_item.updated_at = _now()

            seed_set_row.model_name = llm_result.model_name or seed_set_row.model_name
            self._mark_seed_review_dirty_sync(sync_db, session=session, seed_set=seed_set_row)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_persist)

    async def lock_seed_set(
        self,
        *,
        team_id: int,
        session_id: int,
        seed_set_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _lock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == seed_set_id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            if seed_set.status == QAAIHelperSeedSetStatus.SUPERSEDED.value:
                raise ValueError("此 seed set 已失效")
            self._refresh_seed_adoption_summary_sync(seed_set)
            seed_set.status = QAAIHelperSeedSetStatus.LOCKED.value
            seed_set.updated_at = _now()
            session.active_seed_set_id = seed_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.SEED_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_lock)

    async def unlock_seed_set(
        self,
        *,
        team_id: int,
        session_id: int,
        seed_set_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _unlock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == seed_set_id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            if seed_set.status == QAAIHelperSeedSetStatus.SUPERSEDED.value:
                raise ValueError("此 seed set 已失效")
            seed_set.status = QAAIHelperSeedSetStatus.DRAFT.value
            seed_set.updated_at = _now()
            self._refresh_seed_adoption_summary_sync(seed_set)
            self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)
            session.active_seed_set_id = seed_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.SEED_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_unlock)

    async def generate_testcase_draft_set(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperTestcaseGenerateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        read_snapshot = await self.get_workspace(team_id=team_id, session_id=session_id)
        if read_snapshot.seed_set is None:
            raise ValueError("尚未產生 seed set")
        if read_snapshot.seed_set.status != QAAIHelperSeedSetStatus.LOCKED.value:
            raise ValueError("尚未鎖定 seed set，無法產生 testcase")
        if int(read_snapshot.seed_set.included_seed_count or 0) <= 0:
            raise ValueError("沒有可納入的 seed，無法產生 testcase")

        existing_draft_set = read_snapshot.testcase_draft_set
        if (
            existing_draft_set is not None
            and existing_draft_set.seed_set_id == read_snapshot.seed_set.id
            and existing_draft_set.status
            in {
                QAAIHelperTestcaseDraftSetStatus.DRAFT.value,
                QAAIHelperTestcaseDraftSetStatus.REVIEWING.value,
            }
            and not request.force_regenerate
        ):
            def _reuse(sync_db: Session) -> QAAIHelperWorkspaceResponse:
                session = (
                    sync_db.query(QAAIHelperSession)
                    .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                    .first()
                )
                if session is None:
                    raise ValueError("找不到 qa_ai_helper session")
                self._set_session_screen(
                    session,
                    QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                    allow_same=True,
                )
                session.updated_at = _now()
                return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

            return await self._run_write(_reuse)

        def _prepare_generation_items(sync_db: Session) -> List[Dict[str, Any]]:
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(QAAIHelperSeedSet.id == read_snapshot.seed_set.id)
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            return self._testcase_generation_items_from_seed_set(seed_set)

        generation_items = await self._run_read(_prepare_generation_items)
        if not generation_items:
            raise ValueError("沒有可生成的 testcase seeds")

        output_locale = (
            read_snapshot.session.output_locale.value
            if hasattr(read_snapshot.session.output_locale, "value")
            else str(read_snapshot.session.output_locale)
        )
        section_summary = {
            "ticket_key": read_snapshot.session.ticket_key,
            "seed_set_id": read_snapshot.seed_set.id,
            "section_count": len({item.get("section_id") for item in generation_items}),
        }
        prompt = self.prompt_service.render_stage_prompt(
            "testcase",
            {
                "output_language": output_locale,
                "min_steps": str(self.settings.ai.qa_ai_helper.min_steps),
                "min_preconditions": str(self.settings.ai.qa_ai_helper.min_preconditions),
                "section_summary_json": _json_dumps(section_summary),
                "shared_constraints_json": _json_dumps([]),
                "selected_references_json": _json_dumps([]),
                "generation_items_json": _json_dumps(generation_items),
            },
        )
        llm_result = await self.llm_service.call_stage(
            stage="testcase",
            prompt=prompt,
            max_tokens=max(1200, len(generation_items) * 260),
        )
        try:
            output_payload = json.loads(llm_result.content or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"testcase 模型輸出非 JSON: {exc}") from exc
        model_outputs = output_payload.get("outputs") or []
        outputs_by_ref = {
            str(item.get("seed_reference_key") or "").strip(): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("seed_reference_key") or "").strip()
        }
        outputs_by_index = {
            int(item.get("item_index")): item
            for item in model_outputs
            if isinstance(item, dict) and str(item.get("item_index") or "").strip().isdigit()
        }
        normalized_outputs = [
            self._normalize_testcase_output(
                generation_item,
                outputs_by_ref.get(generation_item["seed_reference_key"])
                or outputs_by_index.get(generation_item["item_index"])
                or {},
            )
            for generation_item in generation_items
        ]

        def _persist(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            seed_set = (
                sync_db.query(QAAIHelperSeedSet)
                .filter(
                    QAAIHelperSeedSet.id == read_snapshot.seed_set.id,
                    QAAIHelperSeedSet.session_id == session.id,
                )
                .first()
            )
            if seed_set is None:
                raise ValueError("找不到 seed set")
            if seed_set.status != QAAIHelperSeedSetStatus.LOCKED.value:
                raise ValueError("尚未鎖定 seed set，無法產生 testcase")

            self._mark_active_testcase_draft_sets_superseded_sync(sync_db, session=session)

            draft_set = QAAIHelperTestcaseDraftSet(
                session_id=session.id,
                seed_set_id=seed_set.id,
                status=QAAIHelperTestcaseDraftSetStatus.REVIEWING.value,
                model_name=llm_result.model_name,
                created_by_user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(draft_set)
            sync_db.flush()

            for generation_item, normalized_output in zip(generation_items, normalized_outputs):
                sync_db.add(
                    QAAIHelperTestcaseDraft(
                        testcase_draft_set_id=draft_set.id,
                        seed_item_id=generation_item["seed_item_id"],
                        seed_reference_key=generation_item["seed_reference_key"],
                        assigned_testcase_id=generation_item["assigned_testcase_id"],
                        body_json=_json_storage_dumps(
                            {
                                "title": normalized_output["title"],
                                "priority": normalized_output["priority"],
                                "preconditions": normalized_output["preconditions"],
                                "steps": normalized_output["steps"],
                                "expected_results": normalized_output["expected_results"],
                            }
                        ),
                        is_ai_generated=True,
                        user_edited=False,
                        selected_for_commit=False,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
            sync_db.flush()
            sync_db.expire(draft_set, ["drafts"])
            self._refresh_testcase_adoption_summary_sync(draft_set)
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_persist)

    async def update_testcase_draft(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
        draft_id: int,
        request: QAAIHelperTestcaseDraftUpdateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可編修")
            draft = (
                sync_db.query(QAAIHelperTestcaseDraft)
                .filter(
                    QAAIHelperTestcaseDraft.id == draft_id,
                    QAAIHelperTestcaseDraft.testcase_draft_set_id == draft_set.id,
                )
                .first()
            )
            if draft is None:
                raise ValueError("找不到 testcase draft")
            draft.body_json = _json_storage_dumps(request.body.model_dump())
            draft.user_edited = True
            draft.updated_at = _now()
            validation_summary = self._validate_testcase_draft_body(
                draft=draft,
                body=request.body.model_dump(),
            )
            if not validation_summary["is_valid"] and draft.selected_for_commit:
                draft.selected_for_commit = False
            draft_set.status = QAAIHelperTestcaseDraftSetStatus.REVIEWING.value
            self._refresh_testcase_adoption_summary_sync(draft_set)
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_update)

    async def update_testcase_draft_selection(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
        draft_id: int,
        request: QAAIHelperTestcaseDraftSelectionRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可編修")
            draft = (
                sync_db.query(QAAIHelperTestcaseDraft)
                .filter(
                    QAAIHelperTestcaseDraft.id == draft_id,
                    QAAIHelperTestcaseDraft.testcase_draft_set_id == draft_set.id,
                )
                .first()
            )
            if draft is None:
                raise ValueError("找不到 testcase draft")
            body = _json_storage_loads(draft.body_json, {})
            validation_summary = self._validate_testcase_draft_body(draft=draft, body=body)
            if request.selected_for_commit and not validation_summary["is_valid"]:
                first_error = (validation_summary["errors"] or [{}])[0]
                raise ValueError(str(first_error.get("message") or "此 testcase draft 尚未通過驗證"))
            draft.selected_for_commit = bool(request.selected_for_commit)
            draft.updated_at = _now()
            draft_set.status = QAAIHelperTestcaseDraftSetStatus.REVIEWING.value
            self._refresh_testcase_adoption_summary_sync(draft_set)
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_update)

    async def update_testcase_section_selection(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
        section_id: str,
        request: QAAIHelperTestcaseSectionSelectionRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可編修")

            changed = False
            for draft in draft_set.drafts or []:
                current_section_id = str(
                    getattr(getattr(getattr(draft, "seed_item", None), "plan_section", None), "section_id", "")
                ).strip()
                if current_section_id != section_id:
                    continue
                body = _json_storage_loads(draft.body_json, {})
                validation_summary = self._validate_testcase_draft_body(draft=draft, body=body)
                next_selected = bool(request.selected) and validation_summary["is_valid"]
                if draft.selected_for_commit != next_selected:
                    draft.selected_for_commit = next_selected
                    draft.updated_at = _now()
                    changed = True
            if changed:
                draft_set.status = QAAIHelperTestcaseDraftSetStatus.REVIEWING.value
                self._refresh_testcase_adoption_summary_sync(draft_set)
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_update)

    async def open_testcase_set_selection(
        self,
        *,
        team_id: int,
        session_id: int,
        request: QAAIHelperTestcaseSetSelectionRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _open(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == request.testcase_draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可進入畫面六")
            if int(draft_set.selected_for_commit_count or 0) <= 0:
                raise ValueError("至少需勾選一筆通過驗證的 testcase 才能進入畫面六")
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.SET_SELECTION.value,
                allow_same=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_open)

    async def return_to_testcase_review(
        self,
        *,
        team_id: int,
        session_id: int,
        request: QAAIHelperTestcaseSetSelectionRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _back(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == request.testcase_draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可返回畫面五")
            session.active_testcase_draft_set_id = draft_set.id
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.TESTCASE_REVIEW.value,
                allow_same=True,
                force=True,
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_back)

    async def commit_selected_testcases(
        self,
        *,
        team_id: int,
        session_id: int,
        request: QAAIHelperCommitRequest,
        user_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _commit(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperTestcaseDraftSet)
                .filter(
                    QAAIHelperTestcaseDraftSet.id == request.testcase_draft_set_id,
                    QAAIHelperTestcaseDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 testcase draft set")
            if draft_set.status in {
                QAAIHelperTestcaseDraftSetStatus.SUPERSEDED.value,
                QAAIHelperTestcaseDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 testcase draft set 狀態不可 commit")

            has_existing_target = request.target_test_case_set_id is not None
            has_new_target = request.new_test_case_set_payload is not None
            if has_existing_target == has_new_target:
                raise ValueError("target_test_case_set_id 與 new_test_case_set_payload 必須二選一")

            if has_existing_target:
                target_set = (
                    sync_db.query(TestCaseSet)
                    .filter(
                        TestCaseSet.id == request.target_test_case_set_id,
                        TestCaseSet.team_id == team_id,
                    )
                    .first()
                )
                if target_set is None:
                    raise ValueError("目標 Test Case Set 不存在")
            else:
                target_set = self._create_test_case_set_sync(
                    sync_db,
                    team_id=team_id,
                    payload=request.new_test_case_set_payload,
                )

            root_section = self._ensure_ai_helper_root_section_sync(sync_db, set_id=target_set.id)
            requested_ids: List[int] = list(dict.fromkeys(int(item) for item in request.selected_draft_ids))
            if not requested_ids:
                raise ValueError("至少需勾選一筆 testcase")

            draft_by_id = {
                int(draft.id): draft
                for draft in (draft_set.drafts or [])
            }
            draft_results: List[Dict[str, Any]] = []
            created_ids: List[str] = []
            created_count = 0
            failed_count = 0
            skipped_count = 0

            for draft_id in requested_ids:
                draft = draft_by_id.get(draft_id)
                if draft is None:
                    skipped_count += 1
                    draft_results.append(
                        {
                            "testcase_draft_id": int(draft_id),
                            "status": "skipped",
                            "reason": "找不到 testcase draft",
                        }
                    )
                    continue

                body = _json_storage_loads(draft.body_json, {})
                validation_summary = self._validate_testcase_draft_body(draft=draft, body=body)
                if not draft.selected_for_commit:
                    skipped_count += 1
                    draft_results.append(
                        {
                            "testcase_draft_id": draft.id,
                            "seed_item_id": draft.seed_item_id,
                            "seed_reference_key": draft.seed_reference_key,
                            "assigned_testcase_id": draft.assigned_testcase_id,
                            "status": "skipped",
                            "reason": "此 testcase draft 尚未勾選提交",
                        }
                    )
                    continue
                if not validation_summary["is_valid"]:
                    skipped_count += 1
                    first_error = (validation_summary.get("errors") or [{}])[0]
                    draft_results.append(
                        {
                            "testcase_draft_id": draft.id,
                            "seed_item_id": draft.seed_item_id,
                            "seed_reference_key": draft.seed_reference_key,
                            "assigned_testcase_id": draft.assigned_testcase_id,
                            "status": "skipped",
                            "reason": str(first_error.get("message") or "此 testcase draft 尚未通過驗證"),
                        }
                    )
                    continue
                if not draft.assigned_testcase_id or not draft.seed_reference_key or draft.seed_item is None:
                    skipped_count += 1
                    draft_results.append(
                        {
                            "testcase_draft_id": draft.id,
                            "seed_item_id": draft.seed_item_id,
                            "seed_reference_key": draft.seed_reference_key,
                            "assigned_testcase_id": draft.assigned_testcase_id,
                            "status": "skipped",
                            "reason": "testcase draft trace 不完整，無法 commit",
                        }
                    )
                    continue

                existing_case = (
                    sync_db.query(TestCaseLocal)
                    .filter(
                        TestCaseLocal.team_id == team_id,
                        TestCaseLocal.test_case_number == draft.assigned_testcase_id,
                    )
                    .first()
                )
                if existing_case is not None:
                    failed_count += 1
                    draft_results.append(
                        {
                            "testcase_draft_id": draft.id,
                            "seed_item_id": draft.seed_item_id,
                            "seed_reference_key": draft.seed_reference_key,
                            "assigned_testcase_id": draft.assigned_testcase_id,
                            "status": "failed",
                            "reason": f"Test Case 編號已存在: {draft.assigned_testcase_id}",
                            "test_case_id": existing_case.id,
                        }
                    )
                    continue

                plan_section = getattr(draft.seed_item, "plan_section", None)
                section_name = "Generated"
                if plan_section is not None:
                    section_name = f"{plan_section.section_id or ''} {plan_section.section_title or ''}".strip() or "Generated"
                commit_section = self._ensure_commit_section_sync(
                    sync_db,
                    set_id=target_set.id,
                    parent_section_id=root_section.id,
                    name=section_name,
                )
                test_case = TestCaseLocal(
                    team_id=team_id,
                    test_case_set_id=target_set.id,
                    test_case_section_id=commit_section.id,
                    test_case_number=draft.assigned_testcase_id,
                    title=body.get("title") or draft.assigned_testcase_id,
                    priority=_priority_from_text(body.get("priority") or "Medium"),
                    precondition=_join_lines(body.get("preconditions") or []),
                    steps=_join_lines(body.get("steps") or [], numbered=True),
                    expected_result=_join_lines(body.get("expected_results") or []),
                    tcg_json=_json_dumps([session.ticket_key] if session.ticket_key else []),
                    sync_status=SyncStatus.SYNCED,
                    created_at=_now(),
                    updated_at=_now(),
                )
                sync_db.add(test_case)
                sync_db.flush()
                sync_db.add(
                    QAAIHelperCommitLink(
                        session_id=session.id,
                        testcase_draft_set_id=draft_set.id,
                        testcase_draft_id=draft.id,
                        seed_item_id=draft.seed_item_id,
                        test_case_id=test_case.id,
                        test_case_set_id=target_set.id,
                        is_ai_generated=draft.is_ai_generated,
                        selected_for_commit=True,
                        committed_at=_now(),
                    )
                )
                created_count += 1
                created_ids.append(draft.assigned_testcase_id)
                draft_results.append(
                    {
                        "testcase_draft_id": draft.id,
                        "seed_item_id": draft.seed_item_id,
                        "seed_reference_key": draft.seed_reference_key,
                        "assigned_testcase_id": draft.assigned_testcase_id,
                        "status": "created",
                        "test_case_id": test_case.id,
                    }
                )

            draft_set.status = QAAIHelperTestcaseDraftSetStatus.COMMITTED.value
            draft_set.committed_at = _now()
            draft_set.updated_at = _now()
            session.active_testcase_draft_set_id = draft_set.id
            session.selected_target_test_case_set_id = target_set.id
            session.target_test_case_set_id = target_set.id
            session.status = QAAIHelperSessionStatus.COMPLETED.value
            self._set_session_screen(
                session,
                QAAIHelperSessionScreen.COMMIT_RESULT.value,
                allow_same=True,
                force=True,
            )
            session.updated_at = _now()

            result_payload = {
                "testcase_draft_set_id": draft_set.id,
                "target_test_case_set_id": target_set.id,
                "target_test_case_set_name": target_set.name,
                "created_count": created_count,
                "failed_count": failed_count,
                "skipped_count": skipped_count,
                "created_test_case_ids": created_ids,
                "draft_results": draft_results,
                "target_set_link": f"/test-case-management?set_id={target_set.id}&team_id={team_id}",
            }
            self._persist_telemetry_sync(
                sync_db,
                session=session,
                planned_revision_id=None,
                draft_set_id=None,
                user_id=user_id,
                stage="commit",
                event_name="result",
                status=(
                    QAAIHelperRunStatus.SUCCEEDED.value
                    if failed_count == 0 and skipped_count == 0
                    else QAAIHelperRunStatus.FAILED.value
                ),
                model_name=draft_set.model_name,
                usage={},
                duration_ms=0,
                payload=result_payload,
            )
            sync_db.flush()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_commit)

    async def fetch_ticket(
        self,
        *,
        team_id: int,
        session_id: int,
        request: QAAIHelperTicketFetchRequest,
    ) -> QAAIHelperWorkspaceResponse:
        ticket_key = request.ticket_key
        include_comments = request.include_comments

        def _prepare(sync_db: Session) -> Dict[str, Any]:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            resolved_ticket_key = (ticket_key or session.ticket_key or "").strip()
            if not resolved_ticket_key:
                raise ValueError("ticket_key 不可為空")
            return {
                "session_id": session.id,
                "ticket_key": resolved_ticket_key,
                "include_comments": session.include_comments if include_comments is None else include_comments,
            }

        prepared = await self._run_read(_prepare)
        jira_issue = self.jira_client_factory().get_issue(
            prepared["ticket_key"],
            fields=[
                "summary",
                "description",
                "comment",
            ],
        )
        if not jira_issue:
            raise RuntimeError(f"Jira 找不到 ticket: {prepared['ticket_key']}")

        fields = jira_issue.get("fields") or {}
        raw_comments = []
        if prepared["include_comments"]:
            for item in (fields.get("comment") or {}).get("comments", []):
                body = _coerce_jira_text(item.get("body"))
                if body.strip():
                    raw_comments.append(body.strip())
        raw_source_payload = self.planner.resolve_raw_sources(
            summary=_coerce_jira_text(fields.get("summary")),
            description=_coerce_jira_text(fields.get("description")),
            comments=raw_comments,
        )
        canonical_language = None

        def _save(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            session.ticket_key = prepared["ticket_key"]
            session.include_comments = bool(prepared["include_comments"])
            session.source_payload_json = _json_storage_dumps(raw_source_payload)
            if not session.canonical_language:
                languages = [key for key in raw_source_payload.get("language_variants", {}).keys() if key != "unknown"]
                canonical_language_local = "zh-TW" if "zh" in languages else "en"
                session.canonical_language = canonical_language_local
            suggested = self.planner.suggest_canonical_content(
                summary=raw_source_payload.get("summary", ""),
                description=raw_source_payload.get("description", ""),
                canonical_language=session.canonical_language,
                raw_source_metadata=raw_source_payload,
            )
            active_canonical = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
                .first()
                if session.active_canonical_revision_id
                else None
            )
            if active_canonical is None:
                revision = QAAIHelperCanonicalRevision(
                    session_id=session.id,
                    revision_number=1,
                    status=QAAIHelperCanonicalRevisionStatus.EDITABLE.value,
                    content_json=_json_storage_dumps(suggested),
                    canonical_language=session.canonical_language or "zh-TW",
                    counter_settings_json=_json_storage_dumps(
                        {"middle": "010", "tail": "010"}
                    ),
                    created_by_user_id=session.created_by_user_id,
                    created_at=_now(),
                    updated_at=_now(),
                )
                sync_db.add(revision)
                sync_db.flush()
                session.active_canonical_revision_id = revision.id
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_save)

    async def save_canonical_revision(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperCanonicalRevisionCreateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _save(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            previous_active = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
                .first()
                if session.active_canonical_revision_id
                else None
            )
            if previous_active is not None:
                previous_active.status = QAAIHelperCanonicalRevisionStatus.SUPERSEDED.value
                previous_active.updated_at = _now()

            revision_number = self._next_revision_number(
                sync_db,
                QAAIHelperCanonicalRevision,
                session.id,
            )
            revision = QAAIHelperCanonicalRevision(
                session_id=session.id,
                revision_number=revision_number,
                status=QAAIHelperCanonicalRevisionStatus.CONFIRMED.value,
                content_json=_json_storage_dumps(request.content.model_dump(by_alias=True)),
                canonical_language=request.canonical_language.value,
                counter_settings_json=_json_storage_dumps(request.counter_settings.model_dump()),
                created_by_user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(revision)
            sync_db.flush()
            session.canonical_language = request.canonical_language.value
            session.active_canonical_revision_id = revision.id
            session.current_phase = QAAIHelperPhase.INTAKE.value
            session.active_planned_revision_id = None
            session.active_draft_set_id = None
            session.updated_at = _now()
            for planned in (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(
                    QAAIHelperPlannedRevision.session_id == session.id,
                    QAAIHelperPlannedRevision.status != QAAIHelperPlannedRevisionStatus.STALE.value,
                )
                .all()
            ):
                planned.status = QAAIHelperPlannedRevisionStatus.STALE.value
                planned.updated_at = _now()
            self._mark_active_drafts_outdated_sync(sync_db, session_id=session.id)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_save)

    async def plan_session(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperPlanRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _plan(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            canonical_id = request.canonical_revision_id or session.active_canonical_revision_id
            if canonical_id is None:
                raise ValueError("尚未建立 canonical revision")
            canonical_revision = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(
                    QAAIHelperCanonicalRevision.id == canonical_id,
                    QAAIHelperCanonicalRevision.session_id == session.id,
                )
                .first()
            )
            if canonical_revision is None:
                raise ValueError("找不到 canonical revision")
            content = _json_storage_loads(canonical_revision.content_json, {})
            validation = self.planner.validate_canonical_content(content)
            if validation.get("missing_sections"):
                raise ValueError("canonical sections 尚未補齊，無法進入 planning")
            current_planned = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
                .first()
                if session.active_planned_revision_id
                else None
            )
            selected_references = (
                request.selected_references
                if request.selected_references is not None
                else _json_storage_loads(
                    current_planned.selected_references_json if current_planned else None,
                    {"section_references": {}},
                )
            )
            team_extensions = (
                [item.model_dump() for item in request.team_extensions]
                if request.team_extensions
                else _json_storage_loads(
                    current_planned.matrix_json if current_planned else None,
                    {},
                ).get("team_extensions", [])
            )
            applicability_overrides = _json_storage_loads(
                current_planned.applicability_overrides_json if current_planned else None,
                {},
            )
            counter_settings = (
                _json_storage_loads(current_planned.counter_settings_json, {})
                if current_planned is not None
                else _json_storage_loads(canonical_revision.counter_settings_json, {})
            )
            plan = self.planner.build_plan(
                ticket_key=session.ticket_key or "TCG-UNKNOWN",
                canonical_revision_id=canonical_revision.id,
                canonical_language=canonical_revision.canonical_language,
                content=content,
                counter_settings=counter_settings,
                applicability_overrides=applicability_overrides,
                selected_references=selected_references,
                team_extensions=team_extensions,
            )
            if current_planned is not None:
                current_planned.status = QAAIHelperPlannedRevisionStatus.STALE.value
                current_planned.updated_at = _now()
            revision = QAAIHelperPlannedRevision(
                session_id=session.id,
                canonical_revision_id=canonical_revision.id,
                revision_number=self._next_revision_number(sync_db, QAAIHelperPlannedRevision, session.id),
                status=QAAIHelperPlannedRevisionStatus.EDITABLE.value,
                matrix_json=self._persistable_plan_json(plan),
                seed_map_json=_json_storage_dumps({}),
                applicability_overrides_json=_json_storage_dumps(applicability_overrides),
                selected_references_json=_json_storage_dumps(selected_references),
                counter_settings_json=_json_storage_dumps(counter_settings),
                impact_summary_json=_json_storage_dumps(plan.get("impact_summary", {})),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(revision)
            sync_db.flush()
            session.active_planned_revision_id = revision.id
            session.active_draft_set_id = None
            session.current_phase = QAAIHelperPhase.PLANNED.value
            session.updated_at = _now()
            self._mark_active_drafts_outdated_sync(sync_db, session_id=session.id)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_plan)

    async def apply_planning_overrides(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperPlanningOverrideApplyRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _apply(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            current_planned = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
                .first()
                if session.active_planned_revision_id
                else None
            )
            if current_planned is None:
                raise ValueError("尚未建立 planned revision")
            canonical_revision = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(QAAIHelperCanonicalRevision.id == current_planned.canonical_revision_id)
                .first()
            )
            if canonical_revision is None:
                raise ValueError("找不到 canonical revision")
            content = _json_storage_loads(canonical_revision.content_json, {})
            overrides = _json_storage_loads(current_planned.applicability_overrides_json, {})
            for item in request.overrides:
                overrides[item.row_key] = {
                    "status": item.status.value,
                    "reason": item.reason,
                }
            selected_references = (
                request.selected_references
                if request.selected_references is not None
                else _json_storage_loads(current_planned.selected_references_json, {"section_references": {}})
            )
            team_extensions = (
                [item.model_dump() for item in request.team_extensions]
                if request.team_extensions
                else _json_storage_loads(current_planned.matrix_json, {}).get("team_extensions", [])
            )
            counter_settings = (
                request.counter_settings.model_dump()
                if request.counter_settings is not None
                else _json_storage_loads(current_planned.counter_settings_json, {})
            )
            plan = self.planner.build_plan(
                ticket_key=session.ticket_key or "TCG-UNKNOWN",
                canonical_revision_id=canonical_revision.id,
                canonical_language=canonical_revision.canonical_language,
                content=content,
                counter_settings=counter_settings,
                applicability_overrides=overrides,
                selected_references=selected_references,
                team_extensions=team_extensions,
                previous_plan=_json_storage_loads(current_planned.matrix_json, {}),
            )
            current_planned.status = QAAIHelperPlannedRevisionStatus.STALE.value
            current_planned.updated_at = _now()
            revision = QAAIHelperPlannedRevision(
                session_id=session.id,
                canonical_revision_id=canonical_revision.id,
                revision_number=self._next_revision_number(sync_db, QAAIHelperPlannedRevision, session.id),
                status=QAAIHelperPlannedRevisionStatus.EDITABLE.value,
                matrix_json=self._persistable_plan_json(plan),
                seed_map_json=_json_storage_dumps({}),
                applicability_overrides_json=_json_storage_dumps(overrides),
                selected_references_json=_json_storage_dumps(selected_references),
                counter_settings_json=_json_storage_dumps(counter_settings),
                impact_summary_json=_json_storage_dumps(plan.get("impact_summary", {})),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(revision)
            sync_db.flush()
            session.active_planned_revision_id = revision.id
            session.active_draft_set_id = None
            session.current_phase = QAAIHelperPhase.PLANNED.value
            session.updated_at = _now()
            self._mark_active_drafts_outdated_sync(sync_db, session_id=session.id)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_apply)

    async def apply_requirement_delta(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperRequirementDeltaCreateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _apply(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            current_canonical = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
                .first()
                if session.active_canonical_revision_id
                else None
            )
            current_planned = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
                .first()
                if session.active_planned_revision_id
                else None
            )
            if current_canonical is None:
                raise ValueError("尚未建立 canonical revision")
            current_content = _json_storage_loads(current_canonical.content_json, {})
            delta_payload = {
                "delta_type": request.delta_type.value,
                "target_scope": request.target_scope,
                "target_requirement_key": request.target_requirement_key,
                "target_scenario_key": request.target_scenario_key,
                "proposed_content": request.proposed_content,
                "reason": request.reason,
            }
            updated_content = self.planner.apply_requirement_delta(
                content=current_content,
                delta=delta_payload,
            )
            delta_impact = self.planner.analyze_requirement_delta_impact(
                previous_content=current_content,
                updated_content=updated_content,
                delta=delta_payload,
            )
            current_canonical.status = QAAIHelperCanonicalRevisionStatus.SUPERSEDED.value
            current_canonical.updated_at = _now()
            if current_planned is not None:
                current_planned.status = QAAIHelperPlannedRevisionStatus.STALE.value
                current_planned.updated_at = _now()
            revision = QAAIHelperCanonicalRevision(
                session_id=session.id,
                revision_number=self._next_revision_number(
                    sync_db,
                    QAAIHelperCanonicalRevision,
                    session.id,
                ),
                status=QAAIHelperCanonicalRevisionStatus.CONFIRMED.value,
                content_json=_json_storage_dumps(updated_content),
                canonical_language=current_canonical.canonical_language,
                counter_settings_json=current_canonical.counter_settings_json,
                created_by_user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(revision)
            sync_db.flush()
            delta_row = QAAIHelperRequirementDelta(
                session_id=session.id,
                source_canonical_revision_id=current_canonical.id,
                source_planned_revision_id=current_planned.id if current_planned else None,
                delta_type=request.delta_type.value,
                target_scope=request.target_scope,
                target_requirement_key=request.target_requirement_key,
                target_scenario_key=request.target_scenario_key,
                proposed_content_json=_json_storage_dumps(request.proposed_content),
                reason=request.reason,
                created_from_phase=QAAIHelperPhase.PLANNED.value,
                actor_user_id=user_id,
                applied_canonical_revision_id=revision.id,
                created_at=_now(),
                applied_at=_now(),
            )
            sync_db.add(delta_row)
            selected_references = _json_storage_loads(
                current_planned.selected_references_json if current_planned else None,
                {"section_references": {}},
            )
            compact_previous_plan = _json_storage_loads(
                current_planned.matrix_json if current_planned else None,
                {},
            )
            team_extensions = compact_previous_plan.get("team_extensions", [])
            applicability_overrides = _json_storage_loads(
                current_planned.applicability_overrides_json if current_planned else None,
                {},
            )
            counter_settings = _json_storage_loads(
                current_planned.counter_settings_json if current_planned else current_canonical.counter_settings_json,
                {},
            )
            previous_plan = (
                self.planner.build_plan(
                    ticket_key=session.ticket_key or "TCG-UNKNOWN",
                    canonical_revision_id=current_canonical.id,
                    canonical_language=current_canonical.canonical_language,
                    content=_json_storage_loads(current_canonical.content_json, {}),
                    counter_settings=counter_settings,
                    applicability_overrides=applicability_overrides,
                    selected_references=selected_references,
                    team_extensions=team_extensions,
                )
                if current_planned is not None
                else None
            )
            plan = self.planner.build_plan(
                ticket_key=session.ticket_key or "TCG-UNKNOWN",
                canonical_revision_id=revision.id,
                canonical_language=revision.canonical_language,
                content=updated_content,
                counter_settings=counter_settings,
                applicability_overrides=applicability_overrides,
                selected_references=selected_references,
                team_extensions=team_extensions,
                previous_plan=previous_plan,
                delta_impact=delta_impact,
            )
            planned_revision = QAAIHelperPlannedRevision(
                session_id=session.id,
                canonical_revision_id=revision.id,
                revision_number=self._next_revision_number(sync_db, QAAIHelperPlannedRevision, session.id),
                status=QAAIHelperPlannedRevisionStatus.EDITABLE.value,
                matrix_json=self._persistable_plan_json(plan),
                seed_map_json=_json_storage_dumps({}),
                applicability_overrides_json=_json_storage_dumps(applicability_overrides),
                selected_references_json=_json_storage_dumps(selected_references),
                counter_settings_json=_json_storage_dumps(counter_settings),
                impact_summary_json=_json_storage_dumps(plan.get("impact_summary", {})),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(planned_revision)
            sync_db.flush()
            session.active_canonical_revision_id = revision.id
            session.active_planned_revision_id = planned_revision.id
            session.active_draft_set_id = None
            session.current_phase = QAAIHelperPhase.PLANNED.value
            session.updated_at = _now()
            self._mark_active_drafts_outdated_sync(sync_db, session_id=session.id)
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_apply)

    async def lock_planning(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperPlanningLockRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _lock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            planned_revision = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(
                    QAAIHelperPlannedRevision.id == request.planned_revision_id,
                    QAAIHelperPlannedRevision.session_id == session.id,
                )
                .first()
            )
            if planned_revision is None:
                raise ValueError("找不到 planned revision")
            if planned_revision.status == QAAIHelperPlannedRevisionStatus.STALE.value:
                raise ValueError("此 planned revision 已失效，無法鎖定")
            planned_revision.status = QAAIHelperPlannedRevisionStatus.LOCKED.value
            planned_revision.locked_at = _now()
            planned_revision.locked_by_user_id = user_id
            planned_revision.updated_at = _now()
            session.active_planned_revision_id = planned_revision.id
            session.current_phase = QAAIHelperPhase.PLANNED.value
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_lock)

    async def unlock_planning(
        self,
        *,
        team_id: int,
        session_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _unlock(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            planned_revision = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == session.active_planned_revision_id)
                .first()
                if session.active_planned_revision_id
                else None
            )
            if planned_revision is None:
                raise ValueError("尚未建立 planned revision")
            if planned_revision.status == QAAIHelperPlannedRevisionStatus.STALE.value:
                raise ValueError("此 planned revision 已失效")
            planned_revision.status = QAAIHelperPlannedRevisionStatus.EDITABLE.value
            planned_revision.locked_at = None
            planned_revision.locked_by_user_id = None
            planned_revision.updated_at = _now()
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_unlock)

    def _iter_generation_batches(
        self,
        *,
        section: Dict[str, Any],
        requested_row_group_keys: set[str],
        force_one_seed: bool,
    ) -> List[Dict[str, Any]]:
        batches: List[Dict[str, Any]] = []
        items = section.get("generation_items", [])
        allowed_items = [
            item
            for item in items
            if not requested_row_group_keys or item.get("row_group_key") in requested_row_group_keys
        ]
        if not allowed_items:
            return []
        complexity = self.planner.compute_complexity(section)
        batch_mode = "one-seed-per-call" if force_one_seed else complexity["batch_mode"]
        if batch_mode == "section-batch":
            section_copy = deepcopy(section)
            section_copy["generation_items"] = allowed_items
            batches.append(section_copy)
            return batches
        if batch_mode == "row-group-batch":
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for item in allowed_items:
                groups.setdefault(str(item.get("row_group_key") or "baseline"), []).append(item)
            for group_items in groups.values():
                section_copy = deepcopy(section)
                section_copy["generation_items"] = group_items
                batches.append(section_copy)
            return batches
        for item in allowed_items:
            section_copy = deepcopy(section)
            section_copy["generation_items"] = [item]
            batches.append(section_copy)
        return batches

    async def generate_drafts(
        self,
        *,
        team_id: int,
        session_id: int,
        user_id: int,
        request: QAAIHelperGenerateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        read_snapshot = await self._run_read(
            lambda sync_db: self._load_workspace_sync(sync_db, team_id=team_id, session_id=session_id)
        )
        session = read_snapshot.session
        planned_revision = read_snapshot.planned_revision
        canonical_revision = read_snapshot.canonical_revision
        if planned_revision is None:
            raise ValueError("尚未建立 planned revision")
        if canonical_revision is None:
            raise ValueError("尚未建立 canonical revision")
        if planned_revision.status != QAAIHelperPlannedRevisionStatus.LOCKED:
            raise ValueError("尚未鎖定 planning revision，無法生成 testcase")
        existing_draft = read_snapshot.draft_set
        if existing_draft and existing_draft.status == QAAIHelperDraftSetStatus.ACTIVE:
            if not request.force_regenerate:
                return read_snapshot
            raise ValueError("此 locked revision 已有 active drafts，請先 discard 或建立新 lock")

        plan = self._rebuild_full_plan_from_workspace(
            session=session,
            canonical_revision=canonical_revision,
            planned_revision=planned_revision,
        )
        output_locale = (
            session.output_locale.value
            if hasattr(session.output_locale, "value")
            else str(session.output_locale)
        )
        sections = plan.get("sections") or []
        selected_section_ids = set(request.section_ids or [])
        row_group_keys = set(request.row_group_keys or [])
        candidate_sections = [
            section
            for section in sections
            if not selected_section_ids or section.get("section_id") in selected_section_ids
        ]
        if not candidate_sections:
            raise ValueError("沒有可生成的 section")
        incomplete_items = [
            item["item_key"]
            for section in candidate_sections
            for item in section.get("generation_items", [])
            if (not row_group_keys or item.get("row_group_key") in row_group_keys)
            and item.get("applicability") != QAAIHelperApplicabilityStatus.NOT_APPLICABLE
            and item.get("missing_required_facts")
        ]
        if incomplete_items:
            raise ValueError(
                "以下 generation items 缺少必要 hard facts，請先回 canonical/plan review 補齊："
                + ", ".join(incomplete_items)
            )

        row_limit = int(self.settings.ai.qa_ai_helper.generation_budget_row_limit)
        prompt_limit = int(self.settings.ai.qa_ai_helper.generation_budget_prompt_tokens)
        output_limit = int(self.settings.ai.qa_ai_helper.generation_budget_output_tokens)
        planned_row_count = 0
        estimated_prompt_tokens = 0
        estimated_output_tokens = 0
        for section in candidate_sections:
            batches = self._iter_generation_batches(
                section=section,
                requested_row_group_keys=row_group_keys,
                force_one_seed=False,
            )
            for batch in batches:
                planned_row_count += len(batch.get("generation_items", []))
                generation_budget = batch.get("generation_budget") or {}
                estimated_prompt_tokens += _safe_int(
                    generation_budget.get("estimated_prompt_tokens"),
                    len(json.dumps(batch, ensure_ascii=False)) // 4,
                )
                estimated_output_tokens += _safe_int(
                    generation_budget.get("estimated_output_tokens"),
                    max(1, len(batch.get("generation_items", [])) * 160),
                )
        if (
            planned_row_count > row_limit
            or estimated_prompt_tokens > prompt_limit
            or estimated_output_tokens > output_limit
        ) and not request.confirm_exhaustive:
            raise ValueError(
                f"本次生成超出 budget：rows={planned_row_count}, prompt_tokens={estimated_prompt_tokens}, output_tokens={estimated_output_tokens}"
            )

        all_merged_drafts: List[Dict[str, Any]] = []
        telemetry_records: List[Dict[str, Any]] = []
        model_name = None
        for section in candidate_sections:
            section_references = (
                ((planned_revision.selected_references or {}).get("section_references") or {}).get(
                    section["section_id"],
                    [],
                )
            )
            batches = self._iter_generation_batches(
                section=section,
                requested_row_group_keys=row_group_keys,
                force_one_seed=False,
            )
            for batch in batches:
                payload = self.planner.build_model_facing_payload(
                    ticket_key=session.ticket_key or "TCG-UNKNOWN",
                    output_language=output_locale,
                    section=batch,
                    section_references=section_references,
                )
                start_ts = time.perf_counter()
                prompt = self.prompt_service.render_stage_prompt(
                    "testcase",
                    {
                        "output_language": output_locale,
                        "min_steps": str(self.settings.ai.qa_ai_helper.min_steps),
                        "min_preconditions": str(
                            self.settings.ai.qa_ai_helper.min_preconditions
                        ),
                        "section_summary_json": _json_dumps(payload.get("section_summary", {})),
                        "shared_constraints_json": _json_dumps(payload.get("shared_constraints", [])),
                        "selected_references_json": _json_dumps(payload.get("selected_references", [])),
                        "generation_items_json": _json_dumps(payload.get("generation_items", [])),
                    },
                )
                llm_result: QAAIHelperLLMResult = await self.llm_service.call_stage(
                    stage="testcase",
                    prompt=prompt,
                    max_tokens=max(1000, len(payload.get("generation_items", [])) * 350),
                )
                duration_ms = int((time.perf_counter() - start_ts) * 1000)
                model_name = llm_result.model_name or model_name
                telemetry_records.append(
                    {
                        "stage": "testcase",
                        "event_name": "generate",
                        "status": QAAIHelperRunStatus.SUCCEEDED.value,
                        "model_name": llm_result.model_name,
                        "usage": llm_result.usage,
                        "duration_ms": duration_ms,
                        "payload": {
                            "section_id": section["section_id"],
                            "batch_size": len(batch.get("generation_items", [])),
                        },
                    }
                )
                try:
                    output_payload = json.loads(llm_result.content or "{}")
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"模型輸出非 JSON: {exc}") from exc
                merged_batch = post_merge_generation_outputs(
                    generation_items=batch.get("generation_items", []),
                    model_outputs=output_payload.get("outputs") or [],
                    selected_references=section_references,
                )
                all_merged_drafts.extend(merged_batch)

        expected_generation_items = [
            item
            for section in candidate_sections
            for item in section.get("generation_items", [])
            if not row_group_keys or item.get("row_group_key") in row_group_keys
        ]
        coverage_index = self._coverage_index_for_plan(plan)
        validation_summary = validate_merged_drafts(
            generation_items=expected_generation_items,
            merged_drafts=all_merged_drafts,
            min_preconditions=self.settings.ai.qa_ai_helper.min_preconditions,
            min_steps=self.settings.ai.qa_ai_helper.min_steps,
            coverage_index={
                key: value
                for key, value in coverage_index.items()
                if any(item_key in [item["item_key"] for item in expected_generation_items] for item_key in value)
            },
        )
        if (
            not validation_summary["ok"]
            and self.settings.ai.qa_ai_helper.max_repair_rounds > 0
            and self.settings.ai.qa_ai_helper.models.repair is not None
        ):
            repair_payload = build_repair_prompt_payload(
                merged_drafts=all_merged_drafts,
                validation_errors=validation_summary["errors"],
            )
            prompt = self.prompt_service.render_stage_prompt(
                "repair",
                {
                    "output_language": output_locale,
                    "min_steps": str(self.settings.ai.qa_ai_helper.min_steps),
                    "min_preconditions": str(self.settings.ai.qa_ai_helper.min_preconditions),
                    **repair_payload,
                },
            )
            start_ts = time.perf_counter()
            repair_result = await self.llm_service.call_stage(
                stage="repair",
                prompt=prompt,
                max_tokens=max(600, len(all_merged_drafts) * 200),
            )
            duration_ms = int((time.perf_counter() - start_ts) * 1000)
            telemetry_records.append(
                {
                    "stage": "repair",
                    "event_name": "repair",
                    "status": QAAIHelperRunStatus.SUCCEEDED.value,
                    "model_name": repair_result.model_name,
                    "usage": repair_result.usage,
                    "duration_ms": duration_ms,
                    "payload": {"draft_count": len(all_merged_drafts)},
                }
            )
            repair_outputs = json.loads(repair_result.content or "{}").get("outputs") or []
            repaired_map = {int(item.get("item_index", -1)): item for item in repair_outputs}
            invalid_keys = {
                str(error.get("item_key") or "")
                for error in validation_summary["errors"]
                if str(error.get("item_key") or "")
            }
            for merged_draft in all_merged_drafts:
                if merged_draft["item_key"] not in invalid_keys:
                    continue
                repair_index = list(sorted(invalid_keys)).index(merged_draft["item_key"])
                if repair_index in repaired_map:
                    merged_draft["body"] = repaired_map[repair_index]
            validation_summary = validate_merged_drafts(
                generation_items=expected_generation_items,
                merged_drafts=all_merged_drafts,
                min_preconditions=self.settings.ai.qa_ai_helper.min_preconditions,
                min_steps=self.settings.ai.qa_ai_helper.min_steps,
                coverage_index={
                    key: value
                    for key, value in coverage_index.items()
                    if any(item_key in [item["item_key"] for item in expected_generation_items] for item_key in value)
                },
            )

        def _save(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session_row = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session_row is None:
                raise ValueError("找不到 qa_ai_helper session")
            planned_revision_row = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == planned_revision.id)
                .first()
            )
            if planned_revision_row is None:
                raise ValueError("找不到 planned revision")
            draft_set = QAAIHelperDraftSet(
                session_id=session_row.id,
                planned_revision_id=planned_revision_row.id,
                status=QAAIHelperDraftSetStatus.ACTIVE.value
                if validation_summary["ok"]
                else QAAIHelperDraftSetStatus.ACTIVE.value,
                generation_mode="section-scoped",
                model_name=model_name,
                summary_json=_json_storage_dumps(validation_summary),
                created_by_user_id=user_id,
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(draft_set)
            sync_db.flush()
            for merged_draft in all_merged_drafts:
                sync_db.add(
                    QAAIHelperDraft(
                        draft_set_id=draft_set.id,
                        item_key=merged_draft["item_key"],
                        seed_id=merged_draft.get("seed_id"),
                        testcase_id=merged_draft.get("testcase_id"),
                        body_json=_json_storage_dumps(merged_draft.get("body", {})),
                        trace_json=_json_storage_dumps(merged_draft.get("trace", {})),
                        version=1,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
            validation_run = self._persist_validation_run_sync(
                sync_db,
                session=session_row,
                planned_revision_id=planned_revision_row.id,
                draft_set_id=draft_set.id,
                run_type="generation",
                status=QAAIHelperRunStatus.SUCCEEDED.value
                if validation_summary["ok"]
                else QAAIHelperRunStatus.FAILED.value,
                summary=validation_summary,
                errors=validation_summary["errors"],
                user_id=user_id,
            )
            for record in telemetry_records:
                self._persist_telemetry_sync(
                    sync_db,
                    session=session_row,
                    planned_revision_id=planned_revision_row.id,
                    draft_set_id=draft_set.id,
                    user_id=user_id,
                    stage=record["stage"],
                    event_name=record["event_name"],
                    status=record["status"],
                    model_name=record.get("model_name"),
                    usage=record.get("usage", {}),
                    duration_ms=record.get("duration_ms", 0),
                    payload=record.get("payload"),
                )
            session_row.active_draft_set_id = draft_set.id
            session_row.current_phase = (
                QAAIHelperPhase.VALIDATED.value
                if validation_summary["ok"]
                else QAAIHelperPhase.GENERATED.value
            )
            session_row.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session_id)

        return await self._run_write(_save)

    async def update_draft(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
        user_id: int,
        request: QAAIHelperDraftUpdateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _update(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperDraftSet)
                .filter(
                    QAAIHelperDraftSet.id == draft_set_id,
                    QAAIHelperDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 draft set")
            if draft_set.status != QAAIHelperDraftSetStatus.ACTIVE.value:
                raise ValueError("只有 active draft set 可以編修")
            draft = (
                sync_db.query(QAAIHelperDraft)
                .filter(
                    QAAIHelperDraft.draft_set_id == draft_set.id,
                    QAAIHelperDraft.item_key == request.item_key,
                )
                .first()
            )
            if draft is None:
                raise ValueError("找不到 draft item")
            draft.body_json = _json_storage_dumps(request.body.model_dump())
            draft.version += 1
            draft.updated_at = _now()

            planned_revision = (
                sync_db.query(QAAIHelperPlannedRevision)
                .filter(QAAIHelperPlannedRevision.id == draft_set.planned_revision_id)
                .first()
            )
            canonical_revision = (
                sync_db.query(QAAIHelperCanonicalRevision)
                .filter(
                    QAAIHelperCanonicalRevision.id == planned_revision.canonical_revision_id
                )
                .first()
                if planned_revision is not None
                else None
            )
            if planned_revision is None or canonical_revision is None:
                raise ValueError("找不到 planned revision")
            compact_plan = _json_storage_loads(planned_revision.matrix_json, {})
            plan = self.planner.build_plan(
                ticket_key=session.ticket_key or "TCG-UNKNOWN",
                canonical_revision_id=canonical_revision.id,
                canonical_language=canonical_revision.canonical_language,
                content=_json_storage_loads(canonical_revision.content_json, {}),
                counter_settings=_json_storage_loads(planned_revision.counter_settings_json, {}),
                applicability_overrides=_json_storage_loads(planned_revision.applicability_overrides_json, {}),
                selected_references=_json_storage_loads(
                    planned_revision.selected_references_json,
                    {"section_references": {}},
                ),
                team_extensions=compact_plan.get("team_extensions", []),
            )
            sections = plan.get("sections") or []
            generation_items = [
                item
                for section in sections
                for item in (section.get("generation_items") or [])
            ]
            merged_drafts = []
            for item in draft_set.drafts:
                body = _json_storage_loads(item.body_json, {})
                trace = _json_storage_loads(item.trace_json, {})
                merged_drafts.append(
                    {
                        "item_key": item.item_key,
                        "body": body,
                        "trace": trace,
                    }
                )
            validation_summary = validate_merged_drafts(
                generation_items=generation_items,
                merged_drafts=merged_drafts,
                min_preconditions=self.settings.ai.qa_ai_helper.min_preconditions,
                min_steps=self.settings.ai.qa_ai_helper.min_steps,
                coverage_index=self._coverage_index_for_plan(plan),
            )
            draft_set.summary_json = _json_storage_dumps(validation_summary)
            draft_set.updated_at = _now()
            validation_run = self._persist_validation_run_sync(
                sync_db,
                session=session,
                planned_revision_id=planned_revision.id if planned_revision else draft_set.planned_revision_id,
                draft_set_id=draft_set.id,
                run_type="recheck",
                status=QAAIHelperRunStatus.SUCCEEDED.value
                if validation_summary["ok"]
                else QAAIHelperRunStatus.FAILED.value,
                summary=validation_summary,
                errors=validation_summary["errors"],
                user_id=user_id,
            )
            session.current_phase = (
                QAAIHelperPhase.VALIDATED.value
                if validation_summary["ok"]
                else QAAIHelperPhase.GENERATED.value
            )
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session_id)

        return await self._run_write(_update)

    async def discard_draft_set(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
    ) -> QAAIHelperWorkspaceResponse:
        def _discard(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperDraftSet)
                .filter(
                    QAAIHelperDraftSet.id == draft_set_id,
                    QAAIHelperDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 draft set")
            draft_set.status = QAAIHelperDraftSetStatus.DISCARDED.value
            draft_set.updated_at = _now()
            if session.active_draft_set_id == draft_set.id:
                session.active_draft_set_id = None
            session.current_phase = QAAIHelperPhase.PLANNED.value
            session.updated_at = _now()
            return self._load_workspace_sync(sync_db, team_id=team_id, session_id=session.id)

        return await self._run_write(_discard)

    async def commit_draft_set(
        self,
        *,
        team_id: int,
        session_id: int,
        draft_set_id: int,
    ) -> QAAIHelperCommitResponse:
        def _commit(sync_db: Session) -> QAAIHelperCommitResponse:
            session = (
                sync_db.query(QAAIHelperSession)
                .filter(QAAIHelperSession.id == session_id, QAAIHelperSession.team_id == team_id)
                .first()
            )
            if session is None:
                raise ValueError("找不到 qa_ai_helper session")
            draft_set = (
                sync_db.query(QAAIHelperDraftSet)
                .filter(
                    QAAIHelperDraftSet.id == draft_set_id,
                    QAAIHelperDraftSet.session_id == session.id,
                )
                .first()
            )
            if draft_set is None:
                raise ValueError("找不到 draft set")
            if draft_set.status in {
                QAAIHelperDraftSetStatus.OUTDATED.value,
                QAAIHelperDraftSetStatus.DISCARDED.value,
                QAAIHelperDraftSetStatus.COMMITTED.value,
            }:
                raise ValueError("此 draft set 狀態不可 commit")
            target_set = (
                sync_db.query(TestCaseSet)
                .filter(
                    TestCaseSet.id == session.target_test_case_set_id,
                    TestCaseSet.team_id == team_id,
                )
                .first()
            )
            if target_set is None:
                raise ValueError("目標 Test Case Set 不存在")
            root_section = self._ensure_ai_helper_root_section_sync(sync_db, set_id=target_set.id)
            created_count = 0
            updated_count = 0
            for draft in draft_set.drafts:
                body = _json_storage_loads(draft.body_json, {})
                trace = _json_storage_loads(draft.trace_json, {})
                section_name = f"{trace.get('section_id', '')} {trace.get('scenario_title', 'Generated')}".strip()
                section = self._ensure_commit_section_sync(
                    sync_db,
                    set_id=target_set.id,
                    parent_section_id=root_section.id,
                    name=section_name,
                )
                existing_case = (
                    sync_db.query(TestCaseLocal)
                    .filter(
                        TestCaseLocal.team_id == team_id,
                        TestCaseLocal.test_case_number == draft.testcase_id,
                    )
                    .first()
                )
                if existing_case is None:
                    existing_case = TestCaseLocal(
                        team_id=team_id,
                        test_case_set_id=target_set.id,
                        test_case_section_id=section.id,
                        test_case_number=draft.testcase_id,
                        title=body.get("title") or draft.testcase_id,
                        priority=_priority_from_text(body.get("priority") or "Medium"),
                        precondition=_join_lines(body.get("preconditions") or []),
                        steps=_join_lines(body.get("steps") or [], numbered=True),
                        expected_result=_join_lines(body.get("expected_results") or []),
                        tcg_json=_json_dumps([session.ticket_key] if session.ticket_key else []),
                        sync_status=SyncStatus.SYNCED,
                        created_at=_now(),
                        updated_at=_now(),
                    )
                    sync_db.add(existing_case)
                    created_count += 1
                else:
                    existing_case.test_case_set_id = target_set.id
                    existing_case.test_case_section_id = section.id
                    existing_case.title = body.get("title") or existing_case.title
                    existing_case.priority = _priority_from_text(body.get("priority") or "Medium")
                    existing_case.precondition = _join_lines(body.get("preconditions") or [])
                    existing_case.steps = _join_lines(body.get("steps") or [], numbered=True)
                    existing_case.expected_result = _join_lines(body.get("expected_results") or [])
                    existing_case.tcg_json = _json_dumps([session.ticket_key] if session.ticket_key else [])
                    existing_case.sync_status = SyncStatus.SYNCED
                    existing_case.updated_at = _now()
                    updated_count += 1
            draft_set.status = QAAIHelperDraftSetStatus.COMMITTED.value
            draft_set.committed_at = _now()
            draft_set.updated_at = _now()
            session.current_phase = QAAIHelperPhase.COMMITTED.value
            session.status = QAAIHelperSessionStatus.COMPLETED.value
            session.updated_at = _now()
            return QAAIHelperCommitResponse(
                created_count=created_count,
                updated_count=updated_count,
                committed_draft_set_id=draft_set.id,
            )

        return await self._run_write(_commit)
