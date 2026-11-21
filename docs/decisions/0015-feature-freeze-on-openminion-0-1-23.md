# 0015. Feature freeze on openminion 0.1.23, final measurements taken early

Date: 2026-11-21 · Status: accepted

## Context

The plan was to upgrade OpenMinion once, to the newest release, just before the feature freeze
(2026-12-05 00:00 UTC), then repeat the tests and the live measurements on that version. On
2026-11-21 the newest release on PyPI is 0.1.23, the version this project has pinned since its
first commit. Waiting for a release that may not come would leave the final measurements to the
last days before the freeze, when there is no time left to report a failure properly.

## Decision

- Keep `openminion==0.1.23`. The upgrade step is recorded as "no newer release" in `RELEASE.md`
  (`## Upgrade`), with the date the index was checked.
- Take the final measurements now, on 0.1.23: the offline suite, one live read-only sweep (H1),
  the second and last test-set run of the label agreement (H2), and the three repro scripts.
  Results are in `docs/TEST-RESULTS.md` under "Feature freeze measurement".
- From this point `src/` changes are fixes only. No new features before the freeze date.

## Consequences

- The published numbers describe the version a judge installs from `uv.lock`.
- The H2 test set has now been read twice; `max_test_runs = 2` refuses a third run.
- If OpenMinion ships a newer release before the freeze date, this project does not follow it.
  The findings in `repro/` are stated for 0.1.23.

## Rollback

If a newer release must be adopted before 2026-12-05: raise the pin in `pyproject.toml`, run
`uv lock`, the offline suite and the three repro scripts, record what changed in `RELEASE.md`
`## Upgrade`, and mark this ADR superseded. The H1 sweep can be repeated; the H2 test set cannot.
