"""`followthrough doctor` / `schedule`: isolated OpenMinion home, one proof run, nothing left behind."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from followthrough import cli, config, omhome, schedule

OPS = config.load("ops")
SECRET = "sk-test-not-a-real-key-123456"
ENV = {"PATH": "/usr/bin:/bin", "ANTHROPIC_API_KEY": SECRET, "GITHUB_TOKEN": "ghp_fake_token_value"}


def _ops(**schedule_overrides):
    ops = json.loads(json.dumps(OPS))
    ops["schedule"].update({"poll_every_s": 0, **schedule_overrides})
    return ops


class FakeOpenMinion:
    """Plays `python -m openminion ...` for the proof: create, daemon, run, show, pause, stop."""

    def __init__(self, create_ok=True, final_state="finished", leftover=None):
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.create_ok, self.final_state, self.leftover = create_ok, final_state, leftover
        self.shows = 0

    def __call__(self, argv, env, timeout_s):
        argv = list(argv)
        self.calls.append(argv)
        self.envs.append(dict(env))
        i = argv.index("--no-interactive") + 1
        cmd, home = argv[i:], Path(argv[argv.index("--home-root") + 1])
        out = ""
        if cmd[:2] == ["cron", "create"]:
            data = {"task_id": "t1", "next_due_at": "2026-11-18T06:30:00+00:00"} if self.create_ok else {}
            out = json.dumps({"ok": self.create_ok, "data": data})
        elif cmd[:2] == ["daemon", "start"]:
            pid_file = home / "data" / "state" / "openminiond.pid"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(self.leftover.pid if self.leftover else 999999999))
            out = "Started daemon pid=1"
        elif cmd[:2] == ["cron", "run"]:
            out = json.dumps({"ok": True, "data": {"state": "queued"}})
        elif cmd[:2] == ["cron", "show"]:
            self.shows += 1
            state = "queued" if self.shows < 2 else self.final_state
            run = {"state": state, "summary": "scheduler: " + OPS["schedule"]["instruction"],
                   "output": {"delivery": {"state": "failed", "error": {"code": "cron_delivery_failed"}}}}
            out = json.dumps({"ok": True, "data": {"task": {"runs": [run]}}})
        elif cmd[:2] == ["cron", "pause"]:
            out = json.dumps({"ok": True, "data": {"enabled": False, "next_due_at": None}})
        elif cmd[:1] == ["doctor"]:
            out = json.dumps({"summary": {"status": "ok", "provider": "echo", "counts": {"ok": 2}},
                              "checks": [{"id": "a", "status": "ok"}, {"id": "b", "status": "warn",
                                                                       "message": SECRET}]})
        return subprocess.CompletedProcess(argv, 0, out, "INFO lots of tool registrations\n" + SECRET)

    def commands(self):
        return [c[c.index("--no-interactive") + 1:][:2] for c in self.calls]


@pytest.mark.parametrize("value,expected", [("06:30", (6, 30)), ("0:05", (0, 5)), ("23:59", (23, 59))])
def test_parse_daily(value, expected):
    assert schedule.parse_daily(value) == expected
    assert schedule.cron_expr(*expected) == f"{expected[1]} {expected[0]} * * *"


@pytest.mark.parametrize("value", ["24:00", "06:60", "6", "06:5", "ab:cd", "-1:30", ""])
def test_parse_daily_rejects(value):
    with pytest.raises(ValueError):
        schedule.parse_daily(value)


def test_proof_creates_runs_pauses_stops_and_deletes():
    fake = FakeOpenMinion()
    report = schedule.schedule_proof(_ops(), 6, 30, runner=fake, environ=ENV, sleep=lambda s: None)
    assert report["ok"] is True
    assert fake.commands() == [["cron", "create"], ["daemon", "start"], ["cron", "run"], ["cron", "show"],
                               ["cron", "show"], ["cron", "pause"], ["daemon", "stop"]]
    assert report["run"]["state"] == "finished" and report["run"]["summary_is_instruction"]
    assert report["run"]["delivery_error"] == "cron_delivery_failed"
    assert report["pause"]["enabled"] is False and report["daemon"]["alive_after_stop"] is False
    homes = {c[c.index("--home-root") + 1] for c in fake.calls}
    assert len(homes) == 1 and not Path(homes.pop()).exists()  # the throw-away home is gone
    create = fake.calls[0]
    assert create[create.index("--cron") + 1] == "30 6 * * *" and create[create.index("--tz") + 1] == "UTC"


def test_secrets_never_reach_openminion_or_the_report():
    fake = FakeOpenMinion()
    report = schedule.schedule_proof(_ops(), 6, 30, runner=fake, environ=ENV, sleep=lambda s: None)
    assert all("ANTHROPIC_API_KEY" not in e and "GITHUB_TOKEN" not in e for e in fake.envs)
    assert SECRET not in json.dumps(report)


def test_create_failure_starts_no_daemon():
    fake = FakeOpenMinion(create_ok=False)
    report = schedule.schedule_proof(_ops(), 6, 30, runner=fake, environ=ENV, sleep=lambda s: None)
    assert report["ok"] is False and fake.commands() == [["cron", "create"]]


def test_run_still_queued_fails_but_still_cleans_up():
    fake = FakeOpenMinion(final_state="queued")
    report = schedule.schedule_proof(_ops(poll_max=3), 6, 30, runner=fake, environ=ENV, sleep=lambda s: None)
    assert report["ok"] is False and report["run"]["state"] == "queued"
    assert fake.commands()[-2:] == [["cron", "pause"], ["daemon", "stop"]]


def test_daemon_that_survives_stop_is_killed():
    leftover = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        fake = FakeOpenMinion(leftover=leftover)
        report = schedule.schedule_proof(_ops(), 6, 30, runner=fake, environ=ENV, sleep=lambda s: None)
        assert report["daemon"]["alive_after_stop"] is True and report["daemon"]["killed"] is True
        assert leftover.wait(timeout=10) != 0
        assert report["ok"] is False
    finally:
        if leftover.poll() is None:
            leftover.kill()


def test_doctor_checks_project_config_and_echo_turn(tmp_path: Path):
    fake = FakeOpenMinion()
    agents_json = tmp_path / "agents.json"
    report = schedule.doctor(OPS, agents_json, "ANTHROPIC_API_KEY", runner=fake, environ=ENV)
    project, turn = fake.calls
    assert project[project.index("--config") + 1] == str(agents_json) and "--check-turn" not in project
    assert "--check-turn" in turn and turn[turn.index("--config") + 1] != str(agents_json)
    assert fake.envs[0].get("ANTHROPIC_API_KEY") == SECRET and "GITHUB_TOKEN" not in fake.envs[0]
    assert "ANTHROPIC_API_KEY" not in fake.envs[1]
    assert report["turn_check"]["not_ok"] == [{"id": "b", "status": "warn"}]
    assert SECRET not in json.dumps(report)


def test_isolated_home_uses_its_own_port_and_echo_provider():
    with omhome.IsolatedHome(OPS, runner=FakeOpenMinion(), environ=ENV) as home:
        data = json.loads(home.config_path.read_text(encoding="utf-8"))
        root = home.root
    assert data["runtime"]["ipc_port"] == data["gateway"]["port"] == home.port != 18789
    assert data["agents"][OPS["isolated"]["profile"]]["provider"] == "echo"
    assert root is not None and not root.exists()


def test_cli_rejects_bad_time(capsys):
    assert cli.main(["schedule", "--daily", "25:00"]) == cli.EXIT_USAGE
    assert "HH:MM" in capsys.readouterr().err


def test_cron_line_comes_from_config():
    line = schedule.cron_line(OPS, 6, 30, "o/r", Path("/srv/ft"))
    assert line.startswith("30 6 * * * cd /srv/ft && ") and "--repo o/r" in line
