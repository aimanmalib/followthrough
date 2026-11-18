"""`openminion cron run` answers ok and `queued` when no daemon is running, and the run never starts.

A throw-away home (key-free `echo` provider, its own free daemon port so no other OpenMinion on the
host is reached) gets one cron task; `cron run` is called with no daemon; `cron show` is polled for
`WAIT_S` seconds. Nothing tells the caller that a daemon is needed. The task is paused and the home
deleted afterwards. Run from the repository root: `uv run python repro/cron-run-ok-without-daemon/repro.py`
Exit 0 = the gap is still there (rc 0, run still queued); 1 = the run started or the CLI refused.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from openminion.base.config import AgentProfileConfig, OpenMinionConfig, save_config

WAIT_S = 30


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_home(root: Path) -> Path:
    path = root / "agents.json"
    cfg = OpenMinionConfig()
    cfg.agents = {"repro": AgentProfileConfig(name="repro", provider="echo", default_channel="console")}
    cfg.default_agent = "repro"
    cfg.storage.path = str(root / "openminion.db")
    save_config(cfg, str(path), home_root=root)
    data = json.loads(path.read_text(encoding="utf-8"))
    port = free_port()
    data["runtime"]["ipc_host"] = data["gateway"]["host"] = "127.0.0.1"
    data["runtime"]["ipc_port"] = data["gateway"]["port"] = port
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def om(config: Path, root: Path, *args: str) -> tuple[int, dict]:
    argv = [sys.executable, "-m", "openminion", "--config", str(config), "--home-root", str(root),
            "--data-root", str(root / "data"), "--no-update-check", "--no-interactive", *args]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_TOKEN")}
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=180, check=False)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {}
    data = out.get("data") if isinstance(out, dict) else None  # the CLI wraps results as {"data": {...}}
    data = dict(data) if isinstance(data, dict) else {}
    data["_ok"] = out.get("ok") if isinstance(out, dict) else None
    return proc.returncode, data


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="om-repro-cron-"))
    try:
        config = make_home(root)
        rc, task = om(config, root, "cron", "create", "--instruction", "repro ping", "--cron", "0 6 * * *",
                      "--tz", "UTC", "--name", "repro", "--json")
        task_id = str(task.get("task_id") or "")
        print(f"cron create: rc {rc}, task id present: {bool(task_id)}")
        if not task_id:
            return 1
        rc, queued = om(config, root, "cron", "run", "--job-id", task_id, "--json")
        print(f"cron run (no daemon): rc {rc}, ok {queued.get('_ok')!r}, state {queued.get('state')!r}")
        deadline, state = time.monotonic() + WAIT_S, None
        while time.monotonic() < deadline:
            _, shown = om(config, root, "cron", "show", task_id, "--json")
            runs = (shown.get("task") or {}).get("runs") or []
            state = runs[0].get("state") if runs else None
            if state not in ("queued", None):
                break
            time.sleep(3)
        print(f"run state after {WAIT_S} s: {state!r}")
        _, paused = om(config, root, "cron", "pause", task_id, "--json")
        print(f"cron pause: enabled {paused.get('enabled')!r}")
        return 0 if rc == 0 and state == "queued" else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
