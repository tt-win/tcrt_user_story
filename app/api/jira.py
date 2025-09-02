"""
JIRA API 路由
提供 JIRA 相關的 API 端點
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any
import re
from datetime import datetime
from ..services.jira_client import JiraClient
from ..config import settings

router = APIRouter(prefix="/jira", tags=["jira"])

# TP 票號格式驗證
TP_PATTERN = re.compile(r'^TP-\d+$')

def validate_tp_format(tp_number: str) -> tuple[bool, Optional[str]]:
    """
    驗證 TP 票號格式
    
    Args:
        tp_number: TP 票號字串
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not TP_PATTERN.match(tp_number):
        return False, f'TP 票號格式無效: {tp_number} (預期格式: TP-XXXXX)'
    return True, None

def safe_get_field(data: Dict[str, Any], *field_path: str, default: Any = None) -> Any:
    """
    安全地從巢狀字典中獲取欄位值
    
    Args:
        data: 資料字典
        *field_path: 欄位路徑 (例如: 'fields', 'assignee', 'displayName')
        default: 預設值
        
    Returns:
        欄位值或預設值
    """
    current = data
    for field in field_path:
        if isinstance(current, dict) and field in current:
            current = current[field]
        else:
            return default
    return current

# 全域 JIRA 客戶端實例
_jira_client = None

def get_jira_client() -> JiraClient:
    """取得 JIRA 客戶端實例"""
    global _jira_client
    if _jira_client is None:
        try:
            _jira_client = JiraClient()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"JIRA 客戶端初始化失敗: {str(e)}"
            )
    return _jira_client

@router.get("/ticket/{ticket_key}")
async def get_ticket_info(
    ticket_key: str,
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    取得 JIRA ticket 的基本資訊

    Args:
        ticket_key: JIRA ticket 編號 (例如: TCG-93178)

    Returns:
        Dict: 包含 ticket 基本資訊的字典
    """
    try:
        # 取得 ticket 詳細資訊
        ticket_data = jira_client.get_issue(
            ticket_key,
            fields=['summary', 'status', 'assignee', 'created', 'updated', 'description']
        )

        if not ticket_data:
            raise HTTPException(
                status_code=404,
                detail=f"找不到 ticket: {ticket_key}"
            )

        # 提取需要的欄位
        fields = ticket_data.get('fields', {})

        # 格式化回應
        response = {
            'ticket_key': ticket_key,
            'summary': fields.get('summary', ''),
            'status': {
                'name': fields.get('status', {}).get('name', ''),
                'id': fields.get('status', {}).get('id', '')
            },
            'assignee': {
                'displayName': fields.get('assignee', {}).get('displayName', '未指派'),
                'accountId': fields.get('assignee', {}).get('accountId', '')
            } if fields.get('assignee') else None,
            'created': fields.get('created', ''),
            'updated': fields.get('updated', ''),
            'description': fields.get('description', '')[:500] if fields.get('description') else '',  # 限制描述長度
            'url': f"{settings.jira.server_url}/browse/{ticket_key}"
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"取得 ticket 資訊失敗: {str(e)}"
        )

@router.get("/connection-test")
async def test_jira_connection(
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    測試 JIRA 連接狀態

    Returns:
        Dict: 包含連接狀態和使用者資訊
    """
    try:
        connection_ok = jira_client.test_connection()

        if connection_ok:
            return {
                'status': 'connected',
                'message': 'JIRA 連接正常',
                'server_url': settings.jira.server_url,
                'username': settings.jira.username
            }
        else:
            return {
                'status': 'disconnected',
                'message': '無法連接至 JIRA 伺服器',
                'server_url': settings.jira.server_url
            }

    except Exception as e:
        return {
            'status': 'error',
            'message': f'連接測試失敗: {str(e)}',
            'server_url': settings.jira.server_url
        }

@router.get("/projects")
async def get_jira_projects(
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    取得所有可用的 JIRA 專案

    Returns:
        Dict: 包含專案列表
    """
    try:
        projects = jira_client.get_projects()

        return {
            'projects': projects,
            'count': len(projects)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"取得專案列表失敗: {str(e)}"
        )

@router.get("/tp/{tp_number}/validate")
async def validate_tp_ticket(
    tp_number: str,
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    驗證 TP 票號有效性
    
    Args:
        tp_number: TP 票號 (例如: TP-12345)
        
    Returns:
        Dict: 驗證結果包含格式檢查和 JIRA 存在性檢查
    """
    # TP 票號格式驗證
    format_valid, error_message = validate_tp_format(tp_number)
    
    if not format_valid:
        return {
            'ticket_number': tp_number,
            'valid': False,
            'format_valid': False,
            'exists_in_jira': False,
            'error': error_message
        }
    
    # JIRA 存在性檢查
    try:
        ticket_data = jira_client.get_issue(
            tp_number,
            fields=['summary', 'status', 'key']
        )
        
        if ticket_data:
            return {
                'ticket_number': tp_number,
                'valid': True,
                'format_valid': True,
                'exists_in_jira': True,
                'summary': safe_get_field(ticket_data, 'fields', 'summary', default=''),
                'status': safe_get_field(ticket_data, 'fields', 'status', 'name', default=''),
                'url': f"{jira_client.server_url}/browse/{tp_number}"
            }
        else:
            return {
                'ticket_number': tp_number,
                'valid': False,
                'format_valid': True,
                'exists_in_jira': False,
                'error': f'TP 票號在 JIRA 中不存在: {tp_number}'
            }
            
    except Exception as e:
        return {
            'ticket_number': tp_number,
            'valid': False,
            'format_valid': True,
            'exists_in_jira': False,
            'error': f'檢查 TP 票號時發生錯誤: {str(e)}'
        }

@router.get("/tp/{tp_number}/details")
async def get_tp_ticket_details(
    tp_number: str,
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    取得 TP 票號詳細資訊
    
    Args:
        tp_number: TP 票號 (例如: TP-12345)
        
    Returns:
        Dict: 完整的 TP 票號 JIRA 資訊包含標題、狀態、負責人、優先級、連結
    """
    # TP 票號格式驗證
    format_valid, error_message = validate_tp_format(tp_number)
    
    if not format_valid:
        raise HTTPException(
            status_code=400,
            detail=error_message
        )
    
    try:
        # 查詢完整的票號資訊
        ticket_data = jira_client.get_issue(
            tp_number,
            fields=['summary', 'status', 'assignee', 'priority', 'created', 
                   'updated', 'description', 'issuetype', 'project']
        )
        
        if not ticket_data:
            raise HTTPException(
                status_code=404,
                detail=f"TP 票號不存在: {tp_number}"
            )
        
        # 安全提取各欄位資訊
        fields = ticket_data.get('fields', {})
        
        # 負責人資訊
        assignee_data = fields.get('assignee')
        assignee_info = None
        if assignee_data:
            assignee_info = {
                'display_name': safe_get_field(assignee_data, 'displayName', default='未知'),
                'email': safe_get_field(assignee_data, 'emailAddress', default=''),
                'account_id': safe_get_field(assignee_data, 'accountId', default='')
            }
        
        # 優先級資訊
        priority_data = fields.get('priority')
        priority_info = None
        if priority_data:
            priority_info = {
                'name': safe_get_field(priority_data, 'name', default='未設定'),
                'id': safe_get_field(priority_data, 'id', default=''),
                'icon_url': safe_get_field(priority_data, 'iconUrl', default='')
            }
        
        # 狀態資訊
        status_data = fields.get('status', {})
        status_info = {
            'name': safe_get_field(status_data, 'name', default='未知'),
            'id': safe_get_field(status_data, 'id', default=''),
            'category': safe_get_field(status_data, 'statusCategory', 'name', default='')
        }
        
        # 專案資訊
        project_data = fields.get('project', {})
        project_info = {
            'key': safe_get_field(project_data, 'key', default=''),
            'name': safe_get_field(project_data, 'name', default='')
        }
        
        # 議題類型
        issue_type_data = fields.get('issuetype', {})
        issue_type_info = {
            'name': safe_get_field(issue_type_data, 'name', default=''),
            'icon_url': safe_get_field(issue_type_data, 'iconUrl', default='')
        }
        
        # 安全取得描述並限制長度
        description = safe_get_field(fields, 'description', default='')
        description = description[:1000] if description else ''
        
        # 組裝回應資料
        response_data = {
            'ticket_number': tp_number,
            'summary': safe_get_field(fields, 'summary', default=''),
            'description': description,
            'status': status_info,
            'assignee': assignee_info,
            'priority': priority_info,
            'project': project_info,
            'issue_type': issue_type_info,
            'created': safe_get_field(fields, 'created', default=''),
            'updated': safe_get_field(fields, 'updated', default=''),
            'url': f"{jira_client.server_url}/browse/{tp_number}",
            'retrieved_at': datetime.now().isoformat()  # API 呼叫時間戳
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"取得 TP 票號詳情失敗: {str(e)}"
        )

@router.post("/tp/batch")
async def get_tp_tickets_batch(
    tp_numbers: list[str],
    fields: list[str] = None,
    jira_client: JiraClient = Depends(get_jira_client)
) -> Dict[str, Any]:
    """
    批次查詢多個 TP 票號資訊
    
    Args:
        tp_numbers: TP 票號列表
        fields: 要返回的欄位列表 (可選)
        
    Returns:
        Dict: 批次查詢結果包含所有票號的詳細資訊
    """
    if not tp_numbers:
        return {
            'total_count': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'results': {}
        }
    
    # 限制批次查詢數量
    max_batch_size = 50
    if len(tp_numbers) > max_batch_size:
        raise HTTPException(
            status_code=400,
            detail=f"批次查詢數量超過限制 {max_batch_size}，當前: {len(tp_numbers)}"
        )
    
    try:
        # 呼叫服務層批次查詢方法
        results = jira_client.get_tp_tickets_batch(tp_numbers, fields)
        
        # 統計結果
        valid_count = sum(1 for result in results.values() if result.get('valid', False))
        invalid_count = len(results) - valid_count
        
        return {
            'total_count': len(tp_numbers),
            'valid_count': valid_count,
            'invalid_count': invalid_count,
            'results': results
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"批次查詢 TP 票號失敗: {str(e)}"
        )