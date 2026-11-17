"""Read-only GitHub client: no network, `urlopen` is replaced by a recording fake."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path

import pytest

from followthrough import config, github
from followthrough.github import GitHub, GitHubError, RateLimited, WriteRefused

API = "https://api.github.com"
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sandbox-repo.json"


def _headers(values: dict[str, str] | None = None) -> Message:
    msg = Message()
    for key, val in (values or {}).items():
        msg[key] = val
    return msg


class _Resp:
    def __init__(self, body, headers=None, status=200):
        self._raw = json.dumps(body).encode()
        self.headers = _headers(headers)
        self.status = status

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Maps URL -> list of replies (a _Resp, or an int HTTP error code). Records every Request."""

    def __init__(self, routes):
        self.routes = {url: list(replies) for url, replies in routes.items()}
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append(req)
        replies = self.routes.get(req.full_url)
        if not replies:
            raise AssertionError(f"unexpected URL {req.full_url}")
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, tuple):
            code, hdrs = reply
            raise urllib.error.HTTPError(req.full_url, code, "err", _headers(hdrs), io.BytesIO(b""))
        return reply


@pytest.fixture
def policy():
    return config.load("policy")


def client(policy, tmp_path, routes, token="tok-test-123"):
    opener = FakeOpener(routes)
    env = {policy["github"]["token_env"]: token} if token else {}
    return GitHub(policy, env=env, opener=opener, root=tmp_path), opener


@pytest.mark.parametrize("method", ["POST", "patch", "PUT", "DELETE", "HEAD"])
def test_non_get_methods_are_refused_before_any_network(policy, tmp_path, method):
    gh, opener = client(policy, tmp_path, {})
    with pytest.raises(WriteRefused):
        gh.request(method, f"{API}/repos/o/r/issues/1/comments")
    assert opener.calls == []
    assert gh.requests == []


def test_token_comes_from_env_and_is_never_shown(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    gh, opener = client(policy, tmp_path, {url: [_Resp([], {"ETag": '"a"'})]})
    gh.releases("o", "r")
    gh.save_cache()
    assert opener.calls[0].get_header("Authorization") == "Bearer tok-test-123"
    assert "tok-test-123" not in repr(gh)
    assert "tok-test-123" not in gh.cache_path.read_text()


def test_no_token_means_no_auth_header(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    gh, opener = client(policy, tmp_path, {url: [_Resp([])]}, token="")
    gh.releases("o", "r")
    assert opener.calls[0].get_header("Authorization") is None


def test_every_request_is_get(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    gh, opener = client(policy, tmp_path, {url: [_Resp([])]})
    gh.releases("o", "r")
    assert [req.get_method() for req in opener.calls] == ["GET"]
    assert gh.requests == [("GET", "/repos/o/r/releases", 200)]


def test_etag_is_sent_and_304_is_served_from_cache(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    body = [{"tag_name": "v1", "published_at": "2026-11-01T00:00:00Z"}]
    gh, opener = client(policy, tmp_path, {url: [_Resp(body, {"ETag": '"v1"'}), (304, {})]})
    assert gh.releases("o", "r") == body
    gh.save_cache()
    # a fresh client reads the cache from disk and sends If-None-Match
    gh2 = GitHub(policy, env={}, opener=opener, root=tmp_path)
    assert gh2.releases("o", "r") == body
    assert opener.calls[0].get_header("If-none-match") is None
    assert opener.calls[1].get_header("If-none-match") == '"v1"'
    assert gh2.requests == [("GET", "/repos/o/r/releases", 304)]


def test_paging_follows_link_next(policy, tmp_path):
    per = policy["github"]["per_page"]
    first = f"{API}/repos/o/r/issues?state=open&per_page={per}"
    second = f"{API}/repositories/1/issues?state=open&per_page={per}&page=2"
    routes = {
        first: [_Resp([{"number": 1}], {"Link": f'<{second}>; rel="next", <{second}>; rel="last"'})],
        second: [_Resp([{"number": 2}], {"Link": f'<{first}>; rel="prev"'})],
    }
    gh, _ = client(policy, tmp_path, routes)
    assert [i["number"] for i in gh.open_threads("o", "r")] == [1, 2]


def test_paging_has_a_hard_stop(policy, tmp_path):
    per = policy["github"]["per_page"]
    url = f"{API}/repos/o/r/issues?state=open&per_page={per}"
    gh, _ = client(policy, tmp_path, {url: [_Resp([{"number": 1}], {"Link": f'<{url}>; rel="next"'})]})
    with pytest.raises(GitHubError):
        gh.open_threads("o", "r")
    assert len(gh.requests) == policy["github"]["max_pages"]


def test_rate_limit_is_reported(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    gh, _ = client(policy, tmp_path, {url: [(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1763600000"})]})
    with pytest.raises(RateLimited):
        gh.releases("o", "r")


def test_other_http_errors_raise(policy, tmp_path):
    url = f"{API}/repos/o/r/releases?per_page={policy['github']['per_page']}"
    gh, _ = client(policy, tmp_path, {url: [(404, {})]})
    with pytest.raises(GitHubError) as err:
        gh.releases("o", "r")
    assert not isinstance(err.value, RateLimited)


def test_maintainer_by_association_or_extra_list(policy):
    roles = dict(policy["roles"], maintainers_extra=["Hidden-Member"])
    pol = dict(policy, roles=roles)
    for assoc in policy["roles"]["maintainer_associations"]:
        assert github.is_maintainer("x", assoc, pol)
    assert not github.is_maintainer("x", "CONTRIBUTOR", pol)
    assert github.is_maintainer("hidden-member", "CONTRIBUTOR", pol)


def _snapshot_routes(per):
    base = f"{API}/repos/o/r"
    issues = [
        {"number": 5, "title": "Bug", "labels": [{"name": "status:awaiting-release"}], "comments": 1,
         "user": {"login": "ana"}, "author_association": "MEMBER", "body": "b",
         "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-02T00:00:00Z"},
        {"number": 6, "title": "PR", "labels": [], "comments": 0, "pull_request": {},
         "user": {"login": "kai"}, "author_association": "CONTRIBUTOR", "body": None,
         "created_at": "2026-11-03T00:00:00Z", "updated_at": "2026-11-03T00:00:00Z"},
    ]
    timeline = [
        {"event": "labeled"},
        {"event": "cross-referenced", "source": {"issue": {"number": 9, "pull_request": {},
                                                            "repository": {"full_name": "o/r"}}}},
        {"event": "cross-referenced", "source": {"issue": {"number": 77, "pull_request": {},
                                                            "repository": {"full_name": "fork/r"}}}},
    ]
    return {
        f"{base}/releases?per_page={per}": [_Resp([
            {"tag_name": "v0.1", "published_at": "2026-10-01T00:00:00Z"},
            {"tag_name": "v0.2", "published_at": "2026-11-10T00:00:00Z"},
            {"tag_name": "v0.3-draft", "published_at": None, "draft": True}])],
        f"{base}/issues?state=open&per_page={per}": [_Resp(issues)],
        f"{base}/issues/5/comments?per_page={per}": [_Resp([
            {"id": 1, "user": {"login": "kai"}, "author_association": "CONTRIBUTOR",
             "created_at": "2026-11-02T00:00:00Z", "body": "thanks"}])],
        f"{base}/issues/5/timeline?per_page={per}": [_Resp(timeline)],
        f"{base}/pulls/9": [_Resp({"merged": True, "merge_commit_sha": "abc123"})],
        f"{base}/compare/v0.2...abc123": [_Resp({"status": "behind"})],
    }


def test_snapshot_shape_linked_pr_and_file(policy, tmp_path):
    gh, opener = client(policy, tmp_path, _snapshot_routes(policy["github"]["per_page"]))
    snap = gh.snapshot("o", "r", NOW)
    assert snap["latest_release"] == {"tag": "v0.2", "published_at": "2026-11-10T00:00:00Z"}
    bug, pr = snap["threads"]
    assert bug["author"] == {"login": "ana", "association": "MEMBER", "maintainer": True}
    assert bug["comments"][0]["author"]["maintainer"] is False
    assert bug["linked_prs"] == [{"number": 9, "merged": True, "merge_commit_sha": "abc123", "in_latest_release": True}]
    assert pr["is_pr"] is True and pr["comments"] == [] and pr["body"] == ""
    assert all(req.get_method() == "GET" for req in opener.calls)
    path = gh.write_snapshot(snap, NOW)
    assert path.relative_to(tmp_path).as_posix() == f"{policy['github']['snapshot_dir']}/o__r/20261120T0900Z.json"
    assert json.loads(path.read_text())["repo"] == "o/r"


def test_compare_ahead_means_not_released(policy, tmp_path):
    routes = _snapshot_routes(policy["github"]["per_page"])
    routes[f"{API}/repos/o/r/compare/v0.2...abc123"] = [_Resp({"status": "ahead"})]
    gh, _ = client(policy, tmp_path, routes)
    snap = gh.snapshot("o", "r", NOW, numbers={5})
    assert [t["number"] for t in snap["threads"]] == [5]
    assert snap["threads"][0]["linked_prs"][0]["in_latest_release"] is False


def test_fixture_is_synthetic_and_covers_every_action():
    fx = json.loads(FIXTURE.read_text())
    meta = fx["fixture"]
    assert meta["synthetic"] is True
    assert set(meta["expected"].values()) == {
        "FOLLOW_UP_DUE", "TAKEOVER_ALLOWED", "MAINTAINER_REPLY_PENDING", "READY_TO_VERIFY", "NO_ACTION"}
    assert list(meta["expected"].values()).count("FOLLOW_UP_DUE") == 2
    numbers = {str(t["number"]) for t in fx["threads"]}
    assert numbers == set(meta["expected"])
    # same shape as a live snapshot
    for thread in fx["threads"]:
        assert set(thread) == {"number", "title", "is_pr", "labels", "author", "created_at", "updated_at",
                               "body", "comments", "linked_prs"}
    # exactly one fake quote, and it is not a substring of any text in its thread
    fake = meta["fake_quote"]
    thread = next(t for t in fx["threads"] if t["number"] == fake["number"])
    texts = [thread["body"]] + [c["body"] for c in thread["comments"]]
    assert not any(fake["quote"] in text for text in texts)
