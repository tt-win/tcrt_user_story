"""Helpers for QA AI Helper testcase title generation."""

from __future__ import annotations

import re
from typing import Sequence

_LEADING_LIST_MARKER_PATTERN = re.compile(r"^\s*(?:\d+[\.\)]\s*|[-*]\s*)")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_GENERIC_TITLE_KEYS = {
    "已準備符合需求的測試資料",
    "使用者具備執行本案例所需權限",
    "進入目標頁面或操作入口",
    "執行需求描述的主要操作",
    "檢查系統回應與畫面結果",
    "系統符合該案例預期結果",
    "系統符合需求規則",
    "系統符合預期結果",
}
_SUMMARY_PREFIX_PATTERNS = (
    re.compile(r"^.*?後應(?:該)?"),
    re.compile(r"^.*?後可(?:以)?"),
    re.compile(r"^.*?後會"),
    re.compile(r"^.*?時應(?:該)?"),
    re.compile(r"^.*?\bthen\b\s*", re.IGNORECASE),
    re.compile(r"^.*?\bshould\b\s*", re.IGNORECASE),
    re.compile(r"^.*?\bmust\b\s*", re.IGNORECASE),
    re.compile(r"^.*?\bverify(?: that)?\b\s*", re.IGNORECASE),
    re.compile(r"^.*?\bconfirm(?: that)?\b\s*", re.IGNORECASE),
)


def _clean_title_text(value: str) -> str:
    normalized = _LEADING_LIST_MARKER_PATTERN.sub("", str(value or ""))
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized)
    return normalized.strip(" \t\r\n-–—:：;；,，。.!！?？")


def _title_key(value: str) -> str:
    return _clean_title_text(value).casefold()


def _strip_summary_prefixes(value: str) -> str:
    candidate = _clean_title_text(value)
    if not candidate:
        return ""

    for pattern in _SUMMARY_PREFIX_PATTERNS:
        rewritten = pattern.sub("", candidate).strip(" ：:，,")
        if rewritten and rewritten != candidate:
            candidate = _clean_title_text(rewritten)
            break

    candidate = re.sub(r"^(?:確認|檢查|驗證)\s*", "", candidate).strip(" ：:，,")
    candidate = re.sub(r"^(?:verify|confirm)\s*", "", candidate, flags=re.IGNORECASE).strip(" ：:，,")
    return _clean_title_text(candidate)


def is_direct_testcase_title_copy(
    title: str,
    raw_candidates: Sequence[str | None] | None,
) -> bool:
    title_key = _title_key(title)
    if not title_key:
        return False
    return any(title_key == _title_key(candidate or "") for candidate in (raw_candidates or []) if _title_key(candidate or ""))


def build_testcase_title_summary(
    *,
    steps: Sequence[str] | None = None,
    expected_results: Sequence[str] | None = None,
    step_hints: Sequence[str] | None = None,
    expected_hints: Sequence[str] | None = None,
    seed_body_text: str | None = None,
    scenario_title: str | None = None,
    section_title: str | None = None,
    title_hint: str | None = None,
    verification_item_summary: str | None = None,
    fallback_title: str | None = None,
    disallowed_titles: Sequence[str | None] | None = None,
) -> str:
    generic_keys = {_title_key(value) for value in _GENERIC_TITLE_KEYS}
    disallowed_keys = {
        _title_key(candidate or "")
        for candidate in (disallowed_titles or [])
        if _title_key(candidate or "")
    }

    def _pick(candidates: Sequence[str] | None) -> str:
        for raw in candidates or []:
            candidate = _strip_summary_prefixes(str(raw or ""))
            candidate_key = _title_key(candidate)
            if not candidate_key or candidate_key in generic_keys or candidate_key in disallowed_keys:
                continue
            return candidate
        return ""

    title = _pick(expected_results)
    if title:
        return title

    title = _pick(expected_hints)
    if title:
        return title

    title = _pick(steps)
    if title:
        return title

    title = _pick(step_hints)
    if title:
        return title

    for raw in (
        seed_body_text,
        scenario_title,
        section_title,
        title_hint,
        verification_item_summary,
    ):
        candidate = _strip_summary_prefixes(str(raw or ""))
        candidate_key = _title_key(candidate)
        if not candidate_key or candidate_key in generic_keys or candidate_key in disallowed_keys:
            continue
        return candidate

    fallback = _clean_title_text(str(fallback_title or ""))
    return fallback or "Generated testcase"
