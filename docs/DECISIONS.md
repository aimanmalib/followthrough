# Design decisions

Each design decision is recorded as a short file in [`decisions/`](decisions/); this table lists them in order.

| No. | Decision | Status | Date |
|---|---|---|---|
| [0001](decisions/0001-stack-and-licence.md) | Stack and licence | accepted | 2026-11-17 |
| [0002](decisions/0002-read-only-github-snapshots.md) | Read-only GitHub access and the snapshot format | accepted | 2026-11-17 |
| [0003](decisions/0003-thread-state-guard-and-rules.md) | Thread state, quote guard and follow-up rules | accepted | 2026-11-17 |
| [0004](decisions/0004-reader-agents-and-budget.md) | Reader agents on OpenMinion, and the spend budget | accepted | 2026-11-17 |
| [0005](decisions/0005-sweep-and-digest.md) | Sweep pipeline, digest format and public CI | accepted | 2026-11-17 |
| [0006](decisions/0006-drafts-and-the-write-path.md) | Drafts and the single write path | accepted | 2026-11-17 |
| [0007](decisions/0007-reminder-ledger.md) | Reminder ledger in SQLite, not OpenMinion memory | accepted | 2026-11-18 |
| [0008](decisions/0008-diagnostics-telemetry-and-scheduling.md) | Diagnostics, per-turn telemetry and the scheduling proof | accepted | 2026-11-18 |
| [0009](decisions/0009-sandbox-approval-demo.md) | Sandbox approval demo: the `post` command, the allow-list and the publisher message | accepted | 2026-11-18 |
| [0010](decisions/0010-live-sweep-runtimes-cache-metrics.md) | Live sweep: one runtime per reader worker, a reading cache, and `metrics.json` | accepted | 2026-11-18 |
| [0011](decisions/0011-label-agreement.md) | Label agreement (H2): blind readings, odd/even split, two test runs at most | accepted | 2026-11-18 |
| [0012](decisions/0012-record-and-replay-demo.md) | Record and replay of the model API for a key-free demo | accepted | 2026-11-18 |
| [0013](decisions/0013-digest-page.md) | The digest as one self-contained HTML page | accepted | 2026-11-18 |
| [0014](decisions/0014-openminion-findings.md) | OpenMinion findings: local repro scripts, run by hand | accepted | 2026-11-18 |
| [0015](decisions/0015-feature-freeze-on-openminion-0-1-23.md) | Feature freeze on openminion 0.1.23, final measurements taken early | accepted | 2026-11-21 |
| [0016](decisions/0016-public-demo-page-on-github-pages.md) | Public demo page on GitHub Pages, built by a workflow | accepted | 2026-11-25 |

A new decision adds a file in `decisions/` and a row here.
