"""One sweep: snapshot -> readings -> guard -> rules -> digest.

Two readers produce the same `ReadOutcome`s:
- "model": one OpenMinion subagent per thread (`agents.read_threads`), spend booked in the ledger;
- "states": hand-written readings from a file (the synthetic fixture's expected answers), so the whole
  pipeline runs offline, without a key, in tests and public CI.
Either way every reading passes the quote guard (`state.verify`) before the rules see it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from followthrough import agents, config
from followthrough.agents import ReadOutcome, ReadReport
from followthrough.rules import Decision, decide
from followthrough.spend import Spend
from followthrough.state import ThreadState, verify


def read_with_states(snapshot: Mapping[str, Any], states_doc: Mapping[str, Any]) -> ReadReport:
    """Readings from a states file, guarded exactly like model readings. Missing thread = read failure."""
    states = {s["number"]: s for s in states_doc["states"]}
    outcomes = []
    for thread in snapshot["threads"]:
        raw = states.get(thread["number"])
        if raw is None:
            outcomes.append(ReadOutcome(thread["number"], error="no_reading", source="states"))
            continue
        state = ThreadState.model_validate(raw)
        outcomes.append(ReadOutcome(thread["number"], checked=verify(state, thread), source="states"))
    return ReadReport(outcomes=outcomes, session_id="states")


def read_with_model(snapshot: Mapping[str, Any], now: datetime, root: Path) -> ReadReport:
    """One subagent per thread with the configured reader model; stops at the budget limits."""
    models = config.load("models")
    path = agents.write_agents_json(root, models)
    spend = Spend(root, agents.session_id(snapshot["repo"], now))
    return agents.read_threads(snapshot, [t["number"] for t in snapshot["threads"]],
                               config_path=path, spend=spend, now=now, models=models)


def decide_all(snapshot: Mapping[str, Any], report: ReadReport, now: datetime,
               policy: Mapping[str, Any]) -> list[tuple[ReadOutcome, Decision | None]]:
    """The rules' decision for every reading; None where the thread could not be read at all."""
    threads = {t["number"]: t for t in snapshot["threads"]}
    release = snapshot.get("latest_release")
    return [(o, decide(o.checked.state, threads[o.number], now, policy, release) if o.checked else None)
            for o in report.outcomes]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
