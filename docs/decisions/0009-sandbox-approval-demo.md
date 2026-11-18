# 0009. Sandbox approval demo: the `post` command, the allow-list and the publisher message

Date: 2026-11-18 · Status: accepted

## Context

ADR 0006 built the single write path (`post.publish`) and tested it offline. The live demo needs a
person to see a saved draft and answer, a repository the agent may write to, and a thread to act on.
The only repository the agent may ever post to is the project's own private sandbox.

Measured on openminion 0.1.23 during the live run: with the old publisher message ("Post this
approved comment with post_comment." followed by a dated body) the runtime's freshness classifier
judged the request time-sensitive and answered it itself with 0 tool calls, so the approval callback
never ran. An explicit tool request ("Call post_comment …") skips the classifier.

## Decision

- `followthrough post --repo --number --draft` reads the saved draft, runs `post.publish`, and asks
  on standard input when OpenMinion's action policy asks for approval. Only the exact answer
  `allow_once` allows; anything else, including end of input, denies. Exit codes: 0 posted or denied,
  5 stop file (from `config/safety.toml`), 1 anything else, 2 empty draft or bad arguments.
  The prompt text lives in `locales/{en,ms}.toml`.
- `config/safety.toml` ships `allow_post_repos = ["aimanmalib/followthrough-sandbox"]`. A third-party
  repository stays refused before approval, model and HTTP (test). Anyone running their own copy edits
  this list for their own sandbox.
- `scripts/seed_sandbox.py` writes one synthetic fixture thread to that single allow-listed repository
  through the `gh` CLI (no token in the script), finds existing issues by a plain listing (the search
  index lags), and never posts a comment twice.
- The publisher message in `config/prompts.toml` starts with "Call post_comment"; a test pins that
  it parses as an explicit tool request.

## Consequences

- The demo proves the gate on real GitHub: deny = 0 comments, allow_once = exactly 1 comment with the
  approved text, stop file = exit 5 and nothing posted (`docs/TEST-RESULTS.md`).
- The seeded posts all come from one account, and the rules' clock is moved with `--now`; both are
  stated as demo limits.
- The workaround depends on the classifier's skip rule for explicit tool requests; the test fails if
  that rule changes in an OpenMinion upgrade.

## Rollback

Set `allow_post_repos = []` to switch posting off everywhere (the `post` command then refuses every
repository). Revert the `[publisher] message` text and remove `src/followthrough/approve.py`, the `post`
subcommand in `cli.py`, its locale keys and `scripts/seed_sandbox.py`. Sandbox issues stay as they are.
