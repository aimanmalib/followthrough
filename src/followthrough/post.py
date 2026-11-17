"""The only write path: post one approved comment on an allow-listed repository.

`publish()` and the `post_comment` tool check, in this order, before any network call:
1. the stop file: the file named by env `PERANAN_HENTI` (name configurable as `safety.stop_env`) or the
   repo-local `safety.stop_file`; if either exists, exit with `safety.stop_exit_code` (5) and post nothing;
2. the allow-list `safety.allow_post_repos` (empty by default = posting is off everywhere);
3. human approval: `approver` returns "allow_once" or "deny"; no approver = paused (no model, no HTTP).

The post itself runs through an OpenMinion agent whose only tool is `post_comment`, declared
`dangerous=True, min_scope="WRITE_SAFE"`, so OpenMinion's action policy asks the same approver again
before the tool runs. The tool posts only the exact body that was approved. `github.py` stays GET-only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openminion import Agent, APIRuntime, ProviderError, tool

from followthrough import config
from followthrough.spend import Spend

GATE_NAME = "followthrough-post"  # how a refusal is recorded by an optional outside recorder
ALLOW_ONCE = "allow_once"
DENY = "deny"

Approver = Callable[[str, int, str], str]  # (repo, number, body) -> "allow_once" | "deny"
Opener = Callable[..., Any]


class Stopped(SystemExit):
    """The stop file exists: nothing is posted."""


@dataclass
class PostResult:
    """What happened to one draft. `status`: posted | paused | denied | refused_repo | not_posted | error."""

    repo: str
    number: int
    status: str
    url: str | None = None
    http_posts: int = 0
    detail: str = ""


def stop_files(safety: Mapping[str, Any], root: Path) -> list[Path]:
    files = [root / safety["stop_file"]]
    named = os.environ.get(safety.get("stop_env") or "PERANAN_HENTI")
    if named:
        files.insert(0, Path(named).expanduser())
    return files


def check_stop(safety: Mapping[str, Any], root: Path) -> None:
    """Raise `Stopped` (exit code 5) when a stop file exists. Called first, before anything else."""
    hit = next((f for f in stop_files(safety, root) if f.exists()), None)
    if hit is None:
        return
    recorder = os.environ.get("PERANAN_KELUAR_PY")  # optional: records the refused attempt elsewhere
    if recorder:
        try:
            subprocess.run([sys.executable, recorder, "tolak", GATE_NAME], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    raise Stopped(int(safety["stop_exit_code"]))


def allowed(repo: str, safety: Mapping[str, Any]) -> bool:
    return repo in list(safety["allow_post_repos"])


class CommentPoster:
    """POST /repos/{o}/{r}/issues/{n}/comments. The token comes from the environment only."""

    def __init__(self, policy: Mapping[str, Any], opener: Opener | None = None) -> None:
        gh = policy["github"]
        self.api_base = gh["api_base"].rstrip("/")
        self.timeout = float(gh["timeout_s"])
        self._token = os.environ.get(gh["token_env"], "")
        self._open = opener or urllib.request.urlopen
        self.posts = 0

    def __repr__(self) -> str:  # never show the token
        return f"CommentPoster({self.api_base!r})"

    def post(self, repo: str, number: int, body: str) -> str:
        owner, name = repo.split("/", 1)
        url = f"{self.api_base}/repos/{owner}/{name}/issues/{int(number)}/comments"
        headers = {"Accept": "application/vnd.github+json", "Content-Type": "application/json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "followthrough"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        req = urllib.request.Request(url, data=json.dumps({"body": body}).encode("utf-8"),
                                     headers=headers, method="POST")
        self.posts += 1
        with self._open(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        return str(data.get("html_url") or "")


def make_post_comment(approved: Mapping[tuple[str, int], str], poster: CommentPoster, *,
                      safety: Mapping[str, Any], root: Path, posted: list[str],
                      stopped: list[int] | None = None) -> Callable[..., Any]:
    """Build the `post_comment` tool for one approved draft (key (repo, number) -> exact body).

    A stop inside the tool is noted in `stopped` as well as raised, because the agent runtime may turn
    a tool exception into an error result; `publish()` re-raises it after the run.
    """

    @tool(name="post_comment", dangerous=True, min_scope="WRITE_SAFE",
          description="Post one approved comment on an issue or pull request.")
    def post_comment(repo: str, number: int, body: str) -> dict[str, Any]:
        """Post one approved comment on an issue or pull request."""
        try:
            check_stop(safety, root)
        except Stopped as exc:
            if stopped is not None:
                stopped.append(int(exc.code or 0))
            raise
        if not allowed(repo, safety):
            return {"posted": False, "reason": "repo_not_allowed"}
        if approved.get((repo, int(number))) != body:
            return {"posted": False, "reason": "body_not_approved"}
        url = poster.post(repo, int(number), body)
        posted.append(url)
        return {"posted": True, "url": url}

    return post_comment


def publish(repo: str, number: int, body: str, *, approver: Approver | None, config_path: Path,
            spend: Spend, root: Path, opener: Opener | None = None,
            safety: Mapping[str, Any] | None = None, policy: Mapping[str, Any] | None = None,
            models: Mapping[str, Any] | None = None, prompts: Mapping[str, Any] | None = None,
            timeout_s: float | None = None) -> PostResult:
    """Post `body` on repo#number if, and only if, every check passes. See the module docstring."""
    safety = safety if safety is not None else config.load("safety")
    check_stop(safety, root)
    if not allowed(repo, safety):
        return PostResult(repo, number, "refused_repo")
    if approver is None:
        return PostResult(repo, number, "paused")
    policy = policy or config.load("policy")
    models = models or config.load("models")
    prompts = prompts or config.load("prompts")
    poster = CommentPoster(policy, opener)
    posted: list[str] = []
    stopped: list[int] = []
    decisions: list[str] = []

    def on_approval(tool_name: str, args: dict[str, Any], _approval_id: str) -> bool:
        if tool_name != "post_comment":
            decisions.append(DENY)
            return False
        choice = approver(str(args.get("repo")), int(args.get("number") or 0), str(args.get("body")))
        decisions.append(choice)
        return choice == ALLOW_ONCE

    model = models["profiles"]["reader"]["model"]
    message = prompts["publisher"]["message"].format(repo=repo, number=number, body=body)
    held = spend.hold()
    runtime = APIRuntime.from_config_path(str(config_path), logging_mode="interactive")
    agent: Agent[Any, Any] = Agent(runtime=runtime, name="publisher", agent_id="reader",
                                   instructions=prompts["publisher"]["instructions"],
                                   tools=[make_post_comment({(repo, number): body}, poster, safety=safety,
                                                            root=root, posted=posted, stopped=stopped)])
    try:
        result = agent.run(message, approval_callback=on_approval, timeout_seconds=timeout_s)
        spend.settle(held, model, result.stats, len(message), len(result.text))
    except (ProviderError, RuntimeError, TimeoutError) as exc:
        spend.forfeit(held, model)
        return PostResult(repo, number, "error", http_posts=poster.posts, detail=type(exc).__name__)
    finally:
        runtime.close()
    if stopped:
        raise Stopped(stopped[0])
    if posted:
        return PostResult(repo, number, "posted", url=posted[0], http_posts=poster.posts)
    if DENY in decisions:
        return PostResult(repo, number, "denied", http_posts=poster.posts)
    return PostResult(repo, number, "not_posted", http_posts=poster.posts)
