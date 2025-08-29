#!/usr/bin/env python3
"""
安全的並行更新測試 - 使用完整的 TestCase 模型避免資料丟失
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
from app.models.test_case import TestCase

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    print("🔒 安全的並行更新測試")
    print("=" * 60)
    
    try:
        # 設定
        client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
        db = next(get_db())
        team = db.query(Team).first()
        
        if not client.set_wiki_token(team.wiki_token):
            print("❌ 無法設定 wiki_token")
            return 1
        
        # 取得測試記錄
        all_records = client.get_all_records(team.test_case_table_id)
        test_records = all_records[:3]  # 只測試 3 筆
        
        print(f"📦 測試 {len(test_records)} 筆記錄")
        
        # 保存原始 Expected Result
        original_results = []
        safe_updates = []
        
        for record in test_records:
            record_id = record['record_id']
            
            # 轉換成 TestCase 模型
            test_case = TestCase.from_lark_record(record, team.id)
            original_results.append({
                'record_id': record_id,
                'original_expected_result': test_case.expected_result
            })
            
            # 安全地修改只有 expected_result 欄位
            test_case.expected_result = f'[安全並行測試] {time.time()}'
            
            # 使用完整的欄位資料進行更新
            safe_updates.append({
                'record_id': record_id,
                'fields': test_case.to_lark_fields()  # 使用完整欄位避免資料丟失
            })
        
        print("🚀 開始安全並行更新...")
        start_time = time.time()
        
        success, success_count, errors = client.parallel_update_records(
            team.test_case_table_id,
            safe_updates,
            max_workers=3
        )
        
        duration = time.time() - start_time
        print(f"✅ 並行更新完成: {success_count}/{len(safe_updates)} 成功, 耗時: {duration:.2f}秒")
        
        if errors:
            print("⚠️ 錯誤訊息:")
            for error in errors:
                print(f"  - {error}")
        
        # 恢復原始資料
        if success_count > 0:
            print("🔄 恢復原始資料...")
            restore_updates = []
            
            # 重新取得當前資料
            current_records = client.get_all_records(team.test_case_table_id)
            for original in original_results:
                # 找到對應記錄
                current_record = None
                for r in current_records:
                    if r['record_id'] == original['record_id']:
                        current_record = r
                        break
                
                if current_record:
                    # 安全地恢復資料
                    test_case = TestCase.from_lark_record(current_record, team.id)
                    test_case.expected_result = original['original_expected_result']
                    
                    restore_updates.append({
                        'record_id': original['record_id'],
                        'fields': test_case.to_lark_fields()
                    })
            
            restore_success, restore_count, restore_errors = client.parallel_update_records(
                team.test_case_table_id,
                restore_updates,
                max_workers=3
            )
            
            print(f"復原完成: {restore_count}/{len(restore_updates)} 成功")
        
        print("=" * 60)
        print("✅ 安全並行更新測試完成！")
        
        return 0 if success else 1
        
    except Exception as e:
        logger.error(f"測試失敗: {e}")
        print(f"💥 測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)