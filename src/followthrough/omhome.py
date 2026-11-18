"""Call the `openminion` CLI: in a throw-away home (echo provider) or against the project's own config.

The throw-away home is used for doctor's turn check and for the scheduling proof (ADR 0008). It has
its own config, database and daemon port, so nothing touches another OpenMinion install on the host,
and it is deleted on exit. Secrets are removed from the child environment, and any secret value that
still shows up in captured output is replaced before it is returned.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openminion.base.config import AgentProfileConfig, OpenMinionConfig, save_config

REDACTED = "[redacted]"
Runner = Callable[[Sequence[str], Mapping[str, str], float], subprocess.CompletedProcess[str]]


def run_process(argv: Sequence[str], env: Mapping[str, str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), env=dict(env), capture_output=True, text=True, timeout=timeout_s, check=False)


def free_port(host: str) -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def child_env(strip: Iterable[str], environ: Mapping[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """The environment without `strip`, plus the stripped values (for redaction)."""
    environ = dict(os.environ if environ is None else environ)
    secrets = [environ.pop(name) for name in strip if environ.get(name)]
    return environ, secrets


def redact(text: str, secrets: Iterable[str]) -> str:
    for value in secrets:
        if value:
            text = text.replace(value, REDACTED)
    return text


@dataclass
class Result:
    rc: int
    data: Any  # parsed JSON from stdout, or None when stdout was not JSON
    stdout: str
    stderr_tail: str


def parse(proc: subprocess.CompletedProcess[str], secrets: Iterable[str], tail_lines: int = 5) -> Result:
    secrets = list(secrets)
    out = redact(proc.stdout or "", secrets)
    try:
        data = json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        data = None
    # OpenMinion logs every registered tool on stderr; keep only the last lines for diagnosis.
    tail = "\n".join(redact(proc.stderr or "", secrets).strip().splitlines()[-tail_lines:])
    return Result(proc.returncode, data, out, tail)


def base_argv(config: Path, home: Path, data: Path) -> list[str]:
    return [sys.executable, "-m", "openminion", "--config", str(config), "--home-root", str(home),
            "--data-root", str(data), "--no-update-check", "--no-interactive"]


class IsolatedHome:
    """`with IsolatedHome(ops) as home: home.call("cron", "status", "--json")`."""

    def __init__(self, ops: Mapping[str, Any], runner: Runner | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self.ops = ops["isolated"]
        self.runner = runner or run_process
        self.env, self.secrets = child_env(self.ops["strip_env"], environ)
        self.root: Path | None = None
        self.port = 0

    def __enter__(self) -> IsolatedHome:
        self.root = Path(tempfile.mkdtemp(prefix="followthrough-om-"))
        self.port = free_port(self.ops["host"])
        self._write_config()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)
            self.root = None

    @property
    def config_path(self) -> Path:
        assert self.root is not None, "use IsolatedHome as a context manager"
        return self.root / "agents.json"

    def _write_config(self) -> None:
        assert self.root is not None
        name, provider = self.ops["profile"], self.ops["provider"]
        cfg = OpenMinionConfig()
        cfg.agents = {name: AgentProfileConfig(name=name, provider=provider, default_channel="console")}
        cfg.default_agent = name
        cfg.storage.path = str(self.root / "openminion.db")
        save_config(cfg, str(self.config_path), home_root=self.root)
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        # Own daemon port: the default one may belong to another OpenMinion on the same host.
        data["runtime"]["ipc_host"] = data["gateway"]["host"] = self.ops["host"]
        data["runtime"]["ipc_port"] = data["gateway"]["port"] = self.port
        self.config_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def call(self, *args: str) -> Result:
        assert self.root is not None
        argv = base_argv(self.config_path, self.root, self.root / "data") + list(args)
        proc = self.runner(argv, self.env, float(self.ops["command_timeout_s"]))
        return parse(proc, self.secrets)


def call_project(config_path: Path, data_root: Path, args: Sequence[str], ops: Mapping[str, Any],
                 keep: Iterable[str] = (), runner: Runner | None = None,
                 environ: Mapping[str, str] | None = None) -> Result:
    """Run `openminion` against the project's generated config (no turn: nothing is spent)."""
    keep = set(keep)
    env, secrets = child_env([n for n in ops["isolated"]["strip_env"] if n not in keep], environ)
    secrets += [env[n] for n in keep if env.get(n)]  # passed through, but never shown
    argv = base_argv(config_path, config_path.parent, data_root) + list(args)
    proc = (runner or run_process)(argv, env, float(ops["isolated"]["command_timeout_s"]))
    return parse(proc, secrets)
