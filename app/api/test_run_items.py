"""
Test Run Items API

Local CRUD for test run items stored in SQLite, detached from Lark.
Items are created by selecting Test Cases and copying necessary fields.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
from datetime import datetime
import json
import logging

from app.services.lark_client import LarkClient
from app.config import settings
from app.models.test_case import TestCase

from app.database import get_db
from app.models.database_models import (
    TestRunItem as TestRunItemDB,
    TestRunConfig as TestRunConfigDB,
    Team as TeamDB,
    TestRunItemResultHistory as ResultHistoryDB,
)
from app.models.lark_types import Priority, TestResultStatus
from pydantic import BaseModel, Field


router = APIRouter(prefix="/teams/{team_id}/test-run-configs/{config_id}/items", tags=["test-run-items"])

@router.post("/{item_id}/upload-results")
async def upload_test_run_results(
    team_id: int,
    config_id: int,
    item_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    上傳測試執行結果檔案到對應的 Test Case
    
    流程：
    1. 驗證 Test Run Item 存在
    2. 取得團隊和表格配置
    3. 轉換檔案名稱使用標準格式
    4. 上傳檔案到 Lark Drive
    5. 更新對應 Test Case 的 Test Results Files 欄位
    6. 記錄上傳歷史到本地資料庫
    """
    from fastapi import File, UploadFile
    from app.services.test_result_file_service import TestCaseResultFileManager
    import json
    
    # 驗證 Test Run Item 存在
    test_run_item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.team_id == team_id
    ).first()
    
    if not test_run_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行項目 ID {item_id}"
        )
    
    # 取得團隊配置
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    try:
        # 使用共用輔助函數初始化 Lark 服務
        lark_client, team_config = _get_lark_client_for_team(team_id, db)
        result_file_manager = TestCaseResultFileManager(lark_client)
        
        # 查詢 Test Case 以取得 record_id
        records = lark_client.get_all_records(team.test_case_table_id)
        
        target_record = None
        for record in records:
            fields = record.get('fields', {})
            if fields.get(TestCase.FIELD_IDS['test_case_number']) == test_run_item.test_case_number:
                target_record = record
                break
        
        if not target_record:
            return {
                "success": False,
                "message": "檔案上傳失敗",
                "error_messages": [f"找不到 Test Case {test_run_item.test_case_number}"]
            }
        
        # 上傳結果檔案
        result = await result_file_manager.attach_test_run_results(
            test_run_item_id=item_id,
            test_case_number=test_run_item.test_case_number,
            test_case_record_id=target_record.get('record_id', ''),
            files=files,
            team_wiki_token=team.wiki_token,
            test_case_table_id=team.test_case_table_id
        )
        
        if result['success']:
            # 更新本地 Test Run Item 記錄
            test_run_item.result_files_uploaded = True
            test_run_item.result_files_count = result['uploaded_files']
            test_run_item.upload_history_json = json.dumps(result['upload_history'], ensure_ascii=False)
            
            db.commit()
            
            return {
                "success": True,
                "message": f"成功上傳 {result['uploaded_files']} 個結果檔案到 Test Case {test_run_item.test_case_number}",
                "uploaded_files": result['uploaded_files'],
                "upload_details": result['upload_results']
            }
        else:
            return {
                "success": False,
                "message": "檔案上傳失敗",
                "error_messages": result['error_messages']
            }
            
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"上傳結果檔案時發生錯誤: {str(e)}"
        )


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
    assignee_name: Optional[str] = None
    test_result: Optional[TestResultStatus] = None
    executed_at: Optional[datetime] = None
    execution_duration: Optional[int] = None
    attachments: Optional[List[AttachmentItem]] = None
    execution_results: Optional[List[AttachmentItem]] = None
    # Optional: 變更原因（寫入歷程）
    change_reason: Optional[str] = None
    change_source: Optional[str] = None  # single, api


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


class ResultHistoryItem(BaseModel):
    id: int
    item_id: int
    prev_result: Optional[str] = None
    new_result: Optional[str] = None
    prev_executed_at: Optional[datetime] = None
    new_executed_at: Optional[datetime] = None
    changed_by_id: Optional[str] = None
    changed_by_name: Optional[str] = None
    change_source: Optional[str] = None
    change_reason: Optional[str] = None
    changed_at: datetime


class BatchCreateRequest(BaseModel):
    items: List[TestRunItemCreate]


class BatchCreateResponse(BaseModel):
    success: bool
    created_count: int
    skipped_duplicates: int
    errors: List[str] = Field(default_factory=list)


class BatchUpdateResultRequest(BaseModel):
    updates: List[Dict[str, Any]]  # each { id: int, test_result?: str, executed_at?: datetime, assignee_name?: str, change_reason?: str }
    change_source: Optional[str] = None  # batch


class BugTicketRequest(BaseModel):
    ticket_number: str = Field(..., description="JIRA ticket number (e.g., PRJ-123)")


class BugTicketResponse(BaseModel):
    ticket_number: str
    created_at: datetime


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

def _get_lark_client_for_team(team_id: int, db: Session):
    """獲取配置好的 LarkClient 實例"""
    team_config = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="團隊配置不存在"
        )
    
    lark_client = LarkClient(
        app_id=settings.lark.app_id,
        app_secret=settings.lark.app_secret
    )
    lark_client.set_wiki_token(team_config.wiki_token)
    return lark_client, team_config


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


def _add_result_history(db: Session, item: TestRunItemDB,
                        prev_result, prev_executed_at,
                        new_result, new_executed_at,
                        source: Optional[str] = None,
                        reason: Optional[str] = None,
                        changed_by_id: Optional[str] = None,
                        changed_by_name: Optional[str] = None):
    # 僅在真的有變更時寫入
    if prev_result == new_result and prev_executed_at == new_executed_at:
        return
    rec = ResultHistoryDB(
        team_id=item.team_id,
        config_id=item.config_id,
        item_id=item.id,
        prev_result=prev_result,
        new_result=new_result,
        prev_executed_at=prev_executed_at,
        new_executed_at=new_executed_at,
        changed_by_id=changed_by_id,
        changed_by_name=changed_by_name or 'web',
        change_source=source or 'single',
        change_reason=reason,
        changed_at=datetime.utcnow()
    )
    db.add(rec)


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
    prev_result = item.test_result
    prev_executed_at = item.executed_at
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

    # Assignee (object form)
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

    # Assignee (simple name form)
    if 'assignee_name' in data:
        name = (data.get('assignee_name') or '').strip()
        if name:
            item.assignee_name = name
            item.assignee_id = None
            item.assignee_en_name = None
            item.assignee_email = None
            item.assignee_json = None
        else:
            item.assignee_id = None
            item.assignee_name = None
            item.assignee_en_name = None
            item.assignee_email = None
            item.assignee_json = None

    # Attachments
    if 'attachments' in data:
        attachments = data['attachments'] or []
        item.attachments_json = _to_json(attachments)
    if 'execution_results' in data:
        execution_results = data['execution_results'] or []
        item.execution_results_json = _to_json(execution_results)

    # 記錄歷程（若有變更）
    _add_result_history(
        db, item,
        prev_result, prev_executed_at,
        item.test_result, item.executed_at,
        source=data.get('change_source') or 'single',
        reason=data.get('change_reason'),
        changed_by_id=None,
        changed_by_name=None
    )

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
    # 保險刪除對應歷程（避免 DB 未啟用 FK 級聯時殘留）
    db.query(ResultHistoryDB).filter(
        ResultHistoryDB.team_id == team_id,
        ResultHistoryDB.config_id == config_id,
        ResultHistoryDB.item_id == item_id,
    ).delete(synchronize_session=False)
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
    source = payload.change_source or 'batch'
    for upd in payload.updates:
        try:
            item_id = upd.get('id')
            # 檢查是否至少有一個要更新的欄位
            if not item_id or not any(key in upd for key in ['test_result', 'assignee_name', 'executed_at']):
                errors.append("缺少 id 或更新欄位")
                continue

            item = db.query(TestRunItemDB).filter(
                TestRunItemDB.id == item_id,
                TestRunItemDB.team_id == team_id,
                TestRunItemDB.config_id == config_id,
            ).first()
            if not item:
                errors.append(f"項目 {item_id} 不存在")
                continue

            prev_result = item.test_result
            prev_executed_at = item.executed_at

            # 更新測試結果
            if 'test_result' in upd and upd['test_result'] is not None:
                item.test_result = upd['test_result']

            # 更新執行時間
            if 'executed_at' in upd:
                executed_at_value = upd.get('executed_at')
                if executed_at_value:
                    # 處理 ISO 字串格式的 datetime
                    if isinstance(executed_at_value, str):
                        try:
                            if executed_at_value.endswith('Z'):
                                executed_at_value = executed_at_value[:-1] + '+00:00'
                            item.executed_at = datetime.fromisoformat(executed_at_value.replace('Z', '+00:00'))
                        except Exception:
                            item.executed_at = datetime.utcnow()
                    else:
                        item.executed_at = executed_at_value
                else:
                    item.executed_at = datetime.utcnow()

            # 更新執行者
            if 'assignee_name' in upd:
                assignee_name = upd.get('assignee_name')
                if assignee_name:
                    item.assignee_name = assignee_name
                    item.assignee_id = None
                    item.assignee_en_name = None
                    item.assignee_email = None
                    item.assignee_json = None
                else:
                    item.assignee_id = None
                    item.assignee_name = None
                    item.assignee_en_name = None
                    item.assignee_email = None
                    item.assignee_json = None

            # 記錄歷程（僅在有變更時會落盤）
            _add_result_history(
                db, item,
                prev_result, prev_executed_at,
                item.test_result, item.executed_at,
                source=source,
                reason=upd.get('change_reason')
            )

            item.updated_at = datetime.utcnow()
            success += 1
        except Exception as e:
            errors.append(f"項目 {upd.get('id')} 更新失敗: {str(e)}")
            continue
    db.commit()
    return {
        "success": len(errors) == 0,
        "processed_count": len(payload.updates),
        "success_count": success,
        "error_count": len(errors),
        "error_messages": errors,
    }


@router.get("/{item_id}/result-history", response_model=List[ResultHistoryItem])
async def get_result_history(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200)
):
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")

    q = db.query(ResultHistoryDB).filter(
        ResultHistoryDB.team_id == team_id,
        ResultHistoryDB.config_id == config_id,
        ResultHistoryDB.item_id == item_id,
    ).order_by(ResultHistoryDB.changed_at.desc())
    records = q.offset(skip).limit(limit).all()
    def _map(r: ResultHistoryDB) -> ResultHistoryItem:
        return ResultHistoryItem(
            id=r.id,
            item_id=r.item_id,
            prev_result=r.prev_result.value if hasattr(r.prev_result, 'value') else r.prev_result,
            new_result=r.new_result.value if hasattr(r.new_result, 'value') else r.new_result,
            prev_executed_at=r.prev_executed_at,
            new_executed_at=r.new_executed_at,
            changed_by_id=r.changed_by_id,
            changed_by_name=r.changed_by_name,
            change_source=r.change_source,
            change_reason=r.change_reason,
            changed_at=r.changed_at,
        )
    return [_map(r) for r in records]


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

    # 計算 Bug Tickets 統計
    bug_tickets_count = 0
    unique_bug_tickets = set()
    
    # 查詢所有有 bug_tickets_json 的項目
    items_with_bugs = q.filter(TestRunItemDB.bug_tickets_json.isnot(None)).all()
    
    for item in items_with_bugs:
        if item.bug_tickets_json:
            try:
                tickets_data = json.loads(item.bug_tickets_json)
                if isinstance(tickets_data, list):
                    for ticket in tickets_data:
                        if isinstance(ticket, dict) and 'ticket_number' in ticket:
                            unique_bug_tickets.add(ticket['ticket_number'].upper())
            except Exception:
                pass  # 忽略解析錯誤的項目
    
    bug_tickets_count = len(unique_bug_tickets)

    return {
        "total_runs": total,
        "executed_runs": executed,
        "passed_runs": passed,
        "failed_runs": failed,
        "retest_runs": retest,
        "not_available_runs": na,
        "unique_bug_tickets_count": bug_tickets_count,
        # 無條件捨去為整數
        "execution_rate": int(execution_rate // 1),
        "pass_rate": int(pass_rate // 1),
        "total_pass_rate": int(total_pass_rate // 1),
    }


# -------------------- Bug Tickets Management --------------------

@router.get("/bug-tickets/summary")
async def get_bug_tickets_summary(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """取得該 Test Run 的 Bug Tickets 摘要資訊"""
    from ..config import settings
    from ..services.jira_client import JiraClient
    
    _verify_team_and_config(team_id, config_id, db)
    
    # 查詢所有有 bug_tickets_json 的項目
    items = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.bug_tickets_json.isnot(None)
    ).all()
    
    bug_tickets_data = {}  # ticket_number -> {'ticket_info': {...}, 'test_cases': [...]}
    
    for item in items:
        if item.bug_tickets_json:
            try:
                tickets_data = json.loads(item.bug_tickets_json)
                if isinstance(tickets_data, list):
                    for ticket in tickets_data:
                        if isinstance(ticket, dict) and 'ticket_number' in ticket:
                            ticket_number = ticket['ticket_number'].upper()
                            
                            # 初始化 ticket 資料
                            if ticket_number not in bug_tickets_data:
                                bug_tickets_data[ticket_number] = {
                                    'ticket_info': {
                                        'ticket_number': ticket_number,
                                        'status': {'name': 'Unknown', 'id': ''},
                                        'summary': '',
                                        'url': f"{settings.jira.server_url}/browse/{ticket_number}" if settings.jira.server_url else ''
                                    },
                                    'test_cases': []
                                }
                            
                            # 添加測試案例
                            bug_tickets_data[ticket_number]['test_cases'].append({
                                'item_id': item.id,
                                'test_case_number': item.test_case_number,
                                'title': item.title or '',
                                'test_result': item.test_result
                            })
            except Exception:
                pass  # 忽略解析錯誤的項目
    
    # 嘗試從 JIRA API 取得實際的票券資訊
    try:
        jira_client = JiraClient()
        for ticket_number, ticket_data in bug_tickets_data.items():
            try:
                jira_info = jira_client.get_issue(
                    ticket_number,
                    fields=['summary', 'status']
                )
                if jira_info and 'fields' in jira_info:
                    fields = jira_info['fields']
                    if 'summary' in fields and fields['summary']:
                        ticket_data['ticket_info']['summary'] = fields['summary']
                    if 'status' in fields and fields['status']:
                        ticket_data['ticket_info']['status'] = {
                            'name': fields['status'].get('name', 'Unknown'),
                            'id': fields['status'].get('id', '')
                        }
            except Exception as e:
                # JIRA API 調用失敗時保持預設值
                print(f"Failed to get JIRA info for {ticket_number}: {e}")
                continue
    except Exception as e:
        # JIRA Client 初始化失敗時保持預設值
        print(f"Failed to initialize JIRA client: {e}")
        pass
    
    # 轉換為回應格式
    summary_data = {
        'total_unique_tickets': len(bug_tickets_data),
        'tickets': list(bug_tickets_data.values())
    }
    
    return summary_data

@router.get("/{item_id}/bug-tickets", response_model=List[BugTicketResponse])
async def get_bug_tickets(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_db)
):
    """取得測試項目的 Bug Tickets 清單"""
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")
    
    # 解析 bug_tickets_json
    bug_tickets = []
    if item.bug_tickets_json:
        try:
            tickets_data = json.loads(item.bug_tickets_json)
            if isinstance(tickets_data, list):
                for ticket in tickets_data:
                    if isinstance(ticket, dict) and 'ticket_number' in ticket:
                        bug_tickets.append(BugTicketResponse(
                            ticket_number=ticket['ticket_number'],
                            created_at=datetime.fromisoformat(ticket.get('created_at', datetime.utcnow().isoformat()))
                        ))
        except Exception:
            pass  # 如果解析失敗，返回空列表
    
    return bug_tickets


@router.post("/{item_id}/bug-tickets", response_model=BugTicketResponse, status_code=status.HTTP_201_CREATED)
async def add_bug_ticket(
    team_id: int,
    config_id: int,
    item_id: int,
    payload: BugTicketRequest,
    db: Session = Depends(get_db)
):
    """新增 Bug Ticket 到測試項目"""
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")
    
    # 解析現有的 bug_tickets_json
    existing_tickets = []
    if item.bug_tickets_json:
        try:
            tickets_data = json.loads(item.bug_tickets_json)
            if isinstance(tickets_data, list):
                existing_tickets = tickets_data
        except Exception:
            existing_tickets = []
    
    # 檢查是否已存在相同的 ticket number
    ticket_number = payload.ticket_number.strip().upper()
    for ticket in existing_tickets:
        if isinstance(ticket, dict) and ticket.get('ticket_number', '').upper() == ticket_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bug ticket {ticket_number} 已存在"
            )
    
    # 新增 ticket
    new_ticket = {
        'ticket_number': ticket_number,
        'created_at': datetime.utcnow().isoformat()
    }
    existing_tickets.append(new_ticket)
    
    # 更新資料庫
    item.bug_tickets_json = json.dumps(existing_tickets, ensure_ascii=False)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    
    return BugTicketResponse(
        ticket_number=new_ticket['ticket_number'],
        created_at=datetime.fromisoformat(new_ticket['created_at'])
    )


@router.delete("/{item_id}/bug-tickets/{ticket_number}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bug_ticket(
    team_id: int,
    config_id: int,
    item_id: int,
    ticket_number: str,
    db: Session = Depends(get_db)
):
    """刪除測試項目的指定 Bug Ticket"""
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")
    
    # 解析現有的 bug_tickets_json
    existing_tickets = []
    if item.bug_tickets_json:
        try:
            tickets_data = json.loads(item.bug_tickets_json)
            if isinstance(tickets_data, list):
                existing_tickets = tickets_data
        except Exception:
            existing_tickets = []
    
    # 尋找並移除指定的 ticket
    ticket_number_upper = ticket_number.strip().upper()
    original_count = len(existing_tickets)
    existing_tickets = [ticket for ticket in existing_tickets 
                      if not (isinstance(ticket, dict) and 
                             ticket.get('ticket_number', '').upper() == ticket_number_upper)]
    
    if len(existing_tickets) == original_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bug ticket {ticket_number} 不存在"
        )
    
    # 更新資料庫
    item.bug_tickets_json = json.dumps(existing_tickets, ensure_ascii=False) if existing_tickets else None
    item.updated_at = datetime.utcnow()
    db.commit()


# -------------------- Test Results Management --------------------

@router.get("/{item_id}/test-results")
async def get_test_run_results(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_db)
):
    """
    獲取 Test Run Item 的測試結果檔案
    
    Returns:
        測試結果檔案列表和統計資訊
    """
    _verify_team_and_config(team_id, config_id, db)
    
    # 驗證 Test Run Item 存在
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test Run Item 不存在"
        )
    
    try:
        # 使用共用輔助函數初始化 Lark 服務
        lark_client, team_config = _get_lark_client_for_team(team_id, db)
        
        # 從 Lark 取得所有記錄，然後找到指定的記錄
        records = lark_client.get_all_records(team_config.test_case_table_id)
        
        target_record = None
        for record in records:
            fields = record.get('fields', {})
            if fields.get(TestCase.FIELD_IDS['test_case_number']) == item.test_case_number:
                target_record = record
                break
        
        if not target_record:
            return {
                "test_results_files": [],
                "files_count": 0,
                "total_size": 0
            }
        
        # 轉換為 TestCase 模型
        test_case = TestCase.from_lark_record(target_record, team_config.id)
        
        # 提取測試結果檔案
        test_results_files = test_case.test_results_files or []
        
        # 計算統計資訊
        files_count = len(test_results_files)
        total_size = sum(file.size for file in test_results_files if hasattr(file, 'size') and file.size)
        
        return {
            "test_results_files": [
                {
                    "file_token": file.file_token,
                    "name": file.name,
                    "size": getattr(file, 'size', 0),
                    "uploaded_at": getattr(file, 'uploaded_at', None) or getattr(file, 'created_at', None),
                    "content_type": getattr(file, 'content_type', 'application/octet-stream')
                }
                for file in test_results_files
            ],
            "files_count": files_count,
            "total_size": total_size
        }
        
    except Exception as e:
        logging.error(f"獲取測試結果檔案失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取測試結果檔案失敗: {str(e)}"
        )


@router.delete("/{item_id}/test-results/{file_token}")
async def delete_test_result_file(
    team_id: int,
    config_id: int,
    item_id: int,
    file_token: str,
    db: Session = Depends(get_db)
):
    """
    刪除單一測試結果檔案
    
    Flow:
    1. 驗證檔案屬於該 Test Run Item
    2. 從 Test Case 的 Test Results Files 欄位中移除檔案
    3. 更新本地追蹤記錄
    """
    _verify_team_and_config(team_id, config_id, db)
    
    # 驗證 Test Run Item 存在
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.id == item_id
    ).first()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test Run Item 不存在"
        )
    
    try:
        # 使用共用輔助函數初始化 Lark 服務
        lark_client, team_config = _get_lark_client_for_team(team_id, db)
        
        # 從 Lark 取得所有記錄，然後找到指定的記錄
        records = lark_client.get_all_records(team_config.test_case_table_id)
        
        target_record = None
        for record in records:
            fields = record.get('fields', {})
            if fields.get(TestCase.FIELD_IDS['test_case_number']) == item.test_case_number:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Test Case 不存在"
            )
        
        # 轉換為 TestCase 模型
        test_case = TestCase.from_lark_record(target_record, team_config.id)
        
        # 檢查檔案是否存在於 Test Results Files 中
        test_results_files = test_case.test_results_files or []
        file_to_remove = None
        
        for file in test_results_files:
            if file.file_token == file_token:
                file_to_remove = file
                break
        
        if not file_to_remove:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="檔案不存在於測試結果中"
            )
        
        # 從列表中移除檔案
        remaining_files = [f for f in test_results_files if f.file_token != file_token]
        
        # 更新 Lark Test Case 記錄的 Test Results Files 欄位
        success = lark_client.update_record_attachment(
            team_config.test_case_table_id,
            test_case.record_id,
            'Test Results Files',
            [f.file_token for f in remaining_files],
            team_config.wiki_token
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新 Test Case 記錄失敗"
            )
        
        # 更新本地追蹤記錄
        if item.upload_history_json:
            try:
                upload_history = json.loads(item.upload_history_json)
                uploads = upload_history.get('uploads', [])
                
                # 從上傳歷史中移除該檔案
                uploads = [upload for upload in uploads if upload.get('file_token') != file_token]
                
                # 更新統計
                upload_history['uploads'] = uploads
                upload_history['total_uploads'] = len(uploads)
                
                item.upload_history_json = json.dumps(upload_history, ensure_ascii=False) if uploads else None
                item.result_files_count = len(uploads)
                item.result_files_uploaded = len(uploads) > 0
                item.updated_at = datetime.utcnow()
                
                db.commit()
                
            except Exception as e:
                logging.warning(f"更新上傳歷史記錄失敗: {e}")
                # 不影響主要功能
        
        return {
            "success": True,
            "message": "檔案刪除成功",
            "remaining_files_count": len(remaining_files)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"刪除測試結果檔案失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除檔案失敗: {str(e)}"
        )
