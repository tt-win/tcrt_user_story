"""
測試案例 API 路由

直接操作 Lark 多維表格，提供測試案例的 CRUD 操作、搜尋、過濾、排序和批次操作功能
SQLite 僅用於存儲團隊配置資訊
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models.test_case import (
    TestCase, TestCaseCreate, TestCaseUpdate, TestCaseResponse,
    TestCaseBatchOperation, TestCaseBatchResponse
)
from app.models.database_models import Team as TeamDB
from app.services.lark_client import LarkClient

router = APIRouter(prefix="/teams/{team_id}/testcases", tags=["test-cases"])


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
        app_id="cli_a8d1077685be102f",
        app_secret="***REMOVED***"
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
    
    # 搜尋標題
    if filters.get('search'):
        search_term = filters['search'].lower()
        filtered_records = [
            r for r in filtered_records 
            if search_term in r.get('fields', {}).get('Title', '').lower()
        ]
    
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
    # 分頁參數
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(100, ge=1, le=1000, description="回傳筆數")
):
    """取得測試案例列表，支援搜尋、過濾和排序"""
    lark_client, team = get_lark_client_for_team(team_id, db)
    
    try:
        # 從 Lark 獲取所有記錄
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
        
        # 轉換為 TestCase 模型
        test_cases = []
        for record in paginated_records:
            try:
                test_case = TestCase.from_lark_record(record, team_id)
                test_cases.append(test_case)
            except Exception as e:
                print(f"轉換記錄失敗 {record.get('record_id')}: {e}")
                continue
        
        return test_cases
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取測試案例失敗: {str(e)}"
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
        # 從 Lark 獲取所有記錄
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
            detail=f"獲取測試案例數量失敗: {str(e)}"
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
        # 從 Lark 獲取所有記錄，然後找到指定的記錄
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
            detail=f"獲取測試案例失敗: {str(e)}"
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
        # 建立 TestCase 模型實例
        test_case = TestCase(
            test_case_number=case.test_case_number,
            title=case.title,
            priority=case.priority,
            precondition=case.precondition,
            steps=case.steps,
            expected_result=case.expected_result,
            assignee=case.assignee,
            test_result=case.test_result,
            attachments=case.attachments or [],
            user_story_map=case.user_story_map or [],
            tcg=case.tcg or [],
            parent_record=case.parent_record,
            team_id=team_id
        )
        
        # 轉換為 Lark 格式
        lark_fields = test_case.to_lark_fields()
        
        # 建立 Lark 記錄
        record_id = lark_client.create_record(team.test_case_table_id, lark_fields)
        
        if not record_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="建立 Lark 記錄失敗"
            )
        
        # 重新獲取建立的記錄
        records = lark_client.get_all_records(team.test_case_table_id)
        created_record = None
        for record in records:
            if record.get('record_id') == record_id:
                created_record = record
                break
        
        if not created_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法獲取建立的記錄"
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
        # 先獲取現有記錄
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
        if case_update.attachments is not None:
            existing_case.attachments = case_update.attachments
        if case_update.user_story_map is not None:
            existing_case.user_story_map = case_update.user_story_map
        if case_update.tcg is not None:
            existing_case.tcg = case_update.tcg
        if case_update.parent_record is not None:
            existing_case.parent_record = case_update.parent_record
        
        # 轉換為 Lark 格式
        lark_fields = existing_case.to_lark_fields()
        
        # 更新 Lark 記錄
        success = lark_client.update_record(team.test_case_table_id, record_id, lark_fields)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新 Lark 記錄失敗"
            )
        
        # 重新獲取更新後的記錄
        updated_records = lark_client.get_all_records(team.test_case_table_id)
        updated_record = None
        for record in updated_records:
            if record.get('record_id') == record_id:
                updated_record = record
                break
        
        if not updated_record:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="無法獲取更新後的記錄"
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
        # 獲取所有記錄
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
                    test_case.tcg = operation.update_data["tcg"]
                    
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