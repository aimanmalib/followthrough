"""scripts/build_pages.py: the landing pages and the digest pages carry preview tags, the icon and image; the digest
body is unchanged (ADR 0016, ADR 0017)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_pages", ROOT / "scripts" / "build_pages.py")
assert SPEC and SPEC.loader
build_pages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_pages)

DIGEST_JSON = {"schema": 1, "repo": "o/sandbox", "as_of": "2026-11-20T09:00:00Z", "threads": 6, "guard_rejected": 1, "read_failed": 0,
               "counts": {"FOLLOW_UP_DUE": 2, "TAKEOVER_ALLOWED": 1, "READY_TO_VERIFY": 2, "NO_ACTION": 1}, "items": [{"number": 1}]}
METRICS_JSON = {"schema": 1, "guard": {"checked": 6, "rejected": 1}, "usd": 0.0}
PAGE = ('<!doctype html>\n<html lang="{lang}">\n<head>\n<title>Digest &amp; {lang}</title>\n</head>\n'
        '<body><p>body {lang}</p></body>\n</html>\n')


@pytest.fixture()
def runs(tmp_path: Path) -> Path:
    for lang in ("en", "ms"):
        folder = tmp_path / "runs" / lang / "2026-11-20"
        folder.mkdir(parents=True)
        (folder / "digest.html").write_text(PAGE.format(lang=lang), encoding="utf-8")
        (folder / "digest.json").write_text(json.dumps(DIGEST_JSON), encoding="utf-8")
        (folder / "metrics.json").write_text(json.dumps(METRICS_JSON), encoding="utf-8")
    return tmp_path / "runs"


def test_builds_landing_and_digest_pages_with_assets(runs: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    cfg = build_pages.load("pages")
    written = build_pages.build(runs, site)
    expected = {f"{p}index.html" for p in [*cfg["paths"].values(), *cfg["digest_paths"].values()]}
    assert len(expected) == 4
    summary = next(iter(cfg["digest_paths"].values())) + cfg["landing"]["summary_file"]
    assert sorted(p.relative_to(site).as_posix() for p in written) == sorted(expected | {summary})
    for key in ("image", "icon"):
        assert (site / Path(cfg[key]).name).stat().st_size > 0
    assert (site / ".nojekyll").exists()


def test_summary_needs_the_sweep_json(runs: Path, tmp_path: Path) -> None:
    (next((runs / "en").glob("*")) / "metrics.json").unlink()
    with pytest.raises(FileNotFoundError):
        build_pages.build(runs, tmp_path / "site")


def test_digest_head_has_preview_tags_and_body_is_unchanged(runs: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    build_pages.build(runs, site)
    cfg = build_pages.load("pages")
    for lang, path in cfg["digest_paths"].items():
        html = (site / path / "index.html").read_text(encoding="utf-8")
        head, body = html.split("</head>", 1)
        for needle in ('name="description"', 'property="og:title" content="Digest &amp; ' + lang,
                       'property="og:image" content="' + cfg["site_url"], 'name="twitter:card"', 'rel="icon"',
                       f'rel="canonical" href="{cfg["site_url"]}{path}"',
                       *(f'hreflang="{code}" href="{cfg["site_url"]}{p}"' for code, p in cfg["digest_paths"].items())):
            assert needle in head
        assert body == PAGE.format(lang=lang).split("</head>", 1)[1]


def test_landing_head_points_at_landing_paths(runs: Path, tmp_path: Path) -> None:
    site = tmp_path / "site"
    build_pages.build(runs, site)
    cfg = build_pages.load("pages")
    for lang, path in cfg["paths"].items():
        head = (site / path / "index.html").read_text(encoding="utf-8").split("</head>", 1)[0]
        assert head.count("</title>") == 1 and head.count('name="description"') == 1
        assert f'rel="canonical" href="{cfg["site_url"]}{path}"' in head
        for code, p in cfg["paths"].items():
            assert f'hreflang="{code}" href="{cfg["site_url"]}{p}"' in head


def test_text_is_escaped(runs: Path) -> None:
    cfg = build_pages.load("pages")
    tags = build_pages.head_tags({**cfg, "site_url": 'https://x.test/"><script>/'}, "en", "t")
    assert "<script>" not in tags


def test_page_without_head_fails_loudly() -> None:
    with pytest.raises(ValueError):
        build_pages.with_tags("<html><body>no head</body></html>", "<meta>")


def test_missing_run_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_pages.build(tmp_path / "nothing", tmp_path / "site")
