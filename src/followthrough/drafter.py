"""Follow-up drafts for human review: one OpenMinion subagent per thread whose action needs a draft.

The drafter is given structured facts only (action, the dates the rules computed, the CONTRIBUTING step
from config/drafts.toml), never the thread text, so nothing a third party wrote can steer the draft.
Each reply must validate as `Draft` (`output_type`), then pass `check()`: at most `max_words` words,
every computed date present verbatim, no @mentions. Passing drafts are saved to
`<output_dir>/<YYYY-MM-DD>/<subdir>/<number>.md`; nothing is posted here (see post.py).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from openminion import Agent, AgentOutputValidationError, APIRuntime, ProviderError, subagent, tool
from pydantic import BaseModel, Field

from followthrough import agents, config
from followthrough.rules import Decision
from followthrough.spend import BudgetExceeded, Spend, TurnCost

MENTION = re.compile(r"(?<![\w.])@[A-Za-z0-9-]+")


class Draft(BaseModel):
    number: int
    body: str = Field(min_length=1)


@dataclass
class DraftOutcome:
    number: int
    action: str
    path: Path | None = None
    problems: list[str] = field(default_factory=list)
    cost: TurnCost | None = None
    source: str | None = None  # "output_type" (final reply validated) or "submit_draft" (tool arguments)
    raw: str = ""  # model reply that failed validation; kept for diagnosis, never published


def make_submit_draft(captured: dict[int, str]) -> Callable[..., Any]:
    """`submit_draft`: the Draft fields as typed tool arguments, used when the final reply does not
    validate (the runtime sometimes blocks a JSON reply as a tool envelope; same pattern as ADR 0004)."""

    @tool(name="submit_draft", min_scope="READ_ONLY", idempotent=True,
          description="Submit the follow-up comment. Call once.")
    def submit_draft(number: int, body: str) -> dict[str, Any]:
        """Submit the follow-up comment. Call once."""
        captured[int(number)] = str(body)
        return {"received": True, "next": "reply with the same draft as one JSON object"}

    return submit_draft


def needs_draft(decision: Decision | None, drafts: Mapping[str, Any]) -> bool:
    return decision is not None and decision.action in drafts["actions"]


def facts(decision: Decision, drafts: Mapping[str, Any]) -> dict[str, Any]:
    """Everything the drafter may know about one thread. No thread text."""
    fmt = drafts["date_format"]
    step = drafts["steps"][decision.action]
    return {"action": decision.action, "reason": decision.reason,
            "dates": {k: _fmt(v, fmt) for k, v in sorted(decision.dates.items())},
            "release_tag": decision.release_tag,
            "contributing_step": {"source": step["source"], "step": step["step"]}, "goal": step["goal"]}


def _fmt(value: date | str, fmt: str) -> str:
    return value.strftime(fmt) if isinstance(value, date) else str(value)


def words(text: str) -> int:
    return len(text.split())


def check(body: str, decision: Decision, drafts: Mapping[str, Any], max_words: int) -> list[str]:
    """Problems that keep a draft from being saved; empty list = fine."""
    problems = []
    if words(body) > max_words:
        problems.append("too_long")
    for key, value in sorted(facts(decision, drafts)["dates"].items()):
        if value not in body:
            problems.append(f"missing_date:{key}")
    if decision.release_tag and decision.release_tag not in body:
        problems.append("missing_release_tag")
    if MENTION.search(body):
        problems.append("mention")
    return problems


def draft_path(root: Path, output_dir: str, subdir: str, now: datetime, number: int) -> Path:
    return root / output_dir / f"{now.astimezone(UTC):%Y-%m-%d}" / subdir / f"{int(number)}.md"


def write_draft(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def draft_all(repo: str, decisions: Iterable[Decision | None], *, config_path: Path, spend: Spend,
              now: datetime, root: Path, models: Mapping[str, Any] | None = None,
              prompts: Mapping[str, Any] | None = None, drafts: Mapping[str, Any] | None = None,
              policy: Mapping[str, Any] | None = None, timeout_s: float | None = None) -> list[DraftOutcome]:
    """Draft every decision whose action is in `drafts.actions`, one subagent each, in order."""
    models = models or config.load("models")
    prompts = prompts or config.load("prompts")
    drafts = drafts or config.load("drafts")
    policy = policy or config.load("policy")
    profile = models["profiles"]["drafter"]
    max_words = int(profile["max_words"])
    instructions = prompts["drafter"]["instructions"].format(max_words=max_words)
    wanted = [d for d in decisions if needs_draft(d, drafts)]
    if not wanted:
        return []
    sid = agents.session_id(repo, now)
    runtime = APIRuntime.from_config_path(str(config_path), logging_mode="interactive")
    parent: Agent[Any, Any] = Agent(runtime=runtime, name="drafts", agent_id="drafter", session_id=sid)
    out: list[DraftOutcome] = []
    try:
        for decision in wanted:
            assert decision is not None
            outcome = DraftOutcome(decision.number, decision.action)
            out.append(outcome)
            try:
                held = spend.hold()
            except BudgetExceeded:
                outcome.problems.append("budget_stopped")
                continue
            message = prompts["drafter"]["message"].format(
                number=decision.number, facts=json.dumps(facts(decision, drafts), ensure_ascii=False))
            captured: dict[int, str] = {}
            child = subagent(parent, instructions=instructions, model=profile["model"],
                             name=f"drafter-{decision.number}", tools=[make_submit_draft(captured)],
                             output_type=Draft)
            try:
                result = child.run(message, session_id=f"{sid}:draft:{decision.number}", timeout_seconds=timeout_s)
            except AgentOutputValidationError as exc:
                outcome.cost = spend.forfeit(held, profile["model"])
                outcome.raw = exc.raw_text
                if decision.number not in captured:
                    outcome.problems.append("invalid_output")
                    continue
                outcome.source = "submit_draft"
                _finish(outcome, captured[decision.number], decision, drafts, max_words, root, policy, now)
                continue
            except (ProviderError, RuntimeError, TimeoutError):
                outcome.cost = spend.forfeit(held, profile["model"])
                outcome.problems.append("provider_error")
                continue
            outcome.cost = spend.settle(held, profile["model"], result.stats,
                                        len(instructions) + len(message), len(result.text))
            outcome.source = "output_type"
            if result.output.number != decision.number:
                outcome.problems.append("wrong_number")
                continue
            _finish(outcome, result.output.body, decision, drafts, max_words, root, policy, now)
    finally:
        runtime.close()
    return out


def _finish(outcome: DraftOutcome, body: str, decision: Decision, drafts: Mapping[str, Any], max_words: int,
            root: Path, policy: Mapping[str, Any], now: datetime) -> None:
    """Check one draft and save it when it passes."""
    outcome.problems = check(body, decision, drafts, max_words)
    if not outcome.problems:
        outcome.path = write_draft(draft_path(root, policy["sweep"]["output_dir"], drafts["subdir"],
                                              now, decision.number), body)
