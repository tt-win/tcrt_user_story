"""Test Run Set API 路由"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.orm import Session, joinedload

from app.database import get_sync_db
from app.models.database_models import (
    TestRunConfig as TestRunConfigDB,
    TestRunSet as TestRunSetDB,
    TestRunSetMembership as TestRunSetMembershipDB,
    TestCaseLocal as TestCaseLocalDB,
    TestRunItem as TestRunItemDB,
)
from app.models.test_run_config import TestRunConfigSummary
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
def list_test_run_sets(
    team_id: int,
    include_archived: bool = Query(False, description="是否包含已歸檔"),
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)

    query = _query_set_with_members(db).filter(TestRunSetDB.team_id == team_id)
    if not include_archived:
        query = query.filter(TestRunSetDB.status != TestRunSetStatus.ARCHIVED)

    sets = query.order_by(TestRunSetDB.created_at.desc()).all()
    return [_build_set_summary(s) for s in sets]


@router.get("/overview", response_model=TestRunSetOverview)
def get_test_run_set_overview(
    team_id: int,
    include_archived: bool = Query(False, description="是否包含已歸檔的 Set"),
    db: Session = Depends(get_sync_db),
):
    """取得 Test Run Set 與未歸組 Test Run 的總覽"""

    verify_team_exists(team_id, db)

    query = _query_set_with_members(db).filter(TestRunSetDB.team_id == team_id)
    if not include_archived:
        query = query.filter(TestRunSetDB.status != TestRunSetStatus.ARCHIVED)

    sets = query.order_by(TestRunSetDB.created_at.desc()).all()
    unassigned_configs = _fetch_unassigned_configs(db, team_id)

    return TestRunSetOverview(
        sets=[_build_set_detail(s) for s in sets],
        unassigned=[build_config_summary(cfg) for cfg in unassigned_configs],
    )


@router.post("/", response_model=TestRunSetDetail, status_code=status.HTTP_201_CREATED)
def create_test_run_set(
    team_id: int,
    payload: TestRunSetCreate,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)

    new_set = TestRunSetDB(
        team_id=team_id,
        name=payload.name,
        description=payload.description,
        status=TestRunSetStatus.ACTIVE,
    )

    db.add(new_set)
    db.flush()

    if payload.related_tp_tickets is not None:
        sync_tp_tickets_to_db(new_set, payload.related_tp_tickets)

    configs = _validate_config_ids(db, team_id, payload.initial_config_ids or [])
    for config_db in configs:
        attach_config_to_set(db, team_id, config_db, new_set.id)

    recalculate_set_status(db, new_set)

    db.commit()
    db.refresh(new_set)

    loaded_set = _load_set_or_404(db, team_id, new_set.id)
    return _build_set_detail(loaded_set)


@router.get("/{set_id}", response_model=TestRunSetDetail)
def get_test_run_set(
    team_id: int,
    set_id: int,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)
    test_run_set = _load_set_or_404(db, team_id, set_id)
    return _build_set_detail(test_run_set)


@router.put("/{set_id}", response_model=TestRunSet)
def update_test_run_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetUpdate,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)
    test_run_set = ensure_test_run_set(db, team_id, set_id)

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

    recalculate_set_status(db, test_run_set)

    db.commit()
    db.refresh(test_run_set)

    resolved_status = resolve_status_for_response(test_run_set)

    return TestRunSet(
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


@router.post("/{set_id}/members", response_model=TestRunSetDetail)
def add_members_to_set(
    team_id: int,
    set_id: int,
    payload: TestRunSetMembershipCreate,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)
    test_run_set = ensure_test_run_set(db, team_id, set_id)

    configs = _validate_config_ids(db, team_id, payload.config_ids)
    for config_db in configs:
        attach_config_to_set(db, team_id, config_db, test_run_set.id)

    recalculate_set_status(db, test_run_set)

    db.commit()
    db.refresh(test_run_set)

    loaded_set = _load_set_or_404(db, team_id, set_id)
    return _build_set_detail(loaded_set)


@router.post("/members/{config_id}/move", response_model=TestRunConfigSummary)
def move_config_between_sets(
    team_id: int,
    config_id: int,
    payload: TestRunSetMembershipMove,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)

    config_db = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id,
    ).first()

    if not config_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到 Test Run Config ID {config_id}"
        )

    previous_set_id = None
    if config_db.set_membership:
        previous_set_id = config_db.set_membership.set_id

    if payload.target_set_id is None:
        detach_config_from_set(db, config_id)
        if previous_set_id is not None:
            previous_set = ensure_test_run_set(db, team_id, previous_set_id)
            recalculate_set_status(db, previous_set)
    else:
        target_set = ensure_test_run_set(db, team_id, payload.target_set_id)
        attach_config_to_set(db, team_id, config_db, target_set.id)
        recalculate_set_status(db, target_set)
        if previous_set_id and previous_set_id != target_set.id:
            previous_set = ensure_test_run_set(db, team_id, previous_set_id)
            recalculate_set_status(db, previous_set)

    db.commit()
    db.refresh(config_db)
    db.expire(config_db, ['set_membership'])

    return build_config_summary(config_db)


@router.delete("/{set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run_set(
    team_id: int,
    set_id: int,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)
    test_run_set = _load_set_or_404(db, team_id, set_id)

    try:
        for membership in list(test_run_set.memberships):
            if membership.config:
                await delete_test_run_config_cascade(db, team_id, membership.config)
        db.delete(test_run_set)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{set_id}/archive", response_model=TestRunSet)
def archive_test_run_set(
    team_id: int,
    set_id: int,
    db: Session = Depends(get_sync_db),
):
    verify_team_exists(team_id, db)
    test_run_set = ensure_test_run_set(db, team_id, set_id)

    test_run_set.status = TestRunSetStatus.ARCHIVED
    test_run_set.archived_at = datetime.utcnow()

    db.commit()
    db.refresh(test_run_set)

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


@router.get("/search/tp", response_model=List[TestRunSetSummary])
def search_test_run_sets_by_tp_tickets(
    team_id: int,
    q: str = Query(..., min_length=2, max_length=50, description="搜尋查詢字串（TP 票號）"),
    limit: int = Query(20, ge=1, le=100, description="最大返回結果數"),
    db: Session = Depends(get_sync_db),
):
    """根據 TP 票號搜尋 Test Run Set"""

    verify_team_exists(team_id, db)

    search_query = q.strip().upper()
    if not _is_valid_tp_search_query(search_query):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="搜尋查詢必須包含 TP 票號相關內容",
        )

    query = (
        db.query(TestRunSetDB)
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


# ============ USM Integration: Create Test Run with Test Cases ============
@router.post("/from-test-cases")
def create_test_run_from_test_cases(
    team_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_sync_db),
):
    """
    从选定的测试案例创建 Test Run
    
    Parameters:
        team_id: 团队 ID
        payload: {
            "name": "Test Run 名称",
            "test_case_records": [record_id1, record_id2, ...],
            "description": "可选描述"
        }
    
    Returns:
        Created TestRunConfig with added test cases
    """
    try:
        verify_team_exists(team_id, db)
        
        name = payload.get("name", "")
        if not name or not name.strip():
            raise HTTPException(status_code=400, detail="Test Run 名称不能为空")
        
        test_case_records = payload.get("test_case_records", [])
        if not test_case_records:
            raise HTTPException(status_code=400, detail="必须至少选择一个测试案例")
        
        description = payload.get("description", "")
        
        # Create a Test Run Config
        config = TestRunConfigDB(
            team_id=team_id,
            name=name.strip(),
            description=description,
            status='active',
            total_test_cases=0
        )
        
        db.add(config)
        db.flush()
        
        # Add each test case as a Test Run Item
        for record_id in test_case_records:
            # Get the test case by lark_record_id
            test_case = db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.lark_record_id == record_id,
                TestCaseLocalDB.team_id == team_id
            ).first()
            
            if not test_case:
                continue
            
            # Create Test Run Item for this test case
            item = TestRunItemDB(
                team_id=team_id,
                config_id=config.id,
                test_case_number=test_case.test_case_number
            )
            db.add(item)
        
        db.flush()
        
        # Update test case count
        config.total_test_cases = db.query(TestRunItemDB).filter(
            TestRunItemDB.config_id == config.id
        ).count()
        
        db.commit()
        db.refresh(config)
        
        # Return the created Test Run Config
        return {
            "id": config.id,
            "team_id": config.team_id,
            "name": config.name,
            "description": config.description,
            "status": config.status,
            "total_test_cases": config.total_test_cases,
            "created_at": config.created_at.isoformat() if config.created_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating test run from test cases: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建 Test Run 失败: {str(e)}")
