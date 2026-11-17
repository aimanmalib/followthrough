# 0006. Drafts and the single write path

Date: 2026-11-17 · Status: accepted

## Context

A follow-up is only useful if it reaches the issue, but an agent that posts on its own to someone
else's repository is exactly what maintainers do not want. The product requirement (H4) is: no
approver means pause with no HTTP; a denial sends nothing; `allow_once` sends exactly one POST to the
sandbox repository; a repository off the allow-list is refused before any HTTP; an existing stop file
exits with code 5.

## Decision

- **Drafter** (`drafter.py`): one OpenMinion `subagent` per thread whose action is listed in
  `config/drafts.toml actions` (FOLLOW_UP_DUE, TAKEOVER_ALLOWED, READY_TO_VERIFY), model from the
  `drafter` profile, `output_type=Draft`. It receives structured facts only: the action, the dates
  the rules computed, the release tag, and the CONTRIBUTING step for that action (written in our own
  words in `config/drafts.toml`). It never sees thread text, so third-party text cannot steer a draft.
  As with the reader (ADR 0004), a typed `submit_draft(number, body)` tool carries the schema; its
  arguments are used when the final reply does not validate (measured: the runtime sometimes blocks
  a plain JSON reply as an "unexecutable tool envelope").
- A draft is saved to `out/<YYYY-MM-DD>/drafts/<number>.md` only if it passes `check()`: at most
  `max_words` words (120), every computed date present verbatim, the release tag present when there
  is one, no @mentions. Failing drafts are counted with their problem codes and not saved.
- **Write path** (`post.py`, the only module with a non-GET HTTP method; a test enforces this):
  `publish()` checks, in order, the stop file (env `PERANAN_HENTI` or `safety.stop_file`; exit 5),
  the allow-list (`safety.allow_post_repos`, empty by default), then the approver. No approver
  returns `paused` before any model turn or HTTP request.
- With an approver, a publisher `Agent` whose only tool is `post_comment`
  (`@tool(dangerous=True, min_scope="WRITE_SAFE")`) runs on the OpenMinion runtime, so the SDK's
  action policy asks the same approver before the tool runs (`allow_once` = run, `deny` = the policy
  refuses). The tool checks the stop file again (an owner can stop between approval and post), the
  allow-list again, and posts only the exact body that was approved; a changed body is refused.
- A stop inside the tool is re-raised by `publish()` after the run, so the exit code is 5 even if the
  runtime turns the tool's exception into an error result.
- **No Handoff on the write path.** Measured on openminion 0.1.23: a `Handoff`'s generated
  `transfer_to_<name>` tool calls `target.run(message)` without an approval callback. With no
  callback, a dangerous tool falls back to an interactive console prompt and the turn blocks on
  standard input (measured: a run with `approval_callback=None` did not return within 40 s). Putting
  the publisher behind a Handoff would therefore bypass our approver. The publisher is run directly
  with an explicit callback; a test pins the measured Handoff behaviour so an upgrade that changes it
  shows up.

## Consequences

- Drafts are cheap and safe to generate in bulk, but they can only state facts the rules computed;
  any nuance is for the human approving them.
- Posting costs one small model turn (booked in the spend ledger) because the post goes through the
  SDK's approval policy rather than around it.
- The Handoff gap is a finding for the upstream report; until it changes, delegation is not used for
  any tool that needs approval.

## Rollback

Delete `post.py` and `drafter.py` and the two config sections (`config/drafts.toml`, the `drafter`
and `publisher` prompts). Sweeps and digests do not depend on them; `allow_post_repos` stays empty.
