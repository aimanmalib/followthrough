"""A @tool whose parameter is typed `datetime` fails inside the runtime: the handler never runs.

The same tool with the parameter typed `str` is the control. Run from the repository root:
`uv run python repro/tool-datetime-argument/repro.py`
Exit 0 = the gap is still there (control ran, datetime handler did not); 1 = fixed upstream; 2 = control failed.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openminion import Agent, APIRuntime, tool  # noqa: E402

from fake_messages import FakeMessages, Home, text_reply, tool_results  # noqa: E402

calls: dict[str, int] = {"datetime": 0, "str": 0}


@tool(name="record_due", min_scope="READ_ONLY", idempotent=True, description="Record when a reply is due.")
def record_due_datetime(due_at: datetime) -> str:
    """Record when a reply is due."""
    calls["datetime"] += 1
    return f"recorded {due_at.isoformat()}"


@tool(name="record_due", min_scope="READ_ONLY", idempotent=True, description="Record when a reply is due.")
def record_due_str(due_at: str) -> str:
    """Record when a reply is due."""
    calls["str"] += 1
    return f"recorded {due_at}"


def reply(body):
    offered = [t.get("name") for t in body.get("tools", [])]
    if "record_due" in offered and not tool_results(body):
        return [{"type": "tool_use", "id": "tu_due_1", "name": "record_due",
                 "input": {"due_at": "2026-11-20T09:00:00Z"}}]
    return text_reply("done")(body)


def run(tool_fn, label: str) -> None:
    fake = FakeMessages(reply)
    try:
        with Home(fake.base_url) as config_path:
            runtime = APIRuntime.from_config_path(config_path, logging_mode="interactive")
            try:
                result = Agent(runtime=runtime, name="repro", tools=[tool_fn]).run(
                    "Record that a reply is due on 2026-11-20 at 09:00 UTC.", timeout_seconds=60)
            finally:
                runtime.close()
    finally:
        fake.close()
    print(f"[{label}] handler calls: {calls[label]}  run_state: {result.run_state}  reply: {result.text[:120]!r}")


def main() -> int:
    run(record_due_str, "str")
    run(record_due_datetime, "datetime")
    if calls["str"] != 1:
        return 2
    return 0 if calls["datetime"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
