"""Reading cache: a sweep sends to the model only the threads that changed since their last good reading.

One JSON file per repo under `[readings] cache_dir` (state/, never tracked). An entry holds the thread's
state hash (`ledger.state_hash`: updated_at, comment count, labels) and the reading that passed the quote
guard. A thread whose hash is unchanged reuses its reading, checked by the guard again against the new
snapshot; the rules then run with the new date, so waiting windows keep moving. Readings that failed or
were rejected by the guard are not kept, so the next sweep reads those threads again. When a sweep stops
at the budget limit, the threads it did not reach are read first by the next one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from followthrough.agents import ReadOutcome
from followthrough.ledger import state_hash
from followthrough.state import ThreadState, verify

CACHE_SCHEMA = 1
SOURCE = "cache"


class ReadingCache:
    def __init__(self, root: Path, repo: str, cfg: Mapping[str, Any]) -> None:
        owner, name = repo.split("/", 1)
        self.path = root / cfg["cache_dir"] / f"{owner}__{name}.json"
        self.enabled = bool(cfg.get("enabled", True))
        self.entries: dict[str, dict[str, Any]] = self._load() if self.enabled else {}

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return dict(data.get("threads", {})) if data.get("schema") == CACHE_SCHEMA else {}

    def split(self, threads: Iterable[Mapping[str, Any]]) -> tuple[list[int], list[ReadOutcome]]:
        """(numbers to read with the model, outcomes reused from the cache)."""
        to_read: list[int] = []
        reused: list[ReadOutcome] = []
        for thread in threads:
            entry = self.entries.get(str(thread["number"]))
            if entry is None or entry.get("hash") != state_hash(thread):
                to_read.append(thread["number"])
                continue
            state = ThreadState.model_validate(entry["state"])
            reused.append(ReadOutcome(thread["number"], checked=verify(state, thread), source=SOURCE))
        return to_read, reused

    def update(self, threads: Iterable[Mapping[str, Any]], outcomes: Iterable[ReadOutcome]) -> int:
        """Keep every fresh reading that passed the guard; drop threads that are no longer open."""
        by_number = {t["number"]: t for t in threads}
        kept = {k: v for k, v in self.entries.items() if int(k) in by_number}
        added = 0
        for outcome in outcomes:
            if outcome.source == SOURCE or outcome.checked is None or outcome.checked.rejected:
                continue
            kept[str(outcome.number)] = {"hash": state_hash(by_number[outcome.number]),
                                         "state": outcome.checked.state.model_dump(mode="json")}
            added += 1
        self.entries = kept
        return added

    def save(self) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"schema": CACHE_SCHEMA, "threads": self.entries}, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(tmp, self.path)
