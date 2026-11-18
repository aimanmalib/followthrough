"""digest.html: one self-contained page per language, built from the digest and metrics only."""

from __future__ import annotations

import copy
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from followthrough import cli, config, page
from followthrough.rules import ACTIONS
from test_digest import LIST, SNAPSHOT, _digest, _texts

ROOT = Path(__file__).resolve().parents[1]
METRICS = {"seconds": 1.5, "usd": 0.0042, "http": {"requests": 12, "non_get": 0},
           "guard": {"checked": 6, "rejected": 1}}


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attrs, self.text, self.ids = [], [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend(attrs)
        self.ids.extend(v for k, v in attrs if k == "id")

    def handle_data(self, data):
        self.text.append(data)


def _parse(html: str) -> _Collect:
    parser = _Collect()
    parser.feed(html)
    return parser


@pytest.mark.parametrize("lang", ["en", "ms"])
def test_page_is_in_the_chosen_language(lang):
    html = page.render(_digest(), METRICS, lang, LIST)
    assert f'<html lang="{lang}">' in html
    for key in ("page.kicker", "page.tally_heading", "page.privacy_note"):
        assert config.t(key, lang) in html
    for action in ACTIONS:
        assert config.t(f"actions.{action}", lang) in html


def test_page_lists_every_listed_thread_and_every_count():
    built = _digest()
    html = page.render(built, METRICS, "en", LIST)
    for item in built["items"]:
        assert (f"#{item['number']}" in html) == (item["action"] in LIST)
    tally = re.findall(r'tally-item tone-(\w+)[^"]*"><span class="count">(\d+)<', html)
    assert {a: int(n) for a, n in tally} == built["counts"]


def test_page_is_self_contained_with_unique_ids():
    parsed = _parse(page.render(_digest(), METRICS, "en", LIST))
    assert "script" not in parsed.tags and "img" not in parsed.tags and "link" not in parsed.tags
    assert not [v for k, v in parsed.attrs if k in ("href", "src")]
    assert len(parsed.ids) == len(set(parsed.ids))


def test_page_carries_no_thread_text():
    html = page.render(_digest(), METRICS, "en", LIST)
    for text in _texts(SNAPSHOT):
        for chunk in (text[i:i + 40] for i in range(0, max(len(text) - 40, 1), 40)):
            if len(chunk.strip()) >= 20:
                assert chunk not in html


def test_digest_values_are_escaped():
    built = copy.deepcopy(_digest())
    built["repo"] = 'evil/<script>alert(1)</script>'
    built["stopped"] = '<b>limit</b> & "more"'
    html = page.render(built, METRICS, "en", LIST)
    assert "<script>" not in html and "<b>" not in html
    assert "&lt;script&gt;" in html and "&lt;b&gt;limit&lt;/b&gt; &amp;" in html


def test_partial_banner_and_metrics_variants():
    html = page.render(_digest(stopped="time limit"), None, "en", LIST)
    assert 'class="partial"' in html and "time limit" in html
    assert 'class="metrics"' not in html
    offline = page.render(_digest(), {**METRICS, "http": None}, "ms", LIST)
    assert config.t("page.v_http_none", "ms") in offline
    live = page.render(_digest(), METRICS, "en", LIST)
    assert config.t("page.v_http", "en", requests=12, non_get=0) in live
    assert "USD 0.0042" in live and config.t("page.v_guard", "en", rejected=1, checked=6) in live


def test_nothing_listed_message_when_no_listed_action():
    html = page.render(_digest(), METRICS, "en", [])
    assert config.t("page.nothing_listed", "en") in html


def test_colours_live_only_in_the_css_tokens():
    css = (page.TEMPLATES / "digest.css").read_text(encoding="utf-8")
    outside_tokens = re.sub(r":root\s*\{[^}]*\}", "", css)
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", css), "the token blocks define the colours"
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", outside_tokens)
    assert "backdrop-filter" not in css and "@keyframes" not in css


def test_sweep_writes_digest_html_in_the_lang(tmp_path, capsys):
    rc = cli.main(["sweep", "--fixture", "--out", str(tmp_path), "--lang", "ms"])
    assert rc == cli.EXIT_OK
    folder = next(tmp_path.iterdir())
    html = (folder / config.load("policy")["digest"]["html_file"]).read_text(encoding="utf-8")
    built = json.loads((folder / "digest.json").read_text(encoding="utf-8"))
    assert '<html lang="ms">' in html and built["repo"] in html
    capsys.readouterr()
