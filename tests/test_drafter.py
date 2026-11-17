"""Drafts: which threads get one, what the drafter may see, and the checks before a draft is saved."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fake_anthropic import FakeAnthropic
from followthrough import agents, config, drafter, sweep
from followthrough.rules import FOLLOW_UP_DUE, MAINTAINER_REPLY_PENDING, NO_ACTION, Decision
from followthrough.spend import Spend
from followthrough.state import parse_ts

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
STATES = json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text(encoding="utf-8"))
NOW = parse_ts(SNAPSHOT["fixture"]["now"])
DRAFTS = config.load("drafts")
MAX_WORDS = config.load("models")["profiles"]["drafter"]["max_words"]


def _decisions() -> list[Decision | None]:
    report = sweep.read_with_states(SNAPSHOT, STATES)
    return [d for _, d in sweep.decide_all(SNAPSHOT, report, NOW, config.load("policy"))]


def _good_body(decision: Decision) -> str:
    dates = " and ".join(drafter.facts(decision, DRAFTS)["dates"].values())
    tag = f" in {decision.release_tag}" if decision.release_tag else ""
    return f"Hello, per the CONTRIBUTING follow-up step, checking in{tag}: relevant dates {dates}."


def test_every_draft_action_has_a_contributing_step():
    actions = set(DRAFTS["actions"])
    assert actions and actions <= set(DRAFTS["steps"])
    assert MAINTAINER_REPLY_PENDING not in actions and NO_ACTION not in actions


def test_fixture_draft_actions_are_the_expected_set():
    wanted = sorted(d.action for d in _decisions() if drafter.needs_draft(d, DRAFTS))
    assert wanted and set(wanted) <= set(DRAFTS["actions"])
    assert all(not drafter.needs_draft(d, DRAFTS) for d in _decisions()
               if d is None or d.action not in DRAFTS["actions"])


def test_facts_carry_no_thread_text():
    texts = [c["body"] for t in SNAPSHOT["threads"] for c in t["comments"]] + [t["body"] for t in SNAPSHOT["threads"]]
    for d in _decisions():
        if drafter.needs_draft(d, DRAFTS):
            blob = json.dumps(drafter.facts(d, DRAFTS))
            assert not any(len(x) > 20 and x[:40] in blob for x in texts)


def test_check_flags_length_missing_dates_and_mentions():
    d = Decision(5, FOLLOW_UP_DUE, "request_unanswered", {"requested_on": date(2026, 11, 2), "due_on": date(2026, 11, 9)})
    assert drafter.check(_good_body(d), d, DRAFTS, MAX_WORDS) == []
    assert "too_long" in drafter.check(_good_body(d) + " word" * MAX_WORDS, d, DRAFTS, MAX_WORDS)
    assert drafter.check("Checking in on 2026-11-02.", d, DRAFTS, MAX_WORDS) == ["missing_date:due_on"]
    assert "mention" in drafter.check(_good_body(d) + " cc @someone", d, DRAFTS, MAX_WORDS)
    assert "mention" not in drafter.check(_good_body(d) + " mail a@b.example", d, DRAFTS, MAX_WORDS)


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    servers = []

    def _run(answer, calls=None):
        fake = FakeAnthropic(answer, calls=calls)
        servers.append(fake)
        path = agents.write_agents_json(tmp_path, base_url=fake.base_url)
        out = drafter.draft_all(SNAPSHOT["repo"], _decisions(), config_path=path,
                                spend=Spend(tmp_path, "test-drafts"), now=NOW, root=tmp_path, timeout_s=60)
        return out, fake

    yield _run
    for fake in servers:
        fake.close()


def test_one_drafter_per_draft_action_and_files_saved(run, tmp_path):
    by_number = {d.number: d for d in _decisions() if drafter.needs_draft(d, DRAFTS)}
    out, fake = run(lambda n: json.dumps({"number": n, "body": _good_body(by_number[n])}))
    assert sorted(o.number for o in out) == sorted(by_number)
    assert all(o.problems == [] and o.path and o.path.is_file() for o in out)
    assert all(o.path.parent == tmp_path / "out" / NOW.strftime("%Y-%m-%d") / DRAFTS["subdir"] for o in out)
    models = {r["model"] for r in fake.requests}
    assert models == {config.load("models")["profiles"]["drafter"]["model"]}


def test_a_bad_draft_is_not_saved(run):
    out, _ = run(lambda n: json.dumps({"number": n, "body": "Any update? @someone"}))
    assert out and all(o.path is None for o in out)
    assert all("mention" in o.problems and any(p.startswith("missing_date") for p in o.problems) for o in out)


def test_typed_submit_rescues_a_reply_that_does_not_validate(run):
    import re
    by_number = {d.number: d for d in _decisions() if drafter.needs_draft(d, DRAFTS)}

    def submit(text):
        n = int(re.search(r"#(\d+)", text).group(1))
        return {"number": n, "body": _good_body(by_number[n])}

    out, _ = run(lambda n: "Here is the draft you asked for.", calls={"submit_draft": submit})
    assert out and all(o.source == "submit_draft" and o.path and o.problems == [] for o in out)


def test_no_reply_and_no_submit_is_counted_not_saved(run):
    out, _ = run(lambda n: "Here is the draft you asked for.")
    assert out and all(o.problems == ["invalid_output"] and o.path is None for o in out)
