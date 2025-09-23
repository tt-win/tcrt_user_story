#!/usr/bin/env python3
"""
認證服務整合會話管理測試

測試 JWT Token 認證服務與會話管理的整合功能。
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.auth.auth_service import AuthService
from app.auth.models import UserRole
from app.auth.session_service import session_service
from app.database import init_database, get_async_session
from app.models.database_models import ActiveSession, User
from app.auth.password_service import PasswordService

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_auth_service_integration():
    """測試認證服務與會話管理的整合"""
    
    print("=" * 60)
    print("認證服務與會話管理整合測試")
    print("=" * 60)
    
    # 初始化資料庫
    print("\n📦 初始化資料庫...")
    await init_database()
    
    # 測試用戶資料
    user_id = 1001
    username = "test_user"
    role = UserRole.USER
    ip_address = "192.168.1.100"
    user_agent = "Mozilla/5.0 (Test Browser)"
    
    # 創建測試用戶
    print("\n👤 創建測試用戶...")
    async with get_async_session() as session:
        # 檢查用戶是否已存在
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        existing_user = result.scalar_one_or_none()
        
        if not existing_user:
            # 創建新用戶
            test_user = User(
                id=user_id,
                username=username,
                email="test@example.com",
                hashed_password=PasswordService().hash_password("test_password"),
                full_name="Test User",
                role=role,
                is_active=True,
                is_verified=True
            )
            session.add(test_user)
            await session.commit()
            print(f"✅ 測試用戶已創建: ID={user_id}, username={username}")
        else:
            print(f"✅ 測試用戶已存在: ID={user_id}, username={username}")
    
    # 創建認證服務實例
    auth_service = AuthService()
    
    try:
        # 1. 測試創建 Token 與會話記錄
        print("\n🔑 測試 1: 創建 Access Token 與會話記錄")
        token, jti, expires_at = await auth_service.create_access_token(
            user_id=user_id,
            username=username,
            role=role,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        print(f"✅ Token 創建成功")
        print(f"   JTI: {jti}")
        print(f"   過期時間: {expires_at}")
        print(f"   Token 長度: {len(token)} 字符")
        
        # 檢查會話記錄是否已創建
        active_sessions = await session_service.get_active_sessions(user_id)
        assert len(active_sessions) == 1, f"預期 1 個活躍會話，實際 {len(active_sessions)} 個"
        session_record = active_sessions[0]
        assert session_record.jti == jti, "JTI 不匹配"
        assert session_record.ip_address == ip_address, "IP 地址不匹配"
        assert session_record.user_agent == user_agent, "User Agent 不匹配"
        print(f"✅ 會話記錄創建成功")
        
        # 2. 測試 Token 驗證
        print("\n🔐 測試 2: Token 驗證")
        token_data = await auth_service.verify_token(token)
        assert token_data is not None, "Token 驗證失敗"
        assert token_data.user_id == user_id, "User ID 不匹配"
        assert token_data.username == username, "Username 不匹配"
        assert token_data.role == role, "Role 不匹配"
        assert token_data.jti == jti, "JTI 不匹配"
        print(f"✅ Token 驗證成功")
        print(f"   User ID: {token_data.user_id}")
        print(f"   Username: {token_data.username}")
        print(f"   Role: {token_data.role.value}")
        
        # 3. 測試 Token 撤銷
        print("\n❌ 測試 3: Token 撤銷")
        revoke_success = await auth_service.revoke_token(jti, "test_logout")
        assert revoke_success, "Token 撤銷失敗"
        print(f"✅ Token 撤銷成功")
        
        # 檢查撤銷後的 Token 驗證
        revoked_token_data = await auth_service.verify_token(token)
        assert revoked_token_data is None, "撤銷的 Token 不應該通過驗證"
        print(f"✅ 撤銷的 Token 驗證正確失敗")
        
        # 檢查會話記錄狀態
        async with get_async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(ActiveSession).where(ActiveSession.jti == jti)
            )
            revoked_session = result.scalar_one_or_none()
            assert revoked_session is not None, "找不到撤銷的會話記錄"
            assert revoked_session.is_revoked, "會話記錄未標記為已撤銷"
            assert revoked_session.revoked_reason == "test_logout", "撤銷原因不匹配"
            print(f"✅ 會話記錄狀態更新正確")
        
        # 4. 測試 Token 刷新
        print("\n🔄 測試 4: Token 刷新")
        # 創建新的 Token 用於刷新測試
        old_token, old_jti, _ = await auth_service.create_access_token(
            user_id=user_id,
            username=username,
            role=role,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # 刷新 Token
        refresh_result = await auth_service.refresh_token(
            old_token,
            ip_address=ip_address,
            user_agent=user_agent
        )
        assert refresh_result is not None, "Token 刷新失敗"
        
        new_token, new_jti, new_expires_at = refresh_result
        assert new_jti != old_jti, "新 JTI 不應該與舊的相同"
        print(f"✅ Token 刷新成功")
        print(f"   舊 JTI: {old_jti}")
        print(f"   新 JTI: {new_jti}")
        
        # 檢查舊 Token 是否已撤銷
        old_token_data = await auth_service.verify_token(old_token)
        assert old_token_data is None, "刷新後舊 Token 應該被撤銷"
        print(f"✅ 舊 Token 已正確撤銷")
        
        # 檢查新 Token 是否有效
        new_token_data = await auth_service.verify_token(new_token)
        assert new_token_data is not None, "新 Token 應該有效"
        assert new_token_data.jti == new_jti, "新 Token 的 JTI 不匹配"
        print(f"✅ 新 Token 驗證成功")
        
        # 5. 測試撤銷用戶所有 Token
        print("\n🚫 測試 5: 撤銷用戶所有 Token")
        # 創建多個 Token
        tokens_data = []
        for i in range(3):
            token, jti, expires_at = await auth_service.create_access_token(
                user_id=user_id,
                username=username,
                role=role,
                ip_address=f"192.168.1.{100+i}",
                user_agent=f"Browser {i+1}"
            )
            tokens_data.append((token, jti, expires_at))
        
        print(f"✅ 創建了 {len(tokens_data)} 個 Token")
        
        # 撤銷該用戶的所有 Token
        revoked_count = await auth_service.revoke_user_tokens(user_id, "admin_logout")
        # 注意：包括之前刷新測試創建的新 Token，所以總數應該是 4
        assert revoked_count >= 3, f"預期至少撤銷 3 個 Token，實際撤銷 {revoked_count} 個"
        print(f"✅ 撤銷了 {revoked_count} 個用戶 Token")
        
        # 檢查所有 Token 是否都已撤銷
        for i, (token, jti, _) in enumerate(tokens_data):
            token_data = await auth_service.verify_token(token)
            assert token_data is None, f"Token {i+1} 應該已被撤銷"
        print(f"✅ 所有 Token 都已正確撤銷")
        
        # 6. 測試會話統計
        print("\n📊 測試 6: 會話統計")
        stats = await session_service.get_session_statistics()
        print(f"✅ 會話統計:")
        print(f"   總會話數: {stats.get('total_sessions', 0)}")
        print(f"   活躍會話數: {stats.get('active_sessions', 0)}")
        print(f"   已撤銷會話數: {stats.get('revoked_sessions', 0)}")
        print(f"   記憶體快取 JTI 數: {stats.get('memory_cached_jtis', 0)}")
        
        # 7. 測試會話清理
        print("\n🧹 測試 7: 會話清理")
        cleaned_count = await session_service.cleanup_expired_sessions()
        print(f"✅ 清理了 {cleaned_count} 個過期會話")
        
        print("\n" + "=" * 60)
        print("🎉 所有認證服務與會話管理整合測試通過！")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        logger.error(f"認證服務整合測試失敗", exc_info=True)
        return False


async def test_concurrent_operations():
    """測試並發操作"""
    
    print("\n" + "=" * 60)
    print("並發操作測試")
    print("=" * 60)
    
    auth_service = AuthService()
    
    async def create_and_verify_token(test_user_id: int, test_username: str):
        """創建並驗證 Token"""
        try:
            # 確保測試用戶存在
            async with get_async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(User).where(User.id == test_user_id)
                )
                existing_user = result.scalar_one_or_none()
                
                if not existing_user:
                    # 創建新用戶
                    test_user = User(
                        id=test_user_id,
                        username=test_username,
                        email=f"{test_username}@example.com",
                        hashed_password=PasswordService().hash_password("test_password"),
                        full_name=f"Test User {test_user_id}",
                        role=UserRole.USER,
                        is_active=True,
                        is_verified=True
                    )
                    session.add(test_user)
                    await session.commit()
            
            # 創建 Token
            token, jti, expires_at = await auth_service.create_access_token(
                user_id=test_user_id,
                username=test_username,
                role=UserRole.USER,
                ip_address=f"192.168.1.{test_user_id}",
                user_agent=f"Browser {test_user_id}"
            )
            
            # 驗證 Token
            token_data = await auth_service.verify_token(token)
            assert token_data is not None, f"User {test_user_id} Token 驗證失敗"
            assert token_data.user_id == test_user_id, f"User {test_user_id} ID 不匹配"
            
            # 撤銷 Token
            success = await auth_service.revoke_token(jti, f"test_user_{test_user_id}")
            assert success, f"User {test_user_id} Token 撤銷失敗"
            
            return f"User {test_user_id} 操作成功"
            
        except Exception as e:
            return f"User {test_user_id} 操作失敗: {e}"
    
    # 並發執行多個操作
    tasks = []
    for i in range(10):
        task = create_and_verify_token(2000 + i, f"concurrent_user_{i}")
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success_count = 0
    for result in results:
        if isinstance(result, str) and "成功" in result:
            success_count += 1
            print(f"✅ {result}")
        else:
            print(f"❌ {result}")
    
    print(f"\n並發操作結果: {success_count}/{len(tasks)} 個操作成功")
    assert success_count == len(tasks), "部分並發操作失敗"
    
    print("🎉 並發操作測試通過！")
    return True


async def main():
    """主測試函數"""
    try:
        # 基本整合測試
        success1 = await test_auth_service_integration()
        
        # 並發操作測試
        success2 = await test_concurrent_operations()
        
        if success1 and success2:
            print("\n🎊 所有測試都通過了！")
            return 0
        else:
            print("\n💥 部分測試失敗")
            return 1
            
    except Exception as e:
        print(f"\n💥 測試執行失敗: {e}")
        logger.error("測試執行失敗", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)