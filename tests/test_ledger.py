"""Reminder ledger (H3): no repeated reminder for an unchanged thread; exactly one when one thread changes."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from followthrough import cli, config, drafter, ledger, sweep
from followthrough.ledger import Ledger, state_hash
from followthrough.state import parse_ts

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
STATES = json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text(encoding="utf-8"))
NOW = parse_ts(SNAPSHOT["fixture"]["now"])
POLICY = config.load("policy")
DRAFTS = config.load("drafts")
EXPIRY = int(POLICY["ledger"]["expiry_days"])


def _rows(snapshot=SNAPSHOT, now=NOW):
    return sweep.decide_all(snapshot, sweep.read_with_states(snapshot, STATES), now, POLICY)


def _needing(snapshot=SNAPSHOT):
    return sorted(d.number for _, d in _rows(snapshot) if d and d.action in DRAFTS["actions"])


class FakeDrafter:
    """Stands in for the model drafter: records what it was asked for, 'saves' unless told to fail."""

    def __init__(self, fail: frozenset[int] = frozenset()):
        self.calls: list[list[int]] = []
        self.fail = fail

    def __call__(self, todo):
        self.calls.append([d.number for d in todo])
        return [SimpleNamespace(number=d.number, path=None if d.number in self.fail else Path(f"{d.number}.md"))
                for d in todo]


def _sweep(book, snapshot=SNAPSHOT, now=NOW, fake=None):
    fake = fake or FakeDrafter()
    plan, outcomes = sweep.draft_new(snapshot, _rows(snapshot, now), book, now, DRAFTS["actions"], fake)
    return plan, outcomes, fake


@pytest.fixture
def book(tmp_path):
    with Ledger(tmp_path / "ledger.db", prefix=POLICY["ledger"]["namespace_prefix"], expiry_days=EXPIRY) as b:
        yield b


def _changed(snapshot, number):
    """Copy of the snapshot where one thread got a new label and a later updated_at (rules unaffected)."""
    out = copy.deepcopy(snapshot)
    thread = next(t for t in out["threads"] if t["number"] == number)
    thread["labels"] = [*thread["labels"], "touched"]
    thread["updated_at"] = "2026-11-12T08:00:00Z"
    return out


def test_fixture_has_threads_that_need_drafts():
    assert len(_needing()) >= 2


def test_second_sweep_without_changes_drafts_nothing(book):
    plan, outcomes, _fake = _sweep(book)
    assert [o.number for o in outcomes] == _needing()
    assert set(plan.verdicts.values()) == {ledger.NEW}
    plan2, outcomes2, fake2 = _sweep(book)
    assert outcomes2 == [] and fake2.calls == []
    assert set(plan2.verdicts.values()) == {ledger.UNCHANGED}
    assert book.count(SNAPSHOT["repo"]) == len(_needing())


def test_one_changed_thread_gets_exactly_one_draft(book):
    _sweep(book)
    first = _needing()[0]
    plan, outcomes, fake = _sweep(book, _changed(SNAPSHOT, first))
    assert fake.calls == [[first]]
    assert [o.number for o in outcomes] == [first]
    assert plan.verdicts[first] == ledger.CHANGED
    _, again, _fake = _sweep(book, _changed(SNAPSHOT, first))
    assert again == []


def test_failed_draft_is_not_recorded_and_is_retried(book):
    target = _needing()[0]
    _sweep(book, fake=FakeDrafter(fail=frozenset({target})))
    assert book.get(SNAPSHOT["repo"], target) is None
    _, outcomes, fake = _sweep(book)
    assert fake.calls == [[target]] and [o.number for o in outcomes] == [target]


def test_reminder_expires_after_configured_days(book):
    repo, thread = SNAPSHOT["repo"], SNAPSHOT["threads"][0]
    digest = state_hash(thread)
    book.record(repo, thread["number"], digest, "FOLLOW_UP_DUE", NOW, "s")
    just_inside = NOW + timedelta(days=EXPIRY) - timedelta(seconds=1)
    assert book.verdict(repo, thread["number"], digest, "FOLLOW_UP_DUE", just_inside) == ledger.UNCHANGED
    at_expiry = NOW + timedelta(days=EXPIRY)
    assert book.verdict(repo, thread["number"], digest, "FOLLOW_UP_DUE", at_expiry) == ledger.EXPIRED


def test_changed_action_allows_a_new_draft(book):
    repo, thread = SNAPSHOT["repo"], SNAPSHOT["threads"][0]
    digest = state_hash(thread)
    book.record(repo, thread["number"], digest, "FOLLOW_UP_DUE", NOW, "s")
    assert book.verdict(repo, thread["number"], digest, "FOLLOW_UP_DUE", NOW) == ledger.UNCHANGED
    assert book.verdict(repo, thread["number"], digest, "TAKEOVER_ALLOWED", NOW) == ledger.ACTION_CHANGED


def test_repos_do_not_share_reminders(book):
    thread = SNAPSHOT["threads"][0]
    book.record("a/one", thread["number"], state_hash(thread), "FOLLOW_UP_DUE", NOW, "s")
    assert book.verdict("a/two", thread["number"], state_hash(thread), "FOLLOW_UP_DUE", NOW) == ledger.NEW


@pytest.mark.parametrize("change", [
    lambda t: t.update(updated_at="2030-01-01T00:00:00Z"),
    lambda t: t["comments"].append({"body": "x"}),
    lambda t: t.update(labels=[*t["labels"], "new"]),
])
def test_state_hash_follows_updated_at_comments_and_labels(change):
    thread = copy.deepcopy(SNAPSHOT["threads"][0])
    before = state_hash(thread)
    change(thread)
    assert state_hash(thread) != before


def test_state_hash_ignores_label_order_and_text():
    thread = copy.deepcopy(SNAPSHOT["threads"][0])
    thread["labels"] = ["b", "a"]
    other = copy.deepcopy(thread)
    other["labels"] = ["a", "b"]
    other["title"] = "different"
    assert state_hash(thread) == state_hash(other)


def test_ledger_stores_no_thread_text(tmp_path):
    path = tmp_path / "ledger.db"
    with Ledger(path, prefix="followthrough", expiry_days=EXPIRY) as book:
        _sweep(book)
    with sqlite3.connect(path) as db:
        dump = "\n".join(db.iterdump())
    for thread in SNAPSHOT["threads"]:
        assert thread["title"] not in dump
        for comment in thread["comments"]:
            assert comment["body"][:40] not in dump


def test_expiry_must_be_positive(tmp_path):
    with pytest.raises(ValueError):
        Ledger(tmp_path / "x.db", prefix="p", expiry_days=0)


def test_cli_draft_twice_saves_once(tmp_path, monkeypatch, capsys):
    """`sweep --draft` end to end, drafter replaced: the second run saves nothing."""
    env = config.load("models")["key_env"]
    monkeypatch.setenv(env, "test-key-not-real")
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    fake = FakeDrafter()
    monkeypatch.setattr(drafter, "draft_all", lambda repo, todo, **kw: fake(list(todo)))
    argv = ["sweep", "--fixture", str(ROOT / POLICY["sweep"]["fixture"]), "--states",
            str(ROOT / POLICY["sweep"]["fixture_states"]), "--out", str(tmp_path / "out"),
            "--format", "json", "--draft"]
    results = []
    for _ in range(2):
        assert cli.main(argv) == cli.EXIT_OK
        results.append(json.loads(capsys.readouterr().out)["drafts"])
    assert results[0]["saved"] == len(_needing()) and results[1]["saved"] == 0
    assert results[1]["ledger"] == {ledger.UNCHANGED: len(_needing())}
    assert (tmp_path / POLICY["ledger"]["path"]).exists()


def test_cli_draft_without_key_refuses(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(config.load("models")["key_env"], raising=False)
    monkeypatch.setattr(drafter, "draft_all", lambda *a, **k: pytest.fail("drafter must not run"))
    assert cli.main(["sweep", "--fixture", "--draft", "--out", str(tmp_path)]) == cli.EXIT_USAGE
