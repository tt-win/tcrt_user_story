# Automation Hub — Overview

TCRT's Automation Hub turns the repo into a **single pane of glass** for
automated testing without owning runners, IDEs, or report renderers. It glues
**git** (script storage), **CI** (execution), and **report** (visualisation)
behind one team-scoped UI plus an MCP-friendly read API.

## The mental model

```
 ┌─────────────────────────────────────────────────────────────────┐
 │                    TCRT Automation Hub                          │
 │                                                                  │
 │  Provider Settings  ──►  StorageProvider (GitHub / LocalGit)    │
 │                    ──►  CIProvider     (GH Actions / Jenkins)   │
 │                    ──►  ResultProvider (Allure)                 │
 │                                                                  │
 │  Suites tab  · Runs tab · Coverage tab · Settings tab           │
 │                                                                  │
 │  Test case ↔ Automation script ↔ Run ↔ Report                   │
 └─────────────────────────────────────────────────────────────────┘
```

TCRT itself never executes a Playwright spec. It coordinates external systems
and maintains the M2M link between **manual test cases** (the system of record
for QA intent) and **automation scripts** (the system of record for code).

## End-to-end onboarding (5 minutes once providers are configured)

1. **Generate an encryption key** (one time per deployment):
   ```bash
   python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
   ```
   Put it in `.env` as `AUTOMATION_PROVIDER_ENCRYPTION_KEY=...` OR in
   `config.yaml` under `automation_provider.encryption_key`. Env wins over yaml.

2. **Configure providers** at `/automation-provider-settings`:
   - **Storage** (GitHub or LocalGit) — where the scripts live.
   - **CI** (GitHub Actions or Jenkins) — what runs them.
   - **Result** (Allure) — where reports are served.

3. **Discover scripts**: open `/automation-hub` → Suites tab → click *Rescan*.
   TCRT walks `tests/` (or whatever the provider config's `scan_path` /
   `tcrt-automation.yml` manifest dictates), upserts `automation_scripts` rows,
   and refreshes the file tree. The first time you visit the tab with an empty
   table this is auto-triggered.

4. **Build a suite**: tick files in the left tree → click *+ New Suite* → name
   it. TCRT calls `CIProvider.create_suite_job()` and the workflow / Jenkins
   item is provisioned automatically (suite-level paths injected as inputs).

5. **Link to test cases**: open a test case in `test-case-management`. The
   *Automation* panel (below Attachments) shows linked scripts, link types
   (`PRIMARY` / `COVERS` / `REFERENCES`), latest run status, and direct
   buttons to the CI run and Allure report.

6. **Trigger**: hit the green ▶ on a suite or the *Run* action on a row → fill
   branch / runner / extra inputs → confirm. A `automation_runs` row is
   created with a TCRT correlation id and an `external_run_id` from the
   provider.

7. **Wait for status**: CI calls back via inbound webhook
   (`POST /api/v1/webhooks/ci/{token}/run-status`, HMAC signed) **or** the
   per-team background ticker polls `CIProvider.get_run_status` every 60s
   and pulls the report URL through `ResultProvider.get_run_report_url`.

8. **See coverage**: the Coverage tab shows total cases, PRIMARY / COVERS
   coverage, uncovered cases, stale scripts (no run in 30 days), and a 30-day
   coverage trend SVG.

## Where the AI Helper plugs in

The MCP read API (`/api/mcp/teams/{id}/automation-*`) exposes three endpoints
(`automation-scripts`, `automation-runs`, `automation-coverage`) and a new
`linked_automation_scripts` field on the existing test-case detail endpoint.
This lets the QA AI Helper answer questions like:

- "Which cases in this team aren't yet automated?"
- "Show recent failed runs for the login regression suite."
- "Suggest cases that could be batched into a new Playwright suite."

## Conceptual non-goals

- TCRT does not host runners.
- TCRT does not store script content as the source of truth — git is.
- TCRT does not re-implement Allure / ReportPortal — it links / iframes.
- TCRT does not provide an in-browser IDE — preview is read-only with a
  "edit in your IDE and push to git" hint.

## Related docs

- [Provider setup](./automation-provider-setup.md) — GitHub PAT vs App,
  Jenkins CSRF crumb, Allure deployment patterns.
- [Webhook contract](./automation-webhook.md) — inbound payload schema,
  HMAC signing, outbound event types.
- [Workflow templates](./automation-workflow-templates/) — copy-pasteable CI
  configs that close the loop back to TCRT.
- [Security model](./automation-security.md) — credential encryption,
  permission boundaries.
