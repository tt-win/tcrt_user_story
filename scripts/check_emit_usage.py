#!/usr/bin/env python3
"""
Check that emit_event is only called from test files or via safe_emit_event wrapper.
This is a simple AST-based linter that can be run in CI.
"""
import ast
import sys
from pathlib import Path
from typing import List, Tuple

FORBIDDEN_CALL = "emit_event"
ALLOWED_WRAPPER = "safe_emit_event"
TEST_PATHS = ["app/testsuite", "tests", "test_"]

class EmitCallVisitor(ast.NodeVisitor):
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.violations: List[Tuple[int, str]] = []
        self.in_test_file = any(p in filepath for p in TEST_PATHS)
    
    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == FORBIDDEN_CALL:
            if not self.in_test_file:
                # Check if it's inside a function named safe_emit_event (unlikely)
                # or if the file is a test file
                self.violations.append((
                    node.lineno,
                    f"Direct call to '{FORBIDDEN_CALL}' found. Use '{ALLOWED_WRAPPER}' instead."
                ))
        elif isinstance(node.func, ast.Attribute) and node.func.attr == FORBIDDEN_CALL:
            if not self.in_test_file:
                self.violations.append((
                    node.lineno,
                    f"Direct call to '{FORBIDDEN_CALL}' found. Use '{ALLOWED_WRAPPER}' instead."
                ))
        self.generic_visit(node)

def check_file(filepath: Path) -> List[Tuple[int, str]]:
    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
        visitor = EmitCallVisitor(str(filepath))
        visitor.visit(tree)
        return visitor.violations
    except SyntaxError:
        return []

def main():
    violations = []
    for py_file in Path("app").rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        file_violations = check_file(py_file)
        for lineno, msg in file_violations:
            violations.append((str(py_file), lineno, msg))
    
    if violations:
        print("❌ Found direct calls to emit_event (use safe_emit_event instead):")
        for filepath, lineno, msg in violations:
            print(f"  {filepath}:{lineno}: {msg}")
        sys.exit(1)
    else:
        print("✅ No direct emit_event calls found outside tests")
        sys.exit(0)

if __name__ == "__main__":
    main()
