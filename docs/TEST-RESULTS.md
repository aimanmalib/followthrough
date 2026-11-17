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
