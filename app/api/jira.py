"""
JIRA API 路由
提供 JIRA 相關的 API 端點
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any
from ..services.jira_client import JiraClient
from ..config import settings

router = APIRouter(prefix="/jira", tags=["jira"])

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