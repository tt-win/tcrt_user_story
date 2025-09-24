"""
使用者管理 API 端點

提供使用者的 CRUD 操作，需要適當的管理員權限
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
import logging
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole, UserCreate
from app.auth.password_service import PasswordService
from app.services.user_service import UserService
from app.models.database_models import User
from app.database import get_async_session
from sqlalchemy import select, and_, or_, func

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


class UserCreateRequest(BaseModel):
    """建立使用者請求模型"""
    username: str
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: UserRole = UserRole.USER
    password: Optional[str] = None  # 如果不提供，會自動生成
    is_active: bool = True
    lark_user_id: Optional[str] = None

    @validator('username')
    def validate_username(cls, v):
        if not v or len(v) < 3:
            raise ValueError('使用者名稱至少需要 3 個字元')
        return v


class UserUpdateRequest(BaseModel):
    """更新使用者請求模型"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None  # 密碼重設
    lark_user_id: Optional[str] = None


class UserResponse(BaseModel):
    """使用者回應模型"""
    id: int
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: str
    is_active: bool
    lark_user_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime]
    last_login_at: Optional[datetime]


class UserListResponse(BaseModel):
    """使用者列表回應模型"""
    users: List[UserResponse]
    total: int
    page: int
    per_page: int


class PasswordResetResponse(BaseModel):
    """密碼重設回應模型"""
    message: str
    new_password: Optional[str] = None  # 只在自動生成時返回


# ===================== 個人資料相關模型 =====================

class UserSelfOut(BaseModel):
    """使用者自己的資料輸出模型"""
    id: int
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    last_login_at: Optional[datetime]
    teams: List[str] = []  # 所屬團隊名稱列表


class UserSelfUpdate(BaseModel):
    """使用者自己可更新的欄位模型"""
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None

    @validator('email')
    def validate_email(cls, v):
        if v is not None and len(str(v).strip()) == 0:
            v = None  # 空字串轉為 None
        return v


class PasswordChangeRequest(BaseModel):
    """修改密碼請求模型"""
    current_password: str = Field(..., description="目前密碼")
    new_password: str = Field(..., min_length=8, description="新密碼（最少8字符）")

    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('新密碼長度至少需要8個字符')
        return v


@router.get("/", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1, description="頁碼"),
    per_page: int = Query(20, ge=1, le=100, description="每頁筆數"),
    search: Optional[str] = Query(None, description="搜尋關鍵字 (使用者名稱、email、姓名)"),
    role: Optional[UserRole] = Query(None, description="角色篩選"),
    is_active: Optional[bool] = Query(None, description="狀態篩選"),
    current_user: User = Depends(get_current_user)
):
    """
    列出使用者清單

    需要 ADMIN+ 權限。支援分頁、搜尋和篩選功能。
    """
    # 權限檢查：需要 ADMIN+ 權限
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )

    try:
        async with get_async_session() as session:
            # 建立基礎查詢
            query = select(User)

            # 搜尋條件
            if search:
                search_filter = or_(
                    User.username.ilike(f"%{search}%"),
                    User.email.ilike(f"%{search}%"),
                    User.full_name.ilike(f"%{search}%")
                )
                query = query.where(search_filter)

            # 角色篩選
            if role:
                query = query.where(User.role == role)

            # 狀態篩選
            if is_active is not None:
                query = query.where(User.is_active == is_active)

            # 總數查詢
            total_query = select(func.count()).select_from(query.subquery())
            total_result = await session.execute(total_query)
            total = total_result.scalar()

            # 分頁查詢
            offset = (page - 1) * per_page
            query = query.offset(offset).limit(per_page).order_by(User.created_at.desc())

            result = await session.execute(query)
            users = result.scalars().all()

            user_responses = [
                UserResponse(
                    id=user.id,
                    username=user.username,
                    email=user.email,
                    full_name=user.full_name,
                    role=user.role.value,
                    is_active=user.is_active,
                    lark_user_id=getattr(user, 'lark_user_id', None),
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                    last_login_at=user.last_login_at
                )
                for user in users
            ]

            return UserListResponse(
                users=user_responses,
                total=total,
                page=page,
                per_page=per_page
            )

    except Exception as e:
        logger.error(f"列出使用者失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得使用者列表時發生錯誤"
        )


@router.post("/", response_model=UserResponse)
async def create_user(
    request: UserCreateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    建立新使用者

    需要 SUPER_ADMIN 權限。
    """
    # 權限檢查：需要 SUPER_ADMIN 權限
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超級管理員權限"
        )

    try:
        # 轉換為 UserCreate 物件
        # 禁止建立第二位超級管理員
        if request.role == UserRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="系統僅允許一位超級管理員"
            )

        user_create = UserCreate(
            username=request.username,
            email=request.email,
            full_name=request.full_name,
            role=request.role,
            password=request.password,  # 如果為空會在 UserService 中處理
            is_active=request.is_active,
            primary_team_id=None,
            lark_user_id=request.lark_user_id
        )
        
        # 使用統一的 UserService 建立使用者
        new_user = await UserService.create_user_async(user_create)
        
        logger.info(f"管理員 {current_user.username} 建立了新使用者 {new_user.username}")
        
        return UserResponse(
            id=new_user.id,
            username=new_user.username,
            email=new_user.email,
            full_name=new_user.full_name,
            role=new_user.role.value,
            is_active=new_user.is_active,
            lark_user_id=getattr(new_user, 'lark_user_id', None),
            created_at=new_user.created_at,
            updated_at=new_user.updated_at,
            last_login_at=new_user.last_login_at
        )

    except ValueError as e:
        # UserService 抛出的 ValueError 轉為 HTTP 400 錯誤
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"建立使用者失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="建立使用者時發生錯誤"
        )


# ===================== 個人資料 API =====================

@router.get("/me", response_model=UserSelfOut)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """
    取得目前使用者的資料

    任何已登入的使用者都可以查看自己的資料。
    """
    try:
        # TODO: 取得使用者所屬的團隊名稱
        # 這裡需要根據實際的數據庫結構來實作
        teams = []
        
        return UserSelfOut(
            id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            full_name=current_user.full_name,
            role=current_user.role.value,
            is_active=current_user.is_active,
            created_at=current_user.created_at,
            updated_at=current_user.updated_at,
            last_login_at=current_user.last_login_at,
            teams=teams
        )
        
    except Exception as e:
        logger.error(f"取得使用者資料失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得使用者資料時發生錯誤"
        )


@router.put("/me", response_model=UserSelfOut)
async def update_current_user_profile(
    request: UserSelfUpdate,
    current_user: User = Depends(get_current_user)
):
    """
    更新目前使用者的資料

    使用者只能更新自己的基本資料，不能修改角色或狀態。
    """
    try:
        async with get_async_session() as session:
            # 取得最新的使用者資料
            user = await session.get(User, current_user.id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            # 檢查 email 是否重複（如果要更新且不為空）
            if request.email and request.email != user.email:
                existing_email = await session.execute(
                    select(User).where(and_(User.email == str(request.email), User.id != user.id))
                )
                if existing_email.scalar():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="電子信箱已被使用"
                    )

            # 更新欄位
            updated = False
            if request.full_name is not None and request.full_name != user.full_name:
                user.full_name = request.full_name.strip() if request.full_name else None
                updated = True
                
            if request.email is not None and str(request.email) != user.email:
                user.email = str(request.email) if request.email else None
                updated = True

            if updated:
                user.updated_at = datetime.utcnow()
                await session.commit()
                await session.refresh(user)

            logger.info(f"使用者 {user.username} 更新了個人資料")

            # TODO: 取得使用者所屬的團隊名稱
            teams = []

            return UserSelfOut(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
                teams=teams
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新使用者資料失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新使用者資料時發生錯誤"
        )


@router.put("/me/password")
async def change_current_user_password(
    request: PasswordChangeRequest,
    current_user: User = Depends(get_current_user)
):
    """
    修改目前使用者的密碼

    使用者必須提供目前密碼來驗證身分。
    """
    try:
        # 驗證目前密碼
        if not PasswordService.verify_password(request.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="目前密碼不正確"
            )

        # 檢查新密碼是否與舊密碼相同
        if PasswordService.verify_password(request.new_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="新密碼不能與舊密碼相同"
            )

        async with get_async_session() as session:
            # 取得最新的使用者資料
            user = await session.get(User, current_user.id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            # 更新密碼
            user.hashed_password = PasswordService.hash_password(request.new_password)
            user.updated_at = datetime.utcnow()

            await session.commit()

            logger.info(f"使用者 {user.username} 修改了密碼")

            return {"message": "密碼修改成功"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改密碼失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="修改密碼時發生錯誤"
        )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    取得特定使用者資訊

    需要 ADMIN+ 權限，或者查詢自己的資訊。
    """
    # 權限檢查：ADMIN+ 或查詢自己
    admin_roles = [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    if current_user.role not in admin_roles and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="權限不足"
        )

    try:
        async with get_async_session() as session:
            user = await session.get(User, user_id)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            return UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                lark_user_id=getattr(user, 'lark_user_id', None),
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取得使用者失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得使用者資訊時發生錯誤"
        )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    更新使用者資訊

    需要 ADMIN+ 權限。角色變更需要 SUPER_ADMIN 權限。
    """
    # 權限檢查：需要 ADMIN+ 權限
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )

    # 角色變更規則：
    # - Super Admin 可變更他人為 viewer/user/admin，但不可設定 super_admin
    # - Admin 可對 user/viewer 變更為 viewer/user；不可設定 admin/super_admin，也不可修改 admin/super_admin 帳號
    if request.role is not None:
        if current_user.role == UserRole.SUPER_ADMIN:
            if request.role == UserRole.SUPER_ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="不可指派超級管理員角色"
                )
        elif current_user.role == UserRole.ADMIN:
            # 需先取得目標使用者角色後再判斷，邏輯在後續讀取 user 後再次檢查
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="需要管理員權限"
            )

    try:
        async with get_async_session() as session:
            user = await session.get(User, user_id)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            # Admin 不得修改 admin/super_admin 帳號
            if current_user.role == UserRole.ADMIN and user.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin 不得修改 admin/super_admin 帳號"
                )

            # Super Admin 不可將任一帳號設為 super_admin；且不可將唯一 super_admin 降級/停用
            if request.role is not None:
                if current_user.role == UserRole.SUPER_ADMIN and request.role == UserRole.SUPER_ADMIN:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="不可指派超級管理員角色"
                    )
                if current_user.role == UserRole.ADMIN:
                    # Admin 僅能在 user/viewer 間調整
                    if user.role not in [UserRole.USER, UserRole.VIEWER] or request.role not in [UserRole.USER, UserRole.VIEWER]:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin 僅能在 user/viewer 之間調整角色"
                        )

            # 唯一超管保護：若要將 super_admin 降級或停用
            if user.role == UserRole.SUPER_ADMIN:
                demote = (request.role is not None and request.role != UserRole.SUPER_ADMIN)
                deactivate = (request.is_active is not None and request.is_active is False)
                if demote or deactivate:
                    count_result = await session.execute(select(func.count()).where(User.role == UserRole.SUPER_ADMIN))
                    sa_count = count_result.scalar() or 0
                    if sa_count <= 1:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="不可移除唯一的超級管理員"
                        )

            # 檢查 email 是否重複（如果要更新且不為空）
            if request.email and request.email != user.email:
                existing_email = await session.execute(
                    select(User).where(and_(User.email == request.email, User.id != user_id))
                )
                if existing_email.scalar():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="電子信箱已被使用"
                    )

            # 更新欄位
            if request.email is not None:
                user.email = request.email
            if request.full_name is not None:
                user.full_name = request.full_name
            if request.role is not None:
                user.role = request.role
            if request.is_active is not None:
                user.is_active = request.is_active
            if request.password is not None:
                user.hashed_password = PasswordService.hash_password(request.password)
            if request.lark_user_id is not None:
                user.lark_user_id = request.lark_user_id

            user.updated_at = datetime.utcnow()

            await session.commit()
            await session.refresh(user)

            logger.info(f"管理員 {current_user.username} 更新了使用者 {user.username}")

            return UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                lark_user_id=getattr(user, 'lark_user_id', None),
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新使用者失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新使用者時發生錯誤"
        )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    刪除使用者 (軟刪除)

    需要 SUPER_ADMIN 權限。
    """
    # 權限檢查：需要 SUPER_ADMIN 權限
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要超級管理員權限"
        )

    # 防止刪除自己
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能刪除自己的帳號"
        )

    try:
        async with get_async_session() as session:
            user = await session.get(User, user_id)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            # 禁止刪除超級管理員
            if user.role == UserRole.SUPER_ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="不可刪除超級管理員"
                )

            # 軟刪除：設定為不活躍
            user.is_active = False
            user.updated_at = datetime.utcnow()

            await session.commit()

            logger.info(f"管理員 {current_user.username} 刪除了使用者 {user.username}")

            return {"message": f"使用者 {user.username} 已被停用"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刪除使用者失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="刪除使用者時發生錯誤"
        )


@router.post("/{user_id}/reset-password", response_model=PasswordResetResponse)
async def reset_user_password(
    user_id: int,
    generate_new: bool = Query(False, description="是否自動生成新密碼"),
    new_password: Optional[str] = Query(None, description="新密碼（如果不自動生成）"),
    current_user: User = Depends(get_current_user)
):
    """
    重設使用者密碼

    需要 ADMIN+ 權限。
    """
    # 權限檢查：需要 ADMIN+ 權限
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )

    if not generate_new and not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供新密碼或選擇自動生成"
        )

    try:
        async with get_async_session() as session:
            user = await session.get(User, user_id)

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="使用者不存在"
                )

            # Admin 不得重設 super_admin 密碼
            if current_user.role == UserRole.ADMIN and user.role == UserRole.SUPER_ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin 不得操作超級管理員"
                )

            # 生成或使用提供的密碼
            password = new_password
            if generate_new or not password:
                password = PasswordService.generate_temp_password()

            # 更新密碼
            user.hashed_password = PasswordService.hash_password(password)
            user.updated_at = datetime.utcnow()

            await session.commit()

            logger.info(f"管理員 {current_user.username} 重設了使用者 {user.username} 的密碼")

            return PasswordResetResponse(
                message=f"使用者 {user.username} 的密碼已重設",
                new_password=password if generate_new else None
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重設密碼失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="重設密碼時發生錯誤"
        )


