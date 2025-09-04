"""
測試結果檔案處理服務

提供測試執行結果檔案的命名轉換、上傳和關聯功能
"""

import time
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from fastapi import UploadFile
from app.models.lark_types import LarkAttachment
from app.services.lark_client import LarkClient
from app.models.test_case import TestCase


class TestResultFileService:
    """測試結果檔案處理服務"""
    
    def __init__(self, lark_client: LarkClient):
        self.lark_client = lark_client
        self.logger = logging.getLogger(f"{__name__}.TestResultFileService")
        
        # 支援的檔案格式
        self.supported_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.bmp',  # 圖片
            '.pdf', '.doc', '.docx',                   # 文檔
            '.txt', '.log', '.json', '.xml',          # 文字檔
            '.zip', '.rar'                            # 壓縮檔
        }
        
        # 檔案大小限制（50MB）
        self.max_file_size = 50 * 1024 * 1024
    
    @staticmethod
    def convert_test_case_number_to_filename(test_case_number: str) -> str:
        """
        將測試案例編號轉換為檔案名稱格式
        
        Args:
            test_case_number: 測試案例編號 (如: TCG-93178.010.010)
            
        Returns:
            轉換後的檔案名稱前綴 (如: TCG93178_010_010)
            
        Raises:
            ValueError: 當測試案例編號格式無效時
        """
        if not test_case_number or not test_case_number.strip():
            raise ValueError("Test case number cannot be empty")
        
        # 移除破折號並將點號替換為底線
        converted = test_case_number.replace('-', '').replace('.', '_')
        
        # 驗證轉換結果格式（只允許字母、數字和底線）
        if not re.match(r'^[A-Z0-9_]+$', converted):
            raise ValueError(f"Invalid converted filename: {converted}")
        
        return converted
    
    @staticmethod
    def generate_result_filename(test_case_number: str, original_filename: str) -> str:
        """
        生成測試結果檔案名稱
        
        Args:
            test_case_number: 測試案例編號
            original_filename: 原始檔案名稱
            
        Returns:
            最終檔案名稱
            
        Example:
            generate_result_filename("TCG-93178.010.010", "screenshot.png")
            返回: "TCG93178_010_010_1756912872.png"
        """
        # 轉換測試案例編號
        prefix = TestResultFileService.convert_test_case_number_to_filename(test_case_number)
        
        # 生成 EPOCH 時間戳
        timestamp = int(time.time())
        
        # 提取副檔名
        file_extension = ""
        if '.' in original_filename:
            file_extension = '.' + original_filename.split('.')[-1].lower()
        
        return f"{prefix}_{timestamp}{file_extension}"
    
    @staticmethod
    def parse_result_filename(filename: str) -> Optional[Dict[str, str]]:
        """
        解析測試結果檔案名稱
        
        Args:
            filename: 檔案名稱
            
        Returns:
            解析結果字典或 None
            {
                'filename_prefix': str,
                'timestamp': str, 
                'extension': str,
                'original_filename': str
            }
        """
        if not filename:
            return None
        
        # 正則表達式匹配格式：{prefix}_{timestamp}.{extension}
        # 要求至少有一個時間戳（10位數字）
        pattern = r'^([A-Z0-9_]+)_(\d{10,})(\..+)?$'
        match = re.match(pattern, filename)
        
        if not match:
            return None
        
        prefix, timestamp, extension = match.groups()
        
        return {
            'filename_prefix': prefix,
            'timestamp': timestamp,
            'extension': extension or '',
            'original_filename': filename
        }
    
    def validate_file(self, file: UploadFile) -> Tuple[bool, Optional[str]]:
        """
        驗證上傳檔案
        
        Args:
            file: 上傳的檔案
            
        Returns:
            (is_valid, error_message)
        """
        # 檢查檔案大小
        if file.size and file.size > self.max_file_size:
            return False, f"檔案大小超過限制 {self.max_file_size // (1024*1024)}MB"
        
        # 檢查檔案格式
        if file.filename:
            file_ext = '.' + file.filename.split('.')[-1].lower()
            if file_ext not in self.supported_extensions:
                return False, f"不支援的檔案格式: {file_ext}"
        
        return True, None
    
    async def upload_file_with_rename(
        self, 
        file: UploadFile, 
        test_case_number: str,
        wiki_token: str
    ) -> Optional[Dict[str, Any]]:
        """
        上傳檔案並使用標準化檔案名稱
        
        Args:
            file: 上傳的檔案
            test_case_number: 測試案例編號
            wiki_token: Wiki Token
            
        Returns:
            上傳結果字典或 None
            {
                'file_token': str,
                'original_filename': str,
                'generated_filename': str,
                'file_size': int,
                'content_type': str,
                'uploaded_at': str
            }
        """
        try:
            # 驗證檔案
            is_valid, error_msg = self.validate_file(file)
            if not is_valid:
                self.logger.error(f"檔案驗證失敗: {error_msg}")
                return None
            
            # 生成標準化檔案名稱
            generated_filename = self.generate_result_filename(
                test_case_number, 
                file.filename or "unknown"
            )
            
            # 讀取檔案內容
            file_content = await file.read()
            
            # 上傳到 Lark Drive
            file_token = self.lark_client.upload_file_to_drive(
                file_content, 
                generated_filename, 
                wiki_token
            )
            
            if not file_token:
                self.logger.error(f"檔案上傳失敗: {generated_filename}")
                return None
            
            # 返回上傳結果
            result = {
                'file_token': file_token,
                'original_filename': file.filename or "unknown",
                'generated_filename': generated_filename,
                'file_size': len(file_content),
                'content_type': file.content_type or "application/octet-stream",
                'uploaded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            
            self.logger.info(f"檔案上傳成功: {generated_filename} -> {file_token}")
            return result
            
        except Exception as e:
            self.logger.error(f"檔案上傳異常: {e}")
            return None
    
    async def upload_results_to_test_case(
        self,
        test_case_number: str,
        test_case_record_id: str,
        files: List[UploadFile],
        wiki_token: str,
        test_case_table_id: str
    ) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
        """
        將測試執行結果檔案上傳到對應的 Test Case
        
        Args:
            test_case_number: 測試案例編號
            test_case_record_id: Test Case 記錄 ID
            files: 要上傳的檔案列表
            wiki_token: Wiki Token
            test_case_table_id: Test Case 表格 ID
            
        Returns:
            (overall_success, upload_results, error_messages)
        """
        if not files:
            return True, [], []
        
        upload_results = []
        error_messages = []
        
        try:
            # 批次上傳檔案
            file_tokens = []
            
            for file in files:
                upload_result = await self.upload_file_with_rename(
                    file, test_case_number, wiki_token
                )
                
                if upload_result:
                    upload_results.append(upload_result)
                    file_tokens.append(upload_result['file_token'])
                else:
                    error_messages.append(f"檔案 {file.filename} 上傳失敗")
            
            # 如果有成功上傳的檔案，更新 Test Case 記錄
            if file_tokens:
                # 先獲取現有的測試結果檔案
                records = self.lark_client.get_all_records(test_case_table_id, wiki_token)
                existing_files = []
                
                # 找到對應的 Test Case 記錄
                target_record = None
                for record in records:
                    if record.get('record_id') == test_case_record_id:
                        target_record = record
                        break
                
                if target_record and 'fields' in target_record:
                    existing_attachments = target_record['fields'].get(TestCase.FIELD_IDS['test_results_files'], []) or []
                    existing_files = [att.get('file_token') for att in existing_attachments if att and att.get('file_token')]
                
                # 合併現有檔案與新上傳的檔案
                all_file_tokens = existing_files + file_tokens
                
                success = self.lark_client.update_record_attachment(
                    test_case_table_id,
                    test_case_record_id,
                    TestCase.FIELD_IDS['test_results_files'],
                    all_file_tokens,
                    wiki_token
                )
                
                if success:
                    self.logger.info(f"Test Case {test_case_number} 結果檔案更新成功，新增 {len(file_tokens)} 個檔案，總計 {len(all_file_tokens)} 個檔案")
                else:
                    error_messages.append(f"Test Case {test_case_number} 結果檔案欄位更新失敗")
                    return False, upload_results, error_messages
            
            overall_success = len(error_messages) == 0
            return overall_success, upload_results, error_messages
            
        except Exception as e:
            self.logger.error(f"批次上傳異常: {e}")
            error_messages.append(f"批次上傳異常: {str(e)}")
            return False, upload_results, error_messages
    
    def create_upload_history_record(self, upload_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        建立上傳歷史記錄
        
        Args:
            upload_results: 上傳結果列表
            
        Returns:
            上傳歷史記錄字典
        """
        return {
            'uploads': upload_results,
            'total_uploads': len(upload_results),
            'last_upload_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()) if upload_results else None
        }


class TestCaseResultFileManager:
    """Test Case 結果檔案管理器"""
    
    def __init__(self, lark_client: LarkClient):
        self.lark_client = lark_client
        self.file_service = TestResultFileService(lark_client)
        self.logger = logging.getLogger(f"{__name__}.TestCaseResultFileManager")
    
    async def attach_test_run_results(
        self,
        test_run_item_id: int,
        test_case_number: str,
        test_case_record_id: str,
        files: List[UploadFile],
        team_wiki_token: str,
        test_case_table_id: str
    ) -> Dict[str, Any]:
        """
        將 Test Run 執行結果附加到對應的 Test Case
        
        Args:
            test_run_item_id: Test Run Item ID
            test_case_number: 測試案例編號
            test_case_record_id: Test Case 記錄 ID
            files: 要上傳的檔案列表
            team_wiki_token: 團隊 Wiki Token
            test_case_table_id: Test Case 表格 ID
            
        Returns:
            操作結果字典
        """
        try:
            # 上傳檔案到 Test Case
            success, upload_results, error_messages = await self.file_service.upload_results_to_test_case(
                test_case_number,
                test_case_record_id,
                files,
                team_wiki_token,
                test_case_table_id
            )
            
            # 建立上傳歷史記錄
            upload_history = self.file_service.create_upload_history_record(upload_results)
            
            result = {
                'success': success,
                'test_run_item_id': test_run_item_id,
                'test_case_number': test_case_number,
                'uploaded_files': len(upload_results),
                'upload_results': upload_results,
                'upload_history': upload_history,
                'error_messages': error_messages
            }
            
            if success:
                self.logger.info(f"Test Run {test_run_item_id} 結果成功關聯到 Test Case {test_case_number}")
            else:
                self.logger.error(f"Test Run {test_run_item_id} 結果關聯失敗: {error_messages}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Test Run 結果關聯異常: {e}")
            return {
                'success': False,
                'test_run_item_id': test_run_item_id,
                'test_case_number': test_case_number,
                'uploaded_files': 0,
                'upload_results': [],
                'upload_history': {},
                'error_messages': [f"系統異常: {str(e)}"]
            }


# 檔案名稱轉換工具函數
def convert_test_case_number(test_case_number: str) -> str:
    """快速轉換測試案例編號為檔案名稱格式"""
    return TestResultFileService.convert_test_case_number_to_filename(test_case_number)


def generate_test_result_filename(test_case_number: str, original_filename: str) -> str:
    """快速生成測試結果檔案名稱"""
    return TestResultFileService.generate_result_filename(test_case_number, original_filename)