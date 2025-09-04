"""
測試結果檔案服務單元測試

測試檔案名稱轉換邏輯和結果檔案上傳功能
"""

import pytest
import time
import re
from app.services.test_result_file_service import (
    TestResultFileService, 
    convert_test_case_number,
    generate_test_result_filename
)

class TestFileNameConversion:
    """檔案名稱轉換測試"""
    
    def test_basic_conversion(self):
        """基本轉換測試"""
        # 標準格式測試
        result = TestResultFileService.convert_test_case_number_to_filename("TCG-93178.010.010")
        assert result == "TCG93178_010_010"
        
        # 其他格式測試
        result = TestResultFileService.convert_test_case_number_to_filename("ABC-12345.001.002")
        assert result == "ABC12345_001_002"
        
        # 純數字測試
        result = TestResultFileService.convert_test_case_number_to_filename("123-456.789.012")
        assert result == "123456_789_012"
    
    def test_edge_cases(self):
        """邊界情況測試"""
        # 無點號的情況
        result = TestResultFileService.convert_test_case_number_to_filename("TCG-93178")
        assert result == "TCG93178"
        
        # 無破折號的情況
        result = TestResultFileService.convert_test_case_number_to_filename("TCG93178.010.010")
        assert result == "TCG93178_010_010"
        
        # 多重破折號和點號
        result = TestResultFileService.convert_test_case_number_to_filename("ABC-DEF-123.456.789.012")
        assert result == "ABCDEF123_456_789_012"
    
    def test_invalid_inputs(self):
        """無效輸入測試"""
        # 空字串
        with pytest.raises(ValueError, match="Test case number cannot be empty"):
            TestResultFileService.convert_test_case_number_to_filename("")
        
        # None
        with pytest.raises(ValueError):
            TestResultFileService.convert_test_case_number_to_filename(None)
        
        # 只有空格
        with pytest.raises(ValueError):
            TestResultFileService.convert_test_case_number_to_filename("   ")
        
        # 包含無效字符（假設包含小寫或特殊字符）
        with pytest.raises(ValueError):
            TestResultFileService.convert_test_case_number_to_filename("tcg-123.abc")

class TestFileNameGeneration:
    """檔案名稱生成測試"""
    
    def test_basic_generation(self):
        """基本生成測試"""
        test_case_number = "TCG-93178.010.010"
        original_filename = "screenshot.png"
        
        result = TestResultFileService.generate_result_filename(test_case_number, original_filename)
        
        # 檢查格式：TCG93178_010_010_TIMESTAMP.png
        pattern = r'^TCG93178_010_010_\d+\.png$'
        assert re.match(pattern, result), f"生成的檔名格式不正確: {result}"
        
        # 檢查時間戳是否合理（應該接近當前時間）
        parts = result.split('_')
        timestamp_with_ext = parts[-1]  # 1234567890.png
        timestamp = timestamp_with_ext.split('.')[0]  # 1234567890
        
        current_timestamp = int(time.time())
        generated_timestamp = int(timestamp)
        
        # 時間戳差異應該在 10 秒內
        assert abs(current_timestamp - generated_timestamp) < 10
    
    def test_different_extensions(self):
        """不同副檔名測試"""
        test_case_number = "ABC-123.456.789"
        
        test_cases = [
            ("document.pdf", ".pdf"),
            ("image.jpg", ".jpg"), 
            ("data.json", ".json"),
            ("log.txt", ".txt"),
            ("archive.zip", ".zip")
        ]
        
        for original_filename, expected_ext in test_cases:
            result = TestResultFileService.generate_result_filename(test_case_number, original_filename)
            assert result.endswith(expected_ext), f"副檔名不正確: {result}"
            assert result.startswith("ABC123_456_789_"), f"前綴不正確: {result}"
    
    def test_no_extension(self):
        """無副檔名測試"""
        test_case_number = "TCG-93178.010.010"
        original_filename = "logfile"
        
        result = TestResultFileService.generate_result_filename(test_case_number, original_filename)
        
        # 應該沒有副檔名
        assert not result.endswith('.'), f"不應該有副檔名: {result}"
        pattern = r'^TCG93178_010_010_\d+$'
        assert re.match(pattern, result), f"無副檔名格式不正確: {result}"

class TestFileNameParsing:
    """檔案名稱解析測試"""
    
    def test_valid_parsing(self):
        """有效解析測試"""
        filename = "TCG93178_010_010_1756912872.png"
        
        result = TestResultFileService.parse_result_filename(filename)
        assert result is not None
        assert result['filename_prefix'] == "TCG93178_010_010"
        assert result['timestamp'] == "1756912872"
        assert result['extension'] == ".png"
        assert result['original_filename'] == filename
    
    def test_no_extension_parsing(self):
        """無副檔名解析測試"""
        filename = "ABC123_456_789_1234567890"
        
        result = TestResultFileService.parse_result_filename(filename)
        assert result is not None
        assert result['filename_prefix'] == "ABC123_456_789"
        assert result['timestamp'] == "1234567890"
        assert result['extension'] == ""
        assert result['original_filename'] == filename
    
    def test_invalid_parsing(self):
        """無效解析測試"""
        invalid_filenames = [
            "invalid_format.png",
            "TCG93178_010_010.png",  # 缺少時間戳
            "TCG93178_010_010_abc.png",  # 時間戳非數字
            "tcg123_456_1234567890.png",  # 小寫前綴
            "",  # 空字串
            "just_a_filename.txt"  # 完全不符合格式
        ]
        
        for filename in invalid_filenames:
            result = TestResultFileService.parse_result_filename(filename)
            assert result is None, f"應該解析失敗但成功了: {filename}"

class TestUtilityFunctions:
    """工具函數測試"""
    
    def test_convert_test_case_number_utility(self):
        """測試工具函數"""
        result = convert_test_case_number("TCG-93178.010.010")
        assert result == "TCG93178_010_010"
    
    def test_generate_test_result_filename_utility(self):
        """測試檔名生成工具函數"""
        result = generate_test_result_filename("TCG-93178.010.010", "test.png")
        pattern = r'^TCG93178_010_010_\d+\.png$'
        assert re.match(pattern, result)

def run_tests():
    """執行所有測試"""
    test_classes = [
        TestFileNameConversion(),
        TestFileNameGeneration(), 
        TestFileNameParsing(),
        TestUtilityFunctions()
    ]
    
    total_tests = 0
    passed_tests = 0
    failed_tests = []
    
    for test_class in test_classes:
        class_name = test_class.__class__.__name__
        print(f"\n🧪 執行 {class_name} 測試...")
        
        # 找出所有測試方法
        test_methods = [method for method in dir(test_class) if method.startswith('test_')]
        
        for method_name in test_methods:
            total_tests += 1
            try:
                method = getattr(test_class, method_name)
                method()
                print(f"  ✅ {method_name}")
                passed_tests += 1
            except Exception as e:
                print(f"  ❌ {method_name}: {e}")
                failed_tests.append(f"{class_name}.{method_name}: {e}")
    
    print(f"\n📊 測試結果:")
    print(f"  總測試數: {total_tests}")
    print(f"  通過: {passed_tests}")
    print(f"  失敗: {len(failed_tests)}")
    
    if failed_tests:
        print(f"\n❌ 失敗的測試:")
        for failure in failed_tests:
            print(f"  - {failure}")
        return False
    else:
        print(f"\n🎉 所有測試通過！")
        return True

if __name__ == "__main__":
    print("🚀 開始檔案轉換功能測試...")
    success = run_tests()
    
    if success:
        print(f"\n✅ 測試完成 - 所有功能正常運作")
    else:
        print(f"\n❌ 測試發現問題，請檢查實作")