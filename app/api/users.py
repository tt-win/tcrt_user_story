"""
使用者管理 API 端點

提供使用者的 CRUD 操作，需要適當的管理員權限
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Union, Any
from pydantic.main import BaseModel as PydanticBaseModel
from pydantic_core import PydanticUndefined
import logging
from datetime import datetime

from app.auth.dependencies import get_current_user
from app.auth.models import UserRole, UserCreate
from app.auth.password_service import PasswordService
from app.services.user_service import UserService
from app.models.database_models import User, LarkUser
from app.database import get_async_session
from sqlalchemy import select, and_, or_, func
import logging

from app.utils.logging import log_lark_display_decision
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


async def log_user_action(
    action_type: ActionType,
    current_user: User,
    target_user: User,
    action_brief: str,
    details: Optional[dict] = None,
) -> None:
    try:
        role_value = (
            current_user.role.value
            if hasattr(current_user.role, "value")
            else str(current_user.role)
        )
        await audit_service.log_action(
            user_id=current_user.id,
            username=current_user.username,
            role=role_value,
            action_type=action_type,
            resource_type=ResourceType.USER,
            resource_id=str(target_user.id),
            team_id=0,
            details=details,
            action_brief=action_brief,
            severity=AuditSeverity.CRITICAL if action_type == ActionType.DELETE else AuditSeverity.INFO,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("寫入使用者審計記錄失敗: %s", exc, exc_info=True)


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


class UserUpdateRequest(PydanticBaseModel):
    """更新使用者請求模型"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None  # 密碼重設
    lark_user_id: Optional[str] = None

    def field_is_set(self, field_name: str) -> bool:
        """檢查字段是否在請求中被明確設置（通過 model_fields_set）"""
        return field_name in self.model_fields_set


class UserResponse(BaseModel):
    """使用者回應模型"""
    id: int
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: str
    is_active: bool
    lark_user_id: Optional[str] = None
    avatar_url: Optional[str] = None
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
    avatar_url: Optional[str] = None
    lark_name: Optional[str] = None
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
    current_password: str = Field(..., description="目前密碼（可能已加密）")
    new_password: str = Field(..., description="新密碼（可能已加密）")
    encrypted: bool = Field(default=False, description="密碼是否已加密")

    @validator('new_password')
    def validate_new_password(cls, v, values):
        # 如果密碼已加密，跳過長度檢查（解密後再檢查）
        if values.get('encrypted', False):
            return v
        # 明文密碼需要檢查長度
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
            query = select(User, LarkUser.avatar_240).outerjoin(
                LarkUser, User.lark_user_id == LarkUser.user_id
            )

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
            # result now contains (User, avatar_url) tuples
            rows = result.all()

            user_responses = [
                UserResponse(
                    id=user.id,
                    username=user.username,
                    email=user.email,
                    full_name=user.full_name,
                    role=user.role.value,
                    is_active=user.is_active,
                    lark_user_id=getattr(user, 'lark_user_id', None),
                    avatar_url=avatar_url,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                    last_login_at=user.last_login_at
                )
                for user, avatar_url in rows
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

    權限要求：
    - ADMIN 可以創建 USER 和 VIEWER
    - SUPER_ADMIN 可以創建任何角色（除了第二個 SUPER_ADMIN）
    """
    # 權限檢查：至少需要 ADMIN 權限
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
        )

    try:
        # ADMIN 只能創建 USER 和 VIEWER
        if current_user.role == UserRole.ADMIN:
            if request.role not in [UserRole.USER, UserRole.VIEWER]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="管理員只能創建 USER 和 VIEWER 角色"
                )

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

        # 嘗試獲取 Lark 頭像
        avatar_url = None
        if new_user.lark_user_id:
            try:
                async with get_async_session() as session:
                    lark_user = await session.get(LarkUser, new_user.lark_user_id)
                    if lark_user:
                        avatar_url = lark_user.avatar_240
            except Exception as e:
                logger.warning(f"獲取 Lark 頭像失敗: {e}")

        logger.info(f"管理員 {current_user.username} 建立了新使用者 {new_user.username}")

        action_brief = f"{current_user.username} created user {new_user.username}"
        await log_user_action(
            action_type=ActionType.CREATE,
            current_user=current_user,
            target_user=new_user,
            action_brief=action_brief,
            details={
                "user_id": new_user.id,
                "role": new_user.role.value,
                "email": new_user.email,
            },
        )

        return UserResponse(
            id=new_user.id,
            username=new_user.username,
            email=new_user.email,
            full_name=new_user.full_name,
            role=new_user.role.value,
            is_active=new_user.is_active,
            lark_user_id=getattr(new_user, 'lark_user_id', None),
            avatar_url=avatar_url,
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
        
        role_value = str(current_user.role.value) if isinstance(current_user.role, UserRole) else str(current_user.role)

        # 嘗試獲取 Lark 頭像
        avatar_url = None
        lark_name = None
        if current_user.lark_user_id:
            try:
                async with get_async_session() as session:
                    lark_user = await session.get(LarkUser, current_user.lark_user_id)
                    if lark_user:
                        avatar_url = lark_user.avatar_240
                        lark_name = lark_user.name
            except Exception as e:
                logger.warning(f"獲取 Lark 資訊失敗: {e}")

        return UserSelfOut(
            id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            full_name=current_user.full_name,
            role=role_value.lower(),
            is_active=current_user.is_active,
            created_at=current_user.created_at,
            updated_at=current_user.updated_at,
            last_login_at=current_user.last_login_at,
            avatar_url=avatar_url,
            lark_name=lark_name,
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

            # 嘗試獲取 Lark 頭像
            avatar_url = None
            lark_name = None
            if user.lark_user_id:
                lark_user = await session.get(LarkUser, user.lark_user_id)
                if lark_user:
                    avatar_url = lark_user.avatar_240
                    lark_name = lark_user.name

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
                avatar_url=avatar_url,
                lark_name=lark_name,
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
    支援加密和明文兩種模式。
    """
    try:
        # 如果密碼已加密，先解密
        current_password = request.current_password
        new_password = request.new_password

        if request.encrypted:
            from app.auth.password_encryption import password_encryption_service
            try:
                current_password = password_encryption_service.decrypt_password(request.current_password)
                new_password = password_encryption_service.decrypt_password(request.new_password)
            except Exception as e:
                logger.error(f"密碼解密失敗: {e}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="密碼解密失敗，請重試"
                )

        # 解密後檢查新密碼長度
        if len(new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="新密碼長度至少需要8個字符"
            )

        # 驗證目前密碼
        if not PasswordService.verify_password(current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="目前密碼不正確"
            )

        # 檢查新密碼是否與舊密碼相同
        if PasswordService.verify_password(new_password, current_user.hashed_password):
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

            # 更新密碼（使用解密後的明文密碼）
            user.hashed_password = PasswordService.hash_password(new_password)
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

            # 嘗試獲取 Lark 頭像
            avatar_url = None
            if user.lark_user_id:
                lark_user = await session.get(LarkUser, user.lark_user_id)
                if lark_user:
                    avatar_url = lark_user.avatar_240

            return UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                lark_user_id=getattr(user, 'lark_user_id', None),
                avatar_url=avatar_url,
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

            # 更新欄位 - 只有當字段被設置時才更新
            # 對於可為 null 的字段，當設置為 null 時也應更新
            # 對於必需字段，只有當明確提供非 null 值時才更新
            changed_fields: List[str] = []
            if request.field_is_set('email'):
                user.email = request.email
                changed_fields.append("email")
            if request.field_is_set('full_name'):
                user.full_name = request.full_name
                changed_fields.append("full_name")
            if request.field_is_set('role') and request.role is not None:
                user.role = request.role
                changed_fields.append("role")
            if request.field_is_set('is_active') and request.is_active is not None:
                user.is_active = request.is_active
                changed_fields.append("is_active")
            if request.field_is_set('password') and request.password is not None:
                user.hashed_password = PasswordService.hash_password(request.password)
                changed_fields.append("password")
            if request.field_is_set('lark_user_id'):
                # lark_user_id 可以為 null，所以總是更新（即使值為 None）
                user.lark_user_id = request.lark_user_id
                changed_fields.append("lark_user_id")

            user.updated_at = datetime.utcnow()

            await session.commit()
            await session.refresh(user)

            logger.info(f"管理員 {current_user.username} 更新了使用者 {user.username}")

            if changed_fields:
                action_brief = f"{current_user.username} updated user {user.username}"
                await log_user_action(
                    action_type=ActionType.UPDATE,
                    current_user=current_user,
                    target_user=user,
                    action_brief=action_brief,
                    details={
                        "user_id": user.id,
                        "changed_fields": changed_fields,
                        "role": user.role.value,
                    },
                )

            # 嘗試獲取 Lark 頭像
            avatar_url = None
            if user.lark_user_id:
                lark_user = await session.get(LarkUser, user.lark_user_id)
                if lark_user:
                    avatar_url = lark_user.avatar_240

            return UserResponse(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                lark_user_id=getattr(user, 'lark_user_id', None),
                avatar_url=avatar_url,
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
    刪除使用者 (永久刪除)

    權限要求：
    - ADMIN 可以刪除 USER 和 VIEWER
    - SUPER_ADMIN 可以刪除任何角色（除了 SUPER_ADMIN）
    """
    # 權限檢查：至少需要 ADMIN 權限
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPER_ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理員權限"
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

            # ADMIN 只能刪除 USER 和 VIEWER
            if current_user.role == UserRole.ADMIN:
                if user.role not in [UserRole.USER, UserRole.VIEWER]:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="管理員只能刪除 USER 和 VIEWER 角色"
                    )

            deleted_username = user.username

            # 永久刪除使用者資料
            await session.delete(user)
            await session.commit()

            logger.info(f"管理員 {current_user.username} 永久刪除了使用者 {deleted_username}")

            action_brief = f"{current_user.username} deleted user {deleted_username}"
            await log_user_action(
                action_type=ActionType.DELETE,
                current_user=current_user,
                target_user=user,
                action_brief=action_brief,
                details={
                    "user_id": user.id,
                    "username": deleted_username,
                    "role": user.role.value,
                },
            )

            return {"message": f"使用者 {deleted_username} 已被刪除"}

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

            # 更新密碼並清空 last_login_at，強制使用者首次登入時設定新密碼
            user.hashed_password = PasswordService.hash_password(password)
            user.last_login_at = None  # 清空以觸發首次登入流程
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


@router.get("/{user_id}/lark-status", response_model=dict)
async def get_user_lark_status(
    user_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    取得使用者的 Lark 整合狀態
    
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
        # 使用 UserService 檢查 Lark 整合狀態
        status = await UserService.check_lark_integration_status(user_id)
        
        # 記錄顯示決策
        log_lark_display_decision(
            user_id, 
            status.get("lark_linked", False), 
            status.get("has_lark_data", False),
            "顯示" if status.get("has_lark_data", False) else "隱藏"
        )
        
        return status

    except Exception as e:
        logger.error(f"取得使用者 Lark 狀態失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得使用者 Lark 狀態時發生錯誤"
        )
