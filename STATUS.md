# Status

Status of **Follow-Through** for Cortensor Hackathon #5. Every number here is from
[`docs/TEST-RESULTS.md`](docs/TEST-RESULTS.md).

**Version:** [1.0.0](RELEASE.md) · **OpenMinion:** 0.1.23 (pinned) · **Last updated:** 18 November 2026

## Done

- [x] Read-only GitHub client and snapshots (`GET` only, ETag cache)
- [x] Reader subagents with a typed thread state and the quote check
- [x] Follow-up rules from config, with a settable clock
- [x] Digest in Markdown, JSON and HTML, in English and Malay
- [x] Drafts and the approval-gated write path, shown live on the project's sandbox repository
- [x] Reminder ledger (no repeated reminders)
- [x] Diagnostics, telemetry and a scheduling proof with no daemon left
- [x] Read-only live sweep of `openminion/openminion`: 0 write requests
- [x] Label agreement measured on a held-out test set
- [x] Key-free demo from recorded model answers, run in public CI
- [x] Three OpenMinion findings with key-free reproduction scripts
- [x] Tagged release `v1.0.0`, with a demo guide

## Not done, or not met

- [ ] One live sweep of all open OpenMinion threads within 20 minutes (not met on the build host)
- [ ] Label agreement of at least 0.80 (measured 0.171 after the quote check)
- [ ] Upstream issues for the findings (drafted, not filed)
- [ ] Fix pull request upstream
- [ ] Demo video published (recorded, not published yet)
- [ ] Final measurements on the newest OpenMinion release before the feature freeze
