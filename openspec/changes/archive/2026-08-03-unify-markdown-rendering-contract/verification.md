# Markdown rendering verification evidence

Date: 2026-08-03  
Change: `unify-markdown-rendering-contract`

This record is behavior evidence for the checked-in implementation. Source-text assertions are not used as a substitute for parser, Safe Display, or browser behavior checks.

## Focused command matrix

| Command | Observed result |
| --- | --- |
| `uv run pytest app/testsuite/test_qa_ai_helper_markdown.py -q` | 7 passed |
| `uv run pytest app/testsuite/test_qa_ai_helper_preclean.py -q` | 8 passed |
| `uv run pytest app/testsuite/test_qa_ai_helper_api.py -q` | 35 passed |
| `uv run pytest app/testsuite/test_component_spec.py -q` | 419 passed, 4 skipped |
| `node --test app/testsuite/js/markdown-renderer.test.mjs` | 11 passed; checks the 652-example CommonMark corpus, pinned asset/corpus hashes, GFM matrix, Safe Display, URL/task provenance, fallback/readiness, and browser-backed adapter behavior |
| `node --test app/testsuite/js/test-case-list-interactions.test.mjs` | 11 passed, including the generated task-checkbox regression |
| `node --test app/testsuite/js/assistant-widget.test.mjs` | 58 passed |
| `npm run lint` | Exit 0; existing stylelint baseline warnings only (652 warnings, 0 errors); template inline-style guard passed |
| `openspec validate unify-markdown-rendering-contract --strict` | Valid |
| `openspec archive unify-markdown-rendering-contract --yes` | Created `openspec/specs/markdown-rendering/spec.md` and archived the change |
| `openspec validate markdown-rendering --strict` | Valid |

The pytest suites emit existing dependency deprecation warnings; they do not fail the focused commands.

## Browser smoke invocation and observations

Driver: Oh My Pi Chromium browser device (`xd://browser`, `action:"open"` then `action:"run"`) against the locally running `markdown-browser-smoke` server at `http://127.0.0.1:11991`.

1. A run-scoped request interceptor blocked `cdn.jsdelivr.net/npm/marked` and `cdn.jsdelivr.net/npm/dompurify`, then loaded:
   - `/test-case-management?set_id=1&team_id=1`
   - `/test-run-execution?config_id=1&team_id=1`
   - `/qa-ai-helper?team_id=1`

   No blocked legacy parser/sanitizer request occurred. Each page exposed `window.TCRTMarkdown`, settled `ready` as `{status:"ok"}`, and had `window.commonmark`, `window.marked`, and `window.DOMPurify` undefined.

2. Test Case Management opened an editable preview and supplied source containing raw `<script>`, a checked GFM task item, a GFM table, and an external link. The textarea retained exact source; the preview had no script node, showed raw HTML literally, created a table, and emitted a checked disabled task input with no `name`, `value`, or `form`. Calling `focus()` did not focus that checkbox. The external link normalized to `https://example.com/` with exactly `target="_blank" rel="noopener noreferrer"`.

3. Test Run Execution opened the actual test-case detail modal. Its three independent Markdown previews each reported `data-markdown-status="ok"`; raw script was absent, the task control was disabled without form attributes, the table rendered, and the external-link attributes matched the canonical policy.

4. QA AI Helper used an intercepted ticket-session response carrying the same source. Its ticket preview had no script node, rendered literal raw HTML/table/task/link safely, and its separate editor textarea retained exact raw Markdown while preview was hidden in edit mode.

5. Global Assistant Widget used intercepted list/create/messages endpoints and rendered an assistant history message carrying the same source. The request sequence was `list`, `create`, `messages`; the bubble retained its source revision, had no script node, rendered the table, created a disabled non-focusable task control without form attributes, and normalized the external link with the canonical target/rel.

The adapter-focused Node suite additionally exercises pending-to-ready retry, unavailable assets, parser/sanitizer initialization failures, and fail-closed escaped fallback behavior in a controlled browser harness.
