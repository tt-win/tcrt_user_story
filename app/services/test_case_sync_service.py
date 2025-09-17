#!/usr/bin/env python3
"""
Test Case 同步服務

- 作為 Lark 與本地 TestCaseLocal 的中介層
- 提供三種同步模式：
  1) init: 初始同步（清空本地，再從 Lark 匯入，沿用 Lark created/updated 作為 lark_created_at/lark_updated_at，
     本地 created_at/updated_at 在此模式採用 Lark 時間；之後的同步則以本地為主）
  2) diff: 比較雙方差異，互補：
     - Lark 有而本地沒有 -> 插入
     - 本地有、Lark 沒有 -> 規則：保留本地並標記 pending，視需要可在下一步上傳到 Lark（非此函式直接刪除）
     - 雙方都有 -> 以 updated_at 與 checksum 比對，若本地較新 -> 推 Lark；若 Lark 較新 -> 拉回本地
  3) full-update: 以本地覆蓋 Lark（本地為準，上傳；Lark 多餘的保留或刪除由參數決定）

- upsert 策略：以 (team_id, test_case_number) 作為自然鍵；保留 lark_record_id 以利對應
- 索引：已在 ORM 中設置
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.database_models import TestCaseLocal, SyncStatus
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_case import TestCase
from app.services.lark_client import LarkClient


class TestCaseSyncStats:
    def __init__(self):
        self.inserted = 0
        self.updated = 0
        self.unchanged = 0
        self.conflicts = 0
        self.errors: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'inserted': self.inserted,
            'updated': self.updated,
            'unchanged': self.unchanged,
            'conflicts': self.conflicts,
            'errors': self.errors,
        }


def _stable_checksum(payload: Dict[str, Any]) -> str:
    """產生穩定的內容校驗碼（不含變動性欄位）"""
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:64]


def _tc_to_payload(tc: TestCase) -> Dict[str, Any]:
    """將 Pydantic TestCase 模型轉為可計算 checksum 的 payload（過濾易變欄位）"""
    return {
        'test_case_number': tc.test_case_number,
        'title': tc.title,
        'priority': tc.priority.value if hasattr(tc.priority, 'value') else tc.priority,
        'precondition': tc.precondition,
        'steps': tc.steps,
        'expected_result': tc.expected_result,
        'test_result': tc.test_result.value if hasattr(tc.test_result, 'value') else tc.test_result,
        # 關聯轉為原始 json（僅做 checksum 比對用）
        'assignee': tc.assignee.model_dump() if getattr(tc, 'assignee', None) else None,
        'attachments': [a.model_dump() for a in getattr(tc, 'attachments', [])] if getattr(tc, 'attachments', None) else [],
        'test_results_files': [a.model_dump() for a in getattr(tc, 'test_results_files', [])] if getattr(tc, 'test_results_files', None) else [],
        'user_story_map': [r.model_dump() for r in getattr(tc, 'user_story_map', [])] if getattr(tc, 'user_story_map', None) else [],
        'tcg': [r.model_dump() for r in getattr(tc, 'tcg', [])] if getattr(tc, 'tcg', None) else [],
        'parent_record': [r.model_dump() for r in getattr(tc, 'parent_record', [])] if getattr(tc, 'parent_record', None) else [],
    }


def _record_to_testcase(record: Dict[str, Any], team_id: Optional[int]) -> TestCase:
    return TestCase.from_lark_record(record, team_id)


class TestCaseSyncService:
    def __init__(self, team_id: int, db: Session, lark_client: LarkClient, wiki_token: str, table_id: str):
        self.team_id = team_id
        self.db = db
        self.lark = lark_client
        self.wiki_token = wiki_token
        self.table_id = table_id

        # 準備 Lark client 狀態
        self.lark.set_wiki_token(self.wiki_token)

    # ---------------------- 公用基本操作 ----------------------
    def _get_all_lark_records(self) -> List[Dict[str, Any]]:
        return self.lark.get_all_records(self.table_id)

    def _upsert_local_from_tc(self, lark_record: Dict[str, Any], tc: TestCase, init_mode: bool, stats: TestCaseSyncStats) -> None:
        """以 (team_id, test_case_number) 為鍵 upsert 到本地 TestCaseLocal"""
        payload = _tc_to_payload(tc)
        checksum = _stable_checksum(payload)

        # 查找現有本地資料
        existing: Optional[TestCaseLocal] = self.db.execute(
            select(TestCaseLocal).where(
                TestCaseLocal.team_id == self.team_id,
                TestCaseLocal.test_case_number == tc.test_case_number
            )
        ).scalar_one_or_none()

        lark_created_at = None
        lark_updated_at = None
        if lark_record:
            created_time = lark_record.get('created_time')
            last_modified_time = lark_record.get('last_modified_time')
            if isinstance(created_time, (int, float)):
                lark_created_at = datetime.fromtimestamp(created_time / 1000)
            if isinstance(last_modified_time, (int, float)):
                lark_updated_at = datetime.fromtimestamp(last_modified_time / 1000)

        if existing is None:
            # INSERT
            item = TestCaseLocal(
                team_id=self.team_id,
                lark_record_id=lark_record.get('record_id') if lark_record else None,
                test_case_number=tc.test_case_number,
                title=tc.title,
                priority=tc.priority if isinstance(tc.priority, Priority) else Priority(tc.priority) if tc.priority else None,
                precondition=tc.precondition,
                steps=tc.steps,
                expected_result=tc.expected_result,
                test_result=tc.test_result if isinstance(tc.test_result, TestResultStatus) else TestResultStatus(tc.test_result) if tc.test_result else None,
                assignee_json=json.dumps(tc.assignee.model_dump(), ensure_ascii=False) if tc.assignee else None,
                attachments_json=json.dumps([a.model_dump() for a in tc.attachments], ensure_ascii=False) if tc.attachments else None,
                test_results_files_json=json.dumps([a.model_dump() for a in tc.test_results_files], ensure_ascii=False) if tc.test_results_files else None,
                user_story_map_json=json.dumps([r.model_dump() for r in tc.user_story_map], ensure_ascii=False) if tc.user_story_map else None,
                tcg_json=json.dumps([r.model_dump() for r in tc.tcg], ensure_ascii=False) if tc.tcg else None,
                parent_record_json=json.dumps([r.model_dump() for r in tc.parent_record], ensure_ascii=False) if tc.parent_record else None,
                raw_fields_json=json.dumps(tc.raw_fields, ensure_ascii=False) if tc.raw_fields else None,
                checksum=checksum,
                sync_status=SyncStatus.SYNCED if init_mode else SyncStatus.PENDING,
                lark_created_at=lark_created_at,
                lark_updated_at=lark_updated_at,
            )
            # 時間策略：init 模式時，沿用 lark_* 到 created_at/updated_at；否則使用本地現在時間
            if init_mode and lark_created_at:
                item.created_at = lark_created_at
            if init_mode and lark_updated_at:
                item.updated_at = lark_updated_at
            self.db.add(item)
            stats.inserted += 1
            return

        # UPDATE：比對 checksum
        if existing.checksum == checksum:
            # 無變更
            stats.unchanged += 1
            return

        existing.title = tc.title
        existing.priority = tc.priority if isinstance(tc.priority, Priority) else Priority(tc.priority) if tc.priority else None
        existing.precondition = tc.precondition
        existing.steps = tc.steps
        existing.expected_result = tc.expected_result
        existing.test_result = tc.test_result if isinstance(tc.test_result, TestResultStatus) else TestResultStatus(tc.test_result) if tc.test_result else None
        existing.assignee_json = json.dumps(tc.assignee.model_dump(), ensure_ascii=False) if tc.assignee else None
        existing.attachments_json = json.dumps([a.model_dump() for a in tc.attachments], ensure_ascii=False) if tc.attachments else None
        existing.test_results_files_json = json.dumps([a.model_dump() for a in tc.test_results_files], ensure_ascii=False) if tc.test_results_files else None
        existing.user_story_map_json = json.dumps([r.model_dump() for r in tc.user_story_map], ensure_ascii=False) if tc.user_story_map else None
        existing.tcg_json = json.dumps([r.model_dump() for r in tc.tcg], ensure_ascii=False) if tc.tcg else None
        existing.parent_record_json = json.dumps([r.model_dump() for r in tc.parent_record], ensure_ascii=False) if tc.parent_record else None
        existing.raw_fields_json = json.dumps(tc.raw_fields, ensure_ascii=False) if tc.raw_fields else None
        existing.checksum = checksum
        existing.local_version = (existing.local_version or 1) + 1
        existing.sync_status = SyncStatus.SYNCED if init_mode else SyncStatus.PENDING
        existing.lark_record_id = lark_record.get('record_id') if lark_record else existing.lark_record_id
        existing.lark_created_at = lark_created_at or existing.lark_created_at
        existing.lark_updated_at = lark_updated_at or existing.lark_updated_at
        stats.updated += 1

    # ---------------------- 同步模式 ----------------------
    def init_sync(self) -> Dict[str, Any]:
        """初始同步：清空本地並從 Lark 匯入，時間以 Lark 為準（僅此模式）"""
        # 取得 Lark 所有記錄
        records = self._get_all_lark_records()
        stats = TestCaseSyncStats()

        # 先根據 Test Case Number 去重，保留最後更新時間較新的那一筆
        deduped: Dict[str, Dict[str, Any]] = {}
        for r in records:
            fields = r.get('fields', {}) or {}
            num = fields.get('Test Case Number')
            if not num:
                continue
            existed = deduped.get(num)
            if not existed:
                deduped[num] = r
            else:
                prev_time = existed.get('last_modified_time') or existed.get('created_time') or 0
                cur_time = r.get('last_modified_time') or r.get('created_time') or 0
                if cur_time >= prev_time:
                    deduped[num] = r

        # 清空本地 team 的資料
        self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id).delete()

        # 逐筆轉換並 upsert（實為 insert），處理完去重後的資料
        for r in deduped.values():
            tc = _record_to_testcase(r, self.team_id)
            self._upsert_local_from_tc(r, tc, init_mode=True, stats=stats)

        self.db.commit()
        return {'mode': 'init', **stats.to_dict(), 'total_lark_records': len(records), 'deduped_count': len(deduped)}

    def diff_sync(self) -> Dict[str, Any]:
        """比較差異並互補：Lark -> 本地，和本地 -> Lark（本函式先實作拉回本地；推送到 Lark 可由另一個流程呼叫）"""
        records = self._get_all_lark_records()
        stats = TestCaseSyncStats()

        # 建立 Lark 映射（以 test_case_number 為鍵）
        lark_by_number: Dict[str, Dict[str, Any]] = {}
        for r in records:
            fields = r.get('fields', {})
            num = fields.get('Test Case Number') or ''
            if num:
                lark_by_number[str(num)] = r

        # 1) Lark -> 本地：有就更新、沒有就插入
        for num, rec in lark_by_number.items():
            tc = _record_to_testcase(rec, self.team_id)
            self._upsert_local_from_tc(rec, tc, init_mode=False, stats=stats)

        # 2) 本地 -> Lark ：本地有但 Lark 沒有 -> 標記 pending（保留給後續上傳程序）
        local_numbers = {n for n in lark_by_number.keys()}
        q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id)
        for local in q:
            if local.test_case_number not in local_numbers:
                # 本地存在，Lark 不存在 -> 標記待上傳
                if local.sync_status != SyncStatus.PENDING:
                    local.sync_status = SyncStatus.PENDING
                    stats.updated += 1

        self.db.commit()
        return {'mode': 'diff', **stats.to_dict(), 'total_lark_records': len(records)}

    def full_update(self, prune: bool = False) -> Dict[str, Any]:
        """以本地覆蓋 Lark：將本地資料（team）全部上傳到 Lark（create 或 update）。
        若 prune=True，同步完成後會刪除 Lark 上本地不存在的記錄（依 Test Case Number 比對）。
        """
        stats = TestCaseSyncStats()

        # 準備本地資料
        locals_q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id)
        locals_list: List[TestCaseLocal] = list(locals_q)

        # 上傳策略：
        # - 有 lark_record_id -> update
        # - 無 lark_record_id -> create
        updates: List[Dict[str, Any]] = []
        creates: List[Dict[str, Any]] = []

        # 先組裝 Lark 欄位資料
        for item in locals_list:
            # 還原 TCG 資料
            try:
                tcg_data = json.loads(item.tcg_json) if item.tcg_json else []
                from app.models.lark_types import parse_lark_records
                tcg = parse_lark_records(tcg_data)
            except (json.JSONDecodeError, TypeError):
                tcg = []

            tc = TestCase(
                test_case_number=item.test_case_number,
                title=item.title,
                priority=item.priority or Priority.MEDIUM,
                precondition=item.precondition,
                steps=item.steps,
                expected_result=item.expected_result,
                assignee=None,
                test_result=item.test_result,
                attachments=[],
                user_story_map=[],
                tcg=tcg,  # 使用還原的 TCG 資料
                parent_record=[],
                team_id=self.team_id,
            )
            fields = tc.to_lark_sync_fields()
            if item.lark_record_id:
                updates.append({'record_id': item.lark_record_id, 'fields': fields})
            else:
                creates.append(fields)

        # 執行批次建立
        ok_create, created_ids, create_errors = self.lark.batch_create_records(self.table_id, creates) if creates else (True, [], [])
        if not ok_create:
            stats.errors.extend(create_errors)
        else:
            stats.updated += len(created_ids)
            # 依 Test Case Number 回查剛建立的 Lark 記錄，回填 lark_record_id
            try:
                # 重新抓 Lark 記錄形成 map（以 Test Case Number 為鍵）
                lark_records = self._get_all_lark_records()
                by_num: Dict[str, Dict[str, Any]] = {}
                for r in lark_records:
                    f = r.get('fields', {}) or {}
                    num = f.get('Test Case Number')
                    if num:
                        by_num[str(num)] = r
                # 回填
                for item in locals_list:
                    if not item.lark_record_id:
                        rec = by_num.get(item.test_case_number)
                        if rec and rec.get('record_id'):
                            item.lark_record_id = rec['record_id']
            except Exception as e:
                stats.errors.append(f"回填 lark_record_id 失敗: {e}")

        # 並行批次更新
        ok_update, updated_count, update_errors = self.lark.parallel_update_records(self.table_id, updates) if updates else (True, 0, [])
        if not ok_update:
            stats.errors.extend(update_errors)
        else:
            stats.updated += updated_count

        pruned = 0
        prune_errors: List[str] = []
        if prune:
            try:
                # 取得 Lark 現況
                lark_records = self._get_all_lark_records()
                lark_by_num: Dict[str, Dict[str, Any]] = {}
                for r in lark_records:
                    f = r.get('fields', {}) or {}
                    num = f.get('Test Case Number')
                    if num:
                        lark_by_num[str(num)] = r
                local_numbers = {item.test_case_number for item in locals_list if item.test_case_number}
                # 找出 Lark 多餘的（不在本地）
                to_delete_ids = [rec.get('record_id') for num, rec in lark_by_num.items() if num not in local_numbers and rec.get('record_id')]
                if to_delete_ids:
                    ok_del, del_count, del_errors = self.lark.batch_delete_records(self.table_id, to_delete_ids)
                    pruned += del_count if ok_del else 0
                    prune_errors.extend(del_errors or [])
            except Exception as e:
                prune_errors.append(str(e))

        # 將本地 sync_status 標記為 SYNCED
        for item in locals_list:
            item.sync_status = SyncStatus.SYNCED
            item.last_sync_at = datetime.utcnow()

        self.db.commit()
        result = {'mode': 'full-update', **stats.to_dict(), 'created': len(created_ids) if creates else 0, 'updated': stats.updated}
        if prune:
            result.update({'pruned': pruned, 'prune_errors': prune_errors})
        return result
