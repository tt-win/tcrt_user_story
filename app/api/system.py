"""
系統初始化 API
處理系統初始化檢查和 Super Admin 建立相關的 API 端點
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.services.system_init_service import SystemInitService
from app.auth.models import UserRole


router = APIRouter(prefix="/api/system", tags=["System"])


# ===================== 請求/回應模型 =====================

class SystemInitRequest(BaseModel):
    """系統初始化請求模型"""
    username: str = Field(..., min_length=3, max_length=50, description="管理員使用者名稱")
    password: str = Field(..., min_length=8, description="密碼")
    confirm_password: str = Field(..., min_length=8, description="確認密碼")


class SystemStatusResponse(BaseModel):
    """系統狀態回應模型"""
    is_initialized: bool = Field(..., description="系統是否已初始化")
    total_users: int = Field(0, description="總使用者數")
    active_users: int = Field(0, description="活躍使用者數")
    super_admin_count: int = Field(0, description="Super Admin 數量")
    checked_at: str = Field(..., description="檢查時間")


class SystemInitResponse(BaseModel):
    """系統初始化回應模型"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="回應訊息")
    user_id: int = Field(None, description="建立的使用者 ID")
    username: str = Field(None, description="建立的使用者名稱")
    role: str = Field(None, description="使用者角色")
    created_at: str = Field(None, description="建立時間")
    error: str = Field(None, description="錯誤訊息")


# ===================== API 端點 =====================

@router.get("/status", response_model=Dict[str, Any])
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """
    取得系統狀態
    
    回傳系統初始化狀態、使用者統計等資訊
    """
    try:
        init_service = SystemInitService(db)
        stats = await init_service.get_system_stats()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=stats
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": f"取得系統狀態時發生錯誤: {str(e)}",
                "is_initialized": False
            }
        )


@router.get("/initialization-check")
async def check_initialization_needed(db: AsyncSession = Depends(get_db)):
    """
    檢查系統是否需要初始化
    
    Returns:
        Dict: 包含是否需要初始化的資訊
    """
    try:
        init_service = SystemInitService(db)
        is_initialized = await init_service.check_system_initialized()
        stats = await init_service.get_system_stats()
        checked_at = stats.get("checked_at")
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "is_initialized": is_initialized,
                "needs_setup": not is_initialized,
                "setup_url": "/setup" if not is_initialized else None,
                "checked_at": checked_at
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": f"檢查初始化狀態時發生錯誤: {str(e)}",
                "is_initialized": False,
                "needs_setup": True,
                "setup_url": "/setup"
            }
        )


@router.get("/initialization-guide")
async def get_initialization_guide():
    """
    取得系統初始化指引
    
    Returns:
        Dict: 初始化指引資訊
    """
    try:
        init_service = SystemInitService()
        guide = init_service.get_initialization_guide()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=guide
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": f"取得初始化指引時發生錯誤: {str(e)}"
            }
        )


@router.post("/initialize", response_model=Dict[str, Any])
async def initialize_system(
    request: SystemInitRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    初始化系統
    
    建立第一個 Super Admin 使用者並完成系統初始化
    
    Args:
        request: 初始化請求資料
        db: 資料庫會話
        
    Returns:
        Dict: 初始化結果
    """
    try:
        init_service = SystemInitService(db)
        if await init_service.check_system_initialized():
            init_state = {"already_initialized": True, "result": None}
        else:
            admin_data = {
                "username": request.username,
                "password": request.password,
                "confirm_password": request.confirm_password
            }
            result = await init_service.initialize_system(admin_data)
            init_state = {"already_initialized": False, "result": result}

        if init_state["already_initialized"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": "系統已經初始化，不能重複執行初始化程序"
                }
            )

        result = init_state["result"]
        
        if result.get("success"):
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content=result
            )
        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )
            
    except Exception as e:
        error_msg = f"系統初始化時發生錯誤: {str(e)}"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": error_msg
            }
        )


@router.get("/health")
async def system_health_check(db: AsyncSession = Depends(get_db)):
    """
    系統健康檢查
    
    檢查資料庫連線、必要資料表等
    """
    try:
        init_service = SystemInitService(db)

        try:
            stats = await init_service.get_system_stats()
            db_healthy = True
        except Exception as db_error:
            db_healthy = False
            stats = {"error": str(db_error)}
        
        health_status = {
            "status": "healthy" if db_healthy else "unhealthy",
            "database": {
                "connected": db_healthy,
                "tables_exist": stats.get("tables_exist", {}),
                "error": stats.get("error") if not db_healthy else None
            },
            "system": {
                "is_initialized": stats.get("is_initialized", False),
                "total_users": stats.get("total_users", 0),
                "active_users": stats.get("active_users", 0)
            },
            "checked_at": stats.get("checked_at")
        }
        
        status_code = status.HTTP_200_OK if db_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        
        return JSONResponse(
            status_code=status_code,
            content=health_status
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "error": f"健康檢查時發生錯誤: {str(e)}",
                "checked_at": None
            }
        )


# ===================== 管理員專用端點 =====================

@router.get("/admin/reset-initialization-check")
async def admin_reset_initialization_check(
    db: AsyncSession = Depends(get_db),
    # current_user: User = Depends(require_super_admin)  # 需要 Super Admin 權限
):
    """
    管理員重設初始化檢查（調試用）
    
    注意：此端點僅用於開發/調試，生產環境應移除或嚴格限制存取
    """
    try:
        init_service = SystemInitService(db)
        current_stats = await init_service.get_system_stats()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "初始化檢查已重設",
                "current_system_stats": current_stats,
                "warning": "此功能僅用於開發/調試目的"
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": f"重設初始化檢查時發生錯誤: {str(e)}"
            }
        )


# ===================== 工具函數 =====================

async def is_system_initialized(db: AsyncSession) -> bool:
    """
    檢查系統是否已初始化的工具函數
    
    可在其他模組中使用來檢查系統狀態
    """
    try:
        init_service = SystemInitService(db)
        return await init_service.check_system_initialized()
    except Exception:
        return False
