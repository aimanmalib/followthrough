"""Read-only GitHub client and snapshot builder.

Every request goes through `GitHub._get`, and `GitHub.request` refuses any method other than
GET before a request object is even built. The token comes from the environment variable named
in config (`github.token_env`); it is held in memory only, never written to the cache, the
snapshot, logs or any model prompt. Conditional requests (ETag / If-None-Match) keep repeat
sweeps cheap: a 304 reply is served from the local cache and does not count against the rate limit.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import ROOT, load, t

READ_METHOD = "GET"
SNAPSHOT_SCHEMA = 1
_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
# Compare statuses meaning "the merge commit is already part of the release tag".
_IN_RELEASE = {"behind", "identical"}

Opener = Callable[..., Any]


class GitHubError(Exception):
    """A GitHub call failed in a way the sweep should report."""


class WriteRefused(GitHubError):
    """Something asked the read-only client to send a non-GET request."""


class RateLimited(GitHubError):
    """GitHub said the rate limit is used up."""


def is_maintainer(login: str, association: str, policy: Mapping[str, Any]) -> bool:
    """Maintainer = author_association in the configured set, or login in maintainers_extra."""
    roles = policy["roles"]
    if association in roles["maintainer_associations"]:
        return True
    extra = {name.lower() for name in roles["maintainers_extra"]}
    return login.lower() in extra


class GitHub:
    """GET-only GitHub REST client with an on-disk ETag cache and Link-header paging."""

    def __init__(
        self,
        policy: Mapping[str, Any] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        opener: Opener | None = None,
        root: Path | None = None,
    ) -> None:
        self.policy = policy if policy is not None else load("policy")
        gh = self.policy["github"]
        self.api_base = gh["api_base"].rstrip("/")
        self.per_page = int(gh["per_page"])
        self.timeout = float(gh["timeout_s"])
        self.max_pages = int(gh["max_pages"])
        self.root = root or ROOT
        self.cache_path = self.root / gh["etag_cache"]
        self._token = (env if env is not None else os.environ).get(gh["token_env"], "")
        self._open = opener or urllib.request.urlopen
        self._cache: dict[str, dict[str, Any]] = self._load_cache()
        self.requests: list[tuple[str, str, int]] = []  # (method, path, status) — method log for metrics

    def __repr__(self) -> str:  # never show the token
        return f"GitHub(api_base={self.api_base!r}, token={'set' if self._token else 'unset'})"

    # -- cache -------------------------------------------------------------
    def _load_cache(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._cache), encoding="utf-8")
        os.replace(tmp, self.cache_path)

    # -- transport ---------------------------------------------------------
    def _headers(self, url: str) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"followthrough/{__version__}",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        cached = self._cache.get(url)
        if cached and cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        return headers

    def request(self, method: str, url: str) -> tuple[Any, str | None]:
        """Send one request; only GET is allowed. Returns (json body, next-page url)."""
        if method.upper() != READ_METHOD:
            raise WriteRefused(t("github.write_refused", method=method))
        req = urllib.request.Request(url, headers=self._headers(url), method=READ_METHOD)
        path = urllib.parse.urlsplit(url).path
        try:
            with self._open(req, timeout=self.timeout) as resp:
                status = getattr(resp, "status", 200)
                body = json.loads(resp.read().decode("utf-8") or "null")
                link = resp.headers.get("Link", "")
                etag = resp.headers.get("ETag")
        except urllib.error.HTTPError as err:
            self.requests.append((READ_METHOD, path, err.code))
            if err.code == 304 and url in self._cache:
                cached = self._cache[url]
                return cached["body"], cached.get("next")
            if err.code in (403, 429) and err.headers.get("X-RateLimit-Remaining") == "0":
                raise RateLimited(t("github.rate_limited", reset=err.headers.get("X-RateLimit-Reset", "?"))) from None
            raise GitHubError(t("github.http_error", status=err.code, path=path)) from None
        self.requests.append((READ_METHOD, path, status))
        match = _NEXT_LINK.search(link or "")
        nxt = match.group(1) if match else None
        if etag:
            self._cache[url] = {"etag": etag, "body": body, "next": nxt}
        return body, nxt

    def _get(self, path: str, **params: Any) -> Any:
        url = f"{self.api_base}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self.request(READ_METHOD, url)[0]

    def _get_all(self, path: str, **params: Any) -> list[Any]:
        url: str | None = f"{self.api_base}{path}?{urllib.parse.urlencode({**params, 'per_page': self.per_page})}"
        items: list[Any] = []
        pages = 0
        while url:
            if pages >= self.max_pages:
                raise GitHubError(t("github.too_many_pages", pages=pages, path=path))
            body, url = self.request(READ_METHOD, url)
            items.extend(body or [])
            pages += 1
        return items

    # -- endpoints (PRD §4.5) ---------------------------------------------
    def open_threads(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Open issues and pull requests (the issues endpoint returns both)."""
        return self._get_all(f"/repos/{owner}/{repo}/issues", state="open")

    def comments(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        return self._get_all(f"/repos/{owner}/{repo}/issues/{number}/comments")

    def timeline(self, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        return self._get_all(f"/repos/{owner}/{repo}/issues/{number}/timeline")

    def releases(self, owner: str, repo: str) -> list[dict[str, Any]]:
        return self._get(f"/repos/{owner}/{repo}/releases", per_page=self.per_page) or []

    def pull(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._get(f"/repos/{owner}/{repo}/pulls/{number}") or {}

    def compare_status(self, owner: str, repo: str, base: str, head: str) -> str:
        quoted = f"{urllib.parse.quote(base, safe='')}...{urllib.parse.quote(head, safe='')}"
        return (self._get(f"/repos/{owner}/{repo}/compare/{quoted}") or {}).get("status", "")

    # -- snapshot ----------------------------------------------------------
    def _person(self, user: Mapping[str, Any] | None, association: str) -> dict[str, Any]:
        login = (user or {}).get("login", "")
        return {"login": login, "association": association,
                "maintainer": is_maintainer(login, association, self.policy)}

    def _linked_prs(self, owner: str, repo: str, number: int, release_tag: str | None) -> list[dict[str, Any]]:
        linked: list[dict[str, Any]] = []
        seen: set[int] = set()
        for event in self.timeline(owner, repo, number):
            source = (event.get("source") or {}).get("issue") or {}
            if event.get("event") != "cross-referenced" or "pull_request" not in source:
                continue
            src_repo = (source.get("repository") or {}).get("full_name", f"{owner}/{repo}")
            if src_repo.lower() != f"{owner}/{repo}".lower() or source["number"] in seen:
                continue
            seen.add(source["number"])
            pr = self.pull(owner, repo, source["number"])
            sha = pr.get("merge_commit_sha") if pr.get("merged") else None
            in_release = None
            if sha and release_tag:
                in_release = self.compare_status(owner, repo, release_tag, sha) in _IN_RELEASE
            linked.append({"number": source["number"], "merged": bool(pr.get("merged")),
                           "merge_commit_sha": sha, "in_latest_release": in_release})
        return linked

    def snapshot(self, owner: str, repo: str, now: datetime, numbers: set[int] | None = None) -> dict[str, Any]:
        """Read every open thread (or only `numbers`) into one plain-JSON snapshot."""
        published = [r for r in self.releases(owner, repo) if not r.get("draft") and r.get("published_at")]
        latest = max(published, key=lambda r: r["published_at"], default=None)
        release = {"tag": latest["tag_name"], "published_at": latest["published_at"]} if latest else None
        awaiting = self.policy["labels"]["awaiting_release"]
        threads = []
        for item in self.open_threads(owner, repo):
            if numbers is not None and item["number"] not in numbers:
                continue
            labels = [lab["name"] for lab in item.get("labels", [])]
            comments = [] if not item.get("comments") else self.comments(owner, repo, item["number"])
            threads.append({
                "number": item["number"],
                "title": item.get("title", ""),
                "is_pr": "pull_request" in item,
                "labels": labels,
                "author": self._person(item.get("user"), item.get("author_association", "NONE")),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "body": item.get("body") or "",
                "comments": [{"id": c["id"], "created_at": c["created_at"], "body": c.get("body") or "",
                              "author": self._person(c.get("user"), c.get("author_association", "NONE"))}
                             for c in comments],
                "linked_prs": (self._linked_prs(owner, repo, item["number"], release and release["tag"])
                               if awaiting in labels else []),
            })
        return {"schema": SNAPSHOT_SCHEMA, "repo": f"{owner}/{repo}", "taken_at": iso(now),
                "latest_release": release, "threads": threads}

    def write_snapshot(self, snap: Mapping[str, Any], now: datetime) -> Path:
        owner, repo = snap["repo"].split("/", 1)
        folder = self.root / self.policy["github"]["snapshot_dir"] / f"{owner}__{repo}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now.astimezone(UTC):%Y%m%dT%H%MZ}.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
