"""Render digest.html in Chromium and WebKit (iPhone 13) and check it: no sideways scroll, no console
errors, WCAG AA text contrast, in light and dark colour schemes. Saves DSF 3 screenshots.

Needs Playwright with Chromium and WebKit installed (not a project dependency):
    python3 scripts/check_page.py OUT_DIR PAGE.html [PAGE.html ...]
Exit 0 = every page passed in every browser, width and scheme; the report is OUT_DIR/page-check.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = {"w320": {"width": 320, "height": 800}, "desktop": {"width": 1280, "height": 900}}
SCHEMES = ("light", "dark")

# For every element with its own text: contrast of its colour against the first opaque background above it.
CONTRAST_JS = """() => {
  const rgb = s => (s.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((acc, v, i) => acc + v * [0.2126, 0.7152, 0.0722][i], 0);
  const bg = el => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor);
    if (c.length === 3 || (c.length === 4 && c[3] > 0.99)) return c.slice(0, 3); } return [255, 255, 255]; };
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    const st = getComputedStyle(el); const size = parseFloat(st.fontSize); const bold = parseInt(st.fontWeight) >= 700;
    const a = lum(rgb(st.color).slice(0, 3)), b = lum(bg(el));
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) bad.push({ text: el.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100, need });
  }
  return bad;
}"""
OVERFLOW_JS = """() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
  wide: [...document.querySelectorAll('body *')].filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5)
    .map(e => e.className || e.tagName).slice(0, 5) })"""


def check(browser, name: str, context_args: dict, page_path: Path, scheme: str, shots: Path) -> dict:
    context = browser.new_context(**context_args, color_scheme=scheme)
    tab = context.new_page()
    errors: list[str] = []
    tab.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    tab.on("pageerror", lambda e: errors.append(str(e)))
    tab.goto(page_path.resolve().as_uri())
    tab.wait_for_load_state("load")
    overflow = tab.evaluate(OVERFLOW_JS)
    contrast = tab.evaluate(CONTRAST_JS)
    label = page_path.parent.as_posix().strip("./").replace("/", "_")
    shot = shots / f"{label}-{name}-{scheme}.png"
    tab.screenshot(path=str(shot), full_page=True)
    context.close()
    ok = overflow["scroll"] <= overflow["client"] and not overflow["wide"] and not errors and not contrast
    return {"page": str(page_path), "view": name, "scheme": scheme, "ok": ok, "overflow": overflow,
            "console_errors": errors, "low_contrast": contrast, "screenshot": shot.name}


def main(argv: list[str]) -> int:
    out, pages = Path(argv[0]), [Path(p) for p in argv[1:]]
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        views = []
        chromium, webkit = p.chromium.launch(), p.webkit.launch()
        for key, size in WIDTHS.items():
            views.append((chromium, f"chromium-{key}", {"viewport": size, "device_scale_factor": 3}))
        views.append((webkit, "webkit-iphone13", {**p.devices["iPhone 13"], "device_scale_factor": 3}))
        views.append((webkit, "webkit-w320", {"viewport": WIDTHS["w320"], "device_scale_factor": 3,
                                              "is_mobile": True, "has_touch": True}))
        for page_path in pages:
            for browser, name, args in views:
                for scheme in SCHEMES:
                    results.append(check(browser, name, args, page_path, scheme, out))
        chromium.close()
        webkit.close()
    (out / "page-check.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    failed = [r for r in results if not r["ok"]]
    for r in failed:
        print(json.dumps(r))
    print(f"page check: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
