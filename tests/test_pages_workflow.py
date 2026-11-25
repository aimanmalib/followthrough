"""The public Pages workflow publishes only the offline fixture digest, in both languages, with no secrets."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pages.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_uses_fixture_sweep_only() -> None:
    text = _text()
    assert "sweep --fixture" in text
    assert "--live" not in text


def test_no_secrets_or_keys() -> None:
    text = _text()
    for needle in ("secrets.", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "HF_TOKEN"):
        assert needle not in text


def test_both_languages_published() -> None:
    text = _text()
    assert 'for lang in en ms' in text
    assert "scripts/build_pages.py runs _site" in text


def test_minimal_permissions() -> None:
    text = _text()
    assert "contents: read" in text and "pages: write" in text and "id-token: write" in text
    assert "contents: write" not in text
