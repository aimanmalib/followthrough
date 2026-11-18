# 0014. OpenMinion findings: local repro scripts, run by hand

Date: 2026-11-18 · Status: accepted

## Context

The submission checklist asks for a "Building Blocks Tested" note, a "What We Learned" note, and bug
reports with repro steps, expected and actual behaviour, and safe evidence. Building Follow-Through
on openminion 0.1.23 produced several behaviours worth reporting (ADRs 0004, 0006 to 0010, 0012).
A report is only useful upstream if a maintainer can run it without our keys, data or GitHub access.

## Decision

- One folder per finding under `repro/<slug>/`: `README.md` (version, steps, expected, actual, source
  lines, safe evidence, how Follow-Through works around it) and `repro.py`.
- Scripts need no key and reach only 127.0.0.1: either a local stand-in for the Messages API
  (`repro/fake_messages.py`, the same idea as `tests/fake_anthropic.py` but standalone so the folder
  can be copied into an issue) or the key-free `echo` provider with its own free daemon port. Each
  works in a temporary home deleted on exit and starts no lasting process.
- Exit codes: 0 while the finding is still there, 1 once it is fixed, 2 when the control case fails.
  The one OpenMinion upgrade at feature freeze reruns all three to see what changed.
- The scripts take 1 to 3 minutes each (a real runtime boots per run), so CI does not run them.
  `tests/test_findings.py` keeps the package consistent instead: at least three folders with the
  required sections, only localhost in the scripts, links that resolve, at least eight building
  blocks, and every `file:line` in `BUILDING_BLOCKS.md` pointing at a line that uses the OpenMinion API.
- The three repros are the findings with no existing upstream issue (searched 2026-11-18): a `datetime`
  tool parameter, serial turns on a shared runtime, `cron run` without a daemon. Findings that already
  have an issue (#677 memory expiry, #774 Handoff approval) are rows in `BUILDING_BLOCKS.md` only.
- Issue drafts stay outside the repository until the owner approves each one; nothing is filed from
  this step.

## Rollback

Delete `repro/`, `tests/test_findings.py` and this file; `BUILDING_BLOCKS.md` and `LEARNED.md` stand on
the other ADRs' evidence without them.
