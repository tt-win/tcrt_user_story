from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.mcp_dependencies import (
    AUDIT_RESOURCE_ID_MAX_LEN,
    _build_audit_resource_id,
)


def test_build_audit_resource_id_within_limit():
    path = "/api/mcp/teams/2/test-cases"
    query = "skip=0&limit=100&strict_set=false"
    value = _build_audit_resource_id(path, query)

    assert value == f"{path}?{query}"
    assert len(value) <= AUDIT_RESOURCE_ID_MAX_LEN


def test_build_audit_resource_id_over_limit_uses_hash_suffix():
    path = "/api/mcp/teams/2/test-cases"
    query = (
        "skip=0&limit=100&strict_set=false&include_content=true"
        "&set_id=3153&search=93178.010.010&tcg=TP-1001&assignee=alice"
    )
    value = _build_audit_resource_id(path, query)

    assert len(value) == AUDIT_RESOURCE_ID_MAX_LEN
    assert value.startswith(path)
    assert "#h=" in value


def test_build_audit_resource_id_over_limit_is_deterministic():
    path = "/api/mcp/teams/2/test-cases"
    query = (
        "skip=0&limit=100&strict_set=false&include_content=true"
        "&set_id=3153&search=93178.010.010&tcg=TP-1001&assignee=alice"
    )
    value_1 = _build_audit_resource_id(path, query)
    value_2 = _build_audit_resource_id(path, query)

    assert value_1 == value_2
