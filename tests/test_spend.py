"""Budget holds, real-cost settlement, estimates, and the persisted ledger."""

from __future__ import annotations

import json

import pytest

from followthrough import config
from followthrough.spend import BudgetExceeded, Spend, price

MODEL = config.load("models")["profiles"]["reader"]["model"]


def _budget(**changes):
    return dict(config.load("budget"), **changes)


def test_price_uses_prices_toml():
    row = config.load("prices")["models"][MODEL]
    assert price(config.load("prices"), MODEL, 1_000_000, 1_000_000) == pytest.approx(
        row["input_per_mtok"] + row["output_per_mtok"])


def test_unpriced_model_is_refused():
    with pytest.raises(BudgetExceeded):
        price(config.load("prices"), "no-such-model", 1, 1)


def test_settle_books_real_tokens_and_saves(tmp_path):
    spend = Spend(tmp_path, "s1")
    held = spend.hold()
    cost = spend.settle(held, MODEL, {"input_tokens": 2000, "output_tokens": 300, "llm_calls": 2}, 999, 99)
    assert not cost.estimated and (cost.input_tokens, cost.output_tokens) == (2000, 300)
    saved = json.loads((tmp_path / config.load("budget")["spend_ledger"]).read_text())
    assert saved["total_usd"] == pytest.approx(cost.usd)
    assert saved["sweeps"][-1]["id"] == "s1" and saved["sweeps"][-1]["turns"] == 1


def test_zero_tokens_are_estimated_from_characters_per_call(tmp_path):
    spend = Spend(tmp_path, "s1")
    per = config.load("budget")["chars_per_token_estimate"]
    cost = spend.settle(spend.hold(), MODEL, {"input_tokens": 0, "output_tokens": 0, "llm_calls": 3}, 400 * per, 10 * per)
    assert cost.estimated and (cost.input_tokens, cost.output_tokens) == (1200, 10)


def test_hold_refuses_to_cross_the_sweep_limit(tmp_path):
    budget = _budget(usd_max_per_sweep=0.05, turn_reserve_usd=0.02)
    spend = Spend(tmp_path, "s1", budget=budget)
    spend.hold()
    spend.hold()
    with pytest.raises(BudgetExceeded):
        spend.hold()  # 0.06 held would pass 0.05


def test_reserve_grows_to_the_largest_turn_seen(tmp_path):
    spend = Spend(tmp_path, "s1", budget=_budget(usd_max_per_sweep=1.0, turn_reserve_usd=0.0001))
    cost = spend.settle(spend.hold(), MODEL, {"input_tokens": 1_000_000, "output_tokens": 0}, 0, 0)
    assert spend.hold() == pytest.approx(cost.usd)


def test_total_limit_counts_earlier_sweeps(tmp_path):
    budget = _budget(usd_max_total=0.03, turn_reserve_usd=0.02)
    first = Spend(tmp_path, "s1", budget=budget)
    first.forfeit(first.hold(), MODEL)
    second = Spend(tmp_path, "s2", budget=budget)
    assert second.total_usd == pytest.approx(0.02)
    with pytest.raises(BudgetExceeded):
        second.hold()


def test_failed_turn_is_booked_at_its_reserve(tmp_path):
    spend = Spend(tmp_path, "s1", budget=_budget(turn_reserve_usd=0.02))
    cost = spend.forfeit(spend.hold(), MODEL)
    assert cost.estimated and cost.usd == pytest.approx(0.02) and spend.sweep_usd == pytest.approx(0.02)
