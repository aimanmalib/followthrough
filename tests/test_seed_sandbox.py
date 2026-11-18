"""scripts/seed_sandbox.py: sandbox-only, synthetic-only, and idempotent. `gh` is faked."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("seed_sandbox", ROOT / "scripts" / "seed_sandbox.py")
seed_sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_sandbox)

SANDBOX = "aimanmalib/followthrough-sandbox"
THREAD = next(t for t in json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text())["threads"]
              if t["number"] == 101)


class FakeGh:
    def __init__(self, issues=None, comments=None):
        self.calls, self.issues, self.comments = [], issues or [], comments or []

    def __call__(self, args):
        self.calls.append(list(args))
        verb = args[1]
        if verb == "list":
            return json.dumps(self.issues)
        if verb == "create":
            return f"https://github.com/{SANDBOX}/issues/3\n"
        if verb == "view":
            return json.dumps({"comments": [{"body": b} for b in self.comments]})
        return ""

    def writes(self):
        return [c for c in self.calls if c[1] in ("create", "comment")]


def test_shipped_config_names_only_the_sandbox():
    assert seed_sandbox.sandbox_repo(seed_sandbox.config.load("safety")) == SANDBOX


@pytest.mark.parametrize("repos", [[], [SANDBOX, "openminion/openminion"]])
def test_needs_exactly_one_repo(repos):
    with pytest.raises(SystemExit):
        seed_sandbox.sandbox_repo({"allow_post_repos": repos})


def test_first_run_creates_the_issue_and_its_comments():
    fake = FakeGh()
    out = seed_sandbox.seed(THREAD, SANDBOX, fake)
    assert out == {"repo": SANDBOX, "number": 3, "created": True, "comments_posted": len(THREAD["comments"])}
    assert all(c[c.index("-R") + 1] == SANDBOX for c in fake.writes())
    assert THREAD["body"] in fake.writes()[0][fake.writes()[0].index("--body") + 1]


def test_second_run_writes_nothing():
    bodies = [seed_sandbox.comment_body(c) for c in THREAD["comments"]]
    fake = FakeGh(issues=[{"number": 3, "title": THREAD["title"]}], comments=bodies)
    out = seed_sandbox.seed(THREAD, SANDBOX, fake)
    assert out["created"] is False and out["comments_posted"] == 0 and fake.writes() == []


def test_lookup_does_not_use_the_lagging_search_index():
    fake = FakeGh()
    seed_sandbox.seed(THREAD, SANDBOX, fake)
    assert "--search" not in fake.calls[0]


def test_similar_title_is_not_reused():
    fake = FakeGh(issues=[{"number": 9, "title": THREAD["title"] + " (old)"}])
    assert seed_sandbox.seed(THREAD, SANDBOX, fake)["created"] is True


def test_non_synthetic_fixture_is_refused(tmp_path):
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"fixture": {"synthetic": False}, "threads": [THREAD]}))
    with pytest.raises(SystemExit):
        seed_sandbox.main(["--fixture", str(real)])
