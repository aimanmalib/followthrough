"""Spend ledger and hard budget for model calls.

Limits come from config/budget.toml and prices from config/prices.toml. Before each reader turn the
sweep holds back a reserve (the largest turn cost seen so far, at least `turn_reserve_usd`); if the
reserve would cross either limit the turn is not started. After the turn the real cost replaces the
reserve. When the provider reports 0 tokens, tokens are estimated from characters and the turn is
marked `estimated` so the report can say so.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from followthrough import config


class BudgetExceeded(Exception):
    """Starting another model turn could cross a spend limit."""


@dataclass(frozen=True)
class TurnCost:
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    estimated: bool


def price(prices: Mapping[str, Any], model: str, input_tokens: int, output_tokens: int) -> float:
    try:
        row = prices["models"][model]
    except KeyError:
        raise BudgetExceeded(config.t("budget.unpriced_model", model=model)) from None
    return (input_tokens * row["input_per_mtok"] + output_tokens * row["output_per_mtok"]) / 1_000_000


class Spend:
    """Thread-safe spend ledger for one sweep, persisted to `spend_ledger` (JSON)."""

    def __init__(self, root: Path, sweep_id: str, budget: Mapping[str, Any] | None = None,
                 prices: Mapping[str, Any] | None = None) -> None:
        self.budget = budget or config.load("budget")
        self.prices = prices or config.load("prices")
        self.path = root / self.budget["spend_ledger"]
        self.sweep_id = sweep_id
        self._lock = threading.Lock()
        self._data = self._load()
        self._sweep = {"id": sweep_id, "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "usd": 0.0, "turns": 0, "estimated_turns": 0}
        self._data["sweeps"].append(self._sweep)
        self._held = 0.0
        self._reserve = float(self.budget["turn_reserve_usd"])

    def _load(self) -> dict[str, Any]:
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("sweeps", [])
            data.setdefault("total_usd", 0.0)
            return data
        return {"total_usd": 0.0, "sweeps": []}

    @property
    def total_usd(self) -> float:
        return self._data["total_usd"]

    @property
    def sweep_usd(self) -> float:
        return self._sweep["usd"]

    def hold(self) -> float:
        """Reserve money for one turn; BudgetExceeded if the reserve would cross a limit."""
        with self._lock:
            amount = self._reserve
            sweep_after = self._sweep["usd"] + self._held + amount
            total_after = self._data["total_usd"] + self._held + amount
            if sweep_after > self.budget["usd_max_per_sweep"]:
                raise BudgetExceeded(config.t("budget.sweep_limit", limit=self.budget["usd_max_per_sweep"],
                                              spent=round(self._sweep["usd"], 4)))
            if total_after > self.budget["usd_max_total"]:
                raise BudgetExceeded(config.t("budget.total_limit", limit=self.budget["usd_max_total"],
                                              spent=round(self._data["total_usd"], 4)))
            self._held += amount
            return amount

    def settle(self, held: float, model: str, stats: Mapping[str, Any], chars_in: int, chars_out: int) -> TurnCost:
        """Replace a hold with the real cost of the turn, and save the ledger."""
        tokens_in = int(stats.get("input_tokens") or 0)
        tokens_out = int(stats.get("output_tokens") or 0)
        estimated = tokens_in == 0 and tokens_out == 0
        if estimated:
            per = self.budget["chars_per_token_estimate"]
            calls = max(1, int(stats.get("llm_calls") or 1))
            tokens_in = calls * chars_in // per
            tokens_out = chars_out // per
        usd = price(self.prices, model, tokens_in, tokens_out)
        with self._lock:
            self._held -= held
            self._reserve = max(self._reserve, usd)
            self._sweep["usd"] += usd
            self._sweep["turns"] += 1
            self._sweep["estimated_turns"] += int(estimated)
            self._data["total_usd"] += usd
            self._save()
        return TurnCost(model, tokens_in, tokens_out, usd, estimated)

    def forfeit(self, held: float, model: str) -> TurnCost:
        """Book a failed turn at its full reserve: it may have been billed, and we cannot tell how much."""
        with self._lock:
            self._held -= held
            self._sweep["usd"] += held
            self._sweep["turns"] += 1
            self._sweep["estimated_turns"] += 1
            self._data["total_usd"] += held
            self._save()
        return TurnCost(model, 0, 0, held, True)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self._data, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
