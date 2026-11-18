# Release notes

## v1.0.0 (18 November 2026)

First tagged release of Follow-Through, built for Cortensor Hackathon #5 on the OpenMinion SDK 0.1.23 (pinned).

Follow-Through reads the issue and pull request threads that changed in a repository, works out who is waiting
on whom, and drafts a neutral follow-up that a person approves before anything is posted. Every number below is
from [`docs/TEST-RESULTS.md`](docs/TEST-RESULTS.md), which also lists every failure.

### What is in it

- **Read-only GitHub snapshots.** `GET` requests only, with an ETag cache. Any other method fails before the network.
- **One reader subagent per changed thread**, typed output, and a quote check: a date the model relies on must be
  quoted word for word from a real comment, or the thread is counted as unclear.
- **Deterministic follow-up rules** from `config/policy.toml`: follow-up due, take-over allowed, maintainer reply
  pending, ready to verify, no action. The clock can be set with `--now`.
- **Digest** in Markdown, JSON and one self-contained HTML page, in English or Malay.
- **Drafts** of up to 120 words that follow the repository's contributing guide.
- **One write path**, `followthrough post`: stop file, then allow-list, then human approval of the exact body.
- **Reminder ledger:** no second draft until a thread changes.
- `followthrough doctor`, per-turn telemetry, and `followthrough schedule` (a cron proof with no daemon left).
- `followthrough agree`: agreement between the reader and a repository's status labels.
- **Key-free demo:** `demo/run.sh` replays recorded model answers in Docker with no network. Guide:
  [`demo/README.md`](demo/README.md).
- `repro/`: three key-free reproduction scripts for OpenMinion findings.

### Measured

- Approval gate on the project's sandbox repository: `deny` posted 0 comments, `allow_once` posted exactly 1, a stop
  file ended the run with exit code 5.
- Read-only live sweeps of `openminion/openminion`: 225 of 225 GitHub requests per snapshot were `GET`, 0 writes, every
  run under USD 1.00.
- Key-free replay: 83 recorded model exchanges answered, 0 missed.
- Digest page: 24 of 24 browser checks passed in Chromium and WebKit (iPhone 13), light and dark.

### Not met, stated plainly

- A live sweep of all 108 open OpenMinion threads did not finish within 20 minutes on the build host.
- Label agreement was 0.171 after the quote check (0.293 as read), against a target of 0.80.
- The three OpenMinion findings are drafted, not filed upstream. No fix pull request exists.
- OpenMinion is pinned to 0.1.23. The upgrade to the newest SDK release before the feature freeze is still to come
  and will be recorded here.

### Install

```sh
git clone https://github.com/aimanmalib/followthrough && cd followthrough
demo/run.sh        # Docker only, no key
uv sync && uv run followthrough --help
```
