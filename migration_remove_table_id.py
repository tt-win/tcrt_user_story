#!/usr/bin/env python3
"""
資料庫遷移腳本：移除 test_run_configs 表格中的 table_id 欄位

此腳本將：
1. 備份現有的 test_run_configs 資料
2. 移除 table_id 欄位
3. 提供回滾機制

執行方式：
    python migration_remove_table_id.py [--rollback]

注意：執行前請備份整個資料庫檔案
"""

import sqlite3
import json
import argparse
import sys
from datetime import datetime
from pathlib import Path

# 設定檔案路徑
DB_PATH = "test_case_repo.db"
BACKUP_FILE = f"migration_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def backup_table_data(cursor):
    """備份 test_run_configs 表格資料"""
    print("正在備份 test_run_configs 表格資料...")
    
    cursor.execute("SELECT * FROM test_run_configs")
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    
    backup_data = {
        'columns': columns,
        'rows': [dict(zip(columns, row)) for row in rows],
        'backup_time': datetime.now().isoformat(),
        'table_name': 'test_run_configs'
    }
    
    with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"備份完成：{len(rows)} 筆記錄已儲存至 {BACKUP_FILE}")
    return backup_data

def migrate_forward(cursor):
    """執行前向遷移：移除 table_id 欄位"""
    print("開始執行前向遷移...")
    
    # 備份資料
    backup_data = backup_table_data(cursor)
    
    # 檢查是否存在 table_id 欄位
    cursor.execute("PRAGMA table_info(test_run_configs)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    if 'table_id' not in column_names:
        print("table_id 欄位不存在，跳過遷移")
        return True
    
    print("正在移除 table_id 欄位...")
    
    # 建立新表格（不含 table_id）
    cursor.execute("""
        CREATE TABLE test_run_configs_new (
            id INTEGER NOT NULL, 
            team_id INTEGER NOT NULL, 
            name VARCHAR(100) NOT NULL, 
            description TEXT, 
            test_version VARCHAR(50), 
            test_environment VARCHAR(100), 
            build_number VARCHAR(100), 
            status VARCHAR(9), 
            start_date DATETIME, 
            end_date DATETIME, 
            total_test_cases INTEGER, 
            executed_cases INTEGER, 
            passed_cases INTEGER, 
            failed_cases INTEGER, 
            created_at DATETIME, 
            updated_at DATETIME, 
            last_sync_at DATETIME, 
            PRIMARY KEY (id), 
            FOREIGN KEY(team_id) REFERENCES teams (id)
        )
    """)
    
    # 複製資料（排除 table_id）
    cursor.execute("""
        INSERT INTO test_run_configs_new (
            id, team_id, name, description, test_version, test_environment, 
            build_number, status, start_date, end_date, total_test_cases, 
            executed_cases, passed_cases, failed_cases, created_at, 
            updated_at, last_sync_at
        )
        SELECT 
            id, team_id, name, description, test_version, test_environment, 
            build_number, status, start_date, end_date, total_test_cases, 
            executed_cases, passed_cases, failed_cases, created_at, 
            updated_at, last_sync_at
        FROM test_run_configs
    """)
    
    # 刪除舊表格
    cursor.execute("DROP TABLE test_run_configs")
    
    # 重新命名新表格
    cursor.execute("ALTER TABLE test_run_configs_new RENAME TO test_run_configs")
    
    # 重建索引
    cursor.execute("CREATE INDEX ix_test_run_configs_id ON test_run_configs (id)")
    
    print("遷移完成：已移除 table_id 欄位")
    return True

def migrate_rollback(cursor, backup_file=None):
    """執行回滾：還原 table_id 欄位"""
    print("開始執行回滾...")
    
    if not backup_file:
        # 尋找最新的備份檔案
        backup_files = list(Path('.').glob('migration_backup_*.json'))
        if not backup_files:
            print("錯誤：找不到備份檔案")
            return False
        backup_file = max(backup_files, key=lambda f: f.stat().st_mtime)
    
    print(f"使用備份檔案：{backup_file}")
    
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
    except FileNotFoundError:
        print(f"錯誤：備份檔案 {backup_file} 不存在")
        return False
    
    # 刪除現有表格
    cursor.execute("DROP TABLE IF EXISTS test_run_configs")
    
    # 重建原始表格結構
    cursor.execute("""
        CREATE TABLE test_run_configs (
            id INTEGER NOT NULL, 
            team_id INTEGER NOT NULL, 
            name VARCHAR(100) NOT NULL, 
            description TEXT, 
            table_id VARCHAR(255), 
            test_version VARCHAR(50), 
            test_environment VARCHAR(100), 
            build_number VARCHAR(100), 
            status VARCHAR(9), 
            start_date DATETIME, 
            end_date DATETIME, 
            total_test_cases INTEGER, 
            executed_cases INTEGER, 
            passed_cases INTEGER, 
            failed_cases INTEGER, 
            created_at DATETIME, 
            updated_at DATETIME, 
            last_sync_at DATETIME, 
            PRIMARY KEY (id), 
            FOREIGN KEY(team_id) REFERENCES teams (id)
        )
    """)
    
    # 還原資料
    if backup_data['rows']:
        placeholders = ', '.join(['?' for _ in backup_data['columns']])
        insert_sql = f"INSERT INTO test_run_configs ({', '.join(backup_data['columns'])}) VALUES ({placeholders})"
        
        for row in backup_data['rows']:
            values = [row.get(col) for col in backup_data['columns']]
            cursor.execute(insert_sql, values)
    
    # 重建索引
    cursor.execute("CREATE INDEX ix_test_run_configs_id ON test_run_configs (id)")
    
    print(f"回滾完成：已還原 {len(backup_data['rows'])} 筆記錄")
    return True

def main():
    parser = argparse.ArgumentParser(description='Test Run Config Table ID 遷移工具')
    parser.add_argument('--rollback', action='store_true', help='執行回滾操作')
    parser.add_argument('--backup-file', help='指定回滾時使用的備份檔案')
    args = parser.parse_args()
    
    if not Path(DB_PATH).exists():
        print(f"錯誤：資料庫檔案 {DB_PATH} 不存在")
        sys.exit(1)
    
    print(f"連接資料庫：{DB_PATH}")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if args.rollback:
            success = migrate_rollback(cursor, args.backup_file)
        else:
            success = migrate_forward(cursor)
        
        if success:
            conn.commit()
            print("遷移成功完成")
        else:
            conn.rollback()
            print("遷移失敗，已回滾")
            sys.exit(1)
            
    except Exception as e:
        print(f"錯誤：{e}")
        if 'conn' in locals():
            conn.rollback()
        sys.exit(1)
    
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main()