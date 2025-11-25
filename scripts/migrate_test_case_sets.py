#!/usr/bin/env python3
"""
測試案例集合 (Test Case Set) 資料遷移腳本

功能：
1. 為每個現有的 Team 建立預設的 Test Case Set (如果不存在)
   - 命名規則：Default_{team_name}
   - 標記為預設集合 (is_default=True)

2. 為每個 Test Case Set 建立 Unassigned Section
   - 用於放置未分配到其他分類的 Test Cases

3. 將現有的 Test Cases 關聯到對應 Team 的 Default Set
   - 只處理尚未關聯到任何 Set 的 Test Cases (test_case_set_id == NULL)
   - 同時將其 section_id 設為 Unassigned Section

使用：
  python scripts/migrate_test_case_sets.py [--dry-run] [--verbose]

選項：
  --dry-run:   模擬執行，不實際更改資料庫
  --verbose:   顯示詳細執行日誌

範例：
  python scripts/migrate_test_case_sets.py --dry-run --verbose  # 預演執行
  python scripts/migrate_test_case_sets.py                       # 實際執行
"""

from __future__ import annotations

import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime

# 確保專案根目錄在匯入路徑
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import get_sync_engine
from app.models.database_models import (
    Base,
    Team as TeamDB,
    TestCaseLocal as TestCaseLocalDB,
    TestCaseSet as TestCaseSetDB,
    TestCaseSection as TestCaseSectionDB,
)

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_tables(engine):
    """建立新的資料表 (如果不存在)"""
    logger.info("檢查並建立必要的資料表...")
    Base.metadata.create_all(engine)
    logger.info("資料表檢查完成")


def ensure_schema_compatibility(engine):
    """確保資料庫結構與模型相容 (補上可能缺失的欄位)"""
    inspector = inspect(engine)
    
    # 檢查 test_cases 表是否存在
    if not inspector.has_table("test_cases"):
        return

    columns = {col['name'] for col in inspector.get_columns('test_cases')}
    
    with engine.begin() as conn:
        if 'test_case_set_id' not in columns:
            logger.info("補上缺失欄位: test_cases.test_case_set_id")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN test_case_set_id INTEGER"))
            
        if 'test_case_section_id' not in columns:
            logger.info("補上缺失欄位: test_cases.test_case_section_id")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN test_case_section_id INTEGER"))
            
        # 順便補上附件欄位，避免其他潛在錯誤
        if 'has_attachments' not in columns:
            logger.info("補上缺失欄位: test_cases.has_attachments")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN has_attachments INTEGER NOT NULL DEFAULT 0"))
            
        if 'attachment_count' not in columns:
            logger.info("補上缺失欄位: test_cases.attachment_count")
            conn.execute(text("ALTER TABLE test_cases ADD COLUMN attachment_count INTEGER NOT NULL DEFAULT 0"))


def migrate_test_case_sets(engine, dry_run=False, verbose=False):
    """執行資料遷移"""
    session = Session(engine)

    try:
        # 1. 獲取所有 Teams
        teams = session.query(TeamDB).all()
        logger.info(f"找到 {len(teams)} 個 Team")

        if not teams:
            logger.warning("沒有找到任何 Team")
            return

        migration_stats = {
            'teams_processed': 0,
            'default_sets_created': 0,
            'unassigned_sections_created': 0,
            'test_cases_migrated': 0,
            'errors': []
        }

        for team in teams:
            try:
                if verbose:
                    logger.info(f"處理 Team: {team.id} ({team.name})")

                # 2. 檢查該 Team 是否已有 Default Set
                default_set = session.query(TestCaseSetDB).filter(
                    TestCaseSetDB.team_id == team.id,
                    TestCaseSetDB.is_default == True
                ).first()

                if not default_set:
                    # 3. 建立 Default Set
                    set_name = f"Default_{team.name}"

                    # 檢查名稱是否已存在（由於全域唯一約束）
                    existing_by_name = session.query(TestCaseSetDB).filter(
                        TestCaseSetDB.name == set_name
                    ).first()

                    if existing_by_name:
                        # 如果名稱已存在，添加 team_id 以確保唯一性
                        set_name = f"Default_{team.name}_{team.id}"
                        if verbose:
                            logger.warning(f"  名稱衝突，使用替代名稱: {set_name}")

                    default_set = TestCaseSetDB(
                        team_id=team.id,
                        name=set_name,
                        description="團隊預設測試案例集合",
                        is_default=True
                    )
                    session.add(default_set)
                    session.flush()  # 獲取 ID

                    if verbose:
                        logger.info(f"  建立 Default Set: {default_set.name} (ID: {default_set.id})")

                    migration_stats['default_sets_created'] += 1
                else:
                    if verbose:
                        logger.info(f"  Default Set 已存在: {default_set.name} (ID: {default_set.id})")

                # 4. 檢查是否有 Unassigned Section
                unassigned = session.query(TestCaseSectionDB).filter(
                    TestCaseSectionDB.test_case_set_id == default_set.id,
                    TestCaseSectionDB.name == "Unassigned"
                ).first()

                if not unassigned:
                    # 5. 建立 Unassigned Section
                    unassigned = TestCaseSectionDB(
                        test_case_set_id=default_set.id,
                        name="Unassigned",
                        description="未分配的測試案例",
                        level=1,
                        sort_order=0,
                        parent_section_id=None
                    )
                    session.add(unassigned)
                    session.flush()

                    if verbose:
                        logger.info(f"  建立 Unassigned Section (ID: {unassigned.id})")

                    migration_stats['unassigned_sections_created'] += 1
                else:
                    if verbose:
                        logger.info(f"  Unassigned Section 已存在 (ID: {unassigned.id})")

                # 6. 將該 Team 的所有 Test Cases 關聯到 Default Set 的 Unassigned Section
                test_cases = session.query(TestCaseLocalDB).filter(
                    TestCaseLocalDB.team_id == team.id,
                    TestCaseLocalDB.test_case_set_id == None
                ).all()

                if test_cases:
                    for test_case in test_cases:
                        test_case.test_case_set_id = default_set.id
                        test_case.test_case_section_id = unassigned.id

                    if verbose:
                        logger.info(f"  遷移 {len(test_cases)} 個 Test Cases 到 Default Set")

                    migration_stats['test_cases_migrated'] += len(test_cases)

                migration_stats['teams_processed'] += 1

            except Exception as e:
                error_msg = f"處理 Team {team.id} 時出錯: {str(e)}"
                logger.error(error_msg)
                migration_stats['errors'].append(error_msg)

        # 7. 提交更改
        if dry_run:
            logger.info("執行 --dry-run，回滾所有更改")
            session.rollback()
        else:
            logger.info("提交所有更改到資料庫...")
            session.commit()

        # 輸出統計
        logger.info("\n" + "="*50)
        logger.info("遷移統計:")
        logger.info(f"  Teams 已處理: {migration_stats['teams_processed']}")
        logger.info(f"  Default Sets 已建立: {migration_stats['default_sets_created']}")
        logger.info(f"  Unassigned Sections 已建立: {migration_stats['unassigned_sections_created']}")
        logger.info(f"  Test Cases 已遷移: {migration_stats['test_cases_migrated']}")
        if migration_stats['errors']:
            logger.info(f"  錯誤: {len(migration_stats['errors'])}")
            for error in migration_stats['errors']:
                logger.error(f"    - {error}")
        logger.info("="*50)

        return migration_stats

    except Exception as e:
        logger.error(f"遷移失敗: {str(e)}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description='測試案例集合資料遷移腳本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='模擬執行，不實際更改資料庫'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='顯示詳細執行日誌'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        logger.info("開始資料遷移...")
        logger.info(f"模式: {'DRY-RUN' if args.dry_run else '實際執行'}")

        # 1. 獲取資料庫引擎
        engine = get_sync_engine()

        # 2. 建立必要的表
        create_tables(engine)
        
        # 2.5 確保欄位存在 (針對舊庫升級)
        ensure_schema_compatibility(engine)

        # 3. 執行遷移
        stats = migrate_test_case_sets(engine, dry_run=args.dry_run, verbose=args.verbose)

        logger.info("遷移完成!")
        return 0

    except Exception as e:
        logger.error(f"遷移失敗: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
