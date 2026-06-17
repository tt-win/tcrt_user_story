"""Shared scan-pattern matching for automation script discovery.

`script_service.sync_scripts` uses these helpers to filter the repo walk, so a
single `scan.include` / `scan.exclude` block in `tcrt-automation.yml` drives
which repo files become tracked automation scripts.

Patterns are GLOBS (``fnmatch``), matched against both the file basename and
the full normalized path. Globs were chosen over regexes because they are the
format already documented in `tcrt-automation.yml` examples and are far less
error-prone for users to write by hand.
"""
from __future__ import annotations

import fnmatch
from collections.abc import Iterable

DEFAULT_SCAN_PATH = "tests/"

DEFAULT_INCLUDE_PATTERNS: list[str] = [
    "test_*.py",
    "*_test.py",
]

DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "*conftest*",
    "*/pages/*",
    "*/page_objects/*",
    "*/pom/*",
    "*/flows/*",
    "*/fixtures/*",
    "*/resources/*",
    "*/config/*",
    "*/utils/*",
    "*/helpers/*",
    "*/scripts/*",
    "*/reports/*",
]


def _any_match(normalized: str, basename: str, patterns: Iterable[str]) -> bool:
    return any(
        fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(basename, pattern)
        for pattern in patterns
    )


def matches_include(path: str, include_patterns: Iterable[str] | None) -> bool:
    """True when *path* matches any include glob (empty/None ⇒ include all)."""
    patterns = list(include_patterns or [])
    if not patterns:
        return True
    normalized = path.strip("/")
    basename = normalized.rsplit("/", 1)[-1]
    return _any_match(normalized, basename, patterns)


def matches_exclude(path: str, exclude_patterns: Iterable[str] | None) -> bool:
    """True when *path* matches any exclude glob (empty/None ⇒ exclude none)."""
    patterns = list(exclude_patterns or [])
    if not patterns:
        return False
    normalized = path.strip("/")
    basename = normalized.rsplit("/", 1)[-1]
    return _any_match(normalized, basename, patterns)


def matches_scan_filters(
    path: str,
    include_patterns: Iterable[str] | None,
    exclude_patterns: Iterable[str] | None,
) -> bool:
    """True when *path* passes the include filter and is not excluded."""
    return matches_include(path, include_patterns) and not matches_exclude(path, exclude_patterns)
