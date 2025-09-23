#!/usr/bin/env python3
"""
權限服務測試

測試權限檢查服務的各項功能，包括：
- 角色檢查
- 團隊權限檢查  
- 資源權限檢查
- 權限快取
- 可存取團隊列表
"""

import asyncio
import logging
from datetime import datetime

from app.auth.models import UserRole, PermissionType
from app.auth.permission_service import permission_service
from app.database import init_database, get_async_session
from app.models.database_models import User, UserTeamPermission, Team
from app.auth.password_service import PasswordService

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def setup_test_data():
    """設置測試數據"""
    print("\n📦 設置測試數據...")
    
    async with get_async_session() as session:
        from sqlalchemy import select
        
        # 創建測試用戶
        password_service = PasswordService()
        test_users = [
            (3001, "super_admin_user", UserRole.SUPER_ADMIN, "Super Admin User"),
            (3002, "admin_user", UserRole.ADMIN, "Admin User"),  
            (3003, "viewer_user", UserRole.VIEWER, "Viewer User"),
            (3004, "regular_user", UserRole.USER, "Regular User"),
        ]
        
        for user_id, username, role, full_name in test_users:
            # 檢查用戶是否已存在
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            existing_user = result.scalar_one_or_none()
            
            if not existing_user:
                user = User(
                    id=user_id,
                    username=username,
                    email=f"{username}@test.com",
                    hashed_password=password_service.hash_password("test_password"),
                    full_name=full_name,
                    role=role,
                    is_active=True,
                    is_verified=True
                )
                session.add(user)
            
        # 創建測試團隊
        test_teams = [
            (101, "Team Alpha", "測試團隊 Alpha"),
            (102, "Team Beta", "測試團隊 Beta"),
            (103, "Team Gamma", "測試團隊 Gamma"),
        ]
        
        for team_id, name, description in test_teams:
            result = await session.execute(
                select(Team).where(Team.id == team_id)
            )
            existing_team = result.scalar_one_or_none()
            
            if not existing_team:
                team = Team(
                    id=team_id,
                    name=name,
                    description=description,
                    wiki_token="test_token",
                    test_case_table_id="test_table_id",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(team)
        
        # 設定團隊權限
        test_permissions = [
            (3002, 101, PermissionType.ADMIN),   # admin_user -> Team Alpha (ADMIN)
            (3002, 102, PermissionType.WRITE),   # admin_user -> Team Beta (WRITE)
            (3003, 101, PermissionType.READ),    # viewer_user -> Team Alpha (read)
            (3003, 102, PermissionType.READ),    # viewer_user -> Team Beta (read) 
            (3004, 102, PermissionType.READ),    # regular_user -> Team Beta (read)
            (3004, 103, PermissionType.WRITE),   # regular_user -> Team Gamma (WRITE)
        ]
        
        for user_id, team_id, permission in test_permissions:
            result = await session.execute(
                select(UserTeamPermission).where(
                    UserTeamPermission.user_id == user_id,
                    UserTeamPermission.team_id == team_id
                )
            )
            existing_permission = result.scalar_one_or_none()
            
            if not existing_permission:
                team_permission = UserTeamPermission(
                    user_id=user_id,
                    team_id=team_id,
                    permission=permission,
                    granted_at=datetime.utcnow()
                )
                session.add(team_permission)
        
        await session.commit()
        print("✅ 測試數據設置完成")


async def test_user_role_check():
    """測試使用者角色檢查"""
    print("\n🔐 測試 1: 使用者角色檢查")
    
    test_cases = [
        # (user_id, required_role, expected_result, description)
        (3001, UserRole.SUPER_ADMIN, True, "Super Admin 檢查自身角色"),
        (3001, UserRole.ADMIN, True, "Super Admin 具備 Admin 權限"),
        (3001, UserRole.USER, True, "Super Admin 具備 User 權限"),
        (3002, UserRole.SUPER_ADMIN, False, "Admin 不具備 Super Admin 權限"),
        (3002, UserRole.ADMIN, True, "Admin 檢查自身角色"),
        (3002, UserRole.USER, True, "Admin 具備 User 權限"),
        (3003, UserRole.ADMIN, False, "Viewer 不具備 Admin 權限"),
        (3003, UserRole.VIEWER, True, "Viewer 檢查自身角色"),
        (3004, UserRole.VIEWER, True, "User 具備 Viewer 權限"),
        (3004, UserRole.USER, True, "User 檢查自身角色"),
        (9999, UserRole.USER, False, "不存在的用戶"),
    ]
    
    for user_id, required_role, expected, description in test_cases:
        result = await permission_service.check_user_role(user_id, required_role)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {description}: {result}")
        assert result == expected, f"角色檢查失敗: {description}"
    
    print("✅ 使用者角色檢查測試通過")


async def test_team_permission_check():
    """測試團隊權限檢查"""
    print("\n👥 測試 2: 團隊權限檢查")
    
    test_cases = [
        # (user_id, team_id, required_permission, expected_result, description)
        (3002, 101, PermissionType.ADMIN, True, "Admin 用戶對 Team Alpha 的管理權限"),
        (3002, 101, PermissionType.WRITE, True, "Admin 用戶對 Team Alpha 的寫入權限"),
        (3002, 101, PermissionType.READ, True, "Admin 用戶對 Team Alpha 的讀取權限"),
        (3002, 102, PermissionType.ADMIN, False, "Admin 用戶對 Team Beta 無管理權限"),
        (3002, 102, PermissionType.WRITE, True, "Admin 用戶對 Team Beta 的寫入權限"),
        (3003, 101, PermissionType.READ, True, "Viewer 用戶對 Team Alpha 的讀取權限"),
        (3003, 101, PermissionType.WRITE, False, "Viewer 用戶對 Team Alpha 無寫入權限"),
        (3003, 102, PermissionType.READ, True, "Viewer 用戶對 Team Beta 的讀取權限"),
        (3003, 102, PermissionType.WRITE, False, "Viewer 用戶對 Team Beta 無寫入權限"),
        (3004, 102, PermissionType.READ, True, "Regular 用戶對 Team Beta 的讀取權限"),
        (3004, 102, PermissionType.WRITE, False, "Regular 用戶對 Team Beta 無寫入權限"),
        (3004, 103, PermissionType.WRITE, True, "Regular 用戶對 Team Gamma 的寫入權限"),
        (3004, 101, PermissionType.READ, False, "Regular 用戶對 Team Alpha 無權限"),
    ]
    
    for user_id, team_id, required_permission, expected, description in test_cases:
        result = await permission_service.check_team_permission(user_id, team_id, required_permission)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {description}: {result}")
        assert result == expected, f"團隊權限檢查失敗: {description}"
    
    print("✅ 團隊權限檢查測試通過")


async def test_resource_permission_check():
    """測試資源權限檢查"""
    print("\n📁 測試 3: 資源權限檢查")
    
    test_cases = [
        # (user_id, team_id, resource_type, required_permission, expected_result, description)
        (3001, 101, "test_case", PermissionType.ADMIN, True, "Super Admin 對任何資源都有權限"),
        (3001, 999, "test_case", PermissionType.ADMIN, True, "Super Admin 對不存在團隊也有權限"),
        (3002, 101, "test_case", PermissionType.ADMIN, True, "Admin 用戶對 Team Alpha 測試用例的管理權限"),
        (3002, 101, "test_run", PermissionType.WRITE, True, "Admin 用戶對 Team Alpha 測試運行的寫入權限"),
        (3002, 102, "test_case", PermissionType.ADMIN, False, "Admin 用戶對 Team Beta 測試用例無管理權限"),
        (3002, 102, "test_case", PermissionType.WRITE, True, "Admin 用戶對 Team Beta 測試用例的寫入權限"),
        (3003, 101, "test_case", PermissionType.READ, True, "Viewer 用戶對 Team Alpha 測試用例的讀取權限"),
        (3003, 102, "test_case", PermissionType.READ, True, "Viewer 用戶對 Team Beta 測試用例的讀取權限"),
        (3003, 102, "test_case", PermissionType.WRITE, False, "Viewer 用戶對 Team Beta 測試用例無寫入權限"),
        (3004, 102, "test_case", PermissionType.READ, True, "Regular 用戶對 Team Beta 測試用例的讀取權限"),
        (3004, 103, "test_run", PermissionType.WRITE, True, "Regular 用戶對 Team Gamma 測試運行的寫入權限"),
        (3004, 101, "test_case", PermissionType.READ, False, "Regular 用戶對 Team Alpha 測試用例無權限"),
    ]
    
    for user_id, team_id, resource_type, required_permission, expected, description in test_cases:
        result = await permission_service.has_resource_permission(user_id, team_id, resource_type, required_permission)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {description}: {result}")
        assert result == expected, f"資源權限檢查失敗: {description}"
    
    print("✅ 資源權限檢查測試通過")


async def test_accessible_teams():
    """測試可存取團隊列表"""
    print("\n🏢 測試 4: 可存取團隊列表")
    
    test_cases = [
        # (user_id, expected_teams, description)
        (3001, [9, 101, 102, 103], "Super Admin 可存取所有團隊"),
        (3002, [101, 102], "Admin 用戶可存取有權限的團隊"),
        (3003, [101, 102], "Viewer 用戶可存取有權限的團隊"),
        (3004, [102, 103], "Regular 用戶可存取有權限的團隊"),
        (9999, [], "不存在的用戶無法存取任何團隊"),
    ]
    
    for user_id, expected_teams, description in test_cases:
        accessible_teams = await permission_service.get_user_accessible_teams(user_id)
        # 排序以便比較
        accessible_teams.sort()
        expected_teams.sort()
        
        result = accessible_teams == expected_teams
        status = "✅" if result else "❌"
        print(f"  {status} {description}: {accessible_teams}")
        assert result, f"可存取團隊檢查失敗: {description}, 期望: {expected_teams}, 實際: {accessible_teams}"
    
    print("✅ 可存取團隊列表測試通過")


async def test_permission_summary():
    """測試權限摘要"""
    print("\n📊 測試 5: 權限摘要")
    
    test_cases = [
        # (user_id, description)
        (3001, "Super Admin 權限摘要"),
        (3002, "Admin 用戶權限摘要"),
        (3003, "Viewer 用戶權限摘要"),
        (3004, "Regular 用戶權限摘要"),
    ]
    
    for user_id, description in test_cases:
        summary = await permission_service.get_permission_summary(user_id)
        print(f"  📋 {description}:")
        print(f"     用戶ID: {summary.get('user_id')}")
        print(f"     角色: {summary.get('role')}")
        print(f"     可存取團隊: {summary.get('accessible_teams')}")
        print(f"     團隊權限: {summary.get('team_permissions')}")
        print(f"     是否 Super Admin: {summary.get('is_super_admin')}")
        print(f"     是否 Admin: {summary.get('is_admin')}")
        
        assert summary.get('user_id') == user_id, "用戶ID不匹配"
        assert summary.get('role') is not None, "角色資訊缺失"
        assert isinstance(summary.get('accessible_teams'), list), "可存取團隊應為列表"
        assert isinstance(summary.get('team_permissions'), dict), "團隊權限應為字典"
    
    print("✅ 權限摘要測試通過")


async def test_permission_cache():
    """測試權限快取"""
    print("\n🗄️ 測試 6: 權限快取")
    
    # 先執行一次權限檢查，觸發快取
    print("  📥 觸發快取...")
    await permission_service.check_user_role(3002, UserRole.ADMIN)
    await permission_service.check_team_permission(3002, 101, PermissionType.ADMIN)
    await permission_service.has_resource_permission(3002, 101, "test_case", PermissionType.WRITE)
    
    # 再次執行相同檢查，應該使用快取（可以通過 debug 日誌觀察）
    print("  💾 使用快取...")
    result1 = await permission_service.check_user_role(3002, UserRole.ADMIN)
    result2 = await permission_service.check_team_permission(3002, 101, PermissionType.ADMIN)
    result3 = await permission_service.has_resource_permission(3002, 101, "test_case", PermissionType.WRITE)
    
    assert result1 == True, "角色檢查結果錯誤"
    assert result2 == True, "團隊權限檢查結果錯誤"
    assert result3 == True, "資源權限檢查結果錯誤"
    
    # 清除快取
    print("  🗑️ 清除快取...")
    await permission_service.clear_cache(3002, 101)
    await permission_service.clear_cache(3002)
    
    # 重新執行檢查，應該重新查詢資料庫
    print("  🔄 重新查詢...")
    result4 = await permission_service.check_user_role(3002, UserRole.ADMIN)
    result5 = await permission_service.check_team_permission(3002, 101, PermissionType.ADMIN)
    
    assert result4 == True, "快取清除後角色檢查結果錯誤"
    assert result5 == True, "快取清除後團隊權限檢查結果錯誤"
    
    print("✅ 權限快取測試通過")


async def main():
    """主測試函數"""
    try:
        print("=" * 60)
        print("權限服務整合測試")
        print("=" * 60)
        
        # 初始化資料庫
        print("\n📦 初始化資料庫...")
        await init_database()
        
        # 設置測試數據
        await setup_test_data()
        
        # 執行測試
        await test_user_role_check()
        await test_team_permission_check()
        await test_resource_permission_check()
        await test_accessible_teams()
        await test_permission_summary()
        await test_permission_cache()
        
        print("\n" + "=" * 60)
        print("🎉 所有權限服務測試都通過了！")
        print("=" * 60)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        logger.error("權限服務測試失敗", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)