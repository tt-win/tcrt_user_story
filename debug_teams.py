#!/usr/bin/env python3

import asyncio
import sys
import os

# 添加專案路徑到 Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import init_database, get_async_session
from app.models.database_models import Team
from sqlalchemy import select

async def debug_teams():
    """Debug 檢查資料庫中的團隊"""
    print("🔍 檢查資料庫中的團隊...")
    
    # 初始化資料庫
    await init_database()
    
    try:
        async with get_async_session() as session:
            result = await session.execute(select(Team))
            teams = result.fetchall()
            
            print(f"📊 資料庫中共有 {len(teams)} 個團隊:")
            for team in teams:
                team_obj = team[0]  # 取得 Team 物件
                print(f"  - ID: {team_obj.id}, 名稱: {team_obj.name}")
            
    except Exception as e:
        print(f"❌ 檢查團隊失敗: {e}")

if __name__ == "__main__":
    asyncio.run(debug_teams())