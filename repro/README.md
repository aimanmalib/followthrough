# Reproductions

Each folder holds one OpenMinion finding from building Follow-Through: steps, expected and actual
behaviour, a script that shows it, and why the script is safe to run. All scripts:

- run on the pinned version (`openminion==0.1.23`) from the repository root with `uv run python repro/<folder>/repro.py`;
- need no model key and no GitHub token, and reach nothing but `127.0.0.1` (a local stand-in for the
  Messages API in `fake_messages.py`, or the key-free `echo` provider);
- work in a temporary OpenMinion home that is deleted on exit, and start no process that outlives them;
- exit 0 while the finding is still there, 1 once it is fixed upstream, 2 when the control case fails.

| Folder | Finding | Upstream |
|---|---|---|
| [`tool-datetime-argument`](tool-datetime-argument/README.md) | a `@tool` parameter typed `datetime` ends the turn with `RUNTIME_ERROR`; the handler never runs | not filed (draft) |
| [`shared-runtime-turns-run-one-at-a-time`](shared-runtime-turns-run-one-at-a-time/README.md) | agents with decorated tools on one `APIRuntime` run their turns one at a time | not filed (related: #371, closed) |
| [`cron-run-ok-without-daemon`](cron-run-ok-without-daemon/README.md) | `cron run` reports ok and `queued` without a daemon; the run never starts | not filed (draft) |

Measured results are in `docs/TEST-RESULTS.md` (OpenMinion findings).
