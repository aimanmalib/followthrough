"""The digest: how many threads need each action, and one neutral line per listed thread.

`build` turns readings and decisions into a plain-JSON dict; `render_md` prints it in one language.
The digest holds thread numbers, action names, dates and counts only. The neutral line is our own
locale text filled with dates, never words from the thread, so a digest of a third-party repo
carries no third-party text.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from followthrough.agents import ReadOutcome
from followthrough.config import t
from followthrough.github import iso
from followthrough.rules import ACTIONS, NO_ACTION, Decision

DIGEST_SCHEMA = 1
READ_FAILED = "read_failed"


def _item(outcome: ReadOutcome, decision: Decision | None) -> dict[str, Any]:
    if decision is None:
        return {"number": outcome.number, "action": NO_ACTION, "reason": READ_FAILED, "dates": {},
                "release_tag": None, "guard_rejected": False}
    dates = {k: v.isoformat() if isinstance(v, date) else str(v) for k, v in decision.dates.items()}
    return {"number": decision.number, "action": decision.action, "reason": decision.reason, "dates": dates,
            "release_tag": decision.release_tag,
            "guard_rejected": bool(outcome.checked and outcome.checked.rejected)}


def build(repo: str, now: datetime, mode: str, reader: str,
          rows: Iterable[tuple[ReadOutcome, Decision | None]], *, stopped: str | None = None,
          extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One digest as plain JSON. Items are ordered by action (as in `rules.ACTIONS`), then number."""
    items = [_item(outcome, decision) for outcome, decision in rows]
    items.sort(key=lambda i: (ACTIONS.index(i["action"]), i["number"]))
    return {
        "schema": DIGEST_SCHEMA,
        "repo": repo,
        "as_of": iso(now),
        "mode": mode,
        "reader": reader,
        "threads": len(items),
        "counts": {a: sum(1 for i in items if i["action"] == a) for a in ACTIONS},
        "guard_rejected": sum(1 for i in items if i["guard_rejected"]),
        "read_failed": sum(1 for i in items if i["reason"] == READ_FAILED),
        "stopped": stopped,
        "items": items,
        **(dict(extra) if extra else {}),
    }


def line(item: Mapping[str, Any], lang: str) -> str:
    """The neutral one-line explanation for an item, from the locale file."""
    return t(f"reasons.{item['reason']}", lang, **item["dates"], release_tag=item["release_tag"] or "")


def render_md(digest: Mapping[str, Any], lang: str, list_actions: Sequence[str]) -> str:
    """Markdown digest in `lang`: counts table, listed actions with one line per thread, footnotes."""
    out = [f"# {t('digest.title', lang, repo=digest['repo'])}", "",
           t("digest.as_of", lang, as_of=digest["as_of"], threads=digest["threads"]), ""]
    if digest.get("stopped"):
        out += [f"> {t('digest.partial', lang, reason=digest['stopped'])}", ""]
    out += [f"| {t('digest.col_action', lang)} | {t('digest.col_threads', lang)} |", "|---|---:|"]
    out += [f"| {t(f'actions.{a}', lang)} | {n} |" for a, n in digest["counts"].items()]
    for action in list_actions:
        items = [i for i in digest["items"] if i["action"] == action]
        if not items:
            continue
        out += ["", f"## {t(f'actions.{action}', lang)} ({len(items)})", ""]
        out += [f"- #{i['number']}: {line(i, lang)}" for i in items]
    out += ["", t("digest.guard_note", lang, rejected=digest["guard_rejected"], failed=digest["read_failed"])]
    return "\n".join(out) + "\n"


def write(digest: Mapping[str, Any], markdown: str, out_root: Path) -> Path:
    """Write digest.json + digest.md under <out_root>/<YYYY-MM-DD of as_of>/; returns that folder."""
    folder = out_root / digest["as_of"][:10]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (folder / "digest.md").write_text(markdown, encoding="utf-8")
    return folder
