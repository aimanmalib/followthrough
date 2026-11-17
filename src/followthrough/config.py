"""Load config/*.toml and locales/*.toml.

Code reads values from these files; it never stores them. REQUIRED lists the keys each
file must define (dotted paths), so a missing key fails at load time, not mid-sweep.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
LOCALE_DIR = ROOT / "locales"
LANGS = ("en", "ms")
DEFAULT_LANG = "en"

REQUIRED: dict[str, tuple[str, ...]] = {
    "policy": (
        "windows.follow_up_days",
        "windows.after_follow_up_days",
        "windows.maintainer_reply_days",
        "labels.awaiting_release",
        "labels.status_prefix",
        "labels.waiting_on",
        "roles.maintainer_associations",
        "roles.maintainers_extra",
        "guard.quote_max_chars",
        "sweep.fixture",
        "sweep.fixture_states",
        "sweep.output_dir",
        "digest.list_actions",
        "ledger.expiry_days",
        "ledger.namespace_prefix",
        "github.api_base",
        "github.per_page",
        "github.snapshot_dir",
        "github.etag_cache",
        "github.timeout_s",
        "github.max_pages",
        "github.token_env",
    ),
    "models": (
        "provider",
        "key_env",
        "agents_json",
        "max_concurrency",
        "profiles.reader.model",
        "profiles.drafter.model",
        "profiles.drafter.max_words",
        "fallback",
    ),
    "safety": ("stop_env", "stop_file", "stop_exit_code", "allow_post_repos"),
    "budget": (
        "usd_max_per_sweep",
        "usd_max_total",
        "spend_ledger",
        "chars_per_token_estimate",
        "turn_reserve_usd",
    ),
    "prices": ("models",),
    "prompts": ("reader.instructions", "reader.message"),
}


class ConfigError(Exception):
    """A config or locale file is missing or incomplete."""


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(t("errors.config_missing_file", path=path.name))
    with path.open("rb") as fh:
        return tomllib.load(fh)


def get(data: dict[str, Any], dotted: str) -> Any:
    """Return data[a][b][c] for "a.b.c"; KeyError if any part is missing."""
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(dotted)
        cur = cur[part]
    return cur


def load(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Load config/<name>.toml and check every REQUIRED key is present."""
    data = _read((config_dir or CONFIG_DIR) / f"{name}.toml")
    for key in REQUIRED.get(name, ()):
        try:
            get(data, key)
        except KeyError:
            raise ConfigError(t("errors.config_missing_key", file=f"{name}.toml", key=key)) from None
    return data


def load_all(config_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    return {name: load(name, config_dir) for name in REQUIRED}


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in data.items():
        if isinstance(val, dict):
            out.update(_flatten(val, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = val
    return out


_LOCALES: dict[str, dict[str, str]] = {}


def strings(lang: str = DEFAULT_LANG, locale_dir: Path | None = None) -> dict[str, str]:
    """All user-facing strings for one language, as flat dotted keys."""
    if lang not in LANGS:
        raise ConfigError(t("errors.locale_unknown", DEFAULT_LANG, lang=lang))
    if locale_dir is not None:
        with (locale_dir / f"{lang}.toml").open("rb") as fh:
            return _flatten(tomllib.load(fh))
    if lang not in _LOCALES:
        with (LOCALE_DIR / f"{lang}.toml").open("rb") as fh:
            _LOCALES[lang] = _flatten(tomllib.load(fh))
    return _LOCALES[lang]


def t(key: str, lang: str = DEFAULT_LANG, /, **fields: Any) -> str:
    """One translated string with {fields} filled in."""
    return strings(lang)[key].format(**fields)
