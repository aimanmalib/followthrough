"""Record and replay the model API, so the demo runs without a key and gives the same answer every time.

`ReplayServer` is a local Anthropic Messages endpoint (`POST /v1/messages`, JSON or raw SSE bodies):
- record: forwards each request to the real API and saves the exchange under the hash of the request;
- serve: answers only from saved exchanges. A request with no saved answer is a miss: it gets an error
  reply, the closest saved request is diffed, and the run fails afterwards (no silent fallback).

The hash is taken over a canonical form of the request (sorted keys, configured keys dropped, then the
configured regex replacements for time stamps, UUIDs and session ids). Request headers are never saved,
so a key used while recording never reaches the files.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RECORD, SERVE = "record", "serve"


def canonical(body: bytes, cfg: Mapping[str, Any]) -> str:
    """The request as matched: JSON with sorted keys, dropped keys removed, volatile values replaced."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        data = body.decode("utf-8", "replace")
    if isinstance(data, dict):
        data = {k: v for k, v in data.items() if k not in set(cfg["drop_keys"])}
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1)
    for pattern, replacement in cfg["normalize"]:
        text = re.sub(pattern, replacement, text)
    return text


def request_key(path: str, text: str) -> str:
    return hashlib.sha256(f"{path}\n{text}".encode()).hexdigest()[:20]


@dataclass
class Miss:
    path: str
    key: str
    diff: str


@dataclass
class Tally:
    served: int = 0
    recorded: int = 0
    misses: list[Miss] = field(default_factory=list)


class Store:
    """Saved exchanges, one JSON file per request key."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def file(self, key: str) -> Path:
        return self.folder / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.file(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, path: str, text: str, status: int, content_type: str, body: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        record = {"path": path, "request": text,
                  "response": {"status": status, "content_type": content_type, "body": body}}
        self.file(key).write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def requests(self) -> Iterable[tuple[str, str]]:
        for path in sorted(self.folder.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            yield path.stem, record["request"]


def _lines(text: str) -> list[str]:
    # Prompts are long JSON strings: break them at their own newlines so a diff shows the changed line.
    return text.replace("\\n", "\\n\n").splitlines()


def _clip(line: str, other: str, width: int) -> str:
    """A long changed line, shown from just before its first difference with the paired line."""
    if len(line) <= width:
        return line
    # Index 0 is the diff marker ("-" or "+"), which always differs; the change is searched after it.
    start = next((i for i, (a, b) in enumerate(zip(line, other)) if i and a != b), min(len(line), len(other)))
    start = max(1, start - width // 4)
    return f"{line[0]}...{line[start:start + width]}..."


def closest_diff(store: Store, text: str, max_lines: int, width: int = 240) -> str:
    """Unified diff between a missed request and the most similar saved one."""
    best_key, best_text, best_ratio = "", "", -1.0
    for key, saved in store.requests():
        ratio = difflib.SequenceMatcher(None, saved, text, autojunk=False).quick_ratio()
        if ratio > best_ratio:
            best_key, best_text, best_ratio = key, saved, ratio
    if not best_key:
        return "(no saved requests)"
    raw = list(difflib.unified_diff(_lines(best_text), _lines(text), f"saved/{best_key}", "request",
                                    lineterm="", n=2))
    removed = [line for line in raw if line.startswith("-") and not line.startswith("---")]
    added = [line for line in raw if line.startswith("+") and not line.startswith("+++")]
    pairs = dict(zip(removed, added)) | dict(zip(added, removed))
    lines = [_clip(line, pairs.get(line, ""), width) for line in raw]
    if len(lines) > max_lines:
        lines = [*lines[:max_lines], f"... ({len(lines) - max_lines} more lines)"]
    return "\n".join(lines)


class ReplayServer:
    """The local endpoint. `start()` binds loopback on the configured port (0 = free); `close()` stops it."""

    def __init__(self, mode: str, store: Store, cfg: Mapping[str, Any], api_key: str | None = None) -> None:
        if mode not in (RECORD, SERVE):
            raise ValueError(mode)
        host = urllib.parse.urlsplit(str(cfg["upstream"])).hostname or ""
        if any(host == h or host.endswith("." + h) for h in cfg["forbidden_upstream_hosts"]):
            # The only write path to GitHub is post.py; the recorder must never become a second one.
            raise ValueError(f"replay upstream {host} is not a model API")
        self.mode, self.store, self.cfg, self.api_key = mode, store, cfg, api_key
        self.tally = Tally()
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://{self.cfg['host']}:{self._server.server_port}/v1"

    def start(self) -> ReplayServer:
        replay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("content-length") or 0))
                status, content_type, data = replay.handle(self.path, body, dict(self.headers.items()))
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer((self.cfg["host"], int(self.cfg["port"])), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> ReplayServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def handle(self, path: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, str, bytes]:
        text = canonical(body, self.cfg)
        key = request_key(path, text)
        if self.mode == RECORD:
            return self._record(path, key, text, body, headers)
        saved = self.store.get(key)
        if saved is None:
            diff = closest_diff(self.store, text, int(self.cfg["diff_lines"]), int(self.cfg["diff_width"]))
            with self._lock:
                self.tally.misses.append(Miss(path, key, diff))
            error = {"type": "error", "error": {"type": "invalid_request_error",
                                                "message": f"replay miss {key}: no recorded answer"}}
            return int(self.cfg["miss_status"]), "application/json", json.dumps(error).encode()
        with self._lock:
            self.tally.served += 1
        response = saved["response"]
        return int(response["status"]), response["content_type"], response["body"].encode("utf-8")

    def _record(self, path: str, key: str, text: str, body: bytes,
                headers: Mapping[str, str]) -> tuple[int, str, bytes]:
        wanted = {h.lower() for h in self.cfg["forward_headers"]}
        out = {k: v for k, v in headers.items() if k.lower() in wanted}
        if self.api_key:
            out["x-api-key"] = self.api_key
        # A request with a body is sent as the model API call it is; the recorder talks to `upstream` only.
        request = urllib.request.Request(self.cfg["upstream"].rstrip("/") + path, data=body, headers=out)
        try:
            with urllib.request.urlopen(request, timeout=float(self.cfg["upstream_timeout_s"])) as reply:
                status, content_type, data = reply.status, reply.headers.get("content-type", ""), reply.read()
        except urllib.error.HTTPError as err:
            status, content_type, data = err.code, err.headers.get("content-type", "application/json"), err.read()
            # A rejection of this exact request is part of the run (the client handles it the same way on
            # replay); a momentary failure (rate limit, timeout, 5xx) must never be replayed.
            if status >= int(self.cfg["save_errors_below"]) or status in set(self.cfg["never_save"]):
                return status, content_type, data
        with self._lock:
            self.store.put(key, path, text, status, content_type, data.decode("utf-8"))
            self.tally.recorded += 1
        return status, content_type, data


EXIT_MISS = 4  # the wrapped run asked something that was never recorded


def run(mode: str, command: list[str], root: Path, lang: str, port: int | None = None,
        folder: str | None = None) -> int:
    """Start the server, run one followthrough command against it in this process, stop the server.

    record: needs the real model key; old recordings in the folder are removed first.
    serve: needs no key (a placeholder is set when the variable is empty); any miss fails the run."""
    import os
    import sys

    from followthrough import cli, config

    cfg = dict(config.load("replay"))
    if port is not None:
        cfg["port"] = port
    key_env = config.load("models")["key_env"]
    base = Path(folder or cfg["dir"])
    store = Store(base if base.is_absolute() else root / base)
    saved_env = {name: os.environ.get(name) for name in (key_env, cfg["base_url_env"])}
    if mode == RECORD:
        if not os.environ.get(key_env):
            print(config.t("cli.key_missing", lang, env=key_env), file=sys.stderr)
            return cli.EXIT_USAGE
        for old in store.folder.glob("*.json"):
            old.unlink()
    elif not os.environ.get(key_env):
        os.environ[key_env] = cfg["placeholder_key"]
    server = ReplayServer(mode, store, cfg)
    try:
        server.start()
        os.environ[cfg["base_url_env"]] = server.base_url
        print(config.t("replay.listening", lang, mode=mode, url=server.base_url), file=sys.stderr)
        if not command:
            print(config.t("replay.no_command", lang), file=sys.stderr)
            return cli.EXIT_USAGE
        code = cli.main(command)
    finally:
        server.close()
        for name, value in saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    tally = server.tally
    print(config.t("replay.summary", lang, served=tally.served, recorded=tally.recorded,
                   missed=len(tally.misses)), file=sys.stderr)
    for miss in tally.misses:
        print(config.t("replay.miss", lang, key=miss.key, path=miss.path), file=sys.stderr)
        print(miss.diff, file=sys.stderr)
    return EXIT_MISS if tally.misses else code
