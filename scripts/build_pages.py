"""Assemble the public demo site: a landing page and the fixture digest pages (ADR 0016, ADR 0017).

    uv run python scripts/build_pages.py RUNS_DIR SITE_DIR

RUNS_DIR/<lang>/<date>/digest.html comes from `followthrough sweep --fixture --lang <lang> --out RUNS_DIR/<lang>`.
Each digest is copied to SITE_DIR/<digest path>index.html with a description, social preview tags, language
alternates and a tab icon added to <head>; the page body is not changed. The landing page for each language
(scripts/build_landing.py) goes to SITE_DIR/<path>index.html, with its assets under the [landing] assets folder, and the
first language's digest.json + metrics.json become the proof panel's summary.json next to that digest.
Paths come from config/pages.toml.
"""

from __future__ import annotations

import json
import shutil
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from followthrough.config import load, t  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import build_landing  # noqa: E402


def head_tags(cfg: dict, lang: str, title: str, paths: dict[str, str] | None = None,
              description_key: str = "pages.description") -> str:
    """The <head> additions for one language. `title` is the page's own <title> text (already escaped);
    `paths` maps each language to its page (default: the landing paths)."""
    site = cfg["site_url"]
    paths = paths or cfg["paths"]
    image = site + Path(cfg["image"]).name
    description = escape(t(description_key, lang))
    rows = [
        f'<meta name="description" content="{description}">',
        f'<link rel="icon" type="image/png" href="{escape(site + Path(cfg["icon"]).name)}">',
        f'<link rel="canonical" href="{escape(site + paths[lang])}">',
        *(f'<link rel="alternate" hreflang="{code}" href="{escape(site + path)}">' for code, path in paths.items()),
        '<meta property="og:type" content="website">',
        f'<meta property="og:url" content="{escape(site + paths[lang])}">',
        f'<meta property="og:title" content="{title}">',
        f'<meta property="og:description" content="{description}">',
        f'<meta property="og:image" content="{escape(image)}">',
        f'<meta property="og:image:width" content="{int(cfg["image_width"])}">',
        f'<meta property="og:image:height" content="{int(cfg["image_height"])}">',
        f'<meta property="og:image:alt" content="{escape(t(cfg["image_alt_key"], lang))}">',
        f'<meta property="og:locale" content="{"ms_MY" if lang == "ms" else "en_US"}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    return "\n".join(rows) + "\n"


def with_tags(html: str, tags: str) -> str:
    """Insert `tags` just before </head>; fail loudly if the page has no head or no title."""
    if html.count("</head>") != 1 or "<title>" not in html:
        raise ValueError("digest page has no single <head> with a <title>")
    return html.replace("</head>", tags + "</head>", 1)


def page_title(html: str) -> str:
    return html.split("<title>", 1)[1].split("</title>", 1)[0]


def find_page(runs: Path, lang: str) -> Path:
    found = sorted((runs / lang).glob("*/digest.html"))
    if len(found) != 1:
        raise FileNotFoundError(f"expected one digest.html under {runs / lang}, found {len(found)}")
    return found[0]


def write(out: Path, html: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def write_summary(cfg: dict, run: Path, folder: Path) -> Path:
    """The proof panel's counts (scripts/build_landing.summary) from one run folder's digest.json and metrics.json."""
    digest, metrics = (json.loads((run / name).read_text(encoding="utf-8")) for name in ("digest.json", "metrics.json"))
    data = build_landing.summary(digest, metrics, cfg["landing"]["actions"])
    return write(folder / cfg["landing"]["summary_file"], json.dumps(data, indent=1) + "\n")


def build(runs: Path, site: Path, root: Path = ROOT) -> list[Path]:
    cfg = load("pages")
    site.mkdir(parents=True, exist_ok=True)
    written = []
    for lang, path in cfg["digest_paths"].items():
        found = find_page(runs, lang)
        html = found.read_text(encoding="utf-8")
        tags = head_tags(cfg, lang, page_title(html), cfg["digest_paths"])
        written.append(write(site / path / "index.html", with_tags(html, tags)))
    first = next(iter(cfg["digest_paths"]))
    written.append(write_summary(cfg, find_page(runs, first).parent, site / cfg["digest_paths"][first]))
    for lang, path in cfg["paths"].items():
        tags = head_tags(cfg, lang, escape(t("landing.title", lang)), description_key="landing.description")
        written.append(write(site / path / "index.html", build_landing.page(cfg, lang, tags, root)))
    build_landing.copy_assets(cfg, site, root)
    for key in ("image", "icon"):
        shutil.copyfile(root / cfg[key], site / Path(cfg[key]).name)
    (site / ".nojekyll").touch()
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    for path in build(Path(argv[0]), Path(argv[1])):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
