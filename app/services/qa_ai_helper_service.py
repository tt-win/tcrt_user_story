"""Service layer for the rewritten QA AI Helper."""

from __future__ import annotations

import json
import logging
import time
import base64
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
    QAAIHelperDraft,
    QAAIHelperDraftSet,
    QAAIHelperPlannedRevision,
    QAAIHelperRequirementDelta,
    QAAIHelperSession,
    QAAIHelperTelemetryEvent,
    QAAIHelperValidationRun,
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
    QAAIHelperRequirementDeltaCreateRequest,
    QAAIHelperRequirementDeltaType,
    QAAIHelperRunStatus,
    QAAIHelperSessionCreateRequest,
    QAAIHelperSessionListItemResponse,
    QAAIHelperSessionListResponse,
    QAAIHelperSessionResponse,
    QAAIHelperSessionStatus,
    QAAIHelperTicketFetchRequest,
    QAAIHelperWorkspaceResponse,
)
from app.services.jira_client import JiraClient
from app.services.qa_ai_helper_llm_service import (
    QAAIHelperLLMResult,
    get_qa_ai_helper_llm_service,
)
from app.services.qa_ai_helper_planner import QAAIHelperPlanner
from app.services.qa_ai_helper_prompt_service import get_qa_ai_helper_prompt_service
from app.services.qa_ai_helper_runtime import (
    build_repair_prompt_payload,
    post_merge_generation_outputs,
    validate_merged_drafts,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
_DB_JSON_ZLIB_PREFIX = "__qa_ai_helper_zlib__:"
_DB_JSON_COMPRESS_THRESHOLD = 32 * 1024


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
                "ticket_key": session.ticket_key,
                "include_comments": session.include_comments,
                "output_locale": session.output_locale,
                "canonical_language": session.canonical_language,
                "current_phase": session.current_phase,
                "status": session.status,
                "active_canonical_revision_id": session.active_canonical_revision_id,
                "active_planned_revision_id": session.active_planned_revision_id,
                "active_draft_set_id": session.active_draft_set_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            }
        )

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

    def _build_workspace_response(
        self,
        session: QAAIHelperSession,
        canonical_revision: Optional[QAAIHelperCanonicalRevision],
        planned_revision: Optional[QAAIHelperPlannedRevision],
        draft_set: Optional[QAAIHelperDraftSet],
        latest_validation_run: Optional[QAAIHelperValidationRun],
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
            source_payload=_json_storage_loads(session.source_payload_json, {}),
            canonical_validation=canonical_validation,
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
        latest_validation_run = (
            sync_db.query(QAAIHelperValidationRun)
            .filter(QAAIHelperValidationRun.session_id == session.id)
            .order_by(QAAIHelperValidationRun.id.desc())
            .first()
        )
        return self._build_workspace_response(
            session,
            canonical_revision,
            planned_revision,
            draft_set,
            latest_validation_run,
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

    async def start_session(
        self,
        *,
        team_id: int,
        user_id: int,
        request: QAAIHelperSessionCreateRequest,
    ) -> QAAIHelperWorkspaceResponse:
        def _create(sync_db: Session) -> QAAIHelperWorkspaceResponse:
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if team is None:
                raise ValueError(f"找不到 Team {team_id}")
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

            session = QAAIHelperSession(
                team_id=team_id,
                created_by_user_id=user_id,
                target_test_case_set_id=request.target_test_case_set_id,
                ticket_key=request.ticket_key,
                include_comments=request.include_comments,
                output_locale=request.output_locale.value,
                canonical_language=(
                    request.canonical_language.value
                    if request.canonical_language is not None
                    else None
                ),
                current_phase=QAAIHelperPhase.INTAKE.value,
                status=QAAIHelperSessionStatus.ACTIVE.value,
                source_payload_json=_json_storage_dumps({}),
                created_at=_now(),
                updated_at=_now(),
            )
            sync_db.add(session)
            sync_db.flush()
            return self._build_workspace_response(session, None, None, None, None)

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
            return self._build_workspace_response(
                session_row,
                (
                    sync_db.query(QAAIHelperCanonicalRevision)
                    .filter(QAAIHelperCanonicalRevision.id == session_row.active_canonical_revision_id)
                    .first()
                ),
                planned_revision_row,
                draft_set,
                validation_run,
            )

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
            return self._build_workspace_response(
                session,
                (
                    sync_db.query(QAAIHelperCanonicalRevision)
                    .filter(QAAIHelperCanonicalRevision.id == session.active_canonical_revision_id)
                    .first()
                ),
                planned_revision,
                draft_set,
                validation_run,
            )

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
