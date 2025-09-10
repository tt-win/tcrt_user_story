"""
Lark 群組查詢 API

提供群組列表查詢的 REST API 端點
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Dict, Optional
import logging

from app.services.lark_group_service import get_lark_group_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/lark", tags=["lark-integration"])


@router.get("/groups", response_model=List[Dict[str, str]])
async def get_lark_groups(
    q: Optional[str] = Query(None, description="搜尋關鍵字（群組名稱包含）", max_length=50)
):
    """
    取得 Lark 群組列表，支援關鍵字搜尋
    
    Args:
        q: 搜尋關鍵字，會在群組名稱中進行不分大小寫的包含搜尋
        
    Returns:
        群組列表：[{"chat_id": "oc_xxx", "name": "群組名稱"}]
        
    Raises:
        HTTPException: 當 Lark API 調用失敗或配置錯誤時
    """
    try:
        # 取得群組服務
        lark_service = get_lark_group_service()
        
        # 查詢群組列表
        groups = lark_service.list_groups(query=q)
        
        return groups
        
    except Exception as e:
        logger.error(f"查詢 Lark 群組時發生錯誤: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"無法查詢 Lark 群組: {str(e)}"
        )
