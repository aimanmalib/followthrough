"""The OpenMinion findings package (H7): repro folders, BUILDING_BLOCKS.md and LEARNED.md stay consistent.

The repro scripts themselves take 1 to 3 minutes each against a real runtime, so they are run by hand
(results in docs/TEST-RESULTS.md); these checks keep the package honest without running them.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPRO = ROOT / "repro"
SECTIONS = ("## Steps", "## Expected", "## Actual", "## Safe evidence")
# OpenMinion API use that a BUILDING_BLOCKS "Where" reference must point at.
API_TOKENS = ("@tool", "subagent(", "output_type", "home.call(", "approval_callback", "ipc_port")


def repro_folders() -> list[Path]:
    return sorted(p for p in REPRO.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def test_at_least_three_repros_each_with_script_and_required_sections():
    folders = repro_folders()
    assert len(folders) >= 3
    index = (REPRO / "README.md").read_text(encoding="utf-8")
    for folder in folders:
        text = (folder / "README.md").read_text(encoding="utf-8")
        assert all(s in text for s in SECTIONS), folder.name
        assert "openminion 0.1.23" in text, folder.name
        assert (folder / "repro.py").is_file(), folder.name
        assert f"]({folder.name}/README.md)" in index, folder.name


def test_repro_scripts_reach_only_localhost_and_hold_no_tokens():
    for script in REPRO.rglob("*.py"):
        text = script.read_text(encoding="utf-8")
        hosts = set(re.findall(r"https?://([^/:\"'\s]+)", text))
        assert hosts <= {"127.0.0.1"}, (script.name, hosts)
        assert "api.github.com" not in text and "gh auth" not in text, script.name


def test_links_in_findings_documents_resolve():
    for name in ("BUILDING_BLOCKS.md", "LEARNED.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+)\)", text):
            assert (ROOT / target).exists(), (name, target)
        for folder in re.findall(r"`repro/([a-z0-9-]+)`", text):
            assert (REPRO / folder / "README.md").is_file(), (name, folder)


def test_building_blocks_has_eight_blocks_and_line_references_point_at_openminion_use():
    rows = [line for line in (ROOT / "BUILDING_BLOCKS.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| ") and not line.startswith(("| Block", "|---"))]
    assert len(rows) >= 8
    checked = 0
    for row in rows:
        where = row.split("|")[2]
        for path, lines in re.findall(r"`(src/followthrough/[a-z_]+\.py)((?::\d+`?(?:, `?)?)+)", where):
            source = (ROOT / path).read_text(encoding="utf-8").splitlines()
            for number in map(int, re.findall(r"\d+", lines)):
                assert any(t in source[number - 1] for t in API_TOKENS), (path, number, source[number - 1])
                checked += 1
    assert checked >= 10
