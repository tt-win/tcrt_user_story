"""
Lark 通知發送服務

負責發送 Test Run 狀態變更通知到指定的 Lark 群組
"""

import requests
import logging
import json
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.database import get_sync_engine
from app.models.database_models import TestRunConfig as TestRunConfigDB, TestRunItem as TestRunItemDB
from app.services.lark_group_service import get_lark_group_service

logger = logging.getLogger(__name__)

class LarkNotifyService:
    def __init__(self):
        self.settings = get_settings()
    
    def _get_tenant_access_token(self) -> Optional[str]:
        """
        取得 tenant_access_token
        
        Returns:
            access token 或 None (如果失敗)
        """
        # 重用群組服務的 token 取得邏輯
        lark_service = get_lark_group_service()
        return lark_service._get_tenant_access_token()
    
    def send_message_to_chats(self, chat_ids: List[str], content: Dict) -> Dict[str, Dict]:
        """
        向多個群組發送 Rich Text 訊息

        Args:
            chat_ids: 群組 Chat ID 列表
            content: Rich Text 內容字典

        Returns:
            發送結果：{chat_id: {"ok": bool, "error": Optional[str]}}
        """
        results = {}

        # DRY RUN 模式
        if self.settings.app.lark_dry_run:
            logger.info(f"LARK_DRY_RUN 模式：模擬發送訊息到 {len(chat_ids)} 個群組")
            logger.info(f"訊息內容: {json.dumps(content, ensure_ascii=False)}")
            for chat_id in chat_ids:
                results[chat_id] = {"ok": True, "error": None}
            return results

        # 取得 access token
        token = self._get_tenant_access_token()
        if not token:
            error_msg = "無法取得 Lark access token"
            logger.error(error_msg)
            for chat_id in chat_ids:
                results[chat_id] = {"ok": False, "error": error_msg}
            return results

        # 向每個群組發送訊息
        for chat_id in chat_ids:
            try:
                result = self._send_message_to_single_chat(token, chat_id, content)
                results[chat_id] = result

                if result["ok"]:
                    logger.info(f"成功發送訊息到群組 {chat_id}")
                else:
                    logger.warning(f"發送訊息到群組 {chat_id} 失敗: {result['error']}")

            except Exception as e:
                error_msg = f"發送訊息時發生錯誤: {str(e)}"
                logger.error(f"群組 {chat_id}: {error_msg}")
                results[chat_id] = {"ok": False, "error": error_msg}

        return results
    
    def _send_message_to_single_chat(self, token: str, chat_id: str, content: Dict) -> Dict:
        """
        向單一群組發送 Rich Text 訊息

        Args:
            token: tenant_access_token
            chat_id: 群組 Chat ID
            content: Rich Text 內容字典

        Returns:
            發送結果：{"ok": bool, "error": Optional[str]}
        """
        url = f"https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 構建 JSON payload，content 作為字典對象
        payload_data = {
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps(content, ensure_ascii=False)  # 將字典轉換為 JSON 字串
        }

        # 序列化整個 payload
        payload_json = json.dumps(payload_data, ensure_ascii=False)

        try:
            response = requests.post(url, headers=headers, data=payload_json, timeout=15)
            response.raise_for_status()

            result = response.json()
            if result.get("code") == 0:
                return {"ok": True, "error": None}
            else:
                return {"ok": False, "error": f"Lark API 錯誤: {result}"}

        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def build_start_message(self, config: TestRunConfigDB, base_url: str) -> Dict:
        """
        Build start execution notification message (Rich Text format) in English

        Args:
            config: Test Run configuration
            base_url: Application base URL

        Returns:
            Rich Text dictionary
        """
        # Get start time in UTC
        if config.start_date:
            start_time = config.start_date.strftime('%Y-%m-%d %H:%M:%S UTC')
        else:
            start_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

        # Build URL (fix port to 9999)
        if ":8000" in base_url:
            base_url = base_url.replace(":8000", ":9999")
        url = f"{base_url.rstrip('/')}/test-run-execution?config_id={config.id}&team_id={config.team_id}"

        # Build Rich Text content
        content = []

        # Title line (using Font Awesome icons)
        content.append([
            {"tag": "text", "text": "▶ ", "style": []},
            {"tag": "text", "text": "Test Execution Started", "style": ["bold"]}
        ])

        # Empty line
        content.append([{"tag": "text", "text": "", "style": []}])

        # Configuration name
        content.append([
            {"tag": "text", "text": "Config Name: ", "style": ["bold"]},
            {"tag": "text", "text": config.name, "style": []}
        ])

        # Start time
        content.append([
            {"tag": "text", "text": "Start Time: ", "style": ["bold"]},
            {"tag": "text", "text": start_time, "style": []}
        ])

        # Optional information (using Font Awesome style icons)
        if config.test_version:
            content.append([
                {"tag": "text", "text": "⚡ ", "style": []},
                {"tag": "text", "text": "Test Version: ", "style": ["bold"]},
                {"tag": "text", "text": config.test_version, "style": []}
            ])

        if config.test_environment:
            content.append([
                {"tag": "text", "text": "🌍 ", "style": []},
                {"tag": "text", "text": "Test Environment: ", "style": ["bold"]},
                {"tag": "text", "text": config.test_environment, "style": []}
            ])

        if config.build_number:
            content.append([
                {"tag": "text", "text": "🔧 ", "style": []},
                {"tag": "text", "text": "Build: ", "style": ["bold"]},
                {"tag": "text", "text": config.build_number, "style": []}
            ])

        if config.total_test_cases > 0:
            content.append([
                {"tag": "text", "text": "📝 ", "style": []},
                {"tag": "text", "text": "Total Test Cases: ", "style": ["bold"]},
                {"tag": "text", "text": str(config.total_test_cases), "style": []}
            ])

        # Empty line
        content.append([{"tag": "text", "text": "", "style": []}])

        # View details link
        content.append([
            {"tag": "text", "text": "🔗 ", "style": []},
            {"tag": "a", "text": "View Details", "href": url, "style": ["bold"]}
        ])

        # 構建符合 Lark API 規格的 Rich Text 格式
        rich_text = {
            "zh_cn": {
                "title": "Test Execution Notification",
                "content": content
            }
        }

        return rich_text
    
    def build_end_message(self, config: TestRunConfigDB, stats: Dict, base_url: str) -> Dict:
        """
        Build end execution notification message (Rich Text format) in English
        
        Args:
            config: Test Run configuration
            stats: Statistics {"pass_rate": float, "fail_rate": float, "bug_count": int}
            base_url: Application base URL
            
        Returns:
            Rich Text dictionary
        """
        # Build URL (fix port to 9999)
        if ":8000" in base_url:
            base_url = base_url.replace(":8000", ":9999")
        url = f"{base_url.rstrip('/')}/test-run-execution?config_id={config.id}&team_id={config.team_id}"

        # Get end time in UTC
        end_time = config.end_date.strftime('%Y-%m-%d %H:%M:%S UTC') if config.end_date else datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Prepare status icon (using Font Awesome style icons)
        if stats['pass_rate'] >= 95:
            status_icon = "✓ "  # checkmark
        elif stats['pass_rate'] >= 80:
            status_icon = "⚠ "  # warning
        else:
            status_icon = "✗ "  # x-mark
        
        # Build Rich Text content
        content = []
        
        # Title line (status + test execution completed)
        content.append([
            {"tag": "text", "text": status_icon, "style": []},
            {"tag": "text", "text": "Test Execution Completed", "style": ["bold"]}
        ])
        
        # Empty line
        content.append([{"tag": "text", "text": "", "style": []}])
        
        # Configuration name
        content.append([
            {"tag": "text", "text": "Config Name: ", "style": ["bold"]},
            {"tag": "text", "text": config.name, "style": []}
        ])
        
        # End time
        content.append([
            {"tag": "text", "text": "End Time: ", "style": ["bold"]},
            {"tag": "text", "text": end_time, "style": []}
        ])
        
        # Optional information (using Font Awesome style icons)
        if config.test_version:
            content.append([
                {"tag": "text", "text": "⚡ ", "style": []},
                {"tag": "text", "text": "Test Version: ", "style": ["bold"]},
                {"tag": "text", "text": config.test_version, "style": []}
            ])
        
        if config.test_environment:
            content.append([
                {"tag": "text", "text": "🌍 ", "style": []},
                {"tag": "text", "text": "Test Environment: ", "style": ["bold"]},
                {"tag": "text", "text": config.test_environment, "style": []}
            ])
        
        if config.build_number:
            content.append([
                {"tag": "text", "text": "🔧 ", "style": []},
                {"tag": "text", "text": "Build: ", "style": ["bold"]},
                {"tag": "text", "text": config.build_number, "style": []}
            ])
        
        # Empty line
        content.append([{"tag": "text", "text": "", "style": []}])
        
        # Execution results title (using Font Awesome style icons)
        content.append([
            {"tag": "text", "text": "📊 ", "style": []},
            {"tag": "text", "text": "Execution Results:", "style": ["bold"]}
        ])
        
        # Pass rate and fail rate
        content.append([
            {"tag": "text", "text": "  • Pass Rate: ", "style": []},
            {"tag": "text", "text": f"{stats['pass_rate']:.1f}%", "style": ["bold"]}
        ])
        
        content.append([
            {"tag": "text", "text": "  • Fail Rate: ", "style": []},
            {"tag": "text", "text": f"{stats['fail_rate']:.1f}%", "style": ["bold"]}
        ])
        
        # Detailed statistics
        executed_cases = config.executed_cases or 0
        passed_cases = config.passed_cases or 0
        failed_cases = config.failed_cases or 0
        total_cases = config.total_test_cases or 0
        
        content.append([
            {"tag": "text", "text": f"  • Executed: {executed_cases}/{total_cases} test cases", "style": []}
        ])
        
        content.append([
            {"tag": "text", "text": f"  • Passed: {passed_cases} cases", "style": []}
        ])
        
        content.append([
            {"tag": "text", "text": f"  • Failed: {failed_cases} cases", "style": []}
        ])
        
        # Bug count (if any) (using Font Awesome style icons)
        if stats['bug_count'] > 0:
            content.append([
                {"tag": "text", "text": "  • ⚠ ", "style": []},
                {"tag": "text", "text": "Bug Count: ", "style": ["bold"]},
                {"tag": "text", "text": str(stats['bug_count']), "style": []}
            ])
        
        # Empty line
        content.append([{"tag": "text", "text": "", "style": []}])
        
        # View details link
        content.append([
            {"tag": "text", "text": "🔗 ", "style": []},
            {"tag": "a", "text": "View Details", "href": url, "style": ["bold"]}
        ])
        
        # Build Rich Text format for Lark API
        rich_text = {
            "zh_cn": {
                "title": "Test Execution Notification",
                "content": content
            }
        }

        return rich_text
    
    def compute_end_stats(self, team_id: int, config_id: int, db: Session = None) -> Dict:
        """
        計算結束執行所需的統計資訊

        Args:
            team_id: 團隊 ID
            config_id: 配置 ID
            db: 資料庫會話（如果提供則使用，否則建立新的）

        Returns:
            統計資訊：{"pass_rate": float, "fail_rate": float, "bug_count": int}
        """
        close_db = False
        if db is None:
            engine = get_sync_engine()
            SyncSession = sessionmaker(bind=engine)
            db = SyncSession()
            close_db = True

        try:
            # 查詢配置
            config = db.query(TestRunConfigDB).filter(
                TestRunConfigDB.id == config_id,
                TestRunConfigDB.team_id == team_id
            ).first()

            if not config:
                logger.error(f"找不到 Test Run Config: team_id={team_id}, config_id={config_id}")
                return {"pass_rate": 0.0, "fail_rate": 0.0, "bug_count": 0}

            # 計算通過率和失敗率
            executed_cases = config.executed_cases or 0
            passed_cases = config.passed_cases or 0
            failed_cases = config.failed_cases or 0

            if executed_cases > 0:
                pass_rate = (passed_cases / executed_cases) * 100
                fail_rate = (failed_cases / executed_cases) * 100
            else:
                pass_rate = 0.0
                fail_rate = 0.0

            # 計算 bug 數量（從所有 TestRunItem 的 bug_tickets_json 彙整去重）
            items = db.query(TestRunItemDB).filter(
                TestRunItemDB.config_id == config_id,
                TestRunItemDB.team_id == team_id
            ).all()

            all_bugs = set()
            for item in items:
                if item.bug_tickets_json:
                    try:
                        bug_tickets = json.loads(item.bug_tickets_json)
                        if isinstance(bug_tickets, list):
                            all_bugs.update(bug_tickets)
                    except (json.JSONDecodeError, TypeError):
                        continue

            bug_count = len(all_bugs)

            return {
                "pass_rate": pass_rate,
                "fail_rate": fail_rate,
                "bug_count": bug_count
            }

        finally:
            if close_db:
                db.close()
    
    def send_execution_started(self, config_id: int, team_id: int) -> None:
        """
        發送「開始執行」通知（背景任務入口）

        Args:
            config_id: Test Run 配置 ID
            team_id: 團隊 ID
        """
        engine = get_sync_engine()
        SyncSession = sessionmaker(bind=engine)
        db = SyncSession()
        try:
            # 查詢配置
            config = db.query(TestRunConfigDB).filter(
                TestRunConfigDB.id == config_id,
                TestRunConfigDB.team_id == team_id
            ).first()

            if not config:
                logger.error(f"找不到 Test Run Config: team_id={team_id}, config_id={config_id}")
                return

            # 檢查是否啟用通知
            if not config.notifications_enabled:
                logger.debug(f"Config {config_id} 未啟用通知")
                return

            # 解析群組 IDs
            chat_ids = []
            if config.notify_chat_ids_json:
                try:
                    chat_ids = json.loads(config.notify_chat_ids_json)
                    if not isinstance(chat_ids, list):
                        chat_ids = []
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"無法解析 notify_chat_ids_json: {config.notify_chat_ids_json}")
                    return

            if not chat_ids:
                logger.debug(f"Config {config_id} 沒有設定通知群組")
                return

            # 組裝訊息
            message = self.build_start_message(config, self.settings.app.base_url)

            # 發送通知
            logger.info(f"發送開始執行通知: {config.name} (config_id={config_id})")
            results = self.send_message_to_chats(chat_ids, message)

            # 記錄結果
            success_count = sum(1 for result in results.values() if result["ok"])
            logger.info(f"通知發送完成: 成功 {success_count}/{len(chat_ids)} 個群組")

        except Exception as e:
            logger.error(f"發送開始執行通知時發生錯誤: {str(e)}")
        finally:
            db.close()
    
    def send_execution_ended(self, config_id: int, team_id: int) -> None:
        """
        發送「結束執行」通知（背景任務入口）

        Args:
            config_id: Test Run 配置 ID
            team_id: 團隊 ID
        """
        engine = get_sync_engine()
        SyncSession = sessionmaker(bind=engine)
        db = SyncSession()
        try:
            # 查詢配置
            config = db.query(TestRunConfigDB).filter(
                TestRunConfigDB.id == config_id,
                TestRunConfigDB.team_id == team_id
            ).first()

            if not config:
                logger.error(f"找不到 Test Run Config: team_id={team_id}, config_id={config_id}")
                return

            # 檢查是否啟用通知
            if not config.notifications_enabled:
                logger.debug(f"Config {config_id} 未啟用通知")
                return

            # 解析群組 IDs
            chat_ids = []
            if config.notify_chat_ids_json:
                try:
                    chat_ids = json.loads(config.notify_chat_ids_json)
                    if not isinstance(chat_ids, list):
                        chat_ids = []
                except (json.JSONDecodeError, TypeError):
                    logger.error(f"無法解析 notify_chat_ids_json: {config.notify_chat_ids_json}")
                    return

            if not chat_ids:
                logger.debug(f"Config {config_id} 沒有設定通知群組")
                return

            # 計算統計資訊
            stats = self.compute_end_stats(team_id, config_id, db)

            # 組裝訊息
            message = self.build_end_message(config, stats, self.settings.app.base_url)

            # 發送通知
            logger.info(f"發送結束執行通知: {config.name} (config_id={config_id})")
            results = self.send_message_to_chats(chat_ids, message)

            # 記錄結果
            success_count = sum(1 for result in results.values() if result["ok"])
            logger.info(f"通知發送完成: 成功 {success_count}/{len(chat_ids)} 個群組")

        except Exception as e:
            logger.error(f"發送結束執行通知時發生錯誤: {str(e)}")
        finally:
            db.close()


# 全域服務實例
_lark_notify_service = None

def get_lark_notify_service() -> LarkNotifyService:
    """取得 Lark 通知服務實例"""
    global _lark_notify_service
    if _lark_notify_service is None:
        _lark_notify_service = LarkNotifyService()
    return _lark_notify_service
