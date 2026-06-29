"""Test Run Set API 路由"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload
from typing import Dict, Any

from app.db_access import MainAccessBoundary, get_main_access_boundary
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.database_models import (
    AutomationRunStatus,
    AutomationRunTrigger,
    Team,
    User,
)
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity
from app.models.automation_run import AutomationRunListResponse, AutomationRunResponse
from app.models.database_models import (
    AutomationScript,
    AutomationScriptCaseLink,
    AutomationScriptGroup,
    AutomationScriptLinkType,
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
    TestCaseLocal as TestCaseLocalDB,
    TestRunItem as TestRunItemDB,
)
from app.models.test_run_config import TestRunConfigSummary, TestRunStatus
from app.models.test_run_set import (
    AutomationSuiteSummary,
    TestRunSet,
    TestRunSetAutomationCoveredCases,
    TestRunSetCreate,
    TestRunSetDetail,
    TestRunSetOverview,
    TestRunSetMembershipCreate,
    TestRunSetMembershipMove,
    TestRunSetStatus,
    TestRunSetSummary,
    TestRunSetUpdate,
    _deserialize_suite_ids,
    _serialize_suite_ids,
)
from app.services.automation.run_service import (
    AutomationRunAlreadyTerminalError,
    AutomationRunExternalIdMissingError,
    AutomationRunNotFoundError,
    AutomationRunService,
    AutomationRunServiceError,
    automation_run_to_dict,
)
from app.services.automation.provider_registry import (
    ProviderNotConfiguredError,
    ProviderRegistryError,
)
from app.services.test_run_set_status import (
    recalculate_set_status_sync,
    resolve_status_for_response,
)

from .test_run_configs import (
    attach_config_to_set,
    build_config_summary,
    delete_test_run_config_cascade_sync,
    detach_config_from_set,
    ensure_test_run_set,
    verify_team_exists,
    _is_valid_tp_search_query,
    _filter_matching_tp_tickets,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- run helpers
# (replaces the removed automation_runs.py endpoints; the new home of run
#  history is /test-run-sets/{set_id}/runs; see move-run-history-to-test-run-set)


class AutomationRunReconcileRequest(BaseModel):
    external_run_id: Optional[str] = Field(default=None, max_length=120)


class TestRunSetRunAutomationRequest(BaseModel):
    suite_id: Optional[int] = Field(default=None, ge=1)
    environment: Optional[str] = Field(
        default=None,
        max_length=60,
        description=(
            "Automation environment name to run against. Overrides the set's "
            "default_automation_environment; falls back to the team catalog "
            "default. See manage-automation-environment-configs."
        ),
    )


async def _run_write(main_boundary: MainAccessBoundary, operation):
    try:
        return await main_boundary.run_write(operation)
    except AutomationRunAlreadyTerminalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_RUN_ALREADY_TERMINAL", "message": str(exc)},
        ) from exc
    except AutomationRunExternalIdMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_EXTERNAL_ID_MISSING", "message": str(exc)},
        ) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except (AutomationRunServiceError, ProviderRegistryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        ) from exc


def _run_not_found_in_set(run_id: int, set_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "AUTOMATION_RUN_NOT_IN_SET",
            "message": f"Run {run_id} is not part of Test Run Set {set_id}",
        },
    )


async def _log_run_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    try:
        role_value = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.AUTOMATION_RUN,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.INFO,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
    except Exception as exc:
        logger.warning("Failed to write automation run audit log: %s", exc, exc_info=True)

router = APIRouter(prefix="/teams/{team_id}/test-run-sets", tags=["test-run-sets"])


async def log_test_run_set_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """記錄 Test Run Set 相關的審計日誌"""
    try:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.TEST_RUN,
            resource_id=resource_id,
            team_id=team_id,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("寫入 Test Run Set 審計記錄失敗: %s", exc, exc_info=True)


def serialize_tp_tickets(tp_tickets: Optional[List[str]]) -> tuple[Optional[str], Optional[str]]:
    if not tp_tickets:
        return None, None

    json_string = json.dumps(tp_tickets)
    search_string = " ".join(tp_tickets)
    return json_string, search_string


def deserialize_tp_tickets(json_string: Optional[str]) -> List[str]:
    if not json_string:
        return []

    try:
        tickets = json.loads(json_string)
        return tickets if isinstance(tickets, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def sync_tp_tickets_to_db(set_db: TestRunSetDB, tp_tickets: Optional[List[str]]) -> None:
    json_string, search_string = serialize_tp_tickets(tp_tickets)
    set_db.related_tp_tickets_json = json_string
    set_db.tp_tickets_search = search_string


def _query_set_with_members(db: Session):
    return db.query(TestRunSetDB).options(
        joinedload(TestRunSetDB.memberships)
        .joinedload(TestRunSetMembershipDB.config)
        .joinedload(TestRunConfigDB.set_membership),
        joinedload(TestRunSetDB.team).joinedload(Team.automation_script_groups),
    )


def _build_set_summary(set_db: TestRunSetDB) -> TestRunSetSummary:
    resolved_status = resolve_status_for_response(set_db)
    return TestRunSetSummary(
        id=set_db.id,
        name=set_db.name,
        status=resolved_status,
        test_run_count=len(set_db.memberships),
        related_tp_tickets=deserialize_tp_tickets(set_db.related_tp_tickets_json),
        created_at=set_db.created_at,
        updated_at=set_db.updated_at,
    )


def _query_automation_covered_case_rows(
    sync_db: Session, team_id: int, suite_ids: List[int]
) -> list:
    """Distinct (id, test_case_number) rows of cases covered by the suites.

    Coverage = a PRIMARY/COVERS link from any script belonging to any of the
    given suites. Shared by the covered-cases endpoint and the set detail
    automation_covered_case_count field.
    """
    if not suite_ids:
        return []

    suites = (
        sync_db.query(AutomationScriptGroup)
        .filter(
            AutomationScriptGroup.id.in_(suite_ids),
            AutomationScriptGroup.team_id == team_id,
        )
        .all()
    )
    script_ids: set[int] = set()
    for suite in suites:
        try:
            paths = json.loads(suite.script_paths_json or "[]")
        except (TypeError, ValueError):
            paths = []
        if not isinstance(paths, list) or not paths:
            continue
        rows = (
            sync_db.query(AutomationScript.id)
            .filter(
                AutomationScript.team_id == team_id,
                AutomationScript.ref_repo == (suite.ref_repo or ""),
                AutomationScript.ref_path.in_([str(p) for p in paths]),
            )
            .all()
        )
        script_ids.update(int(row.id) for row in rows)

    if not script_ids:
        return []

    return (
        sync_db.query(TestCaseLocalDB.id, TestCaseLocalDB.test_case_number)
        .join(
            AutomationScriptCaseLink,
            AutomationScriptCaseLink.test_case_id == TestCaseLocalDB.id,
        )
        .filter(
            AutomationScriptCaseLink.team_id == team_id,
            AutomationScriptCaseLink.automation_script_id.in_(script_ids),
            AutomationScriptCaseLink.link_type.in_(
                [AutomationScriptLinkType.PRIMARY, AutomationScriptLinkType.COVERS]
            ),
        )
        .distinct()
        .all()
    )


def _build_set_detail(
    set_db: TestRunSetDB, automation_covered_case_count: int = 0
) -> TestRunSetDetail:
    test_runs: List[TestRunConfigSummary] = []
    for membership in sorted(set_db.memberships, key=lambda m: (m.position or 0, m.id)):
        if membership.config:
            test_runs.append(build_config_summary(membership.config))

    resolved_status = resolve_status_for_response(set_db)
    suite_ids = _deserialize_suite_ids(set_db.automation_suite_ids_json)
    suites_by_id: dict[int, AutomationScriptGroup] = {}
    if suite_ids:
        suite_rows = (
            set_db.team.automation_script_groups if getattr(set_db, "team", None) else []
        ) or []
        suites_by_id = {
            int(s.id): s
            for s in suite_rows
            if s is not None and int(getattr(s, "team_id", 0)) == int(set_db.team_id)
        }

    automation_suites: List[AutomationSuiteSummary] = []
    for sid in suite_ids:
        suite = suites_by_id.get(int(sid))
        if not suite:
            continue
        try:
            script_paths = json.loads(suite.script_paths_json or "[]")
        except (TypeError, ValueError):
            script_paths = []
        script_count = len(script_paths) if isinstance(script_paths, list) else 0
        automation_suites.append(
            AutomationSuiteSummary(
                id=suite.id,
                name=suite.name,
                script_count=script_count,
                ci_job_name=suite.ci_job_name,
                ref_branch=None,
            )
        )

    return TestRunSetDetail(
        id=set_db.id,
        team_id=set_db.team_id,
        name=set_db.name,
        description=set_db.description,
        status=resolved_status,
        archived_at=set_db.archived_at,
        related_tp_tickets=deserialize_tp_tickets(set_db.related_tp_tickets_json),
        automation_suite_ids=suite_ids,
        default_automation_environment=set_db.default_automation_environment,
        created_at=set_db.created_at,
        updated_at=set_db.updated_at,
        test_runs=test_runs,
        automation_suites=automation_suites,
        automation_covered_case_count=automation_covered_case_count,
    )


def _fetch_unassigned_configs(db: Session, team_id: int) -> List[TestRunConfigDB]:
    configs = (
        db.query(TestRunConfigDB)
        .outerjoin(
            TestRunSetMembershipDB,
            TestRunSetMembershipDB.config_id == TestRunConfigDB.id,
        )
        .filter(
            TestRunConfigDB.team_id == team_id,
            TestRunSetMembershipDB.id.is_(None),
        )
        .order_by(TestRunConfigDB.created_at.desc())
        .all()
    )
    return configs


def _load_set_or_404(db: Session, team_id: int, set_id: int) -> TestRunSetDB:
    test_run_set = (
        _query_set_with_members(db)
        .filter(TestRunSetDB.id == set_id, TestRunSetDB.team_id == team_id)
        .first()
    )
    if not test_run_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到 Test Run Set ID {set_id}"
        )
    return test_run_set


def _validate_config_ids(
    db: Session,
    team_id: int,
    config_ids: List[int]
) -> List[TestRunConfigDB]:
    if not config_ids:
        return []

    configs = (
        db.query(TestRunConfigDB)
        .filter(TestRunConfigDB.id.in_(config_ids), TestRunConfigDB.team_id == team_id)
        .all()
    )

    if len(configs) != len(set(config_ids)):
        existing_ids = {cfg.id for cfg in configs}
        missing = [cfg_id for cfg_id in config_ids if cfg_id not in existing_ids]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"下列 Test Run Config 不存在或不屬於當前團隊: {missing}"
        )

    return configs


@router.get("/", response_model=List[TestRunSetSummary])
async def list_test_run_sets(
    team_id: int,
    include_archived: bool = Query(False, description="是否包含已歸檔"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    def _list(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        query = _query_set_with_members(sync_db).filter(TestRunSetDB.team_id == team_id)
        if not include_archived:
            query = query.filter(TestRunSetDB.status != TestRunSetStatus.ARCHIVED)

        sets = query.order_by(TestRunSetDB.created_at.desc()).all()
        return [_build_set_summary(s) for s in sets]

    return await main_boundary.run_sync_read(_list)


@router.get("/overview", response_model=TestRunSetOverview)
async def get_test_run_set_overview(
    team_id: int,
    include_archived: bool = Query(False, description="是否包含已歸檔的 Set"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """取得 Test Run Set 與未歸組 Test Run 的總覽"""
    def _overview(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        query = _query_set_with_members(sync_db).filter(TestRunSetDB.team_id == team_id)
        if not include_archived:
            query = query.filter(TestRunSetDB.status != TestRunSetStatus.ARCHIVED)

        sets = query.order_by(TestRunSetDB.created_at.desc()).all()
        unassigned_configs = _fetch_unassigned_configs(sync_db, team_id)

        return TestRunSetOverview(
            sets=[_build_set_detail(s) for s in sets],
            unassigned=[build_config_summary(cfg) for cfg in unassigned_configs],
        )

    return await main_boundary.run_sync_read(_overview)


@router.post("/", response_model=TestRunSetDetail, status_code=status.HTTP_201_CREATED)
async def create_test_run_set(
    team_id: int,
    payload: TestRunSetCreate,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    def _create(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        new_set = TestRunSetDB(
            team_id=team_id,
            name=payload.name,
            description=payload.description,
            status=TestRunSetStatus.ACTIVE,
            automation_suite_ids_json=_serialize_suite_ids(
                payload.automation_suite_ids
            ),
            default_automation_environment=payload.default_automation_environment or None,
        )

        sync_db.add(new_set)
        sync_db.flush()

        if payload.related_tp_tickets is not None:
            sync_tp_tickets_to_db(new_set, payload.related_tp_tickets)

        configs = _validate_config_ids(sync_db, team_id, payload.initial_config_ids or [])
        for config_db in configs:
            attach_config_to_set(sync_db, team_id, config_db, new_set.id)

        new_status = recalculate_set_status_sync(sync_db, new_set)
        sync_db.flush()
        detail = _build_set_detail(_load_set_or_404(sync_db, team_id, new_set.id))

        return detail, {
            "set_id": new_set.id,
            "name": new_set.name,
            "description": new_set.description,
            "config_count": len(configs),
            "status": new_status,
        }

    detail, audit_context = await main_boundary.run_sync_write(_create)

    # 記錄審計日誌
    action_brief = f"{current_user.username} created Test Run Set: {audit_context['name']}"
    await log_test_run_set_action(
        action_type=ActionType.CREATE,
        current_user=current_user,
        team_id=team_id,
        resource_id=str(audit_context["set_id"]),
        action_brief=action_brief,
        details=audit_context,
    )

    return detail


@router.get("/{set_id}", response_model=TestRunSetDetail)
async def get_test_run_set(
    team_id: int,
    set_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    def _get(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = _load_set_or_404(sync_db, team_id, set_id)
        suite_ids = _deserialize_suite_ids(test_run_set.automation_suite_ids_json)
        covered_rows = _query_automation_covered_case_rows(sync_db, team_id, suite_ids)
        return _build_set_detail(
            test_run_set,
            automation_covered_case_count=len({int(row.id) for row in covered_rows}),
        )

    return await main_boundary.run_sync_read(_get)


@router.get("/{set_id}/automation-covered-cases", response_model=TestRunSetAutomationCoveredCases)
async def get_set_automation_covered_cases(
    team_id: int,
    set_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """Test cases already covered by the set's automation suites.

    Coverage = a PRIMARY/COVERS link from any script belonging to any suite
    attached to this set. Case selection uses this to filter out (or badge)
    cases the automation already exercises.
    """

    def _get(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = _load_set_or_404(sync_db, team_id, set_id)
        suite_ids = _deserialize_suite_ids(test_run_set.automation_suite_ids_json)
        link_rows = _query_automation_covered_case_rows(sync_db, team_id, suite_ids)
        if not link_rows:
            return TestRunSetAutomationCoveredCases()
        return TestRunSetAutomationCoveredCases(
            test_case_ids=sorted({int(row.id) for row in link_rows}),
            test_case_numbers=sorted({row.test_case_number for row in link_rows if row.test_case_number}),
        )

    return await main_boundary.run_sync_read(_get)


@router.put("/{set_id}", response_model=TestRunSet)
async def update_test_run_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetUpdate,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    def _update(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = ensure_test_run_set(sync_db, team_id, set_id)

        # 記錄變更前的狀態
        old_status = test_run_set.status
        old_name = test_run_set.name

        update_data = payload.dict(exclude_unset=True)
        if "status" in update_data and update_data["status"] == TestRunSetStatus.ARCHIVED:
            test_run_set.archived_at = datetime.utcnow()
        elif "status" in update_data and update_data["status"] == TestRunSetStatus.ACTIVE:
            test_run_set.archived_at = None

        tp_tickets = update_data.pop("related_tp_tickets", None)
        if tp_tickets is not None:
            sync_tp_tickets_to_db(test_run_set, tp_tickets)

        # automation_suite_ids: list[int] (Pydantic) → automation_suite_ids_json: str
        suite_ids_update = update_data.pop("automation_suite_ids", None)
        if suite_ids_update is not None:
            test_run_set.automation_suite_ids_json = _serialize_suite_ids(
                suite_ids_update
            )

        # default_automation_environment: "" clears the default → store NULL.
        if "default_automation_environment" in update_data:
            env_update = update_data.pop("default_automation_environment")
            test_run_set.default_automation_environment = env_update or None

        for key, value in update_data.items():
            setattr(test_run_set, key, value)

        new_status = recalculate_set_status_sync(sync_db, test_run_set)
        sync_db.flush()

        # 記錄審計日誌
        changes = []
        if "name" in update_data and old_name != test_run_set.name:
            changes.append(f"name: {old_name} -> {test_run_set.name}")
        if "status" in update_data and old_status != new_status:
            changes.append(f"status: {old_status} -> {new_status}")
        if "description" in update_data:
            changes.append("description updated")

        response = TestRunSet(
            id=test_run_set.id,
            team_id=test_run_set.team_id,
            name=test_run_set.name,
            description=test_run_set.description,
            status=new_status,
            archived_at=test_run_set.archived_at,
            related_tp_tickets=deserialize_tp_tickets(test_run_set.related_tp_tickets_json),
            automation_suite_ids=_deserialize_suite_ids(
                test_run_set.automation_suite_ids_json
            ),
            default_automation_environment=test_run_set.default_automation_environment,
            created_at=test_run_set.created_at,
            updated_at=test_run_set.updated_at,
        )

        return response, {
            "changes": changes,
            "set_id": test_run_set.id,
            "set_name": test_run_set.name,
            "old_status": old_status,
            "old_name": old_name,
            "new_status": new_status,
        }

    response, result = await main_boundary.run_sync_write(_update)
    new_status = result["new_status"]

    changes = result["changes"]
    if "name" in payload.dict(exclude_unset=True) and result["old_name"] != response.name:
        changes = [c for c in changes if not c.startswith("name:")] + [f"name: {result['old_name']} -> {response.name}"]
    if "status" in payload.dict(exclude_unset=True) and result["old_status"] != new_status:
        changes = [c for c in changes if not c.startswith("status:")] + [f"status: {result['old_status']} -> {new_status}"]

    action_brief = f"{current_user.username} updated Test Run Set: {response.name}"
    if changes:
        action_brief += f" ({', '.join(changes)})"

    await log_test_run_set_action(
        action_type=ActionType.UPDATE,
        current_user=current_user,
        team_id=team_id,
        resource_id=str(result["set_id"]),
        action_brief=action_brief,
        details={
            "set_id": result["set_id"],
            "changes": changes,
            "new_status": new_status,
        },
    )

    return response


@router.get("/{set_id}/runs", response_model=AutomationRunListResponse)
async def list_test_run_set_runs(
    team_id: int,
    set_id: int,
    run_status: AutomationRunStatus | None = Query(default=None, alias="status"),
    branch: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunListResponse:
    """List every automation run triggered by this Test Run Set.

    This is the new home of run history (replaces the removed
    ``GET /api/teams/{team_id}/automation-runs`` endpoint). The list is
    always filtered by ``test_run_set_id == {set_id}`` and the caller must
    have read access to the team; the set itself is loaded to enforce
    team-scope and surface 404 when the set is missing or cross-team.

    Supports cursor pagination on ``run.id`` and an optional
    ``status`` / ``branch`` filter.
    """
    async def _list(session: AsyncSession) -> AutomationRunListResponse:
        service = AutomationRunService(session)
        rows, next_cursor, total = await service.list_runs(
            team_id=team_id,
            test_run_set_id=set_id,
            status=run_status,
            branch=branch,
            environment=environment,
            cursor=cursor,
            limit=limit,
        )
        return AutomationRunListResponse(
            items=[AutomationRunResponse(**automation_run_to_dict(row)) for row in rows],
            next_cursor=str(next_cursor) if next_cursor is not None else None,
            total=total,
        )

    return await main_boundary.run_read(_list)


@router.get("/{set_id}/runs/{run_id}", response_model=AutomationRunResponse)
async def get_test_run_set_run(
    team_id: int,
    set_id: int,
    run_id: int,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    """Get a single run that belongs to this Test Run Set.

    Returns 404 if the run does not exist **or** does not belong to the
    set — the set-scoping prevents leaking runs from other sets / teams.
    """
    async def _get(session: AsyncSession) -> AutomationRunResponse:
        run_service = AutomationRunService(session)
        try:
            run = await run_service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError as exc:
            raise _run_not_found_in_set(run_id, set_id) from exc
        if run.test_run_set_id != set_id:
            raise _run_not_found_in_set(run_id, set_id)
        return AutomationRunResponse(**automation_run_to_dict(run))

    return await main_boundary.run_read(_get)


@router.post("/{set_id}/runs/{run_id}/cancel", response_model=AutomationRunResponse)
async def cancel_test_run_set_run(
    team_id: int,
    set_id: int,
    run_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    """Cancel a run triggered by this Test Run Set."""
    async def _cancel(session: AsyncSession) -> AutomationRunResponse:
        run_service = AutomationRunService(session)
        try:
            run = await run_service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError as exc:
            raise _run_not_found_in_set(run_id, set_id) from exc
        if run.test_run_set_id != set_id:
            raise _run_not_found_in_set(run_id, set_id)
        return AutomationRunResponse(
            **automation_run_to_dict(
                await run_service.cancel_run(
                    team_id=team_id, run_id=run_id, actor=str(current_user.id)
                )
            )
        )

    response = await _run_write(main_boundary, _cancel)
    await _log_run_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"取消 Test Run Set Run: set={set_id} run={run_id}",
        {
            "test_run_set_id": set_id,
            "external_run_id": response.external_run_id,
            "workflow_id": response.workflow_id,
            "status": response.status,
        },
        request,
    )
    return response


@router.post("/{set_id}/runs/{run_id}/reconcile", response_model=AutomationRunResponse)
async def reconcile_test_run_set_run(
    team_id: int,
    set_id: int,
    run_id: int,
    payload: AutomationRunReconcileRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
) -> AutomationRunResponse:
    """Manually link a run to an external CI run id (only for set-scoped runs)."""
    async def _reconcile(session: AsyncSession) -> AutomationRunResponse:
        run_service = AutomationRunService(session)
        try:
            run = await run_service.get_run(team_id=team_id, run_id=run_id)
        except AutomationRunNotFoundError as exc:
            raise _run_not_found_in_set(run_id, set_id) from exc
        if run.test_run_set_id != set_id:
            raise _run_not_found_in_set(run_id, set_id)
        return AutomationRunResponse(
            **automation_run_to_dict(
                await run_service.reconcile_run(
                    team_id=team_id,
                    run_id=run_id,
                    external_run_id=payload.external_run_id,
                    actor=str(current_user.id),
                )
            )
        )

    response = await _run_write(main_boundary, _reconcile)
    await _log_run_action(
        ActionType.UPDATE,
        current_user,
        team_id,
        str(response.id),
        f"對齊 Test Run Set Run: set={set_id} run={run_id}",
        {
            "test_run_set_id": set_id,
            "external_run_id": response.external_run_id,
            "status": response.status,
            "manual_external_run_id": payload.external_run_id,
        },
        request,
    )
    return response


@router.post("/{set_id}/run-automation")
async def run_automation_for_test_run_set(
    team_id: int,
    set_id: int,
    request: Request,
    payload: TestRunSetRunAutomationRequest | None = Body(default=None),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    """Trigger every automation suite associated with this Test Run Set.

    Replaces the removed ``POST /automation-scripts/{id}/runs`` and
    ``POST /automation-script-groups/{id}/runs`` public endpoints. The Test
    Run Set becomes the single trigger entry point; suites that should run
    together are bundled into a set's ``automation_suite_ids`` list.

    Returns:
        ``{"triggered_suite_ids": [int, ...], "run_ids": [int, ...]}``

    Errors:
        - 404 if the set is not found
        - 400 if the set has no automation suites
        - 400 if any suite id does not belong to this team / no longer exists
        - 400 if requested suite_id is not associated with the set
    """
    from app.services.test_run_set_automation_service import (
        TestRunSetAutomationError,
        TestRunSetAutomationService,
        TestRunSetEmptySuitesError,
        TestRunSetNotFoundError,
        TestRunSetSuiteCrossTeamError,
        TestRunSetSuiteNotFoundError,
        TestRunSetSuiteNotInSetError,
    )
    from app.services.automation.script_group_service import (
        AutomationScriptGroupCIApiError,
        AutomationEnvironmentIncompleteError,
        AutomationEnvironmentRequiredError,
    )
    from app.models.database_models import AutomationRun, AutomationScriptGroup
    from sqlalchemy import select as sa_select

    async def _run_async(async_db: AsyncSession) -> dict[str, list[int]]:
        service = TestRunSetAutomationService(async_db)
        return await service.trigger_automation_suites(
            team_id=team_id,
            set_id=set_id,
            suite_id=payload.suite_id if payload else None,
            actor=str(current_user.id),
            environment=payload.environment if payload else None,
        )

    try:
        result = await main_boundary.run_write(_run_async)
    except TestRunSetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEST_RUN_SET_NOT_FOUND", "message": str(exc)},
        ) from exc
    except TestRunSetEmptySuitesError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_AUTOMATION_SUITES", "message": str(exc)},
        ) from exc
    except (TestRunSetSuiteCrossTeamError, TestRunSetSuiteNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SUITE_INVALID", "message": str(exc)},
        ) from exc
    except TestRunSetSuiteNotInSetError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_SUITE_NOT_IN_SET", "message": str(exc)},
        ) from exc
    except AutomationEnvironmentRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ENVIRONMENT_REQUIRED",
                "message": str(exc),
                "available": exc.available,
            },
        ) from exc
    except AutomationEnvironmentIncompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ENVIRONMENT_INCOMPLETE",
                "message": str(exc),
                "missing": exc.missing,
            },
        ) from exc
    except AutomationScriptGroupCIApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "AUTOMATION_RUN_CI_API_FAILED", "message": str(exc)},
        ) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_PROVIDER_INVALID", "message": str(exc)},
        ) from exc
    except TestRunSetAutomationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "AUTOMATION_RUN_OPERATION_FAILED", "message": str(exc)},
        ) from exc

    # Best-effort audit + outbound webhook for each created run. Failures
    # here MUST NOT roll back the trigger; the runs are already QUEUED on CI.
    for triggered_suite_id, run_id in zip(
        result["triggered_suite_ids"], result["run_ids"]
    ):
        try:
            await main_boundary.run_write(
                lambda db: _audit_run_for_test_run_set(
                    db=db,
                    run_id=run_id,
                    triggered_suite_id=triggered_suite_id,
                    team_id=team_id,
                    current_user=current_user,
                    request=request,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to write Test Run Set automation audit log for run %s: %s",
                run_id, exc, exc_info=True,
            )

    return result


async def _audit_run_for_test_run_set(
    *,
    db: AsyncSession,
    run_id: int,
    triggered_suite_id: int,
    team_id: int,
    current_user: User,
    request: Request,
) -> None:
    """Write a single automation run audit record for a Test Run Set trigger."""
    from app.models.database_models import AutomationRun, AutomationScriptGroup
    from sqlalchemy import select

    row = (
        await db.execute(
            select(AutomationRun, AutomationScriptGroup)
            .join(AutomationScriptGroup, AutomationScriptGroup.id == AutomationRun.script_group_id)
            .where(AutomationRun.id == run_id)
        )
    ).first()
    if row is None:
        return
    run_db, suite_db = row
    role_value = (
        current_user.role.value
        if hasattr(current_user.role, "value")
        else str(current_user.role)
    )
    await audit_service.log_action(
        user_id=current_user.id,
        username=current_user.username,
        role=role_value,
        action_type=ActionType.CREATE,
        resource_type=ResourceType.AUTOMATION_RUN,
        resource_id=str(run_id),
        team_id=team_id,
        details={
            "test_run_set_id": run_db.test_run_set_id,
            "script_group_id": run_db.script_group_id,
            "suite_name": suite_db.name,
            "workflow_id": run_db.workflow_id,
            "branch": run_db.branch,
            "tcrt_correlation_id": run_db.tcrt_correlation_id,
            "trigger_source": "test-run-set",
            "environment": run_db.environment,
        },
        action_brief=(
            f"Test Run Set triggered automation suite: set_id={run_db.test_run_set_id} "
            f"suite_id={run_db.script_group_id} run_id={run_id}"
        ),
        severity=AuditSeverity.INFO,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )


@router.post("/{set_id}/members", response_model=TestRunSetDetail)
async def add_members_to_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetMembershipCreate,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    def _add(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = ensure_test_run_set(sync_db, team_id, set_id)

        configs = _validate_config_ids(sync_db, team_id, payload.config_ids)
        for config_db in configs:
            attach_config_to_set(sync_db, team_id, config_db, test_run_set.id)

        recalculate_set_status_sync(sync_db, test_run_set)
        sync_db.flush()
        return _build_set_detail(_load_set_or_404(sync_db, team_id, test_run_set.id))

    return await main_boundary.run_sync_write(_add)


@router.post("/members/{config_id}/move", response_model=TestRunConfigSummary)
async def move_config_between_sets(
    team_id: int,
    config_id: int,
    payload: TestRunSetMembershipMove,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    def _move(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        config_db = sync_db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id,
            TestRunConfigDB.team_id == team_id,
        ).first()

        if not config_db:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到 Test Run Config ID {config_id}"
            )

        previous_set_id = None
        affected_set_ids = set()
        if config_db.set_membership:
            previous_set_id = config_db.set_membership.set_id
            affected_set_ids.add(previous_set_id)

        if payload.target_set_id is None:
            detach_config_from_set(sync_db, config_id)
            if previous_set_id is not None:
                ensure_test_run_set(sync_db, team_id, previous_set_id)
        else:
            target_set = ensure_test_run_set(sync_db, team_id, payload.target_set_id)
            attach_config_to_set(sync_db, team_id, config_db, target_set.id)
            affected_set_ids.add(target_set.id)
            if previous_set_id and previous_set_id != target_set.id:
                ensure_test_run_set(sync_db, team_id, previous_set_id)

        for affected_set_id in affected_set_ids:
            set_db = ensure_test_run_set(sync_db, team_id, affected_set_id)
            recalculate_set_status_sync(sync_db, set_db)

        sync_db.flush()
        sync_db.expire(config_db, ['set_membership'])

        return build_config_summary(config_db), list(affected_set_ids)

    summary, _affected_set_ids = await main_boundary.run_sync_write(_move)
    return summary


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run_set(
    team_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    from ..services.test_result_cleanup_service import TestResultCleanupService

    def _prepare(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = _load_set_or_404(sync_db, team_id, set_id)

        # 記錄要刪除的 Set 名稱
        set_name = test_run_set.name
        config_count = len(test_run_set.memberships)

        # 預先收集要刪除的 Configs (因為刪除 Set 後 memberships 會被清空)
        config_ids = [m.config.id for m in test_run_set.memberships if m.config]

        # 1. 先刪除 TestRunSet (這會 Cascade 刪除 Memberships)
        sync_db.delete(test_run_set)
        sync_db.flush()  # 強制執行 SQL，確保 DB 中的 Set 和 Memberships 已移除

        return {
            "set_name": set_name,
            "config_count": config_count,
            "config_ids": config_ids,
        }

    try:
        context = await main_boundary.run_sync_read(_prepare)

        cleanup_service = TestResultCleanupService()
        for config_id in context["config_ids"]:
            await cleanup_service.cleanup_test_run_config_files(team_id, config_id, db)

        def _delete(sync_db: Session):
            verify_team_exists(team_id, sync_db)
            test_run_set = _load_set_or_404(sync_db, team_id, set_id)

            sync_db.delete(test_run_set)
            sync_db.flush()

            for config_id in context["config_ids"]:
                delete_test_run_config_cascade_sync(
                    sync_db, team_id, config_id, detach=False
                )

        await main_boundary.run_sync_write(_delete)

        # 記錄審計日誌
        action_brief = f"{current_user.username} deleted Test Run Set: {context['set_name']}"
        await log_test_run_set_action(
            action_type=ActionType.DELETE,
            current_user=current_user,
            team_id=team_id,
            resource_id=str(set_id),
            action_brief=action_brief,
            details={
                "set_id": set_id,
                "set_name": context["set_name"],
                "config_count": context["config_count"],
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{set_id}/archive", response_model=TestRunSet)
async def archive_test_run_set(
    team_id: int,
    set_id: int,
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    def _archive(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = ensure_test_run_set(sync_db, team_id, set_id)

        test_run_set.status = TestRunSetStatus.ARCHIVED
        test_run_set.archived_at = datetime.utcnow()

        return TestRunSet(
            id=test_run_set.id,
            team_id=test_run_set.team_id,
            name=test_run_set.name,
            description=test_run_set.description,
            status=test_run_set.status,
            archived_at=test_run_set.archived_at,
            related_tp_tickets=deserialize_tp_tickets(test_run_set.related_tp_tickets_json),
            automation_suite_ids=_deserialize_suite_ids(
                test_run_set.automation_suite_ids_json
            ),
            default_automation_environment=test_run_set.default_automation_environment,
            created_at=test_run_set.created_at,
            updated_at=test_run_set.updated_at,
        )

    return await main_boundary.run_sync_write(_archive)


@router.post("/{set_id}/generate-html")
async def generate_test_run_set_html_report(
    team_id: int,
    set_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """生成 Test Run Set 的靜態 HTML 報告並回傳可存取連結"""
    try:
        await main_boundary.run_sync_read(lambda sync_db: verify_team_exists(team_id, sync_db))
        await main_boundary.run_sync_read(
            lambda sync_db: _load_set_or_404(sync_db, team_id, set_id)
        )

        from ..services.html_report_service import HTMLReportService

        service = HTMLReportService(db_session=db)
        result = await service.generate_test_run_set_report(team_id=team_id, set_id=set_id)
        base = str(request.base_url).rstrip("/")
        absolute_url = f"{base}{result['report_url']}"
        return {
            "success": True,
            "report_id": result["report_id"],
            "report_url": absolute_url,
            "generated_at": result.get("generated_at"),
            "overwritten": result.get("overwritten", True),
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"HTML 報告生成失敗: {str(e)}",
        )


@router.get("/{set_id}/report", response_model=dict)
async def get_test_run_set_report_status(
    team_id: int,
    set_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """查詢 Test Run Set 的 HTML 報告是否存在，存在則回傳連結"""
    await main_boundary.run_sync_read(lambda sync_db: verify_team_exists(team_id, sync_db))
    await main_boundary.run_sync_read(
        lambda sync_db: _load_set_or_404(sync_db, team_id, set_id)
    )

    from ..services.html_report_service import HTMLReportService

    service = HTMLReportService(db_session=db)
    report_id = f"team-{team_id}-set-{set_id}"
    report_path = service.report_root / f"{report_id}.html"
    exists = report_path.exists()
    result = {"exists": exists, "report_id": report_id}
    base = str(request.base_url).rstrip("/")
    report_url = f"{base}/reports/{result['report_id']}.html"
    return {"exists": result["exists"], "report_url": report_url if result["exists"] else None}


@router.get("/search/tp", response_model=List[TestRunSetSummary])
async def search_test_run_sets_by_tp_tickets(
    team_id: int,
    q: str = Query(..., min_length=2, max_length=50, description="搜尋查詢字串（TP 票號）"),
    limit: int = Query(20, ge=1, le=100, description="最大返回結果數"),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
):
    """根據 TP 票號搜尋 Test Run Set"""
    def _search(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        search_query = q.strip().upper()
        # live-search UX：格式不符時回空列表，不丟 400
        if not _is_valid_tp_search_query(search_query):
            return []

        query = (
            sync_db.query(TestRunSetDB)
            .filter(
                TestRunSetDB.team_id == team_id,
                TestRunSetDB.tp_tickets_search.isnot(None),
                TestRunSetDB.tp_tickets_search.contains(search_query),
            )
            .order_by(TestRunSetDB.updated_at.desc())
            .limit(limit)
        )

        sets_db = query.all()
        summaries: List[TestRunSetSummary] = []
        for set_db in sets_db:
            summary = _build_set_summary(set_db)
            matching = _filter_matching_tp_tickets(
                deserialize_tp_tickets(set_db.related_tp_tickets_json),
                search_query,
            )
            summary.related_tp_tickets = matching
            summaries.append(summary)

        return summaries

    return await main_boundary.run_sync_read(_search)


# ============ USM Integration: Create Test Run with Test Cases ============
@router.post("/from-test-cases", response_model=TestRunSetDetail)
async def create_test_run_set_from_cases(
    team_id: int,
    payload: dict = Body(...),
    main_boundary: MainAccessBoundary = Depends(get_main_access_boundary),
    current_user: User = Depends(get_current_user),
):
    """
    從選定的測試案例建立 Test Run Set，並根據 JIRA Ticket 自動分組建立 Test Run Configs

    Parameters:
        team_id: 團隊 ID
        payload: {
            "name": "Test Run Set 名稱",
            "test_case_records": [record_id1, record_id2, ...],
            "description": "可選描述"
        }

    Returns:
        Created TestRunSetDetail
    """
    try:
        from collections import defaultdict

        def _create(sync_db: Session):
            verify_team_exists(team_id, sync_db)

            name = payload.get("name", "")
            if not name or not name.strip():
                raise HTTPException(status_code=400, detail="Test Run Set 名稱不能為空")

            test_case_records = payload.get("test_case_records", [])
            if not test_case_records:
                raise HTTPException(status_code=400, detail="必須至少選擇一個測試案例")

            description = payload.get("description", "")

            # 1. 建立 Test Run Set
            new_set = TestRunSetDB(
                team_id=team_id,
                name=name.strip(),
                description=description,
                status=TestRunSetStatus.ACTIVE,
                automation_suite_ids_json=None,
            )
            sync_db.add(new_set)
            sync_db.flush()

            # 2. 根據 JIRA Ticket 分組測試案例
            # Key: Ticket Number (e.g., "TCG-123") or "No Ticket"
            # Value: List of TestCaseLocalDB
            ticket_groups: Dict[str, List[TestCaseLocalDB]] = defaultdict(list)
            all_tickets_found = set()

            # 先一次取出所有相關的 Test Case (lark_record_id)
            test_cases = sync_db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.lark_record_id.in_(test_case_records)
            ).all()

            # 建立查找 map
            tc_map = {tc.lark_record_id: tc for tc in test_cases}

            for record_id in test_case_records:
                test_case = tc_map.get(record_id)
                if not test_case:
                    # 嘗試用 ID 查找 (fallback)
                    if str(record_id).isdigit():
                        test_case = sync_db.query(TestCaseLocalDB).filter(
                            TestCaseLocalDB.team_id == team_id,
                            TestCaseLocalDB.id == int(record_id)
                        ).first()

                if not test_case:
                    continue

                # 解析 TCG Json
                tickets = []
                if test_case.tcg_json:
                    try:
                        parsed = json.loads(test_case.tcg_json)
                        if isinstance(parsed, list):
                            tickets = [str(t) for t in parsed if t]
                    except (json.JSONDecodeError, TypeError):
                        pass

                if not tickets:
                    ticket_groups["No Ticket"].append(test_case)
                else:
                    for t in tickets:
                        ticket_groups[t].append(test_case)
                        all_tickets_found.add(t)

            # 3. 為每個分組建立 Test Run Config
            configs_created = []

            # 排序 Groups: No Ticket 最後，其他按字母序
            sorted_groups = sorted(ticket_groups.items(), key=lambda x: (x[0] == "No Ticket", x[0]))

            for ticket, cases in sorted_groups:
                if not cases:
                    continue

                run_name = f"[{ticket}] {name}" if ticket != "No Ticket" else f"[No Ticket] {name}"

                config = TestRunConfigDB(
                    team_id=team_id,
                    name=run_name,
                    description=f"Auto-generated from Set '{name}' for ticket {ticket}",
                    status=TestRunStatus.ACTIVE,  # 直接設為 Active 以便直接開始
                    total_test_cases=len(cases)
                )
                sync_db.add(config)
                sync_db.flush()

                configs_created.append(config)

                # 建立關聯 (Set Membership)
                attach_config_to_set(sync_db, team_id, config, new_set.id)

                # 加入 Test Case Items
                for tc in cases:
                    item = TestRunItemDB(
                        team_id=team_id,
                        config_id=config.id,
                        test_case_number=tc.test_case_number
                    )
                    sync_db.add(item)

            # 更新 Set 的相關票號
            if all_tickets_found:
                sync_tp_tickets_to_db(new_set, list(all_tickets_found))

            new_status = recalculate_set_status_sync(sync_db, new_set)
            sync_db.flush()
            detail = _build_set_detail(_load_set_or_404(sync_db, team_id, new_set.id))

            return detail, {
                "set_id": new_set.id,
                "name": new_set.name,
                "config_count": len(configs_created),
                "groups": list(ticket_groups.keys()),
                "source": "from_test_cases",
                "status": new_status,
            }

        detail, audit_context = await main_boundary.run_sync_write(_create)

        # 記錄審計日誌
        action_brief = f"{current_user.username} created Test Run Set from cases: {audit_context['name']}"
        await log_test_run_set_action(
            action_type=ActionType.CREATE,
            current_user=current_user,
            team_id=team_id,
            resource_id=str(audit_context["set_id"]),
            action_brief=action_brief,
            details=audit_context,
        )

        return detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating test run set from cases: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"建立 Test Run Set 失敗: {str(e)}")
