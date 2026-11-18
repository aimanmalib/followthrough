"""Per-turn telemetry: numbers only, model turns only, written next to the digest."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from followthrough import cli, config, telemetry
from followthrough.agents import ReadOutcome
from followthrough.drafter import DraftOutcome
from followthrough.spend import TurnCost
from followthrough.state import Checked, ThreadState, parse_ts

NOW = parse_ts("2026-11-20T09:00:00Z")
KEYS = config.load("ops")["telemetry"]["stat_keys"]
THREAD_TEXT = "please rebase onto main, the CI is red"


def _state(number: int) -> ThreadState:
    return ThreadState(number=number, kind="defect", waiting_on="contributor",
                       confidence=0.8)


def _cost(usd: float = 0.01, estimated: bool = False) -> TurnCost:
    return TurnCost("claude-haiku-5-5", 1200, 80, usd, estimated)


def _reads() -> list[ReadOutcome]:
    return [
        ReadOutcome(1, checked=Checked(_state(1)), cost=_cost(), source="output_type",
                    stats={"llm_calls": 2, "tool_calls": 1, "transcript": THREAD_TEXT, "cached": True}),
        ReadOutcome(2, checked=Checked(_state(2), ["quote_not_found"]), cost=_cost(0.02, True),
                    source="submit_reading", raw=THREAD_TEXT),
        ReadOutcome(3, error="provider_error", cost=_cost(0.005)),
        ReadOutcome(4, checked=Checked(_state(4))),  # saved reading, no model turn
    ]


def test_turns_and_totals():
    drafts = [DraftOutcome(1, "FOLLOW_UP_DUE", path=Path("out/x/1.md"), cost=_cost(0.03), source="output_type"),
              DraftOutcome(2, "TAKEOVER_ALLOWED", problems=[f"mentions {THREAD_TEXT}"], cost=_cost(0.04))]
    data = telemetry.build("sweep:o__r:20261120", NOW, _reads(), drafts, KEYS)
    assert [(r["kind"], r["number"], r["ok"]) for r in data["turns"]] == [
        ("reader", 1, True), ("reader", 2, False), ("reader", 3, False),
        ("drafter", 1, True), ("drafter", 2, False)]
    totals = data["totals"]
    assert totals["turns"] == 5 and totals["by_kind"] == {"reader": 3, "drafter": 2}
    assert totals["ok"] == 2 and totals["estimated_turns"] == 1
    assert totals["input_tokens"] == 5 * 1200 and totals["output_tokens"] == 5 * 80
    assert totals["usd"] == round(0.01 + 0.02 + 0.005 + 0.03 + 0.04, 6)
    assert data["turns"][0]["stats"] == {"llm_calls": 2, "tool_calls": 1}
    assert data["turns"][1]["problems"] == ["quote_not_found"]
    assert data["turns"][4]["problems"] == ["other"]


def test_no_thread_text_or_reply_is_copied():
    drafts = [DraftOutcome(9, "FOLLOW_UP_DUE", problems=[THREAD_TEXT], cost=_cost(), raw=THREAD_TEXT)]
    dumped = json.dumps(telemetry.build("s", NOW, _reads(), drafts, KEYS))
    assert THREAD_TEXT not in dumped


def test_saved_readings_are_not_turns():
    reads = [ReadOutcome(4, checked=Checked(_state(4))), SimpleNamespace(number=5)]
    data = telemetry.build("s", NOW, reads, [SimpleNamespace(number=6, path=None)], KEYS)
    assert data["turns"] == [] and data["totals"]["turns"] == 0


def test_fixture_sweep_writes_telemetry_next_to_digest(tmp_path: Path, capsys):
    assert cli.main(["sweep", "--fixture", "--out", str(tmp_path)]) == cli.EXIT_OK
    folder = next(tmp_path.iterdir())
    data = json.loads((folder / "telemetry.json").read_text(encoding="utf-8"))
    assert (folder / "digest.json").exists()
    assert data["totals"]["turns"] == 0 and data["session_id"]
