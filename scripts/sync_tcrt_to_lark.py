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
    會先清空 Lark 表格，再將本地所有資料寫入。
    """
    def __init__(self, db: AsyncSession, team: TeamDB, lark_client: LarkClient, lark_table_id: str, dry_run: bool = False):
        self.db = db
        self.team = team
        self.lark_client = lark_client
        self.lark_table_id = lark_table_id
        self.dry_run = dry_run
        self.local_cases = []
        self.remote_records = []

    async def load_local_data(self):
        """載入本地資料庫的所有 Test Cases"""
        logger.info(f"正在從本地資料庫讀取團隊 '{self.team.name}' 的所有 Test Cases...")
        result = await self.db.execute(
            select(TestCaseLocalDB).where(TestCaseLocalDB.team_id == self.team.id).order_by(TestCaseLocalDB.test_case_number)
        )
        self.local_cases = result.scalars().all()
        logger.info(f"已載入 {len(self.local_cases)} 筆本地 Test Cases")

    async def load_remote_data(self):
        """載入遠端 Lark 表格的所有記錄"""
        logger.info(f"正在從 Lark 表格 (ID: {self.lark_table_id}) 讀取所有紀錄...")
        try:
            self.remote_records = await asyncio.to_thread(self.lark_client.get_all_records, self.lark_table_id)
            logger.info(f"已載入 {len(self.remote_records)} 筆 Lark 紀錄")
        except Exception as e:
            logger.error(f"讀取 Lark 紀錄失敗: {e}")
            self.remote_records = []

    def preview_plan(self):
        """顯示同步計畫預覽"""
        print("\n" + "=" * 60)
        print("同步計畫預覽")
        print("=" * 60)
        print(f"團隊: {self.team.name}")
        print(f"Lark 表格 ID: {self.lark_table_id}")
        print(f"模式: {'DRY RUN (不會實際執行)' if self.dry_run else '正式執行'}")
        print("-" * 60)

        # 統計空白或無 Test Case Number 的遠端記錄
        blank_remote = [r for r in self.remote_records if not r.get('fields', {}).get('Test Case Number')]
        valid_remote = [r for r in self.remote_records if r.get('fields', {}).get('Test Case Number')]

        print(f"\n[1] 刪除 Lark 上的所有紀錄:")
        print(f"    - 有效紀錄 (有 Test Case Number): {len(valid_remote)} 筆")
        print(f"    - 空白紀錄 (無 Test Case Number): {len(blank_remote)} 筆")
        print(f"    - 總計: {len(self.remote_records)} 筆")

        print(f"\n[2] 從本地新增到 Lark:")
        print(f"    - 總計: {len(self.local_cases)} 筆")

        if len(self.local_cases) > 0:
            print("\n本地資料預覽 (前 10 筆):")
            for i, case in enumerate(self.local_cases[:10]):
                print(f"    {i+1}. {case.test_case_number}: {case.title}")
            if len(self.local_cases) > 10:
                print(f"    ... (還有 {len(self.local_cases) - 10} 筆)")

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
        """執行同步操作"""
        if self.dry_run:
            print("\n[DRY RUN 模式] 不會實際執行任何操作")
            return

        print("\n開始執行同步...")

        try:
            # 步驟 1: 刪除 Lark 上的所有記錄
            if self.remote_records:
                record_ids_to_delete = [r['record_id'] for r in self.remote_records if 'record_id' in r]
                if record_ids_to_delete:
                    logger.info(f"正在刪除 Lark 上的 {len(record_ids_to_delete)} 筆記錄...")
                    await asyncio.to_thread(
                        self.lark_client.batch_delete_records,
                        self.lark_table_id,
                        record_ids_to_delete
                    )
                    logger.info("Lark 記錄刪除完成")
            else:
                logger.info("Lark 表格為空，跳過刪除步驟")

            # 步驟 2: 將本地資料寫入 Lark
            if self.local_cases:
                logger.info(f"正在將 {len(self.local_cases)} 筆本地資料寫入 Lark...")
                records_to_create = []
                for case in self.local_cases:
                    records_to_create.append(self._convert_local_to_lark_fields(case))

                if records_to_create:
                    await asyncio.to_thread(
                        self.lark_client.batch_create_records,
                        self.lark_table_id,
                        records_to_create
                    )
                    logger.info("本地資料寫入完成")
            else:
                logger.info("本地無資料，跳過寫入步驟")

            print("\n✅ 同步執行成功！")

        except Exception as e:
            logger.error(f"同步過程中發生錯誤: {e}", exc_info=True)
            print(f"\n❌ 同步失敗: {e}")
            raise


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
        """
    )
    parser.add_argument('--team-id', type=int, help="要同步的團隊 ID")
    parser.add_argument('--lark-url', type=str, help="Lark 表格完整 URL (可選，可覆寫團隊預設)")
    parser.add_argument('--dry-run', action='store_true', help="只預覽計畫，不實際執行")
    parser.add_argument('--yes', '-y', action='store_true', help="自動確認，不詢問")
    args = parser.parse_args()

    async with get_async_session() as db:
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

        # 顯示計畫
        synchronizer.preview_plan()

        # 確認執行
        if not args.dry_run:
            if not args.yes:
                confirm = await asyncio.to_thread(
                    input,
                    "\n⚠️  警告：此操作會刪除 Lark 上的所有資料並重新寫入！\n確定要執行嗎？(yes/N): "
                )
                if confirm.lower() != 'yes':
                    print("操作已取消")
                    return

            await synchronizer.execute()
        else:
            print("\n[DRY RUN 完成] 如要實際執行，請移除 --dry-run 參數")


if __name__ == "__main__":
    asyncio.run(main())
