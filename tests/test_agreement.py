"""Label agreement (H2): set selection, blind copies, scoring, the test-run limit and what is public."""

import copy
import json
from datetime import UTC, datetime

import pytest

from followthrough import agreement, config
from followthrough.agents import ReadOutcome
from followthrough.state import Checked, ThreadState

PREFIX = "status:"
MAPPING = {"status:a": "maintainer", "status:b": "contributor", "status:c": "release"}
TITLE = "Third-party title text"


def thread(number, labels, is_pr=False):
    return {"number": number, "title": TITLE, "is_pr": is_pr, "labels": labels, "body": "body"}


@pytest.fixture()
def snap():
    return {"repo": "o/r", "taken_at": "2026-11-18T00:00:00Z", "threads": [
        thread(1, ["status:a", "bug"]),
        thread(2, ["status:b"]),
        thread(3, ["status:c"]),
        thread(4, ["status:a"]),
        thread(5, ["status:a", "status:b"]),       # two status labels: not measured
        thread(6, ["status:unmapped"]),            # label not in the mapping: not measured
        thread(7, ["bug"]),                        # no status label
        thread(8, ["status:a"], is_pr=True),       # pull request: not measured
    ]}


def reading(number, waiting_on, problems=(), read_as=None):
    state = ThreadState(number=number, kind="defect", waiting_on=waiting_on, confidence=0.9)
    return ReadOutcome(number, checked=Checked(state, list(problems), read_as), source="test")


def test_labelled_keeps_issues_with_exactly_one_mapped_status_label(snap):
    assert agreement.labelled(snap, MAPPING, PREFIX) == {1: "maintainer", 2: "contributor", 3: "release",
                                                         4: "maintainer"}


def test_odd_is_dev_and_even_is_test():
    expected = {1: "x", 2: "y", 3: "z", 4: "w"}
    assert agreement.pick(expected, "dev", "odd") == {1: "x", 3: "z"}
    assert agreement.pick(expected, "test", "odd") == {2: "y", 4: "w"}
    assert agreement.pick(expected, "dev", "even") == {2: "y", 4: "w"}
    with pytest.raises(ValueError):
        agreement.pick(expected, "both", "odd")


def test_blind_copy_drops_status_labels_and_other_threads_without_touching_the_input(snap):
    before = copy.deepcopy(snap)
    copy_ = agreement.blind(snap, [1, 2], PREFIX)
    assert [t["number"] for t in copy_["threads"]] == [1, 2]
    assert copy_["threads"][0]["labels"] == ["bug"] and copy_["threads"][1]["labels"] == []
    assert snap == before


def test_score_counts_guarded_as_read_failed_and_confusion():
    expected = {1: "maintainer", 2: "contributor", 3: "release", 4: "maintainer"}
    outcomes = [reading(1, "maintainer"),
                reading(2, "unclear", ["follow_up_time_not_found"], read_as="contributor"),
                reading(3, "contributor"),
                ReadOutcome(4, error="time_limit")]
    result = agreement.score(expected, outcomes)
    assert (result.n, result.agree_guarded, result.agree_as_read) == (4, 1, 2)
    assert (result.failed, result.rejected) == (1, 1)
    assert result.confusion == {"maintainer": {"maintainer": 1, "failed": 1}, "contributor": {"unclear": 1},
                                "release": {"contributor": 1}}
    assert result.confusion_as_read["contributor"] == {"contributor": 1}


def test_issue_without_any_outcome_counts_as_failed():
    result = agreement.score({1: "maintainer"}, [])
    assert result.failed == 1 and result.rows[0]["problems"] == ["no_outcome"]


def test_guard_keeps_the_models_own_answer_when_it_rejects_a_reading():
    from followthrough.state import verify

    t = {"number": 9, "created_at": "2026-11-01T00:00:00Z", "body": "hello",
         "author": {"maintainer": False}, "comments": []}
    state = ThreadState(number=9, kind="defect", waiting_on="contributor", confidence=0.5,
                        last_follow_up_at=datetime(2026, 11, 2, tzinfo=UTC))
    checked = verify(state, t)
    assert checked.state.waiting_on == "unclear" and checked.read_as == "contributor"
    assert verify(state.model_copy(update={"last_follow_up_at": None}), t).read_as is None


def test_test_set_is_refused_past_the_run_limit_and_runs_are_counted_before_they_start(tmp_path):
    path = tmp_path / "runs.json"
    when = datetime(2026, 11, 18, tzinfo=UTC)
    assert agreement.RunLog(path).start("test", 2, when, "s") == 1
    assert agreement.RunLog(path).start("dev", 2, when, "s") == 1
    assert agreement.RunLog(path).start("test", 2, when, "s") == 2
    with pytest.raises(agreement.RunLimitReached):
        agreement.RunLog(path).start("test", 2, when, "s")
    assert agreement.RunLog(path).start("dev", 2, when, "s") == 2  # dev runs are not limited
    assert json.loads(path.read_text())["runs"][0] == {"set": "test", "started_at": "2026-11-18T00:00:00Z",
                                                       "snapshot": "s"}


def test_public_counts_hold_no_issue_numbers_or_text_and_private_list_holds_no_thread_text():
    expected = {101: "maintainer", 203: "contributor"}
    result = agreement.score(expected, [reading(101, "maintainer"), reading(203, "maintainer")])
    public = json.dumps(result.public())
    assert "101" not in public and "203" not in public and TITLE not in public
    assert result.public()["agreement_guarded"] == 0.5
    private = agreement.private_md("o/r", "dev", 1, result)
    assert "| 203 | contributor | maintainer | maintainer | no |" in private and TITLE not in private


def test_mapping_in_config_covers_the_waiting_on_values_the_reader_can_give():
    policy = config.load("policy")
    allowed = {"maintainer", "contributor", "release", "nobody", "unclear"}
    mapping = policy["labels"]["waiting_on"]
    assert mapping and set(mapping.values()) <= allowed
    assert all(label.startswith(policy["labels"]["status_prefix"]) for label in mapping)


def test_newest_snapshot(tmp_path):
    folder = tmp_path / "snaps" / "o__r"
    folder.mkdir(parents=True)
    for name in ("20261118T0100Z.json", "20261118T0200Z.json"):
        (folder / name).write_text("{}")
    assert agreement.newest_snapshot(tmp_path, "snaps", "o/r").name == "20261118T0200Z.json"
    assert agreement.newest_snapshot(tmp_path, "snaps", "x/y") is None


def test_run_reads_blind_writes_counts_and_private_list_and_stops_at_the_test_limit(tmp_path, snap, monkeypatch):
    from followthrough import agents
    from followthrough.agents import ReadReport

    seen = {}

    def fake_read(snapshot, numbers, **kwargs):
        seen["labels"] = [label for t in snapshot["threads"] for label in t["labels"]]
        seen["numbers"] = list(numbers)
        return ReadReport(outcomes=[reading(n, "contributor") for n in numbers], session_id="s")

    monkeypatch.setattr(agents, "read_threads", fake_read)
    path = tmp_path / "snap.json"
    rename = {"status:a": "status:maintainer-investigation", "status:b": "status:awaiting-contributor"}
    threads = [{**t, "labels": [rename.get(label, label) for label in t["labels"]]} for t in snap["threads"]]
    path.write_text(json.dumps({**snap, "threads": threads}))
    cfg = config.load("ops")["agreement"]
    out = tmp_path / "out"
    for _ in range(int(cfg["max_test_runs"])):
        assert agreement.run(which="test", snapshot_path=path, now=None, out_dir=out, root=tmp_path, lang="en") == 0
    assert seen["numbers"] == [2, 4] and not any(label.startswith("status:") for label in seen["labels"])
    written = json.loads(next(out.glob("*/agreement-test.json")).read_text())
    assert (written["n"], written["agree_guarded"], written["run"]) == (2, 1, 2)
    assert len(list((tmp_path / cfg["private_dir"]).glob("test-run*.md"))) == 2
    assert agreement.run(which="test", snapshot_path=path, now=None, out_dir=out, root=tmp_path, lang="en") == 2
