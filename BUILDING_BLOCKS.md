# Building blocks

Which OpenMinion building blocks Follow-Through uses, what worked, what did not, and the evidence.
Measured on the pinned version (openminion 0.1.23).

| Block | Where | Works | Gap | Evidence | Upstream |
|---|---|---|---|---|---|
| Memory records (`MemoryService`, SQLite store) | not used; `src/followthrough/ledger.py` instead | `upsert_record` keeps one live record per (scope, type, key) | no exact lookup by key; `list` returns records past `expires_at`; namespace ids reject `/` | `tests/test_memory_gap.py`, ADR 0007 | #677 (open; expiry part) |
