"""
認證相關 API 端點

提供使用者認證、登入、登出、token 刷新等功能
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from app.auth.auth_service import auth_service
from app.auth.permission_service import permission_service
from app.auth.dependencies import get_current_user
from app.models.database_models import User

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
            }
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

        return {"message": "成功登出"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登出失敗: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登出過程發生錯誤"
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
