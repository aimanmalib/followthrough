"""OpenMinion reader agents: one subagent per changed thread, reading the snapshot through a tool.

The parent `Agent` holds the runtime; each thread gets its own `subagent(...)` with a single read-only
tool, `get_thread`, that serves that thread from the snapshot already on disk (never the network).
The reply must validate as `ThreadState` (`output_type`), and then the quote guard checks it against
the same snapshot. Every turn holds budget first and books its real cost after (see spend.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openminion import Agent, AgentOutputValidationError, APIRuntime, ProviderError, subagent, tool
from openminion.base.config import AgentProfileConfig, OpenMinionConfig, save_config

from followthrough import config
from followthrough.spend import BudgetExceeded, Spend, TurnCost
from followthrough.state import Checked, Kind, Role, ThreadState, WaitingOn, verify

PROFILES = ("reader", "drafter")


def session_id(repo: str, now: datetime) -> str:
    """`sweep:<owner>__<repo>:<YYYYMMDD>`; OpenMinion memory scopes reject "/" (ADR 0004)."""
    owner, name = repo.split("/", 1)
    return f"sweep:{owner}__{name}:{now.astimezone(UTC):%Y%m%d}"


def thread_session_id(sweep_session: str, number: int) -> str:
    """One session per thread, so no reader sees another thread's transcript."""
    return f"{sweep_session}:{number}"


def write_agents_json(root: Path, models: Mapping[str, Any] | None = None,
                      base_url: str | None = None) -> Path:
    """Generate the OpenMinion config (agents.json) from config/models.toml.

    `base_url` points the provider somewhere else (tests and replay use a local server).
    """
    models = models or config.load("models")
    provider = models["provider"]
    cfg = OpenMinionConfig()
    cfg.agents = {name: AgentProfileConfig(name=name, provider=provider, default_channel="console")
                  for name in PROFILES}
    cfg.default_agent = PROFILES[0]
    path = root / models["agents_json"]
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg.storage.path = str((path.parent / "openminion.db").resolve())
    save_config(cfg, str(path), home_root=path.parent)
    data = json.loads(path.read_text(encoding="utf-8"))
    settings = data["providers"][provider]
    settings["model"] = models["profiles"]["reader"]["model"]
    if base_url:
        settings["base_url"] = base_url
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def thread_view(thread: Mapping[str, Any]) -> dict[str, Any]:
    """What the model sees of one thread: posts in order with role and created_at, nothing else."""
    opening = {"created_at": thread["created_at"], "role": _role(thread["author"]), "body": thread["body"]}
    return {
        "number": thread["number"],
        "title": thread.get("title", ""),
        "is_pull_request": thread.get("is_pr", False),
        "labels": list(thread.get("labels", [])),
        "posts": [opening] + [{"created_at": c["created_at"], "role": _role(c["author"]), "body": c["body"]}
                              for c in thread.get("comments", [])],
        "linked_prs": [pr.get("number") for pr in thread.get("linked_prs", [])],
    }


def _role(person: Mapping[str, Any]) -> str:
    return "maintainer" if person.get("maintainer") else "contributor"


def make_get_thread(threads: Mapping[int, Mapping[str, Any]], served: list[int] | None = None) -> Callable[..., Any]:
    """Build the read-only `get_thread` tool over one snapshot's threads."""

    @tool(name="get_thread", min_scope="READ_ONLY", idempotent=True,
          description="Return one issue or pull request thread from the saved snapshot.")
    def get_thread(number: int) -> dict[str, Any]:
        """Return one issue or pull request thread from the saved snapshot."""
        if served is not None:
            served.append(int(number))
        thread = threads.get(int(number))
        if thread is None:
            return {"error": f"thread {number} is not in this snapshot"}
        return thread_view(thread)

    return get_thread


def make_submit_reading(captured: dict[int, dict[str, Any]]) -> Callable[..., Any]:
    """Build `submit_reading`: the ThreadState fields as typed tool arguments.

    `output_type` is only checked against the final reply text, which OpenMinion passes through
    several internal steps; a typed tool call carries the schema to the model itself. The captured
    arguments are used when the final reply does not validate (ADR 0004). Times are plain strings
    here because the runtime cannot serialise datetime tool arguments; ThreadState parses them.
    """

    @tool(name="submit_reading", min_scope="READ_ONLY", idempotent=True,
          description="Submit your reading of the thread. Call once, with every field.")
    def submit_reading(number: int, kind: Kind, waiting_on: WaitingOn, confidence: float,
                       open_request_quote: str | None = None, open_request_by: Role | None = None,
                       open_request_at: str | None = None, agreed_eta: str | None = None,
                       agreed_eta_quote: str | None = None, last_follow_up_at: str | None = None,
                       linked_pr: int | None = None) -> dict[str, Any]:
        """Submit your reading of the thread. Call once, with every field."""
        fields = {"number": number, "kind": kind, "waiting_on": waiting_on, "confidence": confidence,
                  "open_request_quote": open_request_quote, "open_request_by": open_request_by,
                  "open_request_at": open_request_at, "agreed_eta": agreed_eta,
                  "agreed_eta_quote": agreed_eta_quote, "last_follow_up_at": last_follow_up_at,
                  "linked_pr": linked_pr}
        captured[int(number)] = fields
        return {"received": True, "next": "reply with the same reading as one JSON object"}

    return submit_reading


@dataclass
class ReadOutcome:
    """One thread's reading: a guarded state, or the reason there is none."""

    number: int
    checked: Checked | None = None
    error: str | None = None
    cost: TurnCost | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    raw: str = ""  # model reply when it failed validation; may quote the thread, so never published
    source: str | None = None  # "output_type" (final reply validated) or "submit_reading" (tool arguments)

    @property
    def problems(self) -> list[str]:
        if self.checked is None:
            return [self.error or "no_reading"]
        return self.checked.problems


@dataclass
class ReadReport:
    outcomes: list[ReadOutcome]
    session_id: str
    stopped: str | None = None
    tool_calls: list[int] = field(default_factory=list)

    def counts(self) -> dict[str, Any]:
        """Aggregate numbers only (safe to publish: no third-party text)."""
        read = [o for o in self.outcomes if o.checked is not None]
        costs = [o.cost for o in self.outcomes if o.cost is not None]
        return {
            "threads": len(self.outcomes),
            "read": len(read),
            "guard_rejected": sum(1 for o in read if o.checked.rejected),
            "failed": sum(1 for o in self.outcomes if o.checked is None),
            "input_tokens": sum(c.input_tokens for c in costs),
            "output_tokens": sum(c.output_tokens for c in costs),
            "estimated_turns": sum(1 for c in costs if c.estimated),
            "usd": round(sum(c.usd for c in costs), 6),
            "llm_calls": sum(int(o.stats.get("llm_calls") or 0) for o in self.outcomes),
            "get_thread_calls": len(self.tool_calls),
            "from_output_type": sum(1 for o in self.outcomes if o.source == "output_type"),
            "from_submit_reading": sum(1 for o in self.outcomes if o.source == "submit_reading"),
            "stopped": self.stopped,
        }


def read_threads(snapshot: Mapping[str, Any], numbers: Iterable[int], *, config_path: Path, spend: Spend,
                 now: datetime, models: Mapping[str, Any] | None = None,
                 prompts: Mapping[str, Any] | None = None, timeout_s: float | None = None) -> ReadReport:
    """Read each thread in `numbers` with its own subagent; at most `max_concurrency` at once."""
    models = models or config.load("models")
    prompts = prompts or config.load("prompts")
    policy = config.load("policy")
    model = models["profiles"]["reader"]["model"]
    instructions = prompts["reader"]["instructions"].format(quote_max_chars=policy["guard"]["quote_max_chars"])
    threads = {t["number"]: t for t in snapshot["threads"]}
    sid = session_id(snapshot["repo"], now)
    report = ReadReport(outcomes=[], session_id=sid)
    # Build the runtime once, up front: subagent() would otherwise create it lazily from several
    # worker threads at once, and two runtimes migrating one SQLite file fail (ADR 0004).
    runtime = APIRuntime.from_config_path(str(config_path), logging_mode="interactive")
    parent: Agent[Any, Any] = Agent(runtime=runtime, name="sweep", agent_id="reader", session_id=sid)

    def read_one(number: int) -> ReadOutcome:
        if report.stopped:
            return ReadOutcome(number, error="budget_stopped")
        try:
            held = spend.hold()
        except BudgetExceeded as exc:
            report.stopped = str(exc)
            return ReadOutcome(number, error="budget_stopped")
        captured: dict[int, dict[str, Any]] = {}
        child = subagent(parent, instructions=instructions, model=model, name=f"reader-{number}",
                         tools=[make_get_thread(threads, report.tool_calls), make_submit_reading(captured)],
                         output_type=ThreadState)
        message = prompts["reader"]["message"].format(number=number)
        try:
            result = child.run(message, session_id=thread_session_id(sid, number), timeout_seconds=timeout_s)
        except AgentOutputValidationError as exc:
            # The final reply did not validate; the typed tool call may still hold the reading.
            # Stats were lost with the exception, so the turn is booked at its reserve.
            cost = spend.forfeit(held, model)
            state = _from_tool(captured.get(number))
            if state is None:
                return ReadOutcome(number, error="invalid_output", cost=cost, raw=exc.raw_text)
            return ReadOutcome(number, checked=verify(state, threads[number]), cost=cost,
                               raw=exc.raw_text, source="submit_reading")
        except (ProviderError, RuntimeError, TimeoutError):
            return ReadOutcome(number, error="provider_error", cost=spend.forfeit(held, model))
        chars_in = len(instructions) + len(message) + len(json.dumps(thread_view(threads[number])))
        cost = spend.settle(held, model, result.stats, chars_in, len(result.text))
        return ReadOutcome(number, checked=verify(result.output, threads[number]), cost=cost,
                           stats=dict(result.stats), source="output_type")

    try:
        wanted = [n for n in numbers if n in threads]
        with ThreadPoolExecutor(max_workers=max(1, int(models["max_concurrency"]))) as pool:
            report.outcomes = list(pool.map(read_one, wanted))
    finally:
        runtime.close()
    return report


def _from_tool(fields: Mapping[str, Any] | None) -> ThreadState | None:
    if fields is None:
        return None
    try:
        return ThreadState.model_validate(dict(fields))
    except ValueError:
        return None

