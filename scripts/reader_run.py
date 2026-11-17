"""Run the reader agents once over the synthetic fixture with the configured model, and report.

Usage: uv run python scripts/reader_run.py [--fixture fixtures/sandbox-repo.json] [--now ISO]
Needs ANTHROPIC_API_KEY in the environment. Spend is booked in the budget ledger (config/budget.toml).
Prints one JSON object: aggregate counts, plus a per-thread comparison with the hand-written reading
(fixture threads are synthetic, so this is safe to publish). Also written to out/<date>/fixture-run.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from followthrough import agents, config
from followthrough.spend import Spend
from followthrough.state import parse_ts

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default="fixtures/sandbox-repo.json")
    parser.add_argument("--states", default="fixtures/sandbox-states.json")
    parser.add_argument("--now", default=None)
    parser.add_argument("--concurrency", type=int, default=None, help="override max_concurrency for this run")
    args = parser.parse_args()
    snapshot = json.loads((ROOT / args.fixture).read_text(encoding="utf-8"))
    if not snapshot.get("fixture", {}).get("synthetic"):
        print("refusing: this script only runs on synthetic fixtures", file=sys.stderr)
        return 2
    expected = {s["number"]: s for s in json.loads((ROOT / args.states).read_text(encoding="utf-8"))["states"]}
    now = parse_ts(args.now or snapshot["fixture"]["now"])
    started = datetime.now(UTC)
    models = config.load("models")
    if args.concurrency:
        models = dict(models, max_concurrency=args.concurrency)
    path = agents.write_agents_json(ROOT, models)
    spend = Spend(ROOT, f"fixture:{started:%Y%m%dT%H%M%SZ}")
    report = agents.read_threads(snapshot, [t["number"] for t in snapshot["threads"]],
                                 config_path=path, spend=spend, now=now, models=models)
    rows = []
    for outcome in report.outcomes:
        got = outcome.checked.state if outcome.checked else None
        rows.append({"number": outcome.number, "expected_waiting_on": expected[outcome.number]["waiting_on"],
                     "got_waiting_on": got.waiting_on if got else None, "problems": outcome.problems,
                     "llm_calls": outcome.stats.get("llm_calls"),
                     "input_tokens": outcome.cost.input_tokens if outcome.cost else 0,
                     "output_tokens": outcome.cost.output_tokens if outcome.cost else 0,
                     "estimated": outcome.cost.estimated if outcome.cost else None,
                     "raw": outcome.raw[:600]})
    result = {"model": models["profiles"]["reader"]["model"], "provider": models["provider"],
              "max_concurrency": models["max_concurrency"],
              "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
              "counts": report.counts(), "sweep_usd": round(spend.sweep_usd, 6),
              "ledger_total_usd": round(spend.total_usd, 6), "threads": rows}
    out = ROOT / "out" / f"{started:%Y-%m-%d}" / "fixture-run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
