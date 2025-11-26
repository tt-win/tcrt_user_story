import asyncio
import sys
import os
from datetime import datetime

# 將專案根目錄加入 sys.path
sys.path.insert(0, os.getcwd())

from app.database import SessionLocal
from app.models.user_story_map_db import USMAsyncSessionLocal
from app.models.database_models import User, Team
from app.auth.models import UserRole
from app.api.llm_context import get_test_cases_context, get_usm_context
from sqlalchemy import select

async def main():
    print("=== LLM Context API 內部測試腳本 ===")
    
    # 1. 建立 Session
    db = SessionLocal()
    usm_db = USMAsyncSessionLocal()
    
    try:
        # 2. 模擬超級管理員使用者
        # 這裡不需要真的從資料庫撈使用者，只要物件屬性符合 API 需求即可
        # API 檢查: current_user.role, current_user.id, current_user.username
        class MockUser:
            id = 1
            username = "mock_admin"
            role = UserRole.SUPER_ADMIN
            
        current_user = MockUser()
        print(f"模擬使用者: {current_user.username} ({current_user.role})")

        # 3. 獲取一個有效的 Team ID
        print("\n[1] 正在尋找有效團隊...")
        result = await db.execute(select(Team).limit(1))
        team = result.scalars().first()
        
        if not team:
            print("錯誤: 資料庫中沒有團隊，無法測試。")
            return
            
        team_id = team.id
        print(f"使用團隊: {team.name} (ID: {team_id})")

        # 4. 測試 Test Case Context
        print("\n[2] 測試 get_test_cases_context...")
        try:
            tc_resp = await get_test_cases_context(
                team_id=team_id,
                limit=3,
                since=None,
                db=db,
                current_user=current_user
            )
            
            print(f"成功獲取! 總數: {tc_resp.total}, 本次返回: {len(tc_resp.items)}")
            if tc_resp.items:
                item = tc_resp.items[0]
                print("--- 範例資料 (Test Case) ---")
                print(f"ID: {item.id}")
                print(f"Metadata: {item.metadata}")
                print(f"Text (前100字): {item.text[:100]}...")
            else:
                print("無測試案例資料。")
                
        except Exception as e:
            print(f"Test Case API 執行失敗: {e}")
            import traceback
            traceback.print_exc()

        # 5. 測試 USM Context
        print("\n[3] 測試 get_usm_context...")
        try:
            # 嘗試列出該團隊的 USM
            usm_resp = await get_usm_context(
                team_id=team_id,
                map_id=None,
                since=None,
                usm_db=usm_db,
                db=db,
                current_user=current_user
            )
            
            print(f"成功獲取! 總數: {usm_resp.total}, 本次返回: {len(usm_resp.items)}")
            if usm_resp.items:
                # 試著找一個非 root 的節點展示
                sample = next((i for i in usm_resp.items if i.metadata.get('node_type') != 'root'), usm_resp.items[0])
                print("--- 範例資料 (USM Node) ---")
                print(f"ID: {sample.id}")
                print(f"Metadata: {sample.metadata}")
                print(f"Text (前100字): {sample.text[:100]}...")
            else:
                print("無 USM 資料。")

        except Exception as e:
            print(f"USM API 執行失敗: {e}")
            import traceback
            traceback.print_exc()

    finally:
        await db.close()
        await usm_db.close()
        print("\n測試結束。")

if __name__ == "__main__":
    asyncio.run(main())