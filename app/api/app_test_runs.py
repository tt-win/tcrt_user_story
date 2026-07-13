"""App token test run mutation API - /api/app/teams/{team_id}/test-runs."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.test_run_configs import (
    StatusChangeRequest,
    attach_config_to_set,
    build_config_summary,
    delete_test_run_config_cascade_sync,
    detach_config_from_set,
    ensure_test_run_set,
    verify_team_exists,
)
from app.api.test_run_items import (
    BatchUpdateResultRequest,
    TestRunItemUpdate,
    _add_result_history,
    _db_to_response,
    _to_json,
    _verify_team_and_config,
    apply_batch_item_update_sync,
)
from app.api.test_run_sets import _validate_config_ids
from app.audit import ActionType
from app.auth.app_token_dependencies import (
    AppTokenErrorCodes,
    get_current_app_token_principal,
    log_app_token_audit,
    require_app_team_access,
)
from app.database import get_db
from app.db_access.main import create_main_access_boundary_for_session
from app.models.app_token import (
    AppTokenPrincipal,
    SCOPE_TEST_RUN_ADMIN,
    SCOPE_TEST_RUN_EXECUTE,
    SCOPE_TEST_RUN_READ,
    SCOPE_TEST_RUN_WRITE,
)
from app.models.database_models import (
    AutomationScriptGroup as AutomationScriptGroupDB,
    TestRunConfig as TestRunConfigDB,
    TestRunItem as TestRunItemDB,
    TestRunSet as TestRunSetDB,
)
from app.models.test_run_config import TestRunConfigCreate, TestRunConfigUpdate, TestRunStatus
from app.models.test_run_set import TestRunSetCreate, TestRunSetStatus, TestRunSetUpdate
from app.services.attachment_storage import build_attachment_metadata, get_attachments_root_dir
from app.services.test_result_cleanup_service import TestResultCleanupService
from app.services.test_run_scope_service import TestRunScopeService
from app.services.test_run_set_status import (
    apply_config_status_transition_sync,
    recalculate_set_status_sync,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/app", tags=["app-test-run-mutations"])


class AppTestRunItemReadItem(BaseModel):
    id: int
    test_case_number: str
    test_result: Optional[str] = None
    executed_at: Optional[datetime] = None
    execution_duration: Optional[int] = None
    assignee_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class AppTestRunItemPage(BaseModel):
    skip: int
    limit: int
    total: int
    has_next: bool


class AppTestRunItemListResponse(BaseModel):
    team_id: int
    config_id: int
    items: List[AppTestRunItemReadItem]
    page: AppTestRunItemPage


def _serialize_config(config: TestRunConfigDB, cleanup_summary: Optional[dict] = None) -> Dict[str, Any]:
    return {
        "id": config.id,
        "team_id": config.team_id,
        "name": config.name,
        "description": config.description,
        "status": config.status.value if hasattr(config.status, "value") else str(config.status),
        "test_version": config.test_version,
        "test_environment": config.test_environment,
        "build_number": config.build_number,
        "test_case_set_ids": TestRunScopeService.parse_scope_ids_json(config.test_case_set_ids_json),
        "related_tp_tickets": json.loads(config.related_tp_tickets_json) if config.related_tp_tickets_json else [],
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        "cleanup_summary": cleanup_summary,
    }


def _serialize_set(trs: TestRunSetDB) -> Dict[str, Any]:
    return {
        "id": trs.id,
        "team_id": trs.team_id,
        "name": trs.name,
        "description": trs.description,
        "status": trs.status.value if hasattr(trs.status, "value") else str(trs.status),
        "archived_at": trs.archived_at.isoformat() if trs.archived_at else None,
        "related_tp_tickets": json.loads(trs.related_tp_tickets_json) if trs.related_tp_tickets_json else [],
        "automation_suite_ids": json.loads(trs.automation_suite_ids_json) if trs.automation_suite_ids_json else [],
        "created_at": trs.created_at.isoformat() if trs.created_at else None,
        "updated_at": trs.updated_at.isoformat() if trs.updated_at else None,
    }


async def _check_scope(principal: AppTokenPrincipal, scope: str, request: Request, team_id: int):
    if not principal.has_scope(scope):
        await log_app_token_audit(
            request, principal, allowed=False, reason=f"scope_denied:{scope}", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": f"Missing {scope} scope"},
        )


def _validate_automation_suite_ids_sync(sync_db: Session, team_id: int, suite_ids: List[int]) -> None:
    """Reject automation_suite_ids that don't belong to team_id.

    The JWT create/update endpoints for Test Run Set do not perform this
    check today (validation only happens at run-automation trigger time);
    this change's spec requires app-token writes to reject cross-team suite
    ids up front, so this validation is app-token-specific.
    """
    if not suite_ids:
        return
    valid_ids = {
        row[0]
        for row in sync_db.query(AutomationScriptGroupDB.id)
        .filter(AutomationScriptGroupDB.team_id == team_id, AutomationScriptGroupDB.id.in_(suite_ids))
        .all()
    }
    invalid = [sid for sid in suite_ids if sid not in valid_ids]
    if invalid:
        raise ValueError(f"以下 automation suite 不存在或不屬於團隊 {team_id}: {invalid}")


# --------------------------------------------------------------------- test run configs


@router.post("/teams/{team_id}/test-run-configs", status_code=status.HTTP_201_CREATED)
async def create_app_test_run_config(
    team_id: int,
    body: TestRunConfigCreate,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _create(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        try:
            scope_ids = TestRunScopeService.validate_scope_ids(
                sync_db, team_id, body.test_case_set_ids, allow_empty=True
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        config = TestRunConfigDB(
            team_id=team_id,
            name=body.name,
            description=body.description,
            test_case_set_ids_json=TestRunScopeService.dump_scope_ids_json(scope_ids),
            test_version=body.test_version,
            test_environment=body.test_environment,
            build_number=body.build_number,
            related_tp_tickets_json=json.dumps(body.related_tp_tickets or []),
            status=body.status or TestRunStatus.DRAFT,
            start_date=body.start_date,
            notifications_enabled=body.notifications_enabled,
            notify_chat_ids_json=json.dumps(body.notify_chat_ids or []),
            notify_chat_names_snapshot=json.dumps(body.notify_chat_names_snapshot or []),
        )
        sync_db.add(config)
        sync_db.flush()
        sync_db.refresh(config)

        if body.set_id:
            attach_config_to_set(sync_db, team_id, config, body.set_id)

        return config

    config = await boundary.run_sync_write(_create)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_config_create",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"config_id": config.id, "name": config.name},
    )
    return _serialize_config(config)


@router.put("/teams/{team_id}/test-run-configs/{config_id}")
async def update_app_test_run_config(
    team_id: int,
    config_id: int,
    body: TestRunConfigUpdate,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _update(sync_db: Session):
        config = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id
        ).first()
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run config not found")

        if body.name is not None:
            config.name = body.name
        if body.description is not None:
            config.description = body.description
        if body.test_version is not None:
            config.test_version = body.test_version
        if body.test_environment is not None:
            config.test_environment = body.test_environment
        if body.build_number is not None:
            config.build_number = body.build_number
        if body.status is not None:
            config.status = body.status
        if body.related_tp_tickets is not None:
            config.related_tp_tickets_json = json.dumps(body.related_tp_tickets)

        cleanup_summary = None
        if body.test_case_set_ids is not None:
            old_scope = TestRunScopeService.get_config_scope_ids(
                sync_db, config, allow_fallback=True, persist_fallback=False
            )
            try:
                new_scope = TestRunScopeService.validate_scope_ids(
                    sync_db, team_id, body.test_case_set_ids, allow_empty=True
                )
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

            TestRunScopeService.set_config_scope_ids(config, new_scope)
            removed_set_ids = [sid for sid in old_scope if sid not in new_scope]
            if removed_set_ids:
                cleanup_summary = TestRunScopeService.cleanup_scope_reduction(
                    sync_db, team_id, config_id, removed_set_ids
                )

        sync_db.flush()
        sync_db.refresh(config)
        return config, cleanup_summary

    config, cleanup_summary = await boundary.run_sync_write(_update)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_config_update",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"config_id": config.id, "cleanup_summary": cleanup_summary},
    )
    return _serialize_config(config, cleanup_summary=cleanup_summary)


@router.put("/teams/{team_id}/test-run-configs/{config_id}/status")
async def change_app_test_run_config_status(
    team_id: int,
    config_id: int,
    body: StatusChangeRequest,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Transition a Test Run Config through its lifecycle (requires test_run:write).

    Unlike the plain PUT, this enforces the status state machine (shared with the
    JWT endpoint), applies start/end date side-effects, and recalculates the
    parent set status.
    """
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _change(sync_db: Session):
        config = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id
        ).first()
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run config not found")

        try:
            apply_config_status_transition_sync(config, body.status)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        if config.set_membership:
            set_db = ensure_test_run_set(sync_db, team_id, config.set_membership.set_id)
            recalculate_set_status_sync(sync_db, set_db)

        sync_db.flush()
        sync_db.refresh(config)
        return config

    config = await boundary.run_sync_write(_change)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_config_status_change",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={
            "config_id": config_id,
            "status": body.status.value if hasattr(body.status, "value") else str(body.status),
        },
    )
    return _serialize_config(config)


@router.delete("/teams/{team_id}/test-run-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_test_run_config(
    team_id: int,
    config_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_ADMIN, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _load(sync_db: Session):
        config = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id
        ).first()
        if not config:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run config not found")
        return config.name

    config_name = await boundary.run_sync_read(_load)

    cleanup_service = TestResultCleanupService()
    try:
        await cleanup_service.cleanup_test_run_config_files(team_id, config_id, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to clean up result files for config %s: %s", config_id, exc, exc_info=True)

    await boundary.run_sync_write(
        lambda sync_db: delete_test_run_config_cascade_sync(sync_db, team_id, config_id)
    )
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_config_delete",
        action_type=ActionType.DELETE, team_id=team_id,
        extra_details={"config_id": config_id, "name": config_name},
    )


# --------------------------------------------------------------------- test run sets


@router.post("/teams/{team_id}/test-run-sets", status_code=status.HTTP_201_CREATED)
async def create_app_test_run_set(
    team_id: int,
    body: TestRunSetCreate,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _create(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        try:
            _validate_automation_suite_ids_sync(sync_db, team_id, body.automation_suite_ids)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        trs = TestRunSetDB(
            team_id=team_id,
            name=body.name,
            description=body.description,
            related_tp_tickets_json=json.dumps(body.related_tp_tickets or []),
            automation_suite_ids_json=json.dumps(body.automation_suite_ids or []),
            default_automation_environment=body.default_automation_environment,
        )
        sync_db.add(trs)
        sync_db.flush()

        if body.initial_config_ids:
            configs = _validate_config_ids(sync_db, team_id, body.initial_config_ids)
            for config_db in configs:
                attach_config_to_set(sync_db, team_id, config_db, trs.id)

        sync_db.flush()
        sync_db.refresh(trs)
        return trs

    trs = await boundary.run_sync_write(_create)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_create",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"set_id": trs.id, "name": trs.name},
    )
    return _serialize_set(trs)


@router.put("/teams/{team_id}/test-run-sets/{set_id}")
async def update_app_test_run_set(
    team_id: int,
    set_id: int,
    body: TestRunSetUpdate,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _update(sync_db: Session):
        trs = sync_db.query(TestRunSetDB).filter(
            TestRunSetDB.id == set_id, TestRunSetDB.team_id == team_id
        ).first()
        if not trs:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run set not found")
        if body.name is not None:
            trs.name = body.name
        if body.description is not None:
            trs.description = body.description
        if body.status is not None:
            trs.status = body.status
        if body.related_tp_tickets is not None:
            trs.related_tp_tickets_json = json.dumps(body.related_tp_tickets)
        if body.automation_suite_ids is not None:
            try:
                _validate_automation_suite_ids_sync(sync_db, team_id, body.automation_suite_ids)
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
            trs.automation_suite_ids_json = json.dumps(body.automation_suite_ids)
        if body.default_automation_environment is not None:
            trs.default_automation_environment = body.default_automation_environment or None

        sync_db.flush()
        sync_db.refresh(trs)
        return trs

    trs = await boundary.run_sync_write(_update)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_update",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"set_id": trs.id},
    )
    return _serialize_set(trs)


@router.post("/teams/{team_id}/test-run-sets/{set_id}/archive")
async def archive_app_test_run_set(
    team_id: int,
    set_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_ADMIN, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _archive(sync_db: Session):
        trs = ensure_test_run_set(sync_db, team_id, set_id)
        trs.status = TestRunSetStatus.ARCHIVED
        trs.archived_at = datetime.utcnow()
        sync_db.flush()
        sync_db.refresh(trs)
        return trs

    trs = await boundary.run_sync_write(_archive)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_archive",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"set_id": set_id},
    )
    return _serialize_set(trs)


@router.delete("/teams/{team_id}/test-run-sets/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_test_run_set(
    team_id: int,
    set_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_ADMIN, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _prepare(sync_db: Session):
        trs = ensure_test_run_set(sync_db, team_id, set_id)
        return {
            "set_name": trs.name,
            "config_ids": [m.config_id for m in trs.memberships],
        }

    context = await boundary.run_sync_read(_prepare)

    cleanup_service = TestResultCleanupService()
    for config_id in context["config_ids"]:
        try:
            await cleanup_service.cleanup_test_run_config_files(team_id, config_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to clean up result files for config %s: %s", config_id, exc, exc_info=True)

    def _delete(sync_db: Session):
        trs = ensure_test_run_set(sync_db, team_id, set_id)
        sync_db.delete(trs)
        sync_db.flush()
        for config_id in context["config_ids"]:
            delete_test_run_config_cascade_sync(sync_db, team_id, config_id, detach=False)

    await boundary.run_sync_write(_delete)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_delete",
        action_type=ActionType.DELETE, team_id=team_id,
        extra_details={"set_id": set_id, "name": context["set_name"], "config_count": len(context["config_ids"])},
    )


@router.post("/teams/{team_id}/test-run-sets/{set_id}/members")
async def add_app_test_run_set_members(
    team_id: int,
    set_id: int,
    body: Dict[str, Any],
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Attach existing Test Run Configs to this set (requires test_run:write)."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    config_ids = body.get("config_ids") or []
    boundary = create_main_access_boundary_for_session(db)

    def _add(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        ensure_test_run_set(sync_db, team_id, set_id)
        configs = _validate_config_ids(sync_db, team_id, config_ids)
        for config_db in configs:
            attach_config_to_set(sync_db, team_id, config_db, set_id)
        trs = ensure_test_run_set(sync_db, team_id, set_id)
        recalculate_set_status_sync(sync_db, trs)
        sync_db.flush()
        return trs

    trs = await boundary.run_sync_write(_add)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_members_add",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"set_id": set_id, "config_ids": config_ids},
    )
    return _serialize_set(trs)


@router.post("/teams/{team_id}/test-run-sets/members/{config_id}/move")
async def move_app_test_run_config_between_sets(
    team_id: int,
    config_id: int,
    body: Dict[str, Any],
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Move (or detach, if target_set_id is null) a Test Run Config between sets."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    target_set_id = body.get("target_set_id")
    boundary = create_main_access_boundary_for_session(db)

    def _move(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        config_db = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id, TestRunConfigDB.team_id == team_id
        ).first()
        if not config_db:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到 Test Run Config ID {config_id}")

        previous_set_id = None
        affected_set_ids = set()
        if config_db.set_membership:
            previous_set_id = config_db.set_membership.set_id
            affected_set_ids.add(previous_set_id)

        if target_set_id is None:
            detach_config_from_set(sync_db, config_id)
            if previous_set_id is not None:
                ensure_test_run_set(sync_db, team_id, previous_set_id)
        else:
            target_set = ensure_test_run_set(sync_db, team_id, target_set_id)
            attach_config_to_set(sync_db, team_id, config_db, target_set.id)
            affected_set_ids.add(target_set.id)
            if previous_set_id and previous_set_id != target_set.id:
                ensure_test_run_set(sync_db, team_id, previous_set_id)

        for affected_set_id in affected_set_ids:
            set_db = ensure_test_run_set(sync_db, team_id, affected_set_id)
            recalculate_set_status_sync(sync_db, set_db)

        sync_db.flush()
        sync_db.expire(config_db, ["set_membership"])
        return build_config_summary(config_db)

    summary = await boundary.run_sync_write(_move)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_config_move",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"config_id": config_id, "target_set_id": target_set_id},
    )
    return summary


# --------------------------------------------------------------------- test run items


@router.get(
    "/teams/{team_id}/test-run-configs/{config_id}/items",
    response_model=AppTestRunItemListResponse,
)
async def list_app_test_run_items(
    team_id: int,
    config_id: int,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """List a Test Run Config's item execution metadata (requires test_run:read)."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_READ, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _list(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        filters = (TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id)
        total = sync_db.query(func.count(TestRunItemDB.id)).filter(*filters).scalar() or 0
        items = (
            sync_db.query(TestRunItemDB)
            .filter(*filters)
            .order_by(TestRunItemDB.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return total, items

    total, items = await boundary.run_sync_read(_list)
    return AppTestRunItemListResponse(
        team_id=team_id,
        config_id=config_id,
        items=[
            AppTestRunItemReadItem(
                id=item.id,
                test_case_number=item.test_case_number,
                test_result=item.test_result.value if item.test_result else None,
                executed_at=item.executed_at,
                execution_duration=item.execution_duration,
                assignee_name=item.assignee_name,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        page=AppTestRunItemPage(
            skip=skip,
            limit=limit,
            total=total,
            has_next=skip + len(items) < total,
        ),
    )


@router.post("/teams/{team_id}/test-run-configs/{config_id}/items", status_code=status.HTTP_201_CREATED)
async def batch_create_app_test_run_items(
    team_id: int,
    config_id: int,
    body: Dict[str, Any],
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Batch create Test Run Items (one item is just a single-element batch), requires test_run:write."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    from app.api.test_run_items import BatchCreateRequest

    try:
        payload = BatchCreateRequest(**body)
    except Exception as exc:  # noqa: BLE001 - surface pydantic validation errors as 400
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    boundary = create_main_access_boundary_for_session(db)

    def _create(sync_db: Session) -> Dict[str, Any]:
        config_db = _verify_team_and_config(team_id, config_id, sync_db)
        config_scope_ids = TestRunScopeService.get_config_scope_ids(
            sync_db, config_db, allow_fallback=True, persist_fallback=False
        )
        allowed_scope_ids = set(config_scope_ids)
        auto_scope_ids: List[int] = []

        from app.models.database_models import TestCaseLocal as TestCaseLocalDB

        created = 0
        skipped = 0
        errors: List[str] = []

        for idx, item in enumerate(payload.items):
            try:
                existing = (
                    sync_db.query(TestRunItemDB)
                    .filter(
                        TestRunItemDB.team_id == team_id,
                        TestRunItemDB.config_id == config_id,
                        TestRunItemDB.test_case_number == item.test_case_number,
                    )
                    .first()
                )
                if existing:
                    skipped += 1
                    continue

                test_case = (
                    sync_db.query(TestCaseLocalDB)
                    .filter(TestCaseLocalDB.team_id == team_id, TestCaseLocalDB.test_case_number == item.test_case_number)
                    .first()
                )
                if not test_case:
                    errors.append(f"index {idx}: 找不到測試案例 {item.test_case_number}")
                    continue

                case_set_id = getattr(test_case, "test_case_set_id", None)
                if allowed_scope_ids:
                    if case_set_id not in allowed_scope_ids:
                        errors.append(
                            f"index {idx}: 測試案例 {item.test_case_number} 不在此 Test Run 允許的 Test Case Set 範圍內"
                        )
                        continue
                elif case_set_id is not None:
                    auto_scope_ids.append(case_set_id)

                db_item = TestRunItemDB(
                    team_id=team_id,
                    config_id=config_id,
                    test_case_number=item.test_case_number,
                    assignee_id=item.assignee.id if item.assignee else None,
                    assignee_name=item.assignee.name if item.assignee else None,
                    assignee_en_name=item.assignee.en_name if item.assignee else None,
                    assignee_email=item.assignee.email if item.assignee else None,
                    assignee_json=_to_json(item.assignee.model_dump()) if item.assignee else None,
                    test_result=item.test_result,
                    executed_at=item.executed_at,
                    execution_duration=item.execution_duration,
                )
                sync_db.add(db_item)
                created += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"index {idx}: {exc}")
                continue

        if not allowed_scope_ids and auto_scope_ids:
            inferred_scope = TestRunScopeService.normalize_scope_ids(auto_scope_ids)
            TestRunScopeService.set_config_scope_ids(config_db, inferred_scope)

        return {"created": created, "skipped": skipped, "errors": errors}

    result = await boundary.run_sync_write(_create)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_items_batch_create",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"config_id": config_id, "created_count": result["created"], "skipped_count": result["skipped"]},
    )
    return {
        "success": len(result["errors"]) == 0,
        "created_count": result["created"],
        "skipped_duplicates": result["skipped"],
        "errors": result["errors"],
    }


@router.put("/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}")
async def update_app_test_run_item_result(
    team_id: int,
    config_id: int,
    item_id: int,
    body: TestRunItemUpdate,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Update execution result/assignee for a Test Run Item, requires test_run:execute."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_EXECUTE, request, team_id)

    data = body.model_dump(exclude_unset=True)
    boundary = create_main_access_boundary_for_session(db)

    def _update(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")

        prev_result = item.test_result
        prev_executed_at = item.executed_at

        if "test_result" in data and data["test_result"] is not None:
            item.test_result = data["test_result"]
        if "executed_at" in data:
            item.executed_at = data["executed_at"]
        if "execution_duration" in data:
            item.execution_duration = data["execution_duration"]
        if "assignee_name" in data:
            name = (data.get("assignee_name") or "").strip()
            item.assignee_name = name or None
            if not name:
                item.assignee_id = item.assignee_en_name = item.assignee_email = item.assignee_json = None

        _add_result_history(
            sync_db, item, prev_result, prev_executed_at, item.test_result, item.executed_at,
            source=data.get("change_source") or "app-token",
            reason=data.get("change_reason"),
            changed_by_id=None,
            changed_by_name=principal.audit_actor,
        )

        item.updated_at = datetime.utcnow()
        sync_db.flush()
        sync_db.refresh(item)
        return _db_to_response(item, item.test_case, sync_db)

    response = await boundary.run_sync_write(_update)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_item_result_update",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={"item_id": item_id, "test_result": data.get("test_result")},
    )
    return response


@router.post("/teams/{team_id}/test-run-configs/{config_id}/items/batch-update-results")
async def batch_update_app_test_run_item_results(
    team_id: int,
    config_id: int,
    payload: BatchUpdateResultRequest,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Batch update run item results via app token (requires test_run:execute).

    Shares the per-item update core with the JWT batch endpoint: supports
    test_result / assignee_name / executed_at / comment per update, records
    the same result history, and reports per-item errors without failing the batch.
    """
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_EXECUTE, request, team_id)

    source = payload.change_source or "app-token-batch"
    boundary = create_main_access_boundary_for_session(db)

    def _batch(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        success = 0
        errors: List[str] = []

        for upd in payload.updates:
            try:
                item_id = upd.get("id")
                comment_raw = upd.get("comment") if "comment" in upd else None
                comment_text = comment_raw.strip() if isinstance(comment_raw, str) else None
                has_basic_update = any(key in upd for key in ["test_result", "assignee_name", "executed_at"])
                if not item_id or (not has_basic_update and not comment_text):
                    errors.append("缺少 id 或更新欄位")
                    continue

                item = (
                    sync_db.query(TestRunItemDB)
                    .filter(
                        TestRunItemDB.id == item_id,
                        TestRunItemDB.team_id == team_id,
                        TestRunItemDB.config_id == config_id,
                    )
                    .first()
                )
                if not item:
                    errors.append(f"項目 {item_id} 不存在")
                    continue

                apply_batch_item_update_sync(
                    sync_db,
                    item,
                    upd,
                    source=source,
                    changed_by_id=None,
                    changed_by_name=principal.audit_actor,
                )
                success += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"項目 {upd.get('id')} 更新失敗: {str(e)}")
                continue

        return {"success": success, "errors": errors}

    result = await boundary.run_sync_write(_batch)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_items_batch_update_results",
        action_type=ActionType.UPDATE, team_id=team_id,
        extra_details={
            "config_id": config_id,
            "success_count": result["success"],
            "error_count": len(result["errors"]),
        },
    )
    return {
        "success": len(result["errors"]) == 0,
        "processed_count": len(payload.updates),
        "success_count": result["success"],
        "error_count": len(result["errors"]),
        "error_messages": result["errors"],
    }


@router.delete("/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_app_test_run_item(
    team_id: int,
    config_id: int,
    item_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_ADMIN, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _verify(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")

    await boundary.run_sync_read(_verify)

    cleanup_service = TestResultCleanupService()
    try:
        await cleanup_service.cleanup_test_run_item_files(team_id, config_id, item_id, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to clean up result files for item %s: %s", item_id, exc, exc_info=True)

    from app.models.database_models import TestRunItemResultHistory as ResultHistoryDB

    def _delete(sync_db: Session):
        sync_db.query(ResultHistoryDB).filter(
            ResultHistoryDB.team_id == team_id, ResultHistoryDB.config_id == config_id, ResultHistoryDB.item_id == item_id
        ).delete(synchronize_session=False)
        sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).delete(synchronize_session=False)

    await boundary.run_sync_write(_delete)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_item_delete",
        action_type=ActionType.DELETE, team_id=team_id,
        extra_details={"item_id": item_id, "config_id": config_id},
    )


@router.post(
    "/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/upload-results",
    status_code=status.HTTP_201_CREATED,
)
async def upload_app_test_run_item_results(
    team_id: int,
    config_id: int,
    item_id: int,
    request: Request,
    files: List[UploadFile] = File(...),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
    db=Depends(get_db),
):
    """Upload execution result files for a Test Run Item (requires test_run:execute).

    Stores files under ``<attachments>/test-runs/{team}/{config}/{item}/`` and records
    them in the item's ``execution_results_json`` / ``result_files_*`` / ``upload_history_json``,
    matching the JWT ``/upload-results`` schema.
    """
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_EXECUTE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _load(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")
        existing = json.loads(item.execution_results_json) if item.execution_results_json else []
        history = json.loads(item.upload_history_json) if item.upload_history_json else []
        return {
            "existing": existing if isinstance(existing, list) else [],
            "history": history if isinstance(history, list) else [],
        }

    ctx = await boundary.run_sync_read(_load)
    existing = ctx["existing"]
    history = ctx["history"]

    root_dir = get_attachments_root_dir()
    target_dir = root_dir / "test-runs" / str(team_id) / str(config_id) / str(item_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")
    uploaded: List[Dict[str, Any]] = []
    for f in files:
        orig_name = f.filename or "unnamed"
        stored_name = f"{ts}-{safe_re.sub('_', orig_name)}"
        stored_path = target_dir / stored_name
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

    history.append({"uploaded": len(uploaded), "at": datetime.utcnow().isoformat(), "files": uploaded})
    execution_results_json = json.dumps(existing, ensure_ascii=False)
    upload_history_json = json.dumps(history, ensure_ascii=False)

    def _save(sync_db: Session):
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")
        item.execution_results_json = execution_results_json
        item.result_files_uploaded = 1 if len(existing) > 0 else 0
        item.result_files_count = len(existing)
        item.upload_history_json = upload_history_json
        item.updated_at = datetime.utcnow()

    await boundary.run_sync_write(_save)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_item_results_upload",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"item_id": item_id, "config_id": config_id, "uploaded_count": len(uploaded)},
    )
    return {
        "success": True,
        "uploaded_files": len(uploaded),
        "upload_details": uploaded,
        "base_url": "/attachments",
    }


# --------------------------------------------------------------------- bug tickets


@router.get("/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets")
async def list_app_test_run_item_bug_tickets(
    team_id: int,
    config_id: int,
    item_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_READ, request, team_id)

    boundary = create_main_access_boundary_for_session(db)

    def _get(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")
        if not item.bug_tickets_json:
            return []
        try:
            data = json.loads(item.bug_tickets_json)
            return data if isinstance(data, list) else []
        except (TypeError, ValueError):
            return []

    return await boundary.run_sync_read(_get)


@router.post("/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets", status_code=status.HTTP_201_CREATED)
async def add_app_test_run_item_bug_ticket(
    team_id: int,
    config_id: int,
    item_id: int,
    body: Dict[str, Any],
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_EXECUTE, request, team_id)

    ticket_number = str(body.get("ticket_number") or "").strip().upper()
    if not ticket_number:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ticket_number is required")

    boundary = create_main_access_boundary_for_session(db)

    def _add(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")

        existing_tickets = []
        if item.bug_tickets_json:
            try:
                parsed = json.loads(item.bug_tickets_json)
                if isinstance(parsed, list):
                    existing_tickets = parsed
            except (TypeError, ValueError):
                existing_tickets = []

        for ticket in existing_tickets:
            if isinstance(ticket, dict) and str(ticket.get("ticket_number", "")).upper() == ticket_number:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Bug ticket {ticket_number} already exists")

        new_ticket = {"ticket_number": ticket_number, "created_at": datetime.utcnow().isoformat()}
        existing_tickets.append(new_ticket)
        item.bug_tickets_json = json.dumps(existing_tickets, ensure_ascii=False)
        item.updated_at = datetime.utcnow()
        sync_db.flush()
        return new_ticket

    ticket = await boundary.run_sync_write(_add)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_item_bug_ticket_add",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"item_id": item_id, "ticket_number": ticket_number},
    )
    return ticket


@router.delete(
    "/teams/{team_id}/test-run-configs/{config_id}/items/{item_id}/bug-tickets/{ticket_number}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_app_test_run_item_bug_ticket(
    team_id: int,
    config_id: int,
    item_id: int,
    ticket_number: str,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_EXECUTE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)
    target = ticket_number.strip().upper()

    def _remove(sync_db: Session):
        _verify_team_and_config(team_id, config_id, sync_db)
        item = sync_db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id, TestRunItemDB.team_id == team_id, TestRunItemDB.config_id == config_id
        ).first()
        if not item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run item not found")

        existing_tickets = []
        if item.bug_tickets_json:
            try:
                parsed = json.loads(item.bug_tickets_json)
                if isinstance(parsed, list):
                    existing_tickets = parsed
            except (TypeError, ValueError):
                existing_tickets = []

        remaining = [t for t in existing_tickets if str(t.get("ticket_number", "")).upper() != target]
        if len(remaining) == len(existing_tickets):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Bug ticket {target} not found")

        item.bug_tickets_json = json.dumps(remaining, ensure_ascii=False)
        item.updated_at = datetime.utcnow()
        sync_db.flush()

    await boundary.run_sync_write(_remove)
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_item_bug_ticket_remove",
        action_type=ActionType.DELETE, team_id=team_id,
        extra_details={"item_id": item_id, "ticket_number": target},
    )


# --------------------------------------------------------------------- reports


@router.post("/teams/{team_id}/test-run-sets/{set_id}/generate-report")
async def generate_app_test_run_set_report(
    team_id: int,
    set_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Generate the Test Run Set HTML report, requires test_run:write."""
    await require_app_team_access(team_id, request, principal)
    await _check_scope(principal, SCOPE_TEST_RUN_WRITE, request, team_id)

    boundary = create_main_access_boundary_for_session(db)
    await boundary.run_sync_read(lambda sync_db: ensure_test_run_set(sync_db, team_id, set_id))

    from app.services.html_report_service import HTMLReportService

    service = HTMLReportService(db_session=db)
    try:
        result = await service.generate_test_run_set_report(team_id=team_id, set_id=set_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Report generation failed: {exc}")

    base = str(request.base_url).rstrip("/")
    await log_app_token_audit(
        request, principal, allowed=True, reason="test_run_set_report_generate",
        action_type=ActionType.CREATE, team_id=team_id,
        extra_details={"set_id": set_id, "report_id": result["report_id"]},
    )
    return {
        "success": True,
        "report_id": result["report_id"],
        "report_url": f"{base}{result['report_url']}",
        "generated_at": result.get("generated_at"),
        "overwritten": result.get("overwritten", True),
    }


@router.get("/teams/{team_id}/test-run-sets/{set_id}/report")
async def get_app_test_run_set_report_status(
    team_id: int,
    set_id: int,
    request: Request,
    db=Depends(get_db),
    principal: AppTokenPrincipal = Depends(get_current_app_token_principal),
):
    """Look up whether a Test Run Set report exists; requires test_run:read or test_run:write."""
    await require_app_team_access(team_id, request, principal)
    if not principal.has_any_scope(SCOPE_TEST_RUN_READ, SCOPE_TEST_RUN_WRITE):
        await log_app_token_audit(
            request, principal, allowed=False, reason="scope_denied:test_run:read", team_id=team_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": AppTokenErrorCodes.SCOPE_DENIED, "message": "Missing test_run:read scope"},
        )

    boundary = create_main_access_boundary_for_session(db)
    await boundary.run_sync_read(lambda sync_db: ensure_test_run_set(sync_db, team_id, set_id))

    from app.services.html_report_service import HTMLReportService

    service = HTMLReportService(db_session=db)
    report_id = f"team-{team_id}-set-{set_id}"
    report_path = service.report_root / f"{report_id}.html"
    exists = report_path.exists()
    base = str(request.base_url).rstrip("/")
    return {"exists": exists, "report_url": f"{base}/reports/{report_id}.html" if exists else None}
