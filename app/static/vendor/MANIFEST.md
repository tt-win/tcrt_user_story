# Self-hosted frontend vendor assets

Pinned third-party presentation assets served from the application origin.
Do not load these libraries from CDN at runtime.

| Package | Version | Source | Local path |
|---|---|---|---|
| Bootstrap | 5.3.0 | https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/ | `bootstrap/` |
| Font Awesome Free | 6.4.0 | https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/ | `fontawesome/` |
| pako | 2.1.0 | https://cdn.jsdelivr.net/npm/pako@2.1.0/ | `pako/` |
| Noto Sans | wght 400/500/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans/` |
| Noto Sans TC | wght 400/500/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans-tc/` |
| Noto Sans Mono | wght 400/600/700 | Google Fonts CSS API → fonts.gstatic.com woff2 | `fonts/noto-sans-mono/` |

Font faces are declared in `fonts/fonts.css` with `font-display: swap`.
Measured total woff2 size (2026-07-30): ~4.72 MiB (Noto Sans TC alone ~4.2 MiB across unicode-range slices). Static subsetting deferred unless size becomes unacceptable.

## Upgrade steps

1. Download the new pinned version into the matching directory.
2. Update this manifest (version + source URL).
3. Point `app/templates/base.html` (and any other templates) at the new files if names change.
4. For fonts: re-fetch Google Fonts CSS with a browser User-Agent, download referenced woff2 files, rewrite `src` URLs to `/static/vendor/fonts/...`, and regenerate `fonts/fonts.css`.
5. Run `uv run pytest app/testsuite/test_component_spec.py -q` and browser QA offline.
