"""Unit tests for _normalize_test_data_suggestions / _normalize_test_data_items."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.qa_ai_helper_service import QAAIHelperService


def test_normalize_suggestions_drops_empty_name_and_fills_defaults() -> None:
    raw = [
        {"id": "s1", "category": "text", "name": "登入帳號"},
        {"category": "CREDENTIAL", "name": "密碼"},  # upper-case, missing id
        {"category": "bogus", "name": "X"},  # unknown category → text
        {"category": "text", "name": "   "},  # empty → drop
        "not-a-dict",
    ]
    out = QAAIHelperService._normalize_test_data_suggestions(raw)
    assert len(out) == 3
    assert out[0] == {"id": "s1", "category": "text", "name": "登入帳號"}
    assert out[1]["category"] == "credential"
    assert out[1]["name"] == "密碼"
    assert out[1]["id"]  # auto-assigned uuid
    assert out[2]["category"] == "text"
    assert out[2]["name"] == "X"


def test_normalize_suggestions_returns_empty_for_non_list() -> None:
    assert QAAIHelperService._normalize_test_data_suggestions(None) == []
    assert QAAIHelperService._normalize_test_data_suggestions({"a": 1}) == []
    assert QAAIHelperService._normalize_test_data_suggestions("x") == []


def test_normalize_items_aligns_to_suggestions_and_forces_credential_empty() -> None:
    suggestions = [
        {"id": "s1", "category": "credential", "name": "登入帳號"},
        {"id": "s2", "category": "number", "name": "帳號長度上限"},
        {"id": "s3", "category": "email", "name": "通知收件人"},
    ]
    raw = [
        {"category": "credential", "name": "登入帳號", "value": "admin"},  # credential → empty
        {"category": "number", "name": "帳號長度上限", "value": "20"},
        # Missing third → empty value
    ]
    out = QAAIHelperService._normalize_test_data_items(raw, suggestions=suggestions)
    assert len(out) == 3
    assert out[0] == {"id": "s1", "category": "credential", "name": "登入帳號", "value": ""}
    assert out[1]["value"] == "20"
    assert out[2]["value"] == ""


def test_normalize_items_without_suggestions_preserves_valid_entries() -> None:
    raw = [
        {"id": "a", "category": "text", "name": "欄位", "value": "v"},
        {"category": "credential", "name": "帳號", "value": "leaked"},  # forced empty
        {"category": "text", "name": ""},  # dropped
    ]
    out = QAAIHelperService._normalize_test_data_items(raw)
    assert len(out) == 2
    assert out[0]["value"] == "v"
    assert out[1]["category"] == "credential"
    assert out[1]["value"] == ""


def test_normalize_items_non_list_returns_empty_without_suggestions() -> None:
    assert QAAIHelperService._normalize_test_data_items(None) == []
    assert QAAIHelperService._normalize_test_data_items("x") == []
