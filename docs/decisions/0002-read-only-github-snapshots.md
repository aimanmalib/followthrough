# 0002. Read-only GitHub access and the snapshot format

Date: 2026-11-17 · Status: accepted

## Context

Follow-Through is measured on a third-party repository that it must never write to. The model must
also never see the GitHub token, and later steps (rules, the reader agent, the quote guard) need a
stable, offline copy of each thread so tests and replays do not depend on the network.

## Decision

- `src/followthrough/github.py` is the only GitHub reader. `GitHub.request` refuses every method
  except GET before a request object is built, and the request object itself is always created
  with GET. The method, path and status of every call are kept in `GitHub.requests` so a sweep can
  report "0 non-GET requests" from data rather than from a claim.
- The token is read from the environment variable named in `config/policy.toml`
  (`github.token_env`). It is held in memory only: not in the ETag cache, the snapshot, `repr()`,
  logs or prompts.
- Conditional requests: the ETag of each URL is stored in `state/cache/etag.json`; a 304 reply is
  served from that cache.
- Endpoints: open issues and pull requests, comments, timeline, releases, compare (all from the
  product requirements), plus `GET /pulls/{n}` for pull requests cross-referenced from threads that
  carry the awaiting-release label. The timeline alone does not give the merge commit, and the
  merge commit is what `compare` needs to tell whether a fix is in the latest release.
- A snapshot is plain JSON: repo, time taken, latest published release, and per thread the
  number, title, labels, author (login, association, maintainer flag), dates, body, comments and
  linked pull requests. Snapshots are written to `state/snapshots/<owner>__<repo>/<UTC time>.json`,
  which git ignores, so third-party text is never committed.
- `fixtures/sandbox-repo.json` uses the same shape with invented people and text, plus a
  `fixture` block (clock, expected action per thread, one quote that does not exist in its thread).

## Consequences

Paging has a hard stop (`github.max_pages`). A thread with many linked pull requests costs one
extra request per pull request, only for awaiting-release threads.

## Rollback

Delete `github.py`, `tests/test_github.py` and the `etag_cache`, `timeout_s`, `max_pages`,
`token_env` keys in `config/policy.toml` (and their entries in `config.REQUIRED`). The snapshot
format has `schema: 1`; a later change bumps that number instead of editing old snapshots.
