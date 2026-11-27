# 0017. A landing page in front of the digest, with the real digest in device frames

Date: 2026-11-27 · Status: accepted

## Context

The demo site (ADR 0016) opened straight onto the raw digest: the first thing a visitor saw was the name of the
synthetic sandbox repository and a row of counts, with no logo and no sentence saying what Follow-Through is or who it
is for. The other entries in the same hackathon open with a product page. The digest itself is good evidence and must
not change: its body is the agent's output.

## Decision

- **Two kinds of page.** The landing page is the site root (`/`, `/ms/`). The fixture digest moves to `/digest/` and
  `/ms/digest/` with its body byte for byte as the sweep wrote it; only `<head>` tags are added, as before, and its
  canonical and language links point at the new paths. Paths live in `config/pages.toml` (`paths`, `digest_paths`).
- **Text and values outside the code.** Every word on the landing page comes from `locales/en.toml` and
  `locales/ms.toml` under `[landing]` (same keys in both). Links, screenshots, the theme storage key and the asset
  list come from `config/pages.toml [landing]`. The template `docs/site/landing.html` holds no copy; a test checks it.
- **A small renderer of our own.** `scripts/build_landing.py` (standard library only) fills the template with
  `{{key}}`, `{{@context}}`, `<!--if-->` and `<!--each-->` markers and fails on an unknown key or a leftover marker.
  Adding a template engine would mean a new dependency in `uv.lock` for about a hundred lines of work.
- **Design tokens are generated, not written.** `docs/site/token.css` is generated from the shared design tokens by
  the entry kit, with `brand/identity.json` (name, accent, corner radius). The accent is the amber of the logo,
  `#E8B04A`, not a red: red already means "follow-up due" inside the digest. Text on the accent is dark (9.1:1).
  `docs/site/landing.css` uses only `var(--…)` colours; a test rejects colour literals.
- **Look.** The masthead carries the inline logo mark and the name; the hero names the product and its outcome and
  shows the real digest in a CSS browser frame and a CSS phone frame (no vendor artwork). Light and dark follow the
  system, with a switch that is remembered. Two self-hosted fonts (Figtree, Geist Mono; SIL OFL 1.1, licence in
  `docs/site/fonts/OFL.txt`). No blur, no glass, no sticky header; the only motion without a user action is the hero
  frames entering once, and it is off under `prefers-reduced-motion`.
- **robots.txt.** A GitHub project site cannot serve `/robots.txt` at the host root, and the root returns 404, so no
  crawler or link-preview bot is blocked. No placeholder `robots.txt` is published.

Browser checks (Playwright, WebKit iPhone 13, 320 px and 1440 px, light and dark) run on a developer machine, outside
pytest, because Playwright is not a project dependency; the pytest suite checks the built HTML, not a browser.

## Consequences

- Old links to `/` and `/ms/` now land on the product page, which links to the digest in its first screen.
- The hero screenshots are static files in `docs/site/shots/`; they must be retaken when the digest page changes.

## Rollback

Revert the commit that adds this ADR: `config/pages.toml` returns to `paths` only, `scripts/build_pages.py` copies the
digest to `/` and `/ms/` again, and `.github/workflows/pages.yml` expects two pages. `docs/site/`,
`scripts/build_landing.py`, `brand/identity.json` and `tests/test_landing.py` can then be deleted. The live site can
also be put back without a commit by re-running the last successful `pages` workflow run of the earlier commit.
