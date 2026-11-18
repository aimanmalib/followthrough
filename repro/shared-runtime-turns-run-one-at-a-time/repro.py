"""Agents with decorated tools that share one APIRuntime run their turns one at a time.

`Agent.run` enters `ToolRegistry.temporary_registration_scope()` and keeps it (and so the registry's
lock) until `runtime.run_turn` returns. Four threads, each with its own `subagent(...)` and session,
therefore wait on each other for the whole turn, model calls included. The control runs the same
four turns with subagents that have no tools.

The local model answers every request after `DELAY_S` seconds and counts requests in flight at once.
Run from the repository root: `uv run python repro/shared-runtime-turns-run-one-at-a-time/repro.py`
Exit 0 = the gap is still there (control overlaps, tool runs never do); 1 = fixed upstream; 2 = control did not overlap.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openminion import Agent, APIRuntime, subagent, tool  # noqa: E402

from fake_messages import FakeMessages, Home, text_reply  # noqa: E402

WORKERS = 4
DELAY_S = 0.5


@tool(name="lookup", min_scope="READ_ONLY", idempotent=True, description="Look something up.")
def lookup(key: str) -> str:
    """Look something up."""
    return key


def sweep(with_tools: bool) -> tuple[int, float, list[str], int]:
    fake = FakeMessages(text_reply("done"), delay_s=DELAY_S)
    try:
        with Home(fake.base_url) as config_path:
            runtime = APIRuntime.from_config_path(config_path, logging_mode="interactive")
            try:
                parent = Agent(runtime=runtime, name="parent")
                children = [subagent(parent, name=f"child-{i}", instructions="Answer briefly.",
                                     tools=[lookup] if with_tools else None) for i in range(WORKERS)]
                # Warm-up: concurrent FIRST turns on a fresh runtime race on its SQLite migrations
                # ("UNIQUE constraint failed: migrations.version"); one turn first avoids that.
                children[0].run("Say done.", session_id="repro-warm-up", timeout_seconds=120)
                fake.peak = 0
                fake.requests.clear()
                start = time.monotonic()
                with ThreadPoolExecutor(WORKERS) as pool:
                    results = list(pool.map(lambda ic: ic[1].run(f"Say done ({ic[0]}).", session_id=f"repro-{ic[0]}",
                                                                 timeout_seconds=120), enumerate(children)))
                elapsed = time.monotonic() - start
            finally:
                runtime.close()
    finally:
        fake.close()
    return fake.peak, elapsed, [r.run_state for r in results], len(fake.requests)


def main() -> int:
    control = sweep(with_tools=False)
    gap = sweep(with_tools=True)
    for label, (peak, elapsed, states, requests) in (("no tools", control), ("decorated tool", gap)):
        print(f"[{label}] {WORKERS} threads, one runtime: most model requests in flight at once = {peak}, "
              f"{requests} model requests, wall time {elapsed:.1f} s, run states {states}")
    if control[0] < 2:
        return 2
    return 0 if gap[0] == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
