# tcrt-app

A portable AI-agent **skill** that calls TCRT's team-owned **App Token API**
(`/api/app/*`) directly over HTTP — no MCP server required.

`/api/app/*` is TCRT's external API surface for reading and writing test
cases, test runs, test run sets/items, team-scoped pins, and triggering Test
Run Set automation from outside the TCRT web UI. It's the same API `tcrt_mcp`
is migrating its tools onto; this skill exposes it as a small,
dependency-free script for any agent or tool that doesn't go through an MCP
server.

See [`SKILL.md`](SKILL.md) for the full usage guide,
[`references/api-reference.md`](references/api-reference.md) for the endpoint
list, scopes, and error codes, and
[`references/api-usage-guide.md`](references/api-usage-guide.md) for an
end-to-end AI-agent reference walkthrough.

## Setup

1. Get a raw app token from a TCRT team admin (Team Management → enter a team
   → "App Tokens" → Create). The raw token is only shown once at creation.
2. Copy `.env.example` to `.env` in this directory and fill in both
   `TCRT_BASE_URL` and `TCRT_APP_TOKEN` — or set
   `TCRT_ENV_FILE=/absolute/path/to/your/.env` if you'd rather keep the file
   somewhere else. A real exported `TCRT_BASE_URL` / `TCRT_APP_TOKEN`
   environment variable always overrides the file.
3. Verify — pick the client for your platform (same arguments everywhere):
   - Linux / macOS: `sh scripts/tcrt_api.sh check`
   - Windows: `powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 check`
   - Python fallback: `python3 scripts/tcrt_api.py check`

This whole `tools/` directory is already gitignored in the TCRT repo, so a
real `.env` here is safe from accidental commits. If you copy this skill
folder into another repo, make sure that repo's `.gitignore` also excludes
`.env` before you drop a real token in.

This skill does **not** create, list, rotate, or revoke app tokens — that
management API requires a human JWT session and is only reachable from the
TCRT web UI. This skill only consumes a token that already exists.

## Relationship to `tcrt_mcp` and `tcrt-automation-*`

| | `tcrt_mcp` (MCP server) | `tcrt-app` (this skill) | `tcrt-automation-init` / `-pomify` |
| --- | --- | --- | --- |
| Transport | MCP (stdio/HTTP) | Raw HTTP via curl / PowerShell / `urllib` | MCP, for test-case lookup only |
| Auth | Injected by the MCP wrapper, no user setup | User-supplied `.env` file | Same as `tcrt_mcp` |
| Scope | Read-only today, migrating to `/api/app/*` | Full `/api/app/*` surface (read + write) | Generates automation script skeletons/refactors |
| Use when | An MCP server is already connected | No MCP server, or you need a write `tcrt_mcp` doesn't expose yet | Turning a test case into (or tidying) an automation script |
