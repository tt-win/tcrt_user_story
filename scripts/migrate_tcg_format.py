#!/usr/bin/env python3
"""
TCG 單號格式遷移腳本
將現有格式從 Lark record_id 映射轉換為簡單的單號列表

轉換前: [{"record_ids": ["recuRbIbgF1qzJ"], "table_id": "tblcK6eF3yQCuwwl", "text": "TCG-100007", "text_arr": ["TCG-100007"], "type": "text"}]
轉換後: ["TCG-100007"]

用法: python scripts/migrate_tcg_format.py
"""

import json
import argparse
import logging
from typing import Any, Optional, List

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.db_migrations import get_sync_engine_for_target, resolve_main_database_url

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_tcg_numbers_from_old_format(tcg_json_str: str) -> List[str]:
    """
    從舊格式提取 TCG 單號

    Args:
        tcg_json_str: 原始的 JSON 字符串

    Returns:
        TCG 單號列表
    """
    if not tcg_json_str:
        return []

    try:
        data = json.loads(tcg_json_str)
        numbers = []

        # 如果是列表格式 (可能是舊格式 [{"text":...}] 或新格式 ["TCG-...", null])
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    # 舊格式物件處理
                    # 優先使用 text_arr
                    if 'text_arr' in item and isinstance(item['text_arr'], list):
                        numbers.extend([t for t in item['text_arr'] if t])
                    # 其次使用 text
                    elif 'text' in item and item['text']:
                        numbers.append(item['text'])
                elif isinstance(item, str) and item:
                    # 新格式字串處理 (過濾空字串)
                    numbers.append(item)
                # 忽略 None (已被錯誤遷移的髒資料) 或其他非預期類型

        # 如果是單一字典格式 (舊格式變體)
        elif isinstance(data, dict):
            # 優先使用 text_arr
            if 'text_arr' in data and isinstance(data['text_arr'], list):
                numbers.extend([t for t in data['text_arr'] if t])
            # 其次使用 text
            elif 'text' in data and data['text']:
                numbers.append(data['text'])

        # 去除重複並保持順序
        seen = set()
        unique_numbers = []
        for n in numbers:
            if n not in seen:
                unique_numbers.append(n)
                seen.add(n)
        
        return unique_numbers

    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失敗: {e}, 內容: {tcg_json_str}")
        return []
    except Exception as e:
        logger.error(f"提取 TCG 單號失敗: {e}")
        return []


def migrate_tcg_data(database_url: Optional[str] = None) -> bool:
    """執行 TCG 資料遷移"""
    engine = get_sync_engine_for_target(
        "main",
        database_url=database_url or resolve_main_database_url(),
    )
    try:
        if not inspect(engine).has_table("test_cases"):
            logger.error("test_cases 表不存在")
            return False

        with engine.begin() as conn:
            # 取得所有有 TCG 的記錄
            records = conn.execute(
                text("SELECT id, test_case_number, tcg_json FROM test_cases WHERE tcg_json IS NOT NULL")
            )
            rows = records.fetchall()

            logger.info(f"找到 {len(rows)} 筆包含 TCG 的記錄")

            updated_count = 0
            for record_id, test_case_number, tcg_json_str in rows:
                # 提取 TCG 單號
                tcg_numbers = extract_tcg_numbers_from_old_format(tcg_json_str)

                # 新格式：直接存儲單號列表
                new_tcg_json = json.dumps(tcg_numbers, ensure_ascii=False)

                # 如果內容有變更 (例如髒資料被清洗為 [])，則執行更新
                # 注意：忽略空白字符差異
                if new_tcg_json.replace(" ", "") != tcg_json_str.replace(" ", ""):
                    conn.execute(
                        text("UPDATE test_cases SET tcg_json = :tcg_json WHERE id = :record_id"),
                        {"tcg_json": new_tcg_json, "record_id": record_id},
                    )

                    updated_count += 1

                    if updated_count <= 5:  # 只顯示前 5 筆的詳細信息
                        logger.info(
                            f"更新 {test_case_number}: "
                            f"舊格式 -> 新格式 {tcg_numbers}"
                        )

            logger.info(f"成功更新 {updated_count} 筆記錄")
            return True

    except SQLAlchemyError as e:
        logger.error(f"資料庫操作失敗: {e}")
        return False
    finally:
        engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TCG 單號格式遷移腳本")
    parser.add_argument(
        "--database-url",
        dest="database_url",
        help="可選：指定主資料庫 URL；未提供時使用設定檔 / 環境變數解析結果",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logger.info("開始 TCG 單號格式遷移...")
    success = migrate_tcg_data(database_url=args.database_url)

    if success:
        logger.info("✓ 遷移成功完成")
    else:
        logger.error("✗ 遷移失敗")
        exit(1)
