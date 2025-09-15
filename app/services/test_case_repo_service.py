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

from app.models.database_models import TestCaseLocal
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


def _to_response(row: TestCaseLocal, include_attachments: bool = False) -> TestCaseResponse:
    attachments: list = []
    if include_attachments:
        try:
            data = json.loads(row.attachments_json) if row.attachments_json else []
            base_url = "/attachments"
            # 轉成與前端相容的 LarkAttachment 形狀
            # 必填: file_token, name, size, type, url
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
        tcg=[],
        parent_record=[],
        team_id=row.team_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_sync_at=row.last_sync_at,
        raw_fields={},
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
        sort_by: str = 'created_at',
        sort_order: str = 'desc',
        skip: int = 0,
        limit: int = 1000,
    ) -> List[TestCaseResponse]:
        q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == team_id)

        # 搜尋
        if search and search.strip():
            s = f"%{search.strip()}%"
            q = q.filter(or_(
                TestCaseLocal.title.ilike(s),
                TestCaseLocal.test_case_number.ilike(s)
            ))

        # TCG 過濾（簡化：在 tcg_json 文字中 LIKE）
        if tcg_filter and tcg_filter.strip():
            s = f"%{tcg_filter.strip()}%"
            q = q.filter(TestCaseLocal.tcg_json.ilike(s))

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

        # 分頁
        q = q.offset(skip).limit(limit)

        return [_to_response(r, include_attachments=False) for r in q.all()]

    def count(
        self,
        team_id: int,
        search: Optional[str] = None,
        tcg_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        test_result_filter: Optional[str] = None,
        assignee_filter: Optional[str] = None,
    ) -> int:
        q = self.db.query(TestCaseLocal).filter(TestCaseLocal.team_id == team_id)

        if search and search.strip():
            s = f"%{search.strip()}%"
            q = q.filter(or_(
                TestCaseLocal.title.ilike(s),
                TestCaseLocal.test_case_number.ilike(s)
            ))
        if tcg_filter and tcg_filter.strip():
            s = f"%{tcg_filter.strip()}%"
            q = q.filter(TestCaseLocal.tcg_json.ilike(s))
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
        return _to_response(row, include_attachments=include_attachments) if row else None
