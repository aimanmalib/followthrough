# 0004. Reader agents on OpenMinion, and the spend budget

Date: 2026-11-17 · Status: accepted

## Context

Each changed thread has to be read by a model that says who is waiting on whom. The reading must
come back as a typed `ThreadState`, must never reach the network on its own, and must stay inside a
hard spend limit. The first real runs on OpenMinion 0.1.23 showed five behaviours that shape the
design (measured on the synthetic fixture; numbers in `docs/TEST-RESULTS.md`):

1. `subagent()` creates the parent's runtime lazily. Four worker threads calling it at once
   created several runtimes that migrated the same SQLite file and failed with
   `duplicate column name: canonical_event_id`.
2. Memory scopes accept only `[A-Za-z0-9._:-]`, so the session id `sweep:<owner>/<repo>:<date>`
   from the product requirements logs `invalid scope` and skips the memory context.
3. `output_type` is checked only against the final reply text. The schema is not sent to the model,
   and the reply passes through several internal steps (entry, freshness check, act, judge,
   reflect: 5 to 10 model calls per turn). Early runs returned objects with missing or invented keys.
4. Tool arguments typed as `datetime` fail inside the runtime with
   `Object of type datetime is not JSON serializable`.
5. Every reply is prefixed with the default agent's name (`reader: {...}`); `output_type`
   recovers the JSON object from it.

## Decision

- `agents.py` builds one `APIRuntime` up front and hands it to the parent `Agent`; each thread
  gets its own `subagent(..., output_type=ThreadState)` with two tools, at most `max_concurrency`
  at once (`config/models.toml`).
- `get_thread(number)` is `@tool(min_scope="READ_ONLY", idempotent=True)` and serves the thread
  from the snapshot already in memory: roles, `created_at` and text only, no logins, no network.
- `submit_reading(...)` is a second read-only tool whose arguments are the `ThreadState` fields,
  so the schema reaches the model as a tool definition. Times are strings (behaviour 4). The
  final reply validated by `output_type` is used first; the tool arguments are used only when it
  fails, and each reading records its source so the report counts both.
- Every reading, from either source, goes through the quote guard of ADR 0003.
- Session ids are `sweep:<owner>__<repo>:<YYYYMMDD>`, and each thread runs in
  `<that>:<number>` so no reader sees another thread's transcript.
- `agents.json` is generated from `config/models.toml` into `state/` with the key read from
  `ANTHROPIC_API_KEY` at run time (never written). Prompts live in `config/prompts.toml`.
- `spend.py`: before a turn the sweep holds a reserve (`turn_reserve_usd`, raised to the largest
  turn seen); if the reserve could cross `usd_max_per_sweep` or `usd_max_total`, the turn is not
  started. After the turn the real cost from `config/prices.toml` replaces the hold. Zero-token
  telemetry is estimated as characters ÷ `chars_per_token_estimate` per model call and marked
  `estimated`. A turn that raised is booked at its full reserve, because it may have been billed.
- The built-in `anthropic` adapter worked with `claude-haiku-5-5`, so the provider fallbacks in
  `config/models.toml` are not used.

## Rollback

Drop `submit_reading` from the subagent's tools and the `_from_tool` branch to rely on
`output_type` alone. Set `max_concurrency = 1` if parallel turns on one runtime misbehave. To return
to the product-requirements session format, change `session_id()` in `agents.py` (memory context
will then be skipped as in behaviour 2).
