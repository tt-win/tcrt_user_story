#!/usr/bin/env python3
"""
測試 Lark API 批次更新功能
確認 API 端點是否存在及其請求格式
"""
import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

# 加入專案路徑
sys.path.insert(0, str(Path(__file__).parent))

from app.services.lark_client import LarkClient
from app.config import settings
from app.database import get_db
from app.models.database_models import Team

# 設定日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LarkBatchUpdateTester:
    """Lark 批次更新測試器"""
    
    def __init__(self):
        self.client = LarkClient(
            app_id=settings.lark.app_id,
            app_secret=settings.lark.app_secret
        )
        self.test_results = {
            'batch_update_supported': False,
            'api_endpoint': None,
            'http_method': None,
            'request_format': None,
            'max_batch_size': None,
            'error_messages': []
        }
    
    def get_test_team_and_table(self) -> tuple[Optional[str], Optional[str]]:
        """取得測試用的團隊和表格 ID"""
        try:
            db = next(get_db())
            teams = db.query(Team).filter(Team.test_case_table_id.isnot(None)).limit(1).all()
            if teams:
                team = teams[0]
                # 直接使用資料庫中的 wiki_token 和 table_id
                if team.wiki_token and team.test_case_table_id:
                    obj_token = team.wiki_token
                    table_id = team.test_case_table_id
                    logger.info(f"找到測試團隊: {team.name}")
                    logger.info(f"Obj Token: {obj_token}")
                    logger.info(f"Table ID: {table_id}")
                    return obj_token, table_id
            
            logger.warning("未找到可用的測試團隊或無法解析表格資訊")
            return None, None
            
        except Exception as e:
            logger.error(f"取得測試團隊失敗: {e}")
            return None, None
    
    def get_sample_records(self, obj_token: str, table_id: str, limit: int = 2) -> List[Dict[str, Any]]:
        """取得樣本記錄用於測試"""
        try:
            # 使用正確的方式設置 wiki_token
            if not self.client.set_wiki_token(obj_token):
                logger.error("無法設定 wiki_token")
                return []
            records = self.client.get_all_records(table_id)
            if records and len(records) >= limit:
                sample_records = records[:limit]
                logger.info(f"取得 {len(sample_records)} 筆樣本記錄")
                return sample_records
            else:
                logger.warning(f"記錄數量不足，僅有 {len(records) if records else 0} 筆")
                return records[:limit] if records else []
                
        except Exception as e:
            logger.error(f"取得樣本記錄失敗: {e}")
            return []
    
    def create_test_updates(self, sample_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """建立測試用的更新資料"""
        updates = []
        
        for i, record in enumerate(sample_records):
            record_id = record.get('record_id')
            if not record_id:
                continue
                
            # 建立測試更新資料（僅更新安全的欄位）
            test_update = {
                'record_id': record_id,
                'fields': {
                    # 僅更新註解欄位，避免影響重要資料
                    'fldvQT4eUb': f'[測試] 批次更新測試 #{i+1} - {json.dumps({"timestamp": "test", "batch_update": True})}'
                }
            }
            updates.append(test_update)
        
        logger.info(f"建立 {len(updates)} 筆測試更新資料")
        return updates
    
    def test_batch_update_endpoint(self, obj_token: str, table_id: str, updates: List[Dict[str, Any]]) -> bool:
        """測試批次更新端點"""
        test_scenarios = [
            {
                'method': 'POST',
                'endpoint': f"/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_update",
                'data_format': {'records': updates}
            },
            {
                'method': 'PUT', 
                'endpoint': f"/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_update",
                'data_format': {'records': updates}
            },
            {
                'method': 'PATCH',
                'endpoint': f"/bitable/v1/apps/{obj_token}/tables/{table_id}/records/batch_update", 
                'data_format': {'records': updates}
            }
        ]
        
        for scenario in test_scenarios:
            logger.info(f"測試 {scenario['method']} {scenario['endpoint']}")
            
            try:
                url = self.client.record_manager.base_url + scenario['endpoint']
                
                # 使用 Record Manager 的 _make_request 方法
                if scenario['method'] == 'POST':
                    response = self.client.record_manager._make_request('POST', url, json=scenario['data_format'])
                elif scenario['method'] == 'PUT':
                    response = self.client.record_manager._make_request('PUT', url, json=scenario['data_format'])
                elif scenario['method'] == 'PATCH':
                    response = self.client.record_manager._make_request('PATCH', url, json=scenario['data_format'])
                
                if response:
                    logger.info(f"✅ 成功！{scenario['method']} 方法有效")
                    logger.info(f"回應: {json.dumps(response, indent=2, ensure_ascii=False)}")
                    
                    # 記錄成功的配置
                    self.test_results.update({
                        'batch_update_supported': True,
                        'api_endpoint': scenario['endpoint'],
                        'http_method': scenario['method'],
                        'request_format': scenario['data_format'],
                        'max_batch_size': len(updates)
                    })
                    return True
                    
            except Exception as e:
                error_msg = f"{scenario['method']} 失敗: {str(e)}"
                logger.warning(error_msg)
                self.test_results['error_messages'].append(error_msg)
                continue
        
        return False
    
    def test_batch_size_limits(self, obj_token: str, table_id: str, base_update: Dict[str, Any]) -> int:
        """測試批次大小限制"""
        if not self.test_results['batch_update_supported']:
            return 0
        
        test_sizes = [1, 10, 50, 100, 500, 1000]
        max_working_size = 0
        
        for size in test_sizes:
            logger.info(f"測試批次大小: {size}")
            
            # 建立測試資料
            test_updates = []
            for i in range(size):
                update = {
                    'record_id': base_update['record_id'],  # 使用相同記錄ID
                    'fields': {
                        'fldvQT4eUb': f'[測試] 批次大小測試 {size} 筆 #{i+1}'
                    }
                }
                test_updates.append(update)
            
            try:
                url = self.client.record_manager.base_url + self.test_results['api_endpoint']
                data = {'records': test_updates}
                response = self.client.record_manager._make_request(self.test_results['http_method'], url, json=data)
                
                if response:
                    max_working_size = size
                    logger.info(f"✅ 批次大小 {size} 測試成功")
                else:
                    logger.warning(f"❌ 批次大小 {size} 測試失敗")
                    break
                    
            except Exception as e:
                logger.warning(f"❌ 批次大小 {size} 測試失敗: {e}")
                break
        
        self.test_results['max_batch_size'] = max_working_size
        return max_working_size
    
    def rollback_test_changes(self, obj_token: str, table_id: str, original_records: List[Dict[str, Any]]):
        """回滾測試變更"""
        logger.info("開始回滾測試變更...")
        
        try:
            rollback_updates = []
            for record in original_records:
                record_id = record.get('record_id')
                fields = record.get('fields', {})
                
                if record_id and 'fldvQT4eUb' in fields:
                    rollback_updates.append({
                        'record_id': record_id,
                        'fields': {
                            'fldvQT4eUb': fields['fldvQT4eUb']  # 恢復原始值
                        }
                    })
            
            if rollback_updates and self.test_results['batch_update_supported']:
                url = self.client.record_manager.base_url + self.test_results['api_endpoint']
                data = {'records': rollback_updates}
                response = self.client.record_manager._make_request(self.test_results['http_method'], url, json=data)
                
                if response:
                    logger.info("✅ 測試變更回滾成功")
                else:
                    logger.warning("⚠️ 測試變更回滾失敗，請手動檢查")
            else:
                logger.info("無需回滾或批次更新不支援")
                
        except Exception as e:
            logger.error(f"回滾測試變更失敗: {e}")
    
    def run_full_test(self) -> Dict[str, Any]:
        """執行完整測試"""
        logger.info("開始 Lark API 批次更新測試")
        logger.info("=" * 60)
        
        # 1. 取得測試環境
        obj_token, table_id = self.get_test_team_and_table()
        if not obj_token or not table_id:
            self.test_results['error_messages'].append("無法取得測試環境")
            return self.test_results
        
        # 2. 取得樣本記錄
        sample_records = self.get_sample_records(obj_token, table_id, limit=3)
        if not sample_records:
            self.test_results['error_messages'].append("無法取得樣本記錄")
            return self.test_results
        
        # 保存原始記錄用於回滾
        original_records = [record.copy() for record in sample_records]
        
        # 3. 建立測試更新
        test_updates = self.create_test_updates(sample_records)
        if not test_updates:
            self.test_results['error_messages'].append("無法建立測試更新資料")
            return self.test_results
        
        try:
            # 4. 測試批次更新端點
            logger.info("步驟 1: 測試批次更新 API 端點")
            if self.test_batch_update_endpoint(obj_token, table_id, test_updates):
                logger.info("✅ 批次更新 API 存在且可用")
                
                # 5. 測試批次大小限制
                logger.info("步驟 2: 測試批次大小限制")
                max_size = self.test_batch_size_limits(obj_token, table_id, test_updates[0])
                logger.info(f"最大批次大小: {max_size}")
                
            else:
                logger.info("❌ 批次更新 API 不存在或不可用")
                
        finally:
            # 6. 回滾測試變更
            self.rollback_test_changes(obj_token, table_id, original_records)
        
        return self.test_results

def main():
    """主函數"""
    print("🧪 Lark API 批次更新測試腳本")
    print("=" * 60)
    
    try:
        tester = LarkBatchUpdateTester()
        results = tester.run_full_test()
        
        # 輸出測試結果
        print("\n📊 測試結果摘要")
        print("=" * 60)
        
        if results['batch_update_supported']:
            print("✅ Lark 支援批次更新功能")
            print(f"📡 API 端點: {results['api_endpoint']}")
            print(f"🔧 HTTP 方法: {results['http_method']}")
            print(f"📦 最大批次大小: {results['max_batch_size']}")
            print(f"📋 請求格式: {json.dumps(results['request_format'], indent=2, ensure_ascii=False)}")
            
            print("\n🚀 建議實作:")
            print("1. 在 lark_client.py 中實作 batch_update_records 方法")
            print("2. 使用上述 API 端點和請求格式")
            print("3. 批次處理時每批不超過", results['max_batch_size'], "筆記錄")
            print("4. 預期效能提升: 10-50 倍")
            
        else:
            print("❌ Lark 不支援批次更新功能")
            print("🔧 建議優化方案:")
            print("1. 使用並行處理優化逐筆更新")
            print("2. 實作智慧重試機制")
            print("3. 增加進度提示改善使用者體驗")
            print("4. 預期效能提升: 3-5 倍")
        
        if results['error_messages']:
            print("\n⚠️ 測試過程中的錯誤:")
            for error in results['error_messages']:
                print(f"  - {error}")
        
        print("\n" + "=" * 60)
        return 0 if results['batch_update_supported'] else 1
        
    except Exception as e:
        logger.error(f"測試執行失敗: {e}")
        print(f"\n💥 測試失敗: {e}")
        return 2

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)