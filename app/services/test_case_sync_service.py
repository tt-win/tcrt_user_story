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
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.database_models import TestCaseLocal, SyncStatus
from app.models.lark_types import Priority, TestResultStatus
from app.models.test_case import TestCase
from app.services.lark_client import LarkClient
from app.database import run_sync
# TCG 轉換器已移除 - 不再需要依賴 TCG 同步
# from app.services.tcg_converter import tcg_converter


logger = logging.getLogger(__name__)


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
    def __init__(self, team_id: int, db: AsyncSession, lark_client: LarkClient, wiki_token: str, table_id: str):
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

    def _upsert_local_from_tc(self, sync_db: Session, lark_record: Dict[str, Any], tc: TestCase, init_mode: bool, stats: TestCaseSyncStats) -> None:
        """以 (team_id, test_case_number) 為鍵 upsert 到本地 TestCaseLocal

        注意：避免觸發全域 UNIQUE(test_cases.lark_record_id) 的衝突。
        由於多個 team 可能同步自同一 Lark 表，因此相同的 record_id 可能跨 team 出現。
        這裡採用應用層預檢：如偵測到欲寫入的 lark_record_id 在其他記錄已被占用，則本筆改以 lark_record_id=None 儲存。
        """
        payload = _tc_to_payload(tc)
        checksum = _stable_checksum(payload)

        # 查找現有本地資料
        existing: Optional[TestCaseLocal] = sync_db.execute(
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
            logger.debug(
                "[TC-SYNC] Insert local test case | team=%s number=%s init=%s",
                self.team_id, tc.test_case_number, init_mode
            )

            # 預檢 lark_record_id 是否會造成全域唯一衝突
            desired_lark_id = lark_record.get('record_id') if lark_record else None
            if desired_lark_id:
                other = sync_db.execute(
                    select(TestCaseLocal.id, TestCaseLocal.team_id).where(
                        TestCaseLocal.lark_record_id == desired_lark_id
                    )
                ).first()
                if other is not None:
                    logger.warning(
                        "[TC-SYNC] lark_record_id already used by another record; store as NULL to avoid UNIQUE | record_id=%s team=%s",
                        desired_lark_id, self.team_id
                    )
                    desired_lark_id = None

            item = TestCaseLocal(
                team_id=self.team_id,
                lark_record_id=desired_lark_id,
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
            sync_db.add(item)
            stats.inserted += 1
            return

        # UPDATE：比對 checksum
        if existing.checksum == checksum:
            # 無變更
            logger.debug(
                "[TC-SYNC] Skip unchanged test case | team=%s number=%s",
                self.team_id, tc.test_case_number
            )
            stats.unchanged += 1
            return

        logger.debug(
            "[TC-SYNC] Update local test case | team=%s number=%s init=%s",
            self.team_id, tc.test_case_number, init_mode
        )
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

        # 預檢更新 lark_record_id 是否會造成全域唯一衝突
        if lark_record and lark_record.get('record_id'):
            desired_lark_id = lark_record.get('record_id')
            other = sync_db.execute(
                select(TestCaseLocal.id).where(
                    TestCaseLocal.lark_record_id == desired_lark_id,
                    TestCaseLocal.id != existing.id
                )
            ).first()
            if other is not None:
                logger.warning(
                    "[TC-SYNC] Update would violate UNIQUE on lark_record_id; keep as-is/None | record_id=%s team=%s",
                    desired_lark_id, self.team_id
                )
            else:
                existing.lark_record_id = desired_lark_id

        existing.lark_created_at = lark_created_at or existing.lark_created_at
        existing.lark_updated_at = lark_updated_at or existing.lark_updated_at
        stats.updated += 1

    # ---------------------- Diff 計算與套用 ----------------------
    def _normalize_enum(self, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (Priority, TestResultStatus)):
            return v.value
        return str(v)

    def _local_item_to_simple(self, item: TestCaseLocal) -> Dict[str, Any]:
        return {
            'test_case_number': item.test_case_number,
            'title': item.title or '',
            'priority': self._normalize_enum(item.priority) if hasattr(item, 'priority') else None,
            'precondition': item.precondition,
            'steps': item.steps,
            'expected_result': item.expected_result,
            'test_result': self._normalize_enum(item.test_result) if hasattr(item, 'test_result') else None,
        }

    def _tc_to_simple(self, tc: TestCase) -> Dict[str, Any]:
        return {
            'test_case_number': tc.test_case_number,
            'title': tc.title or '',
            'priority': tc.priority.value if hasattr(tc.priority, 'value') else tc.priority,
            'precondition': tc.precondition,
            'steps': tc.steps,
            'expected_result': tc.expected_result,
            'test_result': tc.test_result.value if hasattr(tc.test_result, 'value') else tc.test_result,
            'tcg_numbers': tc.get_tcg_numbers() if hasattr(tc, 'get_tcg_numbers') else [],
        }

    def _local_tcg_numbers(self, item: TestCaseLocal) -> List[str]:
        try:
            data = json.loads(item.tcg_json) if getattr(item, 'tcg_json', None) else []
            nums: List[str] = []
            if isinstance(data, list):
                for it in data:
                    arr = it.get('text_arr') or []
                    if arr and isinstance(arr, list):
                        nums.extend([str(x) for x in arr])
                    else:
                        txt = it.get('text')
                        if txt:
                            nums.append(str(txt))
            # 去重排序，便於穩定比較
            return sorted(list({n for n in nums if n}))
        except Exception:
            return []

    def _local_tcg_map(self, item: TestCaseLocal) -> Dict[str, Optional[str]]:
        """回傳 {tcg_number -> record_id or None} 映射"""
        mapping: Dict[str, Optional[str]] = {}
        try:
            data = json.loads(item.tcg_json) if getattr(item, 'tcg_json', None) else []
            if isinstance(data, list):
                for it in data:
                    txt = it.get('text') or None
                    arr = it.get('text_arr') or []
                    num = str(arr[0]) if arr else (str(txt) if txt else None)
                    if not num:
                        continue
                    rid = None
                    rids = it.get('record_ids') or []
                    if rids and isinstance(rids, list):
                        rid = str(rids[0])
                    mapping[num] = rid
        except Exception:
            return mapping
        return mapping

    def _lark_tcg_map(self, lark_record: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """回傳 {tcg_number -> record_id} 映射，來源 Lark 記錄資料"""
        mapping: Dict[str, Optional[str]] = {}
        if not lark_record:
            return mapping
        fields = lark_record.get('fields', {}) or {}
        # 以 TestCase.FIELD_IDS['tcg'] 取欄位名稱
        try:
            tcg_field_name = TestCase.FIELD_IDS['tcg']
        except Exception:
            tcg_field_name = 'TCG'
        items = fields.get(tcg_field_name) or []
        if isinstance(items, list):
            for it in items:
                txt = it.get('text') or None
                arr = it.get('text_arr') or []
                num = str(arr[0]) if arr else (str(txt) if txt else None)
                if not num:
                    continue
                rid = None
                rids = it.get('record_ids') or []
                if rids and isinstance(rids, list):
                    rid = str(rids[0])
                mapping[num] = rid
        return mapping

    async def compute_diff(self) -> Dict[str, Any]:
        return await run_sync(self.db, self._compute_diff_sync)

    def _compute_diff_sync(self, sync_db: Session) -> Dict[str, Any]:
        records = self._get_all_lark_records()
        lark_by_num: Dict[str, Dict[str, Any]] = {}
        lark_tc_by_num: Dict[str, TestCase] = {}
        for r in records:
            f = r.get('fields', {}) or {}
            num = f.get('Test Case Number')
            if not num:
                continue
            num = str(num)
            lark_by_num[num] = r
            lark_tc_by_num[num] = _record_to_testcase(r, self.team_id)

        locals_list: List[TestCaseLocal] = list(sync_db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id))
        local_by_num: Dict[str, TestCaseLocal] = {str(x.test_case_number): x for x in locals_list if x.test_case_number}

        all_nums = set(local_by_num.keys()) | set(lark_by_num.keys())
        fields = ['title', 'priority', 'precondition', 'steps', 'expected_result', 'test_result']
        diffs: List[Dict[str, Any]] = []
        summary = {'only_local': 0, 'only_lark': 0, 'both_equal': 0, 'both_changed': 0}

        for num in sorted(all_nums):
            local_item = local_by_num.get(num)
            lark_tc = lark_tc_by_num.get(num)
            if local_item and not lark_tc:
                summary['only_local'] += 1
                simple_local = self._local_item_to_simple(local_item)
                f_list = [
                    {'name': k, 'local': simple_local.get(k), 'lark': None, 'different': True}
                    for k in fields
                ]
                # TCG 作為單一欄位進行顯示與比較（聚合）
                local_tcg_display = ", ".join(self._local_tcg_numbers(local_item)) or None
                f_list.append({'name': 'tcg', 'local': local_tcg_display, 'lark': None, 'different': True})
                diffs.append({
                    'test_case_number': num,
                    'status': 'only_local',
                    'lark_record_id': local_item.lark_record_id,
                    'fields': f_list
                })
                continue
            if lark_tc and not local_item:
                summary['only_lark'] += 1
                simple_lark = self._tc_to_simple(lark_tc)
                f_list = [
                    {'name': k, 'local': None, 'lark': simple_lark.get(k), 'different': True}
                    for k in fields
                ]
                # TCG 作為單一欄位進行顯示與比較（聚合）
                lark_tcg_display = ", ".join(simple_lark.get('tcg_numbers') or []) or None
                f_list.append({'name': 'tcg', 'local': None, 'lark': lark_tcg_display, 'different': True})
                diffs.append({
                    'test_case_number': num,
                    'status': 'only_lark',
                    'lark_record_id': lark_by_num[num].get('record_id'),
                    'fields': f_list
                })
                continue
            # both exist
            simple_local = self._local_item_to_simple(local_item)
            simple_lark = self._tc_to_simple(lark_tc)
            field_diffs = []
            different_any = False
            for k in fields:
                lv = simple_local.get(k)
                rv = simple_lark.get(k)
                is_diff = lv != rv
                if is_diff:
                    different_any = True
                field_diffs.append({'name': k, 'local': lv, 'lark': rv, 'different': is_diff})
            # 比對 TCG 單號（欄位為單一聚合，判斷是否不同）
            local_tcg_list = self._local_tcg_numbers(local_item)
            lark_tcg_list = simple_lark.get('tcg_numbers') or []
            local_display = ", ".join(local_tcg_list) or None
            lark_display = ", ".join(lark_tcg_list) or None
            tcg_diff = set(local_tcg_list) != set(lark_tcg_list)
            if tcg_diff:
                different_any = True
            field_diffs.append({'name': 'tcg', 'local': local_display, 'lark': lark_display, 'different': tcg_diff})

            if different_any:
                summary['both_changed'] += 1
                diffs.append({
                    'test_case_number': num,
                    'status': 'both',
                    'lark_record_id': (local_item.lark_record_id or lark_by_num.get(num, {}).get('record_id')),
                    'fields': field_diffs,
                })
            else:
                summary['both_equal'] += 1

        return {'success': True, 'summary': summary, 'diffs': diffs}

    async def apply_diff(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        return await run_sync(self.db, self._apply_diff_sync, decisions)

    def _apply_diff_sync(self, sync_db: Session, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        # 準備映射
        records = self._get_all_lark_records()
        lark_by_num: Dict[str, Dict[str, Any]] = {}
        for r in records:
            f = r.get('fields', {}) or {}
            num = f.get('Test Case Number')
            if num:
                lark_by_num[str(num)] = r
        results: List[Dict[str, Any]] = []
        applied = 0
        errors: List[str] = []

        # 輔助：將本地欄位值轉為 Lark 欄位 payload（僅所選欄位）
        def _build_partial_lark_fields_from_local(item: TestCaseLocal, selected_fields: List[str]) -> Dict[str, Any]:
            fields_payload: Dict[str, Any] = {}
            fld = TestCase.FIELD_IDS
            for k in selected_fields:
                if k == 'title':
                    fields_payload[fld['title']] = item.title or ''
                elif k == 'precondition':
                    fields_payload[fld['precondition']] = item.precondition or ''
                elif k == 'steps':
                    fields_payload[fld['steps']] = item.steps or ''
                elif k == 'expected_result':
                    fields_payload[fld['expected_result']] = item.expected_result or ''
                elif k == 'priority':
                    val = item.priority.value if hasattr(item.priority, 'value') else (item.priority or None)
                    if val is not None:
                        fields_payload[fld['priority']] = val
                elif k == 'test_result':
                    val = item.test_result.value if hasattr(item.test_result, 'value') else (item.test_result or None)
                    if val is not None:
                        fields_payload[fld['test_result']] = val
                elif k == 'tcg':
                    # 轉為 record_ids 陣列
                    arr: List[str] = []
                    try:
                        data = json.loads(item.tcg_json) if getattr(item, 'tcg_json', None) else []
                        if isinstance(data, list):
                            for it in data:
                                rid = None
                                rids = it.get('record_ids') or []
                                if rids and isinstance(rids, list):
                                    rid = rids[0]
                                if rid:
                                    arr.append(str(rid))
                    except Exception:
                        arr = []
                    fields_payload[fld['tcg']] = arr
            # 確保帶上 Test Case Number
            fields_payload[fld['test_case_number']] = item.test_case_number
            return fields_payload

        # 輔助：從 Lark TestCase 套用值到本地（僅所選欄位）
        def _apply_fields_from_lark_to_local(item: TestCaseLocal, tc: TestCase, selected_fields: List[str]):
            if 'title' in selected_fields:
                item.title = tc.title
            if 'precondition' in selected_fields:
                item.precondition = tc.precondition
            if 'steps' in selected_fields:
                item.steps = tc.steps
            if 'expected_result' in selected_fields:
                item.expected_result = tc.expected_result
            if 'priority' in selected_fields and tc.priority is not None:
                item.priority = tc.priority if isinstance(tc.priority, Priority) else Priority(tc.priority)
            if 'test_result' in selected_fields and tc.test_result is not None:
                item.test_result = tc.test_result if isinstance(tc.test_result, TestResultStatus) else TestResultStatus(tc.test_result)
            if 'tcg' in selected_fields:
                try:
                    item.tcg_json = json.dumps([r.model_dump() for r in (tc.tcg or [])], ensure_ascii=False)
                except Exception:
                    item.tcg_json = None

        for d in decisions:
            num = str(d.get('test_case_number')) if d.get('test_case_number') is not None else None
            if not num:
                errors.append(f"無效的決策: {d}")
                continue
            fields_map: Dict[str, str] = d.get('fields') or {}
            src = d.get('source')  # 向下相容：整筆來源
            try:
                if fields_map:
                    # 欄位級合併
                    item = sync_db.query(TestCaseLocal).filter(
                        TestCaseLocal.team_id == self.team_id,
                        TestCaseLocal.test_case_number == num
                    ).first()
                    r = lark_by_num.get(num)
                    lark_tc = _record_to_testcase(r, self.team_id) if r else None
                    # 先處理採用 Lark 的欄位 → 更新本地
                    picks_lark = [k for k, v in fields_map.items() if v == 'lark']
                    if picks_lark:
                        if not item:
                            # 本地不存在，且有採用 Lark → 以 Lark 建立
                            if lark_tc and r:
                                dummy_stats = TestCaseSyncStats()
                                self._upsert_local_from_tc(sync_db, r, lark_tc, init_mode=False, stats=dummy_stats)
                                applied += 1
                                results.append({'test_case_number': num, 'success': True, 'action': 'created_from_lark_for_fields', 'fields': picks_lark})
                            else:
                                results.append({'test_case_number': num, 'success': False, 'message': '本地無此紀錄且 Lark 不存在，無法採用 Lark 欄位', 'fields': picks_lark})
                        else:
                            if not lark_tc:
                                results.append({'test_case_number': num, 'success': False, 'message': 'Lark 無此紀錄，無法採用 Lark 欄位', 'fields': picks_lark})
                            else:
                                # 僅允許欄位級採納，TCG 以整欄處理
                                std_fields = [k for k in picks_lark if k != 'tcg' and not k.startswith('tcg[')]
                                if std_fields:
                                    _apply_fields_from_lark_to_local(item, lark_tc, std_fields)
                                if 'tcg' in picks_lark:
                                    try:
                                        item.tcg_json = json.dumps([r.model_dump() for r in (lark_tc.tcg or [])], ensure_ascii=False)
                                    except Exception:
                                        item.tcg_json = None
                                applied += 1
                                results.append({'test_case_number': num, 'success': True, 'action': 'pulled_fields_from_lark', 'fields': picks_lark})
                    # 再處理採用本地的欄位 → 推送到 Lark
                    picks_local = [k for k, v in fields_map.items() if v == 'local']
                    if picks_local:
                        # 需要本地 item
                        if not item:
                            results.append({'test_case_number': num, 'success': False, 'message': '本地無此紀錄，無法採用本地欄位', 'fields': picks_local})
                        else:
                            # 僅允許欄位級推送，TCG 以整欄處理
                            update_fields = [k for k in picks_local if not k.startswith('tcg[')]

                            ok = True
                            if update_fields:
                                partial_fields = _build_partial_lark_fields_from_local(item, update_fields)
                                if item.lark_record_id:
                                    ok = ok and self.lark.update_record(self.table_id, item.lark_record_id, partial_fields)
                                else:
                                    new_id = self.lark.create_record(self.table_id, partial_fields)
                                    if new_id:
                                        item.lark_record_id = new_id
                                    else:
                                        ok = False

                            if ok:
                                item.sync_status = SyncStatus.SYNCED
                                applied += 1
                                results.append({'test_case_number': num, 'success': True, 'action': 'pushed_fields_to_lark', 'fields': picks_local})
                            else:
                                results.append({'test_case_number': num, 'success': False, 'message': '上傳/更新 Lark 欄位失敗', 'fields': picks_local})
                else:
                    # 向下相容：整筆來源
                    if src not in ('lark', 'local'):
                        errors.append(f"無效的決策: {d}")
                        continue
                    if src == 'lark':
                        r = lark_by_num.get(num)
                        if not r:
                            results.append({'test_case_number': num, 'success': False, 'message': 'Lark 無此紀錄'})
                            continue
                        tc = _record_to_testcase(r, self.team_id)
                        dummy_stats = TestCaseSyncStats()
                        self._upsert_local_from_tc(sync_db, r, tc, init_mode=False, stats=dummy_stats)
                        applied += 1
                        results.append({'test_case_number': num, 'success': True, 'action': 'pulled_from_lark'})
                    else:
                        item = sync_db.query(TestCaseLocal).filter(
                            TestCaseLocal.team_id == self.team_id,
                            TestCaseLocal.test_case_number == num
                        ).first()
                        if not item:
                            results.append({'test_case_number': num, 'success': False, 'message': '本地無此紀錄'})
                            continue
                        # 從本地還原 TCG
                        try:
                            tcg_data = json.loads(item.tcg_json) if getattr(item, 'tcg_json', None) else []
                            from app.models.lark_types import parse_lark_records
                            tcg_list = parse_lark_records(tcg_data)
                        except Exception:
                            tcg_list = []
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
                            tcg=tcg_list,
                            parent_record=[],
                            team_id=self.team_id,
                        )
                        fields_full = tc.to_lark_sync_fields()
                        ok = True
                        if item.lark_record_id:
                            ok = self.lark.update_record(self.table_id, item.lark_record_id, fields_full)
                        else:
                            new_id = self.lark.create_record(self.table_id, fields_full)
                            if new_id:
                                item.lark_record_id = new_id
                            else:
                                ok = False
                        if ok:
                            item.sync_status = SyncStatus.SYNCED
                            applied += 1
                            results.append({'test_case_number': num, 'success': True, 'action': 'pushed_to_lark'})
                        else:
                            results.append({'test_case_number': num, 'success': False, 'message': '上傳/更新 Lark 失敗'})
            except Exception as e:
                errors.append(str(e))
                results.append({'test_case_number': num, 'success': False, 'message': str(e)})
        sync_db.commit()
        return {'success': len(errors) == 0, 'applied': applied, 'results': results, 'errors': errors}

    # ---------------------- 同步模式 ----------------------
    async def init_sync(self) -> Dict[str, Any]:
        return await run_sync(self.db, self._init_sync_sync)

    def _init_sync_sync(self, sync_db: Session) -> Dict[str, Any]:
        """初始同步：清空本地並從 Lark 匯入，時間以 Lark 為準（僅此模式）"""
        # 取得 Lark 所有記錄
        records = self._get_all_lark_records()
        stats = TestCaseSyncStats()
        logger.info('[TC-SYNC][init] Retrieved %s records from Lark for team=%s', len(records), self.team_id)

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

        logger.info(
            '[TC-SYNC][init] Deduped records: %s (team=%s)',
            len(deduped), self.team_id
        )

        # 清空本地 team 的資料
        # 不再先全部清空，改為：先 upsert，再刪除多餘（更安全，避免外鍵連鎖或事務狀態疑難）

        # 逐筆轉換並 upsert（實為 insert 或 update），處理完去重後的資料
        for r in deduped.values():
            tc = _record_to_testcase(r, self.team_id)
            self._upsert_local_from_tc(sync_db, r, tc, init_mode=True, stats=stats)

        # 刪除本地多餘的（不在 deduped 集合內）
        try:
            keep_numbers = set(deduped.keys())
            if keep_numbers:
                q = sync_db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id)
                to_delete = q.filter(~TestCaseLocal.test_case_number.in_(list(keep_numbers)))
                deleted_count = to_delete.delete(synchronize_session=False)
                logger.info('[TC-SYNC][init] Pruned %s local records not present in Lark', deleted_count)
        except Exception as e:
            logger.warning('[TC-SYNC][init] Prune step skipped due to error: %s', e)

        # 提交
        try:
            sync_db.commit()
        except Exception as e:
            # 進一步診斷外鍵等錯誤
            try:
                from sqlalchemy import text as sql_text
                diag = sync_db.execute(sql_text('PRAGMA foreign_key_check')).fetchall()
                if diag:
                    logger.error('[TC-SYNC][init] PRAGMA foreign_key_check violations: %s', diag)
            except Exception:
                pass
            raise

        logger.info('[TC-SYNC][init] Completed init sync | inserted=%s updated=%s unchanged=%s',
                    stats.inserted, stats.updated, stats.unchanged)
        return {'mode': 'init', **stats.to_dict(), 'total_lark_records': len(records), 'deduped_count': len(deduped)}

    async def diff_sync(self) -> Dict[str, Any]:
        return await run_sync(self.db, self._diff_sync_sync)

    def _diff_sync_sync(self, sync_db: Session) -> Dict[str, Any]:
        """比較差異並互補：Lark -> 本地，和本地 -> Lark（本函式先實作拉回本地；推送到 Lark 可由另一個流程呼叫）"""
        records = self._get_all_lark_records()
        stats = TestCaseSyncStats()
        logger.info('[TC-SYNC][diff] Checking differences | team=%s records=%s', self.team_id, len(records))

        # 建立 Lark 映射（以 test_case_number 為鍵）
        lark_by_number: Dict[str, Dict[str, Any]] = {}
        for r in records:
            fields = r.get('fields', {})
            num = fields.get('Test Case Number') or ''
            if num:
                lark_by_number[str(num)] = r

        logger.info('[TC-SYNC][diff] Lark records after mapping=%s', len(lark_by_number))

        # 1) Lark -> 本地：有就更新、沒有就插入
        for num, rec in lark_by_number.items():
            tc = _record_to_testcase(rec, self.team_id)
            self._upsert_local_from_tc(sync_db, rec, tc, init_mode=False, stats=stats)

        # 2) 本地 -> Lark ：本地有但 Lark 沒有 -> 標記 pending（保留給後續上傳程序）
        local_numbers = {n for n in lark_by_number.keys()}
        q = sync_db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id)
        for local in q:
            if local.test_case_number not in local_numbers:
                # 本地存在，Lark 不存在 -> 標記待上傳
                if local.sync_status != SyncStatus.PENDING:
                    logger.debug('[TC-SYNC][diff] Mark pending for upload | number=%s team=%s',
                                 local.test_case_number, self.team_id)
                    local.sync_status = SyncStatus.PENDING
                    stats.updated += 1

        sync_db.commit()
        logger.info('[TC-SYNC][diff] Completed diff sync | inserted=%s updated=%s unchanged=%s',
                    stats.inserted, stats.updated, stats.unchanged)
        return {'mode': 'diff', **stats.to_dict(), 'total_lark_records': len(records)}

    async def full_update(self, prune: bool = False) -> Dict[str, Any]:
        return await run_sync(self.db, self._full_update_sync, prune)

    def _full_update_sync(self, sync_db: Session, prune: bool = False) -> Dict[str, Any]:
        """以本地覆蓋 Lark：將本地資料（team）全部上傳到 Lark（create 或 update）。
        若 prune=True，同步完成後會刪除 Lark 上本地不存在的記錄（依 Test Case Number 比對）。
        """
        stats = TestCaseSyncStats()

        # 準備本地資料
        locals_q = sync_db.query(TestCaseLocal).filter(TestCaseLocal.team_id == self.team_id)
        locals_list: List[TestCaseLocal] = list(locals_q)
        logger.info('[TC-SYNC][full] Start full update | team=%s local_count=%s prune=%s',
                    self.team_id, len(locals_list), prune)

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

        logger.info('[TC-SYNC][full] Prepared payloads | creates=%s updates=%s', len(creates), len(updates))

        # 執行批次建立
        ok_create, created_ids, create_errors = self.lark.batch_create_records(self.table_id, creates) if creates else (True, [], [])
        if not ok_create:
            stats.errors.extend(create_errors)
        else:
            stats.updated += len(created_ids)
            # 依 Test Case Number 回查剛建立的 Lark 記錄，回填 lark_record_id
            try:
                logger.info('[TC-SYNC][full] Fetching Lark records to backfill record_id after create')
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
        ok_update, updated_count, update_errors = (
            self.lark.parallel_update_records(self.table_id, updates, max_workers=5)
            if updates else (True, 0, [])
        )
        if not ok_update:
            stats.errors.extend(update_errors)
        else:
            stats.updated += updated_count
        logger.info('[TC-SYNC][full] Batch operations result | created=%s updated=%s errors=%s',
                    len(created_ids) if creates else 0, updated_count, len(stats.errors))

        pruned = 0
        prune_errors: List[str] = []
        if prune:
            try:
                logger.info('[TC-SYNC][full] Prune enabled, evaluating remote records for deletion')
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

        sync_db.commit()
        logger.info('[TC-SYNC][full] Full update completed | updated=%s errors=%s pruned=%s',
                    stats.updated, len(stats.errors), pruned if prune else 0)
        result = {'mode': 'full-update', **stats.to_dict(), 'created': len(created_ids) if creates else 0, 'updated': stats.updated}
        if prune:
            result.update({'pruned': pruned, 'prune_errors': prune_errors})
        return result
