"""
Test Run Items API

Local CRUD for test run items stored in SQLite, detached from Lark.
Items are created by selecting Test Cases and copying necessary fields.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
from datetime import datetime
import json

from app.database import get_db
from app.models.database_models import (
    TestRunItem as TestRunItemDB,
    TestRunConfig as TestRunConfigDB,
    Team as TeamDB,
)
from app.models.lark_types import Priority, TestResultStatus
from pydantic import BaseModel, Field


router = APIRouter(prefix="/teams/{team_id}/test-run-configs/{config_id}/items", tags=["test-run-items"])


# -------------------- Pydantic Schemas --------------------

class AttachmentItem(BaseModel):
    file_token: str
    name: Optional[str] = None
    size: Optional[int] = None
    type: Optional[str] = None


class LinkedRecord(BaseModel):
    record_ids: List[str]
    table_id: Optional[str] = None
    text: Optional[str] = None
    text_arr: Optional[List[str]] = None
    type: Optional[str] = None


class AssigneeModel(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    en_name: Optional[str] = None
    email: Optional[str] = None


class TestRunItemCreate(BaseModel):
    # Core fields from Test Case
    test_case_number: str
    title: str
    priority: Optional[Priority] = Priority.MEDIUM
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None

    # Assignee
    assignee: Optional[AssigneeModel] = None

    # Initial result (optional)
    test_result: Optional[TestResultStatus] = None
    executed_at: Optional[datetime] = None
    execution_duration: Optional[int] = None

    # Attachments and relations
    attachments: Optional[List[AttachmentItem]] = None
    execution_results: Optional[List[AttachmentItem]] = None
    user_story_map: Optional[List[LinkedRecord]] = None
    tcg: Optional[List[LinkedRecord]] = None
    parent_record: Optional[List[LinkedRecord]] = None
    raw_fields: Optional[Dict[str, Any]] = None


class TestRunItemUpdate(BaseModel):
    title: Optional[str] = None
    priority: Optional[Priority] = None
    precondition: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    assignee: Optional[AssigneeModel] = None
    test_result: Optional[TestResultStatus] = None
    executed_at: Optional[datetime] = None
    execution_duration: Optional[int] = None
    attachments: Optional[List[AttachmentItem]] = None
    execution_results: Optional[List[AttachmentItem]] = None


class TestRunItemResponse(BaseModel):
    id: int
    team_id: int
    config_id: int
    test_case_number: str
    title: str
    priority: Optional[str]
    precondition: Optional[str]
    steps: Optional[str]
    expected_result: Optional[str]
    assignee_id: Optional[str]
    assignee_name: Optional[str]
    assignee_en_name: Optional[str]
    assignee_email: Optional[str]
    test_result: Optional[str]
    executed_at: Optional[datetime]
    execution_duration: Optional[int]
    attachment_count: int = Field(0)
    execution_result_count: int = Field(0)
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class BatchCreateRequest(BaseModel):
    items: List[TestRunItemCreate]


class BatchCreateResponse(BaseModel):
    success: bool
    created_count: int
    skipped_duplicates: int
    errors: List[str] = Field(default_factory=list)


class BatchUpdateResultRequest(BaseModel):
    updates: List[Dict[str, Any]]  # each { id: int, test_result: str, executed_at?: datetime }


def _to_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _len_json_list(text: Optional[str]) -> int:
    if not text:
        return 0
    try:
        data = json.loads(text)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def _verify_team_and_config(team_id: int, config_id: int, db: Session) -> TestRunConfigDB:
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到團隊 ID {team_id}")
    config = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"找不到測試執行配置 ID {config_id}")
    return config


def _db_to_response(item: TestRunItemDB) -> TestRunItemResponse:
    return TestRunItemResponse(
        id=item.id,
        team_id=item.team_id,
        config_id=item.config_id,
        test_case_number=item.test_case_number,
        title=item.title,
        priority=item.priority.value if hasattr(item.priority, 'value') else item.priority,
        precondition=item.precondition,
        steps=item.steps,
        expected_result=item.expected_result,
        assignee_id=item.assignee_id,
        assignee_name=item.assignee_name,
        assignee_en_name=item.assignee_en_name,
        assignee_email=item.assignee_email,
        test_result=item.test_result.value if hasattr(item.test_result, 'value') else item.test_result,
        executed_at=item.executed_at,
        execution_duration=item.execution_duration,
        attachment_count=_len_json_list(item.attachments_json),
        execution_result_count=_len_json_list(item.execution_results_json),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/", response_model=List[TestRunItemResponse])
async def list_items(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db),
    # Filters
    search: Optional[str] = Query(None, description="標題/編號模糊搜尋"),
    priority_filter: Optional[str] = Query(None),
    test_result_filter: Optional[str] = Query(None),
    executed_only: Optional[bool] = Query(None),
    # Sorting
    sort_by: Optional[str] = Query("created_at"),
    sort_order: Optional[str] = Query("desc"),
    # Pagination
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    _verify_team_and_config(team_id, config_id, db)

    q = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    )

    if search:
        s = f"%{search}%"
        q = q.filter((TestRunItemDB.title.like(s)) | (TestRunItemDB.test_case_number.like(s)))

    if priority_filter:
        q = q.filter(TestRunItemDB.priority == priority_filter)
    if test_result_filter:
        q = q.filter(TestRunItemDB.test_result == test_result_filter)
    if executed_only:
        q = q.filter(TestRunItemDB.test_result.isnot(None))

    # Sorting
    sort_map = {
        'created_at': TestRunItemDB.created_at,
        'updated_at': TestRunItemDB.updated_at,
        'priority': TestRunItemDB.priority,
        'test_result': TestRunItemDB.test_result,
        'title': TestRunItemDB.title,
    }
    sort_col = sort_map.get(sort_by, TestRunItemDB.created_at)
    if sort_order.lower() == 'asc':
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    items = q.offset(skip).limit(limit).all()
    return [_db_to_response(i) for i in items]


@router.post("/", response_model=BatchCreateResponse, status_code=status.HTTP_201_CREATED)
async def batch_create_items(
    team_id: int,
    config_id: int,
    payload: BatchCreateRequest,
    db: Session = Depends(get_db)
):
    _verify_team_and_config(team_id, config_id, db)

    created = 0
    skipped = 0
    errors: List[str] = []

    for idx, item in enumerate(payload.items):
        try:
            # Handle duplicates via unique constraint (config_id, test_case_number)
            existing = db.query(TestRunItemDB).filter(
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.config_id == config_id,
                TestRunItemDB.test_case_number == item.test_case_number,
            ).first()
            if existing:
                skipped += 1
                continue

            db_item = TestRunItemDB(
                team_id=team_id,
                config_id=config_id,
                test_case_number=item.test_case_number,
                title=item.title,
                priority=item.priority,
                precondition=item.precondition,
                steps=item.steps,
                expected_result=item.expected_result,
                assignee_id=item.assignee.id if item.assignee else None,
                assignee_name=item.assignee.name if item.assignee else None,
                assignee_en_name=item.assignee.en_name if item.assignee else None,
                assignee_email=item.assignee.email if item.assignee else None,
                assignee_json=_to_json(item.assignee.model_dump()) if item.assignee else None,
                test_result=item.test_result,
                executed_at=item.executed_at,
                execution_duration=item.execution_duration,
                attachments_json=_to_json([a.model_dump() for a in (item.attachments or [])]) if item.attachments else None,
                execution_results_json=_to_json([a.model_dump() for a in (item.execution_results or [])]) if item.execution_results else None,
                user_story_map_json=_to_json([r.model_dump() for r in (item.user_story_map or [])]) if item.user_story_map else None,
                tcg_json=_to_json([r.model_dump() for r in (item.tcg or [])]) if item.tcg else None,
                parent_record_json=_to_json([r.model_dump() for r in (item.parent_record or [])]) if item.parent_record else None,
                raw_fields_json=_to_json(item.raw_fields) if item.raw_fields else None,
            )
            db.add(db_item)
            created += 1
        except Exception as e:
            errors.append(f"index {idx}: {e}")
            continue

    db.commit()

    return BatchCreateResponse(
        success=len(errors) == 0,
        created_count=created,
        skipped_duplicates=skipped,
        errors=errors,
    )


@router.put("/{item_id}", response_model=TestRunItemResponse)
async def update_item(
    team_id: int,
    config_id: int,
    item_id: int,
    payload: TestRunItemUpdate,
    db: Session = Depends(get_db)
):
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")

    data = payload.model_dump(exclude_unset=True)
    # Simple field updates
    for key in ['title', 'precondition', 'steps', 'expected_result', 'execution_duration']:
        if key in data:
            setattr(item, key, data[key])

    if 'priority' in data and data['priority'] is not None:
        item.priority = data['priority']
    if 'test_result' in data and data['test_result'] is not None:
        item.test_result = data['test_result']
    if 'executed_at' in data:
        item.executed_at = data['executed_at']

    # Assignee
    if 'assignee' in data:
        assignee = data['assignee']
        if assignee is None:
            item.assignee_id = item.assignee_name = item.assignee_en_name = item.assignee_email = item.assignee_json = None
        else:
            item.assignee_id = assignee.get('id')
            item.assignee_name = assignee.get('name')
            item.assignee_en_name = assignee.get('en_name')
            item.assignee_email = assignee.get('email')
            item.assignee_json = _to_json(assignee)

    # Attachments
    if 'attachments' in data:
        attachments = data['attachments'] or []
        item.attachments_json = _to_json(attachments)
    if 'execution_results' in data:
        execution_results = data['execution_results'] or []
        item.execution_results_json = _to_json(execution_results)

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _db_to_response(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_db)
):
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")
    db.delete(item)
    db.commit()


@router.post("/batch-update-results", response_model=Dict[str, Any])
async def batch_update_results(
    team_id: int,
    config_id: int,
    payload: BatchUpdateResultRequest,
    db: Session = Depends(get_db)
):
    _verify_team_and_config(team_id, config_id, db)
    success = 0
    errors: List[str] = []
    for upd in payload.updates:
        item_id = upd.get('id')
        result = upd.get('test_result')
        if not item_id or not result:
            errors.append("缺少 id 或 test_result")
            continue
        item = db.query(TestRunItemDB).filter(
            TestRunItemDB.id == item_id,
            TestRunItemDB.team_id == team_id,
            TestRunItemDB.config_id == config_id,
        ).first()
        if not item:
            errors.append(f"項目 {item_id} 不存在")
            continue
        item.test_result = result
        if 'executed_at' in upd:
            item.executed_at = upd.get('executed_at')
        item.updated_at = datetime.utcnow()
        success += 1
    db.commit()
    return {
        "success": len(errors) == 0,
        "processed_count": len(payload.updates),
        "success_count": success,
        "error_count": len(errors),
        "error_messages": errors,
    }


@router.get("/statistics", response_model=Dict[str, Any])
async def get_items_statistics(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    _verify_team_and_config(team_id, config_id, db)
    q = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    )
    total = q.count()
    executed = q.filter(TestRunItemDB.test_result.isnot(None)).count()
    passed = q.filter(TestRunItemDB.test_result == TestResultStatus.PASSED).count()
    failed = q.filter(TestRunItemDB.test_result == TestResultStatus.FAILED).count()
    retest = q.filter(TestRunItemDB.test_result == TestResultStatus.RETEST).count()
    na = q.filter(TestRunItemDB.test_result == TestResultStatus.NOT_AVAILABLE).count()

    execution_rate = (executed / total * 100) if total > 0 else 0.0
    pass_rate = (passed / executed * 100) if executed > 0 else 0.0
    total_pass_rate = (passed / total * 100) if total > 0 else 0.0

    return {
        "total_runs": total,
        "executed_runs": executed,
        "passed_runs": passed,
        "failed_runs": failed,
        "retest_runs": retest,
        "not_available_runs": na,
        "execution_rate": round(execution_rate, 2),
        "pass_rate": round(pass_rate, 2),
        "total_pass_rate": round(total_pass_rate, 2),
    }

