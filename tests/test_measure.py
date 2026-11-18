"""metrics.json: counts only, limits checked, and the method log stays separate."""

import json
from datetime import UTC, datetime, timedelta

from followthrough import measure
from followthrough.agents import ReadOutcome
from followthrough.state import Checked, ThreadState

LIMITS = {"max_minutes": 20, "usd_max_per_sweep": 1.0}
START = datetime(2026, 11, 18, 2, 0, tzinfo=UTC)


def _state(number: int) -> ThreadState:
    return ThreadState(number=number, kind="other", waiting_on="maintainer", confidence=0.9)


def _outcomes() -> list[ReadOutcome]:
    return [ReadOutcome(1, checked=Checked(_state(1)), source="output_type"),
            ReadOutcome(2, checked=Checked(_state(2), ["eta_not_found"]), source="output_type"),
            ReadOutcome(3, checked=Checked(_state(3)), source="cache"),
            ReadOutcome(4, checked=Checked(_state(4), ["eta_not_found"]), source="cache"),
            ReadOutcome(5, error="provider_error")]


def _digest(stopped=None):
    return {"threads": 5, "counts": {"FOLLOW_UP_DUE": 1, "NO_ACTION": 4}, "read_failed": 1, "stopped": stopped}


def _build(seconds=60, usd=0.5, requests=(("GET", "/repos/o/r/issues", 200),), stopped=None):
    return measure.build(repo="o/r", mode="live", started=START, finished=START + timedelta(seconds=seconds),
                         digest=_digest(stopped), outcomes=_outcomes(), reading={"usd": usd, "stopped": stopped},
                         requests=list(requests), limits=LIMITS)


def test_guard_rates_overall_and_fresh():
    guard = measure.guard_stats(_outcomes())
    assert guard["checked"] == 4 and guard["rejected"] == 2 and guard["rejection_rate"] == 0.5
    assert guard["fresh_checked"] == 2 and guard["fresh_rejected"] == 1 and guard["fresh_rejection_rate"] == 0.5
    assert guard["problems"] == {"eta_not_found": 2}


def test_no_readings_gives_no_rate():
    assert measure.guard_stats([])["rejection_rate"] is None


def test_within_limits():
    ok = _build()
    assert ok["seconds"] == 60.0 and ok["within_limits"] == {"minutes": True, "usd": True, "writes": True,
                                                              "completed": True}
    late = _build(seconds=20 * 60 + 1, usd=1.01, stopped="limit")
    assert late["within_limits"] == {"minutes": False, "usd": False, "writes": True, "completed": False}
    assert late["stopped_by_budget"] is True and "stopped" not in late["reading"]


def test_any_non_get_request_fails_the_write_check():
    bad = _build(requests=[("GET", "/a", 200), ("POST", "/b", 201)])
    assert bad["http"]["non_get"] == 1 and bad["http"]["by_method"] == {"GET": 1, "POST": 1}
    assert bad["within_limits"]["writes"] is False


def test_fixture_sweep_has_no_http_section():
    fixture = measure.build(repo="o/r", mode="fixture", started=START, finished=START, digest=_digest(),
                            outcomes=[], reading=None, requests=None, limits=LIMITS)
    assert fixture["http"] is None and fixture["usd"] == 0.0 and fixture["within_limits"]["writes"] is True


def test_metrics_carry_no_thread_numbers_and_log_is_separate(tmp_path):
    requests = [("GET", "/repos/o/r/issues/77/comments", 304), ("GET", "/repos/o/r/issues", 200)]
    metrics = _build(requests=requests)
    path = measure.write(tmp_path, metrics, "metrics.json", requests, "http-log.json")
    text = path.read_text(encoding="utf-8")
    assert "77" not in text and '"number"' not in text
    assert json.loads(text)["http"]["by_status"] == {"200": 1, "304": 1}
    log = json.loads((tmp_path / "http-log.json").read_text(encoding="utf-8"))
    assert log[0] == {"method": "GET", "path": "/repos/o/r/issues/77/comments", "status": 304}


def test_fixture_sweep_writes_metrics(tmp_path, capsys):
    from followthrough import cli

    assert cli.main(["sweep", "--fixture", "--out", str(tmp_path)]) == 0
    folder = next(tmp_path.iterdir())
    metrics = json.loads((folder / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["mode"] == "fixture" and metrics["http"] is None and metrics["threads"] >= 6
    assert metrics["guard"]["checked"] == metrics["threads"] and not (folder / "http-log.json").exists()
