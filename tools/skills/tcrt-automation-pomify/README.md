# tcrt-automation-pomify

A portable AI-agent **skill** that refactors any messy Python automation
script (or folder), normalizes Python API tests, or converts Postman
collections into:

1. **Page Object Model** structure for browser scripts, or pytest API tests for
   API/Postman inputs
2. **TCRT Automation Hub** filename / directory conventions so smart-scan
   auto-discovers it

Works with Playwright (Python async / sync + pytest), pytest + Selenium,
pytest API tests (`requests` / `httpx` / `aiohttp`), and Postman collection
JSON -> pytest API conversion. TypeScript / JavaScript support was removed in
v0.2.

## Who this is for

QA / SDETs whose team uses **TCRT** to coordinate automation runs, but who
write the actual scripts in their own IDE / repo. Drop this skill into your
agent of choice and ask it to "pomify this file" — output is immediately
runnable AND immediately TCRT-scannable.

## Installation

Copy the entire `tcrt-automation-pomify/` directory to wherever your AI agent
loads skills:

| Agent | Location |
|---|---|
| Claude Code (project-scoped) | `<your-repo>/.claude/skills/tcrt-automation-pomify/` |
| Claude Code (global) | `~/.claude/skills/tcrt-automation-pomify/` |
| Cursor | drop into `.cursor/rules/` and reference SKILL.md from `cursor.json` |
| Cline / Continue / Roo | configure as a "custom skill" or "system prompt include" pointing at SKILL.md |
| Anything else (raw markdown) | tell the agent to `@SKILL.md` (or paste it) before your refactor request |

The skill is just markdown + template files — no install step, no runtime
dependencies on the agent side.

## Usage

Once installed, prompt your agent with anything like:

- "Pomify `tests/messy_login.py` for TCRT."
- "Refactor the `legacy-e2e/` folder into POM and TCRT format."
- "Scan this folder for Postman collections and convert them to TCRT API tests."
- "Convert this Playwright script to use page objects and put it where TCRT
  smart-scan can find it." (paste the script)

The agent will:

1. Detect framework or Postman collection shape.
2. Extract selectors and actions per page for browser scripts, or requests and
   assertions for API/Postman inputs.
3. Emit `pages/` with one Page Object per page (with `__init__.py` so
   `from pages.x import ...` resolves), named to TCRT conventions.
4. Emit `tests/<api|ui|e2e>/` with the rewritten test files using your page
   objects for browser tests, or HTTP client tests for API/Postman inputs,
   named so TCRT smart-scan classifies them correctly.
5. Optionally generate a `tcrt-automation.yml` manifest.
6. Self-validate the output (Step 11) before declaring done.
7. Print a summary table mapping source → target → detected framework →
   TCRT `script_format`.

## What "TCRT format" means (the 30-second version)

TCRT scans your repo's `tests/` directory and only picks up files whose
filenames match these globs (NOT regexes):

```
test_*.py        → PYTEST
*_test.py        → PYTEST
flow_*.py (etc., if added to scan.include) → PLAYWRIGHT_PY_ASYNC
```

Files under directories named `pages/`, `flows/`, `fixtures/`, `utils/` etc.
are auto-excluded — so Page Objects belong there. See
`references/tcrt-format-rules.md` for the full contract.

## What's in this bundle

```
tcrt-automation-pomify/
├── SKILL.md                        # Main agent instructions (entry point)
├── README.md                       # This file (human-readable overview)
├── references/
│   ├── tcrt-format-rules.md        # Smart-scan globs, exclusion list, manifest schema
│   ├── pom-conventions.md          # Python POM/API contract
│   ├── framework-detection.md      # How to disambiguate frameworks
│   └── postman-collection.md       # Postman JSON -> pytest API conversion
└── templates/
    ├── python/
    │   ├── pytest_api/              # Postman/API pytest -> PYTEST
    │   ├── playwright_async/        # PLAYWRIGHT_PY_ASYNC
    │   ├── playwright_sync_pytest/  # PYTEST
    │   ├── selenium_pytest/         # PYTEST
    │   └── conftest_tcrt_marker.py  # register @pytest.mark.tcrt
    └── manifest/
        └── tcrt-automation.yml      # Optional repo-root manifest
```

### Template filename convention

Templates use `__` (double underscore) as a path separator so each file
encodes its **intended output location**:

| Template filename | Intended output |
|---|---|
| `pages__login_page.py` | `pages/login_page.py` |
| `pages__base_page.py` | `pages/base_page.py` |
| `tests__api__test_postman_collection.py` | `tests/api/test_<collection>.py` |
| `tests__ui__test_login.py` | `tests/ui/test_login.py` |
| `tests__e2e__flow_login.py` | `tests/e2e/flow_login.py` |

When the agent emits files, it converts `__` back to `/` and replaces
`login` / `LoginPage` / `flow_login` with names derived from the user's
input.

### Template placeholders

Generated files contain `{{PLACEHOLDER}}` tokens that the agent must
substitute before writing:

| Placeholder | Replace with |
|---|---|
| `{{SOURCE_PATH}}` | original file path (or `"pasted"` if no path) |
| `{{TIMESTAMP_UTC}}` | current time in ISO-8601 (`2026-06-03T08:42:11Z`) |
| `{{TEST_NAME}}` | the new test filename stem (e.g. `test_login`) |
| `{{FLOW_NAME}}` | the new flow filename stem (e.g. `flow_login`) |
| `{{PAGE_NAME}}` | the new page class file stem (e.g. `login_page`) |
| `{{COLLECTION_NAME}}` | Postman collection display name |
| `{{BASE_URL}}` | safe API base URL default, or an env-var placeholder |
| `{{DEFAULT_HEADERS}}` | generated Python dict for non-secret default headers |
| `{{TEST_FUNCTIONS}}` | generated pytest functions, one per Postman request |
| `{{TC_ID_*}}` | manual test case IDs (e.g. `{{TC_ID_HAPPY_PATH}}` → `TC-LOGIN-01`) |

If a TC ID is unknown, leave it as `TC-???` and add a `TODO:` comment
above. Do NOT invent IDs.

## Verifying output

After the skill runs, `cd` into the reported output folder
(`tcrt-pomified-<name>/`) and sanity-check by:

1. Open `tests/` — every file must match `test_*.py` or `*_test.py`.
2. Open `pages/` — page object classes only, no test functions, no assertions.
3. For browser output, confirm `pages/__init__.py` exists so imports resolve.
4. Run `pytest -q tests/` — pytest should discover the same tests TCRT will.
5. In TCRT Automation Hub → Suites tab → **Rescan** → confirm each file
   shows the expected `script_format`.

The skill runs a mechanical self-validation in Step 11 before printing the
summary, which catches most of the above automatically.

## Linking automation tests to manual test cases

TCRT can automatically maintain **per-test linkage** between your automation
functions and manual test cases in the test management system. You declare the
relationship directly in the test code; TCRT syncs it on every scan.

> **Marker sync is the only write path.** As of
> `openspec/changes/remove-manual-automation-link-ui-and-write-api/`, the
> manual `POST /automation-scripts/{id}/links` /
> `POST .../links/batch` / `PATCH .../links/{id}` / `DELETE .../links/{id}`
> write endpoints and the Automation Hub "Manage links" modals are being
> removed. Marker sync is the single write path for
> `automation_script_case_links`.

### How it works

| Step | What happens |
|---|---|
| You annotate a test | Add `@pytest.mark.tcrt("TC-001")` |
| TCRT scans the repo | smart-scan extracts `TestEntry` records per function |
| Derived links created | `automation_script_case_links` records appear with `created_by = "marker-sync"` and `note = {"test_name", "line", "marker_raw"}` JSON |
| You remove a marker | Orphan marker-sync links are cleaned up on next scan (audit-logged as `reason: "marker_removed"`) |
| You change `link_type` | The derived link is updated to match |

### TC IDs that contain dots

TCRT's `TestCase.test_case_number` column commonly uses dotted values
(`TCG-100558.020.010`). Marker grammar does **not** allow dots
(`[A-Za-z0-9_-]+`), so the dashed form must be used in markers:

```python
# DB value (canonical):    TCG-100558.020.010
# Marker value (dashed):   TCG-100558-020-010
@pytest.mark.tcrt("TCG-100558-020-010", link_type="primary")
def test_critical_path(page): ...
```

`sync_markers_for_team` auto-registers a dash-normalized alias for every
dotted case number, so the dashed form resolves. Using the **dotted** form
in a marker silently fails to resolve (emits `unknown_tc`).

### Practical rules

1. **Prefer `link_type="primary"`** when the test was written to cover exactly
   one manual test case end-to-end. Use `"covers"` (the default) for partial
   coverage and `"references"` for supporting/regression context.
2. **Use real TC IDs only** — the skill will not invent IDs. If you don't know
   the TC ID yet, use the `TODO:` skeleton in the generated file.
3. **Register the marker in `conftest.py`** to avoid `PytestUnknownMarkWarning`.
   Copy or merge `templates/python/conftest_tcrt_marker.py`.

## Limitations / non-goals

- The skill is **Python-only** (v0.2+). TypeScript and JavaScript are out of
  scope.
- The skill does **not** install dependencies (`pip install httpx`,
  `playwright install`, `pip install pytest-playwright selenium`). It assumes
  the user manages their own dev environment.
- The skill does **not** modify your CI config (`.github/workflows/`,
  `Jenkinsfile`). Suite-level CI jobs are auto-generated by TCRT itself
  when you create a suite in the Hub UI.
- The skill does **not** convert pure unit tests to POM. API tests and Postman
  collections are converted / normalized as TCRT pytest API tests, without page
  objects.
- The skill does **not** preserve git blame on rewritten files. Commit the
  refactor as a separate PR if blame matters.

## Versioning

- **v0.5** — normalize TCG Admin routes via menuId:
  - When an extracted route is a TCG Admin page (a menuId-style route or admin
    host URL), the skill resolves it via the TCRT MCP admin-menu tools
    (`resolve_admin_menu_entry` / `list_admin_menu_entries`), sets the page
    object `path` to the menu's `route_path` on an unambiguous match, moves the
    env-specific host into `base_url` / Playwright `baseURL`, and annotates the
    class with the menu breadcrumb. Ambiguous / not-found → keep the source
    route and add a `TODO(pomify)`. iframe pages also surface `iframe_path`.
    See `references/pom-conventions.md`.
- **v0.4** — added API/TestRail-aligned input paths:
  - API-only pytest files can be normalized into `tests/api/test_*.py` without
    generating Page Objects.
  - Postman collection JSON can be scanned from a file or folder and converted
    to TCRT-standard pytest API tests using `httpx` by default.
- **v0.3** — aligned with the in-flight TCRT changes:
  - Marker sync is the **only** write path for `automation_script_case_links`
    (per `remove-manual-automation-link-ui-and-write-api`). Removed the
    "human link wins" conflict-resolution section; added a §5.2 callout
    pointing at the OpenSpec change.
  - Added §5.1.1: TC ids with dots (`TCG-100558.020.010`) must be dashed
    in markers (`TCG-100558-020-010`) — `sync_markers_for_team` registers
    a dashed alias automatically.
  - Added §5.1.2: marker note JSON schema
    (`{"test_name", "line", "marker_raw"}`).
  - Replaced stale / missing warning keys in §5.3: `unknown_tc`,
    `invalid_tc_format` (not `invalid_tc_id_format`),
    `non_literal_marker` (not `non_literal_argument`),
    `link_type_conflict`, `unknown_marker_kwarg`.
- **v0.2** — removed TypeScript and JavaScript support; fixed Playwright
  Python `to_have_url` lambda bug; added `__init__.py` generation note;
  added Step 10 self-validation; templated source/timestamp/TC-ID placeholders.
- **v0.1** — first cut, covered 6 framework/language combinations.
