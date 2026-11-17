"""ThreadState schema and the quote guard (H6), on the synthetic sandbox fixture."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from followthrough.state import QUOTE_MAX, ThreadState, parse_ts, verify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SNAP = json.loads((FIXTURES / "sandbox-repo.json").read_text(encoding="utf-8"))
GOLD = {s["number"]: s for s in json.loads((FIXTURES / "sandbox-states.json").read_text(encoding="utf-8"))["states"]}
THREADS = {t["number"]: t for t in SNAP["threads"]}


def _state(number: int, **changes) -> ThreadState:
    return ThreadState.model_validate({**GOLD[number], **changes})


@pytest.mark.parametrize("number", sorted(GOLD))
def test_hand_written_reading_passes_the_guard(number):
    checked = verify(_state(number), THREADS[number])
    assert checked.problems == []
    assert checked.state.waiting_on == GOLD[number]["waiting_on"]


def test_fake_quote_from_fixture_is_rejected_and_marked_unclear():
    fake = SNAP["fixture"]["fake_quote"]
    state = _state(fake["number"], open_request_quote=fake["quote"], open_request_at=fake["at"])
    checked = verify(state, THREADS[fake["number"]])
    assert checked.rejected
    assert "open_request_quote_not_found" in checked.problems
    assert checked.state.waiting_on == "unclear"


def test_real_quote_with_wrong_timestamp_is_rejected():
    checked = verify(_state(101, open_request_at="2026-11-02T10:00:01Z"), THREADS[101])
    assert checked.problems == ["open_request_time_mismatch"]
    assert checked.state.waiting_on == "unclear"


def test_quote_attributed_to_the_wrong_side_is_rejected():
    checked = verify(_state(101, open_request_by="contributor"), THREADS[101])
    assert checked.problems == ["open_request_role_mismatch"]


def test_quote_found_in_two_posts_is_ambiguous():
    thread = copy.deepcopy(THREADS[101])
    thread["comments"].append({**thread["comments"][0], "id": 9999, "created_at": "2026-11-03T10:00:00Z"})
    assert verify(_state(101), thread).problems == ["open_request_quote_ambiguous"]


def test_quote_in_the_opening_post_counts_with_the_thread_time():
    state = _state(101, open_request_quote="max_attempts = 2", open_request_by="contributor",
                   open_request_at=THREADS[101]["created_at"])
    assert verify(state, THREADS[101]).problems == []


def test_partial_request_is_rejected():
    assert verify(_state(101, open_request_at=None), THREADS[101]).problems == ["open_request_incomplete"]


def test_eta_without_its_quote_is_rejected():
    assert verify(_state(102, agreed_eta_quote=None), THREADS[102]).problems == ["eta_incomplete"]


def test_invented_eta_quote_is_rejected():
    checked = verify(_state(102, agreed_eta_quote="I will open a PR by 2026-11-15."), THREADS[102])
    assert checked.problems == ["eta_quote_not_found"]


def test_follow_up_time_must_be_a_maintainer_post():
    # 2026-10-31T14:05 is the contributor's own comment on #102, not a maintainer follow-up.
    checked = verify(_state(102, last_follow_up_at="2026-10-31T14:05:00Z"), THREADS[102])
    assert checked.problems == ["follow_up_time_not_found"]


def test_linked_pr_must_appear_in_the_snapshot():
    assert verify(_state(105), THREADS[105]).problems == []
    assert verify(_state(101, linked_pr=777), THREADS[101]).problems == ["linked_pr_not_found"]


def test_number_mismatch_is_rejected():
    assert verify(_state(101), THREADS[102]).problems == ["number_mismatch"]


def test_every_problem_is_counted():
    state = _state(101, open_request_at="2026-11-01T00:00:00Z", linked_pr=777)
    assert len(verify(state, THREADS[101]).problems) == 2


def test_schema_limits():
    with pytest.raises(ValidationError):
        _state(101, open_request_quote="x" * (QUOTE_MAX + 1))
    with pytest.raises(ValidationError):
        _state(101, confidence=1.5)
    with pytest.raises(ValidationError):
        _state(101, waiting_on="someone")
    with pytest.raises(ValidationError):
        ThreadState.model_validate({**GOLD[101], "extra_field": 1})


def test_parse_ts_requires_a_timezone():
    assert parse_ts("2026-11-02T10:00:00Z").isoformat() == "2026-11-02T10:00:00+00:00"
    with pytest.raises(ValueError):
        parse_ts("2026-11-02T10:00:00")
