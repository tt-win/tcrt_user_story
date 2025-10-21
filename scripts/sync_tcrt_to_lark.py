import argparse
import logging
import os
import sys
import json
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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


class TCRTToLarkSynchronizer:
    """
    單向同步：從本地資料庫 (TCRT) 寫入到 Lark。
    改為增量更新模式：新增新記錄，更新已存在的記錄，刪除重複或空白記錄。
    """
    def __init__(self, db: AsyncSession, team: TeamDB, lark_client: LarkClient, lark_table_id: str, dry_run: bool = False):
        self.db = db
        self.team = team
        self.lark_client = lark_client
        self.lark_table_id = lark_table_id
        self.dry_run = dry_run
        self.local_cases = {}  # Dict: {test_case_number: case}
        self.remote_cases = {}  # Dict: {test_case_number: record}
        self.raw_remote_records = []  # 保存原始遠端紀錄
        self.plan = {}

    async def load_local_data(self):
        """載入本地資料庫的所有 Test Cases"""
        logger.info(f"正在從本地資料庫讀取團隊 '{self.team.name}' 的所有 Test Cases...")
        result = await self.db.execute(
            select(TestCaseLocalDB).where(TestCaseLocalDB.team_id == self.team.id).order_by(TestCaseLocalDB.test_case_number)
        )
        cases = result.scalars().all()
        self.local_cases = {case.test_case_number: case for case in cases}
        logger.info(f"已載入 {len(self.local_cases)} 筆本地 Test Cases")

    async def load_remote_data(self):
        """載入遠端 Lark 表格的所有記錄"""
        logger.info(f"正在從 Lark 表格 (ID: {self.lark_table_id}) 讀取所有紀錄...")
        try:
            self.raw_remote_records = await asyncio.to_thread(self.lark_client.get_all_records, self.lark_table_id)
            self.remote_cases = {
                rec['fields'].get('Test Case Number'): rec
                for rec in self.raw_remote_records if rec.get('fields', {}).get('Test Case Number')
            }
            logger.info(f"已載入 {len(self.raw_remote_records)} 筆 Lark 紀錄 (有效記錄: {len(self.remote_cases)} 筆)")
        except Exception as e:
            logger.error(f"讀取 Lark 紀錄失敗: {e}")
            self.raw_remote_records = []
            self.remote_cases = {}

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
        logger.info("開始分析本地與遠端資料差異...")

        # 去重
        self.local_cases, _ = self._deduplicate(self.local_cases, 'local')
        self.remote_cases, remote_duplicates_to_delete = self._deduplicate(self.remote_cases, 'remote')

        # 找出空白記錄
        remote_blank_rows = [rec for rec in self.raw_remote_records if not rec.get('fields', {}).get('Test Case Number')]
        if remote_blank_rows:
            logger.info(f"在 Lark 上發現 {len(remote_blank_rows)} 筆 Test Case Number 為空的行，將被清除。")

        local_keys = set(self.local_cases.keys())
        remote_keys = set(self.remote_cases.keys())

        self.plan = {
            'create_remote': list(local_keys - remote_keys),  # 只在本地有，需要新增到 Lark
            'update_remote': list(local_keys & remote_keys),  # 本地和遠端都有，需要更新 Lark
            'delete_remote': [r['record_id'] for r in remote_duplicates_to_delete] + [r['record_id'] for r in remote_blank_rows],
        }
        logger.info("資料分析完成，已產生同步計畫。")

    def preview_plan(self):
        """顯示同步計畫預覽"""
        if not self.plan:
            print("\n尚未分析資料，請先執行分析。")
            return

        print("\n" + "=" * 60)
        print("同步計畫預覽")
        print("=" * 60)
        print(f"團隊: {self.team.name}")
        print(f"Lark 表格 ID: {self.lark_table_id}")
        print(f"模式: {'DRY RUN (不會實際執行)' if self.dry_run else '正式執行'}")
        print("-" * 60)

        print(f"\n[1] 在 Lark 新增記錄:")
        print(f"    - 總計: {len(self.plan['create_remote'])} 筆 (只在本地有的記錄)")

        print(f"\n[2] 在 Lark 更新記錄:")
        print(f"    - 總計: {len(self.plan['update_remote'])} 筆 (本地和遠端都有)")

        print(f"\n[3] 在 Lark 刪除記錄:")
        print(f"    - 總計: {len(self.plan['delete_remote'])} 筆 (重複或空白記錄)")

        if len(self.plan['create_remote']) > 0:
            print("\n本地新增預覽 (前 10 筆):")
            for i, key in enumerate(self.plan['create_remote'][:10]):
                case = self.local_cases.get(key)
                if case:
                    print(f"    {i+1}. {case.test_case_number}: {case.title}")
            if len(self.plan['create_remote']) > 10:
                print(f"    ... (還有 {len(self.plan['create_remote']) - 10} 筆)")

        print("\n" + "=" * 60)

    def _convert_local_to_lark_fields(self, case: TestCaseLocalDB) -> dict:
        """將本地 DB 物件轉換為 Lark API 的 fields 字典"""
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
            if hasattr(case, 'assignee_json') and case.assignee_json is not None:
                assignee_data = json.loads(str(case.assignee_json))
                if isinstance(assignee_data, list):
                    user_ids = [{"id": user['id']} for user in assignee_data if isinstance(user, dict) and 'id' in user]
                    if user_ids:
                        fields['Assignee'] = user_ids
                elif isinstance(assignee_data, dict) and 'id' in assignee_data:
                    fields['Assignee'] = [{'id': assignee_data['id']}]
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"無法解析 TC '{case.test_case_number}' 的 assignee_json: {case.assignee_json}, 錯誤: {e}")

        # 處理 TCG (關聯) 欄位
        try:
            if hasattr(case, 'tcg_json') and case.tcg_json is not None:
                tcg_data = json.loads(str(case.tcg_json))
                record_ids = []
                if isinstance(tcg_data, list):
                    for item in tcg_data:
                        if isinstance(item, dict) and 'record_ids' in item and isinstance(item['record_ids'], list):
                            record_ids.extend(item['record_ids'])
                if record_ids:
                    fields['TCG'] = record_ids
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"無法解析 TC '{case.test_case_number}' 的 tcg_json: {case.tcg_json}, 錯誤: {e}")

        return {k: v for k, v in fields.items() if v is not None}

    async def execute(self):
        """執行同步操作 (增量更新模式)"""
        if not self.plan:
            print("\n尚未產生計畫，無法執行。")
            return

        if self.dry_run:
            print("\n[DRY RUN 模式] 不會實際執行任何操作")
            return

        print("\n開始執行同步...")

        try:
            # 步驟 1: 刪除重複或空白的遠端記錄
            if self.plan['delete_remote']:
                logger.info(f"正在刪除 {len(self.plan['delete_remote'])} 筆 Lark 上的重複或空白紀錄...")
                await asyncio.to_thread(
                    self.lark_client.batch_delete_records,
                    self.lark_table_id,
                    self.plan['delete_remote']
                )
                logger.info("遠端重複/空白紀錄刪除完成")
            else:
                logger.info("無需刪除重複或空白紀錄")

            # 步驟 2: 新增本地特有的記錄到 Lark
            if self.plan['create_remote']:
                logger.info(f"正在新增 {len(self.plan['create_remote'])} 筆本地特有的記錄到 Lark...")
                records_to_create = []
                for key in self.plan['create_remote']:
                    case = self.local_cases.get(key)
                    if case:
                        records_to_create.append(self._convert_local_to_lark_fields(case))

                if records_to_create:
                    await asyncio.to_thread(
                        self.lark_client.batch_create_records,
                        self.lark_table_id,
                        records_to_create
                    )
                    logger.info("本地特有記錄新增完成")
            else:
                logger.info("無需新增記錄")

            # 步驟 3: 更新本地和遠端都有的記錄
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
                    # 使用 parallel_update_records 如果可用，否則使用 batch_update
                    if hasattr(self.lark_client, 'parallel_update_records'):
                        await asyncio.to_thread(
                            self.lark_client.parallel_update_records,
                            self.lark_table_id,
                            records_to_update
                        )
                    else:
                        # 備用方案：逐個更新
                        for record in records_to_update:
                            await asyncio.to_thread(
                                self.lark_client.update_record,
                                self.lark_table_id,
                                record['record_id'],
                                record['fields']
                            )
                    logger.info("Lark 紀錄更新完成")
            else:
                logger.info("無需更新記錄")

            print("\n✅ 同步執行成功！")

        except Exception as e:
            logger.error(f"同步過程中發生錯誤: {e}", exc_info=True)
            print(f"\n❌ 同步失敗: {e}")
            raise


async def sync_single_team(db: AsyncSession, team: TeamDB, dry_run: bool = False, auto_confirm: bool = False):
    """
    同步單個團隊。
    返回 (success: bool, message: str)
    """
    try:
        # 檢查團隊是否有 Lark 配置
        if not team.wiki_token or not team.test_case_table_id:
            logger.warning(f"團隊 '{team.name}' 尚未設定 Lark wiki_token 或 test_case_table_id，跳過")
            return False, f"跳過：{team.name} 未設定 Lark 配置"

        # 初始化 Lark 客戶端
        lark_client = LarkClient(app_id=settings.lark.app_id, app_secret=settings.lark.app_secret)
        if not lark_client.set_wiki_token(team.wiki_token):
            logger.error(f"設定 Lark wiki token 失敗（團隊：{team.name}）")
            return False, f"失敗：{team.name} - 無法設定 Lark token"

        # 執行同步
        synchronizer = TCRTToLarkSynchronizer(
            db=db,
            team=team,
            lark_client=lark_client,
            lark_table_id=team.test_case_table_id,
            dry_run=dry_run
        )

        # 載入資料
        await synchronizer.load_local_data()
        await synchronizer.load_remote_data()

        # 分析資料差異
        await synchronizer.analyze()

        # 檢查是否有變更
        has_changes = (
            len(synchronizer.plan.get('create_remote', [])) > 0 or
            len(synchronizer.plan.get('update_remote', [])) > 0 or
            len(synchronizer.plan.get('delete_remote', [])) > 0
        )

        if not has_changes:
            logger.info(f"團隊 '{team.name}' 無需同步")
            return True, f"成功：{team.name} - 無需同步"

        # 執行同步
        if not dry_run:
            if auto_confirm:
                await synchronizer.execute()
            else:
                # 顯示計畫並詢問
                print(f"\n--- 同步計畫：{team.name} ---")
                synchronizer.preview_plan()
                confirm = await asyncio.to_thread(
                    input,
                    f"\n確定要為 '{team.name}' 執行同步嗎？(yes/N): "
                )
                if confirm.lower() == 'yes':
                    await synchronizer.execute()
                else:
                    logger.info(f"已跳過團隊 '{team.name}' 的同步")
                    return True, f"已跳過：{team.name}"
        else:
            print(f"\n--- 同步計畫預覽：{team.name} ---")
            synchronizer.preview_plan()

        logger.info(f"團隊 '{team.name}' 同步完成")
        return True, f"成功：{team.name} - 同步完成"

    except Exception as e:
        logger.error(f"同步團隊 '{team.name}' 時發生錯誤: {e}", exc_info=True)
        return False, f"失敗：{team.name} - {str(e)}"


async def main():
    """主執行函式"""
    parser = argparse.ArgumentParser(
        description="單向同步工具：從 TCRT (本地資料庫) 寫入到 Lark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  # 互動式選擇團隊並預覽計畫 (dry-run)
  python scripts/sync_tcrt_to_lark.py --dry-run

  # 指定團隊 ID 並執行同步
  python scripts/sync_tcrt_to_lark.py --team-id 1

  # 指定團隊 ID 和 Lark URL
  python scripts/sync_tcrt_to_lark.py --team-id 1 --lark-url "https://xxx.larksuite.com/wiki/xxx/table/xxx"

  # 自動同步所有團隊 (dry-run)
  python scripts/sync_tcrt_to_lark.py --sync-all --dry-run

  # 自動同步所有團隊 (實際執行，自動確認)
  python scripts/sync_tcrt_to_lark.py --sync-all -y
        """
    )
    parser.add_argument('--team-id', type=int, help="要同步的團隊 ID")
    parser.add_argument('--sync-all', action='store_true', help="自動同步所有具有 Lark 配置的團隊")
    parser.add_argument('--lark-url', type=str, help="Lark 表格完整 URL (可選，可覆寫團隊預設，僅在單一團隊模式下生效)")
    parser.add_argument('--dry-run', action='store_true', help="只預覽計畫，不實際執行")
    parser.add_argument('--yes', '-y', action='store_true', help="自動確認，不詢問")
    args = parser.parse_args()

    # 檢查選項衝突
    if args.sync_all and args.team_id:
        logger.error("--sync-all 和 --team-id 不能同時使用")
        return
    if args.sync_all and args.lark_url:
        logger.error("--sync-all 模式下不支援 --lark-url 參數")
        return

    async with get_async_session() as db:
        # 同步所有團隊模式
        if args.sync_all:
            logger.info("開始自動同步所有團隊...")
            result = await db.execute(select(TeamDB).order_by(TeamDB.name))
            teams = result.scalars().all()

            if not teams:
                logger.error("資料庫中找不到任何團隊")
                return

            print(f"\n將要同步 {len(teams)} 個團隊\n")

            results = []
            for i, team in enumerate(teams, 1):
                print(f"[{i}/{len(teams)}] 正在處理團隊 '{team.name}'...")
                success, message = await sync_single_team(
                    db=db,
                    team=team,
                    dry_run=args.dry_run,
                    auto_confirm=args.yes
                )
                results.append((team.name, success, message))

            # 顯示總結
            print("\n" + "=" * 60)
            print("同步結果總結")
            print("=" * 60)
            for team_name, success, message in results:
                status = "✅" if success else "❌"
                print(f"{status} {message}")

            successful = sum(1 for _, success, _ in results if success)
            print(f"\n成功: {successful}/{len(teams)} 個團隊")
            print("=" * 60)
            return

        # 單一團隊模式
        # 選擇團隊
        if args.team_id:
            result = await db.execute(select(TeamDB).where(TeamDB.id == args.team_id))
            selected_team = result.scalars().first()
            if not selected_team:
                logger.error(f"找不到 ID 為 {args.team_id} 的團隊")
                return
            logger.info(f"已選擇團隊: {selected_team.name}")
        else:
            # 互動式選擇團隊
            result = await db.execute(select(TeamDB).order_by(TeamDB.name))
            teams = result.scalars().all()
            if not teams:
                logger.error("資料庫中找不到任何團隊")
                return

            print("\n請選擇要同步的團隊：")
            for i, team in enumerate(teams):
                print(f"  [{i + 1}] {team.name} (ID: {team.id})")

            while True:
                try:
                    choice = await asyncio.to_thread(input, f"請輸入選項編號 (1-{len(teams)}): ")
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(teams):
                        selected_team = teams[choice_idx]
                        break
                    else:
                        print("無效的選項，請重新輸入")
                except (ValueError, IndexError):
                    print("輸入無效，請輸入數字")
                except (KeyboardInterrupt, EOFError):
                    print("\n操作已取消")
                    return

        # 設定 Lark 配置
        if args.lark_url:
            logger.info("使用命令行參數提供的 Lark URL")
            import re
            match = re.search(r'/wiki/(?P<wiki_token>\w+)/table/(?P<table_id>\w+)', args.lark_url)
            if not match:
                logger.error("提供的 Lark URL 格式不正確")
                return
            wiki_token = match.group('wiki_token')
            table_id = match.group('table_id')
        else:
            logger.info("使用團隊的預設 Lark 設定")
            if not selected_team.wiki_token or not selected_team.test_case_table_id:
                logger.error(f"團隊 '{selected_team.name}' 尚未設定 Lark wiki_token 或 test_case_table_id")
                return
            wiki_token = selected_team.wiki_token
            table_id = selected_team.test_case_table_id

        # 初始化 Lark 客戶端
        lark_client = LarkClient(app_id=settings.lark.app_id, app_secret=settings.lark.app_secret)
        if not lark_client.set_wiki_token(wiki_token):
            logger.error("設定 Lark wiki token 失敗")
            return

        # 執行同步
        synchronizer = TCRTToLarkSynchronizer(
            db=db,
            team=selected_team,
            lark_client=lark_client,
            lark_table_id=table_id,
            dry_run=args.dry_run
        )

        # 載入資料
        await synchronizer.load_local_data()
        await synchronizer.load_remote_data()

        # 分析資料差異
        await synchronizer.analyze()

        # 顯示計畫
        synchronizer.preview_plan()

        # 確認執行
        if not args.dry_run:
            if not args.yes:
                confirm = await asyncio.to_thread(
                    input,
                    "\n⚠️  警告：此操作會更新 Lark 上的資料！\n確定要執行嗎？(yes/N): "
                )
                if confirm.lower() != 'yes':
                    print("操作已取消")
                    return

            await synchronizer.execute()
        else:
            print("\n[DRY RUN 完成] 如要實際執行，請移除 --dry-run 參數")


if __name__ == "__main__":
    asyncio.run(main())
