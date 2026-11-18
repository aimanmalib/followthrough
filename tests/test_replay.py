"""Record/replay of the model API: matching, recording without headers, serving, and loud misses."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fake_anthropic import FakeAnthropic
from followthrough import config, replay, sweep
from followthrough.replay import RECORD, SERVE, ReplayServer, Store, canonical, request_key

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = json.loads((ROOT / "fixtures" / "sandbox-repo.json").read_text(encoding="utf-8"))
STATES = {s["number"]: s for s in json.loads((ROOT / "fixtures" / "sandbox-states.json").read_text())["states"]}
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
CFG = config.load("replay")
NO_CACHE = {"enabled": False, "cache_dir": "state/readings"}


def _post(url: str, body: dict, headers: dict | None = None) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url + "/messages", data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            return reply.status, reply.headers["content-type"], reply.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers["content-type"], err.read()


def _upstream_cfg(fake: FakeAnthropic) -> dict:
    return {**CFG, "upstream": fake.base_url.removesuffix("/v1")}


def test_volatile_values_and_dropped_keys_do_not_change_the_key():
    a = {"model": "m", "metadata": {"user_id": "1"}, "system": "run 3f2b1c9e-0000-4000-8000-00000000abcd at "
         "2026-11-18T06:00:01.123Z session sweep:o__r:20261118", "messages": []}
    b = {**a, "metadata": {"user_id": "2"}, "system": "run 11111111-2222-4333-8444-555555555555 at "
         "2026-11-19T07:30:00+00:00 session sweep:o__r:20261119"}
    assert request_key("/v1/messages", canonical(json.dumps(a).encode(), CFG)) == request_key(
        "/v1/messages", canonical(json.dumps(b).encode(), CFG))
    c = {**a, "messages": [{"role": "user", "content": "thread #101"}]}
    assert canonical(json.dumps(a).encode(), CFG) != canonical(json.dumps(c).encode(), CFG)


def test_record_saves_the_answer_but_no_request_header(tmp_path):
    fake = FakeAnthropic(lambda n: "hello")
    try:
        with ReplayServer(RECORD, Store(tmp_path), _upstream_cfg(fake)) as server:
            status, _, data = _post(server.base_url, {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                                    {"x-api-key": "secret-key-must-not-be-saved"})
    finally:
        fake.close()
    assert status == 200 and json.loads(data)["content"]
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1 and server.tally.recorded == 1
    assert "secret-key-must-not-be-saved" not in files[0].read_text()
    assert len(fake.requests) == 1


@pytest.mark.parametrize("status,saved", [(400, True), (429, False), (529, False), (500, False)])
def test_only_repeatable_upstream_rejections_are_saved(tmp_path, status, saved):
    fake = FakeAnthropic(lambda n: "x", status=status)
    try:
        with ReplayServer(RECORD, Store(tmp_path), _upstream_cfg(fake)) as server:
            got, _, _ = _post(server.base_url, {"model": "m", "messages": []})
    finally:
        fake.close()
    assert got == status
    assert (len(list(tmp_path.glob("*.json"))) == 1) is saved and server.tally.recorded == int(saved)
    if saved:
        with ReplayServer(SERVE, Store(tmp_path), CFG) as server:
            assert _post(server.base_url, {"model": "m", "messages": []})[0] == status
        assert server.tally.served == 1 and not server.tally.misses


def test_serve_returns_the_saved_body_byte_for_byte_including_sse(tmp_path):
    body = {"model": "m", "stream": True, "messages": [{"role": "user", "content": "hi"}]}
    sse = 'event: message_start\ndata: {"type": "message_start"}\n\nevent: message_stop\ndata: {}\n\n'
    text = canonical(json.dumps(body).encode(), CFG)
    Store(tmp_path).put(request_key("/v1/messages", text), "/v1/messages", text, 200, "text/event-stream", sse)
    with ReplayServer(SERVE, Store(tmp_path), CFG) as server:
        status, content_type, data = _post(server.base_url, body)
    assert (status, content_type, data.decode()) == (200, "text/event-stream", sse)
    assert server.tally.served == 1 and not server.tally.misses


def test_a_miss_fails_with_a_diff_to_the_closest_saved_request(tmp_path):
    saved = {"model": "m", "messages": [{"role": "user", "content": "thread #101"}]}
    text = canonical(json.dumps(saved).encode(), CFG)
    Store(tmp_path).put(request_key("/v1/messages", text), "/v1/messages", text, 200, "application/json", "{}")
    with ReplayServer(SERVE, Store(tmp_path), CFG) as server:
        status, _, _ = _post(server.base_url, {**saved, "messages": [{"role": "user", "content": "thread #102"}]})
    assert status == CFG["miss_status"] and server.tally.served == 0
    [miss] = server.tally.misses
    assert '-   "content": "thread #101",' in miss.diff and '+   "content": "thread #102",' in miss.diff


def _read_all(root: Path) -> list:
    report = sweep.read_with_model(SNAPSHOT, NOW, root, cache_cfg=NO_CACHE)
    return [(o.number, o.error, o.checked.state.waiting_on if o.checked and o.checked.state else None)
            for o in report.outcomes]


def test_a_recorded_reader_run_replays_offline_with_the_same_readings(tmp_path, monkeypatch):
    """Record a model-reader sweep through the fake API, then replay it with the fake gone: same readings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    fake = FakeAnthropic(lambda n: json.dumps(STATES.get(n, {})), submit=lambda n: json.dumps(STATES[n]))
    store = Store(tmp_path / "recorded")
    try:
        with ReplayServer(RECORD, store, _upstream_cfg(fake)) as server:
            monkeypatch.setenv(CFG["base_url_env"], server.base_url)
            recorded = _read_all(tmp_path / "a")
    finally:
        fake.close()
    assert server.tally.recorded == len(fake.requests) > 0
    with ReplayServer(SERVE, store, CFG) as server:
        monkeypatch.setenv(CFG["base_url_env"], server.base_url)
        replayed = _read_all(tmp_path / "b")
    assert replayed == recorded and not server.tally.misses
    assert server.tally.served == len(fake.requests)


def test_run_without_a_command_or_key_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.delenv(config.load("models")["key_env"], raising=False)
    assert replay.run(RECORD, ["sweep", "--fixture"], tmp_path, "en", folder=str(tmp_path / "r")) == 2
    assert replay.run(SERVE, [], tmp_path, "en", folder=str(tmp_path / "r")) == 2


@pytest.mark.parametrize("lang", ["en", "ms"])
def test_replay_strings_exist_in_both_languages(lang):
    assert "{missed}" in config.strings(lang)["replay.summary"]


def test_tracked_recordings_hold_no_key_or_local_path_and_match_the_current_rules():
    """Every recording is keyed by today's normalization (a rule change needs a re-record or re-key)."""
    files = sorted((ROOT / CFG["dir"]).glob("*.json"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for needle in ("x-api-key", "sk-ant-", "Bearer ", "/home/", "/tmp/"):
            assert needle not in text, (path.name, needle)
        record = json.loads(text)
        renormalized = canonical(json.dumps(json.loads(record["request"])).encode(), CFG)
        assert request_key(record["path"], renormalized) == path.stem


def test_a_long_changed_line_is_shown_around_its_change_not_its_start():
    head = "x" * 500
    shown = replay._clip(f"-{head}OLD-tail", f"+{head}NEW-tail", 80)
    assert "OLD" in shown and shown.startswith("-...")
