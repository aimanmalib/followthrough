# A `@tool` parameter typed `datetime` ends the turn before the handler runs

**Version:** openminion 0.1.23 · Python 3.12 · Linux

## Steps

1. Decorate a function with `@tool(...)` whose parameter is typed `datetime` (`due_at: datetime`).
2. Give it to `Agent(runtime=..., tools=[...])` and run a turn in which the model calls the tool with
   an ISO 8601 string (`{"due_at": "2026-11-20T09:00:00Z"}`).
3. Control: the same tool with `due_at: str`.

`uv run python repro/tool-datetime-argument/repro.py` does both against a local stand-in for the
Messages API that always asks for the tool once.

## Expected

The handler receives a `datetime` (the SDK coerces typed arguments) and the turn completes, as it
does for the `str` control. Or, if `datetime` is not a supported parameter type, `@tool` refuses it
when the function is decorated.

## Actual

```
[str] handler calls: 1  run_state: completed  reply: 'repro: done'
[datetime] handler calls: 0  run_state: failed  reply: 'repro: State machine error: RUNTIME_ERROR: Object of type datetime is not JSON serializable'
```

The coerced argument is written to the session event store before the handler runs, through
`openminion/modules/session/storage/json_utils.py:6` (`json.dumps(value, sort_keys=True, separators=...)`,
no `default=`), reached from `modules/session/storage/events.py:165` (`insert_session_event_tx`).
The `TypeError` ends the turn; the handler is never called. `run_state` is `failed`, so callers can see it.

## Safe evidence

No key, no network beyond 127.0.0.1; a temporary home deleted on exit; the tool only appends to a
list in the script.

## In Follow-Through

`submit_reading` takes times as plain strings and `ThreadState` (Pydantic) parses them
(`src/followthrough/agents.py`, `make_submit_reading`; ADR 0004).
