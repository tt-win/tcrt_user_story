"""Test-entry & `@pytest.mark.tcrt(...)` marker parsing (Python AST).

Shared between script sync's marker reconcile (`script_service.sync_markers_for_team`)
and the Suites Test view (`script_service.script_to_dict`). Python-only; fail-open:
parse errors flow into warnings and never raise.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarkerHit:
    """Parsed @pytest.mark.tcrt(...) or `// tcrt: ...` marker."""
    tc_ids: list[str]
    link_type: str  # "primary" | "covers" | "references"
    source_line: int
    raw: str


@dataclass
class TestEntry:
    """A single test function / class / JS test discovered inside an entry-point file."""
    name: str
    kind: str  # "function" | "class"
    line: int
    docstring: str | None = None
    markers: list[MarkerHit] = field(default_factory=list)


_VALID_LINK_TYPES = frozenset({"primary", "covers", "references"})
_TC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _extract_test_entries(
    ref_path: str, content: str
) -> tuple[list[TestEntry], list[dict[str, Any]]]:
    """Detect test functions/classes plus tcrt markers from source.

    Python-only. Returns (entries, warnings). Fail-open: parse errors flow
    into warnings, never raise; entries with bad markers still appear with
    empty markers list.
    """
    return _extract_py_test_entries(content)


def _extract_py_test_entries(
    content: str,
) -> tuple[list[TestEntry], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        warnings.append(
            {
                "type": "parse_error",
                "line": getattr(exc, "lineno", 0) or 0,
                "detail": "python_syntax_error",
            }
        )
        return [], warnings

    entries: list[TestEntry] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            markers = _parse_py_markers(node.decorator_list, warnings)
            entries.append(
                TestEntry(
                    name=node.name,
                    kind="function",
                    line=node.lineno,
                    docstring=ast.get_docstring(node),
                    markers=markers,
                )
            )
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            markers = _parse_py_markers(node.decorator_list, warnings)
            entries.append(
                TestEntry(
                    name=node.name,
                    kind="class",
                    line=node.lineno,
                    docstring=ast.get_docstring(node),
                    markers=markers,
                )
            )
    entries.sort(key=lambda e: (e.line, e.name))
    return entries, warnings


def _parse_py_markers(
    decorator_list: list[Any], warnings: list[dict[str, Any]]
) -> list[MarkerHit]:
    """Return MarkerHit list for any @pytest.mark.tcrt(...) decorators.

    Non-literal args, invalid link_type, malformed TC ids → fail-open: marker
    is dropped, a warning entry is appended, scanning continues.
    """
    markers: list[MarkerHit] = []
    for dec in decorator_list:
        if not _is_pytest_tcrt_call(dec):
            continue
        line = getattr(dec, "lineno", 0)
        tc_ids: list[str] = []
        all_literal = True
        for arg in dec.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                tc_ids.append(arg.value)
            else:
                warnings.append({"type": "non_literal_marker", "line": line})
                all_literal = False
                break
        if not all_literal:
            continue

        link_type = "covers"
        bad_kw = False
        for kw in dec.keywords:
            if kw.arg == "link_type":
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    link_type = kw.value.value.lower()
                else:
                    warnings.append({"type": "non_literal_marker", "line": line})
                    bad_kw = True
                    break
            else:
                # Unknown kwarg — warn but don't drop the marker; future-friendly.
                warnings.append(
                    {"type": "unknown_marker_kwarg", "line": line, "kwarg": kw.arg or ""}
                )
        if bad_kw:
            continue

        if link_type not in _VALID_LINK_TYPES:
            warnings.append(
                {"type": "invalid_link_type", "line": line, "value": link_type}
            )
            continue

        valid_tcs: list[str] = []
        invalid_seen = False
        for tc in tc_ids:
            if _TC_ID_PATTERN.match(tc):
                valid_tcs.append(tc)
            else:
                warnings.append(
                    {"type": "invalid_tc_format", "line": line, "tc_id": tc}
                )
                invalid_seen = True
        if invalid_seen or not valid_tcs:
            continue

        if hasattr(ast, "unparse"):
            try:
                raw = ast.unparse(dec)
            except Exception:  # noqa: BLE001
                raw = "@pytest.mark.tcrt(...)"
        else:
            raw = "@pytest.mark.tcrt(...)"
        markers.append(
            MarkerHit(
                tc_ids=valid_tcs,
                link_type=link_type,
                source_line=line,
                raw=raw,
            )
        )
    return markers


def _is_pytest_tcrt_call(node: Any) -> bool:
    """Strict structural match for `pytest.mark.tcrt(...)` Call node."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "tcrt":
        return False
    inner = func.value
    if not isinstance(inner, ast.Attribute) or inner.attr != "mark":
        return False
    root = inner.value
    return isinstance(root, ast.Name) and root.id == "pytest"


# Back-compat: callers expecting list[str] still work; derives names from entries.
def _extract_test_metadata(ref_path: str, content: str) -> list[str]:
    entries, _ = _extract_test_entries(ref_path, content)
    return sorted({entry.name for entry in entries})


# --- Per-script declared variables (module-level TCRT_VARS) ---

_VAR_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_var_dict(
    node: ast.Dict, line: int, warnings: list[dict[str, Any]]
) -> tuple[str, dict[str, Any]] | None:
    """Parse a {name, secret?, required?, description?} dict literal element."""
    data: dict[str, Any] = {}
    for key_node, val_node in zip(node.keys, node.values):
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            warnings.append({"type": "non_literal_var", "line": line})
            return None
        if not isinstance(val_node, ast.Constant):
            warnings.append({"type": "non_literal_var", "line": line})
            return None
        data[key_node.value] = val_node.value
    name = data.get("name")
    if not isinstance(name, str):
        warnings.append({"type": "invalid_var_name", "line": line, "name": str(name)})
        return None
    spec = {
        "secret": bool(data.get("secret", False)),
        "required": bool(data.get("required", True)),
        "description": data["description"] if isinstance(data.get("description"), str) else None,
    }
    return name, spec


def _extract_declared_vars(
    content: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Discover a script's declared variables from a module-level ``TCRT_VARS``.

    ``TCRT_VARS`` is a list/tuple whose elements are either string literals
    (name only ⇒ secret=False, required=True) or dict literals
    ``{name, secret?, required?, description?}``. Names only — no values.

    Python-only, fail-open: a non-literal ``TCRT_VARS`` or bad element flows
    into warnings (``non_literal_var`` / ``invalid_var_name``) and is skipped;
    never raises. Returns ``(declared, warnings)``.
    """
    warnings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        warnings.append(
            {
                "type": "parse_error",
                "line": getattr(exc, "lineno", 0) or 0,
                "detail": "python_syntax_error",
            }
        )
        return [], warnings

    value_node: Any = None
    decl_line = 0
    for node in tree.body:  # module-level only
        if isinstance(node, ast.Assign):
            targets = node.targets
            candidate = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            candidate = node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "TCRT_VARS" for t in targets):
            value_node = candidate
            decl_line = node.lineno
            break

    if value_node is None:
        return [], warnings

    if not isinstance(value_node, (ast.List, ast.Tuple)):
        warnings.append({"type": "non_literal_var", "line": decl_line})
        return [], warnings

    declared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for elt in value_node.elts:
        line = getattr(elt, "lineno", decl_line)
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            name = elt.value
            spec = {"secret": False, "required": True, "description": None}
        elif isinstance(elt, ast.Dict):
            parsed = _parse_var_dict(elt, line, warnings)
            if parsed is None:
                continue
            name, spec = parsed
        else:
            warnings.append({"type": "non_literal_var", "line": line})
            continue
        if not _VAR_NAME_PATTERN.match(name):
            warnings.append({"type": "invalid_var_name", "line": line, "name": name})
            continue
        if name in seen:
            continue
        seen.add(name)
        declared.append({"name": name, **spec})
    return declared, warnings
