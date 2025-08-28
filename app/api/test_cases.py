"""
測試案例 API 路由

直接操作 Lark 多維表格，提供測試案例的 CRUD 操作、搜尋、過濾、排序和批次操作功能
SQLite 僅用於存儲團隊配置資訊
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.test_case import (
    TestCase, TestCaseCreate, TestCaseUpdate, TestCaseResponse,
    TestCaseBatchOperation, TestCaseBatchResponse
)
from app.models.database_models import Team as TeamDB
from app.services.lark_client import LarkClient
from app.services.tcg_converter import tcg_converter
from app.config import settings

router = APIRouter(prefix="/teams/{team_id}/testcases", tags=["test-cases"])


class BulkTestCaseItem(BaseModel):
    test_case_number: str
    title: Optional[str] = None
    priority: Optional[str] = "Medium"


class BulkCreateRequest(BaseModel):
    items: List[BulkTestCaseItem]


class BulkCreateResponse(BaseModel):
    success: bool
    created_count: int = 0
    duplicates: List[str] = []
    errors: List[str] = []


def get_lark_client_for_team(team_id: int, db: Session) -> tuple[LarkClient, TeamDB]:
    """取得團隊的 Lark Client"""
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    # 建立 Lark Client
    lark_client = LarkClient(
        app_id=settings.lark.app_id,
        app_secret=settings.lark.app_secret
    )
    
    if not lark_client.set_wiki_token(team.wiki_token):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="無法連接到 Lark 服務"
        )
    
    return lark_client, team


def filter_test_cases(records: List[dict], **filters) -> List[dict]:
    """根據條件過濾測試案例記錄"""
    filtered_records = records
    
    # 關鍵字搜尋：標題或測試案例編號
    if filters.get('search') is not None and str(filters['search']).strip() != '':
        search_term = str(filters['search']).strip().lower()
        def rec_matches(r: dict) -> bool:
            f = r.get('fields', {}) or {}
            title = str(f.get('Title', '') or '').lower()
            num = str(f.get('Test Case Number', '') or '').lower()
            return (search_term in title) or (search_term in num)
        filtered_records = [r for r in filtered_records if rec_matches(r)]
    
    # TCG 過濾
    if filters.get('tcg_filter'):
        tcg_filter = filters['tcg_filter']
        filtered_records = [
            r for r in filtered_records
            if any(tcg_filter in str(tcg_item.get('text', '')) 
                   for tcg_item in r.get('fields', {}).get('TCG', []))
        ]
    
    # 優先級過濾
    if filters.get('priority_filter'):
        priority_filter = filters['priority_filter']
        filtered_records = [
            r for r in filtered_records
            if r.get('fields', {}).get('Priority') == priority_filter
        ]
    
    # 測試結果過濾
    if filters.get('test_result_filter'):
        result_filter = filters['test_result_filter']
        filtered_records = [
            r for r in filtered_records
            if r.get('fields', {}).get('Test Result') == result_filter
        ]
    
    # 指派人過濾
    if filters.get('assignee_filter'):
        assignee_filter = filters['assignee_filter'].lower()
        filtered_records = [
            r for r in filtered_records
            if any(assignee_filter in assignee.get('name', '').lower() 
                   for assignee in r.get('fields', {}).get('Assignee', []))
        ]
    
    return filtered_records


def sort_test_cases(records: List[dict], sort_by: str = "created_at", sort_order: str = "desc") -> List[dict]:
    """排序測試案例記錄"""
    field_mapping = {
        "title": "Title",
        "priority": "Priority",
        "test_case_number": "Test Case Number",
        "test_result": "Test Result",
        "created_at": "created_time"  # Lark 系統欄位
    }
    
    lark_field = field_mapping.get(sort_by, "created_time")
    reverse = sort_order.lower() == "desc"
    
    def get_sort_value(record):
        if lark_field == "created_time":
            return record.get('created_time', 0)
        else:
            field_value = record.get('fields', {}).get(lark_field, '')
            if isinstance(field_value, list) and field_value:
                return str(field_value[0].get('text', '')) if isinstance(field_value[0], dict) else str(field_value[0])
            return str(field_value)
    
    return sorted(records, key=get_sort_value, reverse=reverse)


@router.get("/", response_model=List[TestCaseResponse])
async def get_test_cases(
    team_id: int,
    db: Session = Depends(get_db),
    # 搜尋參數
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾"),
    # 排序參數
    sort_by: Optional[str] = Query("created_at", description="排序欄位"),
    sort_order: Optional[str] = Query("desc", description="排序順序 (asc/desc)"),
    # 分頁參數（為了前端客戶端分頁，預設取較大量）
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(100000, ge=1, le=1000000, description="回傳筆數")
):
    """取得測試案例列表，支援搜尋、過濾和排序"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 從 Lark 取得所有記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        
        # 過濾
        filters = {
            'search': search,
            'tcg_filter': tcg_filter,
            'priority_filter': priority_filter,
            'test_result_filter': test_result_filter,
            'assignee_filter': assignee_filter
        }
        filtered_records = filter_test_cases(records, **filters)
        
        # 排序
        sorted_records = sort_test_cases(filtered_records, sort_by, sort_order)
        
        # 分頁
        paginated_records = sorted_records[skip:skip + limit]
        
        # 轉換為 TestCase 模型並處理 TCG 顯示
        test_cases = []
        tcg_record_ids = set()
        
        for record in paginated_records:
            try:
                test_case = TestCase.from_lark_record(record, team_id)
                test_cases.append(test_case)
                
                # 收集所有 TCG record_ids 用於批量轉換
                for tcg_record in test_case.tcg:
                    if tcg_record.record_ids:
                        tcg_record_ids.update(tcg_record.record_ids)
                        
            except Exception as e:
                print(f"轉換記錄失敗 {record.get('record_id')}: {e}")
                continue
        
        # 批量轉換 TCG record_ids 為顯示文字
        if tcg_record_ids:
            tcg_mapping = tcg_converter.get_tcg_numbers_by_record_ids(list(tcg_record_ids))
            
            # 為每個測試案例設置 TCG 顯示文字
            for test_case in test_cases:
                for tcg_record in test_case.tcg:
                    if tcg_record.record_ids:
                        # 將 record_ids 轉換為顯示文字
                        tcg_numbers = []
                        for record_id in tcg_record.record_ids:
                            tcg_number = tcg_mapping.get(record_id)
                            if tcg_number:
                                tcg_numbers.append(tcg_number)
                        
                        # 更新顯示文字
                        if tcg_numbers:
                            tcg_record.text = ", ".join(tcg_numbers)
                            tcg_record.text_arr = tcg_numbers
        
        return test_cases
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例失敗: {str(e)}"
        )


@router.get("/count", response_model=dict)
async def get_test_cases_count(
    team_id: int,
    db: Session = Depends(get_db),
    # 搜尋參數（與 get_test_cases 相同）
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    tcg_filter: Optional[str] = Query(None, description="TCG 單號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="指派人過濾")
):
    """取得符合條件的測試案例數量"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 從 Lark 取得所有記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        
        # 過濾
        filters = {
            'search': search,
            'tcg_filter': tcg_filter,
            'priority_filter': priority_filter,
            'test_result_filter': test_result_filter,
            'assignee_filter': assignee_filter
        }
        filtered_records = filter_test_cases(records, **filters)
        
        return {"total": len(filtered_records)}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例數量失敗: {str(e)}"
        )


@router.get("/{record_id}", response_model=TestCaseResponse)
async def get_test_case(
    team_id: int,
    record_id: str,
    db: Session = Depends(get_db)
):
    """取得特定測試案例"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 從 Lark 取得所有記錄，然後找到指定的記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        
        target_record = None
        for record in records:
            if record.get('record_id') == record_id:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {record_id}"
            )
        
        # 轉換為 TestCase 模型
        test_case = TestCase.from_lark_record(target_record, team_id)
        return test_case
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試案例失敗: {str(e)}"
        )


@router.post("/", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    team_id: int,
    case: TestCaseCreate,
    db: Session = Depends(get_db)
):
    """建立新的測試案例到 Lark 表格"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 處理附件：將 SimpleAttachment 轉換為 file_token 列表
        attachment_tokens = []
        if case.attachments:
            attachment_tokens = [att.file_token for att in case.attachments]
        
        # 建立 TestCase 模型實例
        # 注意：TestCase.parent_record 需要 List[LarkRecord]，而 create 模型是 Optional[LarkRecord]
        parent_records = []
        if case.parent_record is not None:
            parent_records = [case.parent_record]
        test_case = TestCase(
            test_case_number=case.test_case_number,
            title=case.title,
            priority=case.priority,
            precondition=case.precondition,
            steps=case.steps,
            expected_result=case.expected_result,
            assignee=case.assignee,
            test_result=case.test_result,
            attachments=[],  # 暫時為空，將在 to_lark_fields 中處理
            user_story_map=case.user_story_map or [],
            tcg=case.tcg or [],
            parent_record=parent_records,
            team_id=team_id
        )
        
        # 轉換為 Lark 格式
        lark_fields = test_case.to_lark_fields()
        
        # 手動添加附件 file_tokens（Lark 需要 [{"file_token": token}]）
        if attachment_tokens is not None:
            lark_fields[test_case.FIELD_IDS['attachments']] = [
                {'file_token': t} for t in attachment_tokens
            ]
        
        # 建立 Lark 記錄
        record_id = lark_client.create_record(team.test_case_table_id, lark_fields)
        
        if not record_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="建立 Lark 記錄失敗"
            )
        
        # 重新取得建立的記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        created_record = None
        for record in records:
            if record.get('record_id') == record_id:
                created_record = record
                break
        
        if not created_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法取得建立的記錄"
            )
        
        # 轉換為 TestCase 模型回傳
        return TestCase.from_lark_record(created_record, team_id)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立測試案例失敗: {str(e)}"
        )


@router.put("/{record_id}", response_model=TestCaseResponse)
async def update_test_case(
    team_id: int,
    record_id: str,
    case_update: TestCaseUpdate,
    db: Session = Depends(get_db)
):
    """更新 Lark 表格中的測試案例"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 先取得現有記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        existing_record = None
        for record in records:
            if record.get('record_id') == record_id:
                existing_record = record
                break
        
        if not existing_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {record_id}"
            )
        
        # 轉換現有記錄為 TestCase 模型
        existing_case = TestCase.from_lark_record(existing_record, team_id)
        
        # 更新欄位
        if case_update.test_case_number is not None:
            existing_case.test_case_number = case_update.test_case_number
        if case_update.title is not None:
            existing_case.title = case_update.title
        if case_update.priority is not None:
            existing_case.priority = case_update.priority
        if case_update.precondition is not None:
            existing_case.precondition = case_update.precondition
        if case_update.steps is not None:
            existing_case.steps = case_update.steps
        if case_update.expected_result is not None:
            existing_case.expected_result = case_update.expected_result
        if case_update.assignee is not None:
            existing_case.assignee = case_update.assignee
        if case_update.test_result is not None:
            existing_case.test_result = case_update.test_result
        # 處理附件更新
        attachment_tokens = None
        if case_update.attachments is not None:
            attachment_tokens = [att.file_token for att in case_update.attachments]
            existing_case.attachments = []  # 清空，稍後手動添加到 lark_fields
            
        if case_update.user_story_map is not None:
            existing_case.user_story_map = case_update.user_story_map
        if case_update.tcg is not None:
            # 處理 TCG 更新：支援字串和 LarkRecord 格式
            if isinstance(case_update.tcg, str):
                # 如果是字串格式，使用 TCG converter 找到對應的 record_id
                tcg_number = case_update.tcg.strip()
                if tcg_number:
                    from app.services.tcg_converter import tcg_converter
                    from app.models.lark_types import LarkRecord
                    
                    # 使用 TCG converter 查找對應的 record_id
                    tcg_record_id = tcg_converter.get_record_id_by_tcg_number(tcg_number)
                    
                    if tcg_record_id:
                        # 創建 LarkRecord 物件
                        tcg_table_id = "tblcK6eF3yQCuwwl"  # TCG 表格的固定 ID
                        tcg_record = LarkRecord(
                            record_ids=[tcg_record_id],
                            table_id=tcg_table_id,
                            text=tcg_number,
                            text_arr=[tcg_number],
                            display_text=tcg_number,
                            type="text"
                        )
                        existing_case.tcg = [tcg_record]
                    else:
                        # 如果找不到對應的 TCG，清空 TCG
                        existing_case.tcg = []
                else:
                    # 空字串則清空 TCG
                    existing_case.tcg = []
            else:
                # 如果是 LarkRecord 列表格式，直接使用
                existing_case.tcg = case_update.tcg
        if case_update.parent_record is not None:
            existing_case.parent_record = case_update.parent_record
        
        # 轉換為 Lark 格式
        lark_fields = existing_case.to_lark_fields()
        
        # 手動處理附件 file_tokens（Lark 需要 [{"file_token": token}]）
        if attachment_tokens is not None:
            lark_fields[existing_case.FIELD_IDS['attachments']] = [
                {'file_token': t} for t in attachment_tokens
            ]
        
        # 更新 Lark 記錄
        success = lark_client.update_record(team.test_case_table_id, record_id, lark_fields)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新 Lark 記錄失敗"
            )
        
        # 重新取得更新後的記錄
        updated_records = lark_client.get_all_records(team.test_case_table_id)
        updated_record = None
        for record in updated_records:
            if record.get('record_id') == record_id:
                updated_record = record
                break
        
        if not updated_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法取得更新後的記錄"
            )
        
        # 轉換為 TestCase 模型回傳
        return TestCase.from_lark_record(updated_record, team_id)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新測試案例失敗: {str(e)}"
        )


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    team_id: int,
    record_id: str,
    db: Session = Depends(get_db)
):
    """刪除 Lark 表格中的測試案例"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 先驗證記錄是否存在
        records = lark_client.get_all_records(team.test_case_table_id)
        target_record = None
        for record in records:
            if record.get('record_id') == record_id:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試案例 {record_id}"
            )
        
        # 執行刪除
        success = lark_client.delete_record(team.test_case_table_id, record_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="刪除 Lark 記錄失敗"
            )
        
        # 成功刪除，回傳 204 No Content
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除測試案例失敗: {str(e)}"
        )


@router.post("/bulk_create", response_model=BulkCreateResponse)
async def bulk_create_test_cases(
    team_id: int,
    request: BulkCreateRequest,
    db: Session = Depends(get_db)
):
    """批次建立測試案例（一次性寫入）"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    try:
        if not request.items:
            return BulkCreateResponse(success=False, created_count=0, errors=["空的建立清單"])

        # 取得現有記錄用於重複檢查
        records = lark_client.get_all_records(team.test_case_table_id)
        existing_numbers = set()
        for r in records:
            fields = r.get('fields', {})
            num = fields.get(TestCase.FIELD_IDS['test_case_number'])
            if num:
                existing_numbers.add(str(num))

        duplicates = [item.test_case_number for item in request.items if item.test_case_number in existing_numbers]
        if duplicates:
            return BulkCreateResponse(success=False, created_count=0, duplicates=duplicates)

        # 準備批次建立的欄位資料
        records_data: List[dict] = []
        for item in request.items:
            title = item.title.strip() if item.title else f"{item.test_case_number} 的測試案例"
            priority = item.priority or 'Medium'
            test_case = TestCase(
                test_case_number=item.test_case_number,
                title=title,
                priority=priority,
                precondition=None,
                steps=None,
                expected_result=None,
                assignee=None,
                test_result=None,
                attachments=[],
                user_story_map=[],
                tcg=[],
                parent_record=[],
                team_id=team_id
            )
            records_data.append(test_case.to_lark_fields())

        ok, ids, error_messages = lark_client.batch_create_records(team.test_case_table_id, records_data)
        if not ok:
            return BulkCreateResponse(success=False, created_count=len(ids), errors=error_messages)

        return BulkCreateResponse(success=True, created_count=len(ids))
    except Exception as e:
        return BulkCreateResponse(success=False, created_count=0, errors=[str(e)])


@router.post("/batch", response_model=TestCaseBatchResponse)
async def batch_operation_test_cases(
    team_id: int,
    operation: TestCaseBatchOperation,
    db: Session = Depends(get_db)
):
    """批次操作 Lark 表格中的測試案例"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    if not operation.record_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="記錄 ID 列表不能為空"
        )
    
    try:
        # 取得所有記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        target_records = [
            record for record in records 
            if record.get('record_id') in operation.record_ids
        ]
        
        if len(target_records) != len(operation.record_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分測試案例不存在"
            )
        
        success_count = 0
        error_messages = []
        
        if operation.operation == "delete":
            # 批次刪除
            try:
                success, deleted_count, error_messages = lark_client.batch_delete_records(
                    team.test_case_table_id, 
                    operation.record_ids
                )
                
                return TestCaseBatchResponse(
                    success=success,
                    processed_count=len(operation.record_ids),
                    success_count=deleted_count,
                    error_count=len(error_messages),
                    error_messages=error_messages
                )
                
            except Exception as e:
                return TestCaseBatchResponse(
                    success=False,
                    processed_count=len(operation.record_ids),
                    success_count=0,
                    error_count=len(operation.record_ids),
                    error_messages=[str(e)]
                )
        
        elif operation.operation == "update_tcg":
            # 批次更新 TCG
            if not operation.update_data or "tcg" not in operation.update_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="批次更新 TCG 需要提供 tcg 資料"
                )
            
            for record in target_records:
                try:
                    # 轉換為 TestCase 模型
                    test_case = TestCase.from_lark_record(record, team_id)
                    
                    # 處理 TCG 更新：支援字串格式
                    tcg_value = operation.update_data["tcg"]
                    if isinstance(tcg_value, str):
                        tcg_number = tcg_value.strip()
                        if tcg_number:
                            # 使用 TCG converter 查找對應的 record_id
                            from app.services.tcg_converter import tcg_converter
                            from app.models.lark_types import LarkRecord
                            
                            tcg_record_id = tcg_converter.get_record_id_by_tcg_number(tcg_number)
                            
                            if tcg_record_id:
                                # 創建 LarkRecord 物件
                                tcg_table_id = "tblcK6eF3yQCuwwl"  # TCG 表格的固定 ID
                                tcg_record = LarkRecord(
                                    record_ids=[tcg_record_id],
                                    table_id=tcg_table_id,
                                    text=tcg_number,
                                    text_arr=[tcg_number],
                                    display_text=tcg_number,
                                    type="text"
                                )
                                test_case.tcg = [tcg_record]
                            else:
                                # 如果找不到對應的 TCG，清空 TCG
                                test_case.tcg = []
                        else:
                            # 空字串則清空 TCG
                            test_case.tcg = []
                    else:
                        # 如果是 LarkRecord 列表格式，直接使用
                        test_case.tcg = tcg_value
                    
                    # 轉換為 Lark 格式並更新
                    lark_fields = test_case.to_lark_fields()
                    success = lark_client.update_record(
                        team.test_case_table_id, 
                        record.get('record_id'), 
                        lark_fields
                    )
                    
                    if success:
                        success_count += 1
                    else:
                        error_messages.append(f"記錄 {record.get('record_id')} 更新失敗")
                        
                except Exception as e:
                    error_messages.append(f"記錄 {record.get('record_id')}: {str(e)}")
        
        elif operation.operation == "update_priority":
            # 批次更新優先級
            if not operation.update_data or "priority" not in operation.update_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="批次更新優先級需要提供 priority 資料"
                )
            
            for record in target_records:
                try:
                    test_case = TestCase.from_lark_record(record, team_id)
                    test_case.priority = operation.update_data["priority"]
                    
                    lark_fields = test_case.to_lark_fields()
                    success = lark_client.update_record(
                        team.test_case_table_id,
                        record.get('record_id'),
                        lark_fields
                    )
                    
                    if success:
                        success_count += 1
                    else:
                        error_messages.append(f"記錄 {record.get('record_id')} 更新失敗")
                        
                except Exception as e:
                    error_messages.append(f"記錄 {record.get('record_id')}: {str(e)}")
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支援的批次操作: {operation.operation}"
            )
        
        return TestCaseBatchResponse(
            success=len(error_messages) == 0,
            processed_count=len(operation.record_ids),
            success_count=success_count,
            error_count=len(error_messages),
            error_messages=error_messages
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return TestCaseBatchResponse(
            success=False,
            processed_count=len(operation.record_ids),
            success_count=0,
            error_count=len(operation.record_ids),
            error_messages=[str(e)]
        )
