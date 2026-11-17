# 0003. Thread state, quote guard and follow-up rules

Date: 2026-11-17 · Status: accepted

## Context

The reader model says who is waiting on whom in a thread. A model can invent a quote or a date, and
a reminder built on an invented quote would put words in a maintainer's mouth. The follow-up
windows come from the target repository's CONTRIBUTING guide, which asks maintainers to "state
those dates on the issue", so every action has to carry the dates it was computed from.

## Decision

- `ThreadState` (`src/followthrough/state.py`) is a strict Pydantic model (`extra="forbid"`); the
  longest quote comes from `config/policy.toml` (`guard.quote_max_chars`).
- `verify` checks a reading against the snapshot it came from. Each quote must be an exact
  substring of exactly one post; the opening post counts as a post with the thread's `created_at`.
  `open_request_at` must equal that post's `created_at` and `open_request_by` must match the
  post author's side. `last_follow_up_at` must be the time of a maintainer post. `linked_pr` must be
  a linked pull request or a `#n` mention. Every failure is recorded as a problem code; any
  problem turns `waiting_on` into `unclear`, which the rules treat as "no action".
- `rules.decide` (`src/followthrough/rules.py`) returns one action per thread. Order:
  READY_TO_VERIFY (label, merged pull request, merge commit in the latest release — all from the
  snapshot, not the model), then unclear → NO_ACTION, then an unanswered maintainer request,
  then a passed agreed date, then an unanswered contributor request, then NO_ACTION.
- Windows are whole UTC calendar days: a request made on day D is due for follow-up on
  D + `follow_up_days`, whatever the hour. Drafts state dates, not hours, and UTC days give the
  same answer on every machine.
- After a maintainer follow-up, take-over is allowed from follow-up day + `after_follow_up_days`
  unless a contributor posted since. Whether someone replied is always read from the snapshot.
- No window, label or count is written in `rules.py`; a test parses the module and fails on any
  integer literal.
- The expected reading of each synthetic thread is kept in `fixtures/sandbox-states.json`, so the
  rules are tested without a model and later steps can reuse it as canned model output.

## Rollback

The rules are pure functions over a reading and a snapshot. To change a window, edit
`config/policy.toml`. To return to hour-based windows, change `_day` and the comparisons in
`rules.py` and the boundary tests; no stored data depends on the choice.
