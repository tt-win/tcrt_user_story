"""
認證相關 API 端點

提供使用者認證、登入、登出、token 刷新等功能
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import logging

from sqlalchemy import select, text

from app.auth.auth_service import auth_service
from app.auth.permission_service import permission_service
from app.auth.dependencies import get_current_user
from app.auth.password_service import PasswordService
from app.database import get_async_session
from app.models.database_models import User
from app.audit import audit_service, ActionType, ResourceType, AuditSeverity

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    """登入請求模型"""
    username_or_email: str
    password: str


class LoginResponse(BaseModel):
    """登入回應模型"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_info: Dict[str, Any]
    first_login: bool = Field(False, description="是否為首次登入")


class PreLoginRequest(BaseModel):
    """登入前檢查請求模型"""
    username_or_email: str


class PreLoginResponse(BaseModel):
    """登入前檢查回應模型"""
    user_exists: bool
    is_active: bool = False
    first_login: bool = False
    username: Optional[str] = None
    full_name: Optional[str] = None
    message: Optional[str] = None


class FirstLoginSetupRequest(BaseModel):
    """首次登入設定密碼請求模型"""
    username: str
    new_password: str
    confirm_password: str


class RefreshRequest(BaseModel):
    """刷新 Token 請求模型"""
    refresh_token: str


class RefreshResponse(BaseModel):
    """刷新 Token 回應模型"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfoResponse(BaseModel):
    """使用者資訊回應模型"""
    user_id: int
    username: str
    email: Optional[str]
    full_name: Optional[str]
    role: str
    is_active: bool
    permissions: Dict[str, Any]
    accessible_teams: list[int]


def get_client_ip(request: Request) -> str:
    """取得客戶端 IP 地址"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """取得使用者代理字串"""
    return request.headers.get("User-Agent", "unknown")


@router.post("/pre-login", response_model=PreLoginResponse)
async def pre_login(request: PreLoginRequest):
    """登入前檢查，確認帳號狀態"""
    identifier = (request.username_or_email or '').strip()

    if not identifier:
        return PreLoginResponse(
            user_exists=False,
            message="請輸入使用者名稱或電子信箱"
        )

    try:
        async with get_async_session() as session:
            query = text(
                """
                SELECT id, username, full_name, is_active,
                       NULLIF(last_login_at, '') AS last_login_at
                FROM users
                WHERE username = :identifier OR email = :identifier
                LIMIT 1
                """
            )
            result = await session.execute(query, {"identifier": identifier})
            row = result.mappings().first()

        if not row:
            return PreLoginResponse(
                user_exists=False,
                message="找不到對應的帳號"
            )

        is_active = bool(row.get('is_active'))
        username = row.get('username')
        full_name = row.get('full_name') or ''
        last_login_value = row.get('last_login_at')
        if isinstance(last_login_value, str):
            last_login_value = last_login_value.strip() or None
        first_login = not last_login_value

        if not is_active:
            return PreLoginResponse(
                user_exists=True,
                is_active=False,
                username=username,
                full_name=full_name,
                message="帳號已被停用，請聯繫系統管理員"
            )

        return PreLoginResponse(
            user_exists=True,
            is_active=True,
            first_login=first_login,
            username=username,
            full_name=full_name
        )

    except Exception as exc:
        logger.error("pre-login 檢查失敗: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="查詢帳號狀態時發生錯誤，請稍後再試"
        )


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, http_request: Request):
    """
    使用者登入

    驗證使用者憑證並建立認證會話，返回 JWT token
    """
    try:
        # 驗證使用者憑證
        user = await auth_service.authenticate_user(
            username_or_email=request.username_or_email,
            password=request.password
        )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="使用者名稱、電子信箱或密碼不正確"
            )

        # 取得客戶端資訊
        ip_address = get_client_ip(http_request)
        user_agent = get_user_agent(http_request)

        # 建立存取 Token
        access_token, jti, expires_at = await auth_service.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            ip_address=ip_address,
            user_agent=user_agent
        )

        # 計算過期時間（秒）
        from datetime import datetime
        expires_in = int((expires_at - datetime.utcnow()).total_seconds())

        logger.info(f"使用者 {user.username} 成功登入")

        try:
            await audit_service.log_action(
                user_id=user.id,
                username=user.username,
                role=user.role.value if hasattr(user.role, 'value') else str(user.role),
                action_type=ActionType.LOGIN,
                resource_type=ResourceType.AUTH,
                resource_id="login",
                team_id=0,
                details={
                    "method": "POST",
                    "path": "/api/auth/login",
                },
                action_brief=f"{user.username} 登入",
                severity=AuditSeverity.INFO,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except Exception as audit_exc:  # noqa: BLE001
            logger.warning("寫入登入審計記錄失敗: %s", audit_exc, exc_info=True)

        first_login_flag = bool(getattr(user, 'was_first_login', False))

        return LoginResponse(
            access_token=access_token,
            expires_in=expires_in,
            user_info={
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active
            },
            first_login=first_login_flag
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登入失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登入過程發生錯誤"
        )


@router.post("/logout")
async def logout(
    http_request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    current_user: User = Depends(get_current_user)
):
    """
    使用者登出

    撤銷目前使用者的存取 Token
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要提供認證 Token"
        )

    try:
        # 驗證並取得 Token 資訊
        token_data = await auth_service.verify_token(credentials.credentials)
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無效的 Token"
            )

        # 撤銷 Token
        success = await auth_service.revoke_token(token_data.jti, "logout")

        if not success:
            logger.warning(f"Token 撤銷失敗: {token_data.jti}")

        logger.info(f"使用者 {current_user.username} 成功登出")

        try:
            ip_address = get_client_ip(http_request)
            user_agent = get_user_agent(http_request)
            await audit_service.log_action(
                user_id=current_user.id,
                username=current_user.username,
                role=current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role),
                action_type=ActionType.LOGOUT,
                resource_type=ResourceType.AUTH,
                resource_id="logout",
                team_id=0,
                details={
                    "method": "POST",
                    "path": "/api/auth/logout",
                },
                action_brief=f"{current_user.username} 登出",
                severity=AuditSeverity.INFO,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        except Exception as audit_exc:  # noqa: BLE001
            logger.warning("寫入登出審計記錄失敗: %s", audit_exc, exc_info=True)

        return {"message": "成功登出"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登出失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登出過程發生錯誤"
        )


@router.post("/first-login/setup", response_model=LoginResponse)
async def first_login_setup(request: FirstLoginSetupRequest, http_request: Request):
    """首次登入時設定新密碼"""
    username = (request.username or '').strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請提供使用者名稱"
        )

    if request.new_password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="兩次輸入的密碼不一致"
        )

    if len(request.new_password or '') < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密碼長度至少需 8 個字元"
        )

    async with get_async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT id, username, email, full_name, role, is_active,
                       NULLIF(last_login_at, '') AS last_login_at
                FROM users
                WHERE username = :username
                LIMIT 1
                """
            ),
            {"username": username}
        )
        row = result.mappings().first()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="帳號不存在"
            )

        if not row.get('is_active'):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="帳號已被停用，請聯繫系統管理員"
            )

        last_login_raw = row.get('last_login_at')
        if isinstance(last_login_raw, str):
            last_login_raw = last_login_raw.strip() or None

        if last_login_raw is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="此帳號已完成初始化，請直接登入"
            )

        hashed_password = PasswordService.hash_password(request.new_password)
        now = datetime.utcnow()

        await session.execute(
            text(
                """
                UPDATE users
                SET hashed_password = :hashed_password,
                    last_login_at = :last_login_at,
                    updated_at = :updated_at,
                    is_verified = 1
                WHERE id = :user_id
                """
            ),
            {
                "hashed_password": hashed_password,
                "last_login_at": now.isoformat(sep=' '),
                "updated_at": now.isoformat(sep=' '),
                "user_id": row['id']
            }
        )
        await session.commit()

        result = await session.execute(
            select(User).where(User.id == row['id'])
        )
        user = result.scalar_one()

    # 建立 Token 供後續使用
    ip_address = get_client_ip(http_request)
    user_agent = get_user_agent(http_request)

    access_token, jti, expires_at = await auth_service.create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        ip_address=ip_address,
        user_agent=user_agent
    )

    expires_in = int((expires_at - datetime.utcnow()).total_seconds())

    logger.info(f"使用者 {user.username} 完成首次登入設定")

    try:
        await audit_service.log_action(
            user_id=user.id,
            username=user.username,
            role=user.role.value if hasattr(user.role, 'value') else str(user.role),
            action_type=ActionType.LOGIN,
            resource_type=ResourceType.AUTH,
            resource_id="first-login",
            team_id=0,
            details={
                "method": "POST",
                "path": "/api/auth/first-login/setup",
            },
            action_brief=f"{user.username} 完成首次登入設定",
            severity=AuditSeverity.INFO,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as audit_exc:  # noqa: BLE001
        logger.warning("寫入首次登入審計記錄失敗: %s", audit_exc, exc_info=True)

    return LoginResponse(
        access_token=access_token,
        expires_in=expires_in,
        user_info={
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "is_active": user.is_active
        },
        first_login=False
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(request: RefreshRequest, http_request: Request):
    """
    刷新 Access Token

    使用舊的 access token 取得新的 access token
    """
    try:
        # 取得客戶端資訊
        ip_address = get_client_ip(http_request)
        user_agent = get_user_agent(http_request)

        # 刷新 Token
        refresh_result = await auth_service.refresh_token(
            old_token=request.refresh_token,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if not refresh_result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="無效的 refresh token"
            )

        new_token, new_jti, expires_at = refresh_result

        # 計算過期時間（秒）
        from datetime import datetime
        expires_in = int((expires_at - datetime.utcnow()).total_seconds())

        logger.info(f"Token 刷新成功: {new_jti}")

        return RefreshResponse(
            access_token=new_token,
            expires_in=expires_in
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新 token 失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的 refresh token"
        )
        logger.error(f"刷新 token 失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的 refresh token"
        )


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    取得目前使用者資訊

    返回使用者基本資訊、角色權限和可存取的團隊列表
    """
    try:
        # 取得使用者權限摘要
        permissions = await permission_service.get_permission_summary(current_user.id)

        # 取得可存取的團隊列表
        accessible_teams = await permission_service.get_user_accessible_teams(current_user.id)

        return UserInfoResponse(
            user_id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            full_name=current_user.full_name,
            role=current_user.role.value,
            is_active=current_user.is_active,
            permissions=permissions,
            accessible_teams=accessible_teams
        )

    except Exception as e:
        logger.error(f"取得使用者資訊失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="取得使用者資訊時發生錯誤"
        )


@router.post("/validate-token")
async def validate_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    驗證 Token 有效性

    檢查提供的 JWT token 是否有效
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要提供認證 Token"
        )

    try:
        # 驗證 Token
        token_data = await auth_service.verify_token(credentials.credentials)

        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 已失效或無效"
            )

        return {
            "valid": True,
            "user_id": token_data.user_id,
            "username": token_data.username,
            "role": token_data.role.value,
            "jti": token_data.jti
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"驗證 token 失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的 token"
        )
