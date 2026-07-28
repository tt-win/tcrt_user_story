"""Shared external read surface.

A single implementation of the six read operations shared by
``/api/mcp/*`` and ``/api/app/*``. Read-only: no session open, no
commit/rollback, no mutation, no HTTPException.
"""

from __future__ import annotations

from app.services.external_read.counts import (
    get_section_case_counts,
    get_team_case_counts,
)
from app.services.external_read.errors import (
    ExternalReadError,
    MissingLookupFilterError,
    TestCaseNotFoundError,
    TestCaseSetNotFoundError,
    TeamNotFoundError,
    UnknownRunTypeError,
)
from app.services.external_read.filters import (
    apply_archive_and_status,
    normalize_priority_filter,
    normalize_result_filter,
    parse_run_types,
    parse_status_filters,
    status_match,
)
from app.services.external_read.payloads import (
    build_case_payload,
    config_payload,
    lookup_match_type,
    parse_assignee,
    parse_json_dict,
    parse_json_list,
    parse_tcg_list,
    to_text,
)
from app.services.external_read.queries import (
    ensure_team_exists,
    get_team_test_case_detail_read,
    list_team_test_case_sections_read,
    list_team_test_cases_read,
    list_team_test_runs_read,
    list_teams_read,
    lookup_test_cases_read,
)

__all__ = [
    # payloads
    "to_text",
    "parse_assignee",
    "parse_tcg_list",
    "parse_json_list",
    "parse_json_dict",
    "build_case_payload",
    "lookup_match_type",
    "config_payload",
    # filters
    "normalize_priority_filter",
    "normalize_result_filter",
    "parse_status_filters",
    "parse_run_types",
    "status_match",
    "apply_archive_and_status",
    # counts
    "get_team_case_counts",
    "get_section_case_counts",
    # queries
    "ensure_team_exists",
    "list_teams_read",
    "list_team_test_cases_read",
    "get_team_test_case_detail_read",
    "lookup_test_cases_read",
    "list_team_test_case_sections_read",
    "list_team_test_runs_read",
    # errors
    "ExternalReadError",
    "TeamNotFoundError",
    "TestCaseSetNotFoundError",
    "TestCaseNotFoundError",
    "MissingLookupFilterError",
    "UnknownRunTypeError",
]
