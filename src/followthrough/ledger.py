"""Reminder ledger: no follow-up is drafted twice for a thread that has not changed.

One row per thread, keyed by (namespace, number), namespace = `<prefix>/<owner>/<repo>`:
{state hash, last action, drafted_at, session_id}. A new draft is allowed only when there is no row,
the state hash changed, the action changed, or the row is older than `ledger.expiry_days`.

Storage is SQLite (`ledger.path`), not OpenMinion memory: measured on openminion 0.1.23, memory has no
exact lookup by key (search by key text returns other keys too) and `list` still returns records whose
`expires_at` has passed, so it cannot enforce "suppress only until expiry" by itself (ADR 0007).
Only numbers, hashes, action names and timestamps are stored; no thread text.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

from followthrough.state import parse_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    namespace  TEXT    NOT NULL,
    number     INTEGER NOT NULL,
    state_hash TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    drafted_at TEXT    NOT NULL,
    session_id TEXT    NOT NULL,
    PRIMARY KEY (namespace, number)
)
"""

NEW = "new"                    # no earlier reminder for this thread
CHANGED = "changed"            # thread state hash differs from the one drafted against
ACTION_CHANGED = "action_changed"
EXPIRED = "expired"            # earlier reminder older than the expiry window
UNCHANGED = "unchanged"        # suppressed: same state, same action, still inside the window
ALLOW = frozenset({NEW, CHANGED, ACTION_CHANGED, EXPIRED})


def state_hash(thread: Mapping[str, Any]) -> str:
    """Hash of what makes a thread "changed": updated_at, number of comments, sorted labels."""
    material = {"updated_at": str(thread.get("updated_at") or ""),
                "comments": len(thread.get("comments") or []),
                "labels": sorted(str(x) for x in thread.get("labels") or [])}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def namespace(repo: str, prefix: str) -> str:
    owner, name = repo.split("/", 1)
    return f"{prefix}/{owner}/{name}"


@dataclass(frozen=True)
class Entry:
    number: int
    state_hash: str
    action: str
    drafted_at: datetime
    session_id: str


class Ledger:
    """SQLite-backed reminder ledger. Use as a context manager or call close()."""

    def __init__(self, path: Path, *, prefix: str, expiry_days: int) -> None:
        if expiry_days <= 0:
            raise ValueError("expiry_days must be positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.prefix = prefix
        self.expiry = timedelta(days=expiry_days)
        self._db = sqlite3.connect(path)
        self._db.execute(SCHEMA)
        self._db.commit()

    @classmethod
    def from_policy(cls, root: Path, policy: Mapping[str, Any]) -> Ledger:
        cfg = policy["ledger"]
        return cls(root / cfg["path"], prefix=cfg["namespace_prefix"], expiry_days=int(cfg["expiry_days"]))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def get(self, repo: str, number: int) -> Entry | None:
        row = self._db.execute(
            "SELECT number, state_hash, action, drafted_at, session_id FROM reminders"
            " WHERE namespace = ? AND number = ?", (namespace(repo, self.prefix), int(number))).fetchone()
        if row is None:
            return None
        return Entry(int(row[0]), row[1], row[2], parse_ts(row[3]), row[4])

    def verdict(self, repo: str, number: int, thread_hash: str, action: str, now: datetime) -> str:
        """Why a draft is (or is not) allowed now; a draft is allowed when the verdict is in ALLOW."""
        entry = self.get(repo, number)
        if entry is None:
            return NEW
        if entry.state_hash != thread_hash:
            return CHANGED
        if entry.action != action:
            return ACTION_CHANGED
        if now - entry.drafted_at >= self.expiry:
            return EXPIRED
        return UNCHANGED

    def record(self, repo: str, number: int, thread_hash: str, action: str, now: datetime,
               session_id: str) -> None:
        """Remember that a draft was saved for this thread state; replaces any earlier row."""
        self._db.execute(
            "INSERT INTO reminders (namespace, number, state_hash, action, drafted_at, session_id)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (namespace, number) DO UPDATE SET"
            " state_hash = excluded.state_hash, action = excluded.action,"
            " drafted_at = excluded.drafted_at, session_id = excluded.session_id",
            (namespace(repo, self.prefix), int(number), thread_hash, action,
             now.astimezone(UTC).isoformat().replace("+00:00", "Z"), session_id))
        self._db.commit()

    def count(self, repo: str) -> int:
        row = self._db.execute("SELECT COUNT(*) FROM reminders WHERE namespace = ?",
                               (namespace(repo, self.prefix),)).fetchone()
        return int(row[0])
