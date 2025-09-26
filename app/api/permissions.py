"""Permissions-related API endpoints"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.auth.permission_service import permission_service
from app.models.database_models import User

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("/ui-config")
async def get_ui_config(
    page: str = Query(..., description="頁面識別字串，例如 organization 或 team_management"),
    current_user: User = Depends(get_current_user),
):
    """回傳指定頁面 UI 元件的可視設定"""
    try:
        config = await permission_service.get_ui_config(current_user, page)
        return config
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "取得 UI 設定失敗: user_id=%s page=%s error=%s",
            getattr(current_user, "id", "?"),
            page,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得 UI 設定時發生錯誤",
        ) from exc
