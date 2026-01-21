"""
測試結果檔案清理服務

提供 Test Run 刪除時的測試結果檔案清理功能
"""

import json
import logging
from typing import List, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from app.models.database_models import TestRunItem as TestRunItemDB, Team as TeamDB
from app.services.lark_client import LarkClient
from app.config import settings
from app.models.test_case import TestCase
from app.database import run_sync


class TestResultCleanupService:
    """測試結果檔案清理服務"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.TestResultCleanupService")
    
    async def cleanup_test_run_config_files(
        self, 
        team_id: int, 
        config_id: int, 
        db: AsyncSession
    ) -> int:
        """
        清理 Test Run Config 相關的所有測試結果檔案
        
        Args:
            team_id: 團隊 ID
            config_id: Test Run Config ID
            db: 資料庫會話
            
        Returns:
            清理的檔案數量
        """
        try:
            # 1. 獲取團隊配置
            team_config = await run_sync(
                db,
                lambda sync_db: sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()
            )
            if not team_config:
                self.logger.warning(f"找不到團隊配置 {team_id}")
                return 0
            
            # 2. 獲取所有相關的 Test Run Items
            test_run_items = await run_sync(
                db,
                lambda sync_db: sync_db.query(TestRunItemDB).filter(
                    TestRunItemDB.team_id == team_id,
                    TestRunItemDB.config_id == config_id,
                    TestRunItemDB.result_files_uploaded == 1,
                    TestRunItemDB.upload_history_json.isnot(None)
                ).all()
            )
            
            total_cleaned_files = 0
            
            # 3. 清理每個 Item 的測試結果檔案
            for item in test_run_items:
                cleaned_count = await self._cleanup_item_files(item, team_config)
                total_cleaned_files += cleaned_count
            
            self.logger.info(f"Test Run Config {config_id} 清理完成，共清理 {total_cleaned_files} 個檔案")
            return total_cleaned_files
            
        except Exception as e:
            self.logger.error(f"清理 Test Run Config {config_id} 檔案失敗: {e}")
            return 0

    async def cleanup_test_run_item_files(
        self, 
        team_id: int, 
        config_id: int,
        item_id: int,
        db: AsyncSession
    ) -> int:
        """
        清理單個 Test Run Item 的測試結果檔案
        
        Args:
            team_id: 團隊 ID
            config_id: Test Run Config ID
            item_id: Test Run Item ID
            db: 資料庫會話
            
        Returns:
            清理的檔案數量
        """
        try:
            # 1. 獲取團隊配置
            team_config = await run_sync(
                db,
                lambda sync_db: sync_db.query(TeamDB).filter(TeamDB.id == team_id).first()
            )
            if not team_config:
                self.logger.warning(f"找不到團隊配置 {team_id}")
                return 0
            
            # 2. 獲取特定的 Test Run Item
            test_run_item = await run_sync(
                db,
                lambda sync_db: sync_db.query(TestRunItemDB).filter(
                    TestRunItemDB.id == item_id,
                    TestRunItemDB.team_id == team_id,
                    TestRunItemDB.config_id == config_id,
                    TestRunItemDB.result_files_uploaded == 1,
                    TestRunItemDB.upload_history_json.isnot(None)
                ).first()
            )
            
            if not test_run_item:
                self.logger.info(f"Test Run Item {item_id} 沒有需要清理的附件")
                return 0
            
            # 3. 清理該 Item 的檔案
            cleaned_count = await self._cleanup_item_files(test_run_item, team_config)
            
            if cleaned_count > 0:
                self.logger.info(f"Test Run Item {item_id} 清理完成，共清理 {cleaned_count} 個檔案")
            
            return cleaned_count
            
        except Exception as e:
            self.logger.error(f"清理 Test Run Item {item_id} 檔案失敗: {e}")
            return 0
    
    async def _cleanup_item_files(
        self, 
        item: TestRunItemDB, 
        team_config: TeamDB
    ) -> int:
        """
        清理單個 Test Run Item 的測試結果檔案
        
        Args:
            item: Test Run Item 資料庫記錄
            team_config: 團隊配置
            
        Returns:
            清理的檔案數量
        """
        try:
            if not item.upload_history_json:
                return 0
            
            # 解析上傳歷史，取得檔案清單
            upload_history = json.loads(item.upload_history_json)
            file_tokens = [upload.get('file_token') for upload in upload_history.get('uploads', [])
                         if upload.get('file_token')]
            
            if not file_tokens:
                return 0
            
            # 從 Test Case 的 Test Results Files 欄位中移除這些檔案
            success = await self._remove_files_from_test_case(
                item.test_case_number, 
                file_tokens, 
                team_config
            )
            
            if success:
                self.logger.info(f"已從 Test Case {item.test_case_number} 清理 {len(file_tokens)} 個檔案")
                return len(file_tokens)
            else:
                self.logger.warning(f"清理 Test Case {item.test_case_number} 檔案失敗")
                return 0
                
        except Exception as e:
            self.logger.error(f"清理 Test Run Item {item.id} 檔案失敗: {e}")
            return 0
    
    async def _remove_files_from_test_case(
        self,
        test_case_number: str,
        file_tokens_to_remove: List[str],
        team_config: TeamDB
    ) -> bool:
        """
        從 Test Case 的 Test Results Files 欄位中移除特定檔案
        
        Args:
            test_case_number: 測試案例編號
            file_tokens_to_remove: 要移除的檔案 token 列表
            team_config: 團隊配置
            
        Returns:
            是否成功移除
        """
        try:
            # 使用 LarkClient 直接獲取當前 Test Case
            lark_client = LarkClient(settings.lark.app_id, settings.lark.app_secret)
            if not lark_client.set_wiki_token(team_config.wiki_token):
                self.logger.error("無法設定 Lark Wiki Token 以清理檔案")
                return False
            
            # 從 Lark 取得所有記錄，然後找到指定的記錄
            records = lark_client.get_all_records(team_config.test_case_table_id)
            
            target_record = None
            for record in records:
                fields = record.get('fields', {})
                if fields.get(TestCase.FIELD_IDS['test_case_number']) == test_case_number:
                    target_record = record
                    break
            
            if not target_record:
                self.logger.warning(f"找不到 Test Case {test_case_number}")
                return False
            
            # 轉換為 TestCase 模型
            test_case = TestCase.from_lark_record(target_record, team_config.id)
            
            # 過濾掉要刪除的檔案
            current_files = test_case.test_results_files or []
            remaining_files = [
                file for file in current_files 
                if file.file_token not in file_tokens_to_remove
            ]
            
            # 更新 Test Case 記錄
            success = lark_client.update_record_attachment(
                team_config.test_case_table_id,
                test_case.record_id,
                TestCase.FIELD_IDS['test_results_files'],
                [file.file_token for file in remaining_files],
                team_config.wiki_token
            )
            
            if success:
                self.logger.info(f"成功從 Test Case {test_case_number} 移除 {len(file_tokens_to_remove)} 個檔案")
            else:
                self.logger.error(f"更新 Test Case {test_case_number} 記錄失敗")
            
            return success
            
        except Exception as e:
            self.logger.error(f"從 Test Case {test_case_number} 移除檔案失敗: {e}")
            return False
