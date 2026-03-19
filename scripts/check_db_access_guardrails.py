#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db_access.guardrails import format_guardrail_violations, scan_db_access_guardrails


def main() -> int:
    violations = scan_db_access_guardrails(PROJECT_ROOT)
    print(format_guardrail_violations(violations))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
