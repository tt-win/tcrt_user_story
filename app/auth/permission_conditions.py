"""
權限條件檢查函數

實作各種業務規則的條件檢查邏輯，支援複雜的權限控制場景。
這些函數會被權限矩陣中的 restrictions 規則呼叫。
"""

import re
import ast
from typing import Dict, Any, Optional, List, Union
from app.models.database_models import User


class PermissionConditions:
    """權限條件檢查器"""

    @staticmethod
    def cannot_target_roles(
        current_user: User, target_user: Optional[User], roles: List[str], **context
    ) -> bool:
        """
        檢查是否不能對指定角色執行動作

        Args:
            current_user: 當前使用者
            target_user: 目標使用者
            roles: 不能操作的角色列表

        Returns:
            True 如果可以操作（目標角色不在禁止列表中）
        """
        if not target_user:
            return False

        target_role = (target_user.role or "").upper()
        forbidden_roles = [role.upper() for role in roles]

        # 如果目標角色在禁止列表中，返回 False（不能操作）
        return target_role not in forbidden_roles

    @staticmethod
    def cannot_modify_self(
        current_user: User, target_user: Optional[User], **context
    ) -> bool:
        """
        檢查是否不能修改自己

        Args:
            current_user: 當前使用者
            target_user: 目標使用者

        Returns:
            True 如果可以操作（不是操作自己）
        """
        if not target_user:
            return False

        # 如果目標是自己，返回 False（不能操作）
        return current_user.id != target_user.id

    @staticmethod
    def cannot_promote_to(
        current_user: User, target_user: Optional[User], roles: List[str], **context
    ) -> bool:
        """
        檢查是否不能提升到指定角色

        Args:
            current_user: 當前使用者
            target_user: 目標使用者
            roles: 不能提升到的角色列表

        Returns:
            True 如果可以操作（新角色不在禁止列表中）
        """
        # 從 context 中取得新角色
        new_role = context.get("new_role", "").upper()
        if not new_role:
            return True  # 如果沒有指定新角色，允許操作

        forbidden_roles = [role.upper() for role in roles]

        # 如果新角色在禁止列表中，返回 False（不能操作）
        return new_role not in forbidden_roles

    @staticmethod
    def must_be_team_admin(
        current_user: User, target_user: Optional[User], **context
    ) -> bool:
        """
        檢查是否必須是團隊管理員（預留給團隊功能使用）

        Args:
            current_user: 當前使用者
            target_user: 目標使用者

        Returns:
            True 如果有權限操作
        """
        # 這裡可以實作團隊管理員檢查邏輯
        # 目前先回傳 True，等團隊功能完善後再實作
        return True

    @staticmethod
    def role_level_higher_than(
        current_user: User, 
        target_user: Optional[User], 
        min_level: int,
        **context
    ) -> bool:
        """
        檢查當前使用者角色層級是否高於指定層級
        
        Args:
            current_user: 當前使用者
            target_user: 目標使用者
            min_level: 最低要求層級
            
        Returns:
            True 如果角色層級足夠
        """
        # 從 context 取得 role_hierarchy（由服務注入），若沒有則使用安全預設
        role_hierarchy = context.get('role_hierarchy') or {
            'VIEWER': 1,
            'USER': 2,
            'ADMIN': 3,
            'SUPER_ADMIN': 4,
        }
        current_role = (current_user.role or '').upper()
        current_level = int(role_hierarchy.get(current_role, 0))
        return current_level >= min_level
class ConditionEvaluator:
    """條件表達式評估器"""

    def __init__(self):
        self.conditions = PermissionConditions()

    def evaluate_condition(
        self,
        condition_str: str,
        current_user: User,
        target_user: Optional[User] = None,
        **context,
    ) -> tuple[bool, str]:
        """
        評估條件表達式

        Args:
            condition_str: 條件表達式字串，例如 "cannot_target_roles(['ADMIN', 'SUPER_ADMIN'])"
            current_user: 當前使用者
            target_user: 目標使用者
            **context: 其他上下文資料

        Returns:
            (是否允許操作, 失敗原因)
        """
        try:
            # 解析函數名稱和參數
            match = re.match(r"(\w+)\((.*)\)", condition_str.strip())
            if not match:
                return False, f"無效的條件表達式: {condition_str}"

            func_name, args_str = match.groups()

            # 檢查函數是否存在
            if not hasattr(self.conditions, func_name):
                return False, f"未知的條件函數: {func_name}"

            # 解析參數
            args, kwargs = self._parse_arguments(args_str)

            # 呼叫條件函數
            func = getattr(self.conditions, func_name)
            result = func(current_user, target_user, *args, **context, **kwargs)

            if not result:
                reason = self._get_failure_reason(func_name, args, kwargs)
                return False, reason

            return True, ""

        except Exception as e:
            return False, f"條件評估錯誤: {str(e)}"

    def _parse_arguments(self, args_str: str) -> tuple[List[Any], Dict[str, Any]]:
        """解析函數參數"""
        args = []
        kwargs = {}

        if not args_str.strip():
            return args, kwargs

        try:
            # 使用 ast.literal_eval 安全地評估參數
            parsed = ast.literal_eval(f"({args_str},)")
            if isinstance(parsed, tuple):
                for arg in parsed:
                    if isinstance(arg, dict):
                        kwargs.update(arg)
                    else:
                        args.append(arg)
            else:
                args.append(parsed)

        except (ValueError, SyntaxError):
            # 如果解析失敗，嘗試簡單的字串分割
            parts = [part.strip() for part in args_str.split(",")]
            for part in parts:
                if "=" in part:
                    key, value = part.split("=", 1)
                    kwargs[key.strip()] = value.strip().strip("'\"")
                else:
                    # 嘗試評估為字串或數字
                    try:
                        args.append(ast.literal_eval(part))
                    except:
                        args.append(part.strip().strip("'\""))

        return args, kwargs

    def _get_failure_reason(
        self, func_name: str, args: List[Any], kwargs: Dict[str, Any]
    ) -> str:
        """取得失敗原因的描述"""
        reason_map = {
            "cannot_target_roles": f"無法對 {args[0] if args else '指定角色'} 執行此動作",
            "cannot_modify_self": "無法修改自己的設定",
            "cannot_promote_to": f"無法提升到 {args[0] if args else '指定角色'}",
            "must_be_team_admin": "需要團隊管理員權限",
            "role_level_higher_than": f"角色層級不足，需要層級 {args[0] if args else 'N/A'} 以上",
        }

        return reason_map.get(func_name, f"權限檢查失敗: {func_name}")

    def evaluate_all_conditions(
        self,
        conditions: List[str],
        current_user: User,
        target_user: Optional[User] = None,
        **context,
    ) -> tuple[bool, List[str]]:
        """
        評估所有條件（AND 邏輯）

        Args:
            conditions: 條件列表
            current_user: 當前使用者
            target_user: 目標使用者
            **context: 其他上下文資料

        Returns:
            (是否全部通過, 失敗原因列表)
        """
        failures = []

        for condition in conditions:
            passed, reason = self.evaluate_condition(
                condition, current_user, target_user, **context
            )
            if not passed:
                failures.append(reason)

        return len(failures) == 0, failures


# 延遲初始化避免匯入循環
_condition_evaluator_instance = None

def get_condition_evaluator():
    global _condition_evaluator_instance
    if _condition_evaluator_instance is None:
        _condition_evaluator_instance = ConditionEvaluator()
    return _condition_evaluator_instance

# 相容舊名稱：直接提供一個單例
condition_evaluator = get_condition_evaluator()
