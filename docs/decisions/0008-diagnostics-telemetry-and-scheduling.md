# 0008. Diagnostics, per-turn telemetry and the scheduling proof

Date: 2026-11-18 · Status: accepted

## Context

The product requirement asks for three operational pieces: telemetry for every model turn in
`out/<date>/telemetry.json`, a saved `openminion doctor --check-turn --json`, and
`followthrough schedule --daily HH:MM` that creates an OpenMinion cron task and runs it once as proof,
with no daemon left running afterwards. Production scheduling is a system cron line that the
maintainer installs; Follow-Through installs nothing.

Measured on openminion 0.1.23:

- `cron run` queues a run; only a running daemon executes it. Without the daemon the run stays
  `queued` and the command still reports `ok`. Pausing the task cancels the queued run.
- There is no `cron delete` in the CLI; `cron pause` is the closest.
- The daemon port (`runtime.ipc_port`, default 18789) is the same for every OpenMinion home. On a
  host where another OpenMinion daemon already listens there, `daemon start` fails with
  "endpoint identity does not match".
- A run that finishes reports delivery `failed` / `cron_delivery_failed` when the task has no
  delivery target. The run itself is `finished`.
- `doctor --check-turn` with the built-in `echo` provider runs a real agent turn with no model key
  and no network call.

## Decision

- `omhome.py`: a throw-away OpenMinion home in a temporary folder with its own config (`echo`
  provider, profile from `config/ops.toml`), its own database and a free daemon port. Model and
  GitHub tokens are removed from the child environment; any secret value that still appears in
  captured output is replaced with `[redacted]`. The folder is deleted on exit.
- `followthrough doctor`: `openminion doctor --json` on the project's generated config (no turn,
  nothing spent; the model key is passed through so the key check is real), then
  `doctor --check-turn --json` in the throw-away home. Both go to `out/<date>/doctor.json`.
- `followthrough schedule --daily HH:MM [--repo owner/name]`: in the throw-away home, `cron create`
  (5-field cron, time zone from config), `daemon start`, one `cron run`, poll `cron show` until the run
  leaves the pending states, then always `cron pause` and `daemon stop`. If the daemon process is still
  alive after stop it is sent SIGTERM. The home is deleted. The report goes to
  `out/<date>/schedule.json` and the command prints the system cron line from config.
  The proof passes only when the run is `finished`, the task is paused, no daemon is alive and the
  home is gone. The delivery failure above is recorded but does not fail the proof.
- The proof task runs on the `echo` provider: the scheduled turn cannot run a sweep (it has no tool for
  that), so a real model turn would cost money and prove nothing more about the scheduler.
- `telemetry.py`: one record per model turn (reader and drafter): model, tokens, USD, estimated or
  not, which path produced the result, problem codes, and the numeric OpenMinion run stats listed in
  `config/ops.toml` (`llm_calls`, `tool_calls`, tokens, `duration_ms`). No thread text, no model reply.
  Every `sweep` writes it next to `digest.json`; a sweep from saved readings has 0 turns.

## Consequences

- Nothing persistent is created by `doctor` or `schedule`: no task, no daemon, no crontab entry.
- The daily schedule a maintainer actually uses is plain cron, so it keeps working without the
  OpenMinion daemon.

## Rollback

Remove the `doctor` and `schedule` subcommands from `cli.py`, delete `omhome.py`, `schedule.py` and
the `[isolated]`, `[doctor]` and `[schedule]` tables of `config/ops.toml`. To drop telemetry, remove the
`telemetry.write` call in `cli.sweep` and `telemetry.py`; the digest is unaffected.
