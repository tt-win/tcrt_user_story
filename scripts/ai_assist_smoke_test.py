import argparse
import json
import os
import getpass
import sys
from typing import Any, Dict, Optional

import requests
import yaml

DEFAULT_PROMPT = (
    "Precondition: user account exists, test data prepared, network is stable.\n"
    "Steps:\n"
    "1. Open the application\n"
    "2. Navigate to the login page\n"
    "3. Click the Login button\n"
    "4. Enter a valid username and password\n"
    "5. Select All option in the filter\n"
    "6. Go to User Management\n"
    "Expected Result: login succeeds, page loads correctly, data is displayed without errors.\n"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TCRT AI assist smoke test")
    parser.add_argument("--config", default=os.getenv("TCRT_CONFIG", "config.yaml"))
    parser.add_argument("--base-url", default=os.getenv("TCRT_BASE_URL"))
    parser.add_argument("--username", default=os.getenv("TCRT_USERNAME"))
    parser.add_argument("--password", default=os.getenv("TCRT_PASSWORD"))
    parser.add_argument("--team-id", type=int, default=os.getenv("TCRT_TEAM_ID"))
    parser.add_argument("--field", choices=["precondition", "steps", "expected_result"], default="steps")
    parser.add_argument("--prompt", default=os.getenv("TCRT_PROMPT", DEFAULT_PROMPT))
    parser.add_argument("--ui-locale", default=os.getenv("TCRT_UI_LOCALE", "zh-TW"))
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def load_base_url_from_config(config_path: str) -> Optional[str]:
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r", encoding="utf-8") as file:
        config_data = yaml.safe_load(file) or {}
    app_cfg = config_data.get("app") or {}
    base_url = app_cfg.get("base_url")
    if base_url:
        return str(base_url).rstrip("/")
    host = app_cfg.get("host", "127.0.0.1")
    port = app_cfg.get("port", 9999)
    return f"http://{host}:{port}"


def login(base_url: str, username: str, password: str, timeout: int) -> Dict[str, Any]:
    payload = {"username_or_email": username, "password": password}
    response = requests.post(
        f"{base_url}/api/auth/login",
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=timeout,
    )
    if not response.ok:
        detail = None
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text
        raise RuntimeError(f"login failed ({response.status_code}): {detail}")
    return response.json()


def get_accessible_teams(base_url: str, token: str, timeout: int) -> list[int]:
    response = requests.get(
        f"{base_url}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    if not response.ok:
        detail = None
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text
        raise RuntimeError(f"fetch user info failed ({response.status_code}): {detail}")
    data = response.json()
    teams = data.get("accessible_teams") or []
    return [int(team_id) for team_id in teams if str(team_id).isdigit()]


def call_ai_assist(
    base_url: str,
    team_id: int,
    token: str,
    field: str,
    prompt: str,
    ui_locale: str,
    timeout: int,
) -> Dict[str, Any]:
    payload = {
        "field": field,
        "input_text": prompt,
        "ui_locale": ui_locale,
    }
    response = requests.post(
        f"{base_url}/api/teams/{team_id}/testcases/ai-assist",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if not response.ok:
        detail = None
        try:
            detail = response.json()
        except json.JSONDecodeError:
            detail = response.text
        raise RuntimeError(f"ai-assist failed ({response.status_code}): {detail}")
    return response.json()


def main() -> int:
    args = parse_args()
    base_url = args.base_url or load_base_url_from_config(args.config)
    if not base_url:
        print("ERROR: base url is required via --base-url or config app.base_url/host/port")
        return 2
    if not args.username:
        print("ERROR: username required via --username or TCRT_USERNAME")
        return 2
    password = args.password
    if not password:
        try:
            password = getpass.getpass("Password: ")
        except (EOFError, KeyboardInterrupt):
            print("\nERROR: password input cancelled")
            return 2
    if not password:
        print("ERROR: password is required")
        return 2

    try:
        login_data = login(base_url, args.username, password, args.timeout)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 3

    token = login_data.get("access_token")
    if not token:
        print("ERROR: login returned no access_token")
        return 4

    if login_data.get("first_login"):
        print("WARN: account is marked as first_login; token may require setup completion")

    team_id = args.team_id
    if not team_id:
        try:
            teams = get_accessible_teams(base_url, token, args.timeout)
        except Exception as exc:
            print(f"ERROR: {exc}")
            return 5
        if not teams:
            print("ERROR: no accessible teams found; provide --team-id")
            return 5
        team_id = teams[0]

    try:
        result = call_ai_assist(
            base_url=base_url,
            team_id=team_id,
            token=token,
            field=args.field,
            prompt=args.prompt,
            ui_locale=args.ui_locale,
            timeout=args.timeout,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 6

    revised = result.get("revised_text", "")
    suggestions = result.get("suggestions", [])
    print("OK: TCRT AI assist responded")
    print("Base URL:", base_url)
    print("Team ID:", team_id)
    print("Field:", args.field)
    print("Detected language:", result.get("detected_language"))
    print("Revised text:\n" + str(revised).strip())
    print("Suggestions:")
    if isinstance(suggestions, list) and suggestions:
        for idx, item in enumerate(suggestions, start=1):
            print(f"  {idx}. {item}")
    else:
        print("  (none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
