#!/usr/bin/env python3
"""
測試並行批次更新效能
比較逐筆更新 vs 並行更新的效能差異
"""
import os
import sys
import time
import logging
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent))

from app.services.lark_client import LarkClient
from app.config import settings
from app.database import get_db
from app.models.database_models import Team

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ParallelPerformanceTester:
    """並行更新效能測試器"""
    
    def __init__(self):
        self.client = LarkClient(
            app_id=settings.lark.app_id,
            app_secret=settings.lark.app_secret
        )
        self.test_results = {
            'sequential_time': 0,
            'parallel_time': 0,
            'speedup_ratio': 0,
            'test_count': 0,
            'errors': []
        }
    
    def get_test_data(self) -> tuple[str, str, List[Dict[str, Any]]]:
        """取得測試用資料"""
        try:
            db = next(get_db())
            teams = db.query(Team).filter(Team.test_case_table_id.isnot(None)).limit(1).all()
            if not teams:
                raise Exception("找不到可用的測試團隊")
            
            team = teams[0]
            obj_token = team.wiki_token
            table_id = team.test_case_table_id
            
            if not self.client.set_wiki_token(obj_token):
                raise Exception("無法設定 wiki_token")
            
            # 取得前 10 筆記錄作為測試
            records = self.client.get_all_records(table_id)
            test_records = records[:10] if len(records) >= 10 else records
            
            logger.info(f"取得 {len(test_records)} 筆測試記錄")
            return obj_token, table_id, test_records
            
        except Exception as e:
            logger.error(f"取得測試資料失敗: {e}")
            raise
    
    def prepare_test_updates(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """準備測試更新資料"""
        updates = []
        for record in records:
            record_id = record.get('record_id')
            fields = record.get('fields', {})
            
            # 確保記錄有 Expected Result 欄位才進行測試
            if record_id and 'Expected Result' in fields:
                test_comment = f"[效能測試] {time.time()}"
                updates.append({
                    'record_id': record_id,
                    'fields': {
                        'Expected Result': test_comment
                    }
                })
        
        logger.info(f"準備了 {len(updates)} 筆有效更新資料（從 {len(records)} 筆記錄中篩選）")
        return updates
    
    def test_sequential_updates(self, obj_token: str, table_id: str, updates: List[Dict[str, Any]]) -> float:
        """測試逐筆更新效能"""
        logger.info(f"開始逐筆更新測試 ({len(updates)} 筆記錄)")
        
        start_time = time.time()
        success_count = 0
        
        for update in updates:
            try:
                success = self.client.record_manager.update_record(
                    obj_token, table_id, 
                    update['record_id'], 
                    update['fields']
                )
                if success:
                    success_count += 1
            except Exception as e:
                self.test_results['errors'].append(f"逐筆更新失敗: {str(e)}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"逐筆更新完成: {success_count}/{len(updates)} 成功, 耗時: {duration:.2f}秒")
        return duration
    
    def test_parallel_updates(self, obj_token: str, table_id: str, updates: List[Dict[str, Any]]) -> float:
        """測試並行更新效能"""
        logger.info(f"開始並行更新測試 ({len(updates)} 筆記錄)")
        
        def progress_callback(current, total, success, errors):
            if current % 5 == 0 or current == total:  # 每 5 筆或最後一筆記錄進度
                logger.info(f"進度: {current}/{total} ({current/total*100:.1f}%), 成功: {success}, 錯誤: {errors}")
        
        start_time = time.time()
        
        try:
            success, success_count, error_messages = self.client.record_manager.parallel_update_records(
                obj_token, table_id, updates,
                max_workers=8,
                progress_callback=progress_callback
            )
            
            self.test_results['errors'].extend(error_messages)
            
        except Exception as e:
            self.test_results['errors'].append(f"並行更新失敗: {str(e)}")
            success_count = 0
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"並行更新完成: {success_count}/{len(updates)} 成功, 耗時: {duration:.2f}秒")
        return duration
    
    def restore_original_data(self, obj_token: str, table_id: str, original_records: List[Dict[str, Any]]):
        """恢復原始資料"""
        logger.info("恢復原始資料中...")
        
        updates = []
        for record in original_records:
            record_id = record.get('record_id')
            fields = record.get('fields', {})
            
            if record_id and 'Expected Result' in fields:
                updates.append({
                    'record_id': record_id,
                    'fields': {
                        'Expected Result': fields['Expected Result']
                    }
                })
        
        if updates:
            # 使用並行處理來快速恢復
            try:
                success, success_count, errors = self.client.record_manager.parallel_update_records(
                    obj_token, table_id, updates, max_workers=8
                )
                logger.info(f"資料恢復完成: {success_count}/{len(updates)} 成功")
            except Exception as e:
                logger.error(f"資料恢復失敗: {e}")
    
    def run_performance_test(self) -> Dict[str, Any]:
        """執行完整效能測試"""
        logger.info("開始並行更新效能測試")
        logger.info("=" * 60)
        
        try:
            # 取得測試資料
            obj_token, table_id, test_records = self.get_test_data()
            
            # 準備測試更新資料
            updates = self.prepare_test_updates(test_records)
            if not updates:
                raise Exception("無法準備測試更新資料")
            
            self.test_results['test_count'] = len(updates)
            
            # 保存原始資料用於恢復
            original_records = [record.copy() for record in test_records]
            
            try:
                # 測試 1: 逐筆更新
                sequential_time = self.test_sequential_updates(obj_token, table_id, updates)
                self.test_results['sequential_time'] = sequential_time
                
                # 等待一段時間讓 API 緩衝
                time.sleep(2)
                
                # 修改更新資料，避免重複更新相同內容
                for update in updates:
                    update['fields']['Expected Result'] = f"[並行測試] {time.time()}"
                
                # 測試 2: 並行更新
                parallel_time = self.test_parallel_updates(obj_token, table_id, updates)
                self.test_results['parallel_time'] = parallel_time
                
                # 計算效能提升比例
                if parallel_time > 0:
                    self.test_results['speedup_ratio'] = sequential_time / parallel_time
                
            finally:
                # 恢復原始資料
                self.restore_original_data(obj_token, table_id, original_records)
            
        except Exception as e:
            logger.error(f"效能測試失敗: {e}")
            self.test_results['errors'].append(f"測試執行失敗: {str(e)}")
        
        return self.test_results

def main():
    """主函數"""
    print("🚀 並行更新效能測試")
    print("=" * 60)
    
    try:
        tester = ParallelPerformanceTester()
        results = tester.run_performance_test()
        
        # 輸出測試結果
        print("\n📊 效能測試結果")
        print("=" * 60)
        
        if results['test_count'] > 0:
            print(f"📦 測試記錄數: {results['test_count']}")
            print(f"⏱️  逐筆更新耗時: {results['sequential_time']:.2f} 秒")
            print(f"⚡ 並行更新耗時: {results['parallel_time']:.2f} 秒")
            
            if results['speedup_ratio'] > 0:
                print(f"🎯 效能提升倍數: {results['speedup_ratio']:.2f}x")
                improvement_pct = (results['speedup_ratio'] - 1) * 100
                print(f"📈 效能提升百分比: {improvement_pct:.1f}%")
                
                if results['speedup_ratio'] >= 3:
                    print("✅ 效能提升顯著！建議使用並行更新")
                elif results['speedup_ratio'] >= 2:
                    print("✅ 效能提升良好！建議使用並行更新")
                else:
                    print("⚠️ 效能提升有限，可能受網路或 API 限制影響")
            else:
                print("❌ 無法計算效能提升比例")
        
        if results['errors']:
            print("\n⚠️ 測試過程中的錯誤:")
            for error in results['errors'][:5]:  # 只顯示前5個錯誤
                print(f"  - {error}")
            if len(results['errors']) > 5:
                print(f"  ... 還有 {len(results['errors']) - 5} 個錯誤")
        
        print("\n" + "=" * 60)
        return 0 if results['speedup_ratio'] >= 2 else 1
        
    except Exception as e:
        logger.error(f"測試執行失敗: {e}")
        print(f"\n💥 測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)