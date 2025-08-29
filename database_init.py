#!/usr/bin/env python3
"""
資料庫初始化腳本

創建測試案例管理系統所需的資料庫表格。
"""

import os
import sys
from pathlib import Path

# 將項目根目錄添加到 Python 路徑中
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine
from app.models.database_models import Base

def init_database():
    """初始化資料庫表格"""
    print("正在創建資料庫表格...")
    
    # 創建所有表格
    Base.metadata.create_all(bind=engine)
    
    print("資料庫表格創建完成！")
    
    # 顯示創建的表格
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    print("\n創建的表格:")
    for table in tables:
        print(f"  - {table}")
        # 檢查並列出重要欄位
        if table == "test_run_items":
            columns = inspector.get_columns(table)
            print(f"    重要欄位:")
            for col in columns:
                if col['name'] in ['id', 'test_case_number', 'bug_tickets_json']:
                    print(f"      - {col['name']} ({col['type']})")
    
    # 執行資料庫結構更新（確保 bug_tickets_json 欄位存在）
    print("\n🔄 檢查資料庫結構更新...")
    try:
        # 動態導入修正檔模組
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "add_bug_tickets_column", 
            "tools/add_bug_tickets_column.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 執行修正檔
        result = module.main()
        if result == 0:
            print("✅ 資料庫結構檢查完成")
        else:
            print("⚠️ 資料庫結構檢查時發現問題，但不影響初始化")
    except Exception as e:
        print(f"⚠️ 注意：無法執行結構檢查 - {e}")
        print("建議手動執行: python tools/add_bug_tickets_column.py")
    
    return True

if __name__ == "__main__":
    init_database()