"""App token test case mutation API - /api/app/teams/{team_id}/test-cases."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.test_cases import (
    BulkCloneRequest,
    _delete_attachment_common,
    resolve_test_case_record,
    run_bulk_clone_sync,
    run_test_case_batch_operation_sync,
)
from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.audit import ActionType
from app.config import PROJECT_ROOT
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import AppTokenPrincipal, SCOPE_TEST_CASE_ADMIN, SCOPE_TEST_CASE_WRITE
from app.models.app_token import SCOPE_TEST_RUN_READ
from app.services.knowledge.hooks import (
    enqueue_test_case_sync,
    enqueue_test_cases_bulk,
)
from app.models.database_models import (
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSection as TestCaseSectionDB,
    TestCaseSet as TestCaseSetDB,
)
from app.models.lark_types import Priority
from app.models.test_case import (
    TestCaseBatchOperation,
    TestCaseCreate,
    TestCaseUpdate,
    normalize_test_data_items,
    redact_credential_test_data,
)
from app.models.test_case_set import (
    TestCaseSectionCreate,
    TestCaseSectionUpdate,
    TestCaseSetCreate,
    TestCaseSetUpdate,
)
from app.services.attachment_storage import (
    build_attachment_metadata,
    ensure_within_root,
    get_attachments_root_dir,
)
from app.services.test_case_section_service import TestCaseSectionService
from app.services.test_case_set_service import TestCaseSetService
from app.services.test_run_scope_service import TestRunScopeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app-test-case-mutations"])


class AppTestCaseMovePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_ids: List[str] = Field(..., min_length=1, max_length=100)
    target_test_set_id: int = Field(..., gt=0)

    @field_validator("record_ids")
    @classmethod
    def normalize_record_ids(cls, value: List[str]) -> List[str]:
        normalized = []
        seen = set()
        for raw in value:
            record_id = str(raw).strip()
            if not record_id:
                raise ValueError("record_ids cannot contain blank values")
            if record_id not in seen:
                seen.add(record_id)
                normalized.append(record_id)
        return normalized


class AppTestCaseMoveRequest(AppTestCaseMovePreviewRequest):
    impact_fingerprint: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    target_section_id: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_single_target_section(self):
        if self.target_section_id is not None and len(self.record_ids) != 1:
            raise ValueError("target_section_id is only valid for a single-case move")
        return self


class AppTestCaseMoveImpactChanged(Exception):
    def __init__(self, preview: Dict[str, Any]):
        self.preview = preview
        super().__init__("Test Case move impact changed; preview and confirm again")


def _serialize_test_case(tc: TestCaseLocalDB) -> Dict[str, Any]:
    # test_data 的 credential value 一律遮蔽：partial update（未帶 test_data）的回應會帶出
    # 既有項目，否則只有 test_case:write 的 token 能藉 no-op PUT 讀到明文。
    return {
        "id": tc.id,
        "team_id": tc.team_id,
        "test_case_number": tc.test_case_number,
        "title": tc.title,
        "priority": tc.priority.value if hasattr(tc.priority, "value") else str(tc.priority),
        "precondition": tc.precondition,
        "steps": tc.steps,
        "expected_result": tc.expected_result,
        "test_result": tc.test_result.value if hasattr(tc.test_result, "value") else str(tc.test_result) if tc.test_result else None,
        "test_case_set_id": tc.test_case_set_id,
        "test_case_section_id": tc.test_case_section_id,
        "tcg": json.loads(tc.tcg_json) if tc.tcg_json else [],
        "test_data": redact_credential_test_data(
            json.loads(tc.test_data_json) if tc.test_data_json else []
        ),
    }


async def _audit_mutation(
    request: Request,
    principal: AppTokenPrincipal,
    action_type: ActionType,
    team_id: int,
    resource_id: str,
    details: Dict[str, Any],
) -> None:
    redacted = {k: v for k, v in details.items()}
    if "test_data" in redacted:
        redacted["test_data"] = redact_credential_test_data(redacted["test_data"])
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason=f"test_case_{action_type.value.lower()}",
        action_type=action_type,
        team_id=team_id,
        extra_details=redacted,
    )


async def _require_case_move_scopes(
    request: Request,
    principal: AppTokenPrincipal,
    team_id: int,
) -> None:
    for scope in (SCOPE_TEST_CASE_WRITE, SCOPE_TEST_RUN_READ):
        if principal.has_scope(scope):
            continue
        await log_app_token_audit(
            request,
            principal,
            allowed=False,
            reason=f"scope_denied:{scope}",
            team_id=team_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": f"Missing {scope} scope"},
        )


def _app_validation_error(message: str, *, status_code: int = 400, code: str | None = None):
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code or AppTokenErrorCodes.VALIDATION_ERROR,
            "message": message,
        },
    )


def _resolve_case_move_records(
    sync_db: Session,
    team_id: int,
    record_ids: List[str],
    *,
    lock: bool = False,
) -> List[TestCaseLocalDB]:
    resolved = []
    for record_id in record_ids:
        item = resolve_test_case_record(sync_db, team_id, record_id)
        if item is None:
            raise _app_validation_error(f"Test case {record_id} does not exist in team {team_id}")
        resolved.append(item)
    if not lock:
        return resolved
    ids = sorted({item.id for item in resolved})
    locked = (
        sync_db.query(TestCaseLocalDB)
        .filter(TestCaseLocalDB.team_id == team_id, TestCaseLocalDB.id.in_(ids))
        .order_by(TestCaseLocalDB.id.asc())
        .with_for_update()
        .all()
    )
    if len(locked) != len(ids):
        raise _app_validation_error("Test Case selection changed before mutation")
    return locked


def _get_or_create_root_unassigned(
    sync_db: Session,
    team_id: int,
    target_set_id: int,
) -> TestCaseSectionDB:
    target_set = (
        sync_db.query(TestCaseSetDB)
        .filter(TestCaseSetDB.id == target_set_id, TestCaseSetDB.team_id == team_id)
        .with_for_update()
        .first()
    )
    if target_set is None:
        raise _app_validation_error(f"Test Case Set {target_set_id} does not exist in team {team_id}")
    roots = (
        sync_db.query(TestCaseSectionDB)
        .filter(
            TestCaseSectionDB.test_case_set_id == target_set_id,
            TestCaseSectionDB.parent_section_id.is_(None),
            TestCaseSectionDB.name == "Unassigned",
        )
        .order_by(TestCaseSectionDB.id.asc())
        .with_for_update()
        .all()
    )
    if len(roots) > 1:
        raise _app_validation_error(
            "Target Set has multiple root Unassigned sections",
            status_code=status.HTTP_409_CONFLICT,
            code=AppTokenErrorCodes.INTEGRITY_CONFLICT,
        )
    if roots:
        return roots[0]
    section = TestCaseSectionDB(
        test_case_set_id=target_set_id,
        name="Unassigned",
        description="",
        level=1,
        sort_order=0,
    )
    sync_db.add(section)
    sync_db.flush()
    return section


@router.post("/teams/{team_id}/test-cases/impact-preview/move-test-set")
async def preview_app_test_case_set_move(
    team_id: int,
    body: AppTestCaseMovePreviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Preview the exact Run Item impact and return a guarded-move fingerprint."""
    await require_app_team_access(team_id, request, principal)
    await _require_case_move_scopes(request, principal, team_id)
    boundary = create_main_access_boundary_for_session(db)

    def _preview(sync_db: Session):
        target = sync_db.query(TestCaseSetDB).filter(
            TestCaseSetDB.id == body.target_test_set_id,
            TestCaseSetDB.team_id == team_id,
        ).first()
        if target is None:
            raise _app_validation_error(
                f"Test Case Set {body.target_test_set_id} does not exist in team {team_id}"
            )
        cases = _resolve_case_move_records(sync_db, team_id, body.record_ids)
        return TestRunScopeService.build_guarded_case_move_preview(
            sync_db,
            team_id,
            cases,
            body.target_test_set_id,
        )

    preview = await boundary.run_sync_read(_preview)
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason="test_case_move_preview",
        action_type=ActionType.READ,
        team_id=team_id,
        extra_details={
            "case_ids": preview["case_ids"],
            "target_test_case_set_id": body.target_test_set_id,
            "impact_fingerprint": preview["impact_fingerprint"],
            "impacted_item_count": preview["impacted_item_count"],
        },
    )
    return preview


@router.post("/teams/{team_id}/test-cases/move-test-set")
async def move_app_test_cases_to_set(
    team_id: int,
    body: AppTestCaseMoveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Atomically move cases only when the confirmed impact fingerprint still matches."""
    await require_app_team_access(team_id, request, principal)
    await _require_case_move_scopes(request, principal, team_id)
    boundary = create_main_access_boundary_for_session(db)

    def _move(sync_db: Session):
        TestRunScopeService.lock_scope_mutation(sync_db, team_id)
        target = (
            sync_db.query(TestCaseSetDB)
            .filter(
                TestCaseSetDB.id == body.target_test_set_id,
                TestCaseSetDB.team_id == team_id,
            )
            .with_for_update()
            .first()
        )
        if target is None:
            raise _app_validation_error(
                f"Test Case Set {body.target_test_set_id} does not exist in team {team_id}"
            )
        cases = _resolve_case_move_records(sync_db, team_id, body.record_ids, lock=True)
        current_preview = TestRunScopeService.build_guarded_case_move_preview(
            sync_db,
            team_id,
            cases,
            body.target_test_set_id,
            lock=True,
        )
        if current_preview["impact_fingerprint"] != body.impact_fingerprint:
            raise AppTestCaseMoveImpactChanged(current_preview)

        changed_cases = [
            case for case in cases if case.test_case_set_id != body.target_test_set_id
        ]
        if body.target_section_id is not None:
            target_section = (
                sync_db.query(TestCaseSectionDB)
                .filter(
                    TestCaseSectionDB.id == body.target_section_id,
                    TestCaseSectionDB.test_case_set_id == body.target_test_set_id,
                )
                .with_for_update()
                .first()
            )
            if target_section is None:
                raise _app_validation_error(
                    f"Section {body.target_section_id} does not belong to target Set"
                )
        elif changed_cases:
            target_section = _get_or_create_root_unassigned(
                sync_db, team_id, body.target_test_set_id
            )
        else:
            target_section = None

        placements = []
        moved_numbers = []
        for case in cases:
            previous_set_id = case.test_case_set_id
            previous_section_id = case.test_case_section_id
            changed = previous_set_id != body.target_test_set_id
            if changed:
                case.test_case_set_id = body.target_test_set_id
                case.test_case_section_id = target_section.id
                moved_numbers.append(case.test_case_number)
            placements.append(
                {
                    "case_id": case.id,
                    "previous_test_case_set_id": previous_set_id,
                    "previous_section_id": previous_section_id,
                    "target_test_case_set_id": case.test_case_set_id,
                    "target_section_id": case.test_case_section_id,
                    "changed": changed,
                }
            )

        cleanup_summary = TestRunScopeService.cleanup_case_move(
            sync_db,
            team_id=team_id,
            case_numbers=moved_numbers,
            target_set_id=body.target_test_set_id,
        )
        sync_db.flush()
        moved_count = len(moved_numbers)
        return {
            "success": True,
            "processed_count": len(cases),
            "moved_count": moved_count,
            "unchanged_count": len(cases) - moved_count,
            "case_ids": [case.id for case in cases],
            "case_numbers": [case.test_case_number for case in cases],
            "target_test_case_set_id": body.target_test_set_id,
            "placements": placements,
            "cleanup_summary": cleanup_summary,
            "impact_fingerprint": body.impact_fingerprint,
        }

    try:
        result = await boundary.run_sync_serialized_write(_move)
    except AppTestCaseMoveImpactChanged as exc:
        await log_app_token_audit(
            request,
            principal,
            allowed=False,
            reason="test_case_move_impact_changed",
            action_type=ActionType.UPDATE,
            team_id=team_id,
            extra_details={
                "case_ids": exc.preview["case_ids"],
                "target_test_case_set_id": body.target_test_set_id,
                "requested_impact_fingerprint": body.impact_fingerprint,
                "current_impact_fingerprint": exc.preview["impact_fingerprint"],
                "impacted_item_count": exc.preview["impacted_item_count"],
            },
        )
        raise _app_validation_error(
            str(exc),
            status_code=status.HTTP_409_CONFLICT,
            code=AppTokenErrorCodes.IMPACT_CHANGED,
        ) from exc
    await _audit_mutation(
        request,
        principal,
        ActionType.UPDATE,
        team_id,
        "test_case:guarded-move",
        {
            "case_ids": result["case_ids"],
            "target_test_case_set_id": result["target_test_case_set_id"],
            "impact_fingerprint": result["impact_fingerprint"],
            "cleanup_summary": result["cleanup_summary"],
        },
    )
    if result["case_numbers"]:
        await enqueue_test_cases_bulk(result["case_numbers"])
    return result


@router.post("/teams/{team_id}/test-cases", status_code=status.HTTP_201_CREATED)
async def create_app_test_case(
    team_id: int,
    body: TestCaseCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Create a test case via app token (requires test_case:write scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:write", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _create(sync_db: Session):
        existing = (
            sync_db.query(TestCaseLocalDB)
            .filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == body.test_case_number,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Test case number already exists")

        if body.test_case_set_id:
            test_set = (
                sync_db.query(TestCaseSetDB)
                .filter(TestCaseSetDB.id == body.test_case_set_id, TestCaseSetDB.team_id == team_id)
                .first()
            )
            if not test_set:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case set not found")
        else:
            from app.services.test_case_set_service import TestCaseSetService
            test_set = TestCaseSetService.get_or_create_default_sync(sync_db, team_id)

        target_section = None
        if body.test_case_section_id:
            target_section = (
                sync_db.query(TestCaseSectionDB)
                .filter(
                    TestCaseSectionDB.id == body.test_case_section_id,
                    TestCaseSectionDB.test_case_set_id == test_set.id,
                )
                .first()
            )
            if not target_section:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case section not found")
        else:
            target_section = (
                sync_db.query(TestCaseSectionDB)
                .filter(
                    TestCaseSectionDB.test_case_set_id == test_set.id,
                    TestCaseSectionDB.name == "Unassigned",
                )
                .first()
            )
            if not target_section:
                target_section = TestCaseSectionDB(
                    test_case_set_id=test_set.id,
                    name="Unassigned",
                    description="",
                    level=1,
                    sort_order=0,
                )
                sync_db.add(target_section)
                sync_db.flush()

        tc = TestCaseLocalDB(
            team_id=team_id,
            lark_record_id=f"local-{body.test_case_number}",
            test_case_number=body.test_case_number,
            title=body.title,
            priority=body.priority or Priority.MEDIUM,
            precondition=body.precondition,
            steps=body.steps,
            expected_result=body.expected_result,
            test_result=body.test_result,
            test_case_set_id=test_set.id,
            test_case_section_id=target_section.id,
            tcg_json=json.dumps(body.tcg or []),
            test_data_json=json.dumps(
                [item.dict() for item in normalize_test_data_items(body.test_data)]
            ) if body.test_data else json.dumps([]),
        )
        sync_db.add(tc)
        sync_db.flush()
        sync_db.refresh(tc)
        return tc

    try:
        tc = await main_boundary.run_sync_write(_create)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        f"test_case:{tc.id}",
        {"test_case_number": tc.test_case_number, "title": tc.title, "test_data": json.loads(tc.test_data_json) if tc.test_data_json else []},
    )
    tc_payload = {
        "test_case_number": tc.test_case_number,
        "title": tc.title or "",
        "precondition": tc.precondition or "",
        "steps": tc.steps or "",
        "expected_result": tc.expected_result or "",
        "team_id": team_id,
    }
    await enqueue_test_case_sync(tc.test_case_number, payload=tc_payload)
    return _serialize_test_case(tc)


@router.put("/teams/{team_id}/test-cases/{case_id}")
async def update_app_test_case(
    team_id: int,
    case_id: int,
    body: TestCaseUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Update a test case via app token (requires test_case:write scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _update(sync_db: Session):
        tc = (
            sync_db.query(TestCaseLocalDB)
            .filter(TestCaseLocalDB.id == case_id, TestCaseLocalDB.team_id == team_id)
            .first()
        )
        if not tc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")

        if (
            body.test_case_set_id is not None
            and body.test_case_set_id != tc.test_case_set_id
        ):
            raise _app_validation_error(
                "Cross-Set updates require impact preview and the guarded move endpoint"
            )

        changed = False

        def _comparable_value(value: Any) -> Any:
            return value.value if hasattr(value, "value") else value

        def _set_if_changed(attribute: str, value: Any) -> None:
            nonlocal changed
            if _comparable_value(getattr(tc, attribute)) == _comparable_value(value):
                return
            setattr(tc, attribute, value)
            changed = True

        def _set_json_if_changed(attribute: str, value: List[Any]) -> None:
            nonlocal changed
            raw_value = getattr(tc, attribute)
            try:
                current_value = json.loads(raw_value) if raw_value else []
            except (TypeError, json.JSONDecodeError):
                current_value = None
            if current_value == value:
                return
            setattr(tc, attribute, json.dumps(value))
            changed = True

        if body.test_case_number is not None:
            _set_if_changed("test_case_number", body.test_case_number)
        if body.title is not None:
            _set_if_changed("title", body.title)
        if body.priority is not None:
            _set_if_changed("priority", body.priority)
        if body.precondition is not None:
            _set_if_changed("precondition", body.precondition)
        if body.steps is not None:
            _set_if_changed("steps", body.steps)
        if body.expected_result is not None:
            _set_if_changed("expected_result", body.expected_result)
        if body.test_result is not None:
            _set_if_changed("test_result", body.test_result)
        # Validate Set / Section ownership before reassigning (mirror create + JWT update paths)
        if body.test_case_set_id is not None:
            target_set = (
                sync_db.query(TestCaseSetDB)
                .filter(
                    TestCaseSetDB.id == body.test_case_set_id,
                    TestCaseSetDB.team_id == team_id,
                )
                .first()
            )
            if not target_set:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Test Case Set {body.test_case_set_id} 不存在或不屬於此 Team",
                )
            _set_if_changed("test_case_set_id", target_set.id)
        if body.test_case_section_id is not None:
            effective_set_id = tc.test_case_set_id
            target_section = (
                sync_db.query(TestCaseSectionDB)
                .filter(
                    TestCaseSectionDB.id == body.test_case_section_id,
                    TestCaseSectionDB.test_case_set_id == effective_set_id,
                )
                .first()
            )
            if not target_section:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Section {body.test_case_section_id} 不存在或不屬於 Test Case Set {effective_set_id}",
                )
            _set_if_changed("test_case_section_id", target_section.id)
        if body.tcg is not None:
            tcg_list = body.tcg if isinstance(body.tcg, list) else [body.tcg]
            _set_json_if_changed("tcg_json", tcg_list)
        if body.test_data is not None:
            normalized_test_data = [
                item.model_dump(mode="json")
                for item in normalize_test_data_items(body.test_data)
            ]
            _set_json_if_changed(
                "test_data_json",
                normalized_test_data,
            )

        if changed:
            tc.updated_at = datetime.utcnow()

        sync_db.flush()
        sync_db.refresh(tc)
        return tc

    try:
        tc = await main_boundary.run_sync_write(_update)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    await _audit_mutation(
        request, principal, ActionType.UPDATE, team_id,
        f"test_case:{tc.id}",
        {"test_case_number": tc.test_case_number, "title": tc.title, "test_data": json.loads(tc.test_data_json) if tc.test_data_json else []},
    )
    uk_payload = {
        "test_case_number": tc.test_case_number,
        "title": tc.title or "",
        "precondition": tc.precondition or "",
        "steps": tc.steps or "",
        "expected_result": tc.expected_result or "",
        "team_id": team_id,
    }
    await enqueue_test_case_sync(tc.test_case_number, payload=uk_payload)
    return _serialize_test_case(tc)


@router.delete("/teams/{team_id}/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_test_case(
    team_id: int,
    case_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Delete a test case via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_ADMIN):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:admin", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:admin scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _delete(sync_db: Session):
        tc = (
            sync_db.query(TestCaseLocalDB)
            .filter(TestCaseLocalDB.id == case_id, TestCaseLocalDB.team_id == team_id)
            .first()
        )
        if not tc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
        sync_db.delete(tc)
        sync_db.flush()
        return tc

    tc = await main_boundary.run_sync_write(_delete)
    await _audit_mutation(
        request, principal, ActionType.DELETE, team_id,
        f"test_case:{case_id}",
        {"test_case_number": tc.test_case_number, "title": tc.title},
    )
    await enqueue_test_case_sync(tc.test_case_number, operation="delete")


@router.post("/teams/{team_id}/test-cases/batch")
async def batch_app_test_cases(
    team_id: int,
    body: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Batch create test cases via app token (requires test_case:write scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    items = body.get("items", [])
    if not items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items provided")

    results = []
    main_boundary = create_main_access_boundary_for_session(db)

    for item_data in items:
        try:
            create_body = TestCaseCreate(**item_data)

            def _create_one(sync_db: Session, cb=create_body):
                existing = (
                    sync_db.query(TestCaseLocalDB)
                    .filter(
                        TestCaseLocalDB.team_id == team_id,
                        TestCaseLocalDB.test_case_number == cb.test_case_number,
                    )
                    .first()
                )
                if existing:
                    raise ValueError("Test case number already exists")

                if cb.test_case_set_id:
                    test_set = (
                        sync_db.query(TestCaseSetDB)
                        .filter(TestCaseSetDB.id == cb.test_case_set_id, TestCaseSetDB.team_id == team_id)
                        .first()
                    )
                    if not test_set:
                        raise ValueError("Test case set not found")
                else:
                    from app.services.test_case_set_service import TestCaseSetService
                    test_set = TestCaseSetService.get_or_create_default_sync(sync_db, team_id)

                target_section = None
                if cb.test_case_section_id:
                    target_section = (
                        sync_db.query(TestCaseSectionDB)
                        .filter(
                            TestCaseSectionDB.id == cb.test_case_section_id,
                            TestCaseSectionDB.test_case_set_id == test_set.id,
                        )
                        .first()
                    )
                    if not target_section:
                        raise ValueError("Test case section not found")
                else:
                    target_section = (
                        sync_db.query(TestCaseSectionDB)
                        .filter(
                            TestCaseSectionDB.test_case_set_id == test_set.id,
                            TestCaseSectionDB.name == "Unassigned",
                        )
                        .first()
                    )
                    if not target_section:
                        target_section = TestCaseSectionDB(
                            test_case_set_id=test_set.id,
                            name="Unassigned",
                            description="",
                            level=1,
                            sort_order=0,
                        )
                        sync_db.add(target_section)
                        sync_db.flush()

                tc = TestCaseLocalDB(
                    team_id=team_id,
                    lark_record_id=f"local-{cb.test_case_number}",
                    test_case_number=cb.test_case_number,
                    title=cb.title,
                    priority=cb.priority or Priority.MEDIUM,
                    precondition=cb.precondition,
                    steps=cb.steps,
                    expected_result=cb.expected_result,
                    test_case_set_id=test_set.id,
                    test_case_section_id=target_section.id if target_section else None,
                    tcg_json=json.dumps(cb.tcg or []),
                    test_data_json=json.dumps(
                        [item.dict() for item in normalize_test_data_items(cb.test_data)]
                    ) if cb.test_data else json.dumps([]),
                )
                sync_db.add(tc)
                sync_db.flush()
                sync_db.refresh(tc)
                return tc

            tc = await main_boundary.run_sync_write(_create_one)
            results.append({"success": True, "test_case_number": tc.test_case_number, "id": tc.id})
        except Exception as exc:
            results.append({
                "success": False,
                "test_case_number": item_data.get("test_case_number", ""),
                "error": str(exc),
            })

    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        "test_case:batch",
        {"batch_size": len(items), "success_count": sum(1 for r in results if r["success"])},
    )
    return {"results": results, "total": len(results), "success_count": sum(1 for r in results if r["success"])}


@router.post("/teams/{team_id}/test-cases/batch-operations")
async def batch_operations_app_test_cases(
    team_id: int,
    operation: TestCaseBatchOperation,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Batch operate test cases via app token, sharing the JWT batch core.

    Supports delete (requires test_case:admin), update_priority, update_tcg,
    update_section, update_test_set (require test_case:write).
    """
    await require_app_team_access(team_id, request, principal)
    if operation.operation == "delete":
        await _require_admin_scope(principal, request, team_id)
    elif not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:write", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    if not operation.record_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="記錄 ID 列表不能為空")
    if operation.operation == "update_test_set":
        raise _app_validation_error(
            "Cross-Set updates require impact preview and the guarded move endpoint"
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _batch(sync_db: Session):
        return run_test_case_batch_operation_sync(sync_db, team_id, operation, principal.audit_actor)

    response, _log_context = await main_boundary.run_sync_write(_batch)
    await _audit_mutation(
        request, principal,
        ActionType.DELETE if operation.operation == "delete" else ActionType.UPDATE,
        team_id,
        f"test_case:batch-{operation.operation}",
        {
            "operation": operation.operation,
            "success_count": response.success_count,
            "error_count": response.error_count,
        },
    )

    # Knowledge graph sync: enqueue all affected test case numbers.
    if _log_context and _log_context.get("details"):
        affected = set()
        for key in ("deleted_items", "updated_items", "moved_items"):
            for item in _log_context["details"].get(key) or []:
                tcn = item.get("test_case_number")
                if tcn:
                    affected.add(tcn)
        kg_op = "delete" if operation.operation == "delete" else "upsert"
        if affected:
            await enqueue_test_cases_bulk(list(affected), operation=kg_op)

    return response


@router.post("/teams/{team_id}/test-cases/bulk-clone")
async def bulk_clone_app_test_cases(
    team_id: int,
    body: BulkCloneRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Bulk clone test cases via app token (requires test_case:write), sharing the JWT core."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:write", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _clone(sync_db: Session):
        return run_bulk_clone_sync(sync_db, team_id, body)

    response, _audit_context = await main_boundary.run_sync_write(_clone)
    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        "test_case:bulk-clone",
        {
            "created_count": response.created_count,
            "duplicates": response.duplicates,
            "error_count": len(response.errors),
        },
    )

    # Knowledge graph sync: all cloned test case items.
    if _audit_context and _audit_context.get("cloned_items"):
        await enqueue_test_cases_bulk(_audit_context["cloned_items"])

    return response


async def _require_admin_scope(principal: AppTokenPrincipal, request: Request, team_id: int) -> None:
    if not principal.has_scope(SCOPE_TEST_CASE_ADMIN):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:admin", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:admin scope"},
        )


async def _load_team_scoped_set(db: AsyncSession, team_id: int, set_id: int) -> TestCaseSetDB:
    result = await db.execute(
        select(TestCaseSetDB).where(TestCaseSetDB.id == set_id, TestCaseSetDB.team_id == team_id)
    )
    test_set = result.scalar_one_or_none()
    if not test_set:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case set not found")
    return test_set


@router.post("/teams/{team_id}/test-case-sets", status_code=status.HTTP_201_CREATED)
async def create_app_test_case_set(
    team_id: int,
    body: TestCaseSetCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Create a test case set via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    service = TestCaseSetService(db)
    try:
        new_set = await service.create(team_id=team_id, name=body.name, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        f"test_case_set:{new_set.id}", {"name": new_set.name},
    )
    return {"id": new_set.id, "name": new_set.name, "description": new_set.description}


@router.put("/teams/{team_id}/test-case-sets/{set_id}")
async def update_app_test_case_set(
    team_id: int,
    set_id: int,
    body: TestCaseSetUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Update a test case set via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    await _load_team_scoped_set(db, team_id, set_id)
    service = TestCaseSetService(db)
    try:
        updated = await service.update(set_id=set_id, team_id=team_id, name=body.name, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.UPDATE, team_id,
        f"test_case_set:{set_id}", {"name": updated.name},
    )
    return {"id": updated.id, "name": updated.name, "description": updated.description}


@router.get("/teams/{team_id}/test-case-sets/{set_id}/impact-preview")
async def preview_app_test_case_set_deletion(
    team_id: int,
    set_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Preview the Test Run impact of deleting a test case set (requires test_case:admin)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    test_set = await _load_team_scoped_set(db, team_id, set_id)
    if test_set.is_default:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the default test case set")

    boundary = create_main_access_boundary_for_session(db)
    return await boundary.run_sync_read(
        lambda sync_db: TestRunScopeService.preview_set_deletion(sync_db, team_id, set_id)
    )


@router.delete("/teams/{team_id}/test-case-sets/{set_id}")
async def delete_app_test_case_set(
    team_id: int,
    set_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Delete a test case set via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    await _load_team_scoped_set(db, team_id, set_id)
    service = TestCaseSetService(db)
    try:
        delete_result = await service.delete(set_id, team_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.DELETE, team_id,
        f"test_case_set:{set_id}", {"cleanup_summary": delete_result.get("cleanup_summary")},
    )
    return {"success": True, **delete_result}


@router.post("/teams/{team_id}/test-case-sets/{set_id}/sections", status_code=status.HTTP_201_CREATED)
async def create_app_test_case_section(
    team_id: int,
    set_id: int,
    body: TestCaseSectionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Create a test case section via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    await _load_team_scoped_set(db, team_id, set_id)
    service = TestCaseSectionService(db)
    try:
        section = await service.create(
            test_case_set_id=set_id,
            name=body.name,
            description=body.description,
            parent_section_id=body.parent_section_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        f"test_case_section:{section.id}", {"name": section.name},
    )
    return {"id": section.id, "name": section.name, "test_case_set_id": section.test_case_set_id}


@router.put("/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}")
async def update_app_test_case_section(
    team_id: int,
    set_id: int,
    section_id: int,
    body: TestCaseSectionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Update a test case section via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    await _load_team_scoped_set(db, team_id, set_id)
    service = TestCaseSectionService(db)
    existing = await service.get_by_id(section_id)
    if not existing or existing.test_case_set_id != set_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case section not found")
    try:
        section = await service.update(section_id=section_id, name=body.name, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.UPDATE, team_id,
        f"test_case_section:{section_id}", {"name": section.name},
    )
    return {"id": section.id, "name": section.name, "test_case_set_id": section.test_case_set_id}


@router.delete("/teams/{team_id}/test-case-sets/{set_id}/sections/{section_id}")
async def delete_app_test_case_section(
    team_id: int,
    set_id: int,
    section_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Delete a test case section via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    await _load_team_scoped_set(db, team_id, set_id)
    service = TestCaseSectionService(db)
    existing = await service.get_by_id(section_id)
    if not existing or existing.test_case_set_id != set_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case section not found")
    try:
        await service.delete(section_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await _audit_mutation(
        request, principal, ActionType.DELETE, team_id,
        f"test_case_section:{section_id}", {"section_id": section_id},
    )
    return {"success": True, "section_id": section_id}


@router.post("/teams/{team_id}/test-cases/{case_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_app_test_case_attachments(
    team_id: int,
    case_id: int,
    request: Request,
    files: List[UploadFile] = File(...),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
    db: AsyncSession = Depends(get_db),
):
    """Upload test case attachments via app token (requires test_case:write scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope(SCOPE_TEST_CASE_WRITE):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_case:write", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:write scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _get_item(sync_db: Session):
        return (
            sync_db.query(TestCaseLocalDB)
            .filter(TestCaseLocalDB.id == case_id, TestCaseLocalDB.team_id == team_id)
            .first()
        )

    item = await main_boundary.run_sync_read(_get_item)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")

    root_dir = get_attachments_root_dir(PROJECT_ROOT)
    base_dir = root_dir / "test-cases" / str(team_id) / item.test_case_number
    ensure_within_root(base_dir, root_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    existing: List[Dict[str, Any]] = []
    if item.attachments_json:
        try:
            parsed = json.loads(item.attachments_json)
            if isinstance(parsed, list):
                existing = parsed
        except (TypeError, ValueError):
            existing = []

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
    uploaded: List[Dict[str, Any]] = []

    for f in files:
        orig_name = f.filename or "unnamed"
        stored_name = f"{ts}-{safe_re.sub('_', orig_name)}"
        stored_path = base_dir / stored_name
        content = await f.read()
        with open(stored_path, "wb") as out:
            out.write(content)
        meta = build_attachment_metadata(
            root_dir=root_dir,
            stored_path=stored_path,
            original_name=orig_name,
            stored_name=stored_name,
            size=len(content),
            content_type=f.content_type or "application/octet-stream",
            uploaded_at=datetime.utcnow().isoformat(),
        )
        existing.append(meta)
        uploaded.append(meta)

    attachments_json = json.dumps(existing, ensure_ascii=False)

    def _save(sync_db: Session):
        item_db = (
            sync_db.query(TestCaseLocalDB)
            .filter(TestCaseLocalDB.id == case_id, TestCaseLocalDB.team_id == team_id)
            .first()
        )
        if not item_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")
        item_db.attachments_json = attachments_json

    await main_boundary.run_sync_write(_save)
    await _audit_mutation(
        request, principal, ActionType.CREATE, team_id,
        f"test_case:{case_id}:attachments", {"uploaded_count": len(uploaded)},
    )
    return {"success": True, "uploaded": len(uploaded), "files": uploaded, "base_url": "/attachments"}


@router.get("/teams/{team_id}/test-cases/{case_id}/attachments")
async def list_app_test_case_attachments(
    team_id: int,
    case_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """List test case attachments via app token (requires test_case:read scope)."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_scope("test_case:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_case:read scope"},
        )

    main_boundary = create_main_access_boundary_for_session(db)

    def _get_item(sync_db: Session):
        return (
            sync_db.query(TestCaseLocalDB)
            .filter(TestCaseLocalDB.id == case_id, TestCaseLocalDB.team_id == team_id)
            .first()
        )

    item = await main_boundary.run_sync_read(_get_item)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test case not found")

    files: List[Dict[str, Any]] = []
    if item.attachments_json:
        try:
            files = json.loads(item.attachments_json) or []
        except (TypeError, ValueError):
            files = []
    return {"success": True, "files": files, "count": len(files), "base_url": "/attachments"}


@router.delete("/teams/{team_id}/test-cases/{case_id}/attachments/{target}")
async def delete_app_test_case_attachment(
    team_id: int,
    case_id: int,
    target: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Delete a test case attachment via app token (requires test_case:admin scope)."""
    await require_app_team_access(team_id, request, principal)
    await _require_admin_scope(principal, request, team_id)

    main_boundary = create_main_access_boundary_for_session(db)
    result = await _delete_attachment_common(team_id, target, main_boundary, id_value=case_id)
    await _audit_mutation(
        request, principal, ActionType.DELETE, team_id,
        f"test_case:{case_id}:attachments", {"target": target, "remaining": result.get("remaining")},
    )
    return result
