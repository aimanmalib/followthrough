"""The landing page of the public demo site (ADR 0017): built from locale text and config only, styled only through
the generated tokens, and every local link resolves in the built site."""

from __future__ import annotations

import importlib.util
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
