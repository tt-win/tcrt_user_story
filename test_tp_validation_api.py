#!/usr/bin/env python3
"""
TP 票號驗證 API 測試腳本
測試 T007 實作的 JIRA TP 票號驗證功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from app.main import app
from app.api.jira import get_jira_client
from app.services.jira_client import JiraClient

# 建立測試客戶端
client = TestClient(app)

def test_tp_validation_format_invalid():
    """測試無效格式的 TP 票號"""
    # 測試無效格式
    invalid_formats = [
        "TP123",      # 缺少連字符
        "tp-123",     # 小寫
        "TP-",        # 缺少數字
        "TP-abc",     # 非數字
        "123-TP",     # 順序錯誤
        "NOTTP-123"   # 錯誤前綴
    ]
    
    for invalid_tp in invalid_formats:
        # 跳過空字串，因為會導致路由錯誤
        if not invalid_tp:
            continue
            
        # Mock JIRA 客戶端
        mock_jira_client = Mock(spec=JiraClient)
        
        # 覆蓋 dependency
        app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
        
        response = client.get(f"/api/jira/tp/{invalid_tp}/validate")
        
        assert response.status_code == 200
        data = response.json()
        assert data['valid'] == False
        assert data['format_valid'] == False
        assert data['exists_in_jira'] == False
        assert 'error' in data
        assert 'TP 票號格式無效' in data['error']
        print(f"✅ 無效格式測試通過: {invalid_tp}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_validation_format_valid_exists():
    """測試有效格式且存在於 JIRA 的 TP 票號"""
    tp_number = "TP-12345"
    
    # Mock JIRA 客戶端和回應
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.server_url = "https://test.atlassian.net"
    mock_jira_client.get_issue.return_value = {
        'fields': {
            'summary': '測試 TP 票號標題',
            'status': {'name': 'In Progress'},
            'key': tp_number
        }
    }
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/validate")
    
    assert response.status_code == 200
    data = response.json()
    assert data['valid'] == True
    assert data['format_valid'] == True
    assert data['exists_in_jira'] == True
    assert data['ticket_number'] == tp_number
    assert data['summary'] == '測試 TP 票號標題'
    assert data['status'] == 'In Progress'
    assert data['url'] == f"https://test.atlassian.net/browse/{tp_number}"
    
    print(f"✅ 有效票號測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_validation_format_valid_not_exists():
    """測試有效格式但不存在於 JIRA 的 TP 票號"""
    tp_number = "TP-99999"
    
    # Mock JIRA 客戶端
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.get_issue.return_value = None  # 票號不存在
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/validate")
    
    assert response.status_code == 200
    data = response.json()
    assert data['valid'] == False
    assert data['format_valid'] == True
    assert data['exists_in_jira'] == False
    assert data['ticket_number'] == tp_number
    assert 'error' in data
    assert 'TP 票號在 JIRA 中不存在' in data['error']
    
    print(f"✅ 不存在票號測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_validation_jira_error():
    """測試 JIRA 連接錯誤的情況"""
    tp_number = "TP-12345"
    
    # Mock JIRA 客戶端拋出異常
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.get_issue.side_effect = Exception("JIRA 連接失敗")
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/validate")
    
    assert response.status_code == 200
    data = response.json()
    assert data['valid'] == False
    assert data['format_valid'] == True
    assert data['exists_in_jira'] == False
    assert data['ticket_number'] == tp_number
    assert 'error' in data
    assert 'JIRA 連接失敗' in data['error']
    
    print(f"✅ JIRA 錯誤測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_multiple_valid_formats():
    """測試多個有效格式的 TP 票號"""
    valid_tps = [
        "TP-1",
        "TP-123",
        "TP-12345",
        "TP-999999"
    ]
    
    for tp_number in valid_tps:
        # Mock JIRA 客戶端
        mock_jira_client = Mock(spec=JiraClient)
        mock_jira_client.server_url = "https://test.atlassian.net"
        mock_jira_client.get_issue.return_value = {
            'fields': {
                'summary': f'{tp_number} 測試標題',
                'status': {'name': 'Open'},
                'key': tp_number
            }
        }
        
        # 覆蓋 dependency
        app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
        
        response = client.get(f"/api/jira/tp/{tp_number}/validate")
        
        assert response.status_code == 200
        data = response.json()
        assert data['valid'] == True
        assert data['format_valid'] == True
        assert data['exists_in_jira'] == True
        print(f"✅ 有效格式測試通過: {tp_number}")
        
        # 清理
        app.dependency_overrides.clear()

def run_all_tests():
    """執行所有測試"""
    print("🧪 開始執行 TP 票號驗證 API 測試...")
    print("=" * 50)
    
    try:
        test_tp_validation_format_invalid()
        test_tp_validation_format_valid_exists()
        test_tp_validation_format_valid_not_exists()
        test_tp_validation_jira_error()
        test_multiple_valid_formats()
        
        print("=" * 50)
        print("🎉 所有測試通過！T007 API 實作成功")
        return True
        
    except Exception as e:
        print(f"❌ 測試失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)