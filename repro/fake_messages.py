"""Shared helpers for the repro scripts: a local stand-in for the Anthropic Messages API and a
throw-away OpenMinion home pointed at it. No model key, no network beyond 127.0.0.1.

`FakeMessages(reply, delay_s)` answers every POST with `reply(body)` (a list of content blocks) after
`delay_s` seconds and records the most requests that were in flight at once.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from openminion.base.config import AgentProfileConfig, OpenMinionConfig, save_config

Reply = Callable[[dict[str, Any]], list[dict[str, Any]]]


def text_reply(text: str) -> Reply:
    return lambda body: [{"type": "text", "text": text}]


def tool_results(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for m in body.get("messages", []) if isinstance(m.get("content"), list)
            for c in m["content"] if c.get("type") == "tool_result"]


class FakeMessages:
    def __init__(self, reply: Reply, delay_s: float = 0.0) -> None:
        self.reply, self.delay_s = reply, delay_s
        self.requests: list[dict[str, Any]] = []
        self.in_flight = self.peak = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                with fake._lock:
                    fake.requests.append(body)
                    fake.in_flight += 1
                    fake.peak = max(fake.peak, fake.in_flight)
                try:
                    time.sleep(fake.delay_s)
                    content = fake.reply(body)
                finally:
                    with fake._lock:
                        fake.in_flight -= 1
                stop = "tool_use" if any(c["type"] == "tool_use" for c in content) else "end_turn"
                data = json.dumps({"id": "msg_fake", "type": "message", "role": "assistant",
                                   "model": body.get("model", ""), "content": content, "stop_reason": stop,
                                   "usage": {"input_tokens": 10, "output_tokens": 5}}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Home:
    """`with Home(base_url) as config_path:` an OpenMinion home whose `anthropic` provider calls `base_url`."""

    def __init__(self, base_url: str, model: str = "claude-haiku-5-5") -> None:
        self.base_url, self.model = base_url, model
        self.root: Path | None = None

    def __enter__(self) -> str:
        os.environ.setdefault("ANTHROPIC_API_KEY", "not-a-real-key")
        self.root = Path(tempfile.mkdtemp(prefix="om-repro-"))
        path = self.root / "agents.json"
        cfg = OpenMinionConfig()
        cfg.agents = {"repro": AgentProfileConfig(name="repro", provider="anthropic", default_channel="console")}
        cfg.default_agent = "repro"
        cfg.storage.path = str(self.root / "openminion.db")
        save_config(cfg, str(path), home_root=self.root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["providers"]["anthropic"].update(base_url=self.base_url, model=self.model)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    def __exit__(self, *exc: object) -> None:
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
