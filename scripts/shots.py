"""Take the landing page's real screenshots and the social card from a built site (ADR 0017).

Host tool, not a project dependency: needs Playwright (WebKit) and Pillow.
    python3 scripts/shots.py SITE_DIR
SITE_DIR is the output of scripts/build_pages.py. The script serves it over http on 127.0.0.1, photographs the
English fixture digest in the light and dark schemes for every hero frame in config/pages.toml [landing.shots]
(capture settings in [shots]), writes WebP files under [landing] source_dir no larger than [shots] max_kb, then
renders the card template ([shots.og]) at image_width x image_height and writes the PNG named by `image`.
"""

from __future__ import annotations

import functools
import io
import sys
import threading
import tomllib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_landing

SCHEMES = ("light", "dark")
SETTLE_JS = "Promise.all([document.fonts.ready, ...[...document.images].map(i => i.decode().catch(() => 0))])"


def load_config(root: Path = ROOT) -> dict[str, Any]:
    with open(root / "config" / "pages.toml", "rb") as fh:
        return tomllib.load(fh)


def webp(png: bytes, size: tuple[int, int], quality: int, max_kb: int) -> bytes:
    """Resize to `size` and encode as WebP, lowering the quality in steps until the file fits in `max_kb`."""
    image = Image.open(io.BytesIO(png)).convert("RGB").resize(size, Image.Resampling.LANCZOS)
    for q in range(quality, 39, -6):
        buf = io.BytesIO()
        image.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= max_kb * 1024:
            return buf.getvalue()
    raise SystemExit(f"cannot fit a {size[0]}x{size[1]} WebP in {max_kb} KB")


def small_png(png: bytes, max_kb: int) -> bytes:
    """Keep the PNG when it fits in `max_kb`; otherwise quantize to a smaller palette until it does."""
    if len(png) <= max_kb * 1024:
        return png
    image = Image.open(io.BytesIO(png)).convert("RGB")
    for colours in (256, 192, 128, 64):
        buf = io.BytesIO()
        image.quantize(colors=colours, method=Image.Quantize.MEDIANCUT).save(buf, "PNG", optimize=True)
        if buf.tell() <= max_kb * 1024:
            return buf.getvalue()
    raise SystemExit(f"cannot fit the card in {max_kb} KB")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


def serve(site: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(site))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def context_args(p: Any, capture: dict[str, Any], scheme: str) -> dict[str, Any]:
    if "device" in capture:
        return {**p.devices[capture["device"]], "color_scheme": scheme}
    return {"viewport": dict(capture["viewport"]), "device_scale_factor": capture["scale"], "color_scheme": scheme}


def take_frames(browser: Any, p: Any, cfg: dict[str, Any], base: str, root: Path) -> list[Path]:
    """One WebP per hero frame and scheme: the first screen of the built digest, scaled to the frame's width x height."""
    land, shots = cfg["landing"], cfg["shots"]
    url = base + cfg["digest_paths"][shots["lang"]]
    written = []
    for name, frame in land["shots"].items():
        for scheme in SCHEMES:
            context = browser.new_context(**context_args(p, shots[name], scheme))
            page = context.new_page()
            page.goto(url, wait_until="load")
            page.evaluate(SETTLE_JS)
            png = page.screenshot()
            context.close()
            target = root / land["source_dir"] / frame[scheme]
            target.write_bytes(webp(png, (frame["width"], frame["height"]), shots["quality"], shots["max_kb"]))
            written.append(target)
    return written


def card_html(cfg: dict[str, Any], root: Path) -> str:
    """The social card page, from the template in source_dir; text from the English [landing] locale."""
    land, og = cfg["landing"], cfg["shots"]["og"]
    template = (root / land["source_dir"] / og["template"]).read_text(encoding="utf-8")
    ctx = {"browser": land["shots"]["browser"], "phone": land["shots"]["phone"],
           "host": cfg["site_url"].split("://", 1)[-1].rstrip("/")}
    html = build_landing.render(template, build_landing.locale(cfg["shots"]["lang"], root), ctx)
    logo = build_landing.inline_logo((root / land["logo"]).read_text(encoding="utf-8"), og["logo_size"])
    return html.replace("<!--logo-->", logo, 1)


def take_card(browser: Any, cfg: dict[str, Any], base: str, site: Path, root: Path) -> Path:
    og, land = cfg["shots"]["og"], cfg["landing"]
    build_landing.copy_assets(cfg, site, root)  # the fresh screenshots
    page_file = site / land["assets_out"] / og["page"]
    page_file.write_text(card_html(cfg, root), encoding="utf-8")
    size = {"width": int(cfg["image_width"]), "height": int(cfg["image_height"])}
    context = browser.new_context(viewport=size, device_scale_factor=1, color_scheme=og["scheme"])
    page = context.new_page()
    page.goto(base + land["assets_out"] + og["page"], wait_until="load")
    page.evaluate(SETTLE_JS)
    png = page.screenshot(clip={"x": 0, "y": 0, **size})
    context.close()
    page_file.unlink()
    target = root / cfg["image"]
    target.write_bytes(small_png(png, og["max_kb"]))
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    site, cfg = Path(argv[0]).resolve(), load_config()
    server, base = serve(site)
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch()
            try:
                written = take_frames(browser, p, cfg, base, ROOT)
                written.append(take_card(browser, cfg, base, site, ROOT))
            finally:
                browser.close()
    finally:
        server.shutdown()
    for path in written:
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
