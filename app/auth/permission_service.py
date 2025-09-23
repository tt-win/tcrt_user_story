"""
權限檢查服務

提供 RBAC 權限檢查、團隊權限管理、權限快取等功能。
"""

from functools import lru_cache
from typing import Optional, List, Set
from app.auth.models import UserRole, PermissionType, PermissionCheck


class PermissionService:
    """權限檢查服務"""
    
    # 權限階層定義（數字越大權限越高）
    ROLE_HIERARCHY = {
        UserRole.VIEWER: 1,
        UserRole.USER: 2, 
        UserRole.ADMIN: 3,
        UserRole.SUPER_ADMIN: 4
    }
    
    @classmethod
    def check_user_role(cls, user_role: UserRole, required_role: UserRole) -> bool:
        """
        檢查使用者角色是否滿足要求（落實預設拒絕）
        
        Args:
            user_role: 使用者當前角色
            required_role: 要求的最低角色
            
        Returns:
            是否有足夠權限
        """
        return cls.ROLE_HIERARCHY.get(user_role, 0) >= cls.ROLE_HIERARCHY.get(required_role, 0)
    
    @classmethod
    def check_team_permission(
        cls, 
        user_id: int, 
        team_id: int, 
        required_permission: PermissionType,
        user_role: UserRole
    ) -> PermissionCheck:
        """
        檢查團隊權限（資源所屬團隊權限優先）
        
        Args:
            user_id: 使用者 ID
            team_id: 團隊 ID
            required_permission: 要求的權限類型
            user_role: 使用者角色
            
        Returns:
            權限檢查結果
        """
        # TODO: 實作團隊權限檢查邏輯
        # 1. 檢查使用者在該團隊的精確授權
        # 2. 若無精確授權，回退到使用者的主團隊角色
        # 3. Super Admin 總是有權限
        
        if user_role == UserRole.SUPER_ADMIN:
            return PermissionCheck(
                has_permission=True,
                user_role=user_role,
                reason="Super Admin 有全系統權限"
            )
        
        # 暫時實作：基於角色的簡單檢查
        if required_permission == PermissionType.READ:
            has_perm = user_role in [UserRole.VIEWER, UserRole.USER, UserRole.ADMIN]
        elif required_permission == PermissionType.WRITE:
            has_perm = user_role in [UserRole.USER, UserRole.ADMIN]
        elif required_permission == PermissionType.ADMIN:
            has_perm = user_role == UserRole.ADMIN
        else:
            has_perm = False
        
        return PermissionCheck(
            has_permission=has_perm,
            user_role=user_role,
            reason="基於角色的權限檢查" if has_perm else "權限不足"
        )
    
    @classmethod
    @lru_cache(maxsize=256)  # TTL 5 分鐘的快取（簡化版）
    def get_user_accessible_teams(cls, user_id: int) -> Set[int]:
        """
        取得使用者可存取的團隊 ID 列表
        
        Args:
            user_id: 使用者 ID
            
        Returns:
            可存取的團隊 ID 集合
        """
        # TODO: 實作從資料庫查詢使用者可存取的團隊
        # 1. 使用者的主要團隊
        # 2. 被授權的跨團隊權限
        return set()
    
    @classmethod
    def has_resource_permission(
        cls,
        user_id: int,
        user_role: UserRole,
        resource_type: str,
        resource_id: str,
        action: str
    ) -> bool:
        """
        檢查對特定資源的權限
        
        Args:
            user_id: 使用者 ID
            user_role: 使用者角色
            resource_type: 資源類型 (test_case, test_run, team_setting)
            resource_id: 資源 ID
            action: 操作類型 (read, write, delete)
            
        Returns:
            是否有權限
        """
        # TODO: 實作資源層級的權限檢查
        # 1. 根據 resource_type 和 resource_id 取得資源所屬團隊
        # 2. 檢查使用者對該團隊的權限
        # 3. 根據 action 判斷需要的權限類型
        
        if user_role == UserRole.SUPER_ADMIN:
            return True
            
        # 暫時實作
        return False
    
    @classmethod
    def clear_cache(cls, user_id: Optional[int] = None, team_id: Optional[int] = None):
        """
        清除權限快取（授權變更時調用）
        
        Args:
            user_id: 特定使用者 ID（可選）
            team_id: 特定團隊 ID（可選）
        """
        # 清除 LRU 快取
        cls.get_user_accessible_teams.cache_clear()
        # TODO: 實作更精細的快取清除邏輯