# Building blocks

Which OpenMinion building blocks Follow-Through uses, what worked, what did not, and the evidence.
Measured on the pinned version (openminion 0.1.23).

| Block | Where | Works | Gap | Evidence | Upstream |
|---|---|---|---|---|---|
| Memory records (`MemoryService`, SQLite store) | not used; `src/followthrough/ledger.py` instead | `upsert_record` keeps one live record per (scope, type, key) | no exact lookup by key; `list` returns records past `expires_at`; namespace ids reject `/` | `tests/test_memory_gap.py`, ADR 0007 | #677 (open; expiry part) |
| Scheduler (`openminion cron create/run/pause`) | `src/followthrough/schedule.py:116`, `:130`, `:144` | `cron create --cron "30 6 * * *" --tz UTC` stores the task with the right `next_due_at`; with the daemon up, `cron run` finishes in about 1 s | `cron run` only queues: without a running daemon the run stays `queued` and the CLI still reports `ok`; the CLI has no `cron delete` (pause is the closest); a finished run reports `cron_delivery_failed` ("FOREIGN KEY constraint failed") when the task has no delivery target | `tests/test_schedule.py`, `docs/TEST-RESULTS.md` Scheduling, ADR 0008 | not yet searched |
| Daemon (`openminion daemon start/stop`) | `src/followthrough/schedule.py:126`, `src/followthrough/omhome.py:116` | start/stop by pid file in the data root; stop leaves no process | default port 18789 is shared by every OpenMinion home on a host: a second home's `daemon start` finds another daemon on that port and fails ("endpoint identity does not match"); each home needs its own `runtime.ipc_port` | `docs/TEST-RESULTS.md` Scheduling, ADR 0008 | not yet searched |
| Diagnostics (`openminion doctor --check-turn --json`) | `src/followthrough/schedule.py:60` | JSON summary + per-check status; the turn check passes with the key-free echo provider | none found | `tests/test_schedule.py`, `docs/TEST-RESULTS.md` Diagnostics | n/a |
