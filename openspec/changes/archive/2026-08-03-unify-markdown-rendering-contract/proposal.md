# Change: Unify Markdown Rendering Contract

## Status

This change completed its implementation-and-verification work and is archived. It includes the canonical CommonMark adapter, self-hosted assets/manifest, corpus/GFM fixtures and tests, and every listed surface migration. All acceptance tasks are checked against the direct evidence in [`verification.md`](verification.md); [`inventory.md`](inventory.md) records the parser, renderer, sanitizer, asset, toolbar, Jira conversion, direct DOM sink, provenance and test coverage.

## Why

TCRT displays Markdown in several unrelated browser paths. Existing paths have page-level `marked` options, regex rendering, different sanitizer allowlists, CDN loaders and Jira Wiki conversion mixed into display code. In particular, `breaks: true` changes CommonMark soft breaks, raw HTML can be confused with safe parser output, and fallback behavior can be mistaken for a successful render. User, database, AI, streaming-tool and external Jira content all cross the same untrusted display boundary.

The change makes the boundary explicit: source text is preserved, parser conformance is tested separately from safe DOM display, and every browser surface consumes one adapter result. Jira Wiki conversion remains a backend source-only operation.

## What changes

- Adopt a single browser dialect: CommonMark 0.31.2 baseline plus only GFM 0.29 tables, task list items, strikethrough and autolink literals. Footnotes, emoji, math, heading anchors, underline and other extensions are not declared support.
- Pin the browser implementation to local `commonmark@0.31.2` ESM (BSD-2-Clause; source `https://unpkg.com/commonmark@0.31.2/dist/commonmark.js`, local ESM wrapper SHA-256 `13613ebd2867bd06994c26cce1089e91b561ff5810ca4da22e51034a4210292f`) and `DOMPurify@3.4.12` ESM. The adapter uses private `new commonmark.Parser().parse(source)` plus `HtmlRenderer({safe:false, softbreak:'\n'})` semantics, a custom AST renderer and `ast-node-type` raw provenance; no parser globals or page options.
- Prove the parser layer against `app/testsuite/fixtures/markdown/commonmark-0.31.2.json` (652 examples, SHA-256 `7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c`) and a separate GFM feature matrix. Sanitizer/display tests must not substitute for corpus proof.
- Define `window.TCRTMarkdown.render(source, { surface }) -> { html, status, reason? }` and a non-rejecting `window.TCRTMarkdown.ready` Promise. Before readiness or when assets/policy are unavailable, the adapter returns escaped `<pre>` plaintext with `status:'fallback'` and a stable reason; surfaces retry the unchanged source only after `{status:'ok'}` readiness.
- Make raw HTML provenance deterministic: every source `html_block`/`html_inline` AST node is escaped as literal text before sanitization. An allowlisted tag name in source does not grant element, event, style, data attribute or task-checkbox privileges.
- Apply one Safe Display Profile: fixed element/attribute allowlists, generated disabled task checkboxes only from GFM AST task-list metadata, deterministic URL normalization, safe `mailto:`, relative/HTTP(S) origin rules, and external `target="_blank" rel="noopener noreferrer"`.
- Keep normal LF as soft break, standard hard-break syntax as `<br>`, and headings without generated IDs. Toolbars emit canonical syntax only. Remove legacy underline output and `Ctrl/Cmd+U` interception without rewriting existing source.
- Keep Jira Wiki adapters as explicit source conversion only. Backend conversion can produce canonical Markdown or Jira Wiki parser input, but never HTML and never a browser parser claim; QA AI Helper sends the resulting source to the shared adapter.
- Migrate Test Case Management, Test Run Execution, QA AI Helper/Jira preview, global Assistant Widget and every Jira adapter in the order documented by `design.md`/`inventory.md`; delete legacy parser, sanitizer, regex and CDN paths only after behavior evidence exists.
- Add localized unavailable status (`role="status"`, `aria-live="polite"`) and task/accessibility behavior in all three locales. Do not expose raw source or reason details in user-facing status or logs.
- Use actual repository harnesses: focused `uv run pytest ...`, `node --test ...`, `npm run lint`, and a browser driver/manual smoke that blocks CDN assets and observes DOM output/readiness recovery. There is no `npm test` command in this repository.

## Non-goals

- Database/schema/migrations remain outside this change.
- The contract does not broaden the dialect or make raw HTML a display feature.
- It does not persist sanitized/rendered HTML or use it as source for editors/backend parsers.
- The primary `openspec/specs/markdown-rendering` contract was updated only after corpus, Safe Display, fallback, asset, integration, i18n/a11y and browser evidence passed.

## Impact

The change includes checked-in runtime/template/locale/vendor/test artifacts described by `inventory.md`: the common adapter, local assets, fixtures, focused tests, and all migrated surfaces. It adds no database/schema/migration work. The complete focused/browser evidence is recorded in [`verification.md`](verification.md), and the verified contract is now in `openspec/specs/markdown-rendering`.
The source data boundary remains unchanged: user, database, AI, tool and external Jira content are untrusted and remain source Markdown (or source Jira Wiki until explicit backend conversion). Sanitized/rendered HTML is never persisted or treated as source.
