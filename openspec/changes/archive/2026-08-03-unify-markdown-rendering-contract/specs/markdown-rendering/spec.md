# markdown-rendering Specification Delta

## Purpose

This delta defines the checked-in TCRT Markdown rendering contract. The canonical adapter, local assets, parser/GFM fixtures, Safe Display suite, surface migrations, and browser evidence are complete; the companion [`../../verification.md`](../../verification.md) records the behavior evidence. This delta is ready to be synchronized into the primary specification and archived.

## ADDED Requirements

### Requirement: Canonical parser implementation, dialect, and corpus

The browser adapter SHALL use local, version-pinned `commonmark@0.31.2` ESM (BSD-2-Clause) and local, version-pinned `DOMPurify@3.4.12` ESM. The CommonMark wrapper SHALL expose `new commonmark.Parser().parse(source)` and the canonical AST renderer SHALL use `new commonmark.HtmlRenderer({safe:false, softbreak:'\n'})` semantics before its Safe Display policy. No surface MAY access `window.commonmark`, `window.marked`, `window.DOMPurify`, parser globals, `setOptions`, or a private parser configuration.

The declared dialect SHALL be CommonMark 0.31.2 plus only GFM 0.29 tables, task list items, strikethrough and autolink literals. Footnotes, emoji, math, heading anchors, underline and other unlisted extensions are not supported by this contract.

The CommonMark parser test SHALL use `app/testsuite/fixtures/markdown/commonmark-0.31.2.json`, containing all 652 examples, with SHA-256 `7eda833601c864e0f3c36bac8c1a33d16d2071b90ad347a6f2c0e7088792c42c` (140848 bytes); it SHALL execute every example and compare parser-layer output without sanitizer output. A separate `app/testsuite/fixtures/markdown/gfm-matrix.json` SHALL include positive, boundary and negative/literal cases.

#### Scenario: Parser uses the exact canonical configuration

- **WHEN** a surface renders any source Markdown
- **THEN** the adapter SHALL use the pinned local CommonMark parser and exact AST-renderer configuration
- **AND** SHALL parse with `new commonmark.Parser().parse(source)` and render with `safe:false`, `softbreak:'\n'`, the four declared GFM AST extensions, and the provenance policy
- **AND** SHALL NOT read or mutate a parser global or accept surface option overrides

#### Scenario: CommonMark corpus is proof of parser conformance

- **WHEN** parser conformance verification runs
- **THEN** the fixture hash SHALL be checked
- **AND** every CommonMark 0.31.2 example SHALL be executed
- **AND** the assertion SHALL inspect parser/conformance output before Safe Display sanitization
- **AND** a sanitizer pass or source-text search SHALL NOT substitute for corpus evidence

#### Scenario: Declared GFM features are bounded

- **WHEN** source contains a table, task list item, strikethrough or autolink literal
- **THEN** parser behavior SHALL match the GFM 0.29 matrix
- **AND WHEN** source uses footnotes, emoji, math, heading anchors, underline or another unlisted extension
- **THEN** the system MUST NOT claim support or use a surface-specific interpretation
- **AND** unsupported syntax SHALL remain canonical literal/safe output

### Requirement: Raw HTML has deterministic AST provenance

The adapter SHALL distinguish source raw HTML from parser-generated structure using the CommonMark AST node types `html_block` and `html_inline` and a per-render provenance registry. Every such source node SHALL be registered by node identity and exact source literal under semantic `origin:'source-raw-html'`; parser-generated structure is AST output. The adapter policy SHALL expose `rawHtmlProvenance:'ast-node-type'`; provenance metadata MUST NOT be serialized as user-controlled DOM attributes.

The browser renderer SHALL escape the complete raw node source literal as text before DOMPurify. Raw `<script>`, `<img>`, `<input>`, `<p>`, or any other source element SHALL NEVER be reparsed or emitted as an element, even when its name is in the generated element allowlist. Raw HTML SHALL NOT create task checkbox state, links, images, events, style, data attributes or executable content.

#### Scenario: Allowlisted raw tag remains literal text

- **WHEN** source contains `<p>text</p>`, `<img src="https://example.test/a">`, or `<input type="checkbox">`
- **THEN** the adapter SHALL escape the complete raw AST node source literal as text
- **AND** DOM SHALL contain no corresponding source-created `p`, `img` or `input` node
- **AND** the result SHALL not execute, navigate, load an image, submit a form or create a checkbox

#### Scenario: Raw script and event attributes are fail-closed

- **WHEN** source contains `<script>`, `onerror`, `style`, `data-*`, SVG, MathML or another raw attribute/element
- **THEN** the complete source AST node SHALL be escaped or removed by the fixed policy
- **AND** no untrusted HTML SHALL reach a DOM sink
- **AND** the original source SHALL remain unchanged for later rendering

### Requirement: One shared adapter result and readiness contract

The only allowed browser parser namespace SHALL be `window.TCRTMarkdown` from `/static/js/common/markdown-renderer.js`:

```js
window.TCRTMarkdown.render(source, { surface })
// { html: string, status: 'ok'|'fallback', reason?: ReasonCode }
window.TCRTMarkdown.ready
// Promise<{status:'ok'|'fallback', reason?: ReasonCode}>
```

`render` SHALL always return a string `html` safe for direct display, and SHALL normalize null/undefined source to an empty string. `surface` SHALL be diagnostic only and SHALL NOT change parser options, extension set, URL policy or allowlist. `ready` SHALL settle once and never reject.

Before readiness, `render` SHALL return escaped `<pre>` plaintext with `status:'fallback'` and `reason:'renderer-pending'`. Canonical reason codes SHALL be `renderer-pending`, `asset-unavailable`, `parser-unavailable`, `sanitizer-unavailable`, and `renderer-error`. A surface-local missing namespace/result may report an internal `adapter-unavailable`, `invalid-adapter-result` or `adapter-error`, but it MUST still display only safe adapter output or escaped text.

A caller that first receives `fallback` SHALL retain the unchanged source and retry only after `await window.TCRTMarkdown.ready` returns `{status:'ok'}`. If readiness returns fallback, the caller SHALL keep the safe fallback and localized unavailable indicator. Source revision/node identity SHALL guard against stale asynchronous retries.

#### Scenario: Renderer is pending

- **WHEN** a caller invokes `render` before local parser/sanitizer initialization completes
- **THEN** result SHALL have `status:'fallback'` and `reason:'renderer-pending'`
- **AND** `html` SHALL be escaped plaintext in a `<pre>` preserving newlines
- **AND** result SHALL not contain parser HTML, raw source attributes or a partial regex render

#### Scenario: Readiness succeeds and source is re-rendered

- **WHEN** `ready` resolves `{status:'ok'}` after an initial fallback
- **THEN** the caller SHALL invoke the adapter again with the unchanged source
- **AND** SHALL replace the fallback only if the source and target node are still current
- **AND** SHALL not use fallback HTML as new Markdown source

#### Scenario: Readiness is unavailable

- **WHEN** local asset import fails or parser/sanitizer/policy initialization is unavailable
- **THEN** `ready` SHALL resolve `{status:'fallback', reason:<unavailable-code>}` without rejecting
- **AND** callers SHALL keep escaped plaintext and status indication
- **AND** no CDN or page-level fallback MAY be attempted

#### Scenario: Malformed-looking input is not unavailable

- **WHEN** source has an unclosed emphasis delimiter, unmatched bracket, or unclosed fence that the canonical parser accepts
- **THEN** the adapter SHALL return `status:'ok'` with the parser's literal/standard semantics
- **AND** SHALL NOT classify the source as an unavailable asset or renderer-pending condition
- **AND** only an unexpected parser/policy exception MAY return `status:'fallback', reason:'renderer-error'`

### Requirement: Safe Display Profile is centralized

Sanitization MUST run only inside the canonical adapter, after canonical rendering and before any DOM insertion. The adapter-generated element allowlist SHALL be exactly: `p`, `h1`–`h6`, `ul`, `ol`, `li`, `blockquote`, `pre`, `code`, `em`, `strong`, `del`, `a`, `br`, `hr`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `img`, and task-list `input` checkbox. `div`, `span`, `iframe`, `form`, `button`, `script`, `style`, SVG, MathML and custom elements SHALL NOT be generated by the adapter.

Allowed attributes SHALL be exact: `a[href]` plus generated external `target`/`rel`; `img[src,alt]`; and task `input[type="checkbox"]` plus generated `checked`/`disabled`. All `id`, `class`, `title`, `style`, `data-*`, `aria-*`, `on*`, form and unknown attributes SHALL be removed/escaped. DOMPurify SHALL be configured with explicit tags/attributes, `ALLOW_DATA_ATTR:false`, no style/URI relaxation, and a URL-policy hook.
The parser/conformance layer MAY observe ordered-list start and GFM table alignment semantics. Browser Safe Display SHALL intentionally omit `ol[start]` and `th/td[align]` because they are outside the display attribute allowlist; table structure SHALL remain rendered and parser-layer corpus/matrix tests SHALL prove syntax recognition.

#### Scenario: Safe parser output is still sanitized

- **WHEN** canonical parser output contains a generated link, image, table, code block or task list
- **THEN** the adapter SHALL apply the same Safe Display Profile for every surface
- **AND** the surface SHALL insert only returned `html`
- **AND** no surface-specific sanitizer or allowlist MAY widen the result

#### Scenario: Unsafe attributes never become capabilities

- **WHEN** source contains event attributes, inline style, data attributes, user-controlled classes/IDs or a disallowed element
- **THEN** the adapter SHALL remove/escape them before return
- **AND** output SHALL contain no event handler, style execution, arbitrary data capability or executable node

### Requirement: URLs use deterministic normalization and origin rules

Before assigning a generated anchor/image URL, the adapter SHALL:

1. reject empty destinations, ASCII controls, backslashes, protocol-relative `//host`, malformed URLs and explicit schemes other than `http`, `https` and safe `mailto:`;
2. reject `javascript:`, `data:`, `blob:`, `file:`, `vbscript:` and all other unsafe schemes, case-insensitively;
3. treat percent-encoded scheme-looking text as a relative literal serialized with `encodeURI`, never decode it into a scheme; HTML-entity spellings of unsafe schemes/colons SHALL instead be normalized only for detection and rejected;
4. preserve relative anchor semantics (`/`, `./`, `../`, `?`, `#`, relative path) with `encodeURI`, without `target`/`rel`;
5. resolve explicit HTTP(S) with `new URL(value, document.baseURI)`, serialize `.href`, and compare `.origin` with the browser page origin; same-origin has no `target`/`rel`, different-origin gets exactly `_blank` and `noopener noreferrer`;
6. reject credentials and protocol-relative destinations rather than inheriting a scheme;
7. allow `mailto:` only for a non-empty addr-spec with no controls, whitespace, nested scheme, query or fragment; and
8. allow image `src` only when relative or explicit HTTPS, rejecting external HTTP and unsafe schemes.

A rejected link SHALL preserve only its safe rendered label without a clickable `href`; a rejected image SHALL preserve only safe alt text (or no image). Raw HTML URLs are already escaped by the raw AST node rule.

#### Scenario: Relative and same-origin links remain internal

- **WHEN** source contains `[x](/path?q=1#f)`, `[x](./path)`, or `[x](https://app.example/path)` on `https://app.example`
- **THEN** the output SHALL preserve relative semantics or use normalized same-origin URL
- **AND** SHALL NOT add `target` or `rel`

#### Scenario: External links are isolated

- **WHEN** source contains an explicit HTTP(S) URL whose origin differs from the browser page
- **THEN** output SHALL use normalized URL `.href`
- **AND** SHALL set `target="_blank" rel="noopener noreferrer"`
- **AND** an unsafe/invalid URL SHALL not remain clickable

#### Scenario: Unsafe and protocol-relative schemes are rejected

- **WHEN** source contains `javascript:`, `data:`, `blob:`, `file:`, a control/backslash, or `//other.example/path`
- **THEN** the URL SHALL be rejected
- **AND** no executable/navigation-capable attribute SHALL be returned

#### Scenario: Safe mailto and image rules are distinct

- **WHEN** source contains `<user@example.com>` or `[mail](mailto:user@example.com)`
- **THEN** a valid safe `mailto:` anchor MAY remain without target/rel
- **AND WHEN** an image uses an external HTTPS URL
- **THEN** it MAY remain
- **AND WHEN** an image uses external HTTP or any unsafe scheme
- **THEN** it SHALL be removed/escaped

### Requirement: Task checkboxes require parser provenance

A task checkbox SHALL be emitted only from a parsed list-item node that the canonical GFM extension annotated by per-render node identity after recognizing a source-leading `[ ]`, `[x]`, or `[X]` marker. It SHALL be exactly a renderer-generated disabled checkbox with `type="checkbox"`, optional `checked`, and `disabled`; it SHALL have no `name`, `value`, `form`, event, style, data or user-controlled attributes. A raw HTML `<input>` or checkbox-looking text SHALL never qualify. Checkbox state SHALL never write back to source.

#### Scenario: GFM task marker projects to a disabled control

- **WHEN** source contains `- [ ] todo` and `- [x] done`
- **THEN** output SHALL contain unchecked/checked disabled checkbox nodes
- **AND** visible list semantics and source text SHALL remain authoritative
- **AND** no checkbox SHALL be interactive or submit data

#### Scenario: Raw input cannot forge a task checkbox

- **WHEN** source contains `<input type="checkbox" checked>` or a task-like string outside a GFM task list item
- **THEN** the raw node/string SHALL be escaped or treated as ordinary text
- **AND** no source-created input node SHALL be emitted

### Requirement: CommonMark line breaks and heading semantics remain unchanged

Ordinary single LF SHALL remain a soft break. Only standard CommonMark hard-break syntax (two or more trailing spaces or a backslash) MAY generate `<br>`. The renderer SHALL use `softbreak:'\n'`, SHALL NOT add heading IDs/anchors or code language classes, and SHALL NOT rewrite AST level/inline semantics.

#### Scenario: Soft and hard breaks are distinguishable

- **WHEN** source contains `one\ntwo` without hard-break syntax
- **THEN** output SHALL not contain an automatic `<br>`
- **AND WHEN** source contains `one  \ntwo` or `one\\\ntwo`
- **THEN** output SHALL contain the corresponding hard break

#### Scenario: Heading identity is not invented

- **WHEN** source contains `# Heading`
- **THEN** output SHALL contain a heading with the standard level/text
- **AND** SHALL NOT contain generated `id`, anchor or slug attributes

### Requirement: Editors emit canonical syntax and preserve legacy source

Editor toolbars SHALL produce only canonical CommonMark/GFM syntax. They MUST NOT produce raw HTML underline, private underline markers, page-specific break syntax or another undeclared extension. Existing stored source SHALL not be rewritten merely because it contains unsupported/legacy syntax.

`Ctrl/Cmd+B` and `Ctrl/Cmd+I` SHALL retain canonical formatting behavior. The legacy `Ctrl/Cmd+U` handler SHALL be removed in Test Case Management and Test Run Execution; it SHALL not insert `<u>` or consume the key for Markdown. Existing `<u>` source remains source text and is escaped by Safe Display.

#### Scenario: Toolbar insertion is source-only

- **WHEN** a user activates a Markdown toolbar control
- **THEN** the textarea SHALL receive canonical source syntax
- **AND** preview SHALL call the shared adapter
- **AND** toolbar code SHALL not call parser/sanitizer or insert generated HTML

#### Scenario: Legacy underline does not widen the dialect

- **WHEN** a user presses `Ctrl/Cmd+U` or an existing source contains `<u>text</u>`
- **THEN** Markdown code SHALL not create underline syntax or intercept the key
- **AND** the existing source SHALL remain unchanged
- **AND** preview SHALL show raw HTML as escaped source text rather than underline DOM

### Requirement: Jira Wiki is source conversion only

Backend Jira Wiki functions SHALL be explicit conversion/preclean boundaries. They MAY convert listed Jira headings, lists, tables, code/noformat, quote, rule, inline formatting, strike and links to canonical Markdown, and MAY convert edited canonical Markdown back to Jira Wiki for the existing deterministic backend parser. They MUST NOT produce browser HTML, call the browser adapter/parser, claim CommonMark conformance, or bypass Safe Display. Unknown Jira tokens SHALL remain safe literal source or produce an explicit conversion result/error.

#### Scenario: Jira input is converted then rendered once

- **WHEN** QA AI Helper loads or reloads an external Jira ticket
- **THEN** backend SHALL persist deterministic raw canonical Markdown source
- **AND** browser preview SHALL pass that source to `window.TCRTMarkdown.render(...,{surface:'qa-ai-helper'})`
- **AND** no Jira converter output HTML SHALL be inserted directly

#### Scenario: Edited source is reparsed only on the backend boundary

- **WHEN** user submits edited `raw_ticket_markdown`
- **THEN** the exact submitted source SHALL remain persisted/returned
- **AND** any Markdown-to-Jira-Wiki conversion SHALL be backend-only parser input
- **AND** sanitized/rendered HTML SHALL never be used as a replacement source

#### Scenario: Unknown Jira token cannot widen the dialect

- **WHEN** Jira source contains no explicit conversion rule
- **THEN** converter SHALL preserve safe literal text or return an explicit conversion result
- **AND** SHALL not silently produce raw HTML, a private extension or direct DOM output

### Requirement: Every listed surface uses the same contract

Test Case Management preview/editor, Test Run Execution fields/comments, QA AI Helper ticket preview, global Assistant Widget messages, and Jira Wiki adapters SHALL treat user, database, AI, tool and external content as untrusted and use the shared contract. No surface MAY use a different parser option, extension set, sanitizer policy, URL policy or fallback renderer.

#### Scenario: Test Case Management source is consistently rendered

- **WHEN** preview displays a user, database, bulk, imported or AI-generated precondition/steps/expected result
- **THEN** it SHALL call the shared adapter and insert only returned `html`
- **AND** editor source SHALL remain available for save/retry

#### Scenario: Test Run fields and comments are consistently rendered

- **WHEN** detail modal or comment display receives database/imported/user content
- **THEN** it SHALL call the same adapter and Safe Display Profile
- **AND** comment edit/cancel SHALL use original source, not rendered HTML

#### Scenario: QA AI Helper and Assistant paths are consistently rendered

- **WHEN** QA ticket preview displays external/AI/user source or Assistant displays streaming/history/tool content
- **THEN** each path SHALL call the shared adapter with only its surface label
- **AND** readiness retry SHALL be source/revision guarded
- **AND** no partial chunk or unavailable asset MAY use another renderer

### Requirement: Self-hosted asset loading and migration order are deterministic

`/static/js/common/markdown-renderer.js` SHALL load local pinned parser/sanitizer assets from the application origin and SHALL be loaded before `assistant-widget.js` and every dependent classic page script. Templates SHALL not include parser/sanitizer CDN tags. The vendor manifest SHALL record versions, source integrity, local hash and license; the component asset guard SHALL no longer allow the removed parser/sanitizer CDN origins.

Migration SHALL occur in this order: inventory/fixtures and adapter contract; adapter/native assets/readiness; Test Case Management; Test Run Execution; QA AI Helper/Jira preview; global Assistant Widget; deletion of legacy parser/sanitizer/regex/CDN paths; layered, integration, browser, i18n and accessibility evidence. Legacy deletion is gated on all surface behavior tests.

#### Scenario: Browser starts offline with local assets

- **WHEN** parser/sanitizer network access is blocked and a supported page loads
- **THEN** page scripts SHALL use same-origin local assets only
- **AND** a missing/unavailable local asset SHALL produce adapter fallback, not a CDN retry or page-global parser

#### Scenario: Adapter precedes classic callers

- **WHEN** any dependent classic page script executes
- **THEN** `window.TCRTMarkdown` and its non-rejecting `ready` Promise SHALL already exist
- **AND** no page script MAY initialize parser globals or call `setOptions`

### Requirement: i18n, accessibility, and verification evidence are explicit

Unavailable status UI SHALL be created with a localized DOM text node/translation key, `role="status"` and `aria-live="polite"`; it SHALL not expose source, URL, exception or reason code. New visible/status/task labels SHALL be present in `en-US.json`, `zh-CN.json` and `zh-TW.json`. Fallback `<pre>` remains readable and non-interactive; task checkboxes are disabled and not focusable/submittable.

Verification SHALL be behavior-oriented and layered. The implementation SHALL use the repository's actual commands:

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

A browser smoke/DOM harness SHALL also block CDN assets, exercise rendered DOM/XSS/URL behavior, verify readiness recovery and keyboard/a11y behavior. The repository has no `npm test` or Playwright npm script; the implementation SHALL record the exact browser-driver/manual invocation used. Source-text assertions alone do not satisfy this requirement.

#### Scenario: Contract cannot be declared complete early

- **WHEN** any corpus, GFM, Safe Display, fallback, asset, i18n/a11y, browser or surface integration evidence is missing
- **THEN** this change SHALL remain active
- **AND** the main spec SHALL not be updated
- **AND** no task checkbox SHALL be changed to claim runtime work done
