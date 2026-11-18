"""One sweep: snapshot -> readings -> guard -> rules -> digest.

Two readers produce the same `ReadOutcome`s:
- "model": one OpenMinion subagent per thread (`agents.read_threads`), spend booked in the ledger;
- "states": hand-written readings from a file (the synthetic fixture's expected answers), so the whole
  pipeline runs offline, without a key, in tests and public CI.
Either way every reading passes the quote guard (`state.verify`) before the rules see it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from followthrough import agents, config
from followthrough.agents import ReadOutcome, ReadReport
from followthrough.ledger import ALLOW, Ledger, state_hash
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


@dataclass
class DraftPlan:
    """Which draft-needing threads get a new draft this sweep, and why the others are held back."""

    todo: list[Decision] = field(default_factory=list)
    verdicts: dict[int, str] = field(default_factory=dict)  # number -> ledger verdict
    hashes: dict[int, str] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for verdict in self.verdicts.values():
            out[verdict] = out.get(verdict, 0) + 1
        return dict(sorted(out.items()))


def plan_drafts(snapshot: Mapping[str, Any], rows: Iterable[tuple[ReadOutcome, Decision | None]],
                ledger: Ledger, now: datetime, draft_actions: Iterable[str]) -> DraftPlan:
    """Ask the ledger about every decision whose action needs a draft; keep the ones it allows."""
    wanted = set(draft_actions)
    threads = {t["number"]: t for t in snapshot["threads"]}
    plan = DraftPlan()
    for _, decision in rows:
        if decision is None or decision.action not in wanted:
            continue
        digest = state_hash(threads[decision.number])
        verdict = ledger.verdict(snapshot["repo"], decision.number, digest, decision.action, now)
        plan.hashes[decision.number] = digest
        plan.verdicts[decision.number] = verdict
        if verdict in ALLOW:
            plan.todo.append(decision)
    return plan


DraftFn = Callable[[list[Decision]], Iterable[Any]]  # returns outcomes with .number and .path (None = not saved)


def draft_new(snapshot: Mapping[str, Any], rows: Iterable[tuple[ReadOutcome, Decision | None]],
              ledger: Ledger, now: datetime, draft_actions: Iterable[str], draft: DraftFn) -> tuple[DraftPlan, list[Any]]:
    """Draft only what the ledger allows, then remember each draft that was actually saved.

    A draft that failed its checks is not recorded, so the next sweep tries it again."""
    plan = plan_drafts(snapshot, rows, ledger, now, draft_actions)
    if not plan.todo:
        return plan, []
    actions = {d.number: d.action for d in plan.todo}
    sid = agents.session_id(snapshot["repo"], now)
    outcomes = list(draft(plan.todo))
    for outcome in outcomes:
        if getattr(outcome, "path", None) is not None and outcome.number in actions:
            ledger.record(snapshot["repo"], outcome.number, plan.hashes[outcome.number],
                          actions[outcome.number], now, sid)
    return plan, outcomes


def run_drafts(snapshot: Mapping[str, Any], rows: list[tuple[ReadOutcome, Decision | None]], now: datetime,
               root: Path, policy: Mapping[str, Any], models: Mapping[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    """The `sweep --draft` step: drafter subagents for what the ledger allows.

    Returns the counts for the digest and the outcomes (for telemetry)."""
    from followthrough import drafter

    drafts = config.load("drafts")
    path = agents.write_agents_json(root, models)
    spend = Spend(root, agents.session_id(snapshot["repo"], now))

    def draft(todo: list[Decision]) -> list[Any]:
        return drafter.draft_all(snapshot["repo"], todo, config_path=path, spend=spend, now=now, root=root,
                                 models=models, drafts=drafts, policy=policy)

    with Ledger.from_policy(root, policy) as ledger:
        plan, outcomes = draft_new(snapshot, rows, ledger, now, drafts["actions"], draft)
    return ({"ledger": plan.counts(), "saved": sum(1 for o in outcomes if o.path is not None),
             "not_saved": sum(1 for o in outcomes if o.path is None)}, outcomes)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
