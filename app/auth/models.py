"""
認證系統資料模型

定義使用者角色、權限類型、認證請求/回應模型等。
"""

from enum import Enum
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """使用者角色枚舉"""
    VIEWER = "viewer"        # 檢視者：只能檢視
    USER = "user"            # 使用者：可進行 CRUD 操作
    ADMIN = "admin"          # 團隊管理員：可管理團隊設定與成員
    SUPER_ADMIN = "super_admin"  # 超級管理員：系統所有權限


class PermissionType(str, Enum):
    """權限類型枚舉"""
    READ = "read"            # 檢視權限
    WRITE = "write"          # 寫入權限（包含 CREATE/UPDATE/DELETE）
    ADMIN = "admin"          # 管理權限（團隊設定、成員管理）


# ===================== 使用者相關模型 =====================

class UserBase(BaseModel):
    """使用者基礎模型"""
    username: str = Field(..., min_length=3, max_length=50, description="使用者名稱")
    lark_user_id: Optional[str] = Field(None, description="關聯的 Lark 使用者 ID")
    role: UserRole = Field(..., description="使用者角色")
    primary_team_id: Optional[int] = Field(None, description="主要團隊 ID")
    is_active: bool = Field(True, description="帳戶是否啟用")


class UserCreate(UserBase):
    """建立使用者請求模型"""
    password: str = Field(..., min_length=8, description="密碼（最少8字符）")
    created_by: Optional[int] = Field(None, description="建立者使用者 ID")


class UserUpdate(BaseModel):
    """更新使用者請求模型"""
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    lark_user_id: Optional[str] = None
    role: Optional[UserRole] = None
    primary_team_id: Optional[int] = None
    is_active: Optional[bool] = None


class User(UserBase):
    """使用者完整模型（回應用）"""
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    
    class Config:
        from_attributes = True


class UserSummary(BaseModel):
    """使用者摘要模型（列表用）"""
    id: int
    username: str
    role: UserRole
    primary_team_id: Optional[int] = None
    is_active: bool
    created_at: datetime


# ===================== 認證相關模型 =====================

class LoginRequest(BaseModel):
    """登入請求模型"""
    username: str = Field(..., description="使用者名稱")
    password: str = Field(..., description="密碼")
    remember_me: bool = Field(False, description="記住登入")


class LoginResponse(BaseModel):
    """登入回應模型"""
    access_token: str = Field(..., description="JWT 存取 Token")
    token_type: str = Field("bearer", description="Token 類型")
    expires_in: int = Field(..., description="Token 有效期（秒）")
    user: UserSummary = Field(..., description="使用者資訊")


class TokenData(BaseModel):
    """JWT Token 資料模型"""
    user_id: int
    username: str
    role: UserRole
    jti: str  # JWT ID，用於撤銷 Token


class ChangePasswordRequest(BaseModel):
    """修改密碼請求模型"""
    current_password: str = Field(..., description="目前密碼")
    new_password: str = Field(..., min_length=8, description="新密碼（最少8字符）")


class ResetPasswordRequest(BaseModel):
    """重設密碼請求模型（管理員用）"""
    user_id: int = Field(..., description="要重設密碼的使用者 ID")
    new_password: str = Field(..., min_length=8, description="新密碼（最少8字符）")


# ===================== 權限相關模型 =====================

class TeamPermissionBase(BaseModel):
    """團隊權限基礎模型"""
    user_id: int = Field(..., description="使用者 ID")
    team_id: int = Field(..., description="團隊 ID")
    permission_type: PermissionType = Field(..., description="權限類型")


class TeamPermissionCreate(TeamPermissionBase):
    """建立團隊權限請求模型"""
    granted_by: int = Field(..., description="授權者使用者 ID")


class TeamPermissionUpdate(BaseModel):
    """更新團隊權限請求模型"""
    permission_type: PermissionType = Field(..., description="新的權限類型")


class TeamPermission(TeamPermissionBase):
    """團隊權限完整模型"""
    id: int
    granted_by: int
    granted_at: datetime
    is_active: bool = True
    
    class Config:
        from_attributes = True


# ===================== 會話管理模型 =====================

class ActiveSession(BaseModel):
    """活動會話模型"""
    id: int
    user_id: int
    username: str
    token_jti: str
    issued_at: datetime
    expires_at: datetime
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    is_active: bool = True
    
    class Config:
        from_attributes = True


class SessionSummary(BaseModel):
    """會話摘要模型（管理用）"""
    user_id: int
    username: str
    session_count: int
    last_login: datetime
    ip_address: Optional[str] = None


# ===================== 錯誤回應模型 =====================

class AuthErrorResponse(BaseModel):
    """認證錯誤回應模型"""
    code: str = Field(..., description="錯誤代碼")
    message: str = Field(..., description="錯誤訊息")
    detail: Optional[str] = Field(None, description="詳細錯誤資訊")


# ===================== 權限檢查輔助模型 =====================

class PermissionCheck(BaseModel):
    """權限檢查結果模型"""
    has_permission: bool
    user_role: UserRole
    team_permission: Optional[PermissionType] = None
    reason: Optional[str] = None