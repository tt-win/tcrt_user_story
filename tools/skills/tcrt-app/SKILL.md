---
name: tcrt-app
description: Call TCRT's team-owned App Token API (/api/app/*) directly over HTTP to read or write test cases, test runs, automation, and team pins. Use curl/sh on Linux/macOS and PowerShell on Windows; Python is only a compatibility fallback.
---

# tcrt-app

Call TCRT's `/api/app/*` App Token API directly over HTTP. This skill uses a
portable POSIX `sh` + `curl` client on Linux/macOS and a built-in PowerShell
client on Windows, so it does not require Python, pip, uv, Node, or a package
installation on any platform.

## Choose a transport

1. For a read-only task with an already-connected `tcrt_mcp` / `tcrt` MCP
   server, use MCP first.
2. For an App Token API operation when POSIX `sh` and `curl` are available
   (Linux, macOS, Git Bash, WSL), use the shell client below.
3. At a Windows **PowerShell prompt** (not `cmd.exe`), use the PowerShell client —
   Windows PowerShell 5.1 ships with Windows 10/11, so nothing needs to be
   installed:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 check
   ```

4. If neither sh+curl nor PowerShell fits but `python3` exists, use the
   compatibility client `python3 scripts/tcrt_api.py ...` with the same
   arguments.
5. If no runtime exists, use the agent host's native HTTP capability. If
   none exists, report the missing transport; do not install a runtime.

## Token setup

This skill never embeds, generates, prints, or accepts a raw token in chat.
Set `TCRT_BASE_URL` and `TCRT_APP_TOKEN` in one env file:

1. Copy `.env.example` to `.env` next to this skill's `SKILL.md`; or
2. Set `TCRT_ENV_FILE` to the env file path; or
3. Export `TCRT_BASE_URL` and `TCRT_APP_TOKEN` in the runtime environment.

Precedence (high → low):
1. Exported environment variables (`TCRT_BASE_URL`, `TCRT_APP_TOKEN`)
2. `TCRT_ENV_FILE` path (points to an alternate env file)
3. `.env` in the skill directory (the default)

The shell client treats the env file as data, not shell code: it only reads the
two exact `KEY=VALUE` keys and never sources or evaluates the file.

`TCRT_BASE_URL` must be an `http://` or `https://` origin only, such as
`https://tcrt.example.com`. Userinfo, query strings, fragments, and non-root
paths are rejected so provenance cannot disclose credentials or join to the
wrong API path.

> **Env reload pitfall**: If `.env` exists in the skill directory, it takes
> precedence even when the user updates `~/.env`. After the user modifies their
> env file, export the variables or set `TCRT_ENV_FILE=/path/to/.env` (or their
> equivalent path) to pick up the new values. Do not modify the skill's own
> `.env` without user direction — use `TCRT_ENV_FILE` instead.

An App Token is issued by a team admin in TCRT Team Management → team → App
Tokens. Keep the real `.env` local and ignored.

## Calling the API

From the skill root, verify setup:

```sh
sh scripts/tcrt_api.sh check
```

Use the same interface for every endpoint:

```sh
sh scripts/tcrt_api.sh <METHOD> <PATH> [--data '<json>'] [--query 'k=v&k2=v2']

# Multipart upload (mutually exclusive with --data); --file is repeatable:
sh scripts/tcrt_api.sh POST <PATH> --file field=@/path/to/file [--file ...]
```

```sh
# Read test cases
sh scripts/tcrt_api.sh GET /api/app/teams/1/test-cases --query 'limit=20'

# Create a test case
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-cases \
  --data '{"test_case_number":"TC-1001","title":"Login smoke test"}'

# Add an unassigned test run (config 12) to test run set 5 after read-back
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-sets/5/members \
  --data '{"config_ids":[12],"expected_memberships":[{"config_id":12,"set_id":null}]}'

# Advance a test run's lifecycle (state machine + start/end dates)
sh scripts/tcrt_api.sh PUT /api/app/teams/1/test-run-configs/5/status \
  --data '{"status":"active"}'

# Upload execution result files for a run item (multipart, test_run:execute)
sh scripts/tcrt_api.sh POST /api/app/teams/1/test-run-configs/5/items/42/upload-results \
  --file files=@./screenshot.png

# Pin a test case set (idempotent)
sh scripts/tcrt_api.sh POST /api/app/teams/1/pins \
  --data '{"entity_type":"test_case_set","entity_id":3}'
```

The response body is written to stdout, `HTTP <status>` to stderr, and every
4xx/5xx or network failure exits nonzero. Non-JSON response bodies are passed
through unchanged.

At a PowerShell prompt, the PowerShell client takes the same logical arguments — replace
`sh scripts/tcrt_api.sh` with
`powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1` in any example
above; it follows the same env-file rules and output contract:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 GET /api/app/teams/1/test-cases --query 'limit=20'
```

The single-quoted JSON examples are PowerShell syntax and are not directly
copyable into `cmd.exe`. The Python compatibility client remains available without changing its
interface:

```sh
python3 scripts/tcrt_api.py check
```

For any real task, open
[`references/api-usage-guide.md`](references/api-usage-guide.md) first — its
task index (§0) routes you to ready-made recipes (Test Case Set creation, batch
case creation/copy/guarded movement, Test Run membership relocation, result
reporting, archive). Look up exact endpoints, scopes,
and body shapes in [`references/api-reference.md`](references/api-reference.md)
only when the recipe doesn't cover your case. Prefer batch endpoints over
looping single-item calls.

## Transparency

When reporting results to the user, always state which `TCRT_BASE_URL` the
data came from. Read it from `check` stderr, which prints
`[tcrt-app] TCRT_BASE_URL=<origin>` before `HTTP <status>`. Never echo a
`TCRT_*` variable: the token must remain out of terminal and chat output.

## Safety

### Archive is not delete

- When the user says **archive / 歸檔**, NEVER call an HTTP `DELETE` endpoint.
- Archive a **Test Run Config** only with `PUT /api/app/teams/{team_id}/test-run-configs/{config_id}/status` and body `{"status":"archived"}`.
- Archive a **Test Run Set** only with `POST /api/app/teams/{team_id}/test-run-sets/{set_id}/archive`.
- Every `DELETE` endpoint permanently removes the target. A Test Run Config delete also removes its run items; a Test Run Set delete removes the set and its runs. Use it only after the user explicitly asks for **permanent deletion / 永久刪除** and confirms the exact target.
- Before any archive or permanent deletion, restate the resource type, ID, correct endpoint, and impact, then obtain explicit confirmation. Never report a `DELETE` as an archive.

### General

- Creates other than pins are generally non-idempotent; after a timeout or 5xx,
  list/lookup before retrying.
- Cross-Set Test Case movement is destructive when it removes out-of-scope Run
  Items. Always use read → impact preview → explicit confirmation when impact is
  nonzero → guarded move with the same fingerprint → read-back. On timeout/5xx,
  placement read-back can establish only final state; report the original
  outcome and cleanup count as unknown and do not blindly resend.
- Read Test Run membership with `include_archived=true`. Use `/members` only
  when every config is confirmed in `unassigned[]`; grouped or mixed batches
  require explicit `/members/batch-move` with expected memberships.
- `credential`-category test data always comes back as `[REDACTED]`; never try
  to obtain the plaintext value through another endpoint.
- A `403 APP_TOKEN_SCOPE_DENIED` means the token needs a new scope from a team
  admin; do not try another endpoint to bypass it.
