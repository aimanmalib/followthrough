# 0013. The digest as one self-contained HTML page

Date: 2026-11-18 · Status: accepted

## Context

Product requirement 4.10 asks for `digest.html` next to `digest.md` and `digest.json`, in the language
chosen with `--lang`, and requirement R4 asks that it renders in Chromium and in WebKit on an iPhone 13.
The same page will later be the public demo page for the synthetic sandbox sweep, so it must work as a
plain static file with no server, and it must not carry any text from the threads it describes.

## Decision

- `page.py` renders the page from the digest dict and the metrics dict that the sweep already builds;
  the CLI writes it as `policy.toml [digest] html_file` in the dated output folder. Nothing new is read or
  computed for the page.
- Layout is `src/followthrough/templates/digest.html` (`string.Template`), styles are
  `templates/digest.css`, inlined into the page. Every colour is a CSS custom property in the two `:root`
  blocks (light and dark through `prefers-color-scheme`); a test fails if a colour appears outside them.
- Every word comes from `locales/{en,ms}.toml` (`[page]`, plus the existing `[digest]`, `[actions]` and
  `[reasons]` keys), and the `<html lang>` attribute follows `--lang`. One page per run, in one language.
- The page has no scripts, no images, no external fonts or style sheets, and no links: system font stacks
  only, so it renders offline and on GitHub Pages without third-party requests. Thread numbers are not
  linked, because the sandbox repository is private and a link would be a broken anchor on a public page.
- Every value from the digest is HTML-escaped; the one piece of markup inside a locale sentence (the
  `<time>` element) is put back after the sentence is escaped.
- No animation, no `backdrop-filter`, no fixed header: the page is a document, and these are the effects
  that crash or mis-render in mobile WebKit.
- `scripts/check_page.py` (Playwright, not a project dependency) renders each page in Chromium at 320 px
  and 1280 px and in WebKit as an iPhone 13 and at 320 px, light and dark, at device scale 3, and fails on
  sideways scroll, any element past the right edge, console errors, or text below WCAG AA contrast.

## Consequences

- The page is as private as the digest: numbers, dates, counts and our own sentences.
- A second language needs a second run (`--lang ms`); the page has no language switch, so it cannot point
  at a file that was not written.
- Browser checks run on the host, not in the offline CI; CI covers the page through `tests/test_page.py`.

## Rollback

Remove `page.py`, `templates/`, `scripts/check_page.py`, `tests/test_page.py`, the `[page]` locale
sections, `html_file` in `config/policy.toml` and the two `page.` lines in `cli.py`; `digest.md` and
`digest.json` are unchanged by this decision.
