"""Sweep pipeline and digest, offline: saved readings -> guard -> rules -> digest, plus the CLI."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from followthrough import cli, config, digest, sweep
from followthrough.agents import ReadOutcome, ReadReport
from followthrough.rules import ACTIONS, NO_ACTION
from followthrough.state import parse_ts

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
STATES = json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text(encoding="utf-8"))
NOW = parse_ts(SNAPSHOT["fixture"]["now"])
POLICY = config.load("policy")
LIST = POLICY["digest"]["list_actions"]


def _digest(states=STATES, snapshot=SNAPSHOT, stopped=None):
    report = sweep.read_with_states(snapshot, states)
    report.stopped = stopped
    rows = sweep.decide_all(snapshot, report, NOW, POLICY)
    return digest.build(snapshot["repo"], NOW, "fixture", "states", rows, stopped=stopped)


def _texts(snapshot):
    """Every piece of thread text a digest must never repeat (titles, bodies, comments)."""
    for th in snapshot["threads"]:
        yield th["title"]
        yield th["body"]
        yield from (c["body"] for c in th["comments"])


def test_fixture_digest_matches_expected_actions():
    built = _digest()
    got = {i["number"]: i["action"] for i in built["items"]}
    assert got == {int(n): a for n, a in SNAPSHOT["fixture"]["expected"].items()}
    assert sum(built["counts"].values()) == built["threads"] == len(SNAPSHOT["threads"])
    assert built["guard_rejected"] == built["read_failed"] == 0


def test_items_ordered_by_action_then_number_with_dates():
    items = _digest()["items"]
    keys = [(ACTIONS.index(i["action"]), i["number"]) for i in items]
    assert keys == sorted(keys)
    for item in items:
        if item["action"] != NO_ACTION:
            assert item["dates"] or item["release_tag"], item


def test_fake_quote_is_rejected_and_counted():
    states = copy.deepcopy(STATES)
    fake = SNAPSHOT["fixture"]["fake_quote"]
    target = next(s for s in states["states"] if s["number"] == fake["number"])
    target.update(open_request_quote=fake["quote"], open_request_at=fake["at"])
    built = _digest(states)
    item = next(i for i in built["items"] if i["number"] == fake["number"])
    assert (item["action"], item["reason"], item["guard_rejected"]) == (NO_ACTION, "unclear", True)
    assert built["guard_rejected"] == 1


def test_thread_without_reading_is_counted_as_read_failed():
    states = {"states": [s for s in STATES["states"] if s["number"] != 101]}
    built = _digest(states)
    item = next(i for i in built["items"] if i["number"] == 101)
    assert (item["action"], item["reason"]) == (NO_ACTION, digest.READ_FAILED)
    assert built["read_failed"] == 1


@pytest.mark.parametrize("lang", config.LANGS)
def test_markdown_uses_locale_strings_and_no_thread_text(lang):
    built = _digest()
    md = digest.render_md(built, lang, LIST)
    assert config.t("digest.title", lang, repo=SNAPSHOT["repo"]) in md
    for action in LIST:
        assert config.t(f"actions.{action}", lang) in md
    for item in built["items"]:
        if item["action"] in LIST:
            assert f"#{item['number']}: {digest.line(item, lang)}" in md
    assert "{" not in md and "}" not in md
    blob = md + json.dumps(built, ensure_ascii=False)
    assert not [text for text in _texts(SNAPSHOT) if text and text in blob]


def test_actions_outside_list_are_counted_not_listed():
    md = digest.render_md(_digest(), "en", ["FOLLOW_UP_DUE"])
    assert "#101:" in md and "#103:" not in md
    assert f"| {config.t('actions.TAKEOVER_ALLOWED', 'en')} | 1 |" in md


def test_partial_digest_is_marked():
    md = digest.render_md(_digest(stopped="limit reached"), "en", LIST)
    assert config.t("digest.partial", "en", reason="limit reached") in md


def test_write_puts_json_and_markdown_in_a_dated_folder(tmp_path):
    built = _digest()
    folder = digest.write(built, "md\n", tmp_path)
    assert folder == tmp_path / SNAPSHOT["fixture"]["now"][:10]
    assert json.loads((folder / "digest.json").read_text())["counts"] == built["counts"]
    assert (folder / "digest.md").read_text() == "md\n"


@pytest.mark.parametrize("argv", [["--lang", "ms", "sweep", "--fixture"], ["sweep", "--fixture", "--lang", "ms"]])
def test_cli_fixture_sweep_prints_malay_digest(argv, tmp_path, capsys):
    assert cli.main([*argv, "--out", str(tmp_path)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("# " + config.t("digest.title", "ms", repo=SNAPSHOT["repo"]))
    assert (tmp_path / SNAPSHOT["fixture"]["now"][:10] / "digest.md").read_text() == out


def test_cli_json_format(tmp_path, capsys):
    assert cli.main(["sweep", "--fixture", "--format", "json", "--out", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["reader"] == "states"


@pytest.mark.parametrize("argv", [["sweep", "--live"], ["sweep", "--live", "--repo", "noslash"],
                                  ["sweep", "--live", "--repo", "o/r", "--reader", "states"]])
def test_cli_live_usage_errors_stop_before_network(argv, monkeypatch, capsys):
    import followthrough.github as gh

    monkeypatch.setenv(config.load("models")["key_env"], "test-key-not-real")
    monkeypatch.setattr(gh, "GitHub", lambda *a, **k: pytest.fail("GitHub must not be reached"))
    assert cli.main(argv) == cli.EXIT_USAGE


def test_cli_model_reader_without_key_refuses(monkeypatch, tmp_path, capsys):
    env = config.load("models")["key_env"]
    monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(sweep, "read_with_model", lambda *a: pytest.fail("model must not be called"))
    assert cli.main(["sweep", "--fixture", "--reader", "model", "--out", str(tmp_path)]) == cli.EXIT_USAGE
    assert env in capsys.readouterr().err


class _FakeGitHub:
    """Stands in for the GET-only client: returns the fixture snapshot and logs GET requests."""

    def __init__(self, *args, **kwargs):
        self.requests = [("GET", "/repos/o/r/issues", 200), ("GET", "/repos/o/r/releases", 304)]

    def snapshot(self, owner, repo, now, numbers=None):
        return dict(copy.deepcopy(SNAPSHOT), repo=f"{owner}/{repo}")

    def write_snapshot(self, snap, now):
        return None

    def save_cache(self):
        return None


def _model_report(stopped=None):
    def fake(snapshot, now, root):
        report = sweep.read_with_states(snapshot, STATES)
        report.stopped = stopped
        return report
    return fake


@pytest.mark.parametrize("stopped,code", [(None, cli.EXIT_OK), ("over budget", cli.EXIT_PARTIAL)])
def test_cli_live_sweep_logs_http_methods(stopped, code, monkeypatch, tmp_path, capsys):
    import followthrough.github as gh

    monkeypatch.setattr(gh, "GitHub", _FakeGitHub)
    monkeypatch.setenv(config.load("models")["key_env"], "test-key-not-real")
    monkeypatch.setattr(sweep, "read_with_model", _model_report(stopped))
    argv = ["sweep", "--live", "--repo", "o/r", "--now", SNAPSHOT["fixture"]["now"], "--format", "json",
            "--out", str(tmp_path)]
    assert cli.main(argv) == code
    built = json.loads(capsys.readouterr().out)
    assert (built["mode"], built["reader"], built["repo"]) == ("live", "model", "o/r")
    assert built["http"] == {"requests": 2, "non_get": 0}
    assert built["stopped"] == stopped
    assert built["reading"]["threads"] == len(SNAPSHOT["threads"])


def test_read_with_states_matches_report_shape():
    report = sweep.read_with_states(SNAPSHOT, STATES)
    assert isinstance(report, ReadReport)
    assert all(isinstance(o, ReadOutcome) and o.source == "states" for o in report.outcomes)
