#!/usr/bin/env python3
"""
Simple JIRA Test Script
測試 JIRA 客戶端基本功能
"""

import sys
from pathlib import Path

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    try:
        from app.services.jira_client import JiraClient

        print("🔍 測試 JIRA 客戶端")
        print("=" * 30)

        # 初始化 JIRA 客戶端
        jira_client = JiraClient()
        print("✅ JIRA 客戶端初始化成功")

        # 測試連接
        print("\n🔗 測試連接...")
        connection_ok = jira_client.test_connection()
        if connection_ok:
            print("✅ 連接成功")
        else:
            print("❌ 連接失敗")
            return

        # 測試取得 ticket
        ticket_key = "TCG-93178"
        print(f"\n📋 取得 Ticket: {ticket_key}")

        ticket_data = jira_client.get_issue(ticket_key)

        if ticket_data:
            print("✅ 成功取得 Ticket")

            # 顯示基本資訊
            fields = ticket_data.get('fields', {})
            print(f"標題: {fields.get('summary', 'N/A')}")
            print(f"狀態: {fields.get('status', {}).get('name', 'N/A')}")

            assignee = fields.get('assignee', {})
            if assignee:
                print(f"指派人: {assignee.get('displayName', 'N/A')}")
            else:
                print("指派人: 未指派")

            print(f"建立時間: {fields.get('created', 'N/A')}")
        else:
            print("❌ 無法取得 Ticket")

    except Exception as e:
        print(f"❌ 錯誤: {e}")

if __name__ == "__main__":
    main()