# 0007. Reminder ledger in SQLite, not OpenMinion memory

Date: 2026-11-18 · Status: accepted

## Context

A daily sweep must not draft the same reminder every day (H3): a second sweep with no change drafts
nothing, and when exactly one thread changes, exactly one new draft appears. The product requirement
asks for an OpenMinion memory record per thread in the namespace `followthrough/<owner>/<repo>`
holding {state hash, last action, drafted at}, expiring after 30 days, with a SQLite fallback if
memory cannot look a record up by exact key or does not honour expiry.

Measured on openminion 0.1.23 (`tests/test_memory_gap.py` keeps these as tests):

- Namespace ids and scopes reject `/`, so `followthrough/<owner>/<repo>` cannot be a memory namespace
  as written (`project:followthrough:<owner>:<repo>` works).
- There is no lookup by key: `ListQueryOptions` has no key filter, and `search` with the full key
  as the query also returns other keys.
- `list` returns records whose `expires_at` has passed, with or without `valid_at` / `as_of`.
- `upsert_record` on (scope, type, key) does keep one live record per key.

So memory could store the rows, but our code would have to list the whole scope and filter key and
expiry itself, which is SQLite with extra steps and more moving parts.

## Decision

- `ledger.py`: SQLite at `config/policy.toml ledger.path` (`state/ledger.db`, never committed), one
  row per (namespace, number) with namespace `followthrough/<owner>/<repo>`: state hash, action,
  drafted_at, sweep session id. No thread text is stored.
- State hash = first 16 hex of SHA-256 over updated_at, comment count and sorted labels.
- `Ledger.verdict` allows a draft when there is no row (`new`), the hash changed (`changed`), the
  action changed (`action_changed`) or the row is at least `ledger.expiry_days` old (`expired`);
  otherwise `unchanged` and the thread is skipped.
- `sweep.draft_new` asks the ledger first, drafts only what it allows, and records a row only for a
  draft that was actually saved; a draft that failed its checks is retried on the next sweep.
- `followthrough sweep --draft` runs this step; the digest JSON gets `drafts.ledger` (count per
  verdict), `drafts.saved` and `drafts.not_saved`.
- The gap is listed in `BUILDING_BLOCKS.md`. The expiry part is the existing upstream issue #677
  (open: expired records stay retrievable until a manual `memory gc`), referenced, not filed again.

## Consequences

- Ledger behaviour is independent of the memory module; an OpenMinion upgrade cannot silently start
  re-sending reminders.
- If a later OpenMinion release adds exact key lookup and expiry, `tests/test_memory_gap.py` fails
  on upgrade and points here.

## Rollback

Drop the `--draft` flag and `ledger.py`, and remove `ledger.path` from `config/policy.toml`.
Drafting then has to be run per thread by hand, as before this change; deleting `state/ledger.db`
alone resets all reminders (every draft-needing thread is drafted again on the next sweep).
