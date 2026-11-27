"""The committed screenshots and social card match config/pages.toml (made by scripts/shots.py, a host tool that is not
run here): every hero frame has a light and a dark WebP of the configured size within budget, the card is a PNG of
image_width x image_height within budget, and the card template renders from the locale with no markers left."""

from __future__ import annotations

import importlib.util
import re
import struct
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _cfg() -> dict:
    with open(ROOT / "config" / "pages.toml", "rb") as fh:
        return tomllib.load(fh)


def _build_landing():
    spec = importlib.util.spec_from_file_location("build_landing", ROOT / "scripts" / "build_landing.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def webp_size(data: bytes) -> tuple[int, int]:
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", "not a WebP file"
    chunk = data[12:16]
    if chunk == b"VP8 ":
        assert data[23:26] == b"\x9d\x01\x2a"
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    raise AssertionError(f"unknown WebP chunk {chunk!r}")


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR", "not a PNG file"
    return struct.unpack(">II", data[16:24])


FRAMES = sorted(_cfg()["landing"]["shots"].items())


@pytest.mark.parametrize("name,frame", FRAMES, ids=[name for name, _ in FRAMES])
def test_each_frame_has_light_and_dark_screenshots_of_the_configured_size(name: str, frame: dict) -> None:
    cfg = _cfg()
    budget = cfg["shots"]["max_kb"] * 1024
    for scheme in ("light", "dark"):
        data = (ROOT / cfg["landing"]["source_dir"] / frame[scheme]).read_bytes()
        assert webp_size(data) == (frame["width"], frame["height"]), (name, scheme)
        assert len(data) <= budget, (name, scheme, len(data))
    assert name in cfg["shots"], f"no capture settings for {name}"


def test_social_card_is_a_png_of_the_card_size_within_budget() -> None:
    cfg = _cfg()
    data = (ROOT / cfg["image"]).read_bytes()
    assert png_size(data) == (cfg["image_width"], cfg["image_height"]) == (1200, 630)
    assert len(data) <= cfg["shots"]["og"]["max_kb"] * 1024


def test_card_template_renders_from_the_locale() -> None:
    cfg, build_landing = _cfg(), _build_landing()
    land, og = cfg["landing"], cfg["shots"]["og"]
    template = (ROOT / land["source_dir"] / og["template"]).read_text(encoding="utf-8")
    assert template.count("<!--logo-->") == 1
    ctx = {"browser": land["shots"]["browser"], "phone": land["shots"]["phone"], "host": "example.test"}
    text = build_landing.locale(cfg["shots"]["lang"], ROOT)
    html = build_landing.render(template, text, ctx)
    assert text["hero_title"] in html.replace("&#x27;", "'")
    for frame in land["shots"].values():
        assert frame["light"] in html
    assert not re.search(r"backdrop-filter|filter:\s*blur", html)
    assert og["template"] not in land["copy"], "the card page is not published"


def test_hero_screenshots_load_eagerly_with_alt_text_in_both_schemes() -> None:
    cfg = _cfg()
    template = (ROOT / cfg["landing"]["source_dir"] / cfg["landing"]["template"]).read_text(encoding="utf-8")
    hero = template.split('<div class="stage">', 1)[1].split("</section>", 1)[0]
    images = re.findall(r"<img [^>]*>", hero)
    assert len(images) == 4
    for tag in images:
        assert 'loading="lazy"' not in tag
        assert re.search(r'alt="\{\{alt_(browser|phone)\}\}"', tag), tag
