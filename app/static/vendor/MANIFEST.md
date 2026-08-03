# Self-hosted frontend vendor assets

Pinned third-party presentation assets served from the application origin.
Do not load these libraries from CDN at runtime.

| Package | Version | Source | Local path | npm integrity | License | Acquired (UTC) |
|---|---|---|---|---|---|---|
| Bootstrap | 5.3.0 | https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/ | `bootstrap/` | `sha512-UnBV3E3v4STVNQdms6jSGO2CvOkjUMdDAVR2V5N4uCMdaIkaQjbcEAMqRimDHIs4uqBYzDAKCQwCB+97tJgHQw==` | MIT | 2026-08-03 |
| Font Awesome Free | 6.4.0 | https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/ | `fontawesome/` | `sha512-0NyytTlPJwB/BF5LtRV8rrABDbe3TdTXqNB3PdZ+UUUZAEIrdOJdmABqKjt4AXwIoJNaRVVZEXxpNrqvE1GAYQ==` | (CC-BY-4.0 AND OFL-1.1 AND MIT) | 2026-08-03 |
| pako | 2.1.0 | https://cdn.jsdelivr.net/npm/pako@2.1.0/ | `pako/` | `sha512-w+eufiZ1WuJYgPXbV/PO3NCMEc3xqylkKHzp8bxp1uW4qaSNQUkwmLLEc3kKsfz8lpV1F8Ht3U1Cm+9Srog2ug==` | (MIT AND Zlib) | 2026-08-03 |
| CommonMark | 0.31.2 | https://unpkg.com/commonmark@0.31.2/dist/commonmark.js | `commonmark/commonmark.esm.mjs` (local ESM wrapper without a browser global; SHA-256 `13613ebd2867bd06994c26cce1089e91b561ff5810ca4da22e51034a4210292f`) | `sha512-2fRLTyb9r/2835k5cwcAwOj0DEc44FARnMp5veGsJ+mEAZdi52sNopLu07ZyElQUz058H43whzlERDIaaSw4rg==` | BSD-2-Clause | 2026-08-03 |
| DOMPurify | 3.4.12 | https://cdn.jsdelivr.net/npm/dompurify@3.4.12/dist/purify.es.mjs | `dompurify/purify.es.mjs` (SHA-256 `b51207de097d14ff9af93bb923d1a245d196a474cbbfdcfeda5e2166734715e1`) | `sha512-zQvGet8Z2sWbQhCmfFz/T5QWH2oBmjnqK3qvOjaqaNLrLEF912WamU+ohnTp0TCep/MFVHpdJuCZEdFOdTnEFg==` | (MPL-2.0 OR Apache-2.0) | 2026-08-03 |
| Noto Sans | wght 400/500/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans/` | n/a (non-npm asset) | OFL-1.1 | 2026-08-03 |
| Noto Sans TC | wght 400/500/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans-tc/` | n/a (non-npm asset) | OFL-1.1 | 2026-08-03 |
| Noto Sans Mono | wght 400/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans-mono/` | n/a (non-npm asset) | OFL-1.1 | 2026-08-03 |

Font faces are declared in `fonts/fonts.css` with `font-display: swap`.
Measured total woff2 size (2026-07-30): ~4.72 MiB (Noto Sans TC alone ~4.2 MiB across unicode-range slices). Static subsetting deferred unless size becomes unacceptable.

## Upgrade steps

1. Download the new pinned version into the matching directory.
2. Update this manifest (version + source URL).
3. Point `app/templates/base.html` (and any other templates) at the new files if names change.
4. For fonts: re-fetch Google Fonts CSS with a browser User-Agent, download referenced woff2 files, rewrite `src` URLs to `/static/vendor/fonts/...`, and regenerate `fonts/fonts.css`.
5. Run `uv run pytest app/testsuite/test_component_spec.py -q` and browser QA offline.
