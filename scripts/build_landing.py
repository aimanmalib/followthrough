"""Render the landing page of the public demo site (ADR 0017). Standard library only; called by build_pages.py.

The template (config/pages.toml [landing] template, under source_dir) uses four markers:
  {{key}}                     text from locales/<lang>.toml [landing], HTML-escaped
  {{@a.b}}                    a value from the build context (paths, config), HTML-escaped
  <!--if @a.b-->…<!--/if-->   kept only when the context value is set
  <!--each key-->…{{.f}}…<!--/each-->   repeated for each table in the locale list `key`
plus <!--head--> (preview tags from build_pages.py) and <!--logo--> (the inline brand mark).
Every text comes from the locale files and every value from config; the template holds no copy.
"""

from __future__ import annotations

import posixpath
import re
import shutil
import tomllib
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EACH = re.compile(r"<!--each ([\w.]+)-->(.*?)<!--/each-->", re.S)
IF = re.compile(r"<!--if @([\w.]+)-->(.*?)<!--/if-->", re.S)
KEY = re.compile(r"\{\{(@?[\w.]+)\}\}")
ITEM = re.compile(r"\{\{\.(\w+)\}\}")


class TemplateError(KeyError):
    """A marker names a key that does not exist, or a marker is left over after rendering."""


def lookup(data: dict[str, Any], dotted: str) -> Any:
    value: Any = data
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise TemplateError(dotted)
        value = value[part]
    return value


def optional(data: dict[str, Any], dotted: str) -> Any:
    try:
        return lookup(data, dotted)
    except TemplateError:
        return None


def render(template: str, text: dict[str, Any], ctx: dict[str, Any]) -> str:
    """Fill `template` from locale `text` and build context `ctx`; fail on unknown keys or leftover markers."""
    def each(m: re.Match) -> str:
        items = lookup(text, m.group(1))
        if not isinstance(items, list):
            raise TemplateError(m.group(1))
        return "".join(ITEM.sub(lambda f: escape(str(lookup(item, f.group(1)))), m.group(2)) for item in items)

    def keep(m: re.Match) -> str:
        return m.group(2) if optional(ctx, m.group(1)) else ""

    def value(m: re.Match) -> str:
        key = m.group(1)
        found = lookup(ctx, key[1:]) if key.startswith("@") else lookup(text, key)
        return escape(str(found))

    out = KEY.sub(value, IF.sub(keep, EACH.sub(each, template)))
    if re.search(r"\{\{|<!--(each|if|/each|/if)\b", out):
        raise TemplateError("marker left after rendering")
    return out


def inline_logo(svg: str, size: int) -> str:
    """The brand SVG as a decorative inline mark: no XML prolog, no title, hidden from assistive tech (the name follows it)."""
    svg = re.sub(r"<\?xml[^>]*>\s*|<!--.*?-->\s*", "", svg, flags=re.S)
    svg = re.sub(r"<title[^>]*>.*?</title>\s*", "", svg, flags=re.S)
    tag, body = svg.split("<svg", 1)[1].split(">", 1)
    tag = re.sub(r'\s(role|aria-labelledby|width|height)="[^"]*"', "", tag)
    body = re.sub(r">\s+<", "><", body).strip()
    return f'<svg{tag} width="{size}" height="{size}" aria-hidden="true" focusable="false">{body}'


def relative(page: str, target: str) -> str:
    """Link from the page at site path `page` (e.g. "ms/") to site path `target` (e.g. "digest/"); always ends in "/"."""
    rel = posixpath.relpath("/" + target, "/" + page) if target != page else "."
    return "./" if rel == "." else rel.rstrip("/") + "/"


def locale(lang: str, root: Path = ROOT, order: list[str] | None = None) -> dict[str, Any]:
    """The [landing] text for `lang`: the numbered `faq` table (q1/a1, q2/a2, …) as a list in number order, plus
    `actions`: the digest's own action labels in `order`."""
    with open(root / "locales" / f"{lang}.toml", "rb") as fh:
        data = tomllib.load(fh)
    text = dict(data["landing"])
    faq = text.get("faq", {})
    numbers = sorted({int(k[1:]) for k in faq if re.fullmatch(r"q\d+", k)})
    text["faq"] = [{"q": faq[f"q{n}"], "a": faq[f"a{n}"]} for n in numbers]
    text["actions"] = [{"code": code, "label": data["actions"][code]} for code in order or []]
    return text


def summary(digest: dict[str, Any], metrics: dict[str, Any], order: list[str]) -> dict[str, Any]:
    """The proof panel's data, from one fixture sweep's digest.json and metrics.json: counts only, no thread text."""
    guard = metrics.get("guard") or {}
    return {
        "schema": 1,
        "repo": digest["repo"],
        "date": digest["as_of"][:10],
        "threads": digest["threads"],
        "actions": [{"code": code, "count": int(digest["counts"].get(code, 0))} for code in order],
        "checked": int(guard.get("checked", 0)),
        "rejected": int(digest["guard_rejected"]),
        "read_failed": int(digest["read_failed"]),
        "usd": f'{float(metrics.get("usd") or 0):.2f}',
    }


def context(cfg: dict[str, Any], lang: str) -> dict[str, Any]:
    land = cfg["landing"]
    paths, digests = cfg["paths"], cfg["digest_paths"]
    here = paths[lang]
    other = next(code for code in paths if code != lang)
    host = cfg["site_url"].split("://", 1)[-1]
    return {
        "lang": lang,
        "home": relative(here, here),
        "assets": relative(here, land["assets_out"]),
        "digest": relative(here, digests[lang]),
        "digest_host": host + digests[lang],
        "other_lang": other,
        "other_href": relative(here, paths[other]),
        "repo_url": land["repo_url"],
        "demo_url": land["demo_url"],
        "demo_guide_url": land["demo_guide_url"],
        "results_url": land["results_url"],
        "video_url": land["video_url"],
        "summary": relative(here, digests[next(iter(digests))]) + land["summary_file"],
        "theme_key": land["theme_storage_key"],
        "browser": land["shots"]["browser"],
        "phone": land["shots"]["phone"],
    }


def page(cfg: dict[str, Any], lang: str, head: str, root: Path = ROOT) -> str:
    """The full landing page for `lang`, with `head` (preview tags) inserted once."""
    land = cfg["landing"]
    template = (root / land["source_dir"] / land["template"]).read_text(encoding="utf-8")
    for marker in ("<!--head-->", "<!--logo-->"):
        if template.count(marker) != 1:
            raise TemplateError(f"template needs exactly one {marker}")
    html = render(template, locale(lang, root, land["actions"]), context(cfg, lang))
    logo = inline_logo((root / land["logo"]).read_text(encoding="utf-8"), 36)
    return html.replace("<!--head-->", head.rstrip("\n"), 1).replace("<!--logo-->", logo, 1)


def copy_assets(cfg: dict[str, Any], site: Path, root: Path = ROOT) -> Path:
    """Copy the page's styles, script, fonts, screenshots and the logo to the site's assets folder."""
    land = cfg["landing"]
    source, out = root / land["source_dir"], site / land["assets_out"]
    out.mkdir(parents=True, exist_ok=True)
    for name in land["copy"]:
        if (source / name).is_dir():
            shutil.copytree(source / name, out / name, dirs_exist_ok=True)
        else:
            shutil.copyfile(source / name, out / name)
    shutil.copyfile(root / land["logo"], out / Path(land["logo"]).name)
    return out
