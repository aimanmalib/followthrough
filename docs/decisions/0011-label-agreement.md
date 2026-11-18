# 0011. Label agreement (H2): blind readings, odd/even split, two test runs at most

Date: 2026-11-18 · Status: accepted

## Context

Requirement H2 asks how often the reader's `waiting_on` agrees with the maintainers' own `status:*`
label on `openminion/openminion`, at least 0.80 on a held-out test set. The reader sees each
thread's labels in a normal sweep (`agents.thread_view`). Measured that way the model could copy the
answer from the label, and the number would say nothing about reading the posts.

## Decision

- `followthrough agree --set dev|test` (`agreement.py`) measures open issues (not pull requests)
  with exactly one status label that `[labels.waiting_on]` in `config/policy.toml` maps:
  maintainer-investigation → maintainer, contributor-in-progress and awaiting-contributor →
  contributor, awaiting-release → release. Labels not in the map are not measured.
- The reader gets a copy of each thread with every `status:*` label removed (blind reading). Other
  labels, the title and every post stay as in a sweep.
- Odd issue numbers are the dev set (prompt tuning allowed), even numbers the test set
  (`[agreement]` in `config/ops.toml`). A test run is recorded in `state/h2-runs.json` before it
  starts, and a third one is refused (`max_test_runs = 2`), so a crashed run still counts.
- It measures a saved snapshot (`--snapshot`, or the newest for `--repo`), so it makes no GitHub
  request, and it does not use or fill the reading cache (those readings saw the labels).
- Two numbers per run: agreement after the quote guard (what the rules act on; a rejected reading
  counts as "unclear") and agreement of the model's own answer (`Checked.read_as`, kept by the
  guard when it rejects a reading). A thread that was not read counts as a disagreement ("failed").
- Public output (`out/<date>/agreement-<set>.json`, `docs/TEST-RESULTS.md`) holds counts and the
  confusion table only. The per-issue list (issue numbers, expected and read values, guard problem
  codes; no thread text) stays in an untracked private folder.

## Consequences

- The number is a lower bound for a sweep that sees the labels, and an honest one for repositories
  that do not label status at all, which is where Follow-Through helps most.
- The label is a maintainer's past decision; a thread can move on without the label changing.
  Disagreements are therefore not all reader errors, and the report says so.

## Rollback

Delete `agreement.py`, the `agree` command, `[agreement]` in `config/ops.toml` and the
`[labels.waiting_on]` entries; `Checked.read_as` is unused elsewhere and can stay or go.
