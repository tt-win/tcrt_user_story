#!/usr/bin/env python3
"""
Test Case 同步 CLI 腳本

使用方式：
  python scripts/sync_test_cases.py --team-id 1 --mode init
  python scripts/sync_test_cases.py --team-id 1 --mode full-update

選項：
  --dry-run 僅顯示將執行的動作統計，不提交變更（目前僅對 full-update 生效）
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Dict

import sys
from pathlib import Path

# 確保可從專案根目錄匯入 app 套件
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker
from app.database import get_sync_engine
from app.config import settings
from app.models.database_models import Team as TeamDB, Base as ModelsBase
from app.services.lark_client import LarkClient
from app.services.test_case_sync_service import TestCaseSyncService


def run_for_team(db, team_id: int, mode: str, dry_run: bool = False, prune: bool = False) -> Dict[str, Any]:
    # 讀取團隊配置
    team = db.query(TeamDB).filter(TeamDB.id == team_id).first()
    if not team:
        raise SystemExit(f"找不到團隊 ID {team_id}")

    lark = LarkClient(app_id=settings.lark.app_id, app_secret=settings.lark.app_secret)
    svc = TestCaseSyncService(
        team_id=team_id,
        db=db,
        lark_client=lark,
        wiki_token=team.wiki_token,
        table_id=team.test_case_table_id,
    )

    if mode == 'init':
        result = svc.init_sync()
    elif mode == 'full-update':
        if dry_run:
            # 目前提供簡單提示，詳細 dry-run 需要在 service 層模擬上傳
            print(f"[DRY-RUN][team={team_id}] full-update 將以本地資料覆蓋 Lark（實際上不會上傳）")
            result = {"mode": "full-update", "dry_run": True, "prune": prune}
        else:
            result = svc.full_update(prune=prune)
    else:
        raise SystemExit(f"不支援的模式：{mode}")

    return result


def _ensure_db_schema(sync_engine):
    # 確保使用 models 的 Base 建表（避免 app.database.Base 與 models.Base 不同造成缺表）
    try:
        ModelsBase.metadata.create_all(bind=sync_engine)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Test Case 同步工具")
    parser.add_argument('--team-id', type=int, help='團隊 ID（未提供時與 --all 互斥）')
    parser.add_argument('--all', action='store_true', help='同步所有團隊（若提供則忽略 --team-id）')
    parser.add_argument('--mode', choices=['init', 'full-update'], required=True, help='同步模式')
    parser.add_argument('--dry-run', action='store_true', help='試 run，不提交變更（僅對 full-update 有效）')
    parser.add_argument('--prune', action='store_true', help='在 full-update 模式下，刪除 Lark 上本地不存在的案例（務必小心）')
    args = parser.parse_args()

    sync_engine = get_sync_engine()
    _ensure_db_schema(sync_engine)
    SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
    db = SyncSessionLocal()
    try:
        results: Dict[str, Any] | list[Dict[str, Any]]
        if args.all or not args.team_id:
            teams = db.query(TeamDB).all()
            aggregated = []
            for t in teams:
                r = run_for_team(db, t.id, args.mode, args.dry_run, args.prune)
                aggregated.append({"team_id": t.id, "team_name": t.name, **r})
            results = aggregated
        else:
            results = run_for_team(db, args.team_id, args.mode, args.dry_run, args.prune)
    finally:
        db.close()

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
