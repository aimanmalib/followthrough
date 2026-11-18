"""`followthrough doctor` and `followthrough schedule --daily HH:MM` (product requirement 4.8, ADR 0008).

doctor: `openminion doctor --json` on the project's generated config (no turn, nothing spent), then
`openminion doctor --check-turn --json` in a throw-away home with the echo provider.

schedule: proves the OpenMinion scheduler with one daily task in a throw-away home: `cron create`,
a daemon started only for the proof, one `cron run`, then `cron pause`, `daemon stop` and the home is
deleted. The production schedule is the system cron line it prints; nothing is installed.
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from followthrough.omhome import IsolatedHome, Result, Runner, call_project


def parse_daily(value: str) -> tuple[int, int]:
    """"HH:MM" (24 h, UTC) -> (hour, minute); ValueError otherwise."""
    hour_s, sep, minute_s = value.partition(":")
    if not sep or not (hour_s.isdigit() and minute_s.isdigit()) or len(minute_s) != 2:
        raise ValueError(value)
    hour, minute = int(hour_s), int(minute_s)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(value)
    return hour, minute


def cron_expr(hour: int, minute: int) -> str:
    return f"{minute} {hour} * * *"


def cron_line(ops: Mapping[str, Any], hour: int, minute: int, repo: str, repo_dir: Path) -> str:
    return ops["schedule"]["cron_line"].format(minute=minute, hour=hour, repo=repo, repo_dir=repo_dir)


def doctor_summary(result: Result) -> dict[str, Any]:
    data = result.data if isinstance(result.data, dict) else {}
    summary = data.get("summary") or {}
    return {
        "rc": result.rc,
        "status": summary.get("status", "no_output"),
        "provider": summary.get("provider"),
        "counts": summary.get("counts", {}),
        "not_ok": [{"id": c.get("id"), "status": c.get("status")}
                   for c in data.get("checks", []) if c.get("status") != "ok"],
    }


def doctor(ops: Mapping[str, Any], agents_json: Path, key_env: str, *, runner: Runner | None = None,
           environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    project = call_project(agents_json, agents_json.parent, ["doctor", "--json"], ops, keep=[key_env],
                           runner=runner, environ=environ)
    with IsolatedHome(ops, runner, environ) as home:
        turn = home.call("doctor", "--check-turn", "--message", ops["doctor"]["message"], "--json")
    return {
        "project_config": doctor_summary(project),
        "turn_check": doctor_summary(turn),
        "raw": {"project_config": project.data, "turn_check": turn.data},
    }


def _data(result: Result) -> dict[str, Any]:
    if isinstance(result.data, dict) and isinstance(result.data.get("data"), dict):
        return result.data["data"]
    return {}


def _pid(home: IsolatedHome) -> int | None:
    assert home.root is not None
    path = home.root / "data" / "state" / "openminiond.pid"
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _last_run(home: IsolatedHome, task_id: str, pending: list[str], every_s: float, tries: int,
              sleep: Callable[[float], None]) -> dict[str, Any]:
    run: dict[str, Any] = {}
    for attempt in range(tries):
        task = _data(home.call("cron", "show", task_id, "--json")).get("task") or {}
        runs = task.get("runs") or []
        run = runs[0] if runs else {}
        if run and run.get("state") not in pending:
            return run
        if attempt + 1 < tries:
            sleep(every_s)
    return run


def schedule_proof(ops: Mapping[str, Any], hour: int, minute: int, *, runner: Runner | None = None,
                   environ: Mapping[str, str] | None = None,
                   sleep: Callable[[float], None] = time.sleep,
                   is_alive: Callable[[int | None], bool] = alive) -> dict[str, Any]:
    s = ops["schedule"]
    report: dict[str, Any] = {"cron": cron_expr(hour, minute), "tz": s["tz"], "task_name": s["task_name"]}
    with IsolatedHome(ops, runner, environ) as home:
        created = home.call("cron", "create", "--instruction", s["instruction"], "--cron", cron_expr(hour, minute),
                            "--tz", s["tz"], "--name", s["task_name"], "--json")
        task = _data(created)
        task_id = str(task.get("task_id") or "")
        report["create"] = {"rc": created.rc, "ok": bool(task_id), "next_due_at": task.get("next_due_at"),
                            "scheduler_note": task.get("scheduler_note")}
        if not task_id:
            report["error"] = created.stderr_tail
            report["home_removed"] = True
            return _finish(report)
        started = home.call("daemon", "start")
        pid = _pid(home)
        report["daemon"] = {"start_rc": started.rc, "started": pid is not None}
        try:
            queued = _data(home.call("cron", "run", "--job-id", task_id, "--json"))
            report["run"] = {"queued_state": queued.get("state")}
            last = _last_run(home, task_id, list(s["pending_states"]), float(s["poll_every_s"]),
                             int(s["poll_max"]), sleep) if pid is not None else {}
            output = last.get("output") or {}
            delivery = output.get("delivery") if isinstance(output, dict) else None
            report["run"].update({
                "state": last.get("state"), "started_at": last.get("started_at"),
                "finished_at": last.get("finished_at"), "error": last.get("error"),
                "summary_is_instruction": (last.get("summary") or "").endswith(s["instruction"]),
                "delivery_state": (delivery or {}).get("state"),
                "delivery_error": ((delivery or {}).get("error") or {}).get("code"),
            })
        finally:
            paused = _data(home.call("cron", "pause", task_id, "--json"))
            report["pause"] = {"enabled": paused.get("enabled"), "next_due_at": paused.get("next_due_at")}
            stop = home.call("daemon", "stop")
            report["daemon"].update({"stop_rc": stop.rc, "alive_after_stop": is_alive(pid)})
            if is_alive(pid):  # never leave a daemon behind
                os.kill(pid, signal.SIGTERM)  # type: ignore[arg-type]
                report["daemon"]["killed"] = True
    report["home_removed"] = home.root is None
    return _finish(report)


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    run = report.get("run") or {}
    daemon = report.get("daemon") or {}
    report["ok"] = bool(
        report.get("create", {}).get("ok")
        and run.get("state") == "finished"
        and report.get("pause", {}).get("enabled") is False
        and not daemon.get("alive_after_stop")
        and report.get("home_removed")
    )
    return report
