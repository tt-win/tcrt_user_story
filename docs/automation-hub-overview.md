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

## Release note: links now come from pytest markers

This is a breaking behavior change for teams that previously created links from
the UI.

- Automation script links are now read-only in TCRT.
- Links come from source-code markers such as `@pytest.mark.tcrt(...)`.
- Historical manual link rows can be audited and cleaned with
  `scripts/cleanup_manual_automation_links.py`.
- If a repo has not adopted markers yet, linked automation may disappear from
  the UI until the next marker-based sync is in place.

## End-to-end onboarding (5 minutes once providers are configured)

1. **Generate an encryption key** (one time per deployment):
   ```bash
   python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
   ```
   Put it in `.env` as `AUTOMATION_PROVIDER_ENCRYPTION_KEY=...` OR in
   `config.yaml` under `automation_provider.encryption_key`. Env wins over yaml.

2. **Configure providers** at `/automation-provider-settings`:
   - **Storage** (GitHub or LocalGit) — where the scripts live.
   - **CI** (Jenkins) — what runs them.
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
   (`PRIMARY` / `COVERS` / `REFERENCES`), and link source badges. Links are
   read-only in the UI and come from source-code markers; run history now
   lives in the Test Run Set detail page.

6. **Trigger (via Test Run Set)**: the Automation Hub no longer exposes a
   direct *Run Suite* / *Run Script* button. To execute a suite, bundle it
   into a [Test Run Set](./user_manual.md#test-run-sets) (the
   *Automation Suites* section on the set detail page) and click
   *Run as Automation*. TCRT walks every linked suite in order, calls
   `CIProvider.trigger_run` per suite, and creates one `automation_runs`
   row per suite with a TCRT correlation id and the provider's
   `external_run_id`. The historical public endpoints
   `POST /automation-scripts/{id}/runs` and
   `POST /automation-script-groups/{id}/runs` have been retired; the
   inbound webhook `/api/v1/webhooks/ci/{token}/trigger` still works for
   automation bound to a webhook suite binding (see
   [add-webhook-suite-trigger](../openspec/changes/add-webhook-suite-trigger/)).

7. **Wait for status**: CI calls back via inbound webhook
   (`POST /api/v1/webhooks/ci/{token}/run-status`, HMAC signed) **or** the
   per-team background ticker polls `CIProvider.get_run_status` every 60s
   and pulls the report URL through `ResultProvider.get_run_report_url`.
   The run itself (status, cancel, reconcile, report embed) is surfaced
   from the Test Run Set detail page — the Hub no longer has a Runs tab
   (see `move-run-history-to-test-run-set`).

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
