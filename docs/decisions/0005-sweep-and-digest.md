# 0005. Sweep pipeline, digest format and public CI

Date: 2026-11-17 · Status: accepted

## Context

The parts built so far (read-only GitHub snapshot, reader agents, quote guard, rules) need one
command that runs them in order and a report a maintainer can read. The report of a third-party
repository must not carry that repository's text, and public CI must run the whole pipeline
without a model key or network.

## Decision

- `followthrough sweep --fixture [PATH] | --live --repo owner/name` runs snapshot -> readings ->
  quote guard -> rules -> digest. `--now` sets the rules' clock (default: the fixture's own time for
  fixtures, the current time for live sweeps).
- Two readers return the same `ReadOutcome`: `model` (one OpenMinion subagent per thread, spend in
  the budget ledger) and `states` (saved readings from a file). `states` is the default for
  `--fixture` and refused for `--live`, so a live digest always comes from the model. Saved readings
  go through the same quote guard as model readings.
- The digest (`out/<YYYY-MM-DD>/digest.json` + `digest.md`) holds counts per action, then one item
  per thread: number, action, reason key, computed dates, release tag. The one-line explanation is
  our own locale text filled with those dates. No title, body or comment text is copied, so a live
  digest can be summarised in public as counts without filtering.
- Only the actions in `config/policy.toml [digest] list_actions` are listed thread by thread;
  `NO_ACTION` is counted only. Guard rejections and unread threads are counted in a footnote.
- Usage errors (missing `--repo`, `--reader states` with `--live`, missing model key) stop with exit
  code 2 before any network request. A sweep stopped by the budget still writes its digest, marked
  partial, and exits 3.
- Live digests record the HTTP request count and the number of non-GET requests (expected 0).
- `.github/workflows/ci.yml` runs on push and pull requests with read-only permissions: locked
  install, the offline test suite, and a fixture sweep in English and Malay.

## Consequences

- The digest is reproducible from a fixture and a date with no key, which the replay demo (later)
  builds on.
- The model reader is only checked against a local fake server in CI; real-model numbers come from
  recorded runs in `docs/TEST-RESULTS.md`.

## Rollback

Revert the commit that adds `sweep.py`, `digest.py` and `.github/workflows/ci.yml`; `cli.py` then
returns to the version-only entry point. The readers, guard and rules are untouched by this change.
