#!/usr/bin/env python3
"""
團隊同步 API 端點

提供團隊的 Lark 組織架構同步相關功能：
- 觸發同步操作
- 獲取同步進度和狀態
- 查看同步歷史記錄
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ..database import get_db, run_sync
from ..models.database_models import Team, LarkDepartment, LarkUser
from ..services.lark_org_sync_service import get_lark_org_sync_service

# 創建路由器
router = APIRouter(prefix="/teams", tags=["team-sync"])

# 日誌記錄器
logger = logging.getLogger(__name__)


class SyncTriggerRequest(BaseModel):
    """同步觸發請求"""
    sync_type: str = "full"  # full, departments, users
    trigger_user: Optional[str] = None


class SyncStatusResponse(BaseModel):
    """同步狀態響應"""
    is_syncing: bool
    current_progress: Optional[str] = None
    last_sync_start: Optional[str] = None
    last_sync_end: Optional[str] = None
    sync_id: Optional[int] = None


class OrganizationStatsResponse(BaseModel):
    """組織架構統計響應"""
    total_departments: int
    total_users: int
    last_sync_time: Optional[str] = None
    sync_status: Optional[str] = None


@router.get("/{team_id}/sync/status")
async def get_sync_status(
    team_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    獲取團隊同步狀態
    
    Returns:
        同步狀態信息，包含是否正在同步、最後同步時間等
    """
    try:
        def _ensure_team(sync_db: Session):
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="團隊不存在")

        await run_sync(db, _ensure_team)
        
        # 獲取同步服務
        sync_service = get_lark_org_sync_service()
        
        # 獲取同步狀態
        status = sync_service.get_sync_status()
        
        return {
            "success": True,
            "data": {
                "is_syncing": status.get('is_syncing', False),
                "current_progress": "同步中..." if status.get('is_syncing', False) else None,
                "last_sync_start": status.get('last_sync_start'),
                "last_sync_end": status.get('last_sync_end'),
                "sync_id": status.get('current_sync_id'),
                "last_result": status.get('last_sync_result')
            }
        }
        
    except Exception as e:
        logger.error(f"獲取同步狀態失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取同步狀態失敗: {str(e)}")


@router.get("/{team_id}/sync/stats")
async def get_organization_stats(
    team_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    獲取組織架構統計信息
    
    Returns:
        部門和用戶數量統計，最後同步時間等
    """
    try:
        def _load_stats(sync_db: Session):
            # 檢查團隊是否存在
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="團隊不存在")

            # 從資料庫直接獲取統計
            total_departments = sync_db.query(LarkDepartment).filter(
                LarkDepartment.status == 'active'
            ).count()

            total_users = sync_db.query(LarkUser).filter(
                LarkUser.is_activated == True,
                LarkUser.is_exited == False
            ).count()

            # 獲取最後同步時間
            last_sync_dept = sync_db.query(LarkDepartment.last_sync_at).order_by(
                LarkDepartment.last_sync_at.desc()
            ).first()

            last_sync_user = sync_db.query(LarkUser.last_sync_at).order_by(
                LarkUser.last_sync_at.desc()
            ).first()

            last_sync_time = None
            if last_sync_dept and last_sync_dept[0]:
                last_sync_time = last_sync_dept[0].isoformat()
            elif last_sync_user and last_sync_user[0]:
                last_sync_time = last_sync_user[0].isoformat()

            return total_departments, total_users, last_sync_time

        total_departments, total_users, last_sync_time = await run_sync(db, _load_stats)
        
        # 獲取同步狀態
        sync_service = get_lark_org_sync_service()
        sync_status = sync_service.get_sync_status()
        
        return {
            "success": True,
            "data": {
                "total_departments": total_departments,
                "total_users": total_users,
                "last_sync_time": last_sync_time,
                "sync_status": "syncing" if sync_status.get('is_syncing', False) else "idle",
                "detailed_stats": {
                    "departments": {
                        "total": total_departments,
                        "active": total_departments
                    },
                    "users": {
                        "total": total_users,
                        "active": total_users
                    }
                }
            }
        }
        
    except Exception as e:
        logger.error(f"獲取組織架構統計失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取組織架構統計失敗: {str(e)}")


@router.post("/{team_id}/sync/trigger")
async def trigger_sync(
    team_id: int,
    request: SyncTriggerRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """
    觸發團隊同步操作
    
    Args:
        team_id: 團隊 ID
        request: 同步請求參數
        background_tasks: 背景任務
        db: 資料庫連線
        
    Returns:
        同步操作結果和同步ID
    """
    try:
        def _ensure_team(sync_db: Session):
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="團隊不存在")

        await run_sync(db, _ensure_team)
        
        # 驗證同步類型
        if request.sync_type not in ['full', 'departments', 'users']:
            raise HTTPException(status_code=400, detail="不支援的同步類型")
        
        # 獲取同步服務
        sync_service = get_lark_org_sync_service()
        
        # 檢查是否已在同步中
        current_status = sync_service.get_sync_status()
        if current_status.get('is_syncing', False):
            return {
                "success": False,
                "message": "同步正在進行中，請稍後再試",
                "data": {
                    "is_syncing": True,
                    "sync_id": current_status.get('current_sync_id')
                }
            }
        
        # 執行同步（背景任務方式）
        async def run_sync_task():
            try:
                result = await sync_service.sync_for_team(
                    None,
                    team_id=team_id,
                    sync_type=request.sync_type,
                    trigger_user=request.trigger_user
                )
                logger.info(f"背景同步完成: {result}")
            except Exception as e:
                logger.error(f"背景同步異常: {e}")

        background_tasks.add_task(run_sync_task)
        
        # 立即回傳同步已開始的狀態
        return {
            "success": True,
            "message": f"{request.sync_type} 同步已開始",
            "data": {
                "sync_type": request.sync_type,
                "trigger_user": request.trigger_user,
                "is_syncing": True,
                "start_time": current_status.get('last_sync_start')
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發同步失敗: {e}")
        raise HTTPException(status_code=500, detail=f"觸發同步失敗: {str(e)}")




@router.get("/{team_id}/sync/progress/{sync_id}")
async def get_sync_progress(
    team_id: int,
    sync_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    獲取特定同步操作的進度
    
    Args:
        team_id: 團隊 ID
        sync_id: 同步記錄 ID
        db: 資料庫連線
        
    Returns:
        同步進度信息
    """
    try:
        def _ensure_team(sync_db: Session):
            team = sync_db.query(Team).filter(Team.id == team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="團隊不存在")

        await run_sync(db, _ensure_team)
        
        # 獲取同步服務
        sync_service = get_lark_org_sync_service()
        
        # 獲取當前同步狀態
        current_status = sync_service.get_sync_status()
        
        # 如果是當前正在同步的操作
        if current_status.get('current_sync_id') == sync_id:
            return {
                "success": True,
                "data": {
                    "sync_id": sync_id,
                    "status": "running",
                    "is_syncing": True,
                    "progress": "同步進行中...",
                    "start_time": current_status.get('last_sync_start'),
                    "estimated_completion": None
                }
            }
        
        # 由於移除了同步歷史功能，無法從歷史記錄查找
        raise HTTPException(status_code=404, detail="同步記錄功能已移除")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"獲取同步進度失敗: {e}")
        raise HTTPException(status_code=500, detail=f"獲取同步進度失敗: {str(e)}")
