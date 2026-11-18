"""The project folder carries what cortensor/community-projects asks of every project.

That repository's README asks each project for README.md, STATUS.md, RELEASE.md, an MIT licence and a
PROJECTS.yml entry; its `tools/hello-world-tool/PROJECTS.yml` template uses the keys checked below. The
check is on shape only, so a later version or tag change does not break it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_KEYS = ["name", "category", "owner", "collaborators", "status", "created", "version", "tags"]


def _top_level_keys(text: str) -> list[str]:
    keys = []
    for line in text.splitlines():
        match = re.match(r"^(?:- |  )([a-z_]+):", line)
        if match:
            keys.append(match.group(1))
    return keys


def test_projects_entry_has_the_template_keys_in_order() -> None:
    text = (ROOT / "PROJECTS.yml").read_text(encoding="utf-8")
    assert text.startswith("- name: ")
    assert _top_level_keys(text) == TEMPLATE_KEYS


def test_projects_entry_values_have_the_template_shape() -> None:
    text = (ROOT / "PROJECTS.yml").read_text(encoding="utf-8")
    assert re.search(r"^  category: (apps|tools|infras)$", text, re.M)
    assert re.search(r'^  owner: "@[A-Za-z0-9-]+"$', text, re.M)
    assert re.search(r'^    - "@[A-Za-z0-9-]+"$', text, re.M)
    assert re.search(r"^  created: \d{4}-\d{2}-\d{2}$", text, re.M)
    assert re.search(r"^  version: v\d+\.\d+\.\d+$", text, re.M)
    assert re.search(r"^  tags: \[[a-z0-9-]+(, [a-z0-9-]+)*\]$", text, re.M)


def test_required_project_files_exist() -> None:
    for name in ("README.md", "STATUS.md", "RELEASE.md", "LICENSE"):
        assert (ROOT / name).is_file(), name
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")
