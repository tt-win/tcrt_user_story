"""Enforcement test: business code must not call emit_event directly."""

import ast
import pathlib
import pytest


BUSINESS_DIRS = [
    "app/api",
    "app/services",
    "app/db_access",
    "app/audit",
    "app/models",
    "app/templates",
    "app/static",
]

ALLOWED_DIRECT_CALLS = {
    "app/services/observability/emit.py",
    "app/testsuite/test_emit_enforcement.py",
}

ALLOWED_CALLS = {
    "emit_event",
    "safe_emit_event",
    "emit_audit_event",
    "emit_ops_event",
}


def find_python_files():
    """Find all Python files in business directories."""
    files = []
    for base in BUSINESS_DIRS:
        base_path = pathlib.Path(base)
        if base_path.exists():
            files.extend(base_path.rglob("*.py"))
    return files


def find_emit_calls(filepath: pathlib.Path) -> list[tuple[int, str]]:
    """Find all calls to emit_* functions in a Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    tree = ast.parse(source)
    calls = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name and func_name.startswith("emit_") and func_name not in ALLOWED_CALLS:
                # Get line number
                line_num = node.lineno
                line = source.splitlines()[line_num - 1].strip() if line_num <= len(source.splitlines()) else ""
                calls.append((line_num, line))

    return calls


def test_no_direct_emit_event_in_business_code():
    """Ensure business code only calls safe_emit_event / emit_audit_event / emit_ops_event."""
    violations = []

    for filepath in find_python_files():
        rel_path = str(filepath)
        if rel_path in ALLOWED_DIRECT_CALLS:
            continue

        calls = find_emit_calls(filepath)
        for line_num, line in calls:
            violations.append(f"{rel_path}:{line_num}: {line}")

    if violations:
        pytest.fail(
            "Direct calls to emit_event (or other emit_* not in ALLOWED_CALLS) found in business code:\n"
            + "\n".join(violations)
            + "\n\nUse safe_emit_event, emit_audit_event, or emit_ops_event instead."
        )


if __name__ == "__main__":
    test_no_direct_emit_event_in_business_code()
    print("Enforcement test passed!")