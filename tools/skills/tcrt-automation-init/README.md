# tcrt-automation-init

A portable AI-agent **skill** that turns a TCRT **manual test case** into a
**fill-in-the-blank automation skeleton**.

Given a test case (resolved from the **TCRT MCP**), it reads the:

- **precondition** → the *setup* (arrange),
- **steps** → the *actions* (act),
- **expected_result** → the *assertions* (assert),
- **test_data** → fixtures (`DATA` literals + `SECRETS` from env),

…and emits either a browser POM-shaped skeleton or an API-only pytest skeleton
where every blank is a marked `TODO`. You fill in the real selectors, HTTP
requests, and assertions; the structure, the `@pytest.mark.tcrt` traceability
marker, and the TCRT Automation Hub layout are already correct.

Supports pytest API tests with HTTP clients (`httpx` by default; `requests` /
`aiohttp` when requested), Playwright (Python sync + pytest — the browser
default, async), and pytest + Selenium. Python only.

## How it fits with `tcrt-automation-pomify`

They are two halves of one pipeline:

| | init (this skill) | pomify |
|---|---|---|
| Direction | top-down, **from the spec** | bottom-up, **from working code** |
| Input | a test case (precondition/steps/expected) | an existing `.py` script |
| Output | empty-but-structured skeleton | POM-refactored, TCRT-ready script |
| When | you're starting a new test | you already wrote one |

```
test case ──▶ skeleton ──▶ you fill the blanks ──▶ pomify ──▶ push & Rescan
```

## Who this is for

QA / SDETs whose team uses **TCRT** to manage manual test cases and coordinate
automation runs. Point your agent at a TC number and get a correct starting
skeleton instead of a blank file.

## Installation

Copy the entire `tcrt-automation-init/` directory to wherever your agent
loads skills:

| Agent | Location |
|---|---|
| Claude Code (global) | `~/.claude/skills/tcrt-automation-init/` |
| Claude Code (project) | `<repo>/.claude/skills/tcrt-automation-init/` |
| Cursor / Cline / Continue | configure as a custom skill pointing at `SKILL.md` |
| Anything else | `@SKILL.md` (or paste it) before your request |

It needs the **TCRT MCP** server connected for live lookup; without it, paste
the test case content and the skill still works.

## Usage

Prompt your agent with anything like:

- "Create an automation test from `TCG-100558.020.010`."
- "幫我從這個 ticket `ICR-93178.010.010` 搭一個填空骨架。"
- "Create the API test skeleton for this TC; use httpx."
- "I need to write the test for TC-A-001 — give me the skeleton." (Selenium)
- "Create every case in the Login section." (batch)

For a **batch** (more than one case), the agent first asks whether to integrate
them into one test script or emit one script per case.

The agent will:

1. Resolve the test case via the TCRT MCP (precondition / steps / expected /
   test_data).
2. Run the pre-flight checks: **scan the folder for prior progress and offer to
   integrate**, classify API-only vs browser, confirm the framework / HTTP
   client, the comment / pseudo-code language (繁中 / English / match the test
   case), and — for a batch — the layout.
3. Map precondition → arrange, steps → act, expected → assert.
4. Emit `tests/` skeleton + `pages/` stubs + `fixtures/test_data.py` +
   `conftest.py` + manifest, with `@pytest.mark.tcrt` filled from the case
   number.
5. Self-validate, then print a summary + a fill-in checklist + the pomify
   hand-off.

## What's in this bundle

```
tcrt-automation-init/
├── SKILL.md                          # agent instructions (entry point)
├── README.md                         # this file
├── references/
│   ├── mcp-lookup.md                 # which MCP tool, fields, test_data, credentials
│   ├── testcase-to-skeleton.md       # the arrange/act/assert mapping + worked example
│   └── tcrt-format-rules.md          # filename / script_format / marker / manifest (condensed)
└── templates/
    ├── python/
    │   ├── pytest_api/             # API-only pytest + httpx skeleton
    │   ├── playwright_sync_pytest/   # browser default — base, page stub, test_*.py, fixtures
    │   ├── playwright_async/         # base, page stub, flow_*.py
    │   ├── selenium_pytest/          # base, page stub, test_*.py, conftest.py
    │   └── conftest_tcrt_marker.py   # register @pytest.mark.tcrt
    └── manifest/
        └── tcrt-automation.yml       # repo-root manifest
```

### Template filename convention

Templates use `__` (double underscore) as a path separator encoding the
intended output location:

| Template filename | Intended output |
|---|---|
| `pages__base_page.py` | `pages/base_page.py` |
| `pages__example_page.py` | `pages/<surface>_page.py` |
| `tests__api__test_example.py` | `tests/api/test_<title>.py` |
| `tests__ui__test_example.py` | `tests/ui/test_<title>.py` |
| `tests__e2e__flow_example.py` | `tests/e2e/flow_<title>.py` |
| `fixtures__test_data.py` | `fixtures/test_data.py` |

## The fill-in-the-blank contract

The emitted test is **runnable immediately** — it imports cleanly and shows as
`skipped` under pytest (via `@pytest.mark.skip`) until you implement it. Each
step and expected outcome is quoted **verbatim** from the test case as a
comment, with a `# TODO(init):` suggestion below it. Your job:

1. Fill in real locators + action-method bodies in `pages/`.
2. Turn each `# TODO` action/assertion into real code.
3. Export any `credential` env vars (`SECRETS`).
4. Delete the `@pytest.mark.skip` decorator.
5. Run `tcrt-automation-pomify` to validate the POM contract, then push and
   Rescan in TCRT Automation Hub.

## Linking to manual test cases (`@pytest.mark.tcrt`)

Because init resolves the test case number from the MCP, the marker is
**filled in** for you:

```python
# DB value (canonical):    TCG-100558.020.010
# Marker value (dashed):   TCG-100558-020-010
@pytest.mark.tcrt("TCG-100558-020-010", link_type="primary")
def test_login_should_work(page): ...
```

Dotted TC numbers must be **dashed** in the marker (`sync_markers_for_team`
registers the dashed alias automatically). A 1:1 skeleton uses
`link_type="primary"`. Marker sync is the only write path for automation ↔ test
case links — declare coverage in code, not in any UI.

## Security: credentials

The TCRT MCP returns `credential` test-data values in the payload (audit logs
redact them; the payload does not). This skill **never inlines** a credential —
it routes them through environment variables in `fixtures/test_data.py`
(`SECRETS["password"] = os.environ["TC_PASSWORD"]`). Keep secrets out of git.

## Limitations / non-goals

- **Python only.** Supports API pytest skeletons plus the existing
  Playwright/Selenium browser skeletons.
- API-only cases intentionally do **not** use Playwright or Selenium drivers;
  generate `tests/api/test_*.py` with `requests`, `httpx`, or `aiohttp`.
- Does **not** invent selectors, URLs, assertion values, or TC numbers — those
  are `TODO`s for the human.
- Does **not** install dependencies or modify CI config.
- Does **not** execute the test — it produces a skipped skeleton, not a passing
  test.
- For refactoring an **existing** script into POM, use `tcrt-automation-pomify`.

## Versioning

- **v0.3** — auto-fill TCG Admin page routes from menuId:
  - For TCG Admin browser cases, the page object `path` is resolved from the
    TCRT MCP's admin-menu tools (`resolve_admin_menu_entry` /
    `list_admin_menu_entries`) and filled with the menu's `route_path`
    (`/{menuId}`) instead of a `TODO` — but only on a single unambiguous match
    (a menuId, or exactly one menu whose name matches). Ambiguous → keep the
    `TODO` and list candidates. The admin **host** stays env-backed; iframe
    pages also surface `iframe_path`. See `references/mcp-lookup.md` §6.
- **v0.2** — added API-only skeleton generation:
  - API-related cases now generate `tests/api/test_*.py` with pytest plus
    `httpx` by default (`requests` / `aiohttp` when requested), not Playwright
    or Selenium driver code.
  - Browser cases keep the existing Playwright / Selenium POM-shaped skeletons.
- **v0.1** — first cut. POM-shaped skeleton from `precondition` / `steps` /
  `expected_result` / `test_data`; default Playwright sync + pytest; async +
  Selenium template sets; MCP-driven TC resolution; credential-safe fixtures;
  `@pytest.mark.tcrt` auto-filled from the case number.
