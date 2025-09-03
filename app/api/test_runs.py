"""
測試執行 API 路由

直接操作 Lark 多維表格，提供測試執行的 CRUD 操作、統計分析、結果管理和附件處理功能
基於 test_run_configs 中配置的測試執行表格進行操作
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import io

from app.database import get_db
from app.models.test_run import (
    TestRun, TestRunCreate, TestRunUpdate, TestRunResponse, TestRunStatistics
)
from app.models.database_models import Team as TeamDB, TestRunConfig as TestRunConfigDB
from app.services.lark_client import LarkClient
from app.config import settings
router = APIRouter(prefix="/teams/{team_id}/test-runs", tags=["test-runs"])


def get_lark_client_for_test_run(team_id: int, config_id: int, db: Session) -> tuple[LarkClient, TeamDB, TestRunConfigDB]:
    """取得測試執行配置的 Lark Client"""
    # 取得團隊
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到團隊 ID {team_id}"
        )
    
    # 取得測試執行配置
    config = db.query(TestRunConfigDB).filter(
        TestRunConfigDB.id == config_id,
        TestRunConfigDB.team_id == team_id
    ).first()
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到測試執行配置 ID {config_id}"
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
    
    return lark_client, team, config


def filter_test_runs(records: List[dict], **filters) -> List[dict]:
    """根據條件過濾測試執行記錄"""
    filtered_records = records
    
    # 搜尋標題
    if filters.get('search'):
        search_term = filters['search'].lower()
        filtered_records = [
            r for r in filtered_records 
            if search_term in r.get('fields', {}).get('Title', '').lower()
        ]
    
    # 測試案例編號過濾
    if filters.get('test_case_number'):
        case_number = filters['test_case_number']
        filtered_records = [
            r for r in filtered_records
            if case_number in str(r.get('fields', {}).get('Test Case Number', ''))
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
    
    # 執行人過濾
    if filters.get('assignee_filter'):
        assignee_filter = filters['assignee_filter'].lower()
        filtered_records = [
            r for r in filtered_records
            if any(assignee_filter in assignee.get('name', '').lower() 
                   for assignee in r.get('fields', {}).get('Assignee', []))
        ]
    
    # 只顯示已執行的項目
    if filters.get('executed_only') is True:
        filtered_records = [
            r for r in filtered_records
            if r.get('fields', {}).get('Test Result') is not None
        ]
    
    # 只顯示有執行結果附件的項目
    if filters.get('has_execution_results') is True:
        filtered_records = [
            r for r in filtered_records
            if r.get('fields', {}).get('Execution Result', [])
        ]
    
    return filtered_records


def sort_test_runs(records: List[dict], sort_by: str = "created_at", sort_order: str = "desc") -> List[dict]:
    """排序測試執行記錄"""
    field_mapping = {
        "title": "Title",
        "priority": "Priority",
        "test_case_number": "Test Case Number",
        "test_result": "Test Result",
        "created_at": "created_time",  # Lark 系統欄位
        "updated_at": "updated_time"   # Lark 系統欄位
    }
    
    lark_field = field_mapping.get(sort_by, "created_time")
    reverse = sort_order.lower() == "desc"
    
    def get_sort_value(record):
        if lark_field in ["created_time", "updated_time"]:
            return record.get(lark_field, 0)
        else:
            field_value = record.get('fields', {}).get(lark_field, '')
            if isinstance(field_value, list) and field_value:
                return str(field_value[0].get('text', '')) if isinstance(field_value[0], dict) else str(field_value[0])
            return str(field_value)
    
    return sorted(records, key=get_sort_value, reverse=reverse)


@router.get("/{config_id}/records", response_model=List[TestRunResponse])
async def get_test_runs(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db),
    # 搜尋參數
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    test_case_number: Optional[str] = Query(None, description="測試案例編號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="執行人過濾"),
    executed_only: Optional[bool] = Query(None, description="只顯示已執行"),
    has_execution_results: Optional[bool] = Query(None, description="只顯示有執行結果"),
    # 排序參數
    sort_by: Optional[str] = Query("created_at", description="排序欄位"),
    sort_order: Optional[str] = Query("desc", description="排序順序 (asc/desc)"),
    # 分頁參數
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(100, ge=1, le=1000, description="回傳筆數")
):
    """取得測試執行記錄列表，支援搜尋、過濾和排序"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 從 Lark 取得所有記錄
        records = lark_client.get_all_records(config.table_id)
        
        # 過濾
        filters = {
            'search': search,
            'test_case_number': test_case_number,
            'priority_filter': priority_filter,
            'test_result_filter': test_result_filter,
            'assignee_filter': assignee_filter,
            'executed_only': executed_only,
            'has_execution_results': has_execution_results
        }
        filtered_records = filter_test_runs(records, **filters)
        
        # 排序
        sorted_records = sort_test_runs(filtered_records, sort_by, sort_order)
        
        # 分頁
        paginated_records = sorted_records[skip:skip + limit]
        
        # 轉換為 TestRunResponse 格式
        test_runs = []
        for record in paginated_records:
            try:
                # 解析基本資訊
                fields = record.get('fields', {})
                
                # 計算附件數量
                attachments = fields.get('Attachment', [])
                execution_results = fields.get('Execution Result', [])
                
                test_run_response = TestRunResponse(
                    record_id=record.get('record_id', ''),
                    test_case_number=fields.get('Test Case Number', ''),
                    title=fields.get('Title', ''),
                    priority=fields.get('Priority', 'Medium'),
                    test_result=fields.get('Test Result'),
                    assignee_name=fields.get('Assignee', [{}])[0].get('name') if fields.get('Assignee') else None,
                    attachment_count=len(attachments) if isinstance(attachments, list) else 0,
                    execution_result_count=len(execution_results) if isinstance(execution_results, list) else 0,
                    total_attachment_count=(len(attachments) if isinstance(attachments, list) else 0) + 
                                         (len(execution_results) if isinstance(execution_results, list) else 0),
                    executed_at=None,  # 可以從記錄中解析時間
                    created_at=datetime.fromtimestamp(record.get('created_time', 0) / 1000) if record.get('created_time') else None,
                    updated_at=datetime.fromtimestamp(record.get('updated_time', 0) / 1000) if record.get('updated_time') else None,
                    last_sync_at=datetime.now()
                )
                
                test_runs.append(test_run_response)
                
            except Exception as e:
                print(f"轉換記錄失敗 {record.get('record_id')}: {e}")
                continue
        
        return test_runs
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試執行記錄失敗: {str(e)}"
        )


@router.get("/{config_id}/records/count", response_model=dict)
async def get_test_runs_count(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db),
    # 搜尋參數（與 get_test_runs 相同）
    search: Optional[str] = Query(None, description="標題模糊搜尋"),
    test_case_number: Optional[str] = Query(None, description="測試案例編號過濾"),
    priority_filter: Optional[str] = Query(None, description="優先級過濾"),
    test_result_filter: Optional[str] = Query(None, description="測試結果過濾"),
    assignee_filter: Optional[str] = Query(None, description="執行人過濾"),
    executed_only: Optional[bool] = Query(None, description="只顯示已執行"),
    has_execution_results: Optional[bool] = Query(None, description="只顯示有執行結果")
):
    """取得符合條件的測試執行記錄數量"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 從 Lark 取得所有記錄
        records = lark_client.get_all_records(config.table_id)
        
        # 過濾
        filters = {
            'search': search,
            'test_case_number': test_case_number,
            'priority_filter': priority_filter,
            'test_result_filter': test_result_filter,
            'assignee_filter': assignee_filter,
            'executed_only': executed_only,
            'has_execution_results': has_execution_results
        }
        filtered_records = filter_test_runs(records, **filters)
        
        return {"total": len(filtered_records)}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試執行記錄數量失敗: {str(e)}"
        )


@router.get("/{config_id}/records/{record_id}", response_model=TestRun)
async def get_test_run(
    team_id: int,
    config_id: int,
    record_id: str,
    db: Session = Depends(get_db)
):
    """取得特定測試執行記錄"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 從 Lark 取得所有記錄，然後找到指定的記錄
        records = lark_client.get_all_records(config.table_id)
        
        target_record = None
        for record in records:
            if record.get('record_id') == record_id:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試執行記錄 {record_id}"
            )
        
        # 轉換為 TestRun 模型
        test_run = TestRun.from_lark_record(target_record, team_id)
        return test_run
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試執行記錄失敗: {str(e)}"
        )


@router.post("/{config_id}/records", response_model=TestRun, status_code=status.HTTP_201_CREATED)
async def create_test_run(
    team_id: int,
    config_id: int,
    test_run: TestRunCreate,
    db: Session = Depends(get_db)
):
    """建立新的測試執行記錄到 Lark 表格"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 建立 TestRun 模型實例
        test_run_instance = TestRun(
            test_case_number=test_run.test_case_number,
            title=test_run.title,
            priority=test_run.priority,
            precondition=test_run.precondition,
            steps=test_run.steps,
            expected_result=test_run.expected_result,
            team_id=team_id,
            test_environment=test_run.test_environment,
            build_version=test_run.build_version,
            related_test_case_number=test_run.related_test_case_number
        )
        
        # 處理執行人員
        if test_run.assignee_email:
            user_info = lark_client.get_user_by_email(test_run.assignee_email)
            if user_info:
                from app.models.lark_types import LarkUser
                test_run_instance.assignee = LarkUser(
                    id=user_info['id'],
                    name=user_info['name'],
                    email=user_info['email']
                )
        
        # 轉換為 Lark 格式
        lark_fields = test_run_instance.to_lark_fields()
        
        # 建立 Lark 記錄
        record_id = lark_client.create_record(config.table_id, lark_fields)
        
        if not record_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="建立 Lark 記錄失敗"
            )
        
        # 重新取得建立的記錄
        records = lark_client.get_all_records(config.table_id)
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
        
        # 轉換為 TestRun 模型回傳
        return TestRun.from_lark_record(created_record, team_id)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立測試執行記錄失敗: {str(e)}"
        )


@router.put("/{config_id}/records/{record_id}", response_model=TestRun)
async def update_test_run(
    team_id: int,
    config_id: int,
    record_id: str,
    test_run_update: TestRunUpdate,
    db: Session = Depends(get_db)
):
    """更新 Lark 表格中的測試執行記錄"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 先取得現有記錄
        records = lark_client.get_all_records(config.table_id)
        existing_record = None
        for record in records:
            if record.get('record_id') == record_id:
                existing_record = record
                break
        
        if not existing_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試執行記錄 {record_id}"
            )
        
        # 轉換現有記錄為 TestRun 模型
        existing_run = TestRun.from_lark_record(existing_record, team_id)
        
        # 更新欄位
        if test_run_update.title is not None:
            existing_run.title = test_run_update.title
        if test_run_update.priority is not None:
            existing_run.priority = test_run_update.priority
        if test_run_update.precondition is not None:
            existing_run.precondition = test_run_update.precondition
        if test_run_update.steps is not None:
            existing_run.steps = test_run_update.steps
        if test_run_update.expected_result is not None:
            existing_run.expected_result = test_run_update.expected_result
        if test_run_update.test_result is not None:
            existing_run.test_result = test_run_update.test_result
        if test_run_update.test_environment is not None:
            existing_run.test_environment = test_run_update.test_environment
        if test_run_update.build_version is not None:
            existing_run.build_version = test_run_update.build_version
        if test_run_update.execution_duration is not None:
            existing_run.execution_duration = test_run_update.execution_duration
        
        # 處理執行人員更新
        if test_run_update.assignee_email is not None:
            if test_run_update.assignee_email:  # 非空值
                user_info = lark_client.get_user_by_email(test_run_update.assignee_email)
                if user_info:
                    from app.models.lark_types import LarkUser
                    existing_run.assignee = LarkUser(
                        id=user_info['id'],
                        name=user_info['name'],
                        email=user_info['email']
                    )
            else:  # 空值，清除執行人員
                existing_run.assignee = None
        
        # 轉換為 Lark 格式
        lark_fields = existing_run.to_lark_fields()
        
        # 更新 Lark 記錄
        success = lark_client.update_record(config.table_id, record_id, lark_fields)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="更新 Lark 記錄失敗"
            )
        
        # 重新取得更新後的記錄
        updated_records = lark_client.get_all_records(config.table_id)
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
        
        # 轉換為 TestRun 模型回傳
        return TestRun.from_lark_record(updated_record, team_id)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新測試執行記錄失敗: {str(e)}"
        )


@router.delete("/{config_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_run(
    team_id: int,
    config_id: int,
    record_id: str,
    db: Session = Depends(get_db)
):
    """刪除 Lark 表格中的測試執行記錄"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 先驗證記錄是否存在
        records = lark_client.get_all_records(config.table_id)
        target_record = None
        for record in records:
            if record.get('record_id') == record_id:
                target_record = record
                break
        
        if not target_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試執行記錄 {record_id}"
            )
        
        # 執行刪除
        success = lark_client.delete_record(config.table_id, record_id)
        
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
            detail=f"刪除測試執行記錄失敗: {str(e)}"
        )


@router.get("/{config_id}/statistics", response_model=TestRunStatistics)
async def get_test_run_statistics(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """取得測試執行統計資訊"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        # 從 Lark 取得所有記錄
        records = lark_client.get_all_records(config.table_id)
        
        # 統計計算
        total_runs = len(records)
        executed_runs = 0
        passed_runs = 0
        failed_runs = 0
        retest_runs = 0
        not_available_runs = 0
        
        for record in records:
            fields = record.get('fields', {})
            test_result = fields.get('Test Result')
            
            if test_result:
                executed_runs += 1
                if test_result == 'Passed':
                    passed_runs += 1
                elif test_result == 'Failed':
                    failed_runs += 1
                elif test_result == 'Retest':
                    retest_runs += 1
                elif test_result == 'N/A':
                    not_available_runs += 1
        
        return TestRunStatistics.create(
            total_runs=total_runs,
            executed_runs=executed_runs,
            passed_runs=passed_runs,
            failed_runs=failed_runs,
            retest_runs=retest_runs,
            not_available_runs=not_available_runs
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取得測試執行統計失敗: {str(e)}"
        )


@router.post("/{config_id}/batch-update-results")
async def batch_update_test_results(
    team_id: int,
    config_id: int,
    updates: List[dict],
    db: Session = Depends(get_db)
):
    """批次更新測試執行結果"""
    lark_client, team, config = get_lark_client_for_test_run(team_id, config_id, db)
    
    try:
        success_count = 0
        error_messages = []
        
        for update_data in updates:
            record_id = update_data.get('record_id')
            test_result = update_data.get('test_result')
            
            if not record_id or not test_result:
                error_messages.append("記錄 ID 和測試結果不能為空")
                continue
            
            try:
                # 更新 Lark 記錄
                lark_fields = {'Test Result': test_result}
                success = lark_client.update_record(config.table_id, record_id, lark_fields)
                
                if success:
                    success_count += 1
                else:
                    error_messages.append(f"記錄 {record_id} 更新失敗")
            except Exception as e:
                error_messages.append(f"記錄 {record_id}: {str(e)}")
        
        return {
            "success": len(error_messages) == 0,
            "processed_count": len(updates),
            "success_count": success_count,
            "error_count": len(error_messages),
            "error_messages": error_messages
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批次更新測試結果失敗: {str(e)}"
        )


@router.get("/{config_id}/generate-pdf")
async def generate_pdf_report(
    team_id: int,
    config_id: int,
    db: Session = Depends(get_db)
):
    """生成 Test Run PDF 報告"""
    from fastapi.responses import StreamingResponse
    from ..services.pdf_report_service import PDFReportService
    
    try:
        # 驗證團隊和配置存在（不需要 Lark API 驗證）
        team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到團隊 ID {team_id}"
            )
        
        config = db.query(TestRunConfigDB).filter(
            TestRunConfigDB.id == config_id,
            TestRunConfigDB.team_id == team_id
        ).first()
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"找不到測試執行配置 ID {config_id}"
            )
        
        # 生成 PDF
        pdf_service = PDFReportService(db)
        pdf_content = pdf_service.generate_test_run_report(team_id, config_id)
        
        # 準備檔案名稱（避免中文字元編碼問題）
        safe_name = config.name.encode('ascii', 'ignore').decode('ascii') if config.name else 'report'
        filename = f"test_run_report_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        return StreamingResponse(
            io.BytesIO(pdf_content),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PDF 生成失敗: {str(e)}"
        )