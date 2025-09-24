import argparse
import logging
import os
import re
import sys
import json
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

# --- 環境設定：確保能從 app 目錄導入 ---
# 將專案根目錄加入 Python 路徑
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- 環境設定結束 ---

from app.database import get_async_session
from app.models.database_models import Team as TeamDB, TestCaseLocal as TestCaseLocalDB
from app.services.lark_client import LarkClient
from app.config import settings

# --- 日誌設定 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- 日誌設定結束 ---


def parse_lark_url(url: str) -> dict | None:
    """
    從 Lark 表格的完整 URL 中解析出 wiki_token 和 table_id。
    範例 URL: https://<domain>.larksuite.com/wiki/<wiki_token>/table/<table_id>
    """
    match = re.search(r'/wiki/(?P<wiki_token>\w+)/table/(?P<table_id>\w+)', url)
    if match:
        return match.groupdict()
    return None

async def select_team(db: AsyncSession) -> TeamDB | None:
    """
    從資料庫中讀取所有團隊，讓使用者透過選單選擇。
    """
    result = await db.execute(select(TeamDB).order_by(TeamDB.name))
    teams = result.scalars().all()
    if not teams:
        logger.error("資料庫中找不到任何團隊。")
        return None

    print("\n請選擇要進行同步的團隊：")
    for i, team in enumerate(teams):
        print(f"  [{i + 1}] {team.name} (ID: {team.id})")

    while True:
        try:
            choice = await asyncio.to_thread(input, f"請輸入選項編號 (1-{len(teams)}): ")
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(teams):
                return teams[choice_idx]
            else:
                print("無效的選項，請重新輸入。")
        except (ValueError, IndexError):
            print("輸入無效，請輸入數字。")
        except (KeyboardInterrupt, EOFError):
            print("\n操作已取消。")
            return None

class TestCaseSynchronizer:
    """
    處理 Test Case 本地與遠端同步的核心邏輯。
    """
    def __init__(self, db: AsyncSession, team: TeamDB, lark_client: LarkClient, lark_table_id: str):
        self.db = db
        self.team = team
        self.lark_client = lark_client
        self.lark_table_id = lark_table_id
        self.plan = {}
        self.local_cases = {}
        self.remote_cases = {}
        self.raw_remote_records = [] # 保存原始遠端紀錄

    async def _get_local_cases(self):
        """獲取本地資料庫的 Test Cases"""
        logger.info(f"正在從本地資料庫讀取團隊 '{self.team.name}' 的 Test Cases...")
        result = await self.db.execute(
            select(TestCaseLocalDB).where(TestCaseLocalDB.team_id == self.team.id)
        )
        cases = result.scalars().all()
        return {case.test_case_number: case for case in cases}

    async def _get_remote_cases(self):
        """獲取遠端 Lark 表格的 Test Cases"""
        logger.info(f"正在從 Lark 表格 (ID: {self.lark_table_id}) 讀取所有紀錄...")
        try:
            self.raw_remote_records = await asyncio.to_thread(self.lark_client.get_all_records, self.lark_table_id)
            return {
                rec['fields'].get('Test Case Number'): rec
                for rec in self.raw_remote_records if rec.get('fields', {}).get('Test Case Number')
            }
        except Exception as e:
            logger.error(f"讀取 Lark 紀錄失敗: {e}")
            return {}

    def _deduplicate(self, cases_dict: dict, source: str) -> tuple[dict, list]:
        """
        對 Test Case 列表進行去重，只保留最新一筆。
        """
        logger.info(f"正在對 {source} 資料進行去重...")
        processed_cases = {}
        to_delete = []
        
        grouped_cases = {}
        for key, case in cases_dict.items():
            if key not in grouped_cases:
                grouped_cases[key] = []
            grouped_cases[key].append(case)

        for number, items in grouped_cases.items():
            if len(items) > 1:
                logger.warning(f"在 {source} 發現重複的 Test Case Number: '{number}' (共 {len(items)} 筆)")
                if source == 'local':
                    items.sort(key=lambda x: x.updated_at, reverse=True)
                else:
                    items.sort(key=lambda x: x.get('updated_time', 0), reverse=True)
                
                processed_cases[number] = items[0]
                to_delete.extend(items[1:])
            else:
                processed_cases[number] = items[0]
        
        return processed_cases, to_delete

    async def analyze(self):
        """
        比對本地與遠端資料，產生同步計畫。
        """
        local_raw = await self._get_local_cases()
        remote_raw = await self._get_remote_cases()

        remote_blank_rows = [rec for rec in self.raw_remote_records if not rec.get('fields',{}).get('Test Case Number')]
        if remote_blank_rows:
            logger.info(f"在 Lark 上發現 {len(remote_blank_rows)} 筆 Test Case Number 為空的行，將被清除。")

        self.local_cases, local_duplicates_to_delete = self._deduplicate(local_raw, 'local')
        self.remote_cases, remote_duplicates_to_delete = self._deduplicate(remote_raw, 'remote')

        local_keys = set(self.local_cases.keys())
        remote_keys = set(self.remote_cases.keys())

        self.plan = {
            'create_local': list(remote_keys - local_keys),
            'create_remote': list(local_keys - remote_keys),
            'update_local': [],
            'update_remote': list(local_keys & remote_keys),
            'delete_local': [c.id for c in local_duplicates_to_delete],
            'delete_remote': [r['record_id'] for r in remote_duplicates_to_delete] + [r['record_id'] for r in remote_blank_rows],
        }
        logger.info("資料分析完成，已產生同步計畫。")

    def preview_plan(self):
        """
        顯示同步計畫的摘要。
        """
        if not self.plan:
            print("\n尚未分析資料，請先執行分析。")
            return

        print("\n--- 同步計畫摘要 ---")
        print(f"  [本地新增]: {len(self.plan['create_local'])} 筆 (從 Lark 同步到本地)")
        print(f"  [遠端新增]: {len(self.plan['create_remote'])} 筆 (從本地同步到 Lark)")
        print(f"  [遠端更新]: {len(self.plan['update_remote'])} 筆 (以本地資料覆蓋 Lark)")
        print(f"  [本地刪除]: {len(self.plan['delete_local'])} 筆 (重複資料)")
        print(f"  [遠端刪除]: {len(self.plan['delete_remote'])} 筆 (重複或空白資料)")
        print("----------------------")

    def display_detailed_plan(self):
        """
        顯示詳細的逐項變更計畫。
        """
        if not self.plan:
            print("\n尚未分析資料，請先執行分析。")
            return False

        print("\n--- 詳細變更項目 ---")
        has_changes = False

        remote_by_record_id = {rec['record_id']: rec for rec in self.raw_remote_records if 'record_id' in rec}
        local_by_id = {case.id: case for case in self.local_cases.values()}

        def print_section(title, keys, source_dict, is_local_source=False):
            nonlocal has_changes
            if not keys:
                return
            has_changes = True
            print(f"\n{title}:")
            for key in keys:
                item = source_dict.get(key)
                if item:
                    title_text = item.title if is_local_source else item.get('fields', {}).get('Title', 'N/A')
                    print(f"  - {key}: {title_text}")

        print_section("[+] 將在 Lark 新增 (來自本地)", self.plan['create_remote'], self.local_cases, is_local_source=True)
        print_section("[+] 將在本地新增 (來自 Lark)", self.plan['create_local'], self.remote_cases)
        print_section("[*] 將在 Lark 更新 (以本地資料為準)", self.plan['update_remote'], self.local_cases, is_local_source=True)

        if self.plan['delete_local']:
            has_changes = True
            print("\n[-] 將在本地刪除 (重複資料):")
            for case_id in self.plan['delete_local']:
                case = local_by_id.get(case_id)
                if case:
                    print(f"  - {case.test_case_number}: {case.title}")

        if self.plan['delete_remote']:
            has_changes = True
            print("\n[-] 將在 Lark 刪除 (重複或空白資料):")
            for record_id in self.plan['delete_remote']:
                record = remote_by_record_id.get(record_id)
                if record:
                    number = record.get('fields', {}).get('Test Case Number', '[空白行]')
                    title = record.get('fields', {}).get('Title', 'N/A')
                    print(f"  - {number}: {title} (Record ID: {record_id})")
        
        if not has_changes:
            print("\n所有資料皆已同步，無需變更。")
        
        print("----------------------")
        return has_changes

    def _convert_local_to_lark_fields(self, case: TestCaseLocalDB) -> dict:
        """將本地 DB 物件轉換為 Lark API 的 fields 字典。"""
        fields = {
            "Test Case Number": case.test_case_number,
            "Title": case.title,
            "Priority": case.priority.value if case.priority else None,
            "Precondition": case.precondition,
            "Steps": case.steps,
            "Expected Result": case.expected_result,
        }
        
        # 處理 Assignee (人員) 欄位
        try:
            if case.assignee_json:
                assignee_data = json.loads(case.assignee_json)
                # Lark 人員欄位預期收到一個只包含 id 的物件列表
                if isinstance(assignee_data, list):
                    # 如果是多人員欄位
                    user_ids = [{"id": user['id']} for user in assignee_data if isinstance(user, dict) and 'id' in user]
                    if user_ids:
                        fields['Assignee'] = user_ids
                elif isinstance(assignee_data, dict) and 'id' in assignee_data:
                    # 如果是單人員欄位
                    fields['Assignee'] = [{'id': assignee_data['id']}]
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"無法解析或轉換 TC '{case.test_case_number}' 的 assignee_json: {case.assignee_json}, 錯誤: {e}")

        # 處理 TCG (關聯) 欄位
        try:
            if case.tcg_json:
                tcg_data = json.loads(case.tcg_json)
                # Lark 關聯欄位預期收到 record_id 的字串列表
                record_ids = []
                if isinstance(tcg_data, list):
                    for item in tcg_data:
                        if isinstance(item, dict) and 'record_ids' in item and isinstance(item['record_ids'], list):
                            record_ids.extend(item['record_ids'])
                if record_ids:
                    fields['TCG'] = record_ids
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"無法解析或轉換 TC '{case.test_case_number}' 的 tcg_json: {case.tcg_json}, 錯誤: {e}")

        return {k: v for k, v in fields.items() if v is not None}

    def _convert_lark_to_local_case(self, record: dict) -> TestCaseLocalDB:
        """將 Lark API record 轉換為本地 DB 物件。"""
        from app.models.lark_types import Priority
        
        fields = record.get('fields', {})
        
        priority_str = fields.get("Priority")
        priority_enum = Priority(priority_str) if priority_str in [p.value for p in Priority] else Priority.MEDIUM

        assignee_val = fields.get("Assignee")
        tcg_val = fields.get("TCG")

        new_case = TestCaseLocalDB(
            team_id=self.team.id,
            lark_record_id=record.get('record_id'),
            test_case_number=fields.get("Test Case Number"),
            title=fields.get("Title"),
            priority=priority_enum,
            precondition=fields.get("Precondition"),
            steps=fields.get("Steps"),
            expected_result=fields.get("Expected Result"),
            assignee_json=json.dumps(assignee_val, ensure_ascii=False) if assignee_val else None,
            tcg_json=json.dumps(tcg_val, ensure_ascii=False) if tcg_val else None,
            lark_created_at=datetime.fromtimestamp(record.get('created_time', 0) / 1000),
            lark_updated_at=datetime.fromtimestamp(record.get('updated_time', 0) / 1000),
        )
        return new_case

    async def execute_plan(self):
        """
        執行同步計畫。
        """
        if not self.plan:
            print("\n尚未產生計畫，無法執行。")
            return

        logger.info("--- 開始執行同步 ---")
        try:
            # 1. 刪除操作
            if self.plan['delete_local']:
                logger.info(f"正在刪除 {len(self.plan['delete_local'])} 筆本地重複紀錄...")
                await self.db.execute(
                    delete(TestCaseLocalDB).where(TestCaseLocalDB.id.in_(self.plan['delete_local']))
                )

            if self.plan['delete_remote']:
                logger.info(f"正在刪除 {len(self.plan['delete_remote'])} 筆遠端重複或空白紀錄...")
                await asyncio.to_thread(self.lark_client.batch_delete_records, self.lark_table_id, self.plan['delete_remote'])

            # 2. 本地新增
            if self.plan['create_local']:
                logger.info(f"正在新增 {len(self.plan['create_local'])} 筆紀錄到本地...")
                new_local_cases = []
                for key in self.plan['create_local']:
                    record = self.remote_cases.get(key)
                    if record:
                        new_case = self._convert_lark_to_local_case(record)
                        new_local_cases.append(new_case)
                if new_local_cases:
                    self.db.add_all(new_local_cases)

            # 3. 遠端新增
            if self.plan['create_remote']:
                logger.info(f"正在新增 {len(self.plan['create_remote'])} 筆紀錄到 Lark...")
                records_to_create = []
                for key in self.plan['create_remote']:
                    case = self.local_cases.get(key)
                    if case:
                        records_to_create.append(self._convert_local_to_lark_fields(case))
                
                if records_to_create:
                    await asyncio.to_thread(self.lark_client.batch_create_records, self.lark_table_id, records_to_create)

            # 4. 遠端更新
            if self.plan['update_remote']:
                logger.info(f"正在更新 {len(self.plan['update_remote'])} 筆 Lark 紀錄...")
                records_to_update = []
                for key in self.plan['update_remote']:
                    case = self.local_cases.get(key)
                    remote_record = self.remote_cases.get(key)
                    if case and remote_record:
                        records_to_update.append({
                            "record_id": remote_record['record_id'],
                            "fields": self._convert_local_to_lark_fields(case)
                        })

                if records_to_update:
                    await asyncio.to_thread(self.lark_client.parallel_update_records, self.lark_table_id, records_to_update)

            await self.db.commit()
            logger.info("--- 同步執行成功 ---")

        except Exception as e:
            await self.db.rollback()
            logger.error(f"同步過程中發生錯誤: {e}", exc_info=True)
            print("錯誤發生，資料庫操作已還原。")

async def main():
    """
    主執行函式。
    """
    parser = argparse.ArgumentParser(description="互動式 Test Case 同步工具")
    parser.add_argument('--team-id', type=int, help="要同步的團隊 ID (可選)")
    parser.add_argument('--lark-url', type=str, help="要同步的 Lark 表格完整 URL (可選，可覆寫團隊預設)")
    args = parser.parse_args()

    async with get_async_session() as db:
        selected_team = None
        if args.team_id:
            result = await db.execute(select(TeamDB).where(TeamDB.id == args.team_id))
            selected_team = result.scalars().first()
            if not selected_team:
                logger.error(f"找不到 ID 為 {args.team_id} 的團隊。")
                return
        else:
            selected_team = await select_team(db)

        if not selected_team:
            return

        logger.info(f"已選擇團隊: {selected_team.name}")

        lark_config = {}
        if args.lark_url:
            logger.info("偵測到 --lark-url 參數，將覆寫團隊預設設定。")
            parsed_url = parse_lark_url(args.lark_url)
            if not parsed_url:
                logger.error("提供的 Lark URL 格式不正確。")
                return
            lark_config['wiki_token'] = parsed_url['wiki_token']
            lark_config['table_id'] = parsed_url['table_id']
        else:
            logger.info("使用團隊的預設 Lark 設定。")
            if not (selected_team.wiki_token and selected_team.test_case_table_id):
                logger.error(f"團隊 '{selected_team.name}' 尚未設定預設的 Lark wiki_token 或 test_case_table_id。")
                return
            lark_config['wiki_token'] = selected_team.wiki_token
            lark_config['table_id'] = selected_team.test_case_table_id

        print(f"\n將要同步的 Lark 表格 ID: {lark_config['table_id']}\n")

        lark_client = LarkClient(app_id=settings.lark.app_id, app_secret=settings.lark.app_secret)
        if not lark_client.set_wiki_token(lark_config['wiki_token']):
            logger.error("設定 Lark wiki token 失敗，請檢查 token 是否正確。")
            return
            
        synchronizer = TestCaseSynchronizer(db, selected_team, lark_client, lark_config['table_id'])

        while True:
            print("\n--- 主選單 ---")
            print("  [1] 分析本地與遠端資料")
            print("  [2] 預覽同步計畫 (摘要)")
            print("  [3] 執行同步 (含詳細預覽)")
            print("  [4] 離開")
            choice = await asyncio.to_thread(input, "請輸入選項: ")

            if choice == '1':
                await synchronizer.analyze()
            elif choice == '2':
                synchronizer.preview_plan()
            elif choice == '3':
                if not synchronizer.plan:
                    print("\n請先執行 [1] 分析資料。")
                    continue
                has_changes = synchronizer.display_detailed_plan()
                if has_changes:
                    confirm = await asyncio.to_thread(input, "\n確定要執行以上所有變更嗎？此操作不可逆 (y/N): ")
                    if confirm.lower() == 'y':
                        await synchronizer.execute_plan()
                    else:
                        print("執行已取消。")
            elif choice == '4':
                print("程式結束。")
                break
            else:
                print("無效的選項，請重新輸入。")


if __name__ == "__main__":
    asyncio.run(main())
