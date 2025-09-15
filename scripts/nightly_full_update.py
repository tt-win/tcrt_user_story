#!/usr/bin/env python3
"""
Nightly full-update sync runner
- Runs full-update sync every day at 00:00 server local time
- By default runs for all teams; can target a specific team via --team-id

Usage:
  python scripts/nightly_full_update.py            # run daily at 00:00 for all teams
  python scripts/nightly_full_update.py --team-id 4 # run daily at 00:00 for team 4

Notes:
- This script is designed to be kept running (e.g., via systemd, pm2, Docker, or a tmux session)
- It computes next midnight in server local time and sleeps until then, then runs sync
"""
from __future__ import annotations

import argparse
import datetime as dt
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "sync_test_cases.py"

_stop = False

def _signal_handler(signum, frame):
    global _stop
    _stop = True


def seconds_until_next_midnight(now: dt.datetime | None = None) -> int:
    if now is None:
        now = dt.datetime.now()
    # Next midnight in local time
    tomorrow = now.date() + dt.timedelta(days=1)
    next_midnight = dt.datetime.combine(tomorrow, dt.time(0, 0, 0))
    delta = next_midnight - now
    secs = int(delta.total_seconds())
    return max(secs, 0)


def run_sync(team_id: int | None, verbose: bool = False) -> int:
    cmd = [PYTHON, str(SYNC_SCRIPT), "--mode", "full-update"]
    if team_id:
        cmd += ["--team-id", str(team_id)]
    else:
        cmd += ["--all"]
    if verbose:
        print(f"[SYNC] {dt.datetime.now().isoformat()} running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if verbose:
        print(f"[SYNC] exit code: {proc.returncode}")
    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="Nightly full-update sync runner")
    parser.add_argument("--team-id", type=int, default=None, help="Target a single team id. Omit to run for all teams.")
    parser.add_argument("--run-now", action="store_true", help="Run immediately once before scheduling.")
    parser.add_argument("--verbose", action="store_true", help="Verbose logs.")
    args = parser.parse_args()

    # Setup signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _signal_handler)

    if args.run_now:
        rc = run_sync(args.team_id, verbose=args.verbose)
        if rc != 0 and args.verbose:
            print(f"[WARN] initial run returned {rc}")

    while not _stop:
        secs = seconds_until_next_midnight()
        if args.verbose:
            print(f"[SCHED] sleeping {secs} seconds until next midnight...")
        # Sleep in small chunks so we can respond to signals
        slept = 0
        chunk = 60
        while slept < secs and not _stop:
            to_sleep = min(chunk, secs - slept)
            time.sleep(to_sleep)
            slept += to_sleep
        if _stop:
            break
        # Recheck time drift then run
        rc = run_sync(args.team_id, verbose=args.verbose)
        if rc != 0 and args.verbose:
            print(f"[WARN] sync returned non-zero: {rc}")
        # Loop to next midnight

    if args.verbose:
        print("[EXIT] graceful shutdown")


if __name__ == "__main__":
    main()
