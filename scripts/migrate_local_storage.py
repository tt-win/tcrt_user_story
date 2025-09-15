#!/usr/bin/env python3
"""
Migration script
- Ensures new DB columns exist (invokes database_init.py --auto-fix)
- Ensures required attachment directories exist

Usage:
  python scripts/migrate_local_storage.py [--no-db] [--no-dirs] [--verbose]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    PROJECT_ROOT / "attachments",
    PROJECT_ROOT / "attachments" / "test-cases",
    PROJECT_ROOT / "attachments" / "test-runs",
]

def ensure_dirs(verbose: bool = False):
    for d in REQUIRED_DIRS:
        d.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"[DIR] ensured: {d}")


def run_db_autofix(verbose: bool = False):
    cmd = [sys.executable, str(PROJECT_ROOT / "database_init.py"), "--auto-fix", "--quiet"]
    if verbose:
        cmd = [sys.executable, str(PROJECT_ROOT / "database_init.py"), "--auto-fix", "--verbose"]
        print(f"[DB] running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def main():
    p = argparse.ArgumentParser(description="Local storage migration helper")
    p.add_argument("--no-db", action="store_true", help="Skip database auto-fix")
    p.add_argument("--no-dirs", action="store_true", help="Skip directory creation")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    args = p.parse_args()

    if not args.no_dirs:
        ensure_dirs(verbose=args.verbose)

    if not args.no_db:
        run_db_autofix(verbose=args.verbose)

    if args.verbose:
        print("[OK] migration steps completed")

if __name__ == "__main__":
    main()
