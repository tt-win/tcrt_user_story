#!/usr/bin/env python3
"""
簡化的並行更新測試
"""
import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent))

from app.services.lark_client import LarkClient
from app.config import settings
from app.database import get_db
from app.models.database_models import Team

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    print("🔧 簡化並行更新測試")
    print("=" * 50)
    
    try:
        # 設定
        client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
        db = next(get_db())
        team = db.query(Team).first()
        
        if not client.set_wiki_token(team.wiki_token):
            print("❌ 無法設定 wiki_token")
            return 1
        
        # 取得一筆測試記錄
        records = client.get_all_records(team.test_case_table_id)
        if not records:
            print("❌ 無法取得測試記錄")
            return 1
        
        test_record = records[0]
        record_id = test_record['record_id']
        original_result = test_record['fields'].get('Expected Result', '')
        
        print(f"📝 測試記錄: {record_id}")
        print(f"📄 原始內容: {original_result[:30]}...")
        
        # 準備測試更新
        updates = [{
            'record_id': record_id,
            'fields': {
                'Expected Result': f'[並行測試] {time.time()}'
            }
        }]
        
        print(f"🚀 執行並行更新測試...")
        
        # 調用並行更新方法
        success, success_count, errors = client.parallel_update_records(
            team.test_case_table_id, 
            updates,
            max_workers=2
        )
        
        print(f"📊 結果: 成功={success}, 成功數量={success_count}, 錯誤數量={len(errors)}")
        
        if errors:
            print("❌ 錯誤訊息:")
            for error in errors:
                print(f"  - {error}")
        
        # 恢復原始資料
        if success_count > 0:
            print("🔄 恢復原始資料...")
            restore_success = client.update_record(team.test_case_table_id, record_id, {'Expected Result': original_result})
            print(f"復原成功: {restore_success}")
        
        return 0 if success else 1
        
    except Exception as e:
        logger.error(f"測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)