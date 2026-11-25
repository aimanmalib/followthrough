# 0016. Public demo page on GitHub Pages, built by a workflow

Date: 2026-11-25 · Status: accepted

## Context

The repository is now public. Judges should be able to see the digest without installing anything.
The digest page (`digest.html`, ADR 0013) is one self-contained file per language with no scripts and
no outside links, and the fixture sweep that produces it is offline and uses a fixed clock, so the
same commit always renders the same page.

## Decision

- `.github/workflows/pages.yml` runs on every push to `main` (and by hand). It installs the locked
  environment, runs `followthrough sweep --fixture` in English and in Malay, and publishes the two
  `digest.html` files as `/` and `/ms/` with the official `upload-pages-artifact` and `deploy-pages`
  actions. Pages is set to build from a workflow, not from a `gh-pages` branch.
- `scripts/build_pages.py` adds to each published copy what a shared link needs and a local digest
  does not: a description, Open Graph and Twitter card tags (the image is the README screenshot of the
  same page), language alternates and a tab icon. The site URL, paths and files are in
  `config/pages.toml`; the description is in `locales/*.toml`. The page body is not changed.
- The page shows the synthetic sample repository only. No live sweep, no snapshot and no draft from a
  third-party repository is published; those stay out of git.
- The workflow uses no secrets and has only the `pages: write` and `id-token: write` permissions the
  deploy action needs.

A `gh-pages` branch would work too, but it means a second history with generated files in it, and a
stale page whenever someone forgets to rebuild it. The workflow rebuilds from the code on each push.

## Consequences

- The page always matches `main`. A change that breaks the fixture sweep also fails the Pages run.
- `tests/test_pages_workflow.py` checks that the workflow stays offline in the sense that matters:
  fixture sweep only, no secrets, both languages.

## Rollback

Delete `.github/workflows/pages.yml`, `scripts/build_pages.py` and `config/pages.toml` and turn Pages off in the repository settings
(`gh api -X DELETE repos/<owner>/<repo>/pages`). Nothing else depends on the page; the README links
to it and can point back to the one-command demo.
