"""Seed the private sandbox repository with one synthetic thread for the approval demo.

Usage: uv run python scripts/seed_sandbox.py [--thread 101]

Writes only to the single repository in config/safety.toml `allow_post_repos` (refuses otherwise),
through the `gh` CLI, so no token passes through this script. The thread text comes from
fixtures/sandbox-repo.json (invented people and text). Idempotent: an open issue with the same title
is reused, and its comments are not posted twice. Prints one JSON line: repo, number, created.

GitHub stamps every seeded post with the seeding time and the seeding account, so the demo sweep
moves its clock forward with `--now` (see docs/TEST-RESULTS.md, "Sandbox approval demo").
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from followthrough import config  # noqa: E402

Runner = Callable[[Sequence[str]], str]
LIST_LIMIT = "200"
MARK = "Synthetic thread for the Follow-Through approval demo"


def gh(args: Sequence[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def sandbox_repo(safety: Mapping[str, Any]) -> str:
    repos = list(safety["allow_post_repos"])
    if len(repos) != 1:
        raise SystemExit("allow_post_repos must name exactly one sandbox repository")
    return repos[0]


def issue_body(thread: Mapping[str, Any]) -> str:
    who = thread["author"]["login"]
    return f"{thread['body']}\n\n---\n_{MARK} (fixture #{thread['number']}; opened by `{who}`, a contributor)._"


def comment_body(comment: Mapping[str, Any]) -> str:
    role = "maintainer" if comment["author"]["maintainer"] else "contributor"
    return f"{comment['body']}\n\n---\n_Written by `{comment['author']['login']}`, a {role}._"


def seed(thread: Mapping[str, Any], repo: str, run: Runner = gh) -> dict[str, Any]:
    if thread.get("is_pr"):
        raise SystemExit("only issue threads can be seeded")
    # A plain listing, not --search: the search index lags new issues by minutes (measured: a second
    # run 10 s after the first created a duplicate).
    found = json.loads(run(["issue", "list", "-R", repo, "--state", "open", "--limit", LIST_LIMIT,
                            "--json", "number,title"]) or "[]")
    match = next((i for i in found if i["title"] == thread["title"]), None)
    created = match is None
    if created:
        url = run(["issue", "create", "-R", repo, "--title", thread["title"], "--body", issue_body(thread)]).strip()
        number = int(url.rstrip("/").rsplit("/", 1)[1])
        existing: list[str] = []
    else:
        number = int(match["number"])
        view = json.loads(run(["issue", "view", str(number), "-R", repo, "--json", "comments"]) or "{}")
        existing = [c.get("body", "") for c in view.get("comments", [])]
    posted = 0
    for comment in thread["comments"]:
        body = comment_body(comment)
        if body.strip() in (e.strip() for e in existing):
            continue
        run(["issue", "comment", str(number), "-R", repo, "--body", body])
        posted += 1
    return {"repo": repo, "number": number, "created": created, "comments_posted": posted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--thread", type=int, default=101, help="fixture thread number to seed")
    parser.add_argument("--fixture", default=str(ROOT / config.load("policy")["sweep"]["fixture"]))
    args = parser.parse_args(argv)
    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    if not fixture.get("fixture", {}).get("synthetic"):
        raise SystemExit("only synthetic fixtures can be seeded")
    thread = next((t for t in fixture["threads"] if t["number"] == args.thread), None)
    if thread is None:
        raise SystemExit(f"no thread {args.thread} in the fixture")
    print(json.dumps(seed(thread, sandbox_repo(config.load("safety")))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
