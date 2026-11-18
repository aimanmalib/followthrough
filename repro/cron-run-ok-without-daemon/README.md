# `cron run` reports ok and `queued` without a daemon; the run never starts

**Version:** openminion 0.1.23 · Python 3.12 · Linux

## Steps

1. In a fresh home (key-free `echo` provider, its own daemon port), `openminion cron create
   --instruction "repro ping" --cron "0 6 * * *" --tz UTC --name repro --json`.
2. With no daemon running, `openminion cron run --job-id <id> --json`.
3. Poll `openminion cron show <id> --json` for 30 s.

`uv run python repro/cron-run-ok-without-daemon/repro.py` does this and pauses the task afterwards.

## Expected

Either the run executes, or
`cron run` says that the run is only queued and needs `openminion daemon start`.

## Actual

`cron run` exits 0 with `ok: true` and state `queued`, and the run is still `queued` 30 s later.
Nothing in the answer says that a daemon is needed. The numbers from the last run are in
`docs/TEST-RESULTS.md`. With a daemon started on the home's own port the same run finishes in about
1 s (`docs/TEST-RESULTS.md`, Scheduling).

## Safe evidence

No key (the `echo` provider sends nothing anywhere), a free local port so no other OpenMinion on the
host is reached, model and GitHub tokens removed from the child environment, the task paused and the
temporary home deleted on exit. No daemon is started.

## In Follow-Through

The scheduling proof starts a daemon on the home's own port, waits for the run to leave the queue,
and fails the proof when it never does (`src/followthrough/schedule.py`, `schedule_proof`; ADR 0008).
