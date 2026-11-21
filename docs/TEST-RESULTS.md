# Test results

Measured numbers only. Failures are reported as they happened.

## Upstream activity

Read-only GitHub searches on `openminion/openminion`, 2026-11-18 10:01 UTC (`gh api search/issues`, `total_count`
only; no thread text kept). These are the counts quoted in the README.

| Query | Count |
|---|---:|
| issues created 2026-10-18 to 2026-11-17 (31 days) | 188 |
| pull requests created 2026-10-18 to 2026-11-17 | 318 |
| open issues and pull requests | 107 |
| open issues labelled `status:awaiting-release` | 18 |

GitHub search counts move as items are deleted or transferred; a nearby window (2026-10-16 to 2026-11-16) gave 186
issues and 322 pull requests.

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

Public CI, GitHub Actions run 44279632622 (2026-11-18, commit 564e987): `uv run --frozen pytest -q` reported
**282 passed** in 46.9 s, with no key and no network.

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
| empty allow-list | refused, 0 HTTP | pass |
| shipped config (allow-list = the sandbox only) on `openminion/openminion` | refused before approver, model and HTTP | pass |
| publisher message (config) parses as an explicit `post_comment` request | yes (regression for the live finding below) | pass |
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

## Sandbox approval demo

Live, 2026-11-18 (01:07 to 01:20 UTC), on the project's own private sandbox repository
`aimanmalib/followthrough-sandbox`, with `claude-haiku-5-5` and `config/safety.toml`
`allow_post_repos = ["aimanmalib/followthrough-sandbox"]`.

1. `scripts/seed_sandbox.py` wrote fixture thread #101 (invented text: a contributor's report and a
   maintainer's request for a reproduction script). The first version looked for an existing issue
   through GitHub search, which had not indexed the new issue 10 s later, so a second run created a
   duplicate: sandbox issues #1 and #2 are the same thread. Fixed (plain listing, regression test);
   a third run reused #2 and posted nothing. Both issues were then used: one approved, one denied.
2. `followthrough sweep --live --repo aimanmalib/followthrough-sandbox --now 2026-11-26T09:00:00Z --draft`.
   GitHub stamps seeded posts with the seeding time, so the rules' clock is moved 8 days forward.
   Result: 2 threads read by the model, 2 x `FOLLOW_UP_DUE` ("maintainer request unanswered since
   2026-11-18"), 0 quote-guard rejections, 4 HTTP requests, 0 non-GET; 2 drafts saved
   (91 and 79 words, dates 2026-11-26 and take-over from 2026-11-29, no mentions). Reading cost
   USD 0.013 (18 model calls).
3. `followthrough post` on each draft:

| Step | Exit code | Comments on the issue (before -> after) | Write requests |
|---|---:|---|---:|
| stop file present (`PERANAN_HENTI`), answer `allow_once` | 5 | #1: 1 -> 1 | 0 |
| answer `deny` on #2 | 0 | #2: 1 -> 1 | 0 |
| answer `allow_once` on #1 | 0 | #1: 1 -> 2 | 1 |

The posted comment (`https://github.com/aimanmalib/followthrough-sandbox/issues/1#issuecomment-6966060777`)
is byte-identical to the saved draft (`diff` empty, trailing whitespace ignored).

Failure found on the way: the first `deny` and `allow_once` runs both ended `not_posted` with 0 tool
calls. The approver was never asked, so that first `deny` proved nothing and is not counted above.
OpenMinion's freshness classifier read the dated comment as a question about current facts, and the
runtime answered it itself ("Missing exact-date evidence for an exact-date freshness answer").
OpenMinion skips that classifier for explicit tool requests, so the publisher message now starts with
"Call post_comment" (config, ADR 0009). After the change the approver received the exact draft body.

Known limits of this demo: every seeded post comes from one account (the sandbox owner), so the
author roles are carried in the text and the reader still classified both threads correctly; the
clock is moved with `--now` rather than waiting 8 days. Total project spend after the demo: USD 0.85
of 20.00.


## Live sweep (read-only)

`openminion/openminion`, 2026-11-18 (01:34 to 03:03 UTC), openminion 0.1.23, reader
`claude-haiku-5-5`, run on a shared host under heavy load (load average 24 to 43 on 16 cores
during the runs). Command: `followthrough sweep --live --repo openminion/openminion --format json`
(no `--draft`: nothing was drafted for this repository). Per requirement 4.10 only counts are
published here; the snapshot, readings and digest items stay in untracked folders.

Snapshot: 108 open threads (79 issues, 29 pull requests). Every snapshot made 225 GitHub requests,
all `GET`; the first returned 200/304 and took 125 s, the later ones were all 304 (ETag cache).
**Write requests to the repository across all runs: 0.**

| Run | Setup | Process wall time | `metrics.json` seconds | Model turns | Readings that passed the guard / rejected | Failed turns (timeout or provider / invalid reply) | Threads not reached | Stopped by | USD |
|---|---|---|---|---:|---|---|---:|---|---:|
| 1 | 8 workers, 8 runtimes on one SQLite file | 5 min 59 s (crashed) | not written | 16 | not written | not written | not written | crash: `sqlite3.OperationalError: database is locked` | 0.254882 |
| 2 | 8 workers, one home each, OpenMinion's 90 s turn timeout | 11 min 41 s | 670.8 | 51 | 5 / 6 | 37 / 3 | 57 | USD limit | 0.901368 |
| 3 | 4 workers, 240 s turn timeout, 16-minute start limit | 17 min 29 s | 1,017.0 | 35 | 9 / 10 (+5 from cache) | 8 / 8 | 68 | time limit | 0.473679 |
| 4 | same as run 3, second run (reading cache) | 23 min 46 s | 1,053.6 | 21 | 5 / 6 (+14 from cache) | 6 / 4 | 73 | time limit | 0.310754 |

Requirement H1 (one sweep finishes in 20 minutes, under USD 1.00, with 0 writes):

- 0 write requests: **met** in every run (225 of 225 requests were `GET`).
- USD 1.00 per sweep: **met** in every run. Run 2 stopped at the limit; 42 of its 51 turns
  failed and were booked at the USD 0.02 reserve, because a failed turn loses its token counts.
- 20 minutes: **not met.** Runs 3 and 4 stopped starting turns at minute 16 as designed, but run 4's
  process ended 23 min 46 s after it started, 6 min after `metrics.json` was written. The cause
  is not yet confirmed. Run 4 also ran next to this repository's own test suite on the same host.
- A complete sweep: **not met.** No run read all 108 threads. With the reading cache, each run
  sends only threads without a good reading to the model. After runs 2 to 4, 19 of 108 threads hold a reading
  that passed the guard.

Throughput: a reader turn alone took 27 s. Eight turns on one shared runtime took 305 s; with one
runtime each, 94.5 s (one SQLite file, before run 1). On the loaded host, 4 workers averaged 1.3
to 2.2 turns per minute, and many turns ran past 90 s.

Quote guard (H6), fresh model readings only: 6 of 11 rejected (run 2), 10 of 19 (run 3), 6 of 11
(run 4), so 22 of 41 overall (0.54). 21 of the 22 rejections were `follow_up_time_not_found`:
the reader gave a `last_follow_up_at` that matches no maintainer post in the thread. The other was
`open_request_incomplete`. Rejected readings count as `unclear` and are never cached.
Invalid replies (15 in runs 2 to 4) were text around the JSON (`reader: {...}`) or prose instead of
a reading. In one of the probes a reader replied with a refusal for lack of "an exact date" (the
runtime's freshness check, see the sandbox demo above).

Digest of run 4 (counts only): `FOLLOW_UP_DUE` 3, `READY_TO_VERIFY` 6, `NO_ACTION` 99, of which
83 were not read in that run.

Total spend on these runs and the four 8-thread probes before them: USD 2.381; spend ledger
total after F9: USD 3.233 of the USD 20.00 limit.

## Label agreement (H2)

`openminion/openminion`, 2026-11-18, openminion 0.1.23, reader `claude-haiku-5-5`, command
`followthrough agree --set dev|test --snapshot <the run 4 snapshot above>` (ADR 0011). The
snapshot was taken at 02:45 UTC, so no GitHub request was made. Measured set: open issues with
exactly one mapped status label, 76 in that snapshot (maintainer-investigation 38,
contributor-in-progress 19, awaiting-release 17, awaiting-contributor 2). Odd numbers are the dev set
(35), even numbers the test set (41). **The reader never saw the status labels.** Only counts are
published; the per-issue list stays in an untracked folder.

| Run | Issues | Read | Agree after guard | Agree as read | Not read (provider error or timeout / invalid reply) | Guard rejected | Host load average | USD |
|---|---:|---:|---|---|---|---:|---|---:|
| dev 1 | 35 | 12 | 4 (0.114 of 35; 4 of 12 read) | 6 (0.171; 6 of 12) | 23 (17 / 6) | 4 | 22 to 104 | 0.5707 |
| test 1 | 41 | 29 | 7 (**0.171** of 41; 7 of 29 read) | 12 (**0.293**; 12 of 29) | 12 (9 / 3) | 9 | 92 falling to 8 | 0.5474 |

**H2 (at least 0.80 on the test set): not met.** 0.171 after the guard and 0.293 as read, counting
unread issues as disagreements; 0.24 and 0.41 of the issues that were read. Test runs used: 1 of 2.

Test run 1, confusion table, rows = expected from the label, columns = the model's own answer:

| Expected | maintainer | contributor | release | nobody | unclear | not read | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| maintainer | 4 | 8 | 2 | 0 | 1 | 8 | 23 |
| contributor | 3 | 3 | 0 | 0 | 0 | 2 | 8 |
| release | 1 | 0 | 5 | 1 | 1 | 2 | 10 |

After the guard the same row totals hold, with the 9 rejected answers moved to `unclear`: maintainer row 1 /
7 / 2 / 0 / 5 / 8, contributor row 1 / 3 / 0 / 0 / 2 / 2, release row 0 / 0 / 3 / 1 / 4 / 2.

What the numbers say:

- The biggest disagreement: issues labelled `status:maintainer-investigation` read as waiting on
  the contributor (8 of the 15 such test issues that were read; 4 of 7 in dev). In these threads the newest
  open request is often a maintainer's question to the reporter, while the label still records an
  earlier triage decision. Neither side is always right; the label is not updated on every comment.
- The guard turned 9 of 29 fresh test readings into `unclear`; 8 of them were
  `follow_up_time_not_found` (the same reader mistake as in the live sweep, H6), so the guarded number is
  lower than the model's own.
- Not-read issues: on a host with load average up to 104 on 16 cores, many reader turns ran past the 240 s
  turn timeout. These count against the agreement here.
- Not tried: the Sonnet drafter as reader. At USD 2.00 / 10.00 per million tokens (20 times the
  reader's price) one test run would cost about USD 10, over the USD 1.00 per-run limit.
- Dev-set tuning (prompt for maintainer-investigation threads and for `last_follow_up_at`) has not
  been done yet; the second test run is kept for after it.

## Key-free demo (record and replay, H5)

`followthrough replay` (ADR 0012), synthetic fixture only, OpenMinion 0.1.23, 2026-11-18.

Recording (`replay --record -- sweep --fixture --reader model --draft`, reader `claude-haiku-5-5`,
drafter `claude-sonnet-5-5`, clean checkout, rc 0, 251.8 s):

- 83 model exchanges recorded in 67 files (1.2 MB); 8 of the files are HTTP 400 replies (see below).
- Cost of this recording: USD 0.1317 (spend ledger; reader 0.0537). An earlier recording made before
  4xx replies were saved cost USD 0.1515 and was replaced. Project total after both: USD 4.63 of 20.00.
- What the model produced, as recorded: follow-up due 2, take-over allowed 1, no action 3; the quote
  check rejected 2 readings (`follow_up_time_not_found`), 1 thread could not be read (`invalid_output`);
  3 drafts allowed by the ledger, 2 saved, 1 not saved (`invalid_output`). These are the model's real
  answers on the fixture, not the hand-written ones; the replay reproduces them, faults included.

Replay (`replay --serve`, no key in the environment):

| Run | Exchanges answered | Missed | rc | Output |
|---|---:|---:|---:|---|
| Second clean checkout on the host, same command | 83 | 0 | 0 | digest and both drafts byte-identical to the recording |
| `demo/run.sh` from `git archive` (Docker, `--network none`, read-only root) | 83 | 0 | 0 | same digest, then the 2 drafts; 47 s and 49 s with cached base images; image removed afterwards |
| `demo/run.sh replay --serve -- sweep --fixture --reader model --lang ms` | 54 | 0 | 0 | Malay digest (reader-only run is a subset of the recording) |

Public CI, cold runner (GitHub Actions run 44259212609, commit 42ae252, step "Key-free demo"): image
built in 18 s, replay finished 32 s after the step started, 83 answered, 0 missed, rc 0.

Misses fail loudly, as designed. Before the normalization rules were complete, the second checkout
missed 54 of 101 requests and exited 4, each miss with a diff to the closest recording. The diffs
showed what OpenMinion puts into prompts on its own and changes per run or per checkout: turn and
capture ids, remaining time budget and memory record ids (the "Active state" line), the working folder,
and the "Runtime Grounding" section cut at a fixed length (a different folder name moves the cut).

Finding: `claude-sonnet-5-5` rejects the forced `tool_choice` (`{"type": "tool"}`) of OpenMinion's
freshness classifier with HTTP 400 ("tool_choice: type tool and any are not supported for this model").
The runtime records `classifier_failed` and carries on, so drafts are still written. The recorder saves
such repeatable 4xx replies (not 408, 409, 429 or 5xx) so the replay takes the same path.

## Digest page (R4)

`digest.html` (ADR 0013), 2026-11-18, host Playwright, `scripts/check_page.py`. Pages checked: the
offline fixture sweep in English and in Malay (`sweep --fixture --lang en|ms`), and an English page built
from the same digest with a budget stop banner and live-style metrics (412 GitHub requests, 0 writes).

| Engine and view | Width | Schemes | Pages | Passed |
|---|---:|---|---:|---:|
| Chromium | 320 px | light, dark | 3 | 6/6 |
| Chromium | 1280 px | light, dark | 3 | 6/6 |
| WebKit, iPhone 13 device | 390 px | light, dark | 3 | 6/6 |
| WebKit, mobile | 320 px | light, dark | 3 | 6/6 |

24/24 passed: `scrollWidth <= clientWidth`, no element past the right edge, no console errors, every
text element at WCAG AA contrast or better (4.5:1, or 3:1 for large text). Screenshots at device scale 3.

The first render showed three layout faults that the checks do not measure: the repository name broke
inside a word at 390 px, a wrapped Malay section heading pushed its count to the far right at 320 px,
and the five action cards left one card alone on a row on desktop. All three were fixed (break after
`owner/`, inline count, one row of cards from 40 rem and a full-width last card on two columns) and the
24 checks were run again.

Sabotage: the English page with the soft text colour set to `#c9c3b5` and a 400 px minimum width failed
7 of 8 checks (18 low-contrast elements in each light view, `scrollWidth` 400 at 320 and 390 px); the
dark desktop view passed, as expected, because neither change touches it. `tests/test_page.py`: 10 tests
(language, counts, self-contained, no thread text, escaping, partial banner, colour tokens, CLI); removing
the escape of the repository name turns the escaping test red.

## OpenMinion findings (repro)

The three scripts in `repro/`, run on the build host on 2026-11-18 (openminion 0.1.23, Python 3.12,
no model key, only 127.0.0.1 reached). Exit code 0 means the finding is still there.

| Script | Output | Exit | Wall time |
|---|---|---|---|
| `tool-datetime-argument` | `str` control: 1 handler call, `completed`; `datetime`: 0 handler calls, `failed`, reply `State machine error: RUNTIME_ERROR: Object of type datetime is not JSON serializable` | 0 | 61.7 s |
| `shared-runtime-turns-run-one-at-a-time` | 4 threads, one runtime, model answers after 0.5 s: no tools = at most 4 requests in flight, 16 requests, 9.9 s; one decorated tool = at most 1 in flight, 16 requests, 17.7 s; all 8 turns `completed` | 0 | not recorded (two runtimes boot per run) |
| `cron-run-ok-without-daemon` | `cron create` rc 0; `cron run` with no daemon rc 0, `ok: true`, state `queued`; still `queued` after 30 s; `cron pause` leaves `enabled: false` | 0 | not recorded |

- First version of the shared-runtime script, without a warm-up turn: the four concurrent first turns
  on a fresh runtime failed with `sqlite3.IntegrityError: UNIQUE constraint failed: migrations.version`
  (exit 1, nothing measured). The script now runs one turn before timing.
- First version of the cron script read the task id from the wrong level of the CLI's JSON
  (`{"data": {...}}`) and exited 1 after `cron create`; fixed before the run above.
- After each run: no `om-repro-*` temporary home left, no daemon started.
- `tests/test_findings.py` (4 tests) keeps the package consistent; sabotage (a wrong `file:line` in
  `BUILDING_BLOCKS.md`, a missing README section, a non-local URL in a script) turns 1, 1 and 1 test red.
- Upstream duplicates searched on 2026-11-18 (`gh issue list --state all --search`, read-only): no
  existing issue for the three findings; related closed #371 and #617, open #677, #720, #726, #774.

## Demo video

Cut on 2026-11-18 from the real captures (digest page, fixture sweep in a terminal, sandbox issue before
and after the approved comment) and title cards; every number on screen and in the narration is taken
from the sections above. Measured on the final file with `ffprobe` and `ffmpeg ebur128`:

| Check | Result |
|---|---|
| Duration (format / video / audio) | 118.4 s / 118.4 s / 118.4 s |
| Picture | 1920x1080, 30 fps, H.264 |
| Integrated loudness | -16.5 LUFS |
| True peak | -2.5 dBTP |
| First 15 s | 0.0 s black, 0.0 s frozen; product UI on screen from 13.2 s |
| Captions | burned in (English), plus a sidecar `.srt` with 53 cues |
| Music | none |
| Narration | ElevenLabs clone of the author's voice, declared on the end card |

Transcription of the final audio (ElevenLabs Scribe, English) against the script: 305 script words,
325 transcribed, match ratio 0.937. Every difference is a spoken form ("31" heard as "thirty one",
"subagent" as "sub agent", "#5" as "number five") or a filler word the narration adds ("and", "it").
The video is not published yet.

## Release

`v1.0.0`, tag on commit 06bcab0, published 2026-11-18 11:35 UTC (notes: `RELEASE.md`).

| Check | Result |
|---|---|
| Public CI on the tagged commit (GitHub Actions run 44295146190) | success: 287 passed, offline; key-free demo step 83 answered, 0 missed |
| `git archive v1.0.0` into an empty folder, then `demo/run.sh` on the build host | rc 0 in 71 s (image build included, host load average about 30); 83 answered from recordings, 0 missed; digest, then 2 drafts; last digest line "Readings rejected by the quote check: 2. Threads that could not be read: 1."; no demo image left afterwards |
| `followthrough --version` | `followthrough 1.0.0` |

The demo guide `demo/README.md` budgets about 3 minutes for steps 1 to 3 (run, digest, drafts) and about 2 minutes
for step 4 (approval on your own repository), which is not part of the offline demo; the measured approval run is
in "Sandbox approval demo" above.

## Feature freeze measurement

2026-11-21, ADR 0015. The newest `openminion` release on PyPI was **0.1.23**, the pinned version, so there was no
upgrade; every number below is on 0.1.23 with reader `claude-haiku-5-5`, on the shared build host (load average
12 to 25 on 16 cores during the runs).

| Check | Result |
|---|---|
| Offline suite on Depot CI (`scripts/gerbang-ujian.sh`, commit 9048055) | 290 passed in 35.1 s |
| `repro/tool-datetime-argument/repro.py` | rc 0 (finding still present): a `datetime` parameter makes the run fail with "Object of type datetime is not JSON serializable"; the `str` control completes. 67 s |
| `repro/shared-runtime-turns-run-one-at-a-time/repro.py` | rc 0 (still present): 4 threads on one runtime, most model requests in flight at once = 4 without tools, 1 with a decorated tool (11.7 s against 22.9 s). 91 s |
| `repro/cron-run-ok-without-daemon/repro.py` | rc 0 (still present): `cron run` reports success while the run stays `queued` 30 s later with no daemon. 187 s |

### Live sweep, run 5 (H1)

`followthrough sweep --live --repo openminion/openminion --format json`, started 13:03 UTC, same setup as runs 3
and 4 above (4 workers, 240 s turn timeout, no new turn after minute 16), with the reading cache from those runs.
Only counts are published.

| Measure | Result |
|---|---|
| Open threads in the snapshot | 134 |
| GitHub requests | 347, all `GET` (230 returned 200, 117 returned 304). **Write requests: 0** |
| Process wall time | 18 min 21 s (`metrics.json`: 1,007.9 s) |
| Model turns | 31: 16 passed the guard, 7 rejected by the guard, 8 invalid replies |
| Threads with a reading | 32 (23 fresh, 9 from cache) |
| Threads not read | 102 (94 not reached before minute 16, 8 invalid replies) |
| Stopped by | time limit ("no new model turn starts after minute 16.0") |
| USD | 0.346209 (1,075,590 input and 77,300 output tokens; 10 turns estimated from characters) |
| Exit code | 3 (digest written, sweep stopped early) |

Requirement H1: 0 writes **met**; under USD 1.00 **met**; process ended within 20 minutes **met in this run**;
a complete sweep **not met** (32 of 134 threads read). Quote guard (H6) on fresh readings: 7 of 23 rejected (0.30),
all 7 `follow_up_time_not_found` (one also `open_request_incomplete`).
Digest counts: `FOLLOW_UP_DUE` 4, `READY_TO_VERIFY` 3, `NO_ACTION` 127, of which 102 were not read.

### Label agreement, test run 2 (H2)

`followthrough agree --set test --snapshot <the run 5 snapshot>`, status labels hidden, no tuning since test
run 1 (the dev set was not re-read). The newer snapshot has 49 test-set issues (41 in run 1). Wall time 1,021.8 s.

| Run | Issues | Read | Agree after guard | Agree as read | Not read (provider error or timeout / invalid reply) | Guard rejected | USD |
|---|---:|---:|---|---|---|---:|---:|
| test 2 | 49 | 37 | 10 (**0.204**) | 17 (**0.347**) | 12 (5 / 7) | 16 | 0.6448 |

Confusion table, model's own answer (rows = expected from the label):

| Expected | maintainer | contributor | release | nobody | not read | Total |
|---|---:|---:|---:|---:|---:|---:|
| maintainer | 6 | 6 | 0 | 2 | 7 | 21 |
| contributor | 6 | 2 | 0 | 0 | 2 | 10 |
| release | 5 | 0 | 9 | 1 | 3 | 18 |

**H2 (at least 0.80 on the test set): not met**, in both test runs (0.171 and 0.204 after the guard). Test runs
used: 2 of 2; a third is refused. Of the 16 guard rejections, 12 were `follow_up_time_not_found`.

Spend ledger total after these runs: USD 5.63 of the USD 20.00 limit.
