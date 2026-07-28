#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

main = importlib.import_module("app.db_cutover_workflow").main


if __name__ == "__main__":
    raise SystemExit(main())
