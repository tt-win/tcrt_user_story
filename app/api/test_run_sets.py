"""Test Run Set API 路由"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload
from typing import Dict, Any

from app.database import get_db, run_sync
from app.auth.dependencies import get_current_user
from app.models.database_models import User
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity
from app.models.database_models import (
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
    TestCaseLocal as TestCaseLocalDB,
    TestRunItem as TestRunItemDB,
)
from app.models.test_run_config import TestRunConfigSummary, TestRunStatus
from app.models.test_run_set import (
    TestRunSet,
    TestRunSetCreate,
    TestRunSetDetail,
    TestRunSetOverview,
    TestRunSetMembershipCreate,
    TestRunSetMembershipMove,
    TestRunSetStatus,
    TestRunSetSummary,
    TestRunSetUpdate,
)
from app.services.test_run_set_status import (
    recalculate_set_status,
    resolve_status_for_response,
)

from .test_run_configs import (
    attach_config_to_set,
    build_config_summary,
    delete_test_run_config_cascade,
    detach_config_from_set,
    ensure_test_run_set,
    verify_team_exists,
    _is_valid_tp_search_query,
    _filter_matching_tp_tickets,
)


logger = logging.getLogger(__name__)

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
        .joinedload(TestRunConfigDB.set_membership)
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


def _build_set_detail(set_db: TestRunSetDB) -> TestRunSetDetail:
    test_runs: List[TestRunConfigSummary] = []
    for membership in sorted(set_db.memberships, key=lambda m: (m.position or 0, m.id)):
        if membership.config:
            test_runs.append(build_config_summary(membership.config))

    resolved_status = resolve_status_for_response(set_db)

    return TestRunSetDetail(
        id=set_db.id,
        team_id=set_db.team_id,
        name=set_db.name,
        description=set_db.description,
        status=resolved_status,
        archived_at=set_db.archived_at,
        related_tp_tickets=deserialize_tp_tickets(set_db.related_tp_tickets_json),
        created_at=set_db.created_at,
        updated_at=set_db.updated_at,
        test_runs=test_runs,
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
    db: AsyncSession = Depends(get_db),
):
    def _list(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        query = _query_set_with_members(sync_db).filter(TestRunSetDB.team_id == team_id)
        if not include_archived:
            query = query.filter(TestRunSetDB.status != TestRunSetStatus.ARCHIVED)

        sets = query.order_by(TestRunSetDB.created_at.desc()).all()
        return [_build_set_summary(s) for s in sets]

    return await run_sync(db, _list)


@router.get("/overview", response_model=TestRunSetOverview)
async def get_test_run_set_overview(
    team_id: int,
    include_archived: bool = Query(False, description="是否包含已歸檔的 Set"),
    db: AsyncSession = Depends(get_db),
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

    return await run_sync(db, _overview)


@router.post("/", response_model=TestRunSetDetail, status_code=status.HTTP_201_CREATED)
async def create_test_run_set(
    team_id: int,
    payload: TestRunSetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    def _create(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        new_set = TestRunSetDB(
            team_id=team_id,
            name=payload.name,
            description=payload.description,
            status=TestRunSetStatus.ACTIVE,
        )

        sync_db.add(new_set)
        sync_db.flush()

        if payload.related_tp_tickets is not None:
            sync_tp_tickets_to_db(new_set, payload.related_tp_tickets)

        configs = _validate_config_ids(sync_db, team_id, payload.initial_config_ids or [])
        for config_db in configs:
            attach_config_to_set(sync_db, team_id, config_db, new_set.id)

        sync_db.commit()
        sync_db.refresh(new_set)

        return {
            "audit": {
                "set_id": new_set.id,
                "name": new_set.name,
                "description": new_set.description,
                "config_count": len(configs),
            }
        }

    result = await run_sync(db, _create)
    set_id = result["audit"]["set_id"]
    created_set = await db.get(TestRunSetDB, set_id)
    if created_set and created_set.team_id == team_id:
        await recalculate_set_status(db, created_set)
        await db.commit()

    detail = await run_sync(db, lambda sync_db: _build_set_detail(_load_set_or_404(sync_db, team_id, set_id)))

    # 記錄審計日誌
    action_brief = f"{current_user.username} created Test Run Set: {result['audit']['name']}"
    await log_test_run_set_action(
        action_type=ActionType.CREATE,
        current_user=current_user,
        team_id=team_id,
        resource_id=str(result["audit"]["set_id"]),
        action_brief=action_brief,
        details=result["audit"],
    )

    return detail


@router.get("/{set_id}", response_model=TestRunSetDetail)
async def get_test_run_set(
    team_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
):
    def _get(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = _load_set_or_404(sync_db, team_id, set_id)
        return _build_set_detail(test_run_set)

    return await run_sync(db, _get)


@router.put("/{set_id}", response_model=TestRunSet)
async def update_test_run_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetUpdate,
    db: AsyncSession = Depends(get_db),
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

        for key, value in update_data.items():
            setattr(test_run_set, key, value)

        sync_db.commit()
        sync_db.refresh(test_run_set)

        # 記錄審計日誌
        changes = []
        if "name" in update_data and old_name != test_run_set.name:
            changes.append(f"name: {old_name} -> {test_run_set.name}")
        if "status" in update_data and old_status != test_run_set.status:
            changes.append(f"status: {old_status} -> {test_run_set.status}")
        if "description" in update_data:
            changes.append("description updated")

        return {
            "changes": changes,
            "set_id": test_run_set.id,
            "set_name": test_run_set.name,
            "old_status": old_status,
            "old_name": old_name,
        }

    result = await run_sync(db, _update)
    set_id = result["set_id"]
    updated_set = await db.get(TestRunSetDB, set_id)
    if updated_set and updated_set.team_id == team_id:
        await recalculate_set_status(db, updated_set)
        await db.commit()

    def _build_response(sync_db: Session):
        test_run_set = _load_set_or_404(sync_db, team_id, set_id)
        resolved_status = resolve_status_for_response(test_run_set)
        response = TestRunSet(
            id=test_run_set.id,
            team_id=test_run_set.team_id,
            name=test_run_set.name,
            description=test_run_set.description,
            status=resolved_status,
            archived_at=test_run_set.archived_at,
            related_tp_tickets=deserialize_tp_tickets(test_run_set.related_tp_tickets_json),
            created_at=test_run_set.created_at,
            updated_at=test_run_set.updated_at,
        )
        return response, test_run_set.status

    response, new_status = await run_sync(db, _build_response)

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


@router.post("/{set_id}/members", response_model=TestRunSetDetail)
async def add_members_to_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetMembershipCreate,
    db: AsyncSession = Depends(get_db),
):
    def _add(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = ensure_test_run_set(sync_db, team_id, set_id)

        configs = _validate_config_ids(sync_db, team_id, payload.config_ids)
        for config_db in configs:
            attach_config_to_set(sync_db, team_id, config_db, test_run_set.id)

        sync_db.commit()
        sync_db.refresh(test_run_set)

        return test_run_set.id

    set_id = await run_sync(db, _add)
    updated_set = await db.get(TestRunSetDB, set_id)
    if updated_set and updated_set.team_id == team_id:
        await recalculate_set_status(db, updated_set)
        await db.commit()

    return await run_sync(db, lambda sync_db: _build_set_detail(_load_set_or_404(sync_db, team_id, set_id)))


@router.post("/members/{config_id}/move", response_model=TestRunConfigSummary)
async def move_config_between_sets(
    team_id: int,
    config_id: int,
    payload: TestRunSetMembershipMove,
    db: AsyncSession = Depends(get_db),
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

        sync_db.commit()
        sync_db.refresh(config_db)
        sync_db.expire(config_db, ['set_membership'])

        return {
            "summary": build_config_summary(config_db),
            "affected_set_ids": list(affected_set_ids),
        }

    result = await run_sync(db, _move)
    affected_set_ids = result.get("affected_set_ids") or []
    for set_id in affected_set_ids:
        set_db = await db.get(TestRunSetDB, set_id)
        if set_db and set_db.team_id == team_id:
            await recalculate_set_status(db, set_db)
    if affected_set_ids:
        await db.commit()

    return result["summary"]


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run_set(
    team_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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
        context = await run_sync(db, _prepare)

        # 2. 再刪除 Configs (傳入 detach=False 以避免重複刪除 membership)
        for config_id in context["config_ids"]:
            await delete_test_run_config_cascade(db, team_id, config_id, detach=False)

        await run_sync(db, lambda sync_db: sync_db.commit())

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
        await run_sync(db, lambda sync_db: sync_db.rollback())
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{set_id}/archive", response_model=TestRunSet)
async def archive_test_run_set(
    team_id: int,
    set_id: int,
    db: AsyncSession = Depends(get_db),
):
    def _archive(sync_db: Session):
        verify_team_exists(team_id, sync_db)
        test_run_set = ensure_test_run_set(sync_db, team_id, set_id)

        test_run_set.status = TestRunSetStatus.ARCHIVED
        test_run_set.archived_at = datetime.utcnow()

        sync_db.commit()
        sync_db.refresh(test_run_set)

        return TestRunSet(
            id=test_run_set.id,
            team_id=test_run_set.team_id,
            name=test_run_set.name,
            description=test_run_set.description,
            status=test_run_set.status,
            archived_at=test_run_set.archived_at,
            related_tp_tickets=deserialize_tp_tickets(test_run_set.related_tp_tickets_json),
            created_at=test_run_set.created_at,
            updated_at=test_run_set.updated_at,
        )

    return await run_sync(db, _archive)


@router.post("/{set_id}/generate-html")
async def generate_test_run_set_html_report(
    team_id: int,
    set_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """生成 Test Run Set 的靜態 HTML 報告並回傳可存取連結"""
    try:
        await run_sync(db, lambda sync_db: verify_team_exists(team_id, sync_db))
        await run_sync(db, lambda sync_db: _load_set_or_404(sync_db, team_id, set_id))

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
):
    """查詢 Test Run Set 的 HTML 報告是否存在，存在則回傳連結"""
    await run_sync(db, lambda sync_db: verify_team_exists(team_id, sync_db))
    await run_sync(db, lambda sync_db: _load_set_or_404(sync_db, team_id, set_id))

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
    db: AsyncSession = Depends(get_db),
):
    """根據 TP 票號搜尋 Test Run Set"""
    def _search(sync_db: Session):
        verify_team_exists(team_id, sync_db)

        search_query = q.strip().upper()
        if not _is_valid_tp_search_query(search_query):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="搜尋查詢必須包含 TP 票號相關內容",
            )

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

    return await run_sync(db, _search)


# ============ USM Integration: Create Test Run with Test Cases ============
@router.post("/from-test-cases", response_model=TestRunSetDetail)
async def create_test_run_set_from_cases(
    team_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
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

            sync_db.commit()
            sync_db.refresh(new_set)

            return {
                "audit": {
                    "set_id": new_set.id,
                    "name": new_set.name,
                    "config_count": len(configs_created),
                    "groups": list(ticket_groups.keys()),
                    "source": "from_test_cases",
                },
            }

        result = await run_sync(db, _create)
        set_id = result["audit"]["set_id"]
        created_set = await db.get(TestRunSetDB, set_id)
        if created_set and created_set.team_id == team_id:
            await recalculate_set_status(db, created_set)
            await db.commit()

        detail = await run_sync(db, lambda sync_db: _build_set_detail(_load_set_or_404(sync_db, team_id, set_id)))

        # 記錄審計日誌
        action_brief = f"{current_user.username} created Test Run Set from cases: {result['audit']['name']}"
        await log_test_run_set_action(
            action_type=ActionType.CREATE,
            current_user=current_user,
            team_id=team_id,
            resource_id=str(result["audit"]["set_id"]),
            action_brief=action_brief,
            details=result["audit"],
        )

        return detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating test run set from cases: {str(e)}", exc_info=True)
        await run_sync(db, lambda sync_db: sync_db.rollback())
        raise HTTPException(status_code=500, detail=f"建立 Test Run Set 失敗: {str(e)}")
