"""`digest.html`: the digest as one self-contained page in one language.

The page carries what `digest.json` and `metrics.json` already carry (counts, thread numbers, our own
locale lines with dates) and nothing else: no thread text, no scripts, no external fonts, images or
links, so it renders offline and can be published as-is for a synthetic sandbox sweep. The layout is
`templates/digest.html`, every colour is a token in `templates/digest.css`, every word is in `locales/`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from string import Template
from typing import Any

from followthrough import __version__
from followthrough.config import t
from followthrough.digest import line

TEMPLATES = Path(__file__).resolve().parent / "templates"
_SLOT = "\x00time\x00"  # stands in for the <time> element while the sentence around it is escaped


def _when(as_of: str) -> str:
    """`2026-11-20T09:00:00Z` -> `2026-11-20 09:00 UTC` (the digest clock is always UTC)."""
    return f"{as_of[:10]} {as_of[11:16]} UTC"


def _tally(counts: Mapping[str, int], lang: str) -> str:
    rows = []
    for action, n in counts.items():
        zero = " is-zero" if n == 0 else ""
        rows.append(f'<li class="tally-item tone-{escape(action)}{zero}"><span class="count">{int(n)}</span>'
                    f'<span class="name">{escape(t(f"actions.{action}", lang))}</span></li>')
    return "\n".join(rows)


def _usd(value: float) -> str:
    return f"{value:.2f}" if value >= 0.01 or value == 0 else f"{value:.4f}"


def _metrics(metrics: Mapping[str, Any] | None, lang: str) -> str:
    if not metrics:
        return ""
    http = metrics.get("http")
    guard = metrics.get("guard") or {}
    cells = [("page.m_seconds", t("page.v_seconds", lang, seconds=metrics["seconds"])),
             ("page.m_usd", t("page.v_usd", lang, usd=_usd(float(metrics.get("usd", 0.0))))),
             ("page.m_http", t("page.v_http", lang, requests=http["requests"], non_get=http["non_get"])
              if http else t("page.v_http_none", lang)),
             ("page.m_guard", t("page.v_guard", lang, rejected=guard.get("rejected", 0),
                                checked=guard.get("checked", 0)))]
    body = "\n".join(f'<div class="metric"><dt>{escape(t(k, lang))}</dt><dd>{escape(v)}</dd></div>'
                     for k, v in cells)
    return (f'<section class="metrics" aria-labelledby="metrics-h">\n'
            f'<h2 id="metrics-h" class="label">{escape(t("page.metrics_heading", lang))}</h2>\n'
            f'<dl class="metric-list">\n{body}\n</dl>\n</section>')


def _sections(digest: Mapping[str, Any], lang: str, list_actions: Sequence[str]) -> str:
    out = []
    for action in list_actions:
        items = [i for i in digest["items"] if i["action"] == action]
        if not items:
            continue
        rows = "\n".join(f'<li class="item"><span class="num">#{int(i["number"])}</span>'
                         f'<span class="why">{escape(line(i, lang))}</span></li>' for i in items)
        slug = escape(action.lower())
        out.append(f'<section class="action tone-{escape(action)}" aria-labelledby="h-{slug}">\n'
                   f'<h2 id="h-{slug}">{escape(t(f"actions.{action}", lang))}'
                   f' <span class="count">{len(items)}</span></h2>\n<ol class="items">\n{rows}\n</ol>\n</section>')
    if not out:
        out.append(f'<section class="action"><p>{escape(t("page.nothing_listed", lang))}</p></section>')
    return "\n".join(out)


def render(digest: Mapping[str, Any], metrics: Mapping[str, Any] | None, lang: str,
           list_actions: Sequence[str]) -> str:
    """The whole page as a string. Every value from the digest is HTML-escaped."""
    repo = digest["repo"]
    when = _when(digest["as_of"])
    stamp = f'<time datetime="{escape(digest["as_of"])}">{escape(when)}</time>'
    as_of = escape(t("page.as_of", lang, as_of=_SLOT, threads=int(digest["threads"]))).replace(_SLOT, stamp)
    source = t("page.source", lang, mode=t(f"page.mode_{digest['mode']}", lang),
               reader=t(f"page.reader_{digest['reader']}", lang))
    partial = ""
    if digest.get("stopped"):
        partial = f'<p class="partial" role="status">{escape(t("digest.partial", lang, reason=digest["stopped"]))}</p>'
    fields = {
        "lang": escape(lang),
        "title": escape(t("digest.title", lang, repo=repo)),
        "css": (TEMPLATES / "digest.css").read_text(encoding="utf-8"),
        "kicker": escape(t("page.kicker", lang)),
        "repo": "/<wbr>".join(escape(part) for part in repo.split("/", 1)),  # breaks after owner/ on narrow screens
        "as_of": as_of,  # escaped text with our own <time> element put back in
        "source": escape(source),
        "partial": partial,
        "tally_heading": escape(t("page.tally_heading", lang)),
        "tally": _tally(digest["counts"], lang),
        "metrics": _metrics(metrics, lang),
        "sections": _sections(digest, lang, list_actions),
        "guard_note": escape(t("digest.guard_note", lang, rejected=digest["guard_rejected"],
                               failed=digest["read_failed"])),
        "privacy_note": escape(t("page.privacy_note", lang)),
        "made_by": escape(t("page.made_by", lang, version=__version__)),
    }
    template = Template((TEMPLATES / "digest.html").read_text(encoding="utf-8"))
    return template.substitute(fields)


def write(folder: Path, page: str, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(page, encoding="utf-8")
    return path
