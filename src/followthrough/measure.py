"""Sweep metrics (`metrics.json`): time, money, HTTP methods and the quote guard, as counts only.

Written next to the digest for every sweep. It holds no thread text, titles, logins or numbers, so the
aggregate can be published for a third-party repo (product requirement 4.10). The per-request method
log (`http-log.json`: method, API path without host or query, status) stays in the output folder, which is never tracked.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from followthrough.github import iso

METRICS_SCHEMA = 1


def guard_stats(outcomes: Iterable[Any]) -> dict[str, Any]:
    """Readings the quote guard checked and rejected, overall and for fresh (model) readings only."""
    checked = [o for o in outcomes if o.checked is not None]
    fresh = [o for o in checked if o.source != "cache"]

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    rejected = sum(1 for o in checked if o.checked.rejected)
    fresh_rejected = sum(1 for o in fresh if o.checked.rejected)
    return {"checked": len(checked), "rejected": rejected, "rejection_rate": rate(rejected, len(checked)),
            "fresh_checked": len(fresh), "fresh_rejected": fresh_rejected,
            "fresh_rejection_rate": rate(fresh_rejected, len(fresh)),
            "problems": dict(sorted(Counter(p for o in checked for p in o.checked.problems).items()))}


def http_stats(requests: Sequence[tuple[str, str, int]]) -> dict[str, Any]:
    methods = Counter(m for m, _, _ in requests)
    return {"requests": len(requests), "non_get": sum(n for m, n in methods.items() if m != "GET"),
            "by_method": dict(sorted(methods.items())),
            "by_status": {str(k): v for k, v in sorted(Counter(s for _, _, s in requests).items())}}


def build(*, repo: str, mode: str, started: datetime, finished: datetime, digest: Mapping[str, Any],
          outcomes: Sequence[Any], reading: Mapping[str, Any] | None, requests: Sequence[tuple[str, str, int]] | None,
          limits: Mapping[str, float]) -> dict[str, Any]:
    seconds = round((finished - started).total_seconds(), 1)
    usd = float((reading or {}).get("usd", 0.0))
    http = http_stats(requests) if requests is not None else None
    within = {"minutes": seconds <= limits["max_minutes"] * 60, "usd": usd <= limits["usd_max_per_sweep"],
              "writes": http is None or http["non_get"] == 0, "completed": not digest.get("stopped")}
    return {
        "schema": METRICS_SCHEMA, "repo": repo, "mode": mode,
        "started_at": iso(started), "finished_at": iso(finished), "seconds": seconds,
        "threads": digest["threads"], "actions": dict(digest["counts"]), "read_failed": digest["read_failed"],
        "reading": {k: v for k, v in (reading or {}).items() if k != "stopped"},
        "stopped_by_budget": bool(digest.get("stopped")),
        "guard": guard_stats(outcomes), "http": http, "usd": round(usd, 6),
        "limits": dict(limits), "within_limits": within,
    }


def write(folder: Path, metrics: Mapping[str, Any], filename: str,
          requests: Sequence[tuple[str, str, int]] | None = None, http_log: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if requests is not None and http_log:
        log = [{"method": m, "path": path, "status": s} for m, path, s in requests]
        (folder / http_log).write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
    path = folder / filename
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path

