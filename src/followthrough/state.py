"""Thread state returned by the reader agent, and the quote guard that checks it against the snapshot.

The reader model fills a `ThreadState` for one thread. Nothing in it is trusted until `verify`
has checked every quote and timestamp against the snapshot the model was given: a quote must be
an exact substring of exactly one post (the opening post or a comment), and its timestamp must be
that post's `created_at`. Any failure turns `waiting_on` into "unclear" and is counted, so a live
sweep can report how often the model was caught.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from followthrough import config

QUOTE_MAX = config.load("policy")["guard"]["quote_max_chars"]

Kind = Literal["defect", "enhancement", "question", "provider_specific", "other"]
WaitingOn = Literal["maintainer", "contributor", "release", "nobody", "unclear"]
Role = Literal["maintainer", "contributor"]


class ThreadState(BaseModel):
    """Who is waiting on whom in one thread, as read by the model (unverified until `verify`)."""

    model_config = ConfigDict(extra="forbid")

    number: int
    kind: Kind
    waiting_on: WaitingOn
    open_request_quote: str | None = Field(default=None, max_length=QUOTE_MAX)
    open_request_by: Role | None = None
    open_request_at: datetime | None = None
    agreed_eta: date | None = None
    agreed_eta_quote: str | None = Field(default=None, max_length=QUOTE_MAX)
    last_follow_up_at: datetime | None = None
    linked_pr: int | None = None
    confidence: float = Field(ge=0.0, le=1.0)


@dataclass(frozen=True)
class Post:
    """The opening post or one comment, flattened for the guard and the rules."""

    created_at: datetime
    body: str
    maintainer: bool


@dataclass
class Checked:
    """A verified state plus every guard problem found (empty list = accepted as read)."""

    state: ThreadState
    problems: list[str] = field(default_factory=list)
    read_as: WaitingOn | None = None  # the model's own waiting_on, kept when the guard turned it "unclear"

    @property
    def rejected(self) -> bool:
        return bool(self.problems)


def parse_ts(value: str | datetime) -> datetime:
    """GitHub timestamp ("2026-11-02T10:00:00Z") or datetime -> aware UTC datetime."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return moment.astimezone(UTC)


def posts(thread: Mapping[str, Any]) -> list[Post]:
    """Opening post first, then comments in the order GitHub returned them."""
    out = [Post(parse_ts(thread["created_at"]), thread.get("body") or "", bool(thread["author"]["maintainer"]))]
    out += [Post(parse_ts(c["created_at"]), c.get("body") or "", bool(c["author"]["maintainer"]))
            for c in thread.get("comments", [])]
    return out


def _find(quote: str, all_posts: list[Post]) -> tuple[Post | None, str | None]:
    """The single post containing `quote`, or a problem code."""
    hits = [p for p in all_posts if quote and quote in p.body]
    if not hits:
        return None, "quote_not_found"
    if len(hits) > 1:
        return None, "quote_ambiguous"
    return hits[0], None


def _same(a: datetime | None, b: datetime) -> bool:
    return a is not None and a.astimezone(UTC) == b


def _check_request(state: ThreadState, all_posts: list[Post]) -> list[str]:
    parts = (state.open_request_quote, state.open_request_by, state.open_request_at)
    if all(p is None for p in parts):
        return []
    if any(p is None for p in parts):
        return ["open_request_incomplete"]
    post, problem = _find(state.open_request_quote or "", all_posts)
    if post is None:
        return [f"open_request_{problem}"]
    found: list[str] = []
    if not _same(state.open_request_at, post.created_at):
        found.append("open_request_time_mismatch")
    if (state.open_request_by == "maintainer") != post.maintainer:
        found.append("open_request_role_mismatch")
    return found


def _check_eta(state: ThreadState, all_posts: list[Post]) -> list[str]:
    if state.agreed_eta is None and state.agreed_eta_quote is None:
        return []
    if state.agreed_eta is None or state.agreed_eta_quote is None:
        return ["eta_incomplete"]
    _, problem = _find(state.agreed_eta_quote, all_posts)
    return [f"eta_{problem}"] if problem else []


def _check_follow_up(state: ThreadState, all_posts: list[Post]) -> list[str]:
    if state.last_follow_up_at is None:
        return []
    if any(p.maintainer and _same(state.last_follow_up_at, p.created_at) for p in all_posts):
        return []
    return ["follow_up_time_not_found"]


def _check_linked_pr(state: ThreadState, thread: Mapping[str, Any], all_posts: list[Post]) -> list[str]:
    if state.linked_pr is None:
        return []
    if any(pr["number"] == state.linked_pr for pr in thread.get("linked_prs", [])):
        return []
    mention = re.compile(rf"#{state.linked_pr}\b")
    return [] if any(mention.search(p.body) for p in all_posts) else ["linked_pr_not_found"]


def verify(state: ThreadState, thread: Mapping[str, Any]) -> Checked:
    """Check every quote and timestamp in `state` against `thread` (one snapshot thread)."""
    if state.number != thread["number"]:
        return Checked(state.model_copy(update={"waiting_on": "unclear"}), ["number_mismatch"], state.waiting_on)
    all_posts = posts(thread)
    problems = (_check_request(state, all_posts) + _check_eta(state, all_posts)
                + _check_follow_up(state, all_posts) + _check_linked_pr(state, thread, all_posts))
    if problems:
        return Checked(state.model_copy(update={"waiting_on": "unclear"}), problems, state.waiting_on)
    return Checked(state)


def quote_post(quote: str | None, thread: Mapping[str, Any]) -> Post | None:
    """The post holding a quote that `verify` already accepted (None if absent)."""
    if not quote:
        return None
    post, _ = _find(quote, posts(thread))
    return post
