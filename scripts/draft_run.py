"""Draft follow-ups once over the synthetic fixture with the configured drafter model, and report.

Usage: uv run python scripts/draft_run.py [--fixture fixtures/sandbox-repo.json] [--now ISO]
Readings come from the saved fixture states (the reader is measured separately), so this run measures
the drafter alone. Needs ANTHROPIC_API_KEY. Spend is booked in the budget ledger. Prints one JSON
object (counts, words and problem codes per draft; fixture threads are synthetic). Drafts are saved
under out/<date>/drafts/ only when they pass the checks; nothing is posted.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from followthrough import agents, config, drafter, sweep
from followthrough.spend import Spend
from followthrough.state import parse_ts

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="fixtures/sandbox-repo.json")
    parser.add_argument("--states", default="fixtures/sandbox-states.json")
    parser.add_argument("--now", default=None)
    args = parser.parse_args()
    snapshot = json.loads((ROOT / args.fixture).read_text(encoding="utf-8"))
    if not snapshot.get("fixture", {}).get("synthetic"):
        print("refusing: this script only runs on synthetic fixtures", file=sys.stderr)
        return 2
    states = json.loads((ROOT / args.states).read_text(encoding="utf-8"))
    now = parse_ts(args.now or snapshot["fixture"]["now"])
    started = datetime.now(UTC)
    models = config.load("models")
    report = sweep.read_with_states(snapshot, states)
    decisions = [d for _, d in sweep.decide_all(snapshot, report, now, config.load("policy"))]
    path = agents.write_agents_json(ROOT, models)
    spend = Spend(ROOT, f"drafts:{started:%Y%m%dT%H%M%SZ}")
    out = drafter.draft_all(snapshot["repo"], decisions, config_path=path, spend=spend, now=now, root=ROOT)
    rows = [{"number": o.number, "action": o.action, "saved": o.path is not None, "source": o.source, "problems": o.problems,
             "words": drafter.words(o.path.read_text(encoding="utf-8")) if o.path else None,
             "input_tokens": o.cost.input_tokens if o.cost else 0,
             "output_tokens": o.cost.output_tokens if o.cost else 0,
             "estimated": o.cost.estimated if o.cost else None, "raw": o.raw[:600]} for o in out]
    result = {"model": models["profiles"]["drafter"]["model"], "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
              "drafts": len(out), "saved": sum(1 for o in out if o.path), "sweep_usd": round(spend.sweep_usd, 6),
              "ledger_total_usd": round(spend.total_usd, 6), "threads": rows}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
