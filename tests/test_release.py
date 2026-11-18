"""The version in pyproject.toml matches the newest CHANGELOG release, RELEASE.md, PROJECTS.yml and STATUS.md."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_changelog_newest_release_is_the_package_version() -> None:
    releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert releases and releases[0] == VERSION


def test_changelog_has_a_link_for_the_release() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{VERSION}]: https://github.com/aimanmalib/followthrough/releases/tag/v{VERSION}" in text


def test_release_notes_start_with_the_package_version() -> None:
    headings = re.findall(r"^## v(\d+\.\d+\.\d+) ", (ROOT / "RELEASE.md").read_text(encoding="utf-8"), re.M)
    assert headings and headings[0] == VERSION


def test_projects_and_status_name_the_package_version() -> None:
    assert f"version: v{VERSION}" in (ROOT / "PROJECTS.yml").read_text(encoding="utf-8")
    assert f"**Version:** [{VERSION}]" in (ROOT / "STATUS.md").read_text(encoding="utf-8")


def test_demo_guide_is_linked_from_both_readmes() -> None:
    assert (ROOT / "demo" / "README.md").is_file()
    for name in ("README.md", "README.ms.md"):
        assert "(demo/README.md)" in (ROOT / name).read_text(encoding="utf-8")
