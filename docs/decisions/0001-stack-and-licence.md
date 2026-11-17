# 0001. Stack and licence

Date: 2026-11-17 · Status: accepted

## Context

Follow-Through must use the OpenMinion SDK as a meaningful part of its runtime. OpenMinion ships a new
release every two to three days, so an unpinned dependency could change behaviour between test runs.
The project may be offered to a community repository that requires the MIT licence.

## Decision

- Python 3.12, managed with `uv`; `uv.lock` is committed and CI installs with `uv sync --frozen`.
- `openminion==0.1.23`, pinned exactly. It is upgraded once, at feature freeze, to the latest release;
  the upgrade and anything it breaks are recorded in `RELEASE.md`.
- No other runtime dependencies. HTTP uses `urllib.request`, TOML uses `tomllib`, and Pydantic comes with
  OpenMinion. `pytest` is a development dependency only.
- Every value that may change (windows, labels, models, prices, budget, allow-list) lives in `config/*.toml`;
  every user-facing string lives in `locales/en.toml` and `locales/ms.toml` with identical keys.
- Each module in `src/` stays under 400 lines.
- Licence: MIT.

## Consequences

Tests run offline and reproducibly from the lock file. Upgrading OpenMinion is a deliberate, recorded
step rather than a side effect of a fresh install.

## Rollback

To change the pin, edit `openminion==<version>` in `pyproject.toml`, run `uv lock`, and rerun the test
suite; revert both files to go back. To change the licence before any outside contribution, replace
`LICENSE` and the `license` field in `pyproject.toml` in one commit.
