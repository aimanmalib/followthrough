"""Deterministic follow-up rules: one action per thread, each with the dates it was computed from.

Inputs are a verified `ThreadState`, the snapshot thread it was read from, the clock (`now`) and
`config/policy.toml`. Windows are whole UTC calendar days, because the drafts state dates
("take-over allowed from 2026-11-23"), not hours. "Has anyone replied since?" is answered from
the snapshot, never from the model. No window, label or day count lives in this file.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from followthrough.state import Post, ThreadState, posts, quote_post

FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
TAKEOVER_ALLOWED = "TAKEOVER_ALLOWED"
MAINTAINER_REPLY_PENDING = "MAINTAINER_REPLY_PENDING"
READY_TO_VERIFY = "READY_TO_VERIFY"
NO_ACTION = "NO_ACTION"
ACTIONS = (FOLLOW_UP_DUE, TAKEOVER_ALLOWED, MAINTAINER_REPLY_PENDING, READY_TO_VERIFY, NO_ACTION)
# Actions that lead to a draft for human approval; MAINTAINER_REPLY_PENDING is digest-only.
DRAFT_ACTIONS = (FOLLOW_UP_DUE, TAKEOVER_ALLOWED, READY_TO_VERIFY)


@dataclass(frozen=True)
class Decision:
    """The action for one thread. `reason` is a locale key suffix; `dates` are ISO-ready."""

    number: int
    action: str
    reason: str
    dates: dict[str, date] = field(default_factory=dict)
    release_tag: str | None = None


@dataclass(frozen=True)
class Windows:
    follow_up: timedelta
    after_follow_up: timedelta
    maintainer_reply: timedelta

    @classmethod
    def from_policy(cls, policy: Mapping[str, Any]) -> Windows:
        w = policy["windows"]
        return cls(timedelta(days=w["follow_up_days"]), timedelta(days=w["after_follow_up_days"]),
                   timedelta(days=w["maintainer_reply_days"]))


def _day(moment: datetime) -> date:
    return moment.astimezone(UTC).date()


def _replied(all_posts: list[Post], since: datetime, by_maintainer: bool) -> bool:
    return any(p.maintainer == by_maintainer and p.created_at > since for p in all_posts)


def _ready_to_verify(thread: Mapping[str, Any], release: Mapping[str, Any] | None,
                     policy: Mapping[str, Any]) -> Decision | None:
    if policy["labels"]["awaiting_release"] not in thread.get("labels", []) or not release:
        return None
    shipped = [pr for pr in thread.get("linked_prs", []) if pr.get("merged") and pr.get("in_latest_release")]
    if not shipped:
        return None
    return Decision(thread["number"], READY_TO_VERIFY, "fix_released",
                    {"released_on": _day(datetime.fromisoformat(release["published_at"].replace("Z", "+00:00")))},
                    release_tag=release["tag"])


def _chase(number: int, pending_since: datetime, due_on: date, reason: str, state: ThreadState,
           all_posts: list[Post], today: date, win: Windows) -> Decision:
    """Contributor owes a reply since `pending_since`: follow up, or allow take-over after a follow-up."""
    follow_up = state.last_follow_up_at
    if follow_up is not None and follow_up > pending_since:
        takeover_from = _day(follow_up) + win.after_follow_up
        dates = {"followed_up_on": _day(follow_up), "takeover_from": takeover_from}
        if _replied(all_posts, follow_up, by_maintainer=False) or today < takeover_from:
            return Decision(number, NO_ACTION, "follow_up_sent", dates)
        return Decision(number, TAKEOVER_ALLOWED, "follow_up_unanswered", dates)
    if today < due_on:
        return Decision(number, NO_ACTION, "within_window", {"follow_up_from": due_on})
    return Decision(number, FOLLOW_UP_DUE, reason,
                    {"follow_up_on": today, "takeover_from": today + win.after_follow_up})


def decide(state: ThreadState, thread: Mapping[str, Any], now: datetime, policy: Mapping[str, Any],
           release: Mapping[str, Any] | None = None) -> Decision:
    """The single action for one thread. `state` must already have passed `state.verify`."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    number, today, win = thread["number"], _day(now), Windows.from_policy(policy)
    ready = _ready_to_verify(thread, release, policy)
    if ready is not None:
        return ready
    if state.waiting_on == "unclear":
        return Decision(number, NO_ACTION, "unclear")
    all_posts = posts(thread)
    asked_at = state.open_request_at
    if state.open_request_by == "maintainer" and asked_at is not None:
        if not _replied(all_posts, asked_at, by_maintainer=False):
            decision = _chase(number, asked_at, _day(asked_at) + win.follow_up, "request_unanswered",
                              state, all_posts, today, win)
            return _with(decision, requested_on=_day(asked_at))
    if state.agreed_eta is not None and today > state.agreed_eta:
        promise = quote_post(state.agreed_eta_quote, thread)
        promised_at = promise.created_at if promise else datetime.combine(state.agreed_eta, datetime.min.time(), UTC)
        if not _replied(all_posts, promised_at, by_maintainer=False):
            end_of_eta = datetime.combine(state.agreed_eta, datetime.max.time(), UTC)
            decision = _chase(number, end_of_eta, today, "eta_passed", state, all_posts, today, win)
            return _with(decision, agreed_eta=state.agreed_eta)
    if state.open_request_by == "contributor" and asked_at is not None:
        if not _replied(all_posts, asked_at, by_maintainer=True):
            reply_due = _day(asked_at) + win.maintainer_reply
            dates = {"asked_on": _day(asked_at), "reply_due": reply_due}
            if today >= reply_due:
                return Decision(number, MAINTAINER_REPLY_PENDING, "contributor_waiting", dates)
            return Decision(number, NO_ACTION, "within_window", dates)
    return Decision(number, NO_ACTION, "nothing_pending")


def _with(decision: Decision, **extra: date) -> Decision:
    return Decision(decision.number, decision.action, decision.reason, {**extra, **decision.dates},
                    decision.release_tag)
