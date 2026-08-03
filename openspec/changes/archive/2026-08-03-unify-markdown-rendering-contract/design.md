# Markdown Rendering Contract Design

## Status and scope

`unify-markdown-rendering-contract` completed the implementation-and-verification work and is archived. The CommonMark adapter, self-hosted assets/manifest, corpus/GFM fixtures, focused tests, and all listed surface migrations are checked in. The direct behavior evidence, including browser smoke coverage, is recorded in [`verification.md`](verification.md); the callsite and trust-boundary ledger remains in [`inventory.md`](inventory.md).

## Context

Markdown 目前出現在 Test Case Management editor/preview、Test Run Execution 欄位與 comments、QA AI Helper ticket preview/editor、global Assistant Widget，以及 Jira Wiki conversion。來源可能是 user、database/API、AI、streaming tool result 或外部 Jira；全部是不可信輸入。Jira Wiki 仍有 backend deterministic parser/converter，但它不是瀏覽器 renderer。

本設計固定兩個不可混用的邊界：

1. **Source boundary:** source Markdown（或 Jira Wiki source 在 backend conversion 前）是唯一 authoritative data。Sanitized/rendered HTML 是暫時 display output，不得持久化、回填 editor 或交給 backend parser 取代 source。
2. **Display boundary:** parser result 只有在 canonical adapter 的 Safe Display Profile 完成後才可交給 DOM sink；surface 不得自行呼叫 parser、sanitizer、regex renderer 或插入 parser HTML。

## Goals / non-goals

### Goals

- 所有 browser Markdown surface 使用同一 `window.TCRTMarkdown` adapter、同一 parser/version/options、同一 GFM matrix、同一 Safe Display Profile。
- 以 CommonMark 0.31.2 official corpus 與 GFM 0.29 feature matrix 證明 parser layer；以獨立 Safe Display/XSS suite 證明 DOM layer；再以每個 surface 的實際 DOM integration 證明遷移完整。
- raw HTML AST nodes have deterministic provenance; regardless of the original element name, no source raw node can become a DOM element.
- fallback、readiness、reason、source retry、URL normalization、task checkbox 與 external-origin semantics 可以由測試直接觀察。
- parser/sanitizer assets self-host、version-pin、single controlled origin、offline 可重現。

### Non-goals

- 不由 design 文件本身重新實作 runtime；已 check-in 的 adapter/assets/surface work 仍須依 tasks/inventory 的可觀察 acceptance evidence 驗證。
- 不引入 footnotes、emoji、math、heading anchors、underline 或其他未宣告 dialect。
- 不把 Jira Wiki conversion 重新命名為 CommonMark parser，也不讓 backend conversion 產生 HTML。
- 不把 raw source HTML 開放為 user-facing HTML 功能；source raw HTML 只能變成 escaped literal text。
- 不更新 `openspec/specs/` 主規格、不 archive 本 change，直到 implementation、分層測試及所有 surface integration 有證據。

## Decision 1: exact parser, assets, options, and corpus proof

### Canonical browser dependency pins

Implementation SHALL vendor the exact local ESM dependencies under `app/static/vendor/` and record source URL, local file SHA-256, license and acquisition date in `app/static/vendor/MANIFEST.md`:

| Role | Package/version and source | Local artifact | Runtime use |
|---|---|---|---|
| CommonMark parser/AST | `commonmark@0.31.2`, BSD-2-Clause; `https://unpkg.com/commonmark@0.31.2/dist/commonmark.js` | `app/static/vendor/commonmark/commonmark.esm.mjs`; local ESM wrapper SHA-256 `13613ebd2867bd06994c26cce1089e91b561ff5810ca4da22e51034a4210292f` | Private `commonmark.Parser`/AST renderer; no page global. |
| Sanitizer | `DOMPurify@3.4.12` ESM; `https://cdn.jsdelivr.net/npm/dompurify@3.4.12/dist/purify.es.mjs` | `app/static/vendor/dompurify/purify.es.mjs`; SHA-256 `b51207de097d14ff9af93bb923d1a245d196a474cbbfdcfeda5e2166734715e1` | Explicit Safe Display allowlist, hooks and URL policy are private to the adapter. |

The browser MUST load these local artifacts from the application origin. No CDN, floating URL, network fetch, `window.commonmark`, `window.marked`, or `window.DOMPurify` dependency is allowed. The commonmark wrapper MAY preserve the upstream source while adapting its exports to ESM; the manifest and adapter import path must remain in sync.

### Exact parser and AST-renderer configuration

The adapter SHALL create one private parser and AST renderer with this immutable configuration; no surface can override it:

```js
const parser = new commonmark.Parser();
const renderer = new commonmark.HtmlRenderer({
  safe: false,
  softbreak: '\n',
});
```

The adapter's canonical AST renderer SHALL use the parsed CommonMark AST and the renderer's `safe:false`/`softbreak:'\n'` semantics, then apply the declared GFM AST extensions. `safe:false` is required so raw nodes are observable for provenance; the canonical raw-node renderer escapes them before sanitization. No marked-only `async`, `breaks`, `gfm`, `pedantic`, `silent`, `headerIds`, `mangle`, `sanitize` or `setOptions` option exists or may be introduced. Surface code cannot pass parser/renderer options.

GFM behavior is implemented only in the canonical AST renderer and SHALL be exactly tables, task list items, strikethrough and autolink literals. CommonMark package behavior outside the baseline and these four extensions is not a declared contract.

### CommonMark corpus proof

The parser layer SHALL execute the frozen `app/testsuite/fixtures/markdown/commonmark-0.31.2.json` fixture containing all 652 CommonMark 0.31.2 examples. Its SHA-256 SHALL be verified as `7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c` (140848 bytes). The corpus test SHALL:

1. verify the fixture identity before running examples;
2. parse every example with `new commonmark.Parser().parse(input)` and the parser-conformance AST renderer (before Safe Display); and
3. compare normalized HTML/AST semantics to each official expected result, with no skipped examples and no sanitizer output in the assertion.

The official GFM specification at `https://github.github.com/gfm/` is the source for the four extension cases. A checked-in GFM matrix SHALL have positive and boundary cases for each declared extension and literal/negative cases for footnotes, emoji, math, heading anchors, underline, raw HTML behavior and other unlisted syntax. GFM cases are not allowed to weaken CommonMark corpus expectations.

Parser conformance and Safe Display are separate tests. The parser-conformance renderer may preserve official raw HTML for comparison; the browser adapter's AST renderer MUST escape source raw HTML as specified below.

## Decision 2: AST provenance and raw HTML policy

The adapter parses source once into a CommonMark AST and classifies raw `html_block`/`html_inline` nodes with a per-render provenance registry:

- `origin: 'commonmark-ast'` identifies parser-generated structure (heading, paragraph, link, image, list, table, task item, etc.).
- `origin: 'source-raw-html'` identifies every `html_block`/`html_inline` node whose bytes came from source Markdown. The record retains node identity and exact source literal; it is not serialized into display HTML. The adapter exposes this policy as `rawHtmlProvenance: 'ast-node-type'`.
- `origin: 'renderer-generated'` identifies only fixed nodes created by the adapter (external-link attributes and task checkbox attributes). Source attributes never become renderer attributes.

The raw HTML rule is deterministic: custom AST methods for `html_block` and `html_inline` return escaped text for the complete source literal, including `<script>`, `<img>`, `<input>`, `<p>`, or any other tag. They never reparse the string, even if the tag name matches an element allowlist. DOMPurify runs after this renderer as defense in depth; it cannot turn escaped raw text back into an element. A source HTML element is therefore never executable or rendered as an element merely because its name is allowed. Raw HTML is not silently treated as a task checkbox or image.

Malformed-looking Markdown is not a raw HTML exception. For example, an unclosed delimiter or an unmatched bracket is handled by CommonMark AST semantics and normally returns `status: 'ok'` with literal text. Only an actual parser/policy exception uses `reason: 'renderer-error'` and fail-closed plaintext.

## Decision 3: shared adapter API, readiness, and reason contract

`/static/js/common/markdown-renderer.js` is the only browser adapter entry point. Its public namespace is the only permitted parser-related global:

```js
window.TCRTMarkdown = {
  ready: Promise<{
    status: 'ok' | 'fallback',
    reason?: ReasonCode
  }>,
  render(source, { surface }): {
    html: string,
    status: 'ok' | 'fallback',
    reason?: ReasonCode
  }
};
```

`source` is normalized to a string (`null`/`undefined` → empty string) before parsing. `surface` is a diagnostic label (`test-case-management`, `test-run-execution`, `qa-ai-helper`, `assistant` or `jira-preview`); it MUST NOT select a parser, option, allowlist, URL policy or fallback variant.

### Readiness lifecycle

- The adapter owns imports/initialization and creates `ready` exactly once.
- Before readiness is settled, `render` returns a complete escaped `<pre>` plaintext result with `status: 'fallback'`, `reason: 'renderer-pending'`; it never returns parser HTML.
- `ready` always resolves and never rejects. Success is `{status:'ok'}`. Unavailability is `{status:'fallback', reason}`; it MUST NOT expose source content in the reason or logs.
- A surface that first receives `fallback` renders the returned `html`, marks a localized unavailable status, and schedules a retry from the unchanged source. It retries only when `await adapter.ready` yields `{status:'ok'}`; an unavailable readiness result leaves the safe fallback in place.
- A readiness retry is conditional on the same DOM node and source revision still being current. A newer edit/stream chunk cancels an older retry.

Canonical reason codes are:

| Reason | Meaning | Required output |
|---|---|---|
| `renderer-pending` | Adapter script exists but assets are not ready | Escaped `<pre>` source, `fallback`; retry on successful readiness. |
| `asset-unavailable` | Self-hosted module import/load failed | Escaped `<pre>` source, `fallback`; no network/CDN retry. |
| `parser-unavailable` | CommonMark module missing or invalid | Escaped `<pre>` source, `fallback`. |
| `sanitizer-unavailable` | DOMPurify module missing or invalid | Escaped `<pre>` source, `fallback`. |
| `renderer-error` | Unexpected parse/policy exception for a string | Escaped `<pre>` source, `fallback`; record only the reason code and surface. |

A malformed Markdown document that the parser accepts is **not** `renderer-pending`, `asset-unavailable`, or `renderer-error`. Surface wrappers may use local diagnostic reasons (`adapter-unavailable`, `invalid-adapter-result`, `adapter-error`) when the namespace/result itself is missing, but these are not renderer reasons and may not cause an unsafe fallback.

The fallback `<pre>` is produced from a text node/escaped text, retains every original LF/CRLF-normalized newline, and contains no source-derived attributes. The adapter's `html` is safe for direct `innerHTML` insertion; a surface MUST NOT add source text to that HTML string.

## Decision 4: Safe Display Profile

Sanitization occurs only inside the adapter after canonical rendering and before any surface DOM insertion. Every surface uses the same profile.

### Element allowlist

The only adapter-generated elements are:

`p`, `h1`–`h6`, `ul`, `ol`, `li`, `blockquote`, `pre`, `code`, `em`, `strong`, `del`, `a`, `br`, `hr`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `img`, and GFM task-list `input`.

No `div`, `span`, `iframe`, `form`, `button`, `script`, `style`, SVG, MathML or custom element is generated by the adapter. A surface may add a presentation wrapper **after** insertion (for example an Assistant table wrapper), but it may not put user/source content into that wrapper HTML.

### Attribute allowlist

| Element | Allowed attributes | Provenance/constraint |
|---|---|---|
| `a` | `href`; generated `target`, `rel` for external HTTP(S) | `href` is normalized by the URL policy; `target`/`rel` are never source-controlled. |
| `img` | `src`, `alt` | `src` is normalized by image policy; `alt` is text, never HTML. |
| task `input` | `type="checkbox"`, optional generated `checked`, `disabled` | All values are renderer-generated from GFM AST task metadata. No `name`, `value`, `form`, event, style or source attribute. |
| all other elements | none | Remove/escape every attribute, including `id`, `class`, `title`, `style`, `data-*`, `on*`, `aria-*`, and unknown attributes. |

The sanitizer SHALL use explicit `ALLOWED_TAGS`, `ALLOWED_ATTR`, `ALLOW_DATA_ATTR: false`, no style/URI relaxation, and an attribute hook that re-applies the URL/origin policy. The rendered output does not acquire heading IDs or anchors.
The parser/conformance layer may observe CommonMark ordered-list start and GFM table alignment semantics. The browser Safe Display output intentionally does not emit `ol[start]` or `th/td[align]`; these are not in the display attribute allowlist. Table structure remains available, and parser-layer corpus/matrix tests remain the proof for syntax recognition.

### URL normalization and origin rules

The adapter receives the parser-normalized destination and applies this deterministic algorithm before assigning `href` or `src`:

1. Reject empty destinations, ASCII controls (`U+0000`–`U+001F`, `U+007F`), backslashes, and protocol-relative `//host` destinations. Reject explicit schemes other than `http`, `https`, and safe `mailto:` (case-insensitive). `javascript:`, `data:`, `blob:`, `file:`, `vbscript:`, and all other schemes are rejected.
2. Percent-encoded scheme-looking text is treated as a relative literal and serialized with `encodeURI`; it is never decoded into an executable scheme. No URL policy may decode it into `javascript:`. HTML-entity spellings of an unsafe scheme/colon (for example `java&#x73;cript:` or `java&colon;script:`) are normalized only for safety detection and rejected.
3. For a relative anchor (`/path`, `./path`, `../path`, `?query`, `#fragment`, or a relative path), preserve the relative navigation semantics using `encodeURI`; emit no `target` or `rel`. It must not be upgraded to an external link merely because the current origin is known.
4. For an explicit `http`/`https` URL, resolve with `new URL(value, document.baseURI)` and serialize `.href`. Compare the resulting `.origin` (scheme/host/effective port) to the browser page origin. Same-origin output has no `target`/`rel`; another origin gets exactly `target="_blank" rel="noopener noreferrer"`.
5. A protocol-relative destination is rejected rather than inheriting a page scheme. Credentials, malformed URL syntax, and control characters in the resolved URL are rejected.
6. A link `mailto:` is allowed only when it is exactly a safe, non-empty addr-spec (`local@domain` with no controls, whitespace, nested scheme, query or fragment). It gets no target/rel. CommonMark email autolink output may be retained only when it satisfies this rule.
7. An image `src` is allowed only when it is relative (same application navigation semantics) or an explicit `https` URL. External `http` images and every unsafe scheme are rejected. An unsafe image becomes its escaped alt text (or no image), never an element with a retained unsafe `src`.
8. For a rejected link, remove the `href` and preserve only the already-safe rendered label text; do not preserve a clickable element. For a rejected image, preserve only safe alt text. Raw HTML links/images never enter this algorithm because their complete AST source nodes were escaped.

The tests SHALL cover case/whitespace variants, `//host`, controls, backslashes, percent-encoded schemes, same-origin/different-origin http(s), relative query/fragment, mailto edge cases, and unsafe image URLs.

### Task-list provenance

A checkbox is emitted only when the canonical GFM extension recognizes a source-leading `[ ]`, `[x]`, or `[X]` marker and binds its checked state to the parsed list-item node by per-render node identity. The renderer removes that marker from visible item text and emits:

```html
<input type="checkbox" disabled>
<input type="checkbox" checked disabled>
```

Attribute order and presence are deterministic. The checkbox is disabled/non-interactive, has no event/name/value/form attributes, and cannot submit or mutate source. A source raw `<input>` or text that merely resembles a checkbox does not qualify. `checked` is the only source-derived state; it is not persisted as HTML. Accessibility status for the task is supplied by the surrounding list text/semantic list, not by user-controlled attributes.

## Decision 5: CommonMark semantics and legacy editor behavior

- A single LF in a paragraph is a soft break. `breaks: true` is forbidden. Only two trailing spaces or a backslash hard-break syntax produce `<br>`.
- Heading level/text and inline AST semantics are unchanged; no automatic `id`, anchor, slug, or heading rewrite.
- Tables, task list items, strikethrough and autolink literals are the only GFM features. Unsupported syntax stays literal/safe; it is not silently transformed into another dialect. Safe Display's intentional omission of ordered-list `start` and table `align` attributes is defined above; parser-layer tests still cover those semantics.
- Toolbars write canonical source only: headings (`# `), lists (`- `/`1. `), emphasis (`*…*`/`**…**`), code (backticks), links/images, tables, task markers, strikethrough (`~~…~~`) and standard hard breaks. They must not write raw HTML, `<u>`, private underline markers, or page-specific line-break syntax.
- Existing `Ctrl/Cmd+B` and `Ctrl/Cmd+I` behavior remains canonical. The legacy `Ctrl/Cmd+U` interception and `<u>` insertion are removed in both Test Case Management and Test Run Execution; the key is no longer consumed by Markdown code. Existing stored `<u>` source is preserved and displays as escaped raw source, not rewritten or rendered as underline.
- Toolbar labels/help/disabled states and unavailable indicators use the existing i18n lifecycle. New keys (at minimum `markdown.rendererUnavailable`, `markdown.taskChecked`, `markdown.taskUnchecked`, and surface-specific accessibility labels where needed) must exist in `en-US.json`, `zh-CN.json`, and `zh-TW.json`; no hard-coded user-visible fallback is accepted once locale data is loaded.

## Decision 6: Jira source-only boundary

The backend functions `_jira_wiki_inline_to_md`, `_jira_wiki_to_markdown`, `_markdown_to_jira_wiki`, and `_build_ticket_markdown` are explicit conversion functions, not CommonMark parsers and not sanitizers. They may:

- convert only listed Jira Wiki headings, lists, code/noformat, quote, rule, table, inline emphasis, strike and links into canonical Markdown;
- preserve unknown Jira tokens as safe literal source or return an explicit conversion result; and
- convert user-edited canonical Markdown back to Jira Wiki solely because the existing deterministic backend parser expects Jira Wiki.

They MUST NOT emit HTML, call `window.TCRTMarkdown`, call a browser parser, or make external Jira content trusted. `fetch_ticket`/`reload_ticket_from_jira` create a raw source snapshot; `reparse_ticket_markdown` persists the submitted source and derives backend-only parser input. QA AI Helper browser preview receives that source and calls the adapter exactly once for display. Outbound `create_bug_from_test_result` Jira descriptions remain an API integration boundary and are not browser Markdown output.

## Decision 7: surface migration matrix

| Surface | Sources | Adapter call | Safe DOM sink/output | Required failure behavior |
|---|---|---|---|---|
| Test Case Management preview/editor | P1/P2/P3 fields, bulk and AI-assisted values | `surface: 'test-case-management'` from the shared Markdown module | Three `.markdown-preview` regions; source stays in textareas/transient retry attributes | Escaped `<pre>` plus localized `role="status" aria-live="polite"`; unchanged source re-rendered after readiness. |
| Test Run Execution fields | P2/P3 test-case precondition, steps, expected result | `surface: 'test-run-execution'` | Detail modal field regions receive only adapter `html` | Same fallback/status; no raw source interpolation into generated detail HTML. |
| Test Run Execution comments | P1/P2/P3 comment source | `surface: 'test-run-execution'` | `#commentContent` receives adapter `html`; original source retained for edit | Same fallback/status; edit/cancel uses original source, not rendered HTML. |
| QA AI Helper ticket preview | P2/P3/P4 raw snapshot, user reparse, AI result | `surface: 'qa-ai-helper'` | `#qaHelperTicketMarkdown` receives adapter `html`; editor remains source-only | Jira conversion occurs before browser call; fallback/status and readiness retry are visible/localized. |
| Global Assistant Widget | P1/P2/P3 messages, SSE chunks, tool/external results, history | `surface: 'assistant'` | `.tcrt-assistant-text` receives adapter `html`; code/table decorations occur after insertion | Every chunk/history path uses same adapter; fallback does not render partial parser HTML and recovery is source/revision guarded. |
| Jira Wiki adapters | P4 external Jira/Wiki source; P1 edited source | Backend conversion only, then browser caller uses one of the above surfaces | No direct HTML output from converter | Unknown token is literal/explicit conversion result; Safe Display cannot be bypassed. |

No source provenance grants a wider allowlist or different parser options.

## Decision 8: i18n and accessibility status

The adapter returns no localized prose. Each surface owns a fixed status node built with DOM APIs and translated through `window.i18n`:

```html
<span role="status" aria-live="polite" data-i18n="markdown.rendererUnavailable"></span>
```

The status says that Markdown rendering is unavailable and that source text is being shown; it never includes the reason code, raw source, exception, URL or ticket data. On successful re-render it is removed or hidden and the preview container is retranslated after locale changes. The fallback `<pre>` remains readable, preserves line breaks, does not create focusable controls, and is not announced as interactive content. Disabled task checkboxes cannot receive focus or submit data. Browser tests SHALL check keyboard/focus order and all three locale keys.

## Decision 9: layered verification and actual harness

Tests are behavior tests, never source-text assertions standing in for runtime behavior:

1. **Parser layer:** `app/testsuite/fixtures/markdown/commonmark-0.31.2.json` hash + all 652 examples; GFM positive/boundary matrix; malformed-looking input returns canonical literal semantics.
2. **Semantic layer:** soft/hard LF, no heading IDs, no code classes, AST task provenance and AST-level source/raw-node distinctions.
3. **Safe Display layer:** raw AST node escaping, element/attribute allowlist, URL normalization/origin, mailto, image, task checkbox, target/rel and XSS vectors.
4. **Failure layer:** pending asset, import failure, parser/sanitizer absence and renderer exception; assert safe `<pre>`, status/reason and no unclean HTML. Separate malformed input (status `ok`) from unavailable assets (status `fallback`).
5. **Surface integration:** actual DOM for every row in `inventory.md`, including streaming/history/reparse/edit/recovery and unchanged source.
6. **Assets/i18n/a11y:** offline same-origin imports, manifest/hash, no parser globals/CDN, three locales, status `role/aria-live`, focus/keyboard behavior.

Existing commands are the focused harness for remaining implementation verification; the checked-in code does not make their results implicit:

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

There is no repository `npm test` or Playwright npm script. Browser smoke evidence must use the available browser driver/manual harness (or a newly added deterministic browser fixture) to block CDN/parser assets, render a page, exercise DOM output, and observe readiness recovery; the remaining verification task must record the exact invocation and evidence. A Node VM test alone cannot claim browser DOM/XSS completion.

## Failure / recovery matrix

| Condition | Classification | Forbidden behavior | Required result | Recovery |
|---|---|---|---|---|
| Unclosed emphasis/bracket/fence accepted by parser | Malformed-looking source, not unavailable | Treat as adapter outage; mutate source | `status:'ok'`, canonical literal/AST semantics | None; normal re-render from source. |
| Adapter not ready | Renderer pending | parser global, partial regex, unsafe HTML | Escaped `<pre>`, `fallback`, `renderer-pending` | Retry unchanged source only after `ready` `{status:'ok'}`. |
| Local asset import fails | Renderer unavailable | CDN retry, global fallback, partial HTML | Escaped `<pre>`, `fallback`, `asset-unavailable` | Keep fallback; diagnostics contain only reason/surface. |
| Parser/sanitizer module unavailable | Renderer unavailable | Surface-specific parser/sanitizer | Escaped `<pre>`, `fallback`, exact unavailable reason | Keep fallback until a later successful adapter initialization. |
| Unexpected parser/policy exception | Renderer error | Return exception HTML or raw source HTML | Escaped `<pre>`, `fallback`, `renderer-error` | Retry only after adapter recovery; source unchanged. |
| Dangerous element/attribute/URL | Untrusted source | Preserve raw HTML or widen allowlist | Escape raw AST node source; remove/escape element/attribute/URL by fixed profile | Render source again with same policy; never rewrite source. |
| Unknown Jira Wiki token | Conversion boundary | Claim CommonMark, emit HTML, bypass adapter | Literal safe source or explicit conversion error/result | Add a reviewed conversion rule plus backend and browser tests. |

## Rollout boundary

Migration completed in the prescribed order: inventory/fixtures → pinned local assets and adapter/readiness → Test Case Management → Test Run Execution → QA AI Helper/Jira preview → Assistant Widget → legacy deletion → layered/integration/browser evidence → primary-spec update/archive. Every task has direct acceptance evidence in [`verification.md`](verification.md).
