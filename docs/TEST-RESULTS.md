# Test results

Measured numbers only. Failures are reported as they happened.

## Fixture run (real model)

Synthetic fixture `fixtures/sandbox-repo.json` (6 invented threads, one per follow-up action, plus a
planted fake quote used only in offline tests), compared with the hand-written readings in
`fixtures/sandbox-states.json`. Script: `scripts/reader_run.py`. Provider `anthropic` (built-in
OpenMinion 0.1.23 adapter), model `claude-haiku-5-5`, 2026-11-17. USD from `config/prices.toml`
and the token counts OpenMinion reports.

| Run | Change before the run | Concurrency | Readings that validated | Rejected by quote guard | Failed (no valid reading) | Model calls | Tokens in / out | USD | Seconds |
|---|---|---|---|---|---|---|---|---|---|
| 1 | first version | 4 | 0 | 0 | 6 | not reported (all raised) | not reported | 0.120000 (booked at reserve) | not recorded |
| 2 | full JSON template in the message; one session per thread | 4 | 2 | 1 | 4 | 14 (2 turns) | 58,525 / 5,956 (2 turns) | 0.088831 | 118.8 |
| 3 | same, run one at a time | 1 | 4 | 2 | 2 | 28 (4 turns) | 113,659 / 10,599 (4 turns) | 0.056665 | 151.5 |
| 4 | typed `submit_reading` tool added | 4 | 6 | 3 | 0 | 50 | 257,758 / 20,128 | 0.035840 | 187.7 |
| 5 | prompt: ETA needs its quote; follow-up must be a maintainer post | 4 | 5 | 2 | 1 | 42 (5 turns) | 216,747 / 16,267 | 0.049808 | 160.7 |

- Failed turns raise inside OpenMinion, so their token counts are lost; each is booked at the
  per-turn reserve (USD 0.02), which overstates their cost.
- In run 4, all 6 readings came from the validated final reply (`output_type`); 0 needed the
  `submit_reading` arguments. In runs 1 to 3, failures were replies with missing keys, invented
  keys (`eta`, `follow_ups`) or a `reader:` prefix around a partial object. In run 5 the one failure
  gave `agreed_eta` as text ("next release") instead of a date.
- Guard rejections in runs 4 and 5: `last_follow_up_at` pointing at a post that is not a maintainer
  post (threads 104 and 106), and an ETA without its quote (thread 105, run 4). Rejected readings
  become `waiting_on: unclear` and are counted, as designed (ADR 0003).
- Accepted readings matched the hand-written `waiting_on` in every case (3 of 3 in both runs 4 and 5).
- One turn makes 5 to 10 model calls (purposes reported by OpenMinion: entry, freshness check,
  act ×2, judge, reflect); in run 5 a thread used 33,345 to 55,252 input tokens.
- Spend ledger after the five runs: USD 0.351144 of the USD 20.00 limit; every run stayed under
  the USD 1.00 per-sweep limit. Five single-thread debugging turns ran outside the ledger while the
  output problems were investigated: four reported 104,128 input and 10,278 output tokens
  (USD 0.015552); the fifth raised before reporting.

## Offline tests

`tests/test_agents.py` runs the same code against a local fake of the Anthropic Messages API
(127.0.0.1, no key): every fixture thread read by its own subagent with one `get_thread` call each,
the planted fake quote rejected, a prose reply counted as failed, a reading recovered from
`submit_reading`, zero-token telemetry estimated, a provider error counted, and a budget stop with
no request sent. `tests/test_spend.py` covers holds, limits across sweeps, estimates and the ledger.

## Fixture sweep (offline)

`followthrough sweep --fixture` on 2026-11-17 (saved readings, clock 2026-11-20T09:00:00Z, no key,
no network), same digest counts in `--lang en` and `--lang ms`:

| Action | Threads |
|---|---:|
| Follow-up due | 2 |
| Take-over allowed | 1 |
| Maintainer reply pending | 1 |
| Ready to verify | 1 |
| No action | 1 |

6 threads read, 0 readings rejected by the quote check, 0 threads unread; every thread got the
action the fixture expects. With the planted fake quote swapped into thread 101's reading, the
guard rejects it and the digest counts 1 rejection (thread 101 becomes "No action", reason
"unclear"). `tests/test_digest.py` (19 cases) covers these, the Malay output, the absence of any
thread text in the digest, the partial digest, and live-mode usage errors stopping before any
network request.

## Drafts (real model)

`scripts/draft_run.py` on 2026-11-17 over the synthetic fixture (saved readings, clock
2026-11-20T09:00:00Z), drafter `claude-sonnet-5-5` through the OpenMinion `anthropic` provider.
The fixture has 4 threads whose action needs a draft (2 × FOLLOW_UP_DUE, 1 × TAKEOVER_ALLOWED,
1 × READY_TO_VERIFY). A draft counts as saved only if it passes the checks (≤ 120 words, every
computed date verbatim, release tag present, no @mentions).

| Run | Drafter set-up | Saved / drafts | Failures | Words (saved) | USD |
|---|---|---:|---|---|---:|
| 1 | reply JSON only (`output_type`) | 1 / 4 | 3 × reply did not validate | 82 | 0.0719 |
| 2 | same, raw reply kept | 3 / 4 | 1 × runtime blocked the reply as an "unexecutable tool envelope" | 82, 93, 71 | 0.0617 |
| 3 | + typed `submit_draft` tool | 3 / 4 | 1 × runtime replied "could not safely update the task conditions" (no tool call) | 80, 85, 76 | 0.1116 |
| 4 | same as run 3 | 4 / 4 | none | 79, 74, 94, 69 | 0.1176 |

All saved drafts passed every check; no draft failed the checks themselves, only the reply step.
Adding the typed tool raised input tokens from about 3,300 to about 10,000 per draft (tool schemas
in every request). Total spend for the four runs: USD 0.36; budget ledger total after them: USD 0.71.
Both failure messages come from the OpenMinion runtime, not from the model's draft; they are
counted, never saved, and the thread stays in the digest.

## Approval gate (H4, offline)

`tests/test_post.py` runs the publisher on the real OpenMinion runtime against a local fake model
that calls `post_comment`, with GitHub replaced by a fake `urlopen` that records every request:

| Case | Expected | Result |
|---|---|---|
| no approver | paused, 0 model requests, 0 HTTP | pass |
| approver says `deny` | approver sees the exact body; 0 HTTP | pass |
| approver says `allow_once` | exactly 1 POST to `/repos/<sandbox>/issues/7/comments` with the approved body | pass |
| repo not on the allow-list | refused before approver, model and HTTP | pass |
| default config (allow-list empty) | refused, 0 HTTP | pass |
| stop file via env or repo-local file | exit code 5 before anything | pass |
| stop file created while the approval prompt is open | exit code 5 from inside the tool, 0 HTTP | pass |
| model changes the body after approval | not posted, 0 HTTP | pass |

Sabotage check: removing the allow-list check, the approved-body check or the pause on a missing
approver turns 4 of these tests red.

## Reminder ledger (H3, offline)

`tests/test_ledger.py` runs the fixture sweep (saved readings, real rules) through `sweep.draft_new`
with a fake drafter and a real SQLite ledger in a temporary folder. The fixture has 4 threads that
need a draft.

| Case | Expected | Result |
|---|---|---|
| first sweep | 4 drafts, all `new` | pass |
| second sweep, nothing changed | 0 drafts, drafter not called, 4 `unchanged` | pass |
| one thread gets a label and a later `updated_at` | exactly 1 draft (that thread, `changed`) | pass |
| same changed snapshot again | 0 drafts | pass |
| a draft that failed its checks | not recorded; drafted again next sweep | pass |
| one second before / at `expiry_days` | `unchanged` / `expired` | pass |
| same state, different action | `action_changed` | pass |
| two repos, same issue number | independent | pass |
| `followthrough sweep --draft` twice (CLI, fake drafter) | saved 4, then saved 0 | pass |
| ledger file contents | no thread title or comment text | pass |

Sabotage check: making the ledger forget rows, recording failed drafts, ignoring expiry, or dropping
labels from the state hash each turns at least one of these tests red (6, 1, 1 and 12 tests).

OpenMinion memory, measured for ADR 0007 (`tests/test_memory_gap.py`, 6 tests pass on 0.1.23):
`list` returns records past `expires_at` (also with `valid_at` / `as_of`); `search` by a full key
also returns another key; a namespace with `/` is rejected; upsert by key keeps one live record.

## Scheduling

`followthrough schedule --daily 06:30 --repo openminion/openminion`, run on the build host on
2026-11-18 (openminion 0.1.23, `echo` provider in a throw-away home, no model key):

| Step | Result |
|---|---|
| `cron create --cron "30 6 * * *" --tz UTC` | ok, `next_due_at` 2026-11-18T06:30:00+00:00 |
| `daemon start` (own free port) | started; pid file in the throw-away home |
| `cron run` | queued, then `finished` (started 00:31:47.649, finished 00:31:48.762 UTC: 1.1 s) |
| run summary | the task instruction, echoed by the `echo` provider |
| delivery | `failed` / `cron_delivery_failed` (no delivery target; recorded, not a proof failure) |
| `cron pause` | `enabled: false`, `next_due_at: null` |
| `daemon stop` | rc 0; daemon process alive afterwards: no |
| throw-away home | deleted |
| proof passed | yes; whole command 80 s wall time |

Afterwards on the host: 0 OpenMinion daemons from Follow-Through homes, 0 leftover temporary homes,
0 crontab lines mentioning Follow-Through. The 0.1.23 CLI has no `cron list` or `cron delete`; the
task lived only in the deleted home. The printed system cron line:

```
30 6 * * * cd <repo folder> && uv run followthrough sweep --live --repo openminion/openminion --draft >> out/cron.log 2>&1
```

Two manual probes before this command existed: (1) without a daemon, `cron run` returned `ok` with
state `queued` and the run never executed (pausing the task cancelled it); (2) with the default port,
`daemon start` failed on this host because another OpenMinion daemon already listened on 18789
("endpoint identity does not match"). Hence the daemon for the proof and the per-home port.

Offline (`tests/test_schedule.py`, 19 tests, fake `openminion` runner): the command order create →
daemon start → run → show → pause → daemon stop; a failed create starts no daemon; a run that never
leaves `queued` fails the proof and still pauses and stops; a daemon process that survives `stop` is
killed (real child process); model and GitHub tokens are not in the child environment and a secret
printed by the child is redacted; the throw-away home uses its own port and the `echo` provider and is
gone afterwards. Sabotage check: removing the kill, the token stripping, the redaction or the per-home
port turns 1, 2, 1 and 1 tests red.

## Diagnostics and telemetry

`followthrough doctor` on the build host (model key loaded, 27 s, nothing spent):

| Check | Status | ok / warn / fail |
|---|---|---|
| `openminion doctor --json`, project config (`anthropic`) | ok | 23 / 3 / 0 |
| `openminion doctor --check-turn --json`, `echo` provider | ok | 23 / 3 / 0 |

The 3 warnings in both: no identity profile for the agent, the untrusted-content boundary posture,
and the security summary that counts it. The saved `doctor.json` does not contain the model key
(checked by searching the file for the key value). Without the key, the project-config check fails on
`provider.anthropic.key` and `runtime.bootstrap`, as expected.

`telemetry.json` from one fixture sweep with the model reader (`sweep --fixture --reader model`,
claude-haiku-5-5, 2026-11-18): 6 reader turns, 3 accepted readings, 224,017 input and 17,495 output
tokens, 1 turn with estimated tokens, USD 0.05115. A turn record carries the OpenMinion run stats, for
example `llm_calls` 7, `tool_calls` 2, `duration_ms` 11,933. Total model spend so far: USD 0.77 of 20.00.

Offline (`tests/test_telemetry.py`, 4 tests): totals per kind, tokens and USD; free-text problems are
replaced by `other`; no thread text or model reply appears in the file; saved readings are not turns;
a fixture sweep writes `telemetry.json` next to `digest.json`. Sabotage check: keeping free-text
problems turns 2 tests red.
