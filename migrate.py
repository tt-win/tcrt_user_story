#!/usr/bin/env python3
"""
資料庫遷移腳本 - 現代化版本
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json

# 將項目根目錄添加到 Python 路徑中
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, MetaData, inspect, text
from sqlalchemy.engine import Engine
from app.database import engine, DATABASE_URL
from app.models.database_models import Base

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DatabaseMigrator:
    """資料庫遷移管理器"""
    
    def __init__(self, engine: Engine):
        self.engine = engine
        self.metadata = MetaData()
        self.inspector = inspect(engine)
        
    def get_current_tables(self) -> List[str]:
        """取得目前資料庫中的表格"""
        return self.inspector.get_table_names()
    
    def get_table_columns(self, table_name: str) -> Dict:
        """取得表格欄位資訊"""
        try:
            columns = self.inspector.get_columns(table_name)
            return {col['name']: col for col in columns}
        except Exception as e:
            logger.warning(f"無法取得表格 {table_name} 的欄位資訊: {e}")
            return {}
    
    def table_exists(self, table_name: str) -> bool:
        """檢查表格是否存在"""
        return table_name in self.get_current_tables()
    
    def column_exists(self, table_name: str, column_name: str) -> bool:
        """檢查欄位是否存在"""
        if not self.table_exists(table_name):
            return False
        columns = self.get_table_columns(table_name)
        return column_name in columns
    
    def backup_database(self, backup_path: Optional[str] = None) -> str:
        """備份資料庫"""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"backup_migration_{timestamp}.db"
        
        logger.info(f"正在備份資料庫到: {backup_path}")
        
        # SQLite 備份
        if "sqlite" in DATABASE_URL.lower():
            import shutil
            db_file = DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
            if os.path.exists(db_file):
                shutil.copy2(db_file, backup_path)
                logger.info(f"✅ 資料庫備份完成: {backup_path}")
                return backup_path
        
        logger.warning("⚠️ 無法自動備份資料庫，請手動備份")
        return ""
    
    def create_migration_info_table(self):
        """創建遷移資訊表格"""
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS migration_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name TEXT NOT NULL UNIQUE,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    description TEXT,
                    success BOOLEAN DEFAULT TRUE
                )
            """))
            conn.commit()
    
    def is_migration_executed(self, migration_name: str) -> bool:
        """檢查遷移是否已執行"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM migration_history WHERE migration_name = :name AND success = 1"),
                    {"name": migration_name}
                )
                return result.scalar() > 0
        except:
            return False
    
    def record_migration(self, migration_name: str, description: str, success: bool = True):
        """記錄遷移執行狀態"""
        with self.engine.connect() as conn:
            conn.execute(text("""
                INSERT OR REPLACE INTO migration_history 
                (migration_name, description, success, executed_at) 
                VALUES (:name, :desc, :success, CURRENT_TIMESTAMP)
            """), {
                "name": migration_name,
                "desc": description,
                "success": success
            })
            conn.commit()
    
    def run_migration_001_initial_schema(self):
        """遷移 001: 初始化資料庫結構"""
        migration_name = "001_initial_schema"
        description = "初始化所有資料庫表格結構"
        
        if self.is_migration_executed(migration_name):
            logger.info(f"⏭️ 遷移 {migration_name} 已執行過，跳過")
            return
        
        logger.info(f"🚀 執行遷移: {migration_name}")
        
        try:
            # 創建所有表格
            Base.metadata.create_all(bind=self.engine)
            
            # 驗證重要表格
            required_tables = [
                'teams', 'test_run_configs', 'test_run_items', 
                'test_run_item_result_history', 'tcg_records',
                'lark_departments', 'lark_users', 'sync_history'
            ]
            
            missing_tables = []
            for table in required_tables:
                if not self.table_exists(table):
                    missing_tables.append(table)
            
            if missing_tables:
                raise Exception(f"以下表格創建失敗: {missing_tables}")
            
            self.record_migration(migration_name, description, True)
            logger.info(f"✅ 遷移 {migration_name} 完成")
            
        except Exception as e:
            logger.error(f"❌ 遷移 {migration_name} 失敗: {e}")
            self.record_migration(migration_name, f"{description} - 失敗: {e}", False)
            raise
    
    def run_migration_002_verify_columns(self):
        """遷移 002: 驗證重要欄位"""
        migration_name = "002_verify_columns"
        description = "驗證所有重要欄位存在"
        
        if self.is_migration_executed(migration_name):
            logger.info(f"⏭️ 遷移 {migration_name} 已執行過，跳過")
            return
        
        logger.info(f"🔍 執行遷移: {migration_name}")
        
        try:
            # 驗證關鍵欄位
            critical_fields = {
                'test_run_items': ['bug_tickets_json', 'assignee_json', 'tcg_json'],
                'test_run_configs': ['related_tp_tickets_json', 'tp_tickets_search'],
                'teams': ['wiki_token', 'test_case_table_id'],
                'lark_users': ['enterprise_email', 'primary_department_id'],
                'lark_departments': ['department_id', 'parent_department_id']
            }
            
            missing_fields = []
            for table_name, fields in critical_fields.items():
                if self.table_exists(table_name):
                    for field in fields:
                        if not self.column_exists(table_name, field):
                            missing_fields.append(f"{table_name}.{field}")
                else:
                    missing_fields.append(f"表格 {table_name} 不存在")
            
            if missing_fields:
                logger.warning(f"⚠️ 缺少欄位: {missing_fields}")
                # 這裡可以根據需要添加修復邏輯
            
            self.record_migration(migration_name, description, True)
            logger.info(f"✅ 遷移 {migration_name} 完成")
            
        except Exception as e:
            logger.error(f"❌ 遷移 {migration_name} 失敗: {e}")
            self.record_migration(migration_name, f"{description} - 失敗: {e}", False)
            raise
    
    def run_migration_003_indexes_constraints(self):
        """遷移 003: 確保索引和約束"""
        migration_name = "003_indexes_constraints"
        description = "創建性能索引和約束"
        
        if self.is_migration_executed(migration_name):
            logger.info(f"⏭️ 遷移 {migration_name} 已執行過，跳過")
            return
        
        logger.info(f"📊 執行遷移: {migration_name}")
        
        try:
            with self.engine.connect() as conn:
                # 創建重要索引（如果不存在）
                indexes = [
                    "CREATE INDEX IF NOT EXISTS ix_test_run_items_config_case ON test_run_items(config_id, test_case_number)",
                    "CREATE INDEX IF NOT EXISTS ix_test_run_items_team_result ON test_run_items(team_id, test_result)",
                    "CREATE INDEX IF NOT EXISTS ix_lark_users_email ON lark_users(enterprise_email)",
                    "CREATE INDEX IF NOT EXISTS ix_lark_users_dept ON lark_users(primary_department_id)",
                    "CREATE INDEX IF NOT EXISTS ix_sync_history_team_time ON sync_history(team_id, start_time)"
                ]
                
                for index_sql in indexes:
                    try:
                        conn.execute(text(index_sql))
                        logger.info(f"  ✓ 索引創建: {index_sql.split('ON')[1].split('(')[0].strip()}")
                    except Exception as e:
                        logger.warning(f"  ⚠️ 索引創建跳過: {e}")
                
                conn.commit()
            
            self.record_migration(migration_name, description, True)
            logger.info(f"✅ 遷移 {migration_name} 完成")
            
        except Exception as e:
            logger.error(f"❌ 遷移 {migration_name} 失敗: {e}")
            self.record_migration(migration_name, f"{description} - 失敗: {e}", False)
            raise
    
    def get_database_stats(self) -> Dict:
        """取得資料庫統計資訊"""
        stats = {
            'tables': len(self.get_current_tables()),
            'table_details': {}
        }
        
        for table in self.get_current_tables():
            try:
                with self.engine.connect() as conn:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                    count = result.scalar()
                    stats['table_details'][table] = {
                        'rows': count,
                        'columns': len(self.get_table_columns(table))
                    }
            except Exception as e:
                stats['table_details'][table] = {'error': str(e)}
        
        return stats
    
    def run_all_migrations(self):
        """執行所有遷移"""
        logger.info("🚀 開始資料庫遷移程序")
        
        # 創建遷移歷史表格
        self.create_migration_info_table()
        
        # 備份資料庫
        backup_file = self.backup_database()
        
        try:
            # 執行所有遷移
            self.run_migration_001_initial_schema()
            self.run_migration_002_verify_columns()
            self.run_migration_003_indexes_constraints()
            
            # 顯示最終統計
            stats = self.get_database_stats()
            logger.info("📊 資料庫統計:")
            logger.info(f"  總表格數: {stats['tables']}")
            for table, details in stats['table_details'].items():
                if 'error' not in details:
                    logger.info(f"  {table}: {details['rows']} 筆記錄, {details['columns']} 欄位")
                else:
                    logger.warning(f"  {table}: 錯誤 - {details['error']}")
            
            logger.info("🎉 所有遷移完成!")
            
        except Exception as e:
            logger.error(f"💥 遷移過程中發生錯誤: {e}")
            if backup_file and os.path.exists(backup_file):
                logger.info(f"🔄 可使用備份檔案恢復: {backup_file}")
            raise

def main():
    """主函數"""
    print("=" * 50)
    print("🗃️  資料庫遷移系統 v2.0")
    print("=" * 50)
    
    migrator = DatabaseMigrator(engine)
    
    try:
        migrator.run_all_migrations()
        print("\n✅ 遷移程序成功完成!")
        print(f"📂 資料庫位置: {DATABASE_URL}")
        
    except Exception as e:
        print(f"\n❌ 遷移程序失敗: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()