"""`followthrough post`: a person reviews one saved draft and answers allow_once or deny.

The draft file is the exact body that may be posted. The answer is read from standard input when
OpenMinion's action policy asks for approval of the `post_comment` call, so the person sees the body
the tool is about to send. End of input, or any answer other than `allow_once`, means deny.
Every other check (stop file, allow-list, exact approved body) lives in `post.publish`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from followthrough import agents, config, post
from followthrough.spend import Spend

EXIT_STOPPED_DEFAULT = 5


def stdin_approver(lang: str, read: IO[str] | None = None, write: IO[str] | None = None) -> post.Approver:
    """Ask once per tool call; the answer must be exactly `allow_once` to allow."""
    src, out = read or sys.stdin, write or sys.stderr

    def approve(repo: str, number: int, body: str) -> str:
        print(config.t("post.review", lang, repo=repo, number=number), file=out)
        print(body, file=out)
        print(config.t("post.ask", lang, allow=post.ALLOW_ONCE, deny=post.DENY), file=out, flush=True)
        answer = (src.readline() or "").strip()
        return post.ALLOW_ONCE if answer == post.ALLOW_ONCE else post.DENY

    return approve


def run(repo: str, number: int, draft: Path, lang: str, root: Path,
        approver: post.Approver | None = None, publish: Callable[..., post.PostResult] = post.publish) -> int:
    """Post one draft after approval. Returns the CLI exit code (stop file = safety.stop_exit_code)."""
    body = draft.read_text(encoding="utf-8").strip()
    if not body:
        print(config.t("post.empty", lang, path=draft), file=sys.stderr)
        return 2
    models = config.load("models")
    path = agents.write_agents_json(root, models)
    spend = Spend(root, agents.session_id(repo, datetime.now(UTC)))
    try:
        result = publish(repo, number, body, approver=approver or stdin_approver(lang), config_path=path,
                         spend=spend, root=root, models=models)
    except post.Stopped as exc:
        print(config.t("post.stopped", lang), file=sys.stderr)
        return int(exc.code if exc.code is not None else EXIT_STOPPED_DEFAULT)
    print(config.t(f"post.status_{result.status}", lang, repo=repo, number=number, url=result.url or "-",
                   posts=result.http_posts))
    return 0 if result.status in ("posted", "denied") else 1
