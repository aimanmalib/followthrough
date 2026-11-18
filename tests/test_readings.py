"""Reading cache: only changed threads go to the model; unchanged ones reuse a guarded reading."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from followthrough import agents, sweep
from followthrough.agents import ReadOutcome, ReadReport
from followthrough.readings import ReadingCache

ROOT = Path(__file__).resolve().parents[1]
CFG = {"enabled": True, "cache_dir": "state/readings"}


@pytest.fixture()
def snap():
    return json.loads((ROOT / "fixtures/sandbox-repo.json").read_text(encoding="utf-8"))


@pytest.fixture()
def good(snap):
    """Readings of every fixture thread from the hand-written states (all pass the guard)."""
    states = json.loads((ROOT / "fixtures/sandbox-states.json").read_text(encoding="utf-8"))
    return sweep.read_with_states(snap, states).outcomes


def test_empty_cache_reads_every_thread(tmp_path, snap):
    to_read, reused = ReadingCache(tmp_path, snap["repo"], CFG).split(snap["threads"])
    assert to_read == [t["number"] for t in snap["threads"]] and reused == []


def test_unchanged_thread_reuses_its_reading_and_is_guarded_again(tmp_path, snap, good):
    cache = ReadingCache(tmp_path, snap["repo"], CFG)
    assert cache.update(snap["threads"], good) == len(good)
    cache.save()
    to_read, reused = ReadingCache(tmp_path, snap["repo"], CFG).split(snap["threads"])
    assert to_read == []
    assert [o.number for o in reused] == [t["number"] for t in snap["threads"]]
    assert all(o.source == "cache" and o.checked is not None and not o.checked.rejected for o in reused)


def test_changed_thread_is_read_again(tmp_path, snap, good):
    cache = ReadingCache(tmp_path, snap["repo"], CFG)
    cache.update(snap["threads"], good)
    cache.save()
    changed = copy.deepcopy(snap["threads"])
    changed[0]["updated_at"] = "2030-01-01T00:00:00Z"
    changed[1]["labels"] = [*changed[1]["labels"], "new-label"]
    to_read, reused = ReadingCache(tmp_path, snap["repo"], CFG).split(changed)
    assert to_read == [changed[0]["number"], changed[1]["number"]]
    assert len(reused) == len(changed) - 2


def test_rejected_failed_and_cached_readings_are_not_stored(tmp_path, snap, good):
    first = snap["threads"][0]["number"]
    planted = copy.deepcopy(good[0])
    planted.checked.problems.append("open_request_not_found")
    outcomes = [planted, ReadOutcome(snap["threads"][1]["number"], error="budget_stopped"),
                ReadOutcome(snap["threads"][2]["number"], checked=good[2].checked, source="cache")]
    cache = ReadingCache(tmp_path, snap["repo"], CFG)
    assert cache.update(snap["threads"], outcomes) == 0
    assert str(first) not in cache.entries


def test_closed_threads_are_dropped(tmp_path, snap, good):
    cache = ReadingCache(tmp_path, snap["repo"], CFG)
    cache.update(snap["threads"], good)
    cache.update(snap["threads"][1:], [])
    assert str(snap["threads"][0]["number"]) not in cache.entries


def test_disabled_cache_neither_reads_nor_writes(tmp_path, snap, good):
    cfg = dict(CFG, enabled=False)
    cache = ReadingCache(tmp_path, snap["repo"], cfg)
    cache.update(snap["threads"], good)
    cache.save()
    assert not (tmp_path / "state/readings").exists()


def test_second_sweep_sends_only_unread_threads_to_the_model(tmp_path, snap, good, monkeypatch):
    """A sweep stopped by the budget is finished by the next one; nothing is read twice."""
    calls: list[list[int]] = []
    by_number = {o.number: o for o in good}

    def fake_read(snapshot, numbers, **kwargs):
        numbers = list(numbers)
        calls.append(numbers)
        done = [by_number[n] for n in numbers[:4]]
        stopped = [ReadOutcome(n, error="budget_stopped") for n in numbers[4:]]
        return ReadReport(outcomes=done + stopped, session_id="s", stopped="limit" if stopped else None)

    monkeypatch.setattr(agents, "read_threads", fake_read)
    monkeypatch.setattr(agents, "write_agents_json", lambda root, models: root / "agents.json")
    now = datetime(2026, 11, 26, tzinfo=UTC)
    first = sweep.read_with_model(snap, now, tmp_path, CFG)
    second = sweep.read_with_model(snap, now, tmp_path, CFG)
    third = sweep.read_with_model(snap, now, tmp_path, CFG)
    numbers = [t["number"] for t in snap["threads"]]
    assert calls == [numbers, numbers[4:]]
    assert first.stopped == "limit" and second.stopped is None
    assert [o.number for o in third.outcomes] == numbers
    assert {o.source for o in third.outcomes} == {"cache"} and third.counts()["from_cache"] == len(numbers)
