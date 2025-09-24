"""
Lark 使用者查詢 API

提供以本地 lark_users 表為資料來源的查詢（名稱、頭像）。
"""

from fastapi import APIRouter, HTTPException, status, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy import select, or_, func

from app.database import get_async_session
from app.models.database_models import LarkUser
from app.auth.dependencies import get_current_user
from app.auth.models import UserRole

router = APIRouter(prefix="/lark/users", tags=["lark_users"])


class LarkUserBasic(BaseModel):
    id: str
    name: Optional[str] = None
    avatar: Optional[str] = None


class LarkUserLite(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar: Optional[str] = None


class LarkUserListResponse(BaseModel):
    users: List[LarkUserLite]
    total: int
    page: int
    per_page: int


@router.get("/", response_model=LarkUserListResponse)
async def list_lark_users(
    search: Optional[str] = Query(None, description="搜尋關鍵字（姓名或企業信箱）"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    active_only: bool = Query(True, description="僅顯示啟用且未離職/未凍結/未離開的用戶"),
    current_user=Depends(get_current_user),
):
    # 僅 ADMIN/SUPER_ADMIN 可使用
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理員權限")

    try:
        async with get_async_session() as session:
            query = select(LarkUser)

            # Active 過濾
            if active_only:
                query = query.where(
                    LarkUser.is_activated.is_(True),
                ).where(
                    LarkUser.is_exited.is_(False)
                ).where(
                    LarkUser.is_frozen.is_(False)
                ).where(
                    LarkUser.is_resigned.is_(False)
                )

            # 搜尋條件
            if search:
                like = f"%{search}%"
                query = query.where(
                    or_(
                        LarkUser.name.ilike(like),
                        LarkUser.enterprise_email.ilike(like),
                    )
                )

            # 總數
            total_q = select(func.count()).select_from(query.subquery())
            total = (await session.execute(total_q)).scalar() or 0

            # 排序 + 分頁
            offset = (page - 1) * per_page
            query = query.order_by(LarkUser.name.asc()).offset(offset).limit(per_page)

            result = await session.execute(query)
            rows = result.scalars().all()

            users = [
                LarkUserLite(
                    id=row.user_id,
                    name=row.name,
                    email=row.enterprise_email,
                    avatar=row.avatar_240 or row.avatar_640 or row.avatar_origin,
                )
                for row in rows
            ]

            return LarkUserListResponse(users=users, total=total, page=page, per_page=per_page)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查詢 Lark 使用者列表時發生錯誤: {str(e)}"
        )


@router.get("/{lark_user_id}", response_model=LarkUserBasic)
async def get_lark_user_basic(lark_user_id: str):
    try:
        async with get_async_session() as session:
            result = await session.execute(select(LarkUser).where(LarkUser.user_id == lark_user_id))
            user = result.scalar_one_or_none()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="找不到對應的 Lark 使用者"
                )
            return LarkUserBasic(id=user.user_id, name=user.name, avatar=user.avatar_240)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查詢 Lark 使用者時發生錯誤: {str(e)}"
        )
