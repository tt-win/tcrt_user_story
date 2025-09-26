"""
FastAPI 認證依賴注入

提供 JWT Token 驗證、權限檢查等依賴注入功能。
"""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Callable
from app.auth.models import UserRole, PermissionType, AuthErrorResponse
from app.auth.auth_service import auth_service
from app.auth.permission_service import permission_service
from app.models.database_models import User
from app.database import get_async_session
from sqlalchemy import select


# HTTP Bearer Token 安全方案
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> User:
    """
    取得目前登入使用者（驗證 Bearer Token、檢查 jti 未撤銷）

    Args:
        credentials: HTTP Bearer Token

    Returns:
        目前使用者資訊

    Raises:
        HTTPException: 401 如果 Token 無效或過期
    """
    token = credentials.credentials
    token_data = await auth_service.verify_token(token)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "無效或過期的存取 Token"},
        )

    # 從資料庫取得完整使用者資訊
    async with get_async_session() as session:
        result = await session.execute(
            select(User).where(User.id == token_data.user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "USER_NOT_FOUND_OR_INACTIVE",
                    "message": "使用者不存在或已停用",
                },
            )

        return user


class AuthDependencies:
    """認證相關依賴注入"""

    @staticmethod
    async def get_current_user_wrapper(
        credentials: HTTPAuthorizationCredentials = Security(security),
    ) -> User:
        return await get_current_user(credentials)

    def require_role(self, required_role: UserRole) -> Callable:
        """
        檢查使用者角色權限的依賴工廠

        Args:
            required_role: 要求的最低角色

        Returns:
            依賴注入函數
        """

        async def dependency(current_user: User = Depends(get_current_user)) -> User:
            ok = await permission_service.check_user_role(current_user.id, required_role)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=AuthErrorResponse(
                        code="INSUFFICIENT_ROLE",
                        message="權限不足",
                        detail=f"需要 {required_role.value} 或更高權限",
                    ).dict(),
                )
            return current_user

        return dependency

    def require_team_permission(
        self, team_id: int, required_permission: PermissionType
    ) -> Callable:
        """
        檢查團隊權限的依賴工廠

        Args:
            team_id: 團隊 ID
            required_permission: 要求的權限類型

        Returns:
            依賴注入函數
        """

        async def dependency(current_user: User = Depends(get_current_user)) -> User:
            ok = await permission_service.check_team_permission(
                current_user.id, team_id, required_permission
            )

            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=AuthErrorResponse(
                        code="INSUFFICIENT_PERMISSION",
                        message="無權限存取此團隊",
                        detail="使用者在該團隊的權限不足",
                    ).dict(),
                )
            return current_user

        return dependency

    def require_admin(self) -> Callable:
        """
        要求 Admin 或更高權限的快捷依賴

        Returns:
            依賴注入函數
        """
        return self.require_role(UserRole.ADMIN)

    def require_super_admin(self) -> Callable:
        """
        要求 Super Admin 權限的快捷依賴

        Returns:
            依賴注入函數
        """
        return self.require_role(UserRole.SUPER_ADMIN)


# 快捷依賴注入函數
def require_role(required_role: UserRole) -> Callable:
    """檢查使用者角色權限的依賴工廠"""

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        ok = await permission_service.check_user_role(current_user.id, required_role)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_ROLE",
                    "message": "權限不足",
                    "detail": f"需要 {required_role.value} 或更高權限",
                },
            )
        return current_user

    return dependency


def require_team_permission(
    team_id: int, required_permission: PermissionType
) -> Callable:
    """檢查團隊權限的依賴工廠"""

    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        ok = await permission_service.check_team_permission(
            current_user.id, team_id, required_permission
        )

        if not ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_PERMISSION",
                    "message": "無權限存取此團隊",
                    "detail": "使用者在該團隊的權限不足",
                },
            )
        return current_user

    return dependency


def require_admin() -> Callable:
    """要求 Admin 或更高權限的快捷依賴"""
    return require_role(UserRole.ADMIN)


def require_super_admin() -> Callable:
    """要求 Super Admin 權限的快捷依賴"""
    return require_role(UserRole.SUPER_ADMIN)
