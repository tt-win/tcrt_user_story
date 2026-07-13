"""App token test case mutation API - /api/app/teams/{team_id}/test-cases."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.test_cases import (
    BulkCloneRequest,
    _delete_attachment_common,
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
)
from app.models.test_case_set import (
    TestCaseSectionCreate,
    TestCaseSectionUpdate,
    TestCaseSetCreate,
    TestCaseSetUpdate,
)
from app.services.attachment_storage import build_attachment_metadata, get_attachments_root_dir
from app.services.test_case_section_service import TestCaseSectionService
from app.services.test_case_set_service import TestCaseSetService
from app.services.test_run_scope_service import TestRunScopeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app-test-case-mutations"])


def _serialize_test_case(tc: TestCaseLocalDB) -> Dict[str, Any]:
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
        "test_data": json.loads(tc.test_data_json) if tc.test_data_json else [],
    }


def _redact_test_data(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for item in items:
        redacted = dict(item)
        if str(item.get("category", "")).lower() == "credential":
            redacted["value"] = "[REDACTED]"
        result.append(redacted)
    return result


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
        redacted["test_data"] = _redact_test_data(redacted["test_data"])
    await log_app_token_audit(
        request,
        principal,
        allowed=True,
        reason=f"test_case_{action_type.value.lower()}",
        action_type=action_type,
        team_id=team_id,
        extra_details=redacted,
    )


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

        if body.test_case_number is not None:
            tc.test_case_number = body.test_case_number
        if body.title is not None:
            tc.title = body.title
        if body.priority is not None:
            tc.priority = body.priority
        if body.precondition is not None:
            tc.precondition = body.precondition
        if body.steps is not None:
            tc.steps = body.steps
        if body.expected_result is not None:
            tc.expected_result = body.expected_result
        if body.test_result is not None:
            tc.test_result = body.test_result
        if body.test_case_set_id is not None:
            tc.test_case_set_id = body.test_case_set_id
        if body.test_case_section_id is not None:
            tc.test_case_section_id = body.test_case_section_id
        if body.tcg is not None:
            tcg_list = body.tcg if isinstance(body.tcg, list) else [body.tcg]
            tc.tcg_json = json.dumps(tcg_list)
        if body.test_data is not None:
            tc.test_data_json = json.dumps(
                [item.dict() for item in normalize_test_data_items(body.test_data)]
            )

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
