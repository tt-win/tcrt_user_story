#!/usr/bin/env python3
"""
JIRA Ticket Test Script
測試 JIRA 客戶端能否取得指定 ticket 的內容
"""

import sys
from pathlib import Path

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_jira_ticket(ticket_key):
    """測試取得 JIRA ticket 內容"""
    print("🔍 測試取得 JIRA Ticket: " + ticket_key)
    print("=" * 50)

    try:
        from app.services.jira_client import JiraClient

        # 初始化 JIRA 客戶端
        jira_client = JiraClient()
        print("✅ JIRA 客戶端初始化成功")

        # 測試連接
        print("\n🔗 測試 JIRA 連接...")
        connection_ok = jira_client.test_connection()
        if not connection_ok:
            print("❌ JIRA 連接測試失敗")
            return
        print("✅ JIRA 連接測試成功")

        # 取得 ticket 內容
        print("\n📋 取得 Ticket 內容: " + ticket_key)
        ticket_data = jira_client.get_issue(ticket_key)

        if ticket_data:
            print("✅ 成功取得 Ticket 內容")
            print("-" * 30)

            # 顯示基本資訊
            fields = ticket_data.get('fields', {})
            summary = fields.get('summary', 'N/A')
            status = fields.get('status', {}).get('name', 'N/A')
            assignee = fields.get('assignee', {})
            assignee_name = assignee.get('displayName', '未指派') if assignee else '未指派'
            created = fields.get('created', 'N/A')
            updated = fields.get('updated', 'N/A')

            print("📝 標題: " + summary)
            print("📊 狀態: " + status)
            print("👤 指派人: " + assignee_name)
            print("📅 建立時間: " + created)
            print("🔄 更新時間: " + updated)

            # 顯示描述 (前200個字元)
            description = fields.get('description', '')
            if description:
                if len(description) > 200:
                    truncated_desc = description[:200] + "..."
                else:
                    truncated_desc = description
                print("📖 描述: " + truncated_desc)

            print("-" * 30)
            print("完整 Ticket 資料:")
            print(ticket_data)

        else:
            print("❌ 無法取得 Ticket: " + ticket_key)

    except Exception as e:
        print("❌ 錯誤: " + str(e))

if __name__ == "__main__":
    # 測試指定的 ticket
    test_jira_ticket("TCG-93178")', 'N/A')}")

                # 顯示描述 (前200個字元)
                description = fields.get('description', '')
                if description:
                    print(f"📖 描述: {description[:200]}{'...' if len(description) > 200 else ''}")

                print("-" * 30)
                print("完整 Ticket 資料:")
                print(ticket_data)

            else:
                print(f"❌ 無法取得 Ticket: {ticket_key}")
                print("可能的原因:")
                print("  - Ticket 不存在")
                print("  - 權限不足")
                print("  - 網路連接問題")

        except Exception as e:
            print(f"❌ 取得 Ticket 時發生錯誤: {e}")

    if __name__ == "__main__":
        # 測試指定的 ticket
        test_jira_ticket("TCG-93178")

except ImportError as e:
    print(f"❌ 匯入錯誤: {e}")
    print("請確保已安裝所有必要的依賴套件")
except Exception as e:
    print(f"❌ 程式錯誤: {e}")