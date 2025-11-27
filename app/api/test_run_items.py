"""
Test Run Items API

Local CRUD for test run items stored in SQLite, detached from Lark.
Items are created by selecting Test Cases and copying necessary fields.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session, aliased, contains_eager, joinedload
from sqlalchemy import and_, or_
from typing import List, Optional, Any, Dict, Union
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

from app.services.lark_client import LarkClient
from app.config import settings
from app.database import get_db, get_sync_db
from app.models.database_models import (
    TestRunItem as TestRunItemDB,
    TestRunConfig as TestRunConfigDB,
    Team as TeamDB,
    TestRunItemResultHistory as ResultHistoryDB,
    TestCaseLocal as TestCaseLocalDB,
    User,
)
from app.models.lark_types import Priority, TestResultStatus
from pydantic import BaseModel, Field
from app.auth.dependencies import get_current_user
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity


router = APIRouter(prefix="/teams/{team_id}/test-run-configs/{config_id}/items", tags=["test-run-items"])


async def log_test_run_item_action(
    action_type: ActionType,
    current_user: User,
    team_id: int,
    resource_id: str,
    action_brief: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
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
        logger.warning("寫入測試執行項目審計記錄失敗: %s", exc, exc_info=True)


@router.post("/{item_id}/upload-results")
async def upload_test_run_results(
    team_id: int,
    config_id: int,
    item_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_sync_db)
):
    """
    上傳測試執行結果檔案到本地 attachments 目錄，並記錄到本地資料庫。

    調整後流程：
    1. 驗證 Test Run Item 存在
    2. 建立存放路徑：attachments/<team_id>/<config_id>/<item_id>/
    3. 儲存檔案到檔案系統，檔名：{timestamp}-{sanitized-name}
    4. 更新 test_run_items.execution_results_json 與統計欄位
    5. 回傳上傳明細
    """
    import os
    import re
    import json
    from pathlib import Path
    from datetime import datetime

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

    try:
        # 使用設定的附件根目錄（未設定則回退到專案 attachments）
        project_root = Path(__file__).resolve().parents[2]
        from app.config import settings
        base_dir = Path(settings.attachments.root_dir) if settings.attachments.root_dir else (project_root / "attachments")
        # 將測試結果檔案統一放在 attachments/test-runs/{team_id}/{config_id}/{item_id}/
        target_dir = base_dir / "test-runs" / str(team_id) / str(config_id) / str(item_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 既存的結果 JSON
        existing = []
        if test_run_item.execution_results_json:
            try:
                data = json.loads(test_run_item.execution_results_json)
                if isinstance(data, list):
                    existing = data
            except Exception:
                existing = []

        upload_results = []
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
        safe_re = re.compile(r"[^A-Za-z0-9_.\-]+")

        for f in files:
            orig_name = f.filename or "unnamed"
            name_part = safe_re.sub("_", orig_name)
            stored_name = f"{ts}-{name_part}"
            stored_path = target_dir / stored_name

            # 寫檔
            content = await f.read()
            with open(stored_path, "wb") as out:
                out.write(content)

            item_meta = {
                "name": orig_name,
                "stored_name": stored_name,
                "size": len(content),
                "type": f.content_type or "application/octet-stream",
                "relative_path": str(stored_path.relative_to(base_dir)),
                "absolute_path": str(stored_path),
                "uploaded_at": datetime.utcnow().isoformat(),
            }
            existing.append(item_meta)
            upload_results.append(item_meta)

        # 更新 DB 欄位
        test_run_item.execution_results_json = json.dumps(existing, ensure_ascii=False)
        test_run_item.result_files_uploaded = 1 if len(existing) > 0 else 0
        test_run_item.result_files_count = len(existing)
        # 追加上傳歷史
        history = []
        if test_run_item.upload_history_json:
            try:
                history = json.loads(test_run_item.upload_history_json) or []
            except Exception:
                history = []
        history.append({
            "uploaded": len(upload_results),
            "at": datetime.utcnow().isoformat(),
            "files": upload_results,
        })
        test_run_item.upload_history_json = json.dumps(history, ensure_ascii=False)

        db.commit()

        return {
            "success": True,
            "message": f"成功上傳 {len(upload_results)} 個結果檔案（本地）",
            "uploaded_files": len(upload_results),
            "upload_details": upload_results,
            "base_url": "/attachments",
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


LinkedRecordInput = Union[LinkedRecord, Dict[str, Any], str]


class AssigneeModel(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    en_name: Optional[str] = None
    email: Optional[str] = None


class TestRunItemCreate(BaseModel):
    # Core fields from Test Case（僅紀錄編號，其他欄位僅作為兼容性輸入）
    test_case_number: str
    title: Optional[str] = None
    priority: Optional[Priority] = None
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
    user_story_map: Optional[List[LinkedRecordInput]] = None
    tcg: Optional[List[LinkedRecordInput]] = None
    parent_record: Optional[List[LinkedRecordInput]] = None
    raw_fields: Optional[Dict[str, Any]] = None


class TestRunItemUpdate(BaseModel):
    # Snapshot 欄位保留兼容性，但後端將忽略這些變更
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
    title: Optional[str]
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
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    execution_result_count: int = Field(0)
    execution_results: List[Dict[str, Any]] = Field(default_factory=list)
    comment: Optional[str] = None
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


class CommentRequest(BaseModel):
    comment: str = Field(..., description="Comment content")


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


def _parse_execution_results(text: Optional[str]) -> List[Dict[str, Any]]:
    if not text:
        return []
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        results = []
        base_url = "/attachments"
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name') or entry.get('stored_name') or 'file'
            rel = entry.get('relative_path') or ''
            stored = entry.get('stored_name') or name
            results.append({
                "file_token": stored,
                "name": name,
                "size": int(entry.get('size') or 0),
                "url": f"{base_url}/{rel}" if rel else None,
                "uploaded_at": entry.get('uploaded_at'),
                "content_type": entry.get('type') or 'application/octet-stream',
            })
        return results
    except Exception:
        return []


def _normalize_linked_records(records: Optional[List[LinkedRecordInput]]) -> Optional[List[Dict[str, Any]]]:
    """
    將多種來源格式（LinkedRecord/ dict / str）正規化為統一的字典列表，
    以避免前端傳入簡化的字串陣列時觸發驗證錯誤。
    """
    if not records:
        return None

    normalized: List[Dict[str, Any]] = []
    for rec in records:
        if rec is None:
            continue
        if isinstance(rec, LinkedRecord):
            normalized.append(rec.model_dump())
            continue
        if isinstance(rec, dict):
            rid = rec.get("record_ids")
            text_val = rec.get("text") or rec.get("record_id") or rec.get("id")
            if isinstance(rid, list) and rid:
                normalized.append({
                    "record_ids": [str(r) for r in rid if r],
                    "table_id": rec.get("table_id"),
                    "text": rec.get("text"),
                    "text_arr": rec.get("text_arr") if isinstance(rec.get("text_arr"), list) else None,
                    "type": rec.get("type"),
                })
                continue
            if text_val:
                normalized.append({"record_ids": [str(text_val)], "text": str(text_val)})
                continue
        if isinstance(rec, str):
            normalized.append({"record_ids": [rec], "text": rec})
            continue
        try:
            normalized.append({"record_ids": [str(rec)]})
        except Exception:
            continue

    return normalized or None

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


def _db_to_response(item: TestRunItemDB, case: Optional[TestCaseLocalDB] = None, db: Optional[Session] = None) -> TestRunItemResponse:
    exec_results = _parse_execution_results(item.execution_results_json)
    attachments = _parse_execution_results(item.attachments_json)  # 使用相同的解析函數
    test_case = case or getattr(item, 'test_case', None)

    title = None
    priority = None
    precondition = None
    steps = None
    expected_result = None
    comment = None

    if test_case is not None:
        title = getattr(test_case, 'title', None)
        pri_value = getattr(test_case, 'priority', None)
        if pri_value is not None:
            priority = pri_value.value if hasattr(pri_value, 'value') else pri_value
        precondition = getattr(test_case, 'precondition', None)
        steps = getattr(test_case, 'steps', None)
        expected_result = getattr(test_case, 'expected_result', None)

    # 從歷史記錄中取得最新的 comment（change_source = 'comment'）
    if db is not None:
        latest_comment_record = db.query(ResultHistoryDB).filter(
            ResultHistoryDB.team_id == item.team_id,
            ResultHistoryDB.config_id == item.config_id,
            ResultHistoryDB.item_id == item.id,
            ResultHistoryDB.change_source == 'comment'
        ).order_by(ResultHistoryDB.changed_at.desc()).first()

        if latest_comment_record and latest_comment_record.change_reason:
            comment = latest_comment_record.change_reason

    return TestRunItemResponse(
        id=item.id,
        team_id=item.team_id,
        config_id=item.config_id,
        test_case_number=item.test_case_number,
        title=title,
        priority=priority,
        precondition=precondition,
        steps=steps,
        expected_result=expected_result,
        assignee_id=item.assignee_id,
        assignee_name=item.assignee_name,
        assignee_en_name=item.assignee_en_name,
        assignee_email=item.assignee_email,
        test_result=item.test_result.value if hasattr(item.test_result, 'value') else item.test_result,
        executed_at=item.executed_at,
        execution_duration=item.execution_duration,
        attachment_count=_len_json_list(item.attachments_json),
        attachments=attachments,
        execution_result_count=len(exec_results),
        execution_results=exec_results,
        comment=comment,
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
    # 檢查是否有實質性的改變：
    # 1. 測試結果或執行時間改變
    # 2. 或者有提供 change_reason（備註/評論）
    has_result_change = (prev_result != new_result or prev_executed_at != new_executed_at)
    has_reason = reason and reason.strip()
    
    # 只有在有改變或有備註時才寫入
    if not has_result_change and not has_reason:
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
    db: Session = Depends(get_sync_db),
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
    limit: int = Query(100, ge=1, le=10000),
):
    _verify_team_and_config(team_id, config_id, db)

    Tc = aliased(TestCaseLocalDB)
    q = db.query(TestRunItemDB).outerjoin(
        Tc,
        and_(
            TestRunItemDB.team_id == Tc.team_id,
            TestRunItemDB.test_case_number == Tc.test_case_number,
        )
    ).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).options(contains_eager(TestRunItemDB.test_case, alias=Tc))

    if search:
        s = f"%{search}%"
        q = q.filter(
            or_(
                TestRunItemDB.test_case_number.like(s),
                Tc.title.like(s)
            )
        )

    if priority_filter:
        priority_lookup = {p.value.lower(): p for p in Priority}
        priority_value = priority_lookup.get(priority_filter.lower()) if isinstance(priority_filter, str) else None
        if priority_value is not None:
            q = q.filter(Tc.priority == priority_value)
    if test_result_filter:
        q = q.filter(TestRunItemDB.test_result == test_result_filter)
    if executed_only:
        q = q.filter(TestRunItemDB.test_result.isnot(None))

    # Sorting
    sort_map = {
        'created_at': TestRunItemDB.created_at,
        'updated_at': TestRunItemDB.updated_at,
        'priority': Tc.priority,
        'test_result': TestRunItemDB.test_result,
        'title': Tc.title,
    }
    sort_col = sort_map.get(sort_by, TestRunItemDB.created_at)
    if sort_order.lower() == 'asc':
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    items = q.offset(skip).limit(limit).all()
    return [_db_to_response(i, getattr(i, 'test_case', None), db) for i in items]


@router.post("/", response_model=BatchCreateResponse, status_code=status.HTTP_201_CREATED)
async def batch_create_items(
    team_id: int,
    config_id: int,
    payload: BatchCreateRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user),
):
    _verify_team_and_config(team_id, config_id, db)

    created = 0
    skipped = 0
    errors: List[str] = []
    created_items = []  # 記錄建立的項目，用於 audit log

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

            test_case = db.query(TestCaseLocalDB).filter(
                TestCaseLocalDB.team_id == team_id,
                TestCaseLocalDB.test_case_number == item.test_case_number
            ).first()
            if not test_case:
                errors.append(f"index {idx}: 找不到測試案例 {item.test_case_number}")
                continue

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
                attachments_json=_to_json([a.model_dump() for a in (item.attachments or [])]) if item.attachments else None,
                execution_results_json=_to_json([a.model_dump() for a in (item.execution_results or [])]) if item.execution_results else None,
                user_story_map_json=_to_json(_normalize_linked_records(item.user_story_map)),
                tcg_json=_to_json(_normalize_linked_records(item.tcg)),
                parent_record_json=_to_json(_normalize_linked_records(item.parent_record)),
                raw_fields_json=_to_json(item.raw_fields) if item.raw_fields else None,
            )
            db.add(db_item)
            created += 1
            # 記錄建立的項目
            created_items.append({
                "test_case_number": item.test_case_number,
                "title": test_case.title if test_case else None,
            })
        except Exception as e:
            errors.append(f"index {idx}: {e}")
            continue

    db.commit()

    # 記錄批次建立 audit log
    if created > 0:
        test_case_numbers = [item["test_case_number"] for item in created_items]
        action_brief = f"{current_user.username} batch created {created} Test Run Items"
        if test_case_numbers[:3]:
            action_brief += f": {', '.join(test_case_numbers[:3])}"
            if len(test_case_numbers) > 3:
                action_brief += f" and {len(test_case_numbers) - 3} more"

        await log_test_run_item_action(
            action_type=ActionType.CREATE,
            current_user=current_user,
            team_id=team_id,
            resource_id=f"batch_{created}_items",
            action_brief=action_brief,
            details={
                "operation": "batch_create_items",
                "config_id": config_id,
                "created_count": created,
                "skipped_count": skipped,
                "total_count": len(payload.items),
                "created_items": created_items,
            },
        )

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
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user)
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
    # 移除快照類欄位（僅保留兼容性輸入）
    for legacy_field in ['title', 'priority', 'precondition', 'steps', 'expected_result']:
        data.pop(legacy_field, None)
    prev_result = item.test_result
    prev_executed_at = item.executed_at
    # Simple field updates
    for key in ['execution_duration']:
        if key in data:
            setattr(item, key, data[key])

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
        changed_by_id=str(current_user.id) if current_user else None,
        changed_by_name=current_user.full_name or current_user.username if current_user else None
    )

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return _db_to_response(item, item.test_case, db)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_sync_db)
):
    """刪除測試執行項目及相關附件"""
    from ..services.test_result_cleanup_service import TestResultCleanupService
    
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")
    
    try:
        # 1. 先清理測試結果檔案
        cleanup_service = TestResultCleanupService()
        cleaned_files_count = await cleanup_service.cleanup_test_run_item_files(
            team_id, config_id, item_id, db
        )
        
        if cleaned_files_count > 0:
            logger.info(f"Test Run Item {item_id} 已清理 {cleaned_files_count} 個測試結果檔案")
        
        # 2. 保險刪除對應歷程（避免 DB 未啟用 FK 級聯時殘留）
        db.query(ResultHistoryDB).filter(
            ResultHistoryDB.team_id == team_id,
            ResultHistoryDB.config_id == config_id,
            ResultHistoryDB.item_id == item_id,
        ).delete(synchronize_session=False)
        
        # 3. 刪除 Test Run Item
        db.delete(item)
        db.commit()
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/batch-update-results", response_model=Dict[str, Any])
async def batch_update_results(
    team_id: int,
    config_id: int,
    payload: BatchUpdateResultRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user)
):
    _verify_team_and_config(team_id, config_id, db)
    success = 0
    errors: List[str] = []
    success_items = []  # 記錄成功更新的項目，用於 audit log
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
                reason=upd.get('change_reason'),
                changed_by_id=str(current_user.id) if current_user else None,
                changed_by_name=current_user.full_name or current_user.username if current_user else None
            )

            item.updated_at = datetime.utcnow()
            success += 1
            # 記錄成功更新的項目
            success_items.append({
                "item_id": item_id,
                "test_case_number": item.test_case_number,
                "test_result": item.test_result,
            })
        except Exception as e:
            errors.append(f"項目 {upd.get('id')} 更新失敗: {str(e)}")
            continue
    db.commit()

    # 記錄批次更新 audit log
    if success > 0:
        test_case_numbers = [item["test_case_number"] for item in success_items]
        action_brief = f"{current_user.username} batch updated results for {success} Test Run Items"
        if test_case_numbers[:3]:
            action_brief += f": {', '.join(test_case_numbers[:3])}"
            if len(test_case_numbers) > 3:
                action_brief += f" and {len(test_case_numbers) - 3} more"

        await log_test_run_item_action(
            action_type=ActionType.UPDATE,
            current_user=current_user,
            team_id=team_id,
            resource_id=f"batch_{success}_items",
            action_brief=action_brief,
            details={
                "operation": "batch_update_results",
                "config_id": config_id,
                "success_count": success,
                "total_count": len(payload.updates),
                "updated_items": success_items,
            },
        )

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
    db: Session = Depends(get_sync_db),
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
    db: Session = Depends(get_sync_db)
):
    _verify_team_and_config(team_id, config_id, db)
    q = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    )
    total = q.count()
    # Executed exclude Pending, but include Not Required (implicit since it is not None)
    executed = q.filter(and_(TestRunItemDB.test_result.isnot(None), TestRunItemDB.test_result != TestResultStatus.PENDING)).count()
    passed = q.filter(TestRunItemDB.test_result == TestResultStatus.PASSED).count()
    failed = q.filter(TestRunItemDB.test_result == TestResultStatus.FAILED).count()
    retest = q.filter(TestRunItemDB.test_result == TestResultStatus.RETEST).count()
    na = q.filter(TestRunItemDB.test_result == TestResultStatus.NOT_AVAILABLE).count()
    pending = q.filter(TestRunItemDB.test_result == TestResultStatus.PENDING).count()
    not_required = q.filter(TestRunItemDB.test_result == TestResultStatus.NOT_REQUIRED).count()

    # 添加詳細的資料狀態診斷日誌
    logger.warning(f"PASS_RATE_DATA_DEBUG: team_id={team_id}, config_id={config_id}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: total items: {total}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: executed items: {executed}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: passed items: {passed}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: failed items: {failed}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: retest items: {retest}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: not_available items: {na}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: pending items: {pending}")
    logger.warning(f"PASS_RATE_DATA_DEBUG: not_required items: {not_required}")

    # 檢查是否有任何項目有 test_result 欄位
    sample_items = q.limit(5).all()
    logger.warning(f"PASS_RATE_SAMPLE_DEBUG: sample items count: {len(sample_items)}")
    for i, item in enumerate(sample_items):
        logger.warning(f"PASS_RATE_SAMPLE_DEBUG: item {i+1}: test_result={item.test_result}, executed_at={item.executed_at}")

    execution_rate = (executed / total * 100) if total > 0 else 0.0
    pass_rate = (passed / executed * 100) if executed > 0 else 0.0
    total_pass_rate = (passed / total * 100) if total > 0 else 0.0

    # 添加診斷日誌來驗證 pass rate 計算問題
    logger.warning(f"PASS_RATE_DEBUG: team_id={team_id}, config_id={config_id}")
    logger.warning(f"PASS_RATE_DEBUG: total={total}, executed={executed}, passed={passed}")
    logger.warning(f"PASS_RATE_DEBUG: pass_rate={pass_rate}, total_pass_rate={total_pass_rate}")
    logger.warning(f"PASS_RATE_DEBUG: executed > 0: {executed > 0}, passed/executed ratio: {passed/executed if executed > 0 else 'N/A'}")

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
        "pending_runs": pending,
        "not_required_runs": not_required,
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
    db: Session = Depends(get_sync_db)
):
    """取得該 Test Run 的 Bug Tickets 摘要資訊"""
    from ..config import settings
    from ..services.jira_client import JiraClient
    
    _verify_team_and_config(team_id, config_id, db)
    
    # 查詢所有有 bug_tickets_json 的項目
    items = db.query(TestRunItemDB).options(joinedload(TestRunItemDB.test_case)).filter(
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
                            case = getattr(item, 'test_case', None)
                            case_title = getattr(case, 'title', None)
                            bug_tickets_data[ticket_number]['test_cases'].append({
                                'item_id': item.id,
                                'test_case_number': item.test_case_number,
                                'title': case_title or '',
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
    db: Session = Depends(get_sync_db)
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
    db: Session = Depends(get_sync_db)
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


@router.delete("/{item_id}/bug-tickets/{ticket_number:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bug_ticket(
    team_id: int,
    config_id: int,
    item_id: int,
    ticket_number: str,
    db: Session = Depends(get_sync_db)
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
    
    # 尋找並移除指定的 ticket（使用精確匹配，不轉換大小寫）
    original_count = len(existing_tickets)
    ticket_number_to_delete = ticket_number.strip()

    # 先嘗試精確匹配
    existing_tickets_filtered = [ticket for ticket in existing_tickets
                      if not (isinstance(ticket, dict) and
                             ticket.get('ticket_number', '') == ticket_number_to_delete)]

    # 如果精確匹配沒找到，嘗試不區分大小寫匹配
    if len(existing_tickets_filtered) == original_count:
        ticket_number_upper = ticket_number_to_delete.upper()
        existing_tickets_filtered = [ticket for ticket in existing_tickets
                          if not (isinstance(ticket, dict) and
                                 ticket.get('ticket_number', '').upper() == ticket_number_upper)]

    existing_tickets = existing_tickets_filtered

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
    db: Session = Depends(get_sync_db)
):
    """
    獲取 Test Run Item 的測試結果檔案（本地）
    - 來源：test_run_items.execution_results_json
    - URL：/attachments/{relative_path}
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
        # 從本地 execution_results_json 讀取
        import json
        files = []
        try:
            if item.execution_results_json:
                data = json.loads(item.execution_results_json)
                if isinstance(data, list):
                    files = data
        except Exception:
            files = []
        
        base_url = "/attachments"
        result_files = []
        total_size = 0
        for f in files:
            name = f.get('name') or f.get('stored_name') or 'file'
            size = int(f.get('size') or 0)
            total_size += size
            rel = f.get('relative_path') or ''
            content_type = f.get('type') or 'application/octet-stream'
            result_files.append({
                "file_token": f.get('stored_name') or name,
                "name": name,
                "size": size,
                "url": f"{base_url}/{rel}" if rel else None,
                "uploaded_at": f.get('uploaded_at'),
                "content_type": content_type,
            })
        
        return {
            "test_results_files": result_files,
            "files_count": len(result_files),
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
    db: Session = Depends(get_sync_db)
):
    """
    刪除單一測試結果檔案（本地）
    - 從 test_run_items.execution_results_json 移除
    - 刪除磁碟檔案（attachments/test-runs/{team}/{config}/{item}/{stored_name}）
    """
    _verify_team_and_config(team_id, config_id, db)

    # 驗證 Test Run Item 存在
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
        TestRunItemDB.id == item_id
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Test Run Item 不存在")

    import json
    import urllib.parse
    import unicodedata
    from pathlib import Path

    # 讀取現有 execution_results_json
    files = []
    try:
        if item.execution_results_json:
            data = json.loads(item.execution_results_json)
            if isinstance(data, list):
                files = data
    except Exception:
        files = []

    # 準備比較（處理 URL decode 與 Unicode 正規化、尾綴比對）
    candidates = set()
    try:
        candidates.add(file_token)
        candidates.add(urllib.parse.unquote(file_token))
        for form in ("NFC", "NFD"):
            candidates.add(unicodedata.normalize(form, file_token))
            candidates.add(unicodedata.normalize(form, urllib.parse.unquote(file_token)))
    except Exception:
        candidates.add(file_token)

    def matches(name: str) -> bool:
        if not name:
            return False
        variants = {unicodedata.normalize(form, name) for form in ("NFC", "NFD")}
        for cand in candidates:
            if cand in variants:
                return True
            for v in variants:
                if v.endswith(cand):
                    return True
        return False

    # 找到目標索引
    idx = None
    for i, f in enumerate(files):
        if matches(f.get('stored_name') or '') or matches(f.get('name') or ''):
            idx = i
            break

    if idx is None:
        raise HTTPException(status_code=404, detail="檔案不存在於測試結果中")

    # 刪除磁碟檔案
    project_root = Path(__file__).resolve().parents[2]
    from app.config import settings
    base_dir = Path(settings.attachments.root_dir) if settings.attachments.root_dir else (project_root / "attachments")
    disk_path = files[idx].get('absolute_path')
    # 若沒有絕對路徑，嘗試用 root_dir + relative_path 組出
    if not disk_path:
        rel = files[idx].get('relative_path') or ''
        try:
            from pathlib import PurePosixPath
            rel_path = PurePosixPath(rel)
            disk_path = str(base_dir / rel_path)
        except Exception:
            disk_path = None
    try:
        if disk_path:
            p = Path(disk_path)
            # 只允許刪除附件根目錄下的檔案
            if (base_dir in p.parents or base_dir == p.parent) and p.exists():
                p.unlink()
    except Exception:
        pass

    # 從 JSON 移除並更新計數
    deleted = files.pop(idx)
    item.execution_results_json = json.dumps(files, ensure_ascii=False) if files else None
    item.result_files_count = len(files)
    item.result_files_uploaded = 1 if len(files) > 0 else 0
    item.updated_at = datetime.utcnow()

    db.commit()

    return {
        "success": True,
        "message": "檔案刪除成功",
        "deleted": deleted.get('stored_name') or deleted.get('name'),
        "remaining_files_count": len(files)
    }


# -------------------- Comment Management --------------------

@router.get("/{item_id}/comment", response_model=Dict[str, Any])
async def get_comment(
    team_id: int,
    config_id: int,
    item_id: int,
    db: Session = Depends(get_sync_db)
):
    """取得測試項目的最新 comment"""
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")

    # 從歷史記錄中取得最新的 comment
    latest_comment_record = db.query(ResultHistoryDB).filter(
        ResultHistoryDB.team_id == team_id,
        ResultHistoryDB.config_id == config_id,
        ResultHistoryDB.item_id == item_id,
        ResultHistoryDB.change_source == 'comment'
    ).order_by(ResultHistoryDB.changed_at.desc()).first()

    comment = latest_comment_record.change_reason if latest_comment_record else None

    return {
        "comment": comment,
        "updated_at": latest_comment_record.changed_at.isoformat() if latest_comment_record else None,
        "updated_by": latest_comment_record.changed_by_name if latest_comment_record else None
    }


@router.put("/{item_id}/comment", response_model=Dict[str, Any])
async def update_comment(
    team_id: int,
    config_id: int,
    item_id: int,
    payload: CommentRequest,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(get_current_user)
):
    """更新測試項目的 comment"""
    _verify_team_and_config(team_id, config_id, db)
    item = db.query(TestRunItemDB).filter(
        TestRunItemDB.id == item_id,
        TestRunItemDB.team_id == team_id,
        TestRunItemDB.config_id == config_id,
    ).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="找不到項目")

    # 清理輸入的 comment
    comment = payload.comment.strip() if payload.comment else ""

    # 建立新的歷史記錄（即使 comment 是空的也要記錄，因為這是用戶的明確操作）
    rec = ResultHistoryDB(
        team_id=item.team_id,
        config_id=item.config_id,
        item_id=item.id,
        prev_result=item.test_result,
        new_result=item.test_result,  # comment 更新不改變測試結果
        prev_executed_at=item.executed_at,
        new_executed_at=item.executed_at,  # comment 更新不改變執行時間
        changed_by_id=str(current_user.id) if current_user else None,
        changed_by_name=current_user.full_name or current_user.username if current_user else 'web',
        change_source='comment',
        change_reason=comment,
        changed_at=datetime.utcnow()
    )
    db.add(rec)

    # 更新項目時間戳
    item.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "comment": comment,
        "updated_at": rec.changed_at.isoformat(),
        "message": "Comment 已更新"
    }
