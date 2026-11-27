"""Render pages in Chromium and WebKit (iPhone 13) and check them: no sideways scroll, no console errors, WCAG AA
text contrast, in light and dark colour schemes. Saves DSF 3 screenshots.

Needs Playwright with Chromium and WebKit installed (not a project dependency):
    python3 scripts/check_page.py OUT_DIR PAGE [PAGE ...]
PAGE is a file path or an http(s) URL; serve the built site over http so the landing page can load its summary.
On pages with a live panel ([data-hidup]) the check waits for it to settle, opens every <details>, and also loads
the page with ?keadaan=kosong and ?keadaan=ralat. Exit 0 = every page passed in every browser, width and scheme;
the report is OUT_DIR/page-check.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = {"w320": {"width": 320, "height": 800}, "desktop": {"width": 1440, "height": 900}}
SCHEMES = ("light", "dark")
STATES = ("kosong", "ralat")

# Colours go through a canvas, so oklab()/color() values from color-mix() come back as sRGB bytes in every engine.
# For every visible element with its own text: contrast of its colour against the first opaque background above it.
CONTRAST_JS = """() => {
  const ctx = Object.assign(document.createElement('canvas'), { width: 1, height: 1 }).getContext('2d', { willReadFrequently: true });
  const rgba = s => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillStyle = s; ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = ([r, g, b]) => [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
    .reduce((acc, v, i) => acc + v * [0.2126, 0.7152, 0.0722][i], 0);
  const bg = el => { for (let e = el; e; e = e.parentElement) { const st = getComputedStyle(e);
    if (st.backgroundColor === 'transparent') continue; const c = rgba(st.backgroundColor); if (c[3] > 0.99) return c; }
    return rgba(getComputedStyle(document.documentElement).backgroundColor); };
  const bad = []; let min = 99;
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden') continue;
    const st = getComputedStyle(el); const size = parseFloat(st.fontSize); const bold = parseInt(st.fontWeight) >= 700;
    const a = lum(rgba(st.color)), b = lum(bg(el));
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    min = Math.min(min, ratio);
    const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
    if (ratio < need) bad.push({ text: el.textContent.trim().slice(0, 30), ratio: Math.round(ratio * 100) / 100, need });
  }
  return { bad, min: Math.round(min * 100) / 100 };
}"""
OVERFLOW_JS = """() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth,
  wide: [...document.querySelectorAll('body *')].filter(e => e.getClientRects().length &&
    e.getBoundingClientRect().right > document.documentElement.clientWidth + 0.5)
    .map(e => e.className || e.tagName).slice(0, 5) })"""
SETTLE_JS = "() => [...document.querySelectorAll('[data-hidup]')].every(s => s.dataset.status && s.dataset.status !== 'muat')"
OPEN_JS = "() => { document.querySelectorAll('details').forEach(d => d.open = true); window.scrollTo(0, document.body.scrollHeight); }"
STATUS_JS = "() => [...document.querySelectorAll('[data-hidup]')].map(s => s.dataset.status)"


def url_of(page: str) -> str:
    return page if re.match(r"https?://", page) else Path(page).resolve().as_uri()


def label_of(page: str) -> str:
    tail = re.sub(r"^https?://[^/]+/", "", page) if re.match(r"https?://", page) else Path(page).parent.as_posix()
    return re.sub(r"[^\w]+", "_", tail.replace("index.html", "")).strip("_") or "root"


def check(browser, name: str, context_args: dict, page: str, scheme: str, shots: Path, state: str = "") -> dict:
    context = browser.new_context(**context_args, color_scheme=scheme)
    tab = context.new_page()
    errors: list[str] = []
    tab.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    tab.on("pageerror", lambda e: errors.append(str(e)))
    tab.goto(url_of(page) + (f"?keadaan={state}" if state else ""))
    tab.wait_for_load_state("load")
    live = tab.evaluate("() => document.querySelectorAll('[data-hidup]').length") > 0
    if live:
        tab.wait_for_function(SETTLE_JS, timeout=5000)
    status = tab.evaluate(STATUS_JS)
    overflow = tab.evaluate(OVERFLOW_JS)
    if live:
        tab.evaluate(OPEN_JS)
        opened = tab.evaluate(OVERFLOW_JS)
        if opened["scroll"] > overflow["scroll"] or opened["wide"]:
            overflow = {**opened, "after": "details opened"}
        tab.evaluate("() => window.scrollTo(0, 0)")
    contrast = tab.evaluate(CONTRAST_JS)
    shot = shots / f"{label_of(page)}-{name}-{scheme}{'-' + state if state else ''}.png"
    tab.screenshot(path=str(shot), full_page=True)
    context.close()
    expected = [state or "ada"] * len(status)
    ok = (overflow["scroll"] <= overflow["client"] and not overflow["wide"] and not errors and not contrast["bad"]
          and status == expected)
    return {"page": page, "view": name, "scheme": scheme, "state": state, "ok": ok, "live": status, "overflow": overflow,
            "console_errors": errors, "low_contrast": contrast["bad"], "min_contrast": contrast["min"], "screenshot": shot.name}


def main(argv: list[str]) -> int:
    out, pages = Path(argv[0]), argv[1:]
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        views = []
        chromium, webkit = p.chromium.launch(), p.webkit.launch()
        for key, size in WIDTHS.items():
            views.append((chromium, f"chromium-{key}", {"viewport": size, "device_scale_factor": 2}))
        views.append((webkit, "webkit-iphone13", {**p.devices["iPhone 13"], "device_scale_factor": 3}))
        views.append((webkit, "webkit-w320", {"viewport": WIDTHS["w320"], "device_scale_factor": 3,
                                              "is_mobile": True, "has_touch": True}))
        views.append((webkit, "webkit-desktop", {"viewport": WIDTHS["desktop"], "device_scale_factor": 1}))
        for page in pages:
            for browser, name, args in views:
                for scheme in SCHEMES:
                    results.append(check(browser, name, args, page, scheme, out))
            if "digest" not in page:
                for state in STATES:
                    for browser, name, args in views[2:4]:
                        results.append(check(browser, name, args, page, "dark", out, state))
        chromium.close()
        webkit.close()
    (out / "page-check.json").write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    failed = [r for r in results if not r["ok"]]
    for r in failed:
        print(json.dumps(r))
    print(f"page check: {len(results) - len(failed)}/{len(results)} passed; "
          f"lowest contrast {min(r['min_contrast'] for r in results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
