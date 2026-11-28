"""The landing page of the public demo site (ADR 0017): built from locale text and config only, styled only through
the generated tokens, and every local link resolves in the built site."""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = ROOT / "docs" / "site"


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_pages = _module("build_pages")
build_landing = build_pages.build_landing
DIGEST_JSON = {"schema": 1, "repo": "o/sandbox", "as_of": "2026-11-20T09:00:00Z", "threads": 6, "guard_rejected": 1, "read_failed": 0,
               "counts": {"FOLLOW_UP_DUE": 2, "TAKEOVER_ALLOWED": 1, "READY_TO_VERIFY": 2, "NO_ACTION": 1}, "items": [{"number": 1}]}
METRICS_JSON = {"schema": 1, "guard": {"checked": 6, "rejected": 1}, "usd": 0.0}
PAGE = '<!doctype html>\n<html lang="{lang}">\n<head>\n<title>Digest {lang}</title>\n</head>\n<body><p>{lang}</p></body>\n</html>\n'


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        found = dict(attrs)
        self.tags.append((tag, found))
        for key in ("href", "src"):
            if found.get(key):
                self.refs.append(found[key])


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("pages")
    for lang in ("en", "ms"):
        folder = base / "runs" / lang / "2026-11-20"
        folder.mkdir(parents=True)
        (folder / "digest.html").write_text(PAGE.format(lang=lang), encoding="utf-8")
        (folder / "digest.json").write_text(json.dumps(DIGEST_JSON), encoding="utf-8")
        (folder / "metrics.json").write_text(json.dumps(METRICS_JSON), encoding="utf-8")
    build_pages.build(base / "runs", base / "site")
    return base / "site"


def _cfg() -> dict:
    return build_pages.load("pages")


# --- renderer -------------------------------------------------------------------------------------------------------

def test_render_fills_text_context_lists_and_conditions() -> None:
    template = '<p>{{a}}</p><b>{{@x.y}}</b><!--if @x.z-->Z<!--/if--><!--if @x.none-->N<!--/if--><!--each items--><i>{{.v}}</i><!--/each-->'
    out = build_landing.render(template, {"a": "<A>", "items": [{"v": "1"}, {"v": "&"}]},
                               {"x": {"y": "Y", "z": "on", "none": ""}})
    assert out == "<p>&lt;A&gt;</p><b>Y</b>Z<i>1</i><i>&amp;</i>"


@pytest.mark.parametrize("template", ["{{missing}}", "{{@nope.x}}", "<!--each missing-->x<!--/each-->", "<!--if @a-->"])
def test_render_fails_loudly(template: str) -> None:
    with pytest.raises(build_landing.TemplateError):
        build_landing.render(template, {}, {"a": "1"})


@pytest.mark.parametrize(("page", "target", "expected"), [
    ("", "", "./"), ("", "digest/", "digest/"), ("ms/", "digest/", "../digest/"), ("ms/", "ms/digest/", "digest/"),
    ("ms/", "", "../"), ("", "ms/", "ms/"), ("", "assets/", "assets/"), ("ms/", "assets/", "../assets/"),
])
def test_relative_links(page: str, target: str, expected: str) -> None:
    assert build_landing.relative(page, target) == expected


def test_inline_logo_is_decorative_and_sized() -> None:
    svg = build_landing.inline_logo((ROOT / _cfg()["landing"]["logo"]).read_text(encoding="utf-8"), 36)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert 'aria-hidden="true"' in svg and "<title" not in svg and "aria-labelledby" not in svg
    assert svg.split(">", 1)[0].count('width="36"') == 1
    assert len(svg.encode()) <= 2048


# --- the built pages ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lang", ["en", "ms"])
def test_landing_page_language_tokens_first_and_local_links_resolve(site: Path, lang: str) -> None:
    cfg = _cfg()
    path = cfg["paths"][lang]
    html = (site / path / "index.html").read_text(encoding="utf-8")
    assert f'<html lang="{lang}">' in html
    assert html.index("token.css") < html.index("landing.css")
    parser = _Links()
    parser.feed(html)
    base = "https://site.test/" + path
    for ref in parser.refs:
        if ref.startswith(("http://", "https://", "#")):
            continue
        local = urljoin(base, ref).removeprefix("https://site.test/")
        target = site / local
        assert (target / "index.html" if local.endswith("/") or not local else target).exists(), ref
    assert sum(1 for tag, _ in parser.tags if tag == "svg") >= 1  # the inline brand mark
    imgs = [a for tag, a in parser.tags if tag == "img"]
    assert all(a.get("width") and a.get("height") and "alt" in a for a in imgs)


def test_every_landing_text_comes_from_the_locale(site: Path) -> None:
    for lang, path in _cfg()["paths"].items():
        html = (site / path / "index.html").read_text(encoding="utf-8")
        text = tomllib.loads((ROOT / "locales" / f"{lang}.toml").read_text(encoding="utf-8"))["landing"]
        for key in ("hero_title", "hero_lede", "cta_primary", "cta_secondary", "footer_note"):
            assert build_landing.escape(text[key]) in html, key


def test_template_holds_no_copy() -> None:
    template = (SITE_SRC / _cfg()["landing"]["template"]).read_text(encoding="utf-8")
    body = template.split("<body>", 1)[1]
    visible = re.sub(r"<script.*?</script>|<!--.*?-->|<[^>]+>|\{\{[^}]+\}\}", " ", body, flags=re.S)
    assert set(visible.split()) <= {"Follow-Through"}


def test_landing_assets_are_copied(site: Path) -> None:
    land = _cfg()["landing"]
    out = site / land["assets_out"]
    for name in land["copy"]:
        assert (out / name).exists(), name
    fonts = sorted(p.name for p in (out / "fonts").iterdir())
    assert len([f for f in fonts if f.endswith(".woff2")]) >= 2 and "OFL.txt" in fonts
    for frame in land["shots"].values():
        for scheme in ("light", "dark"):
            if frame.get(scheme):
                assert (out / frame[scheme]).stat().st_size <= 80 * 1024


# --- styles ---------------------------------------------------------------------------------------------------------

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(rgba?|hsla?|oklch|oklab|lab|lch)\(|(?<![\w-])(white|black|red|blue|green|gray|grey)(?![\w-])")


@pytest.mark.parametrize("css", sorted(p.name for p in SITE_SRC.glob("*.css") if p.name != "token.css"))
def test_page_styles_use_only_tokens(css: str) -> None:
    text = re.sub(r"/\*.*?\*/", "", (SITE_SRC / css).read_text(encoding="utf-8"), flags=re.S)
    assert not COLOUR.search(text), COLOUR.search(text)


def test_one_column_hero_shows_the_product_before_the_lede() -> None:
    """On phones the frames sit right after the headline and actions, so the real digest is on the first screen."""
    css = re.sub(r"/\*.*?\*/", "", (SITE_SRC / "landing.css").read_text(encoding="utf-8"), flags=re.S)
    block = re.search(r"@media \(max-width: 959px\) \{(.*?)\n\}", css, flags=re.S)
    assert block, "no one-column hero rule"
    rules = block.group(1)
    assert re.search(r"\.hero-text \{ display: contents; \}", rules)
    order = {name: int(re.search(rf"\.hero \.{name} \{{ order: (\d+);", rules).group(1)) for name in ("actions", "stage", "lede", "note")}
    assert order["actions"] < order["stage"] < order["lede"] < order["note"], order


def test_no_blur_glass_or_shouting_labels() -> None:
    for path in SITE_SRC.glob("*.*"):
        if path.suffix not in {".css", ".html", ".js"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert "backdrop-filter" not in text and not re.search(r"filter:\s*blur", text), path.name
        assert "text-transform: uppercase" not in text and "uppercase" not in text, path.name
        assert "fonts.googleapis" not in text and "cdn." not in text, path.name


def test_landing_locale_keys_match() -> None:
    keys = [set(tomllib.loads((ROOT / "locales" / f"{lang}.toml").read_text(encoding="utf-8"))["landing"]) for lang in ("en", "ms")]
    assert keys[0] == keys[1]


# --- sections, proof panel, FAQ, demo (R2) ----------------------------------------------------------------------------

def _landing(site: Path, lang: str) -> tuple[str, _Links]:
    html = (site / _cfg()["paths"][lang] / "index.html").read_text(encoding="utf-8")
    parser = _Links()
    parser.feed(html)
    return html, parser


@pytest.mark.parametrize("lang", ["en", "ms"])
def test_landing_has_six_headed_sections_and_every_anchor_lands(site: Path, lang: str) -> None:
    html, parser = _landing(site, lang)
    assert sum(1 for tag, _ in parser.tags if tag == "h2") >= 6
    assert sum(1 for tag, _ in parser.tags if tag == "section") >= 6
    ids = {a["id"] for _, a in parser.tags if a.get("id")}
    anchors = {ref[1:] for ref in parser.refs if ref.startswith("#")}
    assert {"how", "proof", "faq", "demo"} <= anchors <= ids


@pytest.mark.parametrize("lang", ["en", "ms"])
def test_faq_and_lists_come_from_the_locale_in_both_languages(site: Path, lang: str) -> None:
    html, parser = _landing(site, lang)
    text = build_landing.locale(lang)
    assert len(text["faq"]) >= 5
    assert sum(1 for tag, _ in parser.tags if tag == "details") == len(text["faq"])
    for key, fields in (("faq", ("q", "a")), ("how_steps", ("title", "text")), ("proof_measured", ("lead", "text")),
                        ("problem_rules", ("rule", "action"))):
        for item in text[key]:
            for field in fields:
                assert build_landing.escape(item[field]) in html, (key, field)


def test_locale_lists_have_the_same_length_in_both_languages() -> None:
    en, ms = build_landing.locale("en"), build_landing.locale("ms")
    for key, value in en.items():
        if isinstance(value, list):
            assert len(value) == len(ms[key]), key
            assert [sorted(item) for item in value] == [sorted(item) for item in ms[key]], key
    known = set(_cfg()["landing"]["actions"])
    assert {rule["code"] for rule in en["problem_rules"]} <= known


@pytest.mark.parametrize("lang", ["en", "ms"])
def test_proof_panel_loads_the_published_summary(site: Path, lang: str) -> None:
    cfg = _cfg()
    _, parser = _landing(site, lang)
    slots = [a["data-hidup"] for _, a in parser.tags if "data-hidup" in a]
    assert len(slots) == 1
    local = urljoin("https://site.test/" + cfg["paths"][lang], slots[0]).removeprefix("https://site.test/")
    data = json.loads((site / local).read_text(encoding="utf-8"))
    codes = [a["data-code"] for tag, a in parser.tags if tag == "span" and "data-code" in a and a.get("class") is None]
    assert codes == cfg["landing"]["actions"] == [row["code"] for row in data["actions"]]
    states = {a["data-keadaan"] for _, a in parser.tags if "data-keadaan" in a}
    assert states == {"muat", "ada", "kosong", "ralat"}


def test_summary_holds_the_digest_counts_in_config_order_and_no_thread_text() -> None:
    order = _cfg()["landing"]["actions"]
    data = build_landing.summary(DIGEST_JSON, METRICS_JSON, order)
    assert [row["code"] for row in data["actions"]] == order
    assert {row["code"]: row["count"] for row in data["actions"] if row["count"]} == DIGEST_JSON["counts"]
    assert sum(row["count"] for row in data["actions"]) == DIGEST_JSON["threads"]
    assert (data["checked"], data["rejected"], data["read_failed"], data["usd"]) == (6, 1, 0, "0.00")
    assert data["date"] == "2026-11-20" and "items" not in data


def test_demo_section_links_and_video_only_when_set(site: Path) -> None:
    cfg = _cfg()["landing"]
    html, parser = _landing(site, "en")
    hrefs = set(parser.refs)
    assert cfg["demo_url"] in hrefs and cfg["demo_guide_url"] in hrefs and cfg["results_url"] in hrefs
    assert bool("<video" in html or (cfg["video_url"] and cfg["video_url"] in hrefs)) == bool(cfg["video_url"])
    assert build_landing.escape(build_landing.locale("en")["demo_command"]) in html
