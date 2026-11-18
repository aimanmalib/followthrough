# What we learned

Feedback on OpenMinion from building Follow-Through on 0.1.23. Each point names its evidence in this
repository; measured numbers are in `docs/TEST-RESULTS.md`, the building blocks and their gaps in
`BUILDING_BLOCKS.md`, scripts in `repro/`.

## What worked well

- **`@tool` + approval callback is a real gate.** The callback receives the exact tool arguments, `deny`
  means no call, and a missing callback pauses the run. Follow-Through's only write to GitHub sits behind
  it (`tests/test_post.py`, Sandbox approval demo).
- **`base_url` on the built-in provider made offline testing cheap.** Pointing it at a local server lets
  the test suite run every agent path without a key, and lets a whole sweep be recorded and replayed
  (Key-free demo).
- **`openminion doctor --check-turn --json` with the `echo` provider** checks a home end to end without a
  key or spend; the JSON summary is easy to keep as evidence (Diagnostics).
- **`upsert_record` in memory** keeps one live record per key, which is the right shape for "remind once".

## What cost the most time, and what would help

1. **Typed output is checked late.** `output_type` validates only the final reply text, after several
   internal steps (entry, freshness check, act, judge, reflect); the schema is not sent to the model.
   A typed tool call that carries the schema fixed it for us (Fixture run, runs 1–4).
   *Suggestion:* send the `output_type` schema to the model, or offer a built-in "submit result" tool.
2. **Parallel children on one runtime are serial.** With decorated tools, `Agent.run` holds the
   registry lock for the whole turn; one runtime per worker cut a live sweep from 305 s to 94.5 s
   (Live sweep; `repro/shared-runtime-turns-run-one-at-a-time`).
   *Suggestion:* hold the lock for registration and unregistration only, or document "one runtime per
   thread" next to `subagent()`.
3. **Concurrent start-up races on SQLite migrations.** Several runtimes built at once on one file
   failed with `duplicate column name: canonical_event_id` (ADR 0004); concurrent first turns on one
   fresh runtime failed with `UNIQUE constraint failed: migrations.version`. Building runtimes one after
   another and one warm-up turn avoid both.
   *Suggestion:* migrate under a lock when the runtime is built, not on first turn.
4. **Unsupported tool argument types fail at run time.** A `datetime` parameter ends the turn before the
   handler runs (`repro/tool-datetime-argument`). *Suggestion:* serialise with a `default=` for dates, or
   reject the type when the function is decorated.
5. **The freshness classifier can swallow a tool request.** A plain request whose payload contains dates
   was answered by the runtime itself with 0 tool calls; an explicit "Call <tool> …" message avoids it
   (Sandbox approval demo). *Suggestion:* skip the freshness check when the turn's tools can answer it,
   or make it a per-agent setting.
6. **Scheduling needs a daemon, and the CLI does not say so.** `cron run` reports ok and `queued` with no
   daemon, and the run never starts (`repro/cron-run-ok-without-daemon`). Every home also defaults to the
   same daemon port, so a second home on one host needs its own `runtime.ipc_port` (Scheduling).
   *Suggestion:* warn in `cron run` when no daemon answers; pick a free port or name the port clash.
7. **Memory cannot answer "was this exact key reminded, and is it still valid?"** No exact lookup by key,
   `list` returns expired records, and namespace ids reject `/` (Reminder ledger; upstream #677 covers
   expiry). Follow-Through uses its own SQLite ledger for that.
8. **Requests are not stable across runs.** Turn and capture ids, remaining time and the working folder
   are written into prompts, so a recorder must normalise them (Key-free demo). *Suggestion:* a
   "deterministic prompts" switch for tests.

## Not measured

The Cortensor Portal provider has not been tried. All results
above use the built-in `anthropic` provider or the key-free `echo` provider.
