#!/usr/bin/env python3
"""
Test JIRA API for tooltip functionality
測試 JIRA API 是否返回正確的 tooltip 資料格式
"""

import requests
import json

def test_jira_api():
    """測試 JIRA API 回應格式"""
    base_url = "http://localhost:9999"  # 假設本地開發環境
    ticket_key = "TCG-93178"

    print("🔍 測試 JIRA API 回應格式")
    print("=" * 40)

    try:
        # 測試連接
        print("1. 測試連接狀態...")
        response = requests.get(f"{base_url}/api/jira/connection-test")
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ 連接狀態: {data.get('status')}")
        else:
            print(f"   ❌ 連接測試失敗: {response.status_code}")
            return

        # 測試取得 ticket 資訊
        print(f"\n2. 測試取得 ticket: {ticket_key}")
        response = requests.get(f"{base_url}/api/jira/ticket/{ticket_key}")

        if response.status_code == 200:
            data = response.json()
            print("   ✅ API 回應成功")
            print("   📊 回應資料結構:")
            print(f"      - ticket_key: {data.get('ticket_key')}")
            print(f"      - summary: {data.get('summary')}")
            print(f"      - status: {data.get('status', {}).get('name')}")
            print(f"      - assignee: {data.get('assignee', {}).get('displayName') if data.get('assignee') else 'None'}")
            print(f"      - created: {data.get('created')}")
            print(f"      - updated: {data.get('updated')}")
            print(f"      - url: {data.get('url')}")

            # 檢查資料格式是否正確
            print("\n3. 驗證資料格式...")
            required_fields = ['ticket_key', 'summary', 'status', 'created']
            missing_fields = []

            for field in required_fields:
                if field not in data:
                    missing_fields.append(field)

            if missing_fields:
                print(f"   ❌ 缺少必要欄位: {missing_fields}")
            else:
                print("   ✅ 所有必要欄位都存在")

            # 檢查巢狀結構
            if 'status' in data and isinstance(data['status'], dict):
                print("   ✅ status 欄位格式正確")
            else:
                print("   ❌ status 欄位格式不正確")

            if data.get('assignee') is None or isinstance(data.get('assignee'), dict):
                print("   ✅ assignee 欄位格式正確")
            else:
                print("   ❌ assignee 欄位格式不正確")

        elif response.status_code == 404:
            print(f"   ⚠️  Ticket {ticket_key} 不存在")
        else:
            print(f"   ❌ API 請求失敗: {response.status_code}")
            print(f"      錯誤訊息: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ 無法連接到伺服器")
        print("請確保應用程式正在運行在 http://localhost:9999")
    except Exception as e:
        print(f"❌ 測試過程中發生錯誤: {e}")

if __name__ == "__main__":
    test_jira_api()