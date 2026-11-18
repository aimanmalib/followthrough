# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Release notes: [`RELEASE.md`](RELEASE.md).

## [Unreleased]

## [1.0.0] - 2026-11-18

### Added

- Read-only GitHub snapshots (`GET` only, ETag cache) and a typed thread state with a quote check: every date the
  model relies on must be quoted word for word from a real comment.
- Reader subagents on the OpenMinion SDK, one per changed thread, with spend limits per sweep and in total.
- Deterministic follow-up rules from `config/policy.toml`: follow-up due, take-over allowed, maintainer reply pending,
  ready to verify, no action.
- `followthrough sweep`: digest in Markdown, JSON and a self-contained HTML page, in English or Malay.
- Drafts of up to 120 words, and `followthrough post`, the only write path: stop file, allow-list, then human approval.
- A reminder ledger that holds back a second draft until a thread changes.
- `followthrough doctor`, per-turn telemetry, and `followthrough schedule` (an OpenMinion cron proof with no daemon left).
- `followthrough agree`: agreement between the reader and a repository's status labels.
- `followthrough replay` and `demo/run.sh`: the whole pipeline replayed from recorded model answers, with no key and
  no network.
- `repro/`: three key-free reproduction scripts for OpenMinion findings; `BUILDING_BLOCKS.md` and `LEARNED.md`.
- Community files, README in English and Malay, logo.
- `demo/README.md`: a guide from sweep to digest to draft to approval.

[Unreleased]: https://github.com/aimanmalib/followthrough/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/aimanmalib/followthrough/releases/tag/v1.0.0
