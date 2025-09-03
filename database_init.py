#!/usr/bin/env python3
"""
資料庫初始化腳本 - 現代化版本

使用新的遷移系統來安全地初始化和更新資料庫結構。
此腳本是 migrate.py 的簡化封裝，專門用於快速初始化。
"""

import os
import sys
from pathlib import Path

# 將項目根目錄添加到 Python 路徑中
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine

def init_database():
    """使用現代化遷移系統初始化資料庫"""
    print("=" * 50)
    print("🗃️  資料庫初始化系統 (基於現代化遷移)")
    print("=" * 50)
    
    try:
        # 導入現代化遷移系統
        from migrate import DatabaseMigrator
        
        # 創建遷移器
        migrator = DatabaseMigrator(engine)
        
        print("🚀 開始資料庫初始化...")
        
        # 執行所有遷移
        migrator.run_all_migrations()
        
        # 顯示最終統計
        print("\n📊 初始化完成統計:")
        stats = migrator.get_database_stats()
        print(f"  總表格數: {stats['tables']}")
        
        # 顯示重要表格的詳細資訊
        important_tables = ['teams', 'test_run_configs', 'test_run_items', 
                          'test_run_item_result_history', 'lark_users', 'lark_departments']
        
        print("\n重要表格狀態:")
        for table in important_tables:
            if table in stats['table_details']:
                details = stats['table_details'][table]
                if 'error' not in details:
                    print(f"  ✅ {table}: {details['rows']} 筆記錄, {details['columns']} 欄位")
                else:
                    print(f"  ❌ {table}: {details['error']}")
            else:
                print(f"  ⚠️ {table}: 表格不存在")
        
        print("\n✅ 資料庫初始化完成!")
        print(f"📂 資料庫位置: {engine.url}")
        print("\n💡 提示:")
        print("  - 使用 'python migrate.py' 來執行完整的遷移程序")
        print("  - 遷移歷史記錄保存在 migration_history 表格中")
        
        return True
        
    except ImportError as e:
        print(f"❌ 無法導入遷移系統: {e}")
        print("請確保 migrate.py 文件存在且可以正常運行")
        return False
        
    except Exception as e:
        print(f"❌ 初始化過程中發生錯誤: {e}")
        print("\n🔄 回退選項:")
        print("  - 檢查資料庫連接是否正常")
        print("  - 使用 'python migrate.py' 來診斷問題")
        return False

def legacy_init():
    """舊版本的簡單初始化方法（僅用於緊急情況）"""
    print("⚠️ 使用舊版本初始化方法...")
    
    from app.models.database_models import Base
    Base.metadata.create_all(bind=engine)
    
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    print(f"創建了 {len(tables)} 個表格:")
    for table in tables:
        print(f"  - {table}")
    
    print("⚠️ 注意: 舊版本不包含遷移追蹤和備份功能")

if __name__ == "__main__":
    success = init_database()
    if not success:
        print("\n🆘 如果需要緊急初始化，可以嘗試:")
        print("   python -c \"from database_init import legacy_init; legacy_init()\"")
        sys.exit(1)