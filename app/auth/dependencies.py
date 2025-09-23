"""
FastAPI 認證依賴注入

提供 JWT Token 驗證、權限檢查等依賴注入功能。
"""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Callable
from app.auth.models import User, UserRole, PermissionType, AuthErrorResponse
from app.auth.auth_service import AuthService
from app.auth.permission_service import PermissionService


# HTTP Bearer Token 安全方案
security = HTTPBearer()


class AuthDependencies:
    """認證相關依賴注入"""
    
    def __init__(self):
        self.auth_service = AuthService()
    
    async def get_current_user(
        self, 
        credentials: HTTPAuthorizationCredentials = Security(security)
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
        token_data = self.auth_service.verify_token(token)
        
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=AuthErrorResponse(
                    code="INVALID_TOKEN",
                    message="無效或過期的存取 Token"
                ).dict()
            )
        
        # TODO: 檢查 JTI 是否已被撤銷
        # TODO: 從資料庫取得完整使用者資訊
        
        # 暫時返回基於 Token 的使用者資訊
        return User(
            id=token_data.user_id,
            username=token_data.username,
            role=token_data.role,
            lark_user_id=None,
            primary_team_id=None,
            is_active=True,
            created_at="2024-01-01T00:00:00",  # 暫時值
            updated_at="2024-01-01T00:00:00"   # 暫時值
        )
    
    def require_role(self, required_role: UserRole) -> Callable:
        """
        檢查使用者角色權限的依賴工廠
        
        Args:
            required_role: 要求的最低角色
            
        Returns:
            依賴注入函數
        """
        def dependency(current_user: User = Depends(self.get_current_user)) -> User:
            if not PermissionService.check_user_role(current_user.role, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=AuthErrorResponse(
                        code="INSUFFICIENT_ROLE",
                        message="權限不足",
                        detail=f"需要 {required_role.value} 或更高權限"
                    ).dict()
                )
            return current_user
        return dependency
    
    def require_team_permission(
        self, 
        team_id: int, 
        required_permission: PermissionType
    ) -> Callable:
        """
        檢查團隊權限的依賴工廠
        
        Args:
            team_id: 團隊 ID
            required_permission: 要求的權限類型
            
        Returns:
            依賴注入函數
        """
        def dependency(current_user: User = Depends(self.get_current_user)) -> User:
            permission_check = PermissionService.check_team_permission(
                current_user.id,
                team_id,
                required_permission,
                current_user.role
            )
            
            if not permission_check.has_permission:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=AuthErrorResponse(
                        code="INSUFFICIENT_PERMISSION",
                        message="無權限存取此團隊",
                        detail=permission_check.reason
                    ).dict()
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


# 全域實例
auth_deps = AuthDependencies()

# 快捷依賴注入函數
get_current_user = auth_deps.get_current_user
require_role = auth_deps.require_role
require_team_permission = auth_deps.require_team_permission
require_admin = auth_deps.require_admin
require_super_admin = auth_deps.require_super_admin