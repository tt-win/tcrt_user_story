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
    
    return True

if __name__ == "__main__":
    init_database()