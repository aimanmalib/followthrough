"""Label agreement (H2): does the reader's `waiting_on` match the maintainers' own `status:*` label?

The measured set is every open issue (not pull request) with exactly one status label that
`[labels.waiting_on]` maps to an expected value. Odd numbers form the dev set (prompt tuning
allowed), even numbers the test set (read at most `max_test_runs` times, counted before a run
starts, so a crashed run still counts). The reader gets a copy of each thread with every status
label removed, so it has to work the answer out of the posts.

Two agreements are reported: "guarded" uses `waiting_on` after the quote guard (what the rules act
on; a rejected reading counts as "unclear"), "as read" uses the model's own answer. Only counts are
public; the per-issue list (numbers and our one-line verdict, never thread text) stays private.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from followthrough.agents import ReadOutcome

SETS = ("dev", "test")
FAILED = "failed"  # no reading at all (model error, budget or time limit)


class RunLimitReached(Exception):
    """The test set has already been read `max_test_runs` times."""


def labelled(snapshot: Mapping[str, Any], mapping: Mapping[str, str], prefix: str) -> dict[int, str]:
    """number -> expected waiting_on, for open issues with exactly one status label that is mapped."""
    out: dict[int, str] = {}
    for thread in snapshot["threads"]:
        if thread.get("is_pr"):
            continue
        status = [label for label in thread.get("labels", []) if label.startswith(prefix)]
        if len(status) == 1 and status[0] in mapping:
            out[thread["number"]] = mapping[status[0]]
    return out


def pick(expected: Mapping[int, str], which: str, dev_parity: str) -> dict[int, str]:
    """The dev or test half of `expected`, split on issue-number parity."""
    if which not in SETS or dev_parity not in ("odd", "even"):
        raise ValueError(f"set {which!r} / dev_parity {dev_parity!r}")
    dev_remainder = 1 if dev_parity == "odd" else 0
    want = dev_remainder if which == "dev" else 1 - dev_remainder
    return {n: v for n, v in expected.items() if n % 2 == want}


def blind(snapshot: Mapping[str, Any], numbers: Iterable[int], prefix: str) -> dict[str, Any]:
    """A copy of `snapshot` holding only `numbers`, with every status label removed."""
    keep = set(numbers)
    threads = [{**t, "labels": [label for label in t.get("labels", []) if not label.startswith(prefix)]}
               for t in snapshot["threads"] if t["number"] in keep]
    return {**snapshot, "threads": threads}


@dataclass
class Score:
    n: int = 0
    agree_guarded: int = 0
    agree_as_read: int = 0
    failed: int = 0
    rejected: int = 0
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)  # expected -> guarded reading -> count
    confusion_as_read: dict[str, dict[str, int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)  # private: one per issue

    def public(self) -> dict[str, Any]:
        """Counts only: no issue numbers, no text."""
        def rate(k: int) -> float | None:
            return round(k / self.n, 3) if self.n else None
        return {"n": self.n, "agree_guarded": self.agree_guarded, "agreement_guarded": rate(self.agree_guarded),
                "agree_as_read": self.agree_as_read, "agreement_as_read": rate(self.agree_as_read),
                "failed": self.failed, "guard_rejected": self.rejected,
                "confusion_guarded": self.confusion, "confusion_as_read": self.confusion_as_read}


def _bump(table: dict[str, dict[str, int]], expected: str, got: str) -> None:
    row = table.setdefault(expected, {})
    row[got] = row.get(got, 0) + 1


def score(expected: Mapping[int, str], outcomes: Iterable[ReadOutcome]) -> Score:
    """Compare readings with the expected values; an issue with no outcome counts as failed."""
    by_number = {o.number: o for o in outcomes}
    result = Score()
    for number in sorted(expected):
        want = expected[number]
        outcome = by_number.get(number)
        checked = outcome.checked if outcome else None
        guarded = checked.state.waiting_on if checked else FAILED
        as_read = (checked.read_as or checked.state.waiting_on) if checked else FAILED
        result.n += 1
        result.failed += guarded == FAILED
        result.rejected += bool(checked and checked.rejected)
        result.agree_guarded += guarded == want
        result.agree_as_read += as_read == want
        _bump(result.confusion, want, guarded)
        _bump(result.confusion_as_read, want, as_read)
        result.rows.append({"number": number, "expected": want, "guarded": guarded, "as_read": as_read,
                            "problems": outcome.problems if outcome else ["no_outcome"]})
    return result


class RunLog:
    """How many times each set has been read (state/, never tracked)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.runs: list[dict[str, Any]] = (json.loads(path.read_text(encoding="utf-8"))["runs"]
                                           if path.exists() else [])

    def count(self, which: str) -> int:
        return sum(1 for r in self.runs if r["set"] == which)

    def start(self, which: str, max_test_runs: int, when: datetime, snapshot_taken_at: str) -> int:
        """Record a run before it starts; refuse a test run past the limit. Returns the run number."""
        if which == "test" and self.count("test") >= max_test_runs:
            raise RunLimitReached(f"test set already read {self.count('test')} times")
        self.runs.append({"set": which, "started_at": when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "snapshot": snapshot_taken_at})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"runs": self.runs}, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        return self.count(which)


def private_md(repo: str, which: str, run: int, result: Score) -> str:
    """Per-issue list: number, expected, readings, guard problems. Our words only, never thread text."""
    lines = [f"# H2 {which} run {run}: {repo}", "",
             (f"n {result.n} · guarded {result.agree_guarded} · as read {result.agree_as_read} · "
              f"failed {result.failed} · guard rejected {result.rejected}"), "",
             "| # | expected | guarded | as read | match | guard problems |", "|---|---|---|---|---|---|"]
    for row in result.rows:
        match = "yes" if row["guarded"] == row["expected"] else ("as read" if row["as_read"] == row["expected"]
                                                                  else "no")
        lines.append(f"| {row['number']} | {row['expected']} | {row['guarded']} | {row['as_read']} | {match} | "
                     f"{', '.join(row['problems']) or '-'} |")
    return "\n".join(lines) + "\n"


def newest_snapshot(root: Path, snapshot_dir: str, repo: str) -> Path | None:
    owner, name = repo.split("/", 1)
    files = sorted((root / snapshot_dir / f"{owner}__{name}").glob("*.json"))
    return files[-1] if files else None


def run(*, which: str, snapshot_path: Path, now: datetime | None, out_dir: Path, root: Path, lang: str) -> int:
    """`followthrough agree`: read one set blind with the model, score it, write counts + private list."""
    import time

    from followthrough import agents, config, sweep
    from followthrough.spend import Spend
    from followthrough.state import parse_ts

    policy, models, cfg = config.load("policy"), config.load("models"), config.load("ops")["agreement"]
    snapshot = sweep.load_json(snapshot_path)
    prefix = policy["labels"]["status_prefix"]
    expected = pick(labelled(snapshot, policy["labels"]["waiting_on"], prefix), which, cfg["dev_parity"])
    if not expected:
        print(config.t("agree.empty", lang, set=which))
        return 2
    started = datetime.now(UTC)
    try:
        number = RunLog(root / cfg["runs_log"]).start(which, int(cfg["max_test_runs"]), started,
                                                      snapshot["taken_at"])
    except RunLimitReached:
        print(config.t("agree.run_limit", lang, limit=cfg["max_test_runs"]))
        return 2
    owner, name = snapshot["repo"].split("/", 1)
    spend = Spend(root, f"agree:{owner}__{name}:{which}:{started:%Y%m%dT%H%M%S}")
    timeout_s = float(models["profiles"]["reader"].get("timeout_s") or 0)
    report = agents.read_threads(blind(snapshot, expected, prefix), list(expected),
                                 config_path=agents.write_agents_json(root, models), spend=spend,
                                 now=now or parse_ts(snapshot["taken_at"]), models=models,
                                 deadline=sweep.deadline(time.monotonic(), cfg["max_minutes"], timeout_s))
    result = score(expected, report.outcomes)
    public = {"repo": snapshot["repo"], "set": which, "run": number, "snapshot_taken_at": snapshot["taken_at"],
              "reader_model": models["profiles"]["reader"]["model"], "status_labels_hidden": True,
              "usd": round(spend.sweep_usd, 4), "stopped": report.stopped, **result.public()}
    folder = out_dir / started.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / cfg["file"].format(set=which)).write_text(json.dumps(public, indent=1) + "\n", encoding="utf-8")
    private = root / cfg["private_dir"] / f"{which}-run{number}-{started:%Y%m%dT%H%MZ}.md"
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(private_md(snapshot["repo"], which, number, result), encoding="utf-8")
    print(config.t("agree.result", lang, set=which, run=number, n=result.n, guarded=result.agree_guarded,
                   as_read=result.agree_as_read, failed=result.failed, usd=public["usd"]))
    print(json.dumps(public, indent=1))
    return 3 if report.stopped else 0
