"""
權限檢查服務

實作角色檢查、團隊權限檢查、權限快取機制。
遵循「預設拒絕」原則和「資源所屬團隊權限優先」原則。
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from functools import lru_cache
from sqlalchemy import select, and_

from app.database import get_async_session
from app.models.database_models import User, UserTeamPermission, Team
from app.auth.models import UserRole, PermissionType
from app.config import get_settings

logger = logging.getLogger(__name__)


class PermissionCache:
    """權限快取管理器"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5 分鐘 TTL
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[any, datetime]] = {}
        self._lock = asyncio.Lock()
    
    def _make_key(self, user_id: int, team_id: Optional[int] = None, resource_type: Optional[str] = None) -> str:
        """生成快取鍵"""
        if team_id is not None and resource_type is not None:
            return f"perm:{user_id}:{team_id}:{resource_type}"
        elif team_id is not None:
            return f"team:{user_id}:{team_id}"
        else:
            return f"role:{user_id}"
    
    async def get(self, user_id: int, team_id: Optional[int] = None, resource_type: Optional[str] = None) -> Optional[any]:
        """從快取取得權限資訊"""
        key = self._make_key(user_id, team_id, resource_type)
        
        async with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if datetime.utcnow() - timestamp < timedelta(seconds=self.ttl_seconds):
                    logger.debug(f"權限快取命中: {key}")
                    return value
                else:
                    # 過期，移除快取
                    del self._cache[key]
                    logger.debug(f"權限快取過期: {key}")
        
        return None
    
    async def set(self, user_id: int, value: any, team_id: Optional[int] = None, resource_type: Optional[str] = None):
        """設定快取值"""
        key = self._make_key(user_id, team_id, resource_type)
        
        async with self._lock:
            self._cache[key] = (value, datetime.utcnow())
            logger.debug(f"權限快取設定: {key}")
    
    async def clear(self, user_id: int, team_id: Optional[int] = None):
        """清除指定使用者或團隊的快取"""
        async with self._lock:
            keys_to_remove = []
            
            if team_id is not None:
                # 清除特定團隊的快取
                prefix = f"perm:{user_id}:{team_id}:"
                for key in self._cache:
                    if key.startswith(prefix):
                        keys_to_remove.append(key)
                # 也清除團隊權限快取
                team_key = f"team:{user_id}:{team_id}"
                if team_key in self._cache:
                    keys_to_remove.append(team_key)
            else:
                # 清除該使用者所有快取
                user_prefix = f":{user_id}:"
                for key in self._cache:
                    if user_prefix in key or key.startswith(f"role:{user_id}"):
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._cache[key]
                logger.debug(f"清除權限快取: {key}")
    
    async def clear_all(self):
        """清除所有快取"""
        async with self._lock:
            self._cache.clear()
            logger.debug("清除所有權限快取")


class PermissionService:
    """權限檢查服務"""
    
    def __init__(self):
        self.settings = get_settings()
        self.cache = PermissionCache(ttl_seconds=300)  # 5 分鐘快取
    
    async def check_user_role(self, user_id: int, required_role: UserRole) -> bool:
        """
        檢查使用者角色
        
        Args:
            user_id: 使用者 ID
            required_role: 所需角色
            
        Returns:
            是否具備所需角色
        """
        # 嘗試從快取取得
        cached_role = await self.cache.get(user_id)
        if cached_role is not None:
            return self._compare_roles(cached_role, required_role)
        
        # 從資料庫查詢
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(User.role).where(User.id == user_id, User.is_active == True)
                )
                user_role_str = result.scalar_one_or_none()
                
                if not user_role_str:
                    logger.warning(f"找不到活躍使用者: user_id={user_id}")
                    return False
                
                user_role = UserRole(user_role_str)
                
                # 快取結果
                await self.cache.set(user_id, user_role)
                
                return self._compare_roles(user_role, required_role)
                
        except Exception as e:
            logger.error(f"檢查使用者角色失敗: user_id={user_id}, error={e}")
            return False
    
    def _compare_roles(self, user_role: UserRole, required_role: UserRole) -> bool:
        """
        比較角色權限級別
        
        角色權限層級（由高到低）：
        SUPER_ADMIN > ADMIN > MANAGER > USER
        """
        role_hierarchy = {
            UserRole.SUPER_ADMIN: 4,
            UserRole.ADMIN: 3,
            UserRole.USER: 2,
            UserRole.VIEWER: 1
        }
        
        user_level = role_hierarchy.get(user_role, 0)
        required_level = role_hierarchy.get(required_role, 0)
        
        return user_level >= required_level
    
    async def check_team_permission(self, user_id: int, team_id: int, required_permission: PermissionType) -> bool:
        """
        檢查團隊權限
        
        Args:
            user_id: 使用者 ID
            team_id: 團隊 ID
            required_permission: 所需權限類型
            
        Returns:
            是否具備所需權限
        """
        # 嘗試從快取取得
        cached_permission = await self.cache.get(user_id, team_id)
        if cached_permission is not None:
            return self._compare_permissions(cached_permission, required_permission)
        
        # 從資料庫查詢
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(UserTeamPermission.permission).where(
                        and_(
                            UserTeamPermission.user_id == user_id,
                            UserTeamPermission.team_id == team_id
                        )
                    )
                )
                permission_str = result.scalar_one_or_none()
                
                if not permission_str:
                    logger.debug(f"使用者無團隊權限: user_id={user_id}, team_id={team_id}")
                    return False
                
                permission = PermissionType(permission_str)
                
                # 快取結果
                await self.cache.set(user_id, permission, team_id)
                
                return self._compare_permissions(permission, required_permission)
                
        except Exception as e:
            logger.error(f"檢查團隊權限失敗: user_id={user_id}, team_id={team_id}, error={e}")
            return False
    
    def _compare_permissions(self, user_permission: PermissionType, required_permission: PermissionType) -> bool:
        """
        比較權限類型
        
        權限層級（由高到低）：
        ADMIN > WRITE > READ
        """
        permission_hierarchy = {
            PermissionType.ADMIN: 3,
            PermissionType.WRITE: 2,
            PermissionType.READ: 1
        }
        
        user_level = permission_hierarchy.get(user_permission, 0)
        required_level = permission_hierarchy.get(required_permission, 0)
        
        return user_level >= required_level
    
    async def get_user_accessible_teams(self, user_id: int) -> List[int]:
        """
        取得使用者可存取的團隊列表
        
        Args:
            user_id: 使用者 ID
            
        Returns:
            團隊 ID 列表
        """
        try:
            # 首先檢查使用者角色
            user_role = await self._get_user_role(user_id)
            if not user_role:
                return []
            
            async with get_async_session() as session:
                # Super Admin 可以存取所有團隊
                if user_role == UserRole.SUPER_ADMIN:
                    result = await session.execute(select(Team.id))
                    return [team_id for team_id, in result.fetchall()]
                
                # 其他角色只能存取有權限的團隊
                result = await session.execute(
                    select(UserTeamPermission.team_id).where(
                        UserTeamPermission.user_id == user_id
                    )
                )
                return [team_id for team_id, in result.fetchall()]
                
        except Exception as e:
            logger.error(f"取得使用者可存取團隊失敗: user_id={user_id}, error={e}")
            return []
    
    async def has_resource_permission(self, user_id: int, team_id: int, resource_type: str, required_permission: PermissionType) -> bool:
        """
        檢查資源權限（整合角色檢查和團隊權限檢查）
        
        Args:
            user_id: 使用者 ID
            team_id: 資源所屬團隊 ID
            resource_type: 資源類型
            required_permission: 所需權限
            
        Returns:
            是否具備所需權限
        """
        # 檢查快取
        cached_result = await self.cache.get(user_id, team_id, resource_type)
        if cached_result is not None:
            return self._compare_permissions(cached_result, required_permission)
        
        try:
            # 1. 檢查使用者角色
            user_role = await self._get_user_role(user_id)
            if not user_role:
                logger.warning(f"找不到使用者角色: user_id={user_id}")
                return False
            
            # 2. Super Admin 可以存取所有資源
            if user_role == UserRole.SUPER_ADMIN:
                # 快取結果（Super Admin 視為最高權限）
                await self.cache.set(user_id, PermissionType.ADMIN, team_id, resource_type)
                return True
            
            # 3. 檢查團隊權限
            team_permission_result = await self.check_team_permission(user_id, team_id, required_permission)
            
            # 快取結果
            if team_permission_result:
                # 取得實際權限並快取
                user_permission = await self._get_user_team_permission(user_id, team_id)
                if user_permission:
                    await self.cache.set(user_id, user_permission, team_id, resource_type)
            
            return team_permission_result
            
        except Exception as e:
            logger.error(f"檢查資源權限失敗: user_id={user_id}, team_id={team_id}, resource_type={resource_type}, error={e}")
            return False
    
    async def _get_user_role(self, user_id: int) -> Optional[UserRole]:
        """取得使用者角色"""
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(User.role).where(User.id == user_id, User.is_active == True)
                )
                role_str = result.scalar_one_or_none()
                return UserRole(role_str) if role_str else None
        except Exception as e:
            logger.error(f"取得使用者角色失敗: user_id={user_id}, error={e}")
            return None
    
    async def _get_user_team_permission(self, user_id: int, team_id: int) -> Optional[PermissionType]:
        """取得使用者在團隊的權限"""
        try:
            async with get_async_session() as session:
                result = await session.execute(
                    select(UserTeamPermission.permission).where(
                        and_(
                            UserTeamPermission.user_id == user_id,
                            UserTeamPermission.team_id == team_id
                        )
                    )
                )
                permission_str = result.scalar_one_or_none()
                return PermissionType(permission_str) if permission_str else None
        except Exception as e:
            logger.error(f"取得使用者團隊權限失敗: user_id={user_id}, team_id={team_id}, error={e}")
            return None
    
    async def clear_cache(self, user_id: int, team_id: Optional[int] = None):
        """
        清除權限快取
        
        Args:
            user_id: 使用者 ID
            team_id: 團隊 ID（可選，為 None 時清除該使用者所有快取）
        """
        await self.cache.clear(user_id, team_id)
        logger.info(f"已清除權限快取: user_id={user_id}, team_id={team_id}")
    
    async def get_permission_summary(self, user_id: int) -> Dict:
        """
        取得使用者權限摘要
        
        Args:
            user_id: 使用者 ID
            
        Returns:
            權限摘要字典
        """
        try:
            user_role = await self._get_user_role(user_id)
            if not user_role:
                return {}
            
            accessible_teams = await self.get_user_accessible_teams(user_id)
            
            # 取得詳細團隊權限
            team_permissions = {}
            for team_id in accessible_teams:
                permission = await self._get_user_team_permission(user_id, team_id)
                if permission:
                    team_permissions[team_id] = permission.value
            
            return {
                "user_id": user_id,
                "role": user_role.value,
                "accessible_teams": accessible_teams,
                "team_permissions": team_permissions,
                "is_super_admin": user_role == UserRole.SUPER_ADMIN,
                "is_admin": user_role in [UserRole.SUPER_ADMIN, UserRole.ADMIN]
            }
            
        except Exception as e:
            logger.error(f"取得權限摘要失敗: user_id={user_id}, error={e}")
            return {}


# 全域權限服務實例
permission_service = PermissionService()


# 便利函數
async def check_user_role(user_id: int, required_role: UserRole) -> bool:
    """檢查使用者角色"""
    return await permission_service.check_user_role(user_id, required_role)


async def check_team_permission(user_id: int, team_id: int, required_permission: PermissionType) -> bool:
    """檢查團隊權限"""
    return await permission_service.check_team_permission(user_id, team_id, required_permission)


async def has_resource_permission(user_id: int, team_id: int, resource_type: str, required_permission: PermissionType) -> bool:
    """檢查資源權限"""
    return await permission_service.has_resource_permission(user_id, team_id, resource_type, required_permission)


async def get_user_accessible_teams(user_id: int) -> List[int]:
    """取得使用者可存取的團隊列表"""
    return await permission_service.get_user_accessible_teams(user_id)


async def clear_permission_cache(user_id: int, team_id: Optional[int] = None):
    """清除權限快取"""
    await permission_service.clear_cache(user_id, team_id)
        # TODO: 實作更精細的快取清除邏輯