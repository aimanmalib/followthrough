"""A local stand-in for the Anthropic Messages API, for offline agent tests.

It answers the first request of a reader turn with a `get_thread` tool call, then (when `submit`
gives arguments) a `submit_reading` call, and every later request with the canned answer text. Usage is reported per request (or as 0 to mimic
providers that send no telemetry). Bound to 127.0.0.1 on a free port; stopped by `close()`.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content if isinstance(c, dict))


def _has_tool_result(messages: list[dict[str, Any]], name_id: str) -> bool:
    for m in messages:
        if isinstance(m.get("content"), list):
            for c in m["content"]:
                if c.get("type") == "tool_result" and c.get("tool_use_id", "").startswith(name_id):
                    return True
    return False


class FakeAnthropic:
    def __init__(self, answer: Callable[[int], str], usage: Mapping[str, int] | None = None,
                 status: int = 200, submit: Callable[[int], str | None] | None = None) -> None:
        self.answer = answer
        # Arguments for the submit_reading tool call (JSON text), or None to skip that call.
        self.submit = submit or (lambda number: None)
        self.usage = dict(usage if usage is not None else {"input_tokens": 1000, "output_tokens": 100})
        self.status = status
        self.requests: list[dict[str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.requests.append(body)
                reply = fake._reply(body)
                data = json.dumps(reply).encode()
                self.send_response(fake.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def _reply(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.status != 200:
            return {"type": "error", "error": {"type": "api_error", "message": "fake failure"}}
        messages = body.get("messages", [])
        text = " ".join(_text_of(m.get("content", "")) for m in messages if m.get("role") == "user")
        match = re.search(r"#(\d+)", text)
        number = int(match.group(1)) if match else 0
        tools = [t.get("name") for t in body.get("tools", [])]
        answer = self.answer(number)
        if "get_thread" in tools and not _has_tool_result(messages, "tu_get_thread"):
            content = [{"type": "tool_use", "id": f"tu_get_thread_{number}", "name": "get_thread",
                        "input": {"number": number}}]
            stop = "tool_use"
        elif "submit_reading" in tools and not _has_tool_result(messages, "tu_submit") and self.submit(number):
            content = [{"type": "tool_use", "id": f"tu_submit_{number}", "name": "submit_reading",
                        "input": json.loads(self.submit(number))}]
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": answer}]
            stop = "end_turn"
        return {"id": "msg_fake", "type": "message", "role": "assistant", "model": body.get("model", ""),
                "content": content, "stop_reason": stop, "usage": dict(self.usage)}

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
