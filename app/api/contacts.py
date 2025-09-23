#!/usr/bin/env python3
"""
聯絡人 API 端點

提供從本地數據庫獲取聯絡人資訊的 API 端點，
支援團隊聯絡人列表和搜尋建議功能。
數據來源：定時同步的 Lark 組織架構數據。
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlalchemy.orm import Session

from ..database import get_db, get_sync_db
from ..models.database_models import Team
from ..services.lark_org_sync_service import get_lark_org_sync_service

# 創建路由器
router = APIRouter(prefix="/teams", tags=["contacts"])

# 日誌記錄器
logger = logging.getLogger(__name__)


@router.get("/{team_id}/contacts")
async def get_team_contacts(
    team_id: int,
    q: Optional[str] = Query(None, description="搜尋關鍵字"),
    limit: int = Query(50, ge=1, le=100, description="結果數量限制"),
    db: Session = Depends(get_sync_db)
):
    """
    獲取團隊聯絡人列表
    
    支援搜尋功能：
    - 如果提供 q 參數，返回搜尋結果
    - 如果不提供 q 參數，返回前 N 個用戶
    
    Args:
        team_id: 團隊 ID
        q: 搜尋關鍵字（可選）
        limit: 結果數量限制
        db: 資料庫連線
        
    Returns:
        聯絡人列表，包含用戶資訊和搜尋結果
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 如果有搜尋關鍵字，使用搜尋功能
        if q and q.strip():
            result = sync_service.search_contacts_for_team(team_id, q.strip(), limit)
        else:
            # 否則獲取完整聯絡人列表
            result = sync_service.get_contacts_for_team(team_id, limit)
        
        if result.get('success', False):
            contacts_data = result['data']
            return {
                "success": True,
                "data": {
                    "contacts": contacts_data.get('contacts', []),
                    "query": q,
                    "total": contacts_data.get('total', 0),
                    "limit": limit,
                    "has_more": len(contacts_data.get('contacts', [])) >= limit
                },
                "message": f"找到 {contacts_data.get('total', 0)} 個聯絡人" if contacts_data.get('contacts') else "未找到符合條件的聯絡人"
            }
        else:
            # 同步服務失敗，返回空結果但保持成功狀態以兼容前端
            logger.warning(f"獲取團隊 {team_id} 聯絡人失敗: {result.get('message', '未知錯誤')}")
            return {
                "success": True,  # 保持成功狀態以兼容現有前端
                "data": {
                    "contacts": [],
                    "query": q,
                    "total": 0,
                    "limit": limit,
                    "has_more": False
                },
                "message": "聯絡人數據暫未同步，請稍後再試或聯繫管理員",
                "warning": result.get('message', '數據同步中')
            }
        
    except Exception as e:
        logger.error(f"獲取團隊聯絡人時發生異常: {e}")
        
        # 返回空結果而非錯誤，保持 API 兼容性
        return {
            "success": True,
            "data": {
                "contacts": [],
                "query": q,
                "total": 0,
                "limit": limit,
                "has_more": False
            },
            "message": "獲取聯絡人暫時失敗，請稍後再試",
            "error": str(e)
        }


@router.get("/{team_id}/contacts/{user_id}")
async def get_contact_by_id(
    team_id: int,
    user_id: str,
    db: Session = Depends(get_sync_db)
):
    """
    根據用戶 ID 獲取聯絡人詳細資訊
    
    Args:
        team_id: 團隊 ID
        user_id: 用戶 ID
        db: 資料庫連線
        
    Returns:
        聯絡人詳細資訊
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 搜索特定用戶（使用用戶 ID 作為關鍵字）
        search_result = sync_service.search_contacts_for_team(team_id, user_id, 1)
        
        if search_result.get('success', False) and search_result.get('data', {}).get('suggestions'):
            user = search_result['data']['suggestions'][0]
            
            # 檢查是否確實匹配
            if user.get('id') == user_id:
                return {
                    "success": True,
                    "data": {
                        "contact": user
                    },
                    "message": "聯絡人資訊獲取成功"
                }
        
        raise HTTPException(status_code=404, detail="聯絡人不存在")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"獲取聯絡人詳細資訊時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"獲取聯絡人詳細資訊失敗: {str(e)}"
        )


@router.post("/{team_id}/contacts/refresh")
async def refresh_contacts_cache(
    team_id: int,
    db: Session = Depends(get_sync_db)
):
    """
    觸發聯絡人數據同步
    
    適用情況：
    - 需要最新的組織架構數據
    - 手動觸發同步過程
    
    Args:
        team_id: 團隊 ID
        db: 資料庫連線
        
    Returns:
        同步操作結果
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 檢查是否已在同步中
        status = sync_service.get_sync_status()
        if status.get('is_syncing', False):
            return {
                "success": False,
                "message": "組織架構同步正在進行中，請稍後再試",
                "data": {
                    "is_syncing": True,
                    "start_time": status.get('last_sync_start')
                }
            }
        
        # 執行完整組織架構同步
        logger.info(f"手動觸發團隊 {team_id} 的組織架構同步...")
        sync_result = sync_service.sync_full_organization()
        
        if sync_result.get('success', False):
            # 獲取統計信息
            org_stats = sync_service.get_organization_stats()
            
            return {
                "success": True,
                "data": {
                    "sync_result": sync_result,
                    "organization_stats": org_stats,
                    "refresh_time": sync_result.get('sync_time', 'unknown')
                },
                "message": sync_result.get('message', '組織架構同步成功')
            }
        else:
            return {
                "success": False,
                "data": {
                    "sync_result": sync_result
                },
                "message": f"組織架構同步失敗: {sync_result.get('message', '未知錯誤')}"
            }
        
    except Exception as e:
        logger.error(f"刷新聯絡人數據時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"刷新聯絡人數據失敗: {str(e)}"
        )


@router.get("/{team_id}/contacts/search/suggestions")
async def get_search_suggestions(
    team_id: int,
    q: str = Query(..., min_length=1, description="搜尋關鍵字"),
    limit: int = Query(10, ge=1, le=20, description="建議數量"),
    db: Session = Depends(get_sync_db)
):
    """
    獲取搜尋建議（用於自動完成）
    
    提供快速搜尋建議，適合前端下拉式選單的即時搜尋
    
    Args:
        team_id: 團隊 ID
        q: 搜尋關鍵字
        limit: 建議數量（較小）
        db: 資料庫連線
        
    Returns:
        搜尋建議列表，包含精簡的用戶資訊
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 搜尋建議
        result = sync_service.search_contacts_for_team(team_id, q.strip(), limit)
        
        if result.get('success', False):
            return {
                "success": True,
                "data": {
                    "suggestions": result['data'].get('suggestions', []),
                    "query": q,
                    "total": result['data'].get('total', 0)
                }
            }
        else:
            # 對於建議 API，如果出錯就返回空列表，不中斷用戶體驗
            logger.warning(f"獲取搜尋建議失敗: {result.get('message', '未知錯誤')}")
            return {
                "success": True,  # 保持成功狀態以兼容前端
                "data": {
                    "suggestions": [],
                    "query": q,
                    "total": 0
                },
                "message": "搜尋建議暫時不可用"
            }
        
    except Exception as e:
        # 對於建議 API，如果出錯就返回空列表，不中斷用戶體驗
        logger.error(f"獲取搜尋建議時發生異常: {e}")
        return {
            "success": True,
            "data": {
                "suggestions": [],
                "query": q,
                "total": 0
            },
            "error": str(e)
        }


@router.get("/{team_id}/contacts/stats")
async def get_contacts_stats(
    team_id: int,
    db: Session = Depends(get_sync_db)
):
    """
    獲取聯絡人統計信息
    
    Args:
        team_id: 團隊 ID
        db: 資料庫連線
        
    Returns:
        聯絡人和組織架構統計信息
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 獲取組織架構統計
        stats = sync_service.get_organization_stats()
        
        return {
            "success": True,
            "data": stats,
            "message": "統計信息獲取成功"
        }
        
    except Exception as e:
        logger.error(f"獲取聯絡人統計時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"獲取聯絡人統計失敗: {str(e)}"
        )


@router.post("/{team_id}/contacts/sync")
async def trigger_sync(
    team_id: int,
    sync_type: str = Query("full", description="同步類型: full, departments, users"),
    db: Session = Depends(get_sync_db)
):
    """
    觸發組織架構同步（管理員功能）
    
    Args:
        team_id: 團隊 ID
        sync_type: 同步類型（full: 完整同步, departments: 僅部門, users: 僅用戶）
        db: 資料庫連線
        
    Returns:
        同步操作結果
    """
    try:
        # 檢查團隊是否存在
        team = db.query(Team).filter(Team.id == team_id).first()
        if not team:
            raise HTTPException(status_code=404, detail="團隊不存在")
        
        # 獲取組織同步服務
        sync_service = get_lark_org_sync_service()
        
        # 根據同步類型執行不同的同步操作
        if sync_type == "departments":
            result = sync_service.sync_departments_only()
        elif sync_type == "users":
            result = sync_service.sync_users_only()
        elif sync_type == "full":
            result = sync_service.sync_full_organization()
        else:
            raise HTTPException(status_code=400, detail="無效的同步類型，支援: full, departments, users")
        
        return {
            "success": result.get('success', False),
            "data": {
                "sync_type": sync_type,
                "sync_result": result
            },
            "message": result.get('message', f'{sync_type} 同步完成')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"觸發同步時發生異常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"觸發同步失敗: {str(e)}"
        )