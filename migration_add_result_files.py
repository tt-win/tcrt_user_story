"""
資料庫遷移腳本 - 為 TestRunItem 表格添加結果檔案追蹤欄位

新增欄位：
- result_files_uploaded: Boolean (預設 False)
- result_files_count: Integer (預設 0)  
- upload_history_json: Text (可為空)
"""

import sqlite3
import os
from datetime import datetime

def migrate_add_result_files():
    """為 TestRunItem 表格添加結果檔案追蹤欄位"""
    
    db_path = "./test_case_repo.db"
    
    # 檢查資料庫檔案是否存在
    if not os.path.exists(db_path):
        print(f"❌ 資料庫檔案不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("🔍 檢查當前 test_run_items 表格結構...")
        
        # 檢查表格是否存在
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='test_run_items'
        """)
        
        if not cursor.fetchone():
            print("❌ test_run_items 表格不存在")
            return False
        
        # 檢查欄位是否已經存在
        cursor.execute("PRAGMA table_info(test_run_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        print(f"📋 目前欄位: {', '.join(columns)}")
        
        new_columns_to_add = []
        
        # 檢查需要添加的欄位
        if 'result_files_uploaded' not in columns:
            new_columns_to_add.append(('result_files_uploaded', 'INTEGER DEFAULT 0 NOT NULL'))
        
        if 'result_files_count' not in columns:
            new_columns_to_add.append(('result_files_count', 'INTEGER DEFAULT 0 NOT NULL'))
        
        if 'upload_history_json' not in columns:
            new_columns_to_add.append(('upload_history_json', 'TEXT'))
        
        if not new_columns_to_add:
            print("✅ 所有需要的欄位都已存在，無需遷移")
            return True
        
        print(f"➕ 需要添加的欄位: {[col[0] for col in new_columns_to_add]}")
        
        # 執行欄位添加
        for column_name, column_def in new_columns_to_add:
            sql = f"ALTER TABLE test_run_items ADD COLUMN {column_name} {column_def}"
            print(f"📝 執行 SQL: {sql}")
            cursor.execute(sql)
        
        # 創建新的索引
        try:
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS ix_test_run_items_files_uploaded 
                ON test_run_items (result_files_uploaded)
            """)
            print("📝 創建索引: ix_test_run_items_files_uploaded")
        except Exception as e:
            print(f"⚠️ 索引創建警告: {e}")
        
        # 提交變更
        conn.commit()
        
        # 驗證變更
        cursor.execute("PRAGMA table_info(test_run_items)")
        updated_columns = [row[1] for row in cursor.fetchall()]
        
        print("✅ 遷移完成！")
        print(f"📋 更新後欄位: {', '.join(updated_columns)}")
        
        # 檢查表格行數
        cursor.execute("SELECT COUNT(*) FROM test_run_items")
        row_count = cursor.fetchone()[0]
        print(f"📊 表格記錄數: {row_count}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 遷移失敗: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

def validate_migration():
    """驗證遷移結果"""
    db_path = "./test_case_repo.db"
    
    if not os.path.exists(db_path):
        print(f"❌ 資料庫檔案不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 檢查新欄位
        cursor.execute("PRAGMA table_info(test_run_items)")
        columns_info = cursor.fetchall()
        
        required_columns = ['result_files_uploaded', 'result_files_count', 'upload_history_json']
        found_columns = []
        
        for col_info in columns_info:
            col_name = col_info[1]
            if col_name in required_columns:
                found_columns.append(col_name)
                print(f"✅ 欄位存在: {col_name} ({col_info[2]})")
        
        missing_columns = set(required_columns) - set(found_columns)
        if missing_columns:
            print(f"❌ 缺少欄位: {missing_columns}")
            return False
        
        # 檢查索引
        cursor.execute("PRAGMA index_list(test_run_items)")
        indexes = cursor.fetchall()
        
        has_files_index = any('files_uploaded' in idx[1] for idx in indexes)
        if has_files_index:
            print("✅ 索引存在: ix_test_run_items_files_uploaded")
        else:
            print("⚠️ 索引缺失: ix_test_run_items_files_uploaded")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ 驗證失敗: {e}")
        return False

if __name__ == "__main__":
    print("🚀 開始 TestRunItem 結果檔案追蹤欄位遷移...")
    print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if migrate_add_result_files():
        print("\n🔍 執行遷移驗證...")
        if validate_migration():
            print("\n🎉 遷移與驗證完成！")
        else:
            print("\n⚠️ 遷移完成但驗證有問題，請檢查")
    else:
        print("\n❌ 遷移失敗")
    
    print(f"⏰ 結束時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")