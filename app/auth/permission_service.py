"""
權限檢查服務

實作角色檢查、團隊權限檢查、權限快取機制。
遵循「預設拒絕」原則和「資源所屬團隊權限優先」原則。
"""

import asyncio
import logging
import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from functools import lru_cache

import casbin
import yaml
from sqlalchemy import select

from app.database import get_async_session
from app.models.database_models import User, Team
from app.auth.models import UserRole, PermissionType, PermissionCheck
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
    """權限檢查服務（Casbin + 集中設定：policy、constraints、ui_capabilities）"""
    
    # 動作清單（供 get_available_actions 使用）
    ACTIONS = [
        "view", "create", "update", "delete", "reset_password", "change_role", "toggle_active",
        "manage_members"
    ]

    DEFAULT_ROLES = ["SUPER_ADMIN", "ADMIN", "USER", "VIEWER"]

    # 內建預設策略版本（當讀檔失敗時使用）
    FALLBACK_VERSION = "fallback"

    def __init__(self):
        self.settings = get_settings()
        self.cache = PermissionCache(ttl_seconds=300)  # 5 分鐘快取

        # 設定檔路徑（Casbin + constraints + ui mapping）
        base_dir = os.path.join("config", "permissions")
        self._model_path = os.path.join(base_dir, "model.conf")
        self._policy_path = os.path.join(base_dir, "policy.csv")
        self._constraints_path = os.path.join(base_dir, "constraints.yaml")
        self._ui_map_path = os.path.join(base_dir, "ui_capabilities.yaml")

        # 執行體
        self._enforcer: Optional[casbin.Enforcer] = None
        self._constraints: Dict = {}
        self._ui_map: Dict = {}
        self._policy_version: str = self.FALLBACK_VERSION

        # 初始化載入
        self._load_all(initial=True)
    
    def _normalize_role(self, role: str) -> str:
        # 與 Casbin policy.csv 與 constraints.yaml 對齊：使用小寫（例如 SUPER_ADMIN -> super_admin）
        try:
            from app.auth.models import UserRole as _UR
            if isinstance(role, _UR):
                base = role.value
            else:
                base = str(role or "")
        except Exception:
            base = str(role or "")
        return base.strip().lower()

    def _compute_policy_version(self) -> str:
        parts = []
        for p in [self._model_path, self._policy_path, self._constraints_path, self._ui_map_path]:
            try:
                parts.append(str(os.path.getmtime(p)))
            except Exception:
                parts.append("0")
        raw = "|".join(parts).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:12]

    def _load_enforcer(self) -> casbin.Enforcer:
        if not os.path.exists(self._model_path) or not os.path.exists(self._policy_path):
            raise FileNotFoundError("Casbin model.conf 或 policy.csv 不存在")
        e = casbin.Enforcer(self._model_path, self._policy_path)
        return e

    def _load_constraints(self) -> Dict:
        if not os.path.exists(self._constraints_path):
            return {}
        with open(self._constraints_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        # 正規化角色鍵，並確保每個角色的設定至少為空 dict
        normalized: Dict[str, Dict] = {}
        for role_key, raw_rules in data.items():
            normalized_role = self._normalize_role(role_key)
            if isinstance(raw_rules, dict):
                normalized[normalized_role] = raw_rules
            else:
                # YAML 中僅留下註解時會得到 None，轉為空 dict 以避免後續 AttributeError
                normalized[normalized_role] = {}

        return normalized

    def _load_ui_map(self) -> Dict:
        if not os.path.exists(self._ui_map_path):
            return {}
        with open(self._ui_map_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _load_all(self, initial: bool = False) -> None:
        try:
            self._enforcer = self._load_enforcer()
        except FileNotFoundError as e:
            logging.warning(f"權限 policy 未找到，使用無 enforcer 模式: {e}")
            self._enforcer = None
        except Exception as e:
            logging.error(f"載入 Casbin enforcer 失敗: {e}")
            try:
                self._enforcer = casbin.Enforcer()
            except Exception:
                self._enforcer = None

        try:
            self._constraints = self._load_constraints()
        except Exception as e:
            logging.error(f"載入權限限制失敗: {e}")
            self._constraints = {}

        try:
            self._ui_map = self._load_ui_map()
        except Exception as e:
            logging.error(f"載入 UI 權限映射失敗: {e}")
            self._ui_map = {}

        try:
            self._policy_version = self._compute_policy_version()
        except Exception as e:
            logging.debug(f"計算權限版本失敗，使用預設: {e}")
            self._policy_version = self.FALLBACK_VERSION

        if self._enforcer:
            logging.info(f"Permission policy loaded, version={self._policy_version}")
        else:
            logging.info("Permission policy 未載入，僅使用限制與 UI 映射配置")

    def _maybe_reload(self) -> None:
        """若檔案版本有變更則熱重載策略/設定。"""
        try:
            current = self._compute_policy_version()
            if current != self._policy_version:
                logging.info(f"Permission policy changed: {self._policy_version} -> {current}, reloading...")
                self._load_all(initial=False)
        except Exception as e:
            logging.debug(f"_maybe_reload failed: {e}")

    async def get_ui_config(self, current_user: User, page: str) -> Dict[str, Any]:
        """根據使用者權限計算指定頁面的 UI 元件可視設定"""
        self._maybe_reload()

        page_key = (page or "").strip().lower()
        if not page_key:
            return {
                "page": "",
                "components": {},
                "policy_version": self.get_policy_version(),
            }

        pages_cfg: Dict[str, Any] = {}
        if isinstance(self._ui_map, dict):
            pages_cfg = self._ui_map.get("pages", {}) or {}

        page_cfg = pages_cfg.get(page_key) if isinstance(pages_cfg, dict) else None
        components_cfg: Dict[str, Any] = {}
        if isinstance(page_cfg, dict):
            components_cfg = page_cfg.get("components", {}) or {}
        if not isinstance(components_cfg, dict):
            components_cfg = {}

        components_result: Dict[str, bool] = {}

        for component_id, rule in components_cfg.items():
            allowed = False
            if isinstance(rule, dict):
                feature = rule.get("feature")
                action = rule.get("action") or "view"
                if feature:
                    try:
                        check_result = await self.check_permission(
                            current_user=current_user,
                            feature=str(feature),
                            action=str(action),
                        )
                        allowed = bool(getattr(check_result, "has_permission", False))
                    except Exception as e:
                        logger.error(
                            "計算 UI 權限失敗: user_id=%s page=%s component=%s error=%s",
                            getattr(current_user, "id", "?"),
                            page_key,
                            component_id,
                            e,
                        )
                    if not allowed:
                        allowed = self._fallback_ui_allowed(current_user, str(feature), str(action))
            if not allowed:
                allowed = self._fallback_ui_allowed(current_user, "", "", component_id)
            components_result[component_id] = allowed

        return {
            "page": page_key,
            "components": components_result,
            "policy_version": self.get_policy_version(),
        }

    def _fallback_ui_allowed(self, current_user: User, feature: str, action: str, component_id: str = "") -> bool:
        """當 Casbin 未配置時，以角色層級提供最小保護的 UI 顯示判斷"""
        role = getattr(current_user, "role", None)
        try:
            if role and not isinstance(role, UserRole):
                role = UserRole(role)
        except Exception:
            role = None

        if role == UserRole.SUPER_ADMIN:
            return True

        if role == UserRole.ADMIN:
            if feature == "user_management":
                return action in {"view", "update"} or component_id in {
                    "tab-personnel-li",
                    "pm-tab-personnel",
                    "syncOrgBtn",
                }
            if feature == "organization_management" and action == "view":
                return True

        return False

    def reload_matrix(self) -> Dict:
        """重新載入策略與配置，回傳版本摘要（相容舊介面）"""
        self._load_all(initial=False)
        # 回傳簡要（相容 /matrix 使用者）
        return self.get_matrix()

    # 以下方法為相容舊 API，用於 /matrix 顯示（非授權決策依據）
    def get_matrix(self) -> Dict:
        try:
            # 從 policy.csv 反推 features 與 roles
            features = set()
            roles = set()
            if os.path.exists(self._policy_path):
                with open(self._policy_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        cols = [c.strip() for c in line.split(',')]
                        if len(cols) >= 4 and cols[0] == 'p':
                            roles.add(cols[1].upper())
                            features.add(cols[2])
            return {
                "features": {f: {"actions": self.ACTIONS} for f in sorted(features)},
                "roles": {r: {} for r in sorted(roles)},
                "restrictions": self._constraints,
            }
        except Exception:
            return {
                "features": {},
                "roles": {r: {} for r in self.DEFAULT_ROLES},
                "restrictions": {},
            }

    def get_policy_version(self) -> str:
        return self._policy_version

    def get_role_level(self, role: str) -> int:
        # 以 DEFAULT_ROLES 的排序模擬層級
        order = {"VIEWER": 1, "USER": 2, "ADMIN": 3, "SUPER_ADMIN": 4}
        return int(order.get(self._normalize_role(role), 0))

    def has_basic_permission(self, role: str, feature: str, action: str, dom: str = "") -> bool:
        try:
            if not self._enforcer:
                return False
            return bool(self._enforcer.enforce(self._normalize_role(role), feature, action, dom, {}))
        except Exception:
            return False

    def get_feature_actions(self, feature: str) -> List[str]:
        return list(self.ACTIONS)

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
    
    async def _role_to_permission(self, role: UserRole) -> PermissionType:
        """將全域角色映射為資源權限等級"""
        if role == UserRole.SUPER_ADMIN or role == UserRole.ADMIN:
            return PermissionType.ADMIN
        if role == UserRole.USER:
            return PermissionType.WRITE
        return PermissionType.READ

    async def check_team_permission(
        self,
        user_id: int,
        team_id: int,
        required_permission: PermissionType,
        current_role: Optional[UserRole] = None,
    ) -> PermissionCheck:
        """
        根據使用者角色檢查權限。

        現在的權限僅由角色決定，team_id 僅用於快取鍵，實際上不再進行團隊粒度判斷。
        """

        try:
            if current_role:
                user_role = (
                    current_role
                    if isinstance(current_role, UserRole)
                    else UserRole(str(current_role))
                )
            else:
                user_role = await self._get_user_role(user_id)

            if not user_role:
                return PermissionCheck(
                    has_permission=False,
                    user_role=UserRole.VIEWER,
                    team_permission=None,
                    reason="使用者不存在或已停用",
                )

            mapped_permission = await self._role_to_permission(user_role)
            has_perm = self._compare_permissions(mapped_permission, required_permission)

            reason = None if has_perm else (
                f"角色 {user_role.value} 缺少 {required_permission.value} 權限"
            )

            # 仍保留快取，以便其他檢查共用資料
            await self.cache.set(user_id, mapped_permission, team_id)

            return PermissionCheck(
                has_permission=has_perm,
                user_role=user_role,
                team_permission=mapped_permission if has_perm else None,
                reason=reason,
            )

        except Exception as exc:
            logger.error(
                "角色權限檢查失敗: user_id=%s team_id=%s error=%s",
                user_id,
                team_id,
                exc,
            )
            return PermissionCheck(
                has_permission=False,
                user_role=UserRole.VIEWER,
                team_permission=None,
                reason="權限檢查發生例外",
            )

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
            user_role = await self._get_user_role(user_id)
            if not user_role:
                return []

            async with get_async_session() as session:
                result = await session.execute(select(Team.id))
                return [team_id for team_id, in result.fetchall()]

        except Exception as e:
            logger.error(f"取得使用者可存取團隊失敗: user_id={user_id}, error={e}")
            return []
    
    async def has_resource_permission(
        self,
        user_id: int,
        team_id: int,
        resource_type: str,
        required_permission: PermissionType,
    ) -> bool:
        """檢查資源權限，現僅依角色決定"""

        cached_result = await self.cache.get(user_id, team_id, resource_type)
        if cached_result is not None:
            return self._compare_permissions(cached_result, required_permission)

        try:
            permission_check = await self.check_team_permission(
                user_id, team_id, required_permission
            )

            if permission_check.has_permission and permission_check.team_permission:
                await self.cache.set(
                    user_id,
                    permission_check.team_permission,
                    team_id,
                    resource_type,
                )

            return permission_check.has_permission

        except Exception as exc:
            logger.error(
                "檢查資源權限失敗: user_id=%s, team_id=%s, resource_type=%s, error=%s",
                user_id,
                team_id,
                resource_type,
                exc,
            )
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
    
    async def check_permission(
        self,
        current_user: User,
        feature: str,
        action: str,
        target_user: Optional[User] = None,
        dom: str = "",
        **context
    ) -> PermissionCheck:
        """
        基於權限矩陣檢查權限
        
        Args:
            current_user: 當前使用者
            feature: 功能模組名稱
            action: 動作名稱
            target_user: 目標使用者（如果有的話）
            **context: 其他上下文資料（例如 new_role）
            
        Returns:
            權限檢查結果
        """
        # 動態偵測並熱重載策略/模型/限制
        self._maybe_reload()
        user_role = self._normalize_role(current_user.role)
        
        # 1) RBAC（Casbin）
        if not self.has_basic_permission(user_role, feature, action, dom):
            return PermissionCheck(
                has_permission=False,
                user_role=UserRole(current_user.role),
                reason=f"角色 {user_role} 沒有 {feature}.{action} 權限"
            )

        # 2) ABAC 限制（constraints.yaml）
        reasons: List[str] = []
        for ok, msg in self._evaluate_constraints(user_role, feature, action, current_user, target_user, **context):
            if not ok:
                reasons.append(msg)
        if reasons:
            return PermissionCheck(
                has_permission=False,
                user_role=UserRole(current_user.role),
                reason=f"權限限制: {'; '.join(reasons)}"
            )
       
        
        # 3. 檢查通過
        return PermissionCheck(
            has_permission=True,
            user_role=UserRole(current_user.role),
            reason=None
        )
    
    async def get_available_actions(
        self,
        current_user: User,
        feature: str,
        target_user: Optional[User] = None,
        **context
    ) -> List[str]:
        """
        取得當前使用者在指定功能下的可用動作列表
        
        Args:
            current_user: 當前使用者
            feature: 功能模組名稱
            target_user: 目標使用者（如果有的話）
            **context: 其他上下文資料
            
        Returns:
            可用動作列表
        """
        user_role = (current_user.role or "").upper()
        available_actions = []
        
        # 取得該功能的所有可能動作
        all_actions = self.get_feature_actions(feature)
        
        # 檢查每個動作
        for action in all_actions:
            check_result = await self.check_permission(
                current_user, feature, action, target_user, **context
            )
            if check_result.has_permission:
                available_actions.append(action)
        
        return available_actions
    
    async def bulk_check_permissions(
        self,
        current_user: User,
        checks: List[Dict[str, any]]
    ) -> Dict[str, PermissionCheck]:
        """
        批量檢查權限
        
        Args:
            current_user: 當前使用者
            checks: 權限檢查項目列表，每項包含 {"key": str, "feature": str, "action": str, "target_user_id": int?, "context": dict?}
            
        Returns:
            權限檢查結果字典，key 為檢查項目的 key
        """
        results = {}
        
        for check in checks:
            key = check["key"]
            feature = check["feature"]
            action = check["action"]
            target_user_id = check.get("target_user_id")
            context = check.get("context", {})
            
            target_user = None
            if target_user_id:
                # 取得目標使用者資訊
                try:
                    async with get_async_session() as session:
                        result = await session.execute(
                            select(User).where(User.id == target_user_id)
                        )
                        target_user = result.scalar_one_or_none()
                except Exception as e:
                    logger.error(f"取得目標使用者失敗: target_user_id={target_user_id}, error={e}")
            
            # 執行權限檢查
            check_result = await self.check_permission(
                current_user, feature, action, target_user, **context
            )
            results[key] = check_result
        
        return results
    
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
            return {
                "user_id": user_id,
                "role": user_role.value,
                "accessible_teams": accessible_teams,
                "team_permissions": {},
                "is_super_admin": user_role == UserRole.SUPER_ADMIN,
                "is_admin": user_role in [UserRole.SUPER_ADMIN, UserRole.ADMIN]
            }
            
        except Exception as e:
            logger.error(f"取得權限摘要失敗: user_id={user_id}, error={e}")
            return {}


    def _evaluate_constraints(self,
                              role: str,
                              feature: str,
                              action: str,
                              current_user: User,
                              target_user: Optional[User] = None,
                              **context) -> List[Tuple[bool, str]]:
        """執行 constraints.yaml 內的限制條件
        回傳 (是否通過, 理由) 列表（AND 邏輯）。"""
        results: List[Tuple[bool, str]] = []
        role = self._normalize_role(role)
        role_rules = self._constraints.get(role) or {}
        if not isinstance(role_rules, dict):
            role_rules = {}

        feature_rules = role_rules.get(feature) if isinstance(role_rules, dict) else {}
        if not isinstance(feature_rules, dict):
            feature_rules = {}

        action_rules = feature_rules.get(action, [])
        if not isinstance(action_rules, list):
            action_rules = []

        rules = action_rules
        for rule in rules:
            name = rule.get('name')
            args = rule.get('args', [])
            ok, reason = self._run_constraint(name, args, current_user, target_user, **context)
            results.append((ok, reason))
        return results

    def _run_constraint(self, name: str, args: List, current_user: User, target_user: Optional[User], **context) -> Tuple[bool, str]:
        """執行單一限制規則"""
        registry = {
            'cannot_modify_self': self._c_cannot_modify_self,
            'cannot_target_roles': self._c_cannot_target_roles,
            'cannot_promote_to': self._c_cannot_promote_to,
        }
        fn = registry.get(name)
        if not fn:
            return False, f"未知限制: {name}"
        try:
            return fn(current_user=current_user, target_user=target_user, args=args, **context)
        except Exception as e:
            return False, f"限制執行錯誤: {name}: {e}"

    # 以下為限制函式實作（返回 (ok, reason)）
    def _c_cannot_modify_self(self, current_user: User, target_user: Optional[User], args: List, **context) -> Tuple[bool, str]:
        if not target_user:
            return True, ''
        ok = (current_user.id != target_user.id)
        return ok, ('' if ok else '無法修改自己的設定')

    def _c_cannot_target_roles(self, current_user: User, target_user: Optional[User], args: List, **context) -> Tuple[bool, str]:
        if not target_user:
            return True, ''
        forbidden = [str(x).upper() for x in (args[0] if args else [])]
        ok = (str(target_user.role).upper() not in forbidden)
        return ok, ('' if ok else f"無法對 {forbidden} 執行此動作")

    def _c_cannot_promote_to(self, current_user: User, target_user: Optional[User], args: List, **context) -> Tuple[bool, str]:
        new_role = str(context.get('new_role', '')).upper()
        if not new_role:
            return True, ''
        forbidden = [str(x).upper() for x in (args[0] if args else [])]
        ok = (new_role not in forbidden)
        return ok, ('' if ok else f"無法提升到 {forbidden}")

# 全域權限服務實例
permission_service = PermissionService()


# 便利函數
async def check_user_role(user_id: int, required_role: UserRole) -> bool:
    """檢查使用者角色"""
    return await permission_service.check_user_role(user_id, required_role)


async def check_team_permission(
    user_id: int, team_id: int, required_permission: PermissionType
) -> PermissionCheck:
    """檢查團隊權限（角色導向）"""
    return await permission_service.check_team_permission(
        user_id, team_id, required_permission
    )


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
