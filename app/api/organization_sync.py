#!/usr/bin/env python3
"""
全域組織架構同步 API 端點

提供不依賴特定團隊的組織架構同步功能，
適用於系統級別的組織數據維護。
"""

import logging
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from ..services.lark_org_sync_service import get_lark_org_sync_service

# 創建路由器
router = APIRouter(prefix="/organization", tags=["organization"])
logger = logging.getLogger(__name__)


@router.get("/sync/status")
async def get_organization_sync_status():
    """
    獲取組織架構同步狀態
    
    Returns:
        當前同步狀態和最後一次同步結果
    """
    try:
        sync_service = get_lark_org_sync_service()
        status = sync_service.get_sync_status()
        
        return {
            "success": True,
            "data": status
        }
        
    except Exception as e:
        logger.error(f"獲取組織同步狀態失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取同步狀態失敗: {str(e)}")


@router.get("/stats")
async def get_organization_stats():
    """
    獲取組織架構統計信息
    
    Returns:
        部門和用戶統計數據
    """
    try:
        sync_service = get_lark_org_sync_service()
        stats = sync_service.get_organization_stats()
        
        return {
            "success": True,
            "data": stats
        }
        
    except Exception as e:
        logger.error(f"獲取組織統計信息失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取統計信息失敗: {str(e)}")


@router.post("/sync")
async def trigger_organization_sync(
    background_tasks: BackgroundTasks,
    sync_type: str = Query("full", description="同步類型: full, departments, users")
):
    """
    觸發組織架構背景同步（無需團隊依賴）
    
    Args:
        sync_type: 同步類型（full: 完整同步, departments: 僅部門, users: 僅用戶）
        background_tasks: 背景任務管理器
        
    Returns:
        同步開始確認
    """
    try:
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 檢查是否已在同步中
        current_status = sync_service.get_sync_status()
        if current_status.get('is_syncing', False):
            return {
                "success": False,
                "message": "同步正在進行中，請稍後再試",
                "data": {
                    "is_syncing": True
                }
            }
        
        # 驗證同步類型
        if sync_type not in ['full', 'departments', 'users']:
            raise HTTPException(status_code=400, detail="無效的同步類型，支援: full, departments, users")
        
        # 執行背景同步
        def run_background_sync():
            try:
                if sync_type == "departments":
                    result = sync_service.sync_departments_only()
                elif sync_type == "users":
                    result = sync_service.sync_users_only()
                elif sync_type == "full":
                    result = sync_service.sync_full_organization()
                
                logger.info(f"背景組織同步完成: {result}")
            except Exception as e:
                logger.error(f"背景組織同步異常: {e}")
        
        background_tasks.add_task(run_background_sync)
        
        return {
            "success": True,
            "message": f"{sync_type} 組織同步已在背景開始",
            "data": {
                "sync_type": sync_type,
                "is_syncing": True
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發背景組織同步時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"觸發背景同步失敗: {str(e)}"
        )


@router.post("/sync/background")
async def trigger_organization_sync_background(
    sync_type: str = Query("full", description="同步類型: full, departments, users"),
    background_tasks: BackgroundTasks = None
):
    """
    觸發背景組織架構同步（無需團隊依賴）
    
    Args:
        sync_type: 同步類型（full: 完整同步, departments: 僅部門, users: 僅用戶）
        background_tasks: 背景任務管理器
        
    Returns:
        同步開始確認
    """
    try:
        if not background_tasks:
            raise HTTPException(status_code=400, detail="背景任務不可用")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 檢查是否已在同步中
        current_status = sync_service.get_sync_status()
        if current_status.get('is_syncing', False):
            return {
                "success": False,
                "message": "同步正在進行中，請稍後再試",
                "data": {
                    "is_syncing": True
                }
            }
        
        # 執行背景同步
        def run_background_sync():
            try:
                if sync_type == "departments":
                    result = sync_service.sync_departments_only()
                elif sync_type == "users":
                    result = sync_service.sync_users_only()
                elif sync_type == "full":
                    result = sync_service.sync_full_organization()
                else:
                    logger.error(f"無效的同步類型: {sync_type}")
                    return
                
                logger.info(f"背景組織同步完成: {result}")
            except Exception as e:
                logger.error(f"背景組織同步異常: {e}")
        
        background_tasks.add_task(run_background_sync)
        
        return {
            "success": True,
            "message": f"{sync_type} 組織同步已在背景開始",
            "data": {
                "sync_type": sync_type,
                "is_syncing": True
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發背景組織同步時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"觸發背景同步失敗: {str(e)}"
        )


@router.delete("/cleanup")
async def cleanup_organization_data(
    days_threshold: int = Query(30, description="清理超過指定天數的舊數據")
):
    """
    清理組織架構舊數據
    
    Args:
        days_threshold: 天數閾值，清理超過此天數的非活躍數據
        
    Returns:
        清理操作結果
    """
    try:
        sync_service = get_lark_org_sync_service()
        cleanup_result = sync_service.cleanup_old_data(days_threshold)
        
        if 'error' in cleanup_result:
            raise HTTPException(status_code=500, detail=cleanup_result['error'])
        
        return {
            "success": True,
            "data": cleanup_result,
            "message": f"清理完成，共清理 {cleanup_result.get('total_cleaned', 0)} 筆舊數據"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清理組織數據時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"清理數據失敗: {str(e)}"
        )