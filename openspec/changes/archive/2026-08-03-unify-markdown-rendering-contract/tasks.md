# Markdown Rendering Contract Implementation Tasks

本清單描述 checked-in implementation 與後續 verification/governance。Adapter/assets、corpus fixtures/tests 與部分 surface runtime work 已存在，但它們不等於所有 acceptance 已通過；checkbox 只在對應的可觀察證據直接成立時才可勾選。所有 surface SHALL preserve source Markdown and SHALL use only `window.TCRTMarkdown` display output。本 change 不包含 database/schema/migration。

## 0. Contract fixtures and implementation prerequisites

- [x] **0.1 Freeze canonical dependency and corpus metadata.** Record local `commonmark@0.31.2` (BSD-2-Clause, source URL, local ESM wrapper SHA-256 `13613ebd2867bd06994c26cce1089e91b561ff5810ca4da22e51034a4210292f`) and `DOMPurify@3.4.12` (source URL, local SHA-256 `b51207de097d14ff9af93bb923d1a245d196a474cbbfdcfeda5e2166734715e1`, license) in `app/static/vendor/MANIFEST.md`; check in `app/testsuite/fixtures/markdown/commonmark-0.31.2.json` with 652 examples and SHA-256 `7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c`; add the GFM 0.29 four-feature matrix and URL/raw-HTML/task vectors. **Acceptance:** deterministic fixture/hash checks fail on changed assets/corpus and the corpus contains no silently skipped example.
- [x] **0.2 Add test seams before surface migration.** Define a browser/Node fixture that can supply local ESM assets, a controlled `document.baseURI`/page origin, blocked CDN requests, pending readiness, unavailable readiness and successful recovery. **Acceptance:** tests can observe DOM/result behavior and source revision races without source-text-only assertions.
- [x] **0.3 Lock the inventory.** Walk every row in `inventory.md`, map it to an implementation owner/file and a focused behavior test. **Acceptance:** no parser, renderer, sanitizer, asset, toolbar, Jira converter, direct Markdown sink or dependent classic script is unassigned; task checkboxes remain unchanged until runtime evidence exists.

## 1. Canonical adapter and self-hosted assets

- [x] **1.1 Implement `/static/js/common/markdown-renderer.js`.** Expose only `window.TCRTMarkdown.render(source,{surface})` and non-rejecting `window.TCRTMarkdown.ready`; normalize source; use private `new commonmark.Parser().parse(source)` plus `HtmlRenderer({safe:false, softbreak:'\n'})` semantics, the four GFM AST extensions and `ast-node-type` raw provenance. **Acceptance:** valid result shape, safe `html` string, surface is diagnostic only, no `window.commonmark`, `window.marked`, `window.DOMPurify`, `setOptions` or page option override.
- [x] **1.2 Implement adapter initialization/fallback.** Load local assets, distinguish `renderer-pending`, `asset-unavailable`, `parser-unavailable`, `sanitizer-unavailable` and `renderer-error`, and return escaped `<pre>` source for every fallback. **Acceptance:** `ready` always resolves; malformed input accepted by parser is `status:'ok'`; no fallback includes parser HTML, raw source attributes or unclean HTML.
- [x] **1.3 Implement deterministic AST raw-HTML provenance policy.** Classify `html_block`/`html_inline` nodes as `source-raw-html`, escape each complete source literal before DOMPurify, and ensure generated nodes/attributes cannot inherit source attributes. **Acceptance:** raw allowlisted tags, scripts, SVG/MathML, event/style/data attributes and raw inputs remain literal/non-executable DOM text; parser-conformance tests may inspect raw HTML separately but browser display never reparses it.
- [x] **1.4 Implement Safe Display Profile.** Configure explicit generated tag/attribute allowlists, `ALLOW_DATA_ATTR:false`, no style/URI relaxation, no heading IDs or code classes, and one sanitizer/URL hook. **Acceptance:** all surfaces receive identical tags/attrs; no local sanitizer or post-adapter source interpolation is needed; DOM probes show no event/style/data/custom-element capability.
- [x] **1.5 Implement readiness retry contract in shared helpers or documented caller API.** Retain unchanged source and current node/revision, retry only after successful readiness, and prevent stale asynchronous retry from replacing newer content. **Acceptance:** pending→ready, unavailable, edit-before-ready and detached-node scenarios have observable outcomes.
- [x] **1.6 Pin and load assets locally.** Ensure adapter imports only application-origin vendor assets; remove parser/sanitizer CDN tags and stale asset-policy allowlist entries; load adapter before `assistant-widget.js` and every dependent classic page script. **Acceptance:** offline/browser network evidence proves no CDN parser/sanitizer request and manifest/hash/license checks pass.

## 2. Parser conformance and semantic behavior

- [x] **2.1 Execute CommonMark 0.31.2 official corpus.** Run all 652 examples from `app/testsuite/fixtures/markdown/commonmark-0.31.2.json` using `new commonmark.Parser()` and the parser-conformance AST renderer before Safe Display. **Acceptance:** fixture hash `7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c` is checked, no examples are skipped, expected HTML/AST semantics match, and sanitizer assertions are not used as conformance proof.
- [x] **2.2 Execute the GFM 0.29 matrix.** Cover tables, task list items, strikethrough and autolink literals with positive, nested, boundary and malformed-looking cases. **Acceptance:** each declared feature has output and each unlisted extension (footnotes, emoji, math, heading anchors, underline) has a literal/unsupported expectation.
- [x] **2.3 Prove line-break and heading semantics.** Test ordinary LF as soft break under `softbreak:'\n'`, standard hard-break syntax as `<br>`, no heading IDs/anchors and no code-language classes. **Acceptance:** output demonstrates the distinction in actual parser/DOM behavior.
- [x] **2.4 Prove malformed versus unavailable behavior.** Exercise unclosed delimiters/brackets/fences that parser accepts and actual parser/module exceptions. **Acceptance:** accepted malformed-looking source returns `ok` canonical literal semantics; unavailable/exception paths return exact fallback reason and escaped plaintext.

## 3. URL, task, and Safe Display verification

- [x] **3.1 Implement URL normalization/origin policy.** Reject empty/control/backslash/protocol-relative and explicit unsafe schemes; treat percent-encoded scheme-looking text as an encoded relative literal; normalize HTTP(S) with `URL.href`; distinguish same-origin from external; allow only safe `mailto` addr-spec and relative/HTTPS images. **Acceptance:** vectors cover case/whitespace/control/backslash, `//host`, encoded schemes, credentials, malformed URL, relative query/fragment, same-origin and external target/rel, mailto and image behavior.
- [x] **3.2 Implement and verify generated external-link attributes.** Source cannot set `target`/`rel`; only cross-origin HTTP(S) gets exactly `_blank` and `noopener noreferrer`, while same-origin/relative/mailto has no target/rel. **Acceptance:** DOM attributes are deterministic and source `target`, `rel`, `onclick` and equivalent raw HTML never control them.
- [x] **3.3 Implement task checkbox provenance.** Emit checkbox only from a GFM AST task list-item node with task metadata; derive checked only from `[ ]`, `[x]`, `[X]`; emit generated `type="checkbox"`, optional `checked`, `disabled` and no other attrs. **Acceptance:** raw `<input>`/checkbox-like text cannot forge a node; checkboxes are disabled/non-focusable/non-submittable and source is unchanged.
- [x] **3.4 Run independent Safe Display/XSS suite.** Cover raw HTML, event handlers, style/data attrs, dangerous links/images, external target/rel, task controls, parser output and DOM insertion. **Acceptance:** tests inspect actual sanitized HTML/DOM and prove no executable or unclean source-derived markup; they do not merely assert parser output.

## 4. Test Case Management migration (after 1–3)

- [x] **4.1 Migrate `app/static/js/test-case-management/markdown.js`.** Remove regex renderers and local parser behavior; use adapter for each preview and status/fallback retry; retain source in textarea/transient retry state only. **Acceptance:** precondition/steps/expected-result previews, empty state, API/AI/bulk content and recovery use adapter HTML only.
- [x] **4.2 Migrate modal/bulk/clone paths.** Update `modal.js`, `bulk.js`, `bulk-edit.js`, `init.js` and AI-assist preview calls so no Markdown value is interpolated into generated HTML. **Acceptance:** clone/bulk create/edit/reopen/AI preview behavior preserves exact source and displays safe output.
- [x] **4.3 Migrate TCM toolbar and hotkeys.** Keep B/I and canonical controls; remove `<u>` insertion and `Ctrl/Cmd+U` interception; do not add raw HTML controls. **Acceptance:** keyboard and toolbar behavior is observed in DOM/textarea tests and U does not prevent default or mutate source.
- [x] **4.4 Load adapter before TCM scripts and update template contract.** Add adapter script order to `test_case_management.html`/base sequence and remove any page parser dependency. **Acceptance:** page executes with parser globals absent and adapter available before callers.

## 5. Test Run Execution migration (after TCM)

- [x] **5.1 Migrate `app/static/js/test-run-execution/utils.js`.** Remove historical `marked.parse`/local fallback and use the shared result/readiness contract, including source/revision-safe retries. **Acceptance:** utility output is adapter output or escaped fallback with exact status/reason; no parser global is read.
- [x] **5.2 Migrate fields/detail generation in `render.js`.** Update `generateScrollableContentHtml`, `createTestCaseDetailHtml`, `displayTestCaseDetail` so precondition/steps/expected result are separate safe adapter containers, never raw interpolated HTML. **Acceptance:** actual detail modal handles all three fields, fallback and recovery without source-as-HTML injection.
- [x] **5.3 Migrate comments in `tickets.js`.** Remove local `marked.parse`/DOMPurify allowlist; render comment source with adapter, preserve `data-original-markdown`/edit source safely, and status fallback. **Acceptance:** load/edit/save/cancel and XSS/URL behavior pass with source round trip.
- [x] **5.4 Migrate Test Run toolbar/hotkeys and template order.** Remove page marked options and underline handler; delete page CDN parser/sanitizer tags; load adapter before `core.js`, `utils.js`, `render.js`, `tickets.js`. **Acceptance:** tests run with parser globals absent; line-break/hotkey behavior is canonical and page is offline/self-hosted.

## 6. QA AI Helper and Jira source boundary (after Test Run)

- [x] **6.1 Keep backend Jira conversion source-only.** Audit `_jira_wiki_inline_to_md`, `_jira_wiki_to_markdown`, `_markdown_to_jira_wiki`, `_build_ticket_markdown`, preclean and reload/reparse APIs. **Acceptance:** conversion returns source or explicit conversion result/error, never HTML/browser parser output; unknown tokens preserve safe literal or fail explicitly.
- [x] **6.2 Migrate `app/static/js/qa-ai-helper/main.js`.** Remove browser Jira Wiki conversion and historical parser path; render backend canonical source via adapter `surface:'qa-ai-helper'`; preserve `raw_ticket_markdown` source and readiness retry. **Acceptance:** ticket fetch/reparse/AI preview/editor display safe output and exact source; fallback status is localized/a11y-visible.
- [x] **6.3 Update `app/templates/qa_ai_helper.html`.** Remove page CDN marked tag, load adapter before `main.js`, preserve editor/preview separation and status node. **Acceptance:** offline page has no parser globals/CDN dependency and browser DOM behavior passes.
- [x] **6.4 Verify Jira API/source tests.** Exercise external ticket fetch/reload, user reparse, unknown Jira tokens, Markdown-like ticket content, and outbound Jira issue description assembly separately from browser display. **Acceptance:** source hashes/equality and deterministic conversion outputs pass; no rendered HTML is persisted or sent to backend conversion.

## 7. Global Assistant Widget migration (after QA)

- [x] **7.1 Remove lazy CDN parser/sanitizer loader.** Delete `MARKED_URL`, `DOMPURIFY_URL`, `loadScript`, `ensureMarkdownLibs`, global hooks and any page-specific options; rely on preloaded local adapter. **Acceptance:** assistant works with parser globals absent and blocked CDN; no fallback path dynamically fetches third-party assets.
- [x] **7.2 Migrate all assistant display flows.** Route initial messages, SSE/stream chunks, history, retries, tool results and external content through adapter `surface:'assistant'`; insert only returned `html`. **Acceptance:** actual widget DOM never displays raw HTML; source/revision guard prevents stale readiness retries; fallback and recovery are observable.
- [x] **7.3 Preserve post-render presentation safely.** Keep code-copy/table decoration only as DOM operations over already-safe adapter nodes; do not rebuild content from source or `innerHTML` with untrusted values. **Acceptance:** code copy, tables, streaming and accessibility behavior remain intact under Safe Display output.
- [x] **7.4 Verify global ordering/base template.** Ensure adapter script is before `assistant-widget.js` and all dependent page scripts. **Acceptance:** base page executes offline and no global parser state is created.

## 8. i18n, accessibility, and browser proof

- [x] **8.1 Add/update three locale dictionaries.** Add unavailable/status/task labels in `en-US.json`, `zh-CN.json`, `zh-TW.json`; use existing i18n lifecycle and no user-visible hard-coded reason/source. **Acceptance:** all keys exist and status text changes correctly on locale switch.
- [x] **8.2 Implement accessible fallback/status behavior.** Add `role="status" aria-live="polite"`, readable non-focusable `<pre>` fallback, disabled/non-submittable task checkboxes, and safe focus order for toolbar/editor/preview. **Acceptance:** browser accessibility tree and keyboard behavior prove no raw source announcement as executable/interactable content.
- [x] **8.3 Add adapter-focused Node/browser tests.** Add `app/testsuite/js/markdown-renderer.test.mjs` (or repository-equivalent) for result/readiness, corpus fixture loading, GFM, raw HTML, URL, task, safe display and failure cases. **Acceptance:** tests observe behavior, run deterministically and can fail on a plausible contract regression.
- [x] **8.4 Run browser/asset smoke.** Use an existing browser driver/manual harness or add a deterministic fixture; block CDN assets, exercise at least one page per migration surface, observe DOM output, statuses, source recovery and external link attrs. **Acceptance:** exact command/invocation and evidence are recorded in [`verification.md`](verification.md); Node VM/source assertions alone are not accepted.

## 9. Legacy deletion and governance closeout (last)

- [x] **9.1 Prove no legacy callsite remains.** After all surface tests pass, remove regex renderers, local parser/sanitizer imports, page `setOptions`, global parser references, old CDN tags and aliases/shims. **Acceptance:** runtime behavior tests still pass with parser globals undefined and asset network blocked; `inventory.md` rows have evidence.
- [x] **9.2 Run the focused verification matrix.** Use the actual commands below and the browser command recorded in 8.4; do not replace behavior tests with source-text checks. **Acceptance:** all focused layers and every surface integration pass, with no missing/hidden failure.
- [x] **9.3 Update main spec/archive only after evidence.** Cross-check every requirement/scenario against artifacts and test evidence; only then update `openspec/specs/` and archive this change. **Acceptance:** the verified primary spec was created and this change was archived after the evidence recorded in [`verification.md`](verification.md).

## Focused harness commands

These commands are the implementation/verification contract; command output must be recorded before any task checkbox or final conformance claim changes:

```bash
uv run pytest app/testsuite/test_qa_ai_helper_markdown.py -q
uv run pytest app/testsuite/test_qa_ai_helper_preclean.py -q
uv run pytest app/testsuite/test_qa_ai_helper_api.py -q
uv run pytest app/testsuite/test_component_spec.py -q
node --test app/testsuite/js/markdown-renderer.test.mjs
node --test app/testsuite/js/test-case-list-interactions.test.mjs
node --test app/testsuite/js/assistant-widget.test.mjs
npm run lint
```

The repository has no `npm test` or Playwright npm script. A browser smoke command MUST be supplied by the implementation agent using the available browser driver/manual harness or a newly added deterministic browser fixture, and MUST be recorded with its asset-blocking and DOM assertions.
