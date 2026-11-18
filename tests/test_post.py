"""H4: the approval gate and allow-list on the only write path. Model and GitHub are both faked.

The publisher runs on the real OpenMinion runtime against a local fake Anthropic server whose model
calls `post_comment`; GitHub is a fake `urlopen` that counts requests. Order of checks under test:
stop file -> allow-list -> approval -> exactly one POST.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from fake_anthropic import FakeAnthropic
from followthrough import agents, config, post
from followthrough.spend import Spend

SANDBOX = "aimanmalib/followthrough-sandbox"
BODY = "Follow-up due 2026-11-20; take-over allowed from 2026-11-23."


class FakeGitHub:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []

    def __call__(self, req, timeout=None):
        self.requests.append((req.get_method(), req.full_url, json.loads(req.data or b"{}")))
        return io.BytesIO(json.dumps({"html_url": f"https://github.com/{SANDBOX}/issues/7#issuecomment-1"}).encode())


def _post_input(body: str = BODY):
    def make(text: str) -> dict:
        repo = re.search(r"repo: (\S+)", text).group(1)
        number = int(re.search(r"number: (\d+)", text).group(1))
        return {"repo": repo, "number": number, "body": body}
    return make


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token-not-real")
    monkeypatch.delenv("PERANAN_HENTI", raising=False)
    monkeypatch.delenv("PERANAN_KELUAR_PY", raising=False)
    servers: list[FakeAnthropic] = []
    safety = dict(config.load("safety"), allow_post_repos=[SANDBOX])

    def _publish(approver, repo=SANDBOX, model_body=BODY, safety=safety):
        fake = FakeAnthropic(lambda n: "done", calls={"post_comment": _post_input(model_body)})
        servers.append(fake)
        gh = FakeGitHub()
        path = agents.write_agents_json(tmp_path, base_url=fake.base_url)
        result = post.publish(repo, 7, BODY, approver=approver, config_path=path,
                              spend=Spend(tmp_path, "test-post"), root=tmp_path, opener=gh,
                              safety=safety, timeout_s=60)
        return result, gh, fake

    yield _publish
    for fake in servers:
        fake.close()


def test_no_approver_pauses_without_model_or_http(env):
    result, gh, fake = env(None)
    assert result.status == "paused"
    assert gh.requests == [] and fake.requests == []


def test_deny_sends_nothing(env):
    seen = []
    result, gh, fake = env(lambda repo, n, body: seen.append((repo, n, body)) or post.DENY)
    assert seen == [(SANDBOX, 7, BODY)]  # the approver saw exactly what would be posted
    assert result.status == "denied"
    assert gh.requests == []
    assert len(fake.requests) >= 1  # the model did ask for the tool; the policy refused it


def test_allow_once_posts_exactly_once(env):
    result, gh, _ = env(lambda *a: post.ALLOW_ONCE)
    assert result.status == "posted" and result.http_posts == 1
    assert len(gh.requests) == 1
    method, url, payload = gh.requests[0]
    assert method == "POST"
    assert url.endswith(f"/repos/{SANDBOX}/issues/7/comments")
    assert payload == {"body": BODY}
    assert result.url and result.url.startswith("https://github.com/")


def test_repo_off_the_allow_list_is_refused_before_model_and_http(env):
    asked = []
    result, gh, fake = env(lambda *a: asked.append(a) or post.ALLOW_ONCE, repo="openminion/openminion")
    assert result.status == "refused_repo"
    assert asked == [] and gh.requests == [] and fake.requests == []


def test_empty_allow_list_means_nothing_posts(env):
    result, gh, fake = env(lambda *a: post.ALLOW_ONCE, safety=dict(config.load("safety"), allow_post_repos=[]))
    assert result.status == "refused_repo" and gh.requests == [] and fake.requests == []


def test_shipped_allow_list_refuses_the_measured_third_party_repo(env):
    shipped = config.load("safety")
    assert shipped["allow_post_repos"] == [SANDBOX]
    result, gh, fake = env(lambda *a: post.ALLOW_ONCE, repo="openminion/openminion", safety=shipped)
    assert result.status == "refused_repo" and gh.requests == [] and fake.requests == []


@pytest.mark.parametrize("where", ["env", "repo"])
def test_stop_file_exits_5_before_anything(env, tmp_path, monkeypatch, where):
    if where == "env":
        marker = tmp_path / "owner-stop"
        monkeypatch.setenv("PERANAN_HENTI", str(marker))
    else:
        marker = tmp_path / config.load("safety")["stop_file"]
        marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    with pytest.raises(post.Stopped) as exc:
        env(lambda *a: post.ALLOW_ONCE)
    assert exc.value.code == 5


def test_stop_file_created_after_approval_still_stops_inside_the_tool(env, tmp_path, monkeypatch):
    marker = tmp_path / "owner-stop"
    monkeypatch.setenv("PERANAN_HENTI", str(marker))

    def approve_then_stop(*_a):
        marker.write_text("")  # owner pulls the switch while the approval prompt is open
        return post.ALLOW_ONCE

    with pytest.raises(post.Stopped) as exc:
        _, gh, _ = env(approve_then_stop)
    assert exc.value.code == 5


def test_stop_records_the_refusal_when_a_recorder_is_set(tmp_path, monkeypatch):
    log = tmp_path / "refusals.txt"
    recorder = tmp_path / "recorder.py"
    recorder.write_text(f"import sys; open({str(log)!r}, 'a').write(' '.join(sys.argv[1:]))\n")
    marker = tmp_path / "owner-stop"
    marker.write_text("")
    monkeypatch.setenv("PERANAN_HENTI", str(marker))
    monkeypatch.setenv("PERANAN_KELUAR_PY", str(recorder))
    with pytest.raises(post.Stopped):
        post.check_stop(config.load("safety"), tmp_path)
    assert log.read_text() == f"tolak {post.GATE_NAME}"


def test_tool_posts_only_the_approved_body(env):
    result, gh, _ = env(lambda *a: post.ALLOW_ONCE, model_body=BODY + " Also closing this.")
    assert result.status == "not_posted"
    assert gh.requests == []


def test_poster_never_shows_the_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value-123456")
    poster = post.CommentPoster(config.load("policy"))
    assert "secret-value" not in repr(poster)


def test_post_module_is_the_only_writer():
    src = Path(post.__file__).resolve().parent
    writers = [p.name for p in src.glob("*.py")
               if re.search(r"method *= *[\"'](POST|PUT|PATCH|DELETE)[\"']", p.read_text(encoding="utf-8"))]
    assert writers == ["post.py"]


def test_handoff_delegate_does_not_forward_approval_so_post_is_never_behind_one():
    """Measured on openminion 0.1.23 (ADR 0006): a Handoff's transfer tool calls `target.run(message)`
    with no approval_callback, so a dangerous tool behind it would fall back to the console prompt.
    That is why `publish()` runs the publisher directly with an explicit approval callback."""
    from openminion.api.handoff import Handoff, build_delegate_tool

    class Target:
        name = "publisher"
        instructions = "post"
        calls: list = []

        def run(self, message, **kwargs):
            Target.calls.append(kwargs)

            class R:
                output, text, run_id, run_state = "ok", "ok", None, None
            return R()

    decl = build_delegate_tool(Handoff(target=Target()))
    decl.handler({"message": "post it"})
    assert Target.calls == [{}]
    assert "Handoff" not in Path(post.__file__).read_text(encoding="utf-8")


def test_publisher_message_is_an_explicit_tool_request():
    """Regression (sandbox demo): a dated body sent as a plain request was classified as a freshness
    question and answered without calling post_comment. OpenMinion skips that classifier only for an
    explicit tool request, so the rendered message must parse as one."""
    from openminion.modules.brain.bootstrap.freshness_classify import _DIRECT_TOOL_VERB_RE

    message = config.load("prompts")["publisher"]["message"].format(repo=SANDBOX, number=7, body=BODY)
    match = _DIRECT_TOOL_VERB_RE.match(message)
    assert match is not None and match.group(1) == "post_comment"
