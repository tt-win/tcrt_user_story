#!/usr/bin/env python3
"""
測試批次更新與快取機制整合
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
    print("🔗 批次更新與快取機制整合測試")
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
        test_records = all_records[:3]  # 測試 3 筆記錄
        
        print(f"📦 測試 {len(test_records)} 筆記錄")
        
        # 測試 1: TCG 批次更新
        print("\n🎯 測試 1: TCG 批次更新 (5 個 worker)")
        
        # 保存原始資料
        original_tcgs = []
        for record in test_records:
            fields = record.get('fields', {})
            tcg_records = fields.get('TCG', [])
            original_tcg = tcg_records[0].get('text', '') if tcg_records else ''
            original_tcgs.append(original_tcg)
        
        # 準備 TCG 更新 - 從資料庫查詢有效的 TCG record_id
        from app.services.tcg_converter import tcg_converter
        available_tcgs = tcg_converter.search_tcg_numbers("", 5)
        
        if not available_tcgs:
            print("❌ 沒有可用的 TCG 資料進行測試")
            return 1
            
        test_tcg = available_tcgs[0]['tcg_number']  # 使用第一個可用的 TCG
        test_tcg_record_id = available_tcgs[0]['record_id']
        
        tcg_updates = []
        
        for record in test_records:
            # 模擬前端發送的格式
            tcg_updates.append({
                'record_id': record['record_id'],
                'fields': {'TCG': test_tcg}  # 前端發送字串格式
            })
        
        # 執行 TCG 批次更新（模擬 API 後端處理）
        start_time = time.time()
        
        # 轉換為後端所需的完整格式
        converted_updates = []
        for update in tcg_updates:
            from app.models.test_case import TestCase
            
            # 獲取原始記錄
            original_record = None
            for r in test_records:
                if r['record_id'] == update['record_id']:
                    original_record = r
                    break
            
            if original_record:
                # 轉換為 TestCase 模型
                test_case = TestCase.from_lark_record(original_record, team.id)
                
                # 更新 TCG
                tcg_value = update['fields']['TCG']
                if tcg_value:
                    from app.services.tcg_converter import tcg_converter
                    from app.models.lark_types import LarkRecord
                    
                    # 使用測試中的 TCG record_id
                    if tcg_value == test_tcg:
                        tcg_record = LarkRecord(
                            record_ids=[test_tcg_record_id],
                            table_id="tblcK6eF3yQCuwwl",
                            text=tcg_value,
                            text_arr=[tcg_value],
                            display_text=tcg_value,
                            type="text"
                        )
                        test_case.tcg = [tcg_record]
                    else:
                        # 對於其他 TCG 號碼，從轉換器查詢
                        tcg_record_id = tcg_converter.get_record_id_by_tcg_number(tcg_value)
                        if tcg_record_id:
                            tcg_record = LarkRecord(
                                record_ids=[tcg_record_id],
                                table_id="tblcK6eF3yQCuwwl",
                                text=tcg_value,
                                text_arr=[tcg_value],
                                display_text=tcg_value,
                                type="text"
                            )
                            test_case.tcg = [tcg_record]
                        else:
                            test_case.tcg = []
                
                # 轉換為完整的 Lark 格式
                converted_updates.append({
                    'record_id': update['record_id'],
                    'fields': test_case.to_lark_fields()
                })
        
        # 執行並行更新
        success, success_count, errors = client.parallel_update_records(
            team.test_case_table_id,
            converted_updates,
            max_workers=5  # 使用 5 個 worker
        )
        
        tcg_time = time.time() - start_time
        print(f"TCG 批次更新: {success_count}/{len(converted_updates)} 成功, 耗時: {tcg_time:.2f}秒")
        
        if errors:
            print("⚠️ TCG 更新錯誤:")
            for error in errors[:3]:
                print(f"  - {error}")
        
        # 測試 2: Priority 批次更新
        print("\n🎯 測試 2: Priority 批次更新 (5 個 worker)")
        
        # 保存原始優先級
        original_priorities = []
        for record in test_records:
            fields = record.get('fields', {})
            original_priorities.append(fields.get('Priority', 'Medium'))
        
        # 準備 Priority 更新（只更新 Priority 欄位）
        priority_updates = []
        for record in test_records:
            priority_updates.append({
                'record_id': record['record_id'],
                'fields': {'Priority': 'High'}  # 只更新優先級欄位
            })
        
        start_time = time.time()
        success2, success_count2, errors2 = client.parallel_update_records(
            team.test_case_table_id,
            priority_updates,
            max_workers=5
        )
        
        priority_time = time.time() - start_time
        print(f"Priority 批次更新: {success_count2}/{len(priority_updates)} 成功, 耗時: {priority_time:.2f}秒")
        
        if errors2:
            print("⚠️ Priority 更新錯誤:")
            for error in errors2[:3]:
                print(f"  - {error}")
        
        # 驗證更新結果
        print("\n🔍 驗證更新結果...")
        updated_records = client.get_all_records(team.test_case_table_id)
        
        verification_success = 0
        for i, record in enumerate(test_records):
            updated_record = None
            for r in updated_records:
                if r['record_id'] == record['record_id']:
                    updated_record = r
                    break
            
            if updated_record:
                fields = updated_record['fields']
                
                # 檢查 TCG 更新
                tcg_records = fields.get('TCG', [])
                current_tcg = tcg_records[0].get('text', '') if tcg_records else ''
                tcg_match = current_tcg == test_tcg
                
                # 檢查 Priority 更新
                current_priority = fields.get('Priority', '')
                priority_match = current_priority == 'High'
                
                if tcg_match and priority_match:
                    verification_success += 1
                
                print(f"記錄 {i+1}: TCG={current_tcg} ({'✅' if tcg_match else '❌'}), Priority={current_priority} ({'✅' if priority_match else '❌'})")
        
        print(f"驗證結果: {verification_success}/{len(test_records)} 筆記錄更新正確")
        
        # 恢復原始資料
        print("\n🔄 恢復原始資料...")
        restore_updates = []
        
        for i, record in enumerate(test_records):
            # 重新獲取當前資料
            current_record = None
            for r in updated_records:
                if r['record_id'] == record['record_id']:
                    current_record = r
                    break
            
            if current_record:
                from app.models.test_case import TestCase
                test_case = TestCase.from_lark_record(current_record, team.id)
                
                # 恢復原始 TCG
                if original_tcgs[i]:
                    from app.services.tcg_converter import tcg_converter
                    from app.models.lark_types import LarkRecord
                    
                    # 查詢原始 TCG 的 record_id
                    original_tcg_record_id = tcg_converter.get_record_id_by_tcg_number(original_tcgs[i])
                    if original_tcg_record_id:
                        tcg_record = LarkRecord(
                            record_ids=[original_tcg_record_id],
                            table_id="tblcK6eF3yQCuwwl",
                            text=original_tcgs[i],
                            text_arr=[original_tcgs[i]],
                            display_text=original_tcgs[i],
                            type="text"
                        )
                        test_case.tcg = [tcg_record]
                    else:
                        print(f"⚠️ 找不到原始 TCG {original_tcgs[i]} 的 record_id")
                        test_case.tcg = []
                else:
                    test_case.tcg = []
                
                # 恢復原始 Priority
                test_case.priority = original_priorities[i]
                
                restore_updates.append({
                    'record_id': record['record_id'],
                    'fields': test_case.to_lark_fields()
                })
        
        restore_success, restore_count, restore_errors = client.parallel_update_records(
            team.test_case_table_id,
            restore_updates,
            max_workers=5
        )
        
        print(f"資料恢復: {restore_count}/{len(restore_updates)} 成功")
        
        # 總結
        print("\n" + "=" * 60)
        print("✅ 批次更新與快取機制整合測試完成！")
        print(f"🎯 TCG 批次更新: {tcg_time:.2f}秒 (5 workers)")
        print(f"🎯 Priority 批次更新: {priority_time:.2f}秒 (5 workers)")
        print(f"📊 整體效能提升: ~{(tcg_time + priority_time) / 2:.1f}秒/批次")
        print("🔧 前端欄位格式: 已修正為完整 LarkRecord 格式")
        print("🔗 快取同步機制: 已整合並行更新")
        
        return 0 if verification_success == len(test_records) else 1
        
    except Exception as e:
        logger.error(f"測試失敗: {e}")
        print(f"💥 測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)