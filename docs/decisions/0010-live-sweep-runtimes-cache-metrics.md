# 0010. Live sweep: one runtime per reader worker, a reading cache, and `metrics.json`

Date: 2026-11-18 · Status: accepted

## Context

The read-only live sweep of `openminion/openminion` must finish in 20 minutes and USD 1.00
(requirement H1) and report what the quote guard rejected (H6). Measured before this change, on
openminion 0.1.23 and the live snapshot (108 open threads, 225 GET requests, 125 s):

- Eight reader turns with `max_concurrency = 8` on one shared runtime took 305 s, about as long as
  running them one after another. `Agent.run` enters `ToolRegistry.temporary_registration_scope()`
  for the whole turn when the agent has decorated tools, so turns that share a runtime queue on
  that lock (`openminion/api/agent.py`, `modules/tool/registry/__init__.py`).
- A reader turn costs about USD 0.010 to 0.012 (5 to 6 model calls of 30,000 to 40,000 input tokens
  in total). Reading all 108 threads from scratch costs more than the USD 1.00 sweep limit.

## Decision

- `agents.read_threads` gives each worker its own runtime and its own OpenMinion home: worker 0
  uses `state/agents.json`, worker i a copy under `state/workers/w<i>/` whose only change is its
  SQLite file. The runtimes are built one after another before any turn (building them lazily from
  several threads breaks the shared SQLite migration, ADR 0004). Measured on the live sweep: eight
  runtimes on one SQLite file crashed the sweep with "database is locked" after 16 turns, so a
  storage error now fails that one reading instead of the whole sweep.
- `max_concurrency = 4` and a reader turn timeout of 240 s (`[profiles.reader] timeout_s` in
  `config/models.toml`). On a busy host (load average 28 to 43 on 16 cores) most turns with 8 or 4
  workers ran past OpenMinion's default turn timeout of 90 s; the same turn alone took 27 s.
- Time limit next to the money limit: no reader turn starts later than `[measure] max_minutes`
  minus the reader timeout after the sweep began (16 minutes with the shipped values), so a sweep
  ends inside 20 minutes. The digest then says the sweep stopped, exactly as for the USD limit.
- Reading cache (`readings.py`, `[readings]` in `config/policy.toml`, file under `state/`): a thread
  goes to the model only when its state hash (updated_at, comment count, labels; the same hash as
  the reminder ledger) changed since its last reading that passed the quote guard. Unchanged threads
  reuse that reading; the guard checks it again against the new snapshot and the rules run with the
  new date, so waiting windows keep moving. Failed and rejected readings are not cached, so they are
  read again. A first sweep that stops at the USD limit is finished by the next sweep.
- Every sweep writes `metrics.json` (`measure.py`, `[measure]` in `config/ops.toml`) next to the
  digest: wall time, USD, GitHub requests by method and status, readings by source, guard rejections
  (overall and fresh readings only) and the limit checks. It holds counts only, so it is the file
  that may be published for a third-party repository. The per-request method log `http-log.json`
  (method, API path, status) stays in the untracked output folder.

## Consequences

- The cached readings hold quotes from the threads; they live under `state/` and are never tracked.
- A day with many changed threads can still hit the USD or time limit; the digest says the sweep
  stopped and the next run reads the threads that still lack a good reading.
- Measured on a loaded host (`docs/TEST-RESULTS.md`, Live sweep): one run reads about 20 to 35
  threads, so a first sweep of `openminion/openminion` (108 open threads) needs several runs. One
  run's process ended 6 minutes after its metrics were written; the start limit bounds when turns
  begin, not when the process exits. Both stay listed as known limits until measured otherwise.

## Rollback

Set `[readings] enabled = false` to read every thread on every sweep. Set `max_concurrency = 1` to
use a single runtime and home, turn by turn. Remove `timeout_s` to use OpenMinion's default.
Revert `measure.py` and its call in `cli.py` to stop writing
`metrics.json`; nothing else reads it.
