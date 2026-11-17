"""Config and locale files: shape checks only (owners may change the values)."""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from followthrough import cli, config

SANDBOX_REPO = "aimanmalib/followthrough-sandbox"


def test_every_config_file_loads_with_required_keys():
    data = config.load_all()
    assert set(data) == {"policy", "models", "safety", "budget", "prices", "prompts"}


@pytest.mark.parametrize("key", ["follow_up_days", "after_follow_up_days", "maintainer_reply_days"])
def test_windows_are_positive_whole_days(key):
    days = config.get(config.load("policy"), f"windows.{key}")
    assert isinstance(days, int) and days > 0


def test_budget_limits_are_positive_and_ordered():
    budget = config.load("budget")
    per_sweep, total = budget["usd_max_per_sweep"], budget["usd_max_total"]
    assert isinstance(per_sweep, float) and isinstance(total, float)
    assert 0 < per_sweep <= total


def test_every_profile_model_has_a_price():
    models, prices = config.load("models"), config.load("prices")
    for profile in models["profiles"].values():
        price = prices["models"][profile["model"]]
        assert price["input_per_mtok"] >= 0 and price["output_per_mtok"] >= 0


def test_allow_post_repos_holds_only_the_sandbox():
    repos = config.load("safety")["allow_post_repos"]
    assert isinstance(repos, list)
    assert all(r == SANDBOX_REPO for r in repos)


def test_missing_required_key_fails_at_load(tmp_path: Path):
    for f in config.CONFIG_DIR.glob("*.toml"):
        shutil.copy(f, tmp_path / f.name)
    path = tmp_path / "budget.toml"
    path.write_text(
        "\n".join(ln for ln in path.read_text().splitlines() if not ln.startswith("usd_max_total")),
        encoding="utf-8",
    )
    with pytest.raises(config.ConfigError, match="usd_max_total"):
        config.load("budget", tmp_path)


def test_missing_file_fails_at_load(tmp_path: Path):
    with pytest.raises(config.ConfigError, match="policy.toml"):
        config.load("policy", tmp_path)


def _keys(lang: str) -> set[str]:
    with (config.LOCALE_DIR / f"{lang}.toml").open("rb") as fh:
        return set(config._flatten(tomllib.load(fh)))


def test_locales_have_identical_keys():
    assert _keys("en") == _keys("ms")


def test_locale_placeholders_match():
    import string

    fmt = string.Formatter()
    en, ms = config.strings("en"), config.strings("ms")
    for key, text in en.items():
        names = {f for _, f, _, _ in fmt.parse(text) if f}
        assert names == {f for _, f, _, _ in fmt.parse(ms[key]) if f}, key


def test_unknown_language_is_rejected():
    with pytest.raises(config.ConfigError, match="xx"):
        config.strings("xx")


@pytest.mark.parametrize("lang", config.LANGS)
def test_cli_prints_localized_text(lang, capsys):
    assert cli.main(["--lang", lang]) == 0
    assert capsys.readouterr().out.strip() == config.t("cli.not_ready", lang)
