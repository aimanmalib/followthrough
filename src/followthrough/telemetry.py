"""Per-turn telemetry for one sweep: out/<YYYY-MM-DD>/telemetry.json (product requirement 4.8).

One record per model turn (reader or drafter): model, tokens, USD, whether tokens were estimated,
which path produced the result, and the numeric OpenMinion run stats named in config/ops.toml.
Thread text and model replies are never copied; problem entries are kept only when they are codes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


def _codes(problems: Iterable[str]) -> list[str]:
    return [p if CODE.match(p) else "other" for p in problems]


def _stats(stats: Mapping[str, Any], keys: Sequence[str]) -> dict[str, float | int]:
    return {k: stats[k] for k in keys
            if isinstance(stats.get(k), (int, float)) and not isinstance(stats.get(k), bool)}


def turn(kind: str, outcome: Any, stat_keys: Sequence[str]) -> dict[str, Any]:
    """Record for one reader (`ReadOutcome`) or drafter (`DraftOutcome`) turn."""
    cost = outcome.cost
    problems = list(getattr(outcome, "problems", []) or [])
    if kind == "drafter":
        ok = getattr(outcome, "path", None) is not None
    else:
        ok = outcome.checked is not None and not outcome.checked.rejected
    record: dict[str, Any] = {
        "kind": kind,
        "number": outcome.number,
        "ok": ok,
        "source": outcome.source,
        "problems": _codes(problems),
        "model": cost.model if cost else None,
        "input_tokens": cost.input_tokens if cost else 0,
        "output_tokens": cost.output_tokens if cost else 0,
        "usd": round(cost.usd, 6) if cost else 0.0,
        "estimated": bool(cost.estimated) if cost else False,
    }
    record["stats"] = _stats(getattr(outcome, "stats", {}) or {}, stat_keys)
    return record


def build(session_id: str, now: datetime, reads: Iterable[Any], drafts: Iterable[Any],
          stat_keys: Sequence[str]) -> dict[str, Any]:
    """Telemetry for a sweep. Only model turns count: readings loaded from a file have no cost."""
    turns = [turn("reader", o, stat_keys) for o in reads if getattr(o, "cost", None) is not None]
    turns += [turn("drafter", o, stat_keys) for o in drafts if getattr(o, "cost", None) is not None]
    by_kind: dict[str, int] = {}
    for record in turns:
        by_kind[record["kind"]] = by_kind.get(record["kind"], 0) + 1
    return {
        "session_id": session_id,
        "as_of": now.isoformat(),
        "turns": turns,
        "totals": {
            "turns": len(turns),
            "by_kind": by_kind,
            "ok": sum(1 for r in turns if r["ok"]),
            "input_tokens": sum(r["input_tokens"] for r in turns),
            "output_tokens": sum(r["output_tokens"] for r in turns),
            "estimated_turns": sum(1 for r in turns if r["estimated"]),
            "usd": round(sum(r["usd"] for r in turns), 6),
        },
    }


def write(folder: Path, data: Mapping[str, Any], filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path
