"""`followthrough post`: the stdin approver and the exit codes. `post.publish` itself is covered in
test_post.py (real OpenMinion runtime, fake model and GitHub); here it is replaced by a recorder."""

from __future__ import annotations

import io

import pytest

from followthrough import approve, cli, post

SANDBOX = "aimanmalib/followthrough-sandbox"
BODY = "Follow-up due 2026-11-26; take-over allowed from 2026-11-29."


@pytest.mark.parametrize("typed, expected", [
    ("allow_once\n", post.ALLOW_ONCE),
    ("  allow_once  \n", post.ALLOW_ONCE),
    ("deny\n", post.DENY),
    ("yes\n", post.DENY),
    ("ALLOW_ONCE\n", post.DENY),
    ("", post.DENY),  # end of input
])
def test_only_exact_allow_once_allows(typed, expected):
    shown = io.StringIO()
    answer = approve.stdin_approver("en", io.StringIO(typed), shown)(SANDBOX, 7, BODY)
    assert answer == expected
    assert BODY in shown.getvalue() and f"{SANDBOX}#7" in shown.getvalue()


def test_prompt_is_translated():
    shown = io.StringIO()
    approve.stdin_approver("ms", io.StringIO("deny\n"), shown)(SANDBOX, 7, BODY)
    assert "Taip allow_once" in shown.getvalue()


class Recorder:
    def __init__(self, result=None, stop=None):
        self.calls, self.result, self.stop = [], result, stop

    def __call__(self, repo, number, body, *, approver, **_kw):
        self.calls.append((repo, number, body, approver))
        if self.stop is not None:
            raise post.Stopped(self.stop)
        return self.result


@pytest.fixture
def draft(tmp_path):
    path = tmp_path / "7.md"
    path.write_text(BODY + "\n\n", encoding="utf-8")
    return path


def test_posts_the_exact_draft_text(tmp_path, draft, capsys):
    rec = Recorder(post.PostResult(SANDBOX, 7, "posted", url="https://example.test/c/1", http_posts=1))
    assert approve.run(SANDBOX, 7, draft, "en", tmp_path, approver=lambda *a: post.ALLOW_ONCE, publish=rec) == 0
    assert rec.calls[0][:3] == (SANDBOX, 7, BODY)
    assert "https://example.test/c/1" in capsys.readouterr().out


def test_denied_is_a_normal_outcome(tmp_path, draft, capsys):
    rec = Recorder(post.PostResult(SANDBOX, 7, "denied"))
    assert approve.run(SANDBOX, 7, draft, "en", tmp_path, approver=lambda *a: post.DENY, publish=rec) == 0
    assert "Denied" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["refused_repo", "not_posted", "error"])
def test_anything_else_fails(tmp_path, draft, status):
    rec = Recorder(post.PostResult(SANDBOX, 7, status))
    assert approve.run(SANDBOX, 7, draft, "en", tmp_path, approver=lambda *a: post.DENY, publish=rec) == 1


def test_stop_file_exit_code_is_passed_through(tmp_path, draft):
    rec = Recorder(stop=5)
    assert approve.run(SANDBOX, 7, draft, "en", tmp_path, approver=lambda *a: post.ALLOW_ONCE, publish=rec) == 5


def test_empty_draft_posts_nothing(tmp_path):
    empty = tmp_path / "7.md"
    empty.write_text("  \n", encoding="utf-8")
    rec = Recorder()
    assert approve.run(SANDBOX, 7, empty, "en", tmp_path, publish=rec) == 2
    assert rec.calls == []


def test_stop_file_through_the_cli_before_any_model_or_http(tmp_path, draft, monkeypatch):
    marker = tmp_path / "stop"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setenv("PERANAN_HENTI", str(marker))
    monkeypatch.delenv("PERANAN_KELUAR_PY", raising=False)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    called = []
    monkeypatch.setattr(post.CommentPoster, "post", lambda *a: called.append(a))
    assert cli.main(["post", "--repo", SANDBOX, "--number", "7", "--draft", str(draft)]) == 5
    assert called == []


def test_cli_rejects_a_bad_repo(draft):
    assert cli.main(["post", "--repo", "nope", "--number", "7", "--draft", str(draft)]) == cli.EXIT_USAGE
