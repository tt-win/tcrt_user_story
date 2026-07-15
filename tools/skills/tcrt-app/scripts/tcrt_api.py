#!/usr/bin/env python3
"""Thin authenticated HTTP client for the TCRT App Token API (``/api/app/*``).

Usage:
    python3 tcrt_api.py check
    python3 tcrt_api.py <METHOD> <PATH> [--data '<json>'] [--query 'k=v&k2=v2']

Examples:
    python3 tcrt_api.py check
    python3 tcrt_api.py GET /api/app/teams/1/test-cases --query "limit=20"
    python3 tcrt_api.py POST /api/app/teams/1/test-cases \\
        --data '{"test_case_number": "TC-1001", "title": "Login with valid credentials"}'
    python3 tcrt_api.py DELETE /api/app/teams/1/test-cases/42

Config resolution — both TCRT_BASE_URL and TCRT_APP_TOKEN come from one env
file (first match wins):
    1. $TCRT_ENV_FILE     - absolute path to an env file, set at runtime
    2. <skill root>/.env  - drop an env file named ".env" next to this
                            skill's SKILL.md (copy .env.example and fill it in)

A real environment variable of the same name (TCRT_BASE_URL / TCRT_APP_TOKEN)
always overrides whatever is in the env file, same as a normal .env loader.

The raw token is never printed, logged, or included in error output by this script.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = SKILL_DIR / ".env"


def _parse_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_config() -> tuple[str, str]:
    override = os.environ.get("TCRT_ENV_FILE")
    env_path = Path(override).expanduser() if override else DEFAULT_ENV_FILE
    file_values = _parse_env_file(env_path)

    base_url = os.environ.get("TCRT_BASE_URL") or file_values.get("TCRT_BASE_URL")
    token = os.environ.get("TCRT_APP_TOKEN") or file_values.get("TCRT_APP_TOKEN")

    missing = [name for name, value in (("TCRT_BASE_URL", base_url), ("TCRT_APP_TOKEN", token)) if not value]
    if missing:
        raise SystemExit(
            f"[tcrt-app] Missing {', '.join(missing)}.\n"
            f"Env file checked: {env_path} ({'found' if env_path.is_file() else 'not found'})\n"
            "Set up config first:\n"
            f"  1. Copy {SKILL_DIR / '.env.example'} to {DEFAULT_ENV_FILE} and fill in both\n"
            "     TCRT_BASE_URL and TCRT_APP_TOKEN, or\n"
            "  2. Set TCRT_ENV_FILE=/absolute/path/to/your/.env before running this script, or\n"
            "  3. Export TCRT_BASE_URL / TCRT_APP_TOKEN directly as real environment variables.\n"
            "Tokens are issued from TCRT's Team Management UI (App Tokens tab) by a team admin;\n"
            "this script only consumes an existing token, it does not create one."
        )
    return base_url.rstrip("/"), token


def _encode_multipart(file_specs: list) -> tuple[bytes, str]:
    """Build a multipart/form-data body from ``field=@path`` specs (curl -F style)."""
    boundary = "----tcrtapp" + os.urandom(16).hex()
    parts: list = []
    for spec in file_specs:
        field, sep, rest = spec.partition("=")
        if not sep or not rest.startswith("@"):
            raise SystemExit(f"[tcrt-app] --file must look like field=@/path/to/file, got: {spec}")
        file_path = Path(rest[1:]).expanduser()
        if not file_path.is_file():
            raise SystemExit(f"[tcrt-app] --file path not found: {file_path}")
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{file_path.name}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        parts.append(header)
        parts.append(file_path.read_bytes())
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def request(
    method: str,
    path: str,
    data: Optional[dict],
    query: Optional[str],
    files: Optional[list] = None,
) -> None:
    base_url, token = resolve_config()
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base_url}{path}"
    if query:
        url = f"{url}?{query}"

    if files:
        body, content_type = _encode_multipart(files)
    else:
        body = json.dumps(data).encode("utf-8") if data is not None else None
        content_type = "application/json" if body is not None else None
    req = urllib.request.Request(url, data=body, method=method.upper())
    req.add_header("Authorization", f"Bearer {token}")
    if content_type is not None:
        req.add_header("Content-Type", content_type)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SystemExit(f"[tcrt-app] Could not reach {base_url}: {exc.reason}")

    print(f"HTTP {status}", file=sys.stderr)
    try:
        parsed = json.loads(payload) if payload else None
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(payload)

    if status >= 400:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("method", help="HTTP method (GET/POST/PUT/DELETE), or 'check'")
    parser.add_argument("path", nargs="?", default=None, help="Path under /api/app/...")
    parser.add_argument("--data", default=None, help="JSON request body")
    parser.add_argument("--query", default=None, help="Raw query string, e.g. 'limit=20&skip=0'")
    parser.add_argument(
        "--file",
        action="append",
        default=None,
        help="Multipart file field, e.g. files=@/path/to/file (repeatable)",
    )
    args = parser.parse_args()

    if args.method.lower() == "check":
        # GET /api/app/teams only needs test_case:read or test_run:read.
        # A 403 here can mean the token is valid but lacks read scope.
        request("GET", "/api/app/teams", None, None)
        return

    if not args.path:
        parser.error("path is required unless method is 'check'")

    if args.data and args.file:
        parser.error("--data and --file are mutually exclusive")

    data = json.loads(args.data) if args.data else None
    request(args.method, args.path, data, args.query, args.file)


if __name__ == "__main__":
    main()
