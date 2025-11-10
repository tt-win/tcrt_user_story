#!/usr/bin/env python3
"""
TCG 單號格式遷移腳本
將現有格式從 Lark record_id 映射轉換為簡單的單號列表

轉換前: [{"record_ids": ["recuRbIbgF1qzJ"], "table_id": "tblcK6eF3yQCuwwl", "text": "TCG-100007", "text_arr": ["TCG-100007"], "type": "text"}]
轉換後: ["TCG-100007"]

用法: python migrate_tcg_format.py
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import Any, Optional, List

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = "test_case_repo.db"


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
        
        # 如果是列表格式
        if isinstance(data, list):
            numbers = []
            for item in data:
                if isinstance(item, dict):
                    # 優先使用 text_arr
                    if 'text_arr' in item and isinstance(item['text_arr'], list):
                        numbers.extend(item['text_arr'])
                    # 其次使用 text
                    elif 'text' in item:
                        numbers.append(item['text'])
            return numbers
        
        # 如果是字典格式
        elif isinstance(data, dict):
            # 優先使用 text_arr
            if 'text_arr' in data and isinstance(data['text_arr'], list):
                return data['text_arr']
            # 其次使用 text
            elif 'text' in data:
                return [data['text']]
        
        return []
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失敗: {e}, 內容: {tcg_json_str}")
        return []
    except Exception as e:
        logger.error(f"提取 TCG 單號失敗: {e}")
        return []


def migrate_tcg_data():
    """執行 TCG 資料遷移"""
    
    if not Path(DB_PATH).exists():
        logger.error(f"資料庫不存在: {DB_PATH}")
        return False
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 檢查表是否存在
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_cases'"
        )
        if not cursor.fetchone():
            logger.error("test_cases 表不存在")
            return False
        
        # 開始交易
        conn.execute("BEGIN TRANSACTION")
        
        try:
            # 取得所有有 TCG 的記錄
            cursor.execute(
                "SELECT id, test_case_number, tcg_json FROM test_cases WHERE tcg_json IS NOT NULL"
            )
            records = cursor.fetchall()
            
            logger.info(f"找到 {len(records)} 筆包含 TCG 的記錄")
            
            updated_count = 0
            for record_id, test_case_number, tcg_json_str in records:
                # 提取 TCG 單號
                tcg_numbers = extract_tcg_numbers_from_old_format(tcg_json_str)
                
                if tcg_numbers:
                    # 新格式：直接存儲單號列表
                    new_tcg_json = json.dumps(tcg_numbers, ensure_ascii=False)
                    
                    cursor.execute(
                        "UPDATE test_cases SET tcg_json = ? WHERE id = ?",
                        (new_tcg_json, record_id)
                    )
                    
                    updated_count += 1
                    
                    if updated_count <= 3:  # 只顯示前 3 筆的詳細信息
                        logger.info(
                            f"更新 {test_case_number}: "
                            f"舊格式 -> 新格式 {tcg_numbers}"
                        )
            
            # 提交交易
            conn.commit()
            logger.info(f"成功更新 {updated_count} 筆記錄")
            
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"遷移過程中出錯: {e}")
            return False
        finally:
            conn.close()
    
    except sqlite3.Error as e:
        logger.error(f"資料庫操作失敗: {e}")
        return False


if __name__ == "__main__":
    logger.info("開始 TCG 單號格式遷移...")
    success = migrate_tcg_data()
    
    if success:
        logger.info("✓ 遷移成功完成")
    else:
        logger.error("✗ 遷移失敗")
        exit(1)
