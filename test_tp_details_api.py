#!/usr/bin/env python3
"""
TP 票號詳情 API 測試腳本
測試 T008 實作的 JIRA TP 票號詳情獲取功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from fastapi.testclient import TestClient
from unittest.mock import Mock
from app.main import app
from app.api.jira import get_jira_client
from app.services.jira_client import JiraClient

# 建立測試客戶端
client = TestClient(app)

def create_mock_ticket_data(tp_number: str, include_optional_fields: bool = True):
    """創建 Mock 的 JIRA 票號資料"""
    base_data = {
        'fields': {
            'summary': f'{tp_number} 測試票號標題',
            'description': 'This is a test TP ticket description for testing purposes.',
            'status': {
                'name': 'In Progress',
                'id': '3',
                'statusCategory': {'name': 'In Progress'}
            },
            'project': {
                'key': 'TEST',
                'name': 'Test Project'
            },
            'issuetype': {
                'name': 'Task',
                'iconUrl': 'https://test.atlassian.net/images/icons/task.svg'
            },
            'created': '2024-01-01T10:00:00.000+0000',
            'updated': '2024-01-02T15:30:00.000+0000'
        }
    }
    
    if include_optional_fields:
        base_data['fields'].update({
            'assignee': {
                'displayName': 'Test User',
                'emailAddress': 'test@example.com',
                'accountId': 'test-account-id-123'
            },
            'priority': {
                'name': 'High',
                'id': '2',
                'iconUrl': 'https://test.atlassian.net/images/icons/priority_high.svg'
            }
        })
    
    return base_data

def test_tp_details_format_invalid():
    """測試無效格式的 TP 票號請求詳情"""
    invalid_formats = [
        "TP123",      # 缺少連字符
        "tp-123",     # 小寫
        "TP-abc",     # 非數字
        "123-TP",     # 順序錯誤
    ]
    
    for invalid_tp in invalid_formats:
        # Mock JIRA 客戶端 (不會被呼叫，因為格式驗證失敗)
        mock_jira_client = Mock(spec=JiraClient)
        
        # 覆蓋 dependency
        app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
        
        response = client.get(f"/api/jira/tp/{invalid_tp}/details")
        
        # 應該回傳 400 Bad Request
        assert response.status_code == 400
        data = response.json()
        assert 'detail' in data
        assert 'TP 票號格式無效' in data['detail']
        print(f"✅ 無效格式錯誤處理測試通過: {invalid_tp}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_ticket_exists_full_data():
    """測試存在的 TP 票號，包含完整資料"""
    tp_number = "TP-12345"
    
    # 確保清除之前的 overrides
    app.dependency_overrides.clear()
    
    # Mock JIRA 客戶端和完整資料
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.server_url = "https://test.atlassian.net"
    
    # 創建 Mock 資料
    mock_data = create_mock_ticket_data(tp_number, include_optional_fields=True)
    mock_jira_client.get_issue.return_value = mock_data
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    assert response.status_code == 200
    data = response.json()
    
    # 驗證基本欄位
    assert data['ticket_number'] == tp_number
    assert data['summary'] == f'{tp_number} 測試票號標題'
    
    assert 'test tp ticket' in data['description'].lower()
    
    # 驗證狀態資訊
    assert data['status']['name'] == 'In Progress'
    assert data['status']['id'] == '3'
    assert data['status']['category'] == 'In Progress'
    
    # 驗證負責人資訊
    assert data['assignee'] is not None
    assert data['assignee']['display_name'] == 'Test User'
    assert data['assignee']['email'] == 'test@example.com'
    assert data['assignee']['account_id'] == 'test-account-id-123'
    
    # 驗證優先級資訊
    assert data['priority'] is not None
    assert data['priority']['name'] == 'High'
    assert data['priority']['id'] == '2'
    
    # 驗證專案資訊
    assert data['project']['key'] == 'TEST'
    assert data['project']['name'] == 'Test Project'
    
    # 驗證議題類型
    assert data['issue_type']['name'] == 'Task'
    
    # 驗證時間欄位
    assert data['created'] == '2024-01-01T10:00:00.000+0000'
    assert data['updated'] == '2024-01-02T15:30:00.000+0000'
    
    # 驗證 URL
    assert data['url'] == f"https://test.atlassian.net/browse/{tp_number}"
    
    # 驗證時間戳存在
    assert 'retrieved_at' in data
    assert data['retrieved_at'] is not None
    
    print(f"✅ 完整資料測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_ticket_exists_minimal_data():
    """測試存在的 TP 票號，僅包含最少資料（無負責人和優先級）"""
    tp_number = "TP-99999"
    
    # Mock JIRA 客戶端和最少資料
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.server_url = "https://test.atlassian.net"
    mock_jira_client.get_issue.return_value = create_mock_ticket_data(tp_number, include_optional_fields=False)
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    assert response.status_code == 200
    data = response.json()
    
    # 驗證基本欄位
    assert data['ticket_number'] == tp_number
    assert data['summary'] == f'{tp_number} 測試票號標題'
    
    # 驗證可選欄位為 None
    assert data['assignee'] is None
    assert data['priority'] is None
    
    # 驗證其他必要欄位存在
    assert data['status']['name'] == 'In Progress'
    assert data['project']['key'] == 'TEST'
    
    print(f"✅ 最少資料測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_ticket_not_exists():
    """測試不存在的 TP 票號"""
    tp_number = "TP-00000"
    
    # Mock JIRA 客戶端返回 None
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.get_issue.return_value = None  # 票號不存在
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    # 應該回傳 404 Not Found
    assert response.status_code == 404
    data = response.json()
    assert 'detail' in data
    assert 'TP 票號不存在' in data['detail']
    assert tp_number in data['detail']
    
    print(f"✅ 不存在票號測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_jira_connection_error():
    """測試 JIRA 連接錯誤"""
    tp_number = "TP-12345"
    
    # Mock JIRA 客戶端拋出異常
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.get_issue.side_effect = Exception("JIRA 伺服器連接失敗")
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    # 應該回傳 500 Internal Server Error
    assert response.status_code == 500
    data = response.json()
    assert 'detail' in data
    assert '取得 TP 票號詳情失敗' in data['detail']
    assert 'JIRA 伺服器連接失敗' in data['detail']
    
    print(f"✅ 連接錯誤測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_malformed_jira_response():
    """測試 JIRA 回應格式異常"""
    tp_number = "TP-12345"
    
    # Mock JIRA 客戶端返回異常格式的資料
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.server_url = "https://test.atlassian.net"
    mock_jira_client.get_issue.return_value = {
        # 缺少 fields 欄位或格式異常
        'unexpected_field': 'unexpected_value'
    }
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    assert response.status_code == 200  # 應該能處理異常格式
    data = response.json()
    
    # 驗證即使資料異常，也能返回基本結構
    assert data['ticket_number'] == tp_number
    assert data['summary'] == ''  # 預設值
    assert data['assignee'] is None
    assert data['priority'] is None
    
    print(f"✅ 異常回應格式測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def test_tp_details_description_truncation():
    """測試描述長度限制"""
    tp_number = "TP-12345"
    
    # 創建超長描述的 Mock 資料
    long_description = "X" * 2000  # 2000 字符的描述
    
    mock_data = create_mock_ticket_data(tp_number)
    mock_data['fields']['description'] = long_description
    
    mock_jira_client = Mock(spec=JiraClient)
    mock_jira_client.server_url = "https://test.atlassian.net"
    mock_jira_client.get_issue.return_value = mock_data
    
    # 覆蓋 dependency
    app.dependency_overrides[get_jira_client] = lambda: mock_jira_client
    
    response = client.get(f"/api/jira/tp/{tp_number}/details")
    
    assert response.status_code == 200
    data = response.json()
    
    # 驗證描述被截斷到 1000 字符
    assert len(data['description']) == 1000
    assert data['description'] == "X" * 1000
    
    print(f"✅ 描述長度限制測試通過: {tp_number}")
    
    # 清理
    app.dependency_overrides.clear()

def run_all_tests():
    """執行所有測試"""
    print("🧪 開始執行 TP 票號詳情 API 測試 (T008)...")
    print("=" * 60)
    
    try:
        test_tp_details_format_invalid()
        test_tp_details_ticket_exists_full_data()
        test_tp_details_ticket_exists_minimal_data()
        test_tp_details_ticket_not_exists()
        test_tp_details_jira_connection_error()
        test_tp_details_malformed_jira_response()
        test_tp_details_description_truncation()
        
        print("=" * 60)
        print("🎉 所有測試通過！T008 詳情 API 實作成功")
        print("✨ 功能驗證:")
        print("  • TP 票號格式驗證")
        print("  • 完整票號資訊提取")
        print("  • 可選欄位安全處理 (assignee, priority)")
        print("  • 錯誤狀況處理 (404, 500)")
        print("  • 資料格式異常處理")
        print("  • 描述長度限制 (1000 字符)")
        print("  • API 呼叫時間戳記錄")
        return True
        
    except Exception as e:
        print(f"❌ 測試失敗: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)