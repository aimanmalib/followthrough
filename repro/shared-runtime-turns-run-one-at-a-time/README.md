# Agents with decorated tools that share one `APIRuntime` run one turn at a time

**Version:** openminion 0.1.23 · Python 3.12 · Linux

## Steps

1. Build one `APIRuntime` and a parent `Agent` on it.
2. Create four `subagent(parent, ...)` children, each with one `@tool`, and run them from four
   threads, each with its own `session_id`.
3. Control: the same four children with no tools.

`uv run python repro/shared-runtime-turns-run-one-at-a-time/repro.py` does both against a local
stand-in for the Messages API that answers every request after 0.5 s and records how many requests
were in flight at once. One warm-up turn runs first (see the note below).

## Expected

The four turns overlap, as the control does: `subagent()` gives each child its own session, and the
SDK's parallel examples run children from threads.

## Actual

The control has up to four model requests in flight at once; with a decorated tool never more than
one. `Agent._run_once` (`openminion/api/agent.py:314`, `:318`) enters
`ToolRegistry.temporary_registration_scope()` (`openminion/modules/tool/registry/__init__.py:93`)
when the agent has decorated tools or handoffs, and keeps the registry lock until
`runtime.run_turn(...)` (`api/agent.py:347`) returns, model calls included. Other threads wait
on that lock for the whole turn. The numbers from the last run are in `docs/TEST-RESULTS.md`.

Related: #371 (closed) added the lock so a shared-runtime handoff does not deadlock; this report is
about independent parallel children, which then wait for each other. Registration and
unregistration need the lock; the turn itself may not.

Note: concurrent *first* turns on a fresh runtime failed here with
`sqlite3.IntegrityError: UNIQUE constraint failed: migrations.version`; one sequential turn first
avoids that, so the script warms up. That race is not part of this report.

## Safe evidence

No key, no network beyond 127.0.0.1; a temporary home deleted on exit; the tool is never called.

## In Follow-Through

Each reader worker gets its own `APIRuntime` and its own SQLite file
(`src/followthrough/agents.py`, `worker_configs` and `read_threads`; ADR 0010). Measured on the
live sweep: 8 threads in 305 s on one shared runtime, 94.5 s with one runtime per worker.
