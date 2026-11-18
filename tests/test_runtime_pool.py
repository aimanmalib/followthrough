"""Readers in parallel: each worker owns a runtime, so no two turns share one at the same time.

OpenMinion 0.1.23 holds a runtime's tool-registry lock for a whole turn when the agent has decorated
tools, so readers sharing one runtime ran one at a time; runtimes sharing one SQLite file failed with
"database is locked" (ADR 0010). The fakes below have no lock; they
record which runtime each turn used and fail the test if two turns overlap on one runtime.
"""

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from followthrough import agents, config, sweep
from followthrough.spend import Spend

ROOT = Path(__file__).resolve().parents[1]
BUDGET = {"usd_max_per_sweep": 1.0, "usd_max_total": 20.0, "spend_ledger": "state/spend.json",
          "chars_per_token_estimate": 4, "turn_reserve_usd": 0.0}


class FakeRuntime:
    created: list["FakeRuntime"] = []

    def __init__(self, path=None):
        self.path = path
        self.busy = 0
        self.closed = False
        FakeRuntime.created.append(self)

    @classmethod
    def from_config_path(cls, path, logging_mode=None):
        return cls(path)

    def close(self):
        self.closed = True


class FakeParent:
    def __init__(self, runtime, **kwargs):
        self.runtime = runtime


class Result:
    def __init__(self, output):
        self.output, self.text, self.stats = output, "{}", {"input_tokens": 10, "output_tokens": 2}


def test_parallel_readers_never_share_a_runtime(tmp_path, monkeypatch):
    FakeRuntime.created = []
    lock = threading.Lock()
    overlaps: list[int] = []
    peak = [0, 0]  # running now, most at once
    snap = json.loads((ROOT / "fixtures/sandbox-repo.json").read_text(encoding="utf-8"))
    states = {s["number"]: s for s in json.loads((ROOT / "fixtures/sandbox-states.json").read_text())["states"]}

    def fake_subagent(parent, *, name, output_type, **kwargs):
        number = int(name.split("-")[1])

        class Child:
            def run(self, message, **kw):
                runtime = parent.runtime
                with lock:
                    runtime.busy += 1
                    peak[0] += 1
                    peak[1] = max(peak[1], peak[0])
                    if runtime.busy > 1:
                        overlaps.append(number)
                time.sleep(0.05)
                with lock:
                    runtime.busy -= 1
                    peak[0] -= 1
                return Result(output_type.model_validate(states[number]))

        return Child()

    monkeypatch.setattr(agents, "APIRuntime", FakeRuntime)
    monkeypatch.setattr(agents, "Agent", FakeParent)
    monkeypatch.setattr(agents, "subagent", fake_subagent)
    models = dict(config.load("models"), max_concurrency=3, agents_json="state/agents.json")
    config_path = agents.write_agents_json(tmp_path, models)
    report = agents.read_threads(snap, [t["number"] for t in snap["threads"]], config_path=config_path,
                                 spend=Spend(tmp_path, "pool", budget=BUDGET), now=datetime(2026, 11, 26, tzinfo=UTC),
                                 models=models)
    assert len(report.outcomes) == len(snap["threads"]) and all(o.checked for o in report.outcomes)
    assert overlaps == []
    assert peak[1] > 1  # the turns did run in parallel
    assert len(FakeRuntime.created) == 3 and all(r.closed for r in FakeRuntime.created)
    stores = {json.loads(Path(r.path).read_text())["storage"]["path"] for r in FakeRuntime.created}
    assert len(stores) == 3  # one SQLite file per runtime: shared files fail with "database is locked"


def test_a_storage_error_fails_one_reading_not_the_sweep(tmp_path, monkeypatch):
    import sqlite3

    snap = json.loads((ROOT / "fixtures/sandbox-repo.json").read_text(encoding="utf-8"))
    states = {s["number"]: s for s in json.loads((ROOT / "fixtures/sandbox-states.json").read_text())["states"]}
    first = snap["threads"][0]["number"]

    def fake_subagent(parent, *, name, output_type, **kwargs):
        number = int(name.split("-")[1])

        class Child:
            def run(self, message, **kw):
                if number == first:
                    raise sqlite3.OperationalError("database is locked")
                return Result(output_type.model_validate(states[number]))

        return Child()

    monkeypatch.setattr(agents, "APIRuntime", FakeRuntime)
    monkeypatch.setattr(agents, "Agent", FakeParent)
    monkeypatch.setattr(agents, "subagent", fake_subagent)
    models = dict(config.load("models"), max_concurrency=2, agents_json="state/agents.json")
    report = agents.read_threads(snap, [t["number"] for t in snap["threads"]],
                                 config_path=agents.write_agents_json(tmp_path, models),
                                 spend=Spend(tmp_path, "pool", budget=BUDGET), now=datetime(2026, 11, 26, tzinfo=UTC),
                                 models=models)
    errors = {o.number: o.error for o in report.outcomes}
    assert errors[first] == "provider_error"
    assert sum(1 for o in report.outcomes if o.checked) == len(snap["threads"]) - 1


def test_no_turn_starts_after_the_deadline(tmp_path, monkeypatch):
    snap = json.loads((ROOT / "fixtures/sandbox-repo.json").read_text(encoding="utf-8"))
    started: list[str] = []

    def fake_subagent(parent, *, name, **kwargs):
        started.append(name)
        raise AssertionError("no turn may start after the deadline")

    monkeypatch.setattr(agents, "APIRuntime", FakeRuntime)
    monkeypatch.setattr(agents, "Agent", FakeParent)
    monkeypatch.setattr(agents, "subagent", fake_subagent)
    models = dict(config.load("models"), max_concurrency=2, agents_json="state/agents.json")
    until = sweep.deadline(time.monotonic() - 3600, max_minutes=20, turn_timeout_s=240)
    report = agents.read_threads(snap, [t["number"] for t in snap["threads"]],
                                 config_path=agents.write_agents_json(tmp_path, models),
                                 spend=Spend(tmp_path, "pool", budget=BUDGET), now=datetime(2026, 11, 26, tzinfo=UTC),
                                 models=models, deadline=until)
    assert started == [] and report.stopped == until.message and "16.0" in until.message
    assert {o.error for o in report.outcomes} == {"budget_stopped"}


def test_deadline_leaves_room_for_one_turn():
    until = sweep.deadline(100.0, max_minutes=20, turn_timeout_s=240)
    assert until.at == 100.0 + 16 * 60
    assert sweep.deadline(0.0, max_minutes=1, turn_timeout_s=240).at == 0.0
