"""Reader agents run end to end against a local fake Anthropic server: no network, no key."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fake_anthropic import FakeAnthropic
from followthrough import agents, config
from followthrough.spend import Spend

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
STATES = {s["number"]: s for s in json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text())["states"]}
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
# OpenMinion's memory layer (sophiagraph) accepts session scopes matching this pattern only.
SCOPE = re.compile(r"^(session|agent|project|global):[A-Za-z0-9._:-]+$")


def _answer(number: int) -> str:
    return json.dumps(STATES[number])


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    servers = []

    def _run(numbers, answer=_answer, usage=None, status=200, budget=None, submit=None):
        fake = FakeAnthropic(answer, usage=usage, status=status, submit=submit)
        servers.append(fake)
        path = agents.write_agents_json(tmp_path, base_url=fake.base_url)
        spend = Spend(tmp_path, "test-sweep", budget=budget)
        report = agents.read_threads(SNAPSHOT, numbers, config_path=path, spend=spend, now=NOW, timeout_s=60)
        return report, fake, spend

    yield _run
    for fake in servers:
        fake.close()


def test_session_id_is_a_valid_memory_scope():
    sid = agents.session_id("openminion/openminion", NOW)
    assert sid == "sweep:openminion__openminion:20261120"
    assert SCOPE.match(f"session:{sid}")
    assert SCOPE.match(f"session:{agents.thread_session_id(sid, 101)}")


def test_agents_json_comes_from_models_toml(tmp_path):
    models = config.load("models")
    path = agents.write_agents_json(tmp_path, base_url="http://127.0.0.1:9/v1")
    data = json.loads(path.read_text())
    assert path == tmp_path / models["agents_json"]
    assert set(data["agents"]) == {"reader", "drafter"} and data["default_agent"] == "reader"
    assert {a["provider"] for a in data["agents"].values()} == {models["provider"]}
    provider = data["providers"][models["provider"]]
    assert provider["model"] == models["profiles"]["reader"]["model"]
    assert provider["base_url"] == "http://127.0.0.1:9/v1"
    assert provider["api_key"] == ""  # the key is read from the environment, never written
    assert Path(data["storage"]["path"]).parent == path.parent


def test_thread_view_keeps_order_roles_and_times_only():
    thread = next(t for t in SNAPSHOT["threads"] if t["number"] == 101)
    view = agents.thread_view(thread)
    assert [p["created_at"] for p in view["posts"]] == [thread["created_at"]] + [
        c["created_at"] for c in thread["comments"]]
    assert view["posts"][0]["role"] == "contributor" and view["posts"][1]["role"] == "maintainer"
    assert "login" not in json.dumps(view)


def test_get_thread_is_a_read_only_tool_over_the_snapshot():
    served: list[int] = []
    get_thread = agents.make_get_thread({t["number"]: t for t in SNAPSHOT["threads"]}, served)
    assert get_thread.tool_decl.name == "get_thread"
    assert get_thread(101)["number"] == 101
    assert "error" in get_thread(999)
    assert served == [101, 999]


def test_submit_reading_captures_typed_fields():
    captured: dict = {}
    submit = agents.make_submit_reading(captured)
    assert submit.tool_decl.name == "submit_reading"
    submit(**STATES[101])
    assert agents._from_tool(captured[101]).model_dump(mode="json") == STATES[101]
    assert agents._from_tool({"number": 1}) is None and agents._from_tool(None) is None


def test_every_fixture_thread_is_read_by_its_own_subagent(run):
    numbers = [t["number"] for t in SNAPSHOT["threads"]]
    report, fake, spend = run(numbers)
    assert [o.number for o in report.outcomes] == numbers
    assert sorted(report.tool_calls) == numbers  # get_thread called once per thread
    for outcome in report.outcomes:
        assert outcome.checked is not None and not outcome.checked.rejected, outcome.number
        assert outcome.checked.state.model_dump(mode="json") == STATES[outcome.number]
    counts = report.counts()
    assert counts["read"] == 6 and counts["guard_rejected"] == 0 and counts["failed"] == 0
    assert counts["from_output_type"] == 6
    assert counts["usd"] > 0 and counts["estimated_turns"] == 0
    assert spend.sweep_usd == pytest.approx(counts["usd"], abs=1e-6)
    assert {r["model"] for r in fake.requests} == {config.load("models")["profiles"]["reader"]["model"]}


def test_fake_quote_bad_reply_and_missing_telemetry_in_one_sweep(run):
    """One runtime, four threads: a planted quote, a prose reply, a prose reply after a typed
    submit_reading call, and a clean reading; the provider sends 0 tokens."""
    fake_quote = SNAPSHOT["fixture"]["fake_quote"]
    planted, prose, submitted, clean = fake_quote["number"], 106, 104, 103

    def answer(number):
        if number == planted:
            return json.dumps(dict(STATES[number], open_request_quote=fake_quote["quote"]))
        if number in (prose, submitted):
            return "I think the contributor is waiting."
        return json.dumps(STATES[number])

    def submit(number):
        return json.dumps(STATES[number]) if number == submitted else None

    report, _, spend = run([planted, prose, submitted, clean], answer=answer, submit=submit,
                           usage={"input_tokens": 0, "output_tokens": 0})
    by = {o.number: o for o in report.outcomes}
    assert by[planted].checked.rejected and by[planted].checked.state.waiting_on == "unclear"
    assert by[prose].checked is None and by[prose].error == "invalid_output"
    assert by[clean].checked is not None and not by[clean].checked.rejected
    assert by[clean].source == "output_type"
    assert by[submitted].source == "submit_reading" and not by[submitted].checked.rejected
    assert by[submitted].checked.state.model_dump(mode="json") == STATES[submitted]
    for outcome in report.outcomes:  # no telemetry: every turn is estimated, and still costs money
        assert outcome.cost.estimated and outcome.cost.usd > 0
    assert by[clean].cost.input_tokens > 0
    counts = report.counts()
    assert (counts["read"], counts["guard_rejected"], counts["failed"], counts["estimated_turns"]) == (3, 1, 1, 4)
    assert (counts["from_output_type"], counts["from_submit_reading"]) == (2, 1)
    assert spend.sweep_usd == pytest.approx(counts["usd"], abs=1e-6)


def test_provider_failure_is_counted_not_raised(run):
    report, _, _ = run([106], status=500)
    assert report.outcomes[0].error == "provider_error"
    assert report.counts()["failed"] == 1


def test_budget_stop_happens_before_any_model_request(run):
    budget = dict(config.load("budget"), usd_max_per_sweep=0.001)
    report, fake, spend = run([101, 102], budget=budget)
    assert fake.requests == []
    assert report.stopped and all(o.error == "budget_stopped" for o in report.outcomes)
    assert spend.sweep_usd == 0
