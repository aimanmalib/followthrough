"""Why the reminder ledger is SQLite (ADR 0007): measured behaviour of OpenMinion memory, pinned version.

These tests lock what openminion 0.1.23 does today. If an upgrade makes one fail, memory may now do the
job: re-measure, then update ADR 0007 and BUILDING_BLOCKS.md before switching the ledger over.
"""

from __future__ import annotations

import pytest

memory = pytest.importorskip("openminion.modules.memory")
store_mod = pytest.importorskip("openminion.modules.memory.storage.sqlite.store")

SCOPE = "project:followthrough:example:repo"
PAST = "2020-01-01T00:00:00Z"
NOW = "2026-11-10T09:00:00Z"


@pytest.fixture
def service(tmp_path):
    svc = memory.MemoryService(store=store_mod.SQLiteMemoryStore(tmp_path / "memory.db"), owns_store=True)
    for number in (5, 6):
        svc.upsert_record(scope=SCOPE, record_type="fact", key=f"followthrough/example/repo#{number}",
                          record_patch={"title": f"thread {number}", "content": {"hash": "h"}, "expires_at": PAST},
                          project_id="followthrough:example:repo")
    yield svc
    svc.close()


def _keys(records):
    return sorted(r.key for r in records)


def test_namespace_ids_reject_slashes(tmp_path):
    """The product requirement's namespace `followthrough/<owner>/<repo>` is not a valid memory namespace id."""
    svc = memory.MemoryService(store=store_mod.SQLiteMemoryStore(tmp_path / "m.db"), owns_store=True)
    with pytest.raises(Exception, match="invalid"):
        svc.upsert_record(scope="project:followthrough/example/repo", record_type="fact", key="k",
                          record_patch={"title": "t", "content": {}})
    svc.close()


@pytest.mark.parametrize("when", [{}, {"valid_at": NOW}, {"as_of": NOW}])
def test_list_returns_records_past_expires_at(service, when):
    listed = service.list(memory.ListQueryOptions(scopes=[SCOPE], **when))
    assert _keys(listed) == ["followthrough/example/repo#5", "followthrough/example/repo#6"]
    assert all(r.expires_at == PAST for r in listed)


def test_search_by_full_key_is_not_an_exact_lookup(service):
    found = service.search(memory.SearchQueryOptions(query="followthrough/example/repo#5", scopes=[SCOPE]))
    assert "followthrough/example/repo#6" in _keys(found)


def test_upsert_by_key_keeps_one_live_record(service):
    """What does work: upsert on (scope, type, key) supersedes, so one live record per key."""
    service.upsert_record(scope=SCOPE, record_type="fact", key="followthrough/example/repo#5",
                          record_patch={"title": "thread 5", "content": {"hash": "h2"}},
                          project_id="followthrough:example:repo")
    live = [r for r in service.list(memory.ListQueryOptions(scopes=[SCOPE])) if r.key.endswith("#5")]
    assert len(live) == 1 and live[0].content == {"hash": "h2"}
