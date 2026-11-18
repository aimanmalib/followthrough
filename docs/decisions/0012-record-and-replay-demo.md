# 0012. Record and replay of the model API for a key-free demo

Date: 2026-11-18 · Status: accepted

## Context

Requirement H5 asks that anyone can run the demo from a clean clone with Docker only, without a model
key, in at most five minutes, and see the digest. The offline `--reader states` path already runs without a
key, but it skips the agents entirely: the readings come from a hand-written file. A judge should see the
real pipeline (one OpenMinion subagent per thread, the quote guard, the rules, the drafter) run, with
answers that were really given by the model once.

## Decision

- `followthrough replay --record|--serve -- <followthrough command>` (`replay.py`) starts a local
  Anthropic Messages endpoint on 127.0.0.1 (port from `config/replay.toml`, 0 = free), points the run at it
  through the variable `base_url_env` (read by `agents.write_agents_json`, which already took a
  `base_url` for tests), runs the command in the same process and stops the server. No background
  process outlives the command.
- The provider stays the built-in `anthropic` one with a different `base_url`, not
  `custom-anthropic-compatible`: it sends the same request shape the live sweeps use, which is what the
  recordings have to match.
- `--record` forwards each request to the real API and saves `{path, canonical request, status,
  content type, raw body}` as `fixtures/recorded/<key>.json`. JSON and server-sent-event bodies are
  saved as raw text and replayed byte for byte. Request headers are never saved, so the key cannot reach
  the files. Upstream rejections of the exact request (4xx except 408, 409, 429) are saved and replayed, because the
  client reacts to them the same way every time (Sonnet 5.5 rejects the forced `tool_choice` of OpenMinion's
  freshness classifier with HTTP 400 and the runtime carries on); rate limits, timeouts and 5xx are never saved. Old recordings are removed before a new
  recording, so the folder is always one complete run.
- The key is the SHA-256 of the path plus a canonical request: sorted JSON keys, `drop_keys` removed,
  then the `normalize` regex list. All of it is config. The list was found by replaying from a second
  checkout and reading the miss diffs: UUIDs, ISO time stamps and sweep session ids, plus what OpenMinion
  0.1.23 adds to its prompts on its own: the "Active state" bookkeeping line (turn and capture ids,
  remaining time budget, memory record ids), the working folder (`cwd`, `workspace_root`) and the
  "Runtime Grounding" section, which the runtime cuts at a fixed length, so a longer or shorter folder
  name changes what survives the cut.
- `--serve` answers from the files only. A request without a recording gets an error reply
  (`miss_status`; OpenMinion's structured calls retry it, and every retry misses again), the closest saved
  request is diffed to standard error with long prompt lines shown around the change, and the run exits 4
  even when the sweep itself recovered. There is no fallback to the live API.
- Recordings are made only on the synthetic fixture (`fixtures/sandbox-repo.json`), never on a live
  repository, so no third-party text is tracked.
- `demo/run.sh` builds `demo/Dockerfile`, runs it with `--network none --read-only --cpus=1`
  (state, output and OpenMinion's home on tmpfs), prints the digest and the saved drafts (`demo/inside.sh`)
  and removes the image. Public CI runs the same script. Arguments are passed to `followthrough`, so the
  same image also replays the reader-only sweep in Malay (`demo/run.sh replay --serve -- sweep --fixture
  --reader model --lang ms`): its requests are a subset of the recorded run.
- A test re-normalizes every tracked recording and checks its file name, so a rule change without a
  re-key or re-record fails in CI, and checks that no recording holds a key or a local path.

## Consequences

- The demo proves the agent wiring offline; it does not prove the model reads well (that is H1/H2 on the
  live repository, reported separately).
- Any change to a prompt, tool schema, the fixture or the OpenMinion version changes the requests, so the
  replay misses loudly until the fixture run is recorded again (`replay --record`, costs about one fixture
  sweep). That is intended: a stale recording must not pass quietly.

## Rollback

Delete `replay.py`, `config/replay.toml`, `fixtures/recorded/` and `demo/`, the `replay` subcommand in
`cli.py` and the `base_url_env` lookup in `agents.write_agents_json`; the offline demo falls back to
`followthrough sweep --fixture` (hand-written readings), which product requirement 4.9 names as the fallback.
