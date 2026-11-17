"""Deterministic rules (product requirement 4.7): every action, day boundaries, dates carried."""

from __future__ import annotations

import ast
import copy
import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from followthrough import config, rules
from followthrough.rules import decide
from followthrough.state import ThreadState, parse_ts, verify

ROOT = Path(__file__).resolve().parents[1]
SNAP = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
GOLD = {s["number"]: s for s in json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text(encoding="utf-8"))["states"]}
THREADS = {t["number"]: t for t in SNAP["threads"]}
NOW = parse_ts(SNAP["fixture"]["now"])
POLICY = config.load("policy")
RELEASE = SNAP["latest_release"]


def _decide(number, now=NOW, policy=POLICY, thread=None, **changes):
    state = ThreadState.model_validate({**GOLD[number], **changes})
    thread = thread or THREADS[number]
    return decide(verify(state, thread).state, thread, now, policy, RELEASE)


@pytest.mark.parametrize("number", sorted(THREADS))
def test_fixture_expected_action(number):
    assert _decide(number).action == SNAP["fixture"]["expected"][str(number)]


def test_every_action_is_covered_by_the_fixture():
    assert set(SNAP["fixture"]["expected"].values()) == set(rules.ACTIONS)


def test_follow_up_due_carries_the_dates_to_state():
    d = _decide(101)
    assert d.reason == "request_unanswered"
    assert d.dates == {"requested_on": date(2026, 11, 2), "follow_up_on": date(2026, 11, 20),
                       "takeover_from": date(2026, 11, 23)}


def test_passed_eta_is_follow_up_due():
    d = _decide(102)
    assert (d.action, d.reason, d.dates["agreed_eta"]) == ("FOLLOW_UP_DUE", "eta_passed", date(2026, 11, 12))


def test_eta_not_yet_passed_is_no_action():
    assert _decide(102, now=datetime(2026, 11, 12, 23, 59, tzinfo=UTC)).action == "NO_ACTION"
    assert _decide(102, now=datetime(2026, 11, 13, 0, 0, tzinfo=UTC)).action == "FOLLOW_UP_DUE"


def test_takeover_dates_follow_the_follow_up():
    d = _decide(103)
    assert d.dates["followed_up_on"] == date(2026, 11, 10)
    assert d.dates["takeover_from"] == date(2026, 11, 13)


def test_follow_up_within_its_window_is_no_action():
    d = _decide(103, now=datetime(2026, 11, 12, 23, 59, tzinfo=UTC))
    assert (d.action, d.reason) == ("NO_ACTION", "follow_up_sent")
    assert _decide(103, now=datetime(2026, 11, 13, 0, 0, tzinfo=UTC)).action == "TAKEOVER_ALLOWED"


def test_contributor_reply_after_follow_up_stops_takeover():
    thread = copy.deepcopy(THREADS[103])
    thread["comments"].append({"id": 1, "created_at": "2026-11-12T09:00:00Z", "body": "Rebasing now.",
                               "author": {"login": "contributor-sam", "association": "CONTRIBUTOR", "maintainer": False}})
    assert _decide(103, thread=thread).action == "NO_ACTION"


@pytest.mark.parametrize(("now", "expected"), [
    (datetime(2026, 11, 8, 23, 59, 59, tzinfo=UTC), "NO_ACTION"),       # request 2026-11-02 + 7 days = 2026-11-09
    (datetime(2026, 11, 9, 0, 0, 0, tzinfo=UTC), "FOLLOW_UP_DUE"),
    # 2026-11-09 07:00 at UTC+8 is still 2026-11-08 in UTC: windows are counted in UTC days.
    (datetime(2026, 11, 9, 7, 0, tzinfo=timezone(timedelta(hours=8))), "NO_ACTION"),
])
def test_follow_up_day_boundary(now, expected):
    assert _decide(101, now=now).action == expected


def test_maintainer_reply_day_boundary():
    # Contributor asked 2026-11-06; maintainer reply window 7 days -> pending from 2026-11-13.
    assert _decide(104, now=datetime(2026, 11, 12, 23, 59, tzinfo=UTC)).action == "NO_ACTION"
    d = _decide(104, now=datetime(2026, 11, 13, 0, 0, tzinfo=UTC))
    assert d.action == "MAINTAINER_REPLY_PENDING"
    assert d.dates == {"asked_on": date(2026, 11, 6), "reply_due": date(2026, 11, 13)}


def test_windows_come_from_policy():
    policy = copy.deepcopy(POLICY)
    policy["windows"]["follow_up_days"] = 30
    assert _decide(101, policy=policy).action == "NO_ACTION"
    policy["windows"]["maintainer_reply_days"] = 30
    assert _decide(104, policy=policy).action == "NO_ACTION"


def test_ready_to_verify_needs_label_merge_and_release():
    d = _decide(105)
    assert (d.release_tag, d.dates) == ("v0.4.2", {"released_on": date(2026, 11, 18)})
    for change in ({"in_latest_release": False}, {"merged": False}):
        thread = copy.deepcopy(THREADS[105])
        thread["linked_prs"][0].update(change)
        assert _decide(105, thread=thread).action == "NO_ACTION"
    thread = copy.deepcopy(THREADS[105])
    thread["labels"] = []
    assert _decide(105, thread=thread).action == "NO_ACTION"


def test_rejected_reading_gives_no_action():
    fake = SNAP["fixture"]["fake_quote"]
    d = _decide(fake["number"], open_request_quote=fake["quote"], open_request_at=fake["at"])
    assert (d.action, d.reason) == ("NO_ACTION", "unclear")


def test_naive_clock_is_refused():
    with pytest.raises(ValueError):
        _decide(101, now=datetime(2026, 11, 20, 9, 0))


@pytest.mark.parametrize("lang", config.LANGS)
@pytest.mark.parametrize("number", sorted(THREADS))
def test_every_decision_renders_in_both_languages(lang, number):
    d = _decide(number)
    strings = config.strings(lang)
    assert strings[f"actions.{d.action}"]
    assert strings[f"reasons.{d.reason}"].format(release_tag=d.release_tag, **d.dates)


def test_no_window_numbers_in_rules_module():
    tree = ast.parse((ROOT / "src" / "followthrough" / "rules.py").read_text(encoding="utf-8"))
    numbers = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
               and isinstance(n.value, int) and not isinstance(n.value, bool)]
    assert numbers == []
