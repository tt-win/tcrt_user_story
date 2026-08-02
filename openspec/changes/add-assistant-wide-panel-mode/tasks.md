## 1. Contract and change setup

- [x] 1.1 Review existing narrow/medium widget behavior and identify affected JS, CSS, locale, test, and OpenSpec files
- [x] 1.2 Incorporate agent review findings for OpenSpec coverage, direct controls, mobile transform reset, state mapping, and position reset
- [x] 1.3 Create branch `feat/assistant-wide-panel-mode` and initialize the spec-driven change
- [x] 1.4 Add proposal, design, and `assistant-widget-ui` delta spec

## 2. Three-mode direct widget implementation

- [x] 2.1 Normalize canonical `panelSizeMode` to `narrow`, `medium`, or `wide` with narrow fallback
- [x] 2.2 Replace the cycling resize transition with three direct mode buttons and a single active indicator
- [x] 2.3 Centralize mutually exclusive panel class application and persist canonical plus legacy localStorage values
- [x] 2.4 Add dynamic mode group/button labels, titles, aria-labels, aria-pressed state, and closed-panel inert lifecycle

## 3. Wide responsive layout

- [x] 3.1 Add centered desktop wide geometry at exact 80vw target with header/footer-aware height and right/bottom reset
- [x] 3.2 Override open/closed transforms so wide animation remains centered
- [x] 3.3 Extend mobile full-screen specificity to wide, reset centered positioning/transform, and keep direct mode buttons usable
- [x] 3.4 Verify resizing preserves messages, active streaming, confirmation cards, and attachment state
- [x] 3.5 Verify existing message, table, code, history, composer, confirmation, and attachment layout remains usable

## 4. Localization and focused tests

- [x] 4.1 Add `assistant.sizeModeLabel`, `assistant.sizeNarrow`, `assistant.sizeMedium`, and `assistant.sizeWide` to en-US, zh-CN, and zh-TW locales
- [x] 4.2 Update mode normalization tests for narrow/medium/wide, legacy values, and invalid values
- [x] 4.3 Add executable mode/storage/DOM behavior assertions plus CSS regressions for direct controls, unique active state, persistence migration, wide geometry, mobile reset, backdrop, accessibility lifecycle, and dynamic labels
- [x] 4.4 Run `node --check app/static/js/assistant-widget.js` and `node scripts/check-i18n-coverage.mjs`

## 5. Verification and independent review
- [x] 5.1 Run focused Node tests and applicable frontend lint gates
- [x] 5.2 Run `openspec validate add-assistant-wide-panel-mode --strict`
- [x] 5.3 Smoke-test desktop, short viewport, mobile, persistence precedence, language switching, keyboard focus lifecycle, and rich Assistant content
- [x] 5.4 Run independent subagent review of implementation and OpenSpec contract
- [x] 5.5 Fix review findings and repeat focused verification until no blocking findings remain

## 6. Wide backdrop emphasis
- [x] 6.1 Add a visual-only wide backdrop behind the panel/FAB with darkening and blur fallback
- [x] 6.2 Toggle backdrop visibility with wide + open state and preserve non-modal pointer/accessibility behavior
- [x] 6.3 Update the wide-mode spec, design, focused tests, and browser smoke coverage
