#!/usr/bin/env python3
"""
真實效能測試 - 使用實際可更新的記錄
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
    print("🚀 真實並行更新效能測試")
    print("=" * 60)
    
    try:
        # 設定
        client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
        db = next(get_db())
        team = db.query(Team).first()
        
        if not client.set_wiki_token(team.wiki_token):
            print("❌ 無法設定 wiki_token")
            return 1
        
        # 取得測試記錄 - 找出有 Expected Result 欄位的記錄
        all_records = client.get_all_records(team.test_case_table_id)
        
        test_records = []
        for record in all_records:
            if record.get('fields', {}).get('Expected Result'):
                test_records.append(record)
                if len(test_records) >= 5:  # 只使用 5 筆記錄測試
                    break
        
        if not test_records:
            print("❌ 找不到可測試的記錄")
            return 1
        
        print(f"📦 找到 {len(test_records)} 筆可測試的記錄")
        
        # 保存原始資料
        original_data = []
        for record in test_records:
            original_data.append({
                'record_id': record['record_id'],
                'original_result': record['fields']['Expected Result']
            })
        
        # 準備兩組不同的測試更新
        updates_seq = []
        updates_par = []
        
        for i, record in enumerate(test_records):
            record_id = record['record_id']
            updates_seq.append({
                'record_id': record_id,
                'fields': {'Expected Result': f'[逐筆測試] {time.time()}-{i}'}
            })
            updates_par.append({
                'record_id': record_id,
                'fields': {'Expected Result': f'[並行測試] {time.time()}-{i}'}
            })
        
        print(f"⏱️  開始逐筆更新測試...")
        start_time = time.time()
        
        seq_success = 0
        for update in updates_seq:
            success = client.update_record(
                team.test_case_table_id,
                update['record_id'],
                update['fields']
            )
            if success:
                seq_success += 1
        
        seq_time = time.time() - start_time
        print(f"逐筆更新: {seq_success}/{len(updates_seq)} 成功, 耗時: {seq_time:.2f}秒")
        
        # 等待一下
        time.sleep(1)
        
        print(f"⚡ 開始並行更新測試...")
        start_time = time.time()
        
        success, par_success, errors = client.parallel_update_records(
            team.test_case_table_id,
            updates_par,
            max_workers=3  # 使用較少的工作者避免 API 限制
        )
        
        par_time = time.time() - start_time
        print(f"並行更新: {par_success}/{len(updates_par)} 成功, 耗時: {par_time:.2f}秒")
        
        # 計算效能提升
        if par_time > 0 and seq_success > 0 and par_success > 0:
            speedup = seq_time / par_time
            improvement = (speedup - 1) * 100
            print(f"🎯 效能提升: {speedup:.2f}倍 ({improvement:.1f}%)")
        
        # 恢復原始資料
        print("🔄 恢復原始資料...")
        restore_updates = []
        for data in original_data:
            restore_updates.append({
                'record_id': data['record_id'],
                'fields': {'Expected Result': data['original_result']}
            })
        
        restore_success, restore_count, restore_errors = client.parallel_update_records(
            team.test_case_table_id,
            restore_updates,
            max_workers=3
        )
        
        print(f"資料恢復: {restore_count}/{len(restore_updates)} 成功")
        
        if errors:
            print("⚠️ 並行測試錯誤:")
            for error in errors[:3]:
                print(f"  - {error}")
        
        print("=" * 60)
        print("✅ 測試完成！並行更新功能正常運作")
        
        return 0
        
    except Exception as e:
        logger.error(f"測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)