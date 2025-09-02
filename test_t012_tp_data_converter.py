#!/usr/bin/env python3
"""
T012 TP票號資料轉換服務測試

測試 TPTicketDataConverter 類別的所有功能，包括：
1. List ↔ JSON 轉換
2. 搜尋索引建立 
3. 批次轉換功能
4. 驗證與轉換整合
"""

import sys
import os
import json
from typing import List, Optional

# 加入專案路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.models.test_run_config import TPTicketDataConverter

class TestTPDataConverter:
    """TP 票號資料轉換服務測試類別"""
    
    def __init__(self):
        self.test_results = []
        self.passed_tests = 0
        self.total_tests = 0
    
    def run_test(self, test_name: str, test_func):
        """執行單個測試"""
        self.total_tests += 1
        try:
            test_func()
            print(f"✅ {test_name}")
            self.test_results.append(f"PASS: {test_name}")
            self.passed_tests += 1
        except Exception as e:
            print(f"❌ {test_name}: {str(e)}")
            self.test_results.append(f"FAIL: {test_name}: {str(e)}")
    
    def test_list_to_json_basic(self):
        """測試基本 List 轉 JSON 功能"""
        # 測試正常情況
        tickets = ['TP-123', 'TP-456', 'TP-789']
        result = TPTicketDataConverter.list_to_json(tickets)
        expected = json.dumps(tickets, ensure_ascii=False)
        assert result == expected, f"Expected {expected}, got {result}"
        
        # 測試空列表
        result = TPTicketDataConverter.list_to_json([])
        assert result is None, f"Expected None for empty list, got {result}"
        
        # 測試 None 輸入
        result = TPTicketDataConverter.list_to_json(None)
        assert result is None, f"Expected None for None input, got {result}"
    
    def test_json_to_list_basic(self):
        """測試基本 JSON 轉 List 功能"""
        # 測試正常情況
        json_data = '["TP-123", "TP-456", "TP-789"]'
        result = TPTicketDataConverter.json_to_list(json_data)
        expected = ['TP-123', 'TP-456', 'TP-789']
        assert result == expected, f"Expected {expected}, got {result}"
        
        # 測試空字串
        result = TPTicketDataConverter.json_to_list("")
        assert result is None, f"Expected None for empty string, got {result}"
        
        # 測試 None 輸入
        result = TPTicketDataConverter.json_to_list(None)
        assert result is None, f"Expected None for None input, got {result}"
        
        # 測試無效 JSON
        result = TPTicketDataConverter.json_to_list("invalid json")
        assert result is None, f"Expected None for invalid JSON, got {result}"
    
    def test_round_trip_conversion(self):
        """測試來回轉換的一致性"""
        original_tickets = ['TP-100', 'TP-200', 'TP-300']
        
        # List -> JSON -> List
        json_result = TPTicketDataConverter.list_to_json(original_tickets)
        final_result = TPTicketDataConverter.json_to_list(json_result)
        
        assert final_result == original_tickets, f"Round trip failed: {original_tickets} -> {final_result}"
    
    def test_create_search_index(self):
        """測試搜尋索引建立功能"""
        # 測試正常情況
        tickets = ['TP-123', 'TP-456', 'TP-789']
        result = TPTicketDataConverter.create_search_index(tickets)
        expected = 'TP-123 TP-456 TP-789'
        assert result == expected, f"Expected '{expected}', got '{result}'"
        
        # 測試空列表
        result = TPTicketDataConverter.create_search_index([])
        assert result is None, f"Expected None for empty list, got {result}"
        
        # 測試 None 輸入
        result = TPTicketDataConverter.create_search_index(None)
        assert result is None, f"Expected None for None input, got {result}"
        
        # 測試單一票號
        result = TPTicketDataConverter.create_search_index(['TP-999'])
        assert result == 'TP-999', f"Expected 'TP-999', got '{result}'"
    
    def test_batch_convert_to_database_format(self):
        """測試批次轉換為資料庫格式"""
        configs_data = [
            {
                'name': 'Test Config 1',
                'related_tp_tickets': ['TP-100', 'TP-101'],
                'description': 'Test description 1'
            },
            {
                'name': 'Test Config 2', 
                'related_tp_tickets': ['TP-200'],
                'description': 'Test description 2'
            },
            {
                'name': 'Test Config 3',
                'related_tp_tickets': None,
                'description': 'Test description 3'
            }
        ]
        
        result = TPTicketDataConverter.batch_convert_to_database_format(configs_data)
        
        # 檢查第一個配置
        assert result[0]['related_tp_tickets_json'] == '["TP-100", "TP-101"]'
        assert result[0]['tp_tickets_search'] == 'TP-100 TP-101'
        assert 'related_tp_tickets' not in result[0]
        
        # 檢查第二個配置
        assert result[1]['related_tp_tickets_json'] == '["TP-200"]'
        assert result[1]['tp_tickets_search'] == 'TP-200'
        
        # 檢查第三個配置（無 TP 票號）
        assert result[2]['related_tp_tickets_json'] is None
        assert result[2]['tp_tickets_search'] is None
    
    def test_batch_convert_from_database_format(self):
        """測試批次轉換從資料庫格式"""
        db_records = [
            {
                'id': 1,
                'name': 'Test Config 1',
                'related_tp_tickets_json': '["TP-100", "TP-101"]',
                'tp_tickets_search': 'TP-100 TP-101'
            },
            {
                'id': 2,
                'name': 'Test Config 2',
                'related_tp_tickets_json': '["TP-200"]',
                'tp_tickets_search': 'TP-200'
            },
            {
                'id': 3,
                'name': 'Test Config 3',
                'related_tp_tickets_json': None,
                'tp_tickets_search': None
            }
        ]
        
        result = TPTicketDataConverter.batch_convert_from_database_format(db_records)
        
        # 檢查第一個記錄
        assert result[0]['related_tp_tickets'] == ['TP-100', 'TP-101']
        
        # 檢查第二個記錄
        assert result[1]['related_tp_tickets'] == ['TP-200']
        
        # 檢查第三個記錄（無 TP 票號）
        assert result[2]['related_tp_tickets'] is None
    
    def test_validate_and_convert_success(self):
        """測試驗證與轉換成功案例"""
        # 測試有效的 TP 票號
        valid_tickets = ['TP-123', 'TP-456']
        json_data, search_index = TPTicketDataConverter.validate_and_convert(valid_tickets)
        
        assert json_data == '["TP-123", "TP-456"]'
        assert search_index == 'TP-123 TP-456'
        
        # 測試 None 輸入
        json_data, search_index = TPTicketDataConverter.validate_and_convert(None)
        assert json_data is None
        assert search_index is None
    
    def test_validate_and_convert_failure(self):
        """測試驗證與轉換失敗案例"""
        # 測試無效格式的 TP 票號
        invalid_tickets = ['TP-123', 'INVALID-456']
        
        try:
            TPTicketDataConverter.validate_and_convert(invalid_tickets)
            assert False, "Should have raised ValueError for invalid TP ticket format"
        except ValueError as e:
            assert "TP ticket validation failed" in str(e)
        
        # 測試重複的 TP 票號
        duplicate_tickets = ['TP-123', 'TP-123']
        
        try:
            TPTicketDataConverter.validate_and_convert(duplicate_tickets)
            assert False, "Should have raised ValueError for duplicate TP tickets"
        except ValueError as e:
            assert "TP ticket validation failed" in str(e)
    
    def test_edge_cases(self):
        """測試邊界情況"""
        # 測試中文字符的處理
        tickets_with_chinese = ['TP-123']  # 基本測試，不包含中文票號
        json_result = TPTicketDataConverter.list_to_json(tickets_with_chinese)
        list_result = TPTicketDataConverter.json_to_list(json_result)
        assert list_result == tickets_with_chinese
        
        # 測試空白字符處理
        result = TPTicketDataConverter.json_to_list("   ")
        assert result is None
        
        # 測試非列表 JSON
        result = TPTicketDataConverter.json_to_list('{"key": "value"}')
        assert result is None
        
        # 測試非字串類型的 JSON
        result = TPTicketDataConverter.json_to_list(123)
        assert result is None
    
    def run_all_tests(self):
        """執行所有測試"""
        print("🧪 開始執行 T012 TP票號資料轉換服務測試...\n")
        
        # 基本轉換功能測試
        self.run_test("List 轉 JSON 基本功能", self.test_list_to_json_basic)
        self.run_test("JSON 轉 List 基本功能", self.test_json_to_list_basic)
        self.run_test("來回轉換一致性", self.test_round_trip_conversion)
        
        # 搜尋索引功能測試
        self.run_test("搜尋索引建立功能", self.test_create_search_index)
        
        # 批次轉換功能測試
        self.run_test("批次轉換為資料庫格式", self.test_batch_convert_to_database_format)
        self.run_test("批次轉換從資料庫格式", self.test_batch_convert_from_database_format)
        
        # 驗證與轉換整合測試
        self.run_test("驗證與轉換成功案例", self.test_validate_and_convert_success)
        self.run_test("驗證與轉換失敗案例", self.test_validate_and_convert_failure)
        
        # 邊界情況測試
        self.run_test("邊界情況處理", self.test_edge_cases)
        
        # 顯示測試結果摘要
        print(f"\n📊 測試結果摘要:")
        print(f"   總測試數: {self.total_tests}")
        print(f"   通過測試: {self.passed_tests}")
        print(f"   失敗測試: {self.total_tests - self.passed_tests}")
        print(f"   通過率: {(self.passed_tests/self.total_tests)*100:.1f}%")
        
        if self.passed_tests == self.total_tests:
            print("\n🎉 所有測試通過！TP票號資料轉換服務功能正常")
            return True
        else:
            print(f"\n⚠️  有 {self.total_tests - self.passed_tests} 個測試失敗")
            return False


def main():
    """主執行函數"""
    print("=" * 60)
    print("T012 TP票號資料轉換服務測試")
    print("測試範圍: List ↔ JSON 轉換、搜尋索引、批次操作")
    print("=" * 60)
    
    tester = TestTPDataConverter()
    success = tester.run_all_tests()
    
    if success:
        print("\n✅ T012 驗收測試 - 通過")
        print("📋 驗收結果: 資料轉換正確無誤，支援批次操作")
        return 0
    else:
        print("\n❌ T012 驗收測試 - 失敗")
        print("📋 需要修復失敗的測試項目")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)