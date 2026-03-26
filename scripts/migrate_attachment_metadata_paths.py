#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import get_sync_engine
from app.models.database_models import TestCaseLocal, TestRunItem
from app.services.attachment_storage import normalize_attachment_metadata


def _normalize_list(payload: str | None) -> tuple[str | None, bool]:
    if not payload:
        return payload, False
    try:
        data = json.loads(payload)
    except Exception:
        return payload, False
    if not isinstance(data, list):
        return payload, False

    changed = False
    normalized: list[Any] = []
    for entry in data:
        if not isinstance(entry, dict):
            normalized.append(entry)
            continue
        updated = normalize_attachment_metadata(entry, allow_missing_path=True)
        changed = changed or updated != entry
        normalized.append(updated)

    return json.dumps(normalized, ensure_ascii=False), changed


def _normalize_history(payload: str | None) -> tuple[str | None, bool]:
    if not payload:
        return payload, False
    try:
        data = json.loads(payload)
    except Exception:
        return payload, False
    if not isinstance(data, list):
        return payload, False

    changed = False
    normalized_history: list[Any] = []
    for item in data:
        if not isinstance(item, dict):
            normalized_history.append(item)
            continue
        copied = dict(item)
        files = copied.get("files")
        if isinstance(files, list):
            normalized_files = []
            for file_entry in files:
                if not isinstance(file_entry, dict):
                    normalized_files.append(file_entry)
                    continue
                updated = normalize_attachment_metadata(file_entry, allow_missing_path=True)
                changed = changed or updated != file_entry
                normalized_files.append(updated)
            copied["files"] = normalized_files
        normalized_history.append(copied)
    return json.dumps(normalized_history, ensure_ascii=False), changed


def migrate(dry_run: bool = True) -> dict[str, int]:
    engine = get_sync_engine()
    summary = {
        "test_case_rows": 0,
        "test_run_execution_rows": 0,
        "test_run_history_rows": 0,
    }

    with Session(engine) as session:
        for case in session.query(TestCaseLocal).all():
            updated, changed = _normalize_list(case.attachments_json)
            if changed:
                summary["test_case_rows"] += 1
                if not dry_run:
                    case.attachments_json = updated

        for item in session.query(TestRunItem).all():
            updated_results, changed_results = _normalize_list(item.execution_results_json)
            if changed_results:
                summary["test_run_execution_rows"] += 1
                if not dry_run:
                    item.execution_results_json = updated_results

            updated_history, changed_history = _normalize_history(item.upload_history_json)
            if changed_history:
                summary["test_run_history_rows"] += 1
                if not dry_run:
                    item.upload_history_json = updated_history

        if not dry_run:
            session.commit()
        else:
            session.rollback()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize attachment metadata to relative-path-first mode.")
    parser.add_argument("--write", action="store_true", help="Persist normalized metadata back to the database")
    args = parser.parse_args()

    summary = migrate(dry_run=not args.write)
    mode = "write" if args.write else "dry-run"
    print(json.dumps({"mode": mode, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
