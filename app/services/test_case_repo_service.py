#!/usr/bin/env python3
"""
Test Case Repository 服務層（本地資料庫）

- 提供以 TestCaseLocal 為主的查詢與轉換功能
- 維持與現有 TestCaseResponse 相容的輸出格式
"""
from __future__ import annotations

import json
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.database_models import TestCaseLocal, TestCaseSection
from app.models.test_case import TestCaseResponse
from app.models.lark_types import Priority, TestResultStatus


def _safe_json_len(text: Optional[str]) -> int:
    if not text:
        return 0
    try:
        data = json.loads(text)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def _to_response(
    row: TestCaseLocal,
    include_attachments: bool = False,
    section_meta: Optional[Dict[str, Any]] = None,
) -> TestCaseResponse:
    attachments: list = []
    if include_attachments:
        try:
            data = json.loads(row.attachments_json) if row.attachments_json else []
            base_url = "/attachments"
            for it in data if isinstance(data, list) else []:
                file_token = it.get("stored_name") or it.get("name") or ""
                name = it.get("name") or it.get("stored_name") or "file"
                size = int(it.get("size") or 0)
                mime = it.get("type") or "application/octet-stream"
                rel = it.get("relative_path") or ""
                url = f"{base_url}/{rel}" if rel else ""
                attachments.append({
                    "file_token": file_token,
                    "name": name,
                    "size": size,
                    "type": mime,
                    "url": url,
                    "tmp_url": url,
                })
        except Exception:
            attachments = []

    # 解析 TCG - 現在 tcg_json 存儲為簡單字串陣列：["TCG-100007", "TCG-93178"]
    tcg_items: list = []
    try:
        if row.tcg_json:
            data = json.loads(row.tcg_json)
            # tcg_json 現在是簡單的字串列表，不是複雜的 LarkRecord 物件
            if isinstance(data, list):
                tcg_items = [str(t) for t in data if t]
            elif isinstance(data, str):
                tcg_items = [data]
    except Exception:
        tcg_items = []

    section_id = row.test_case_section_id
    section_info = section_meta or {}
    section_name = section_info.get("name")
    section_path = section_info.get("path") or ""
    section_level = section_info.get("level")
    if section_id is None:
        section_name = section_name or "Unassigned"
        section_level = section_level or 1

    return TestCaseResponse(
        record_id=row.lark_record_id or str(row.id),
        test_case_number=row.test_case_number,
        title=row.title,
        priority=row.priority.value if hasattr(row.priority, 'value') else (row.priority or ''),
        precondition=row.precondition,
        steps=row.steps,
        expected_result=row.expected_result,
        assignee=None,  # 保持相容但目前不展開
        test_result=row.test_result.value if hasattr(row.test_result, 'value') else (row.test_result or None),
        attachments=attachments,
        test_results_files=[],
        user_story_map=[],
        tcg=tcg_items,
        parent_record=[],
        team_id=row.team_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_sync_at=row.last_sync_at,
        raw_fields={},
        test_case_section_id=section_id,
        section_name=section_name,
        section_path=section_path,
        section_level=section_level,
    )


class TestCaseRepoService:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        team_id: int,
        search: Optional[str] = None,
        tcg_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        test_result_filter: Optional[str] = None,
        assignee_filter: Optional[str] = None,
        test_case_set_id: Optional[int] = None,
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
        skip: int = 0,
        limit: int = 1000,
    ) -> List[TestCaseResponse]:
        q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == team_id)

        # 過濾特定 Test Case Set 的 test case
        if test_case_set_id:
            # 直接過濾 test_case_set_id 欄位
            q = q.filter(TestCaseLocal.test_case_set_id == test_case_set_id)

        # 搜尋
        if search and search.strip():
            s = f"%{search.strip()}%"
            q = q.filter(or_(
                TestCaseLocal.title.ilike(s),
                TestCaseLocal.test_case_number.ilike(s)
            ))

        # TCG 過濾（支援多個票號搜尋，以逗號分隔）
        if tcg_filter and tcg_filter.strip():
            tickets = [t.strip() for t in tcg_filter.split(',') if t.strip()]
            if tickets:
                # 使用 SQLite json_each 進行精確搜尋，避免字串比對誤判
                # 需確保 tcg_json 是有效 JSON 陣列且非空
                # 使用 literal params 避免 SQL Injection
                conditions = []
                for t in tickets:
                    conditions.append(
                        text(f"EXISTS (SELECT 1 FROM json_each(test_cases.tcg_json) WHERE value LIKE '%{t}%')")
                    )
                
                q = q.filter(and_(
                    TestCaseLocal.tcg_json.is_not(None),
                    TestCaseLocal.tcg_json != '',
                    or_(*conditions)
                ))

        # 優先級
        if priority_filter:
            try:
                pr = Priority(priority_filter)
                q = q.filter(TestCaseLocal.priority == pr)
            except Exception:
                q = q.filter(TestCaseLocal.priority == priority_filter)

        # 測試結果
        if test_result_filter:
            try:
                tr = TestResultStatus(test_result_filter)
                q = q.filter(TestCaseLocal.test_result == tr)
            except Exception:
                q = q.filter(TestCaseLocal.test_result == test_result_filter)

        # 指派人（在 assignee_json 中 LIKE 名稱或 email）
        if assignee_filter and assignee_filter.strip():
            s = f"%{assignee_filter.strip()}%"
            q = q.filter(TestCaseLocal.assignee_json.ilike(s))

        # 排序
        order_desc = (sort_order or 'desc').lower() == 'desc'
        sort_field_map = {
            'title': TestCaseLocal.title,
            'priority': TestCaseLocal.priority,
            'test_case_number': TestCaseLocal.test_case_number,
            'test_result': TestCaseLocal.test_result,
            'created_at': TestCaseLocal.created_at,
            'updated_at': TestCaseLocal.updated_at,
        }
        col = sort_field_map.get(sort_by, TestCaseLocal.created_at)
        q = q.order_by(col.desc() if order_desc else col.asc())

        # 分頁並取得結果
        q = q.offset(skip).limit(limit)
        rows = q.all()
        section_lookup = self._build_section_lookup(rows)

        return [
            _to_response(
                r,
                include_attachments=False,
                section_meta=section_lookup.get(r.test_case_section_id),
            )
            for r in rows
        ]

    def count(
        self,
        team_id: int,
        search: Optional[str] = None,
        tcg_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        test_result_filter: Optional[str] = None,
        assignee_filter: Optional[str] = None,
        test_case_set_id: Optional[int] = None,
    ) -> int:
        q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == team_id)

        # 過濾特定 Test Case Set 的 test case
        if test_case_set_id:
            # 直接過濾 test_case_set_id 欄位
            q = q.filter(TestCaseLocal.test_case_set_id == test_case_set_id)

        if search and search.strip():
            s = f"%{search.strip()}%"
            q = q.filter(or_(
                TestCaseLocal.title.ilike(s),
                TestCaseLocal.test_case_number.ilike(s)
            ))
        if tcg_filter and tcg_filter.strip():
            tickets = [t.strip() for t in tcg_filter.split(',') if t.strip()]
            if tickets:
                conditions = []
                for t in tickets:
                    conditions.append(
                        text(f"EXISTS (SELECT 1 FROM json_each(test_cases.tcg_json) WHERE value LIKE '%{t}%')")
                    )
                q = q.filter(and_(
                    TestCaseLocal.tcg_json.is_not(None),
                    TestCaseLocal.tcg_json != '',
                    or_(*conditions)
                ))
        if priority_filter:
            try:
                pr = Priority(priority_filter)
                q = q.filter(TestCaseLocal.priority == pr)
            except Exception:
                q = q.filter(TestCaseLocal.priority == priority_filter)
        if test_result_filter:
            try:
                tr = TestResultStatus(test_result_filter)
                q = q.filter(TestCaseLocal.test_result == tr)
            except Exception:
                q = q.filter(TestCaseLocal.test_result == test_result_filter)
        if assignee_filter and assignee_filter.strip():
            s = f"%{assignee_filter.strip()}%"
            q = q.filter(TestCaseLocal.assignee_json.ilike(s))

        return q.count()

    def get_by_lark_record_id(self, team_id: int, record_id: str, include_attachments: bool = True) -> Optional[TestCaseResponse]:
        row = self.db.query(TestCaseLocal).filter(
            TestCaseLocal.team_id == team_id,
            TestCaseLocal.lark_record_id == record_id
        ).first()
        if not row:
            return None
        section_meta = self._build_section_lookup([row]).get(row.test_case_section_id)
        return _to_response(
            row,
            include_attachments=include_attachments,
            section_meta=section_meta,
        )

    def _build_section_lookup(self, rows: List[TestCaseLocal]) -> Dict[int, Dict[str, Any]]:
        """建立 Section 快取，供回傳時附帶區段資訊"""
        lookup: Dict[int, Dict[str, Any]] = {}
        if not rows:
            return lookup

        set_ids = {row.test_case_set_id for row in rows if row.test_case_set_id}
        if not set_ids:
            return lookup

        sections = (
            self.db.query(TestCaseSection)
            .filter(TestCaseSection.test_case_set_id.in_(set_ids))
            .all()
        )

        if not sections:
            return lookup

        raw_map: Dict[int, Dict[str, Any]] = {}
        for section in sections:
            raw_map[section.id] = {
                "name": section.name,
                "level": section.level,
                "parent_section_id": section.parent_section_id,
            }

        path_cache: Dict[int, str] = {}

        def build_path(section_id: Optional[int], seen: Optional[set[int]] = None) -> str:
            if not section_id or section_id not in raw_map:
                return ""
            if section_id in path_cache:
                return path_cache[section_id]
            seen = (seen or set()).copy()
            if section_id in seen:
                return raw_map[section_id]["name"]
            seen.add(section_id)
            parent_id = raw_map[section_id]["parent_section_id"]
            parent_path = build_path(parent_id, seen)
            path = (
                f"{parent_path}/{raw_map[section_id]['name']}"
                if parent_path
                else raw_map[section_id]["name"]
            )
            path_cache[section_id] = path
            return path

        for section_id, data in raw_map.items():
            lookup[section_id] = {
                "name": data["name"],
                "level": data["level"],
                "path": build_path(section_id),
            }

        return lookup
