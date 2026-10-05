"""
Screenshots and a walkthrough video of the static demo, taken by a script
so they can be retaken whenever the frontend or the snapshot changes.

    python3 demo/capture.py                 # screenshots into docs/images/
    python3 demo/capture.py --video         # also the walkthrough, into demo/media/

It serves demo/site/ itself (build it first with demo/build.py) and drives
a browser through Playwright, which is not a project dependency -- install
it wherever you run this (pip install playwright). It uses Playwright's own
headless Chromium if installed, else your Google Chrome; with Chrome's
headless mode the video lost its bottom 87 pixels to a grey band, so the
former is preferred. Screenshots are reduced to 256 colours when Pillow is
available (a third of the size, no visible change for a UI). The video is
WebM; Playwright draws no mouse pointer, so the page gets one injected.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import shutil
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "demo" / "site"
IMAGES = ROOT / "docs" / "images"
MEDIA = ROOT / "demo" / "media"

DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}

# (file name, hash route, what to do before the shot)
SHOTS = [
    ("home", "#/", None),
    ("theme-today", "#/theme/memory-storage", None),
    ("theme-performance", "#/theme/memory-storage/performance", None),
    ("theme-earnings", "#/theme/ai-compute/earnings", None),
    ("theme-peers", "#/theme/memory-storage/peers", None),
    ("stock-overview", "#/stock/MU", None),
    ("stock-earnings", "#/stock/MU/earnings", None),
    ("discover", "#/discover", None),
    ("ask", "#/ask", "ask"),
]

# Shown as a dot that follows the mouse, with a ring on each click.
POINTER_JS = """
(() => {
  if (window.__pointer) return;
  const dot = document.createElement('div');
  dot.style.cssText = 'position:fixed;z-index:99999;width:18px;height:18px;margin:-9px 0 0 -9px;' +
    'border-radius:50%;background:rgba(43,33,36,.55);border:2px solid #fff;pointer-events:none;' +
    'left:-40px;top:-40px;transition:transform .12s';
  document.documentElement.appendChild(dot);
  window.__pointer = dot;
  addEventListener('mousemove', e => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => { dot.style.transform = 'scale(.7)'; }, true);
  addEventListener('mouseup', () => { dot.style.transform = ''; }, true);
})();
"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def shrink(path: Path) -> None:
    """256-colour PNG: UI screenshots have few colours, so this is lossless
    to the eye and about a third of the size."""
    try:
        from PIL import Image
    except ImportError:
        return
    image = Image.open(path).convert("RGB")
    image.quantize(colors=256, method=Image.MEDIANCUT, dither=Image.NONE).save(path, optimize=True)


def serve(directory: Path) -> tuple[socketserver.TCPServer, str]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def settle(page) -> None:
    """Wait until the view has rendered: no loading text, no requests in flight."""
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => !document.querySelector('.loading-text')", timeout=15000)
    page.wait_for_timeout(400)


def ask_first_question(page) -> None:
    """The first recorded question, its lookups open, scrolled so the
    answer shows under them."""
    page.click(".starter")
    page.wait_for_selector(".assistant-turn")
    page.click(".trace summary")
    page.evaluate("document.querySelector('.assistant-turn .bubble.agent')"
                  ".scrollIntoView({block: 'end'})")
    page.wait_for_timeout(300)


def screenshots(browser, base: str, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    context = browser.new_context(viewport=DESKTOP, device_scale_factor=2)
    page = context.new_page()
    for name, route, action in SHOTS:
        page.goto(base + route)
        settle(page)
        if action == "ask":
            ask_first_question(page)
        path = out / f"{name}.png"
        page.screenshot(path=str(path))
        shrink(path)
        written.append(path)
        print(f"  {path.relative_to(ROOT)}")
    context.close()

    context = browser.new_context(viewport=MOBILE, device_scale_factor=3, is_mobile=True, has_touch=True)
    page = context.new_page()
    for name, route in [("mobile-home", "#/"), ("mobile-stock", "#/stock/MU")]:
        page.goto(base + route)
        settle(page)
        path = out / f"{name}.png"
        page.screenshot(path=str(path))
        shrink(path)
        written.append(path)
        print(f"  {path.relative_to(ROOT)}")
    context.close()
    return written


def walkthrough(browser, base: str, out: Path) -> Path:
    """About a minute: home and the brief, a theme's tabs, a company, Ask."""
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    context = browser.new_context(viewport=DESKTOP, record_video_dir=str(raw), record_video_size=DESKTOP)
    context.add_init_script(POINTER_JS)
    page = context.new_page()
    mouse = page.mouse

    def glide(selector: str, index: int = 0) -> None:
        box = page.locator(selector).nth(index).bounding_box()
        mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=25)
        page.wait_for_timeout(250)

    def click(selector: str, index: int = 0) -> None:
        glide(selector, index)
        page.locator(selector).nth(index).click()
        settle(page)

    def scroll(pixels: int, pause: int = 900) -> None:
        for _ in range(abs(pixels) // 60):
            mouse.wheel(0, 60 if pixels > 0 else -60)
            page.wait_for_timeout(30)
        page.wait_for_timeout(pause)

    page.goto(base + "#/")
    settle(page)
    mouse.move(720, 450)
    page.wait_for_timeout(1800)
    scroll(500, 1600)                                 # the brief, then the theme cards
    scroll(600, 1600)
    scroll(-1100, 600)

    click('.nav-themes a[href="#/theme/memory-storage"]')
    page.wait_for_timeout(1800)
    scroll(400, 1400)
    scroll(-400, 400)
    for tab in ("performance", "earnings", "peers"):
        click(f'.tabs a[href="#/theme/memory-storage/{tab}"]')
        page.wait_for_timeout(1500)
        scroll(450, 1300)
        scroll(-450, 300)

    page.goto(base + "#/theme/memory-storage")
    settle(page)
    click('.theme-row[aria-label^="MU,"]')
    page.wait_for_timeout(1500)
    scroll(500, 1500)
    scroll(-500, 300)
    click('.tabs a[href="#/stock/MU/earnings"]')
    page.wait_for_timeout(1300)
    scroll(500, 1500)
    scroll(-500, 300)

    click('.nav-item[href="#/ask"]')
    page.wait_for_timeout(900)
    click(".starter")
    page.wait_for_timeout(1200)
    click(".trace summary")
    page.wait_for_timeout(1500)
    glide(".assistant-turn .bubble.agent")
    page.wait_for_timeout(2500)

    video = page.video.path()
    context.close()
    final = out / "walkthrough.webm"
    shutil.move(video, final)
    shutil.rmtree(raw, ignore_errors=True)
    print(f"  {final.relative_to(ROOT)}")
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", action="store_true", help="also record the walkthrough")
    parser.add_argument("--only-video", action="store_true", help="the walkthrough, no screenshots")
    args = parser.parse_args()
    if not (SITE / "demo-config.js").exists():
        print("No demo build in demo/site -- run demo/build.py first.")
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Needs Playwright: pip install playwright (it drives your installed Chrome).")
        return 1

    server, base = serve(SITE)
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                browser = p.chromium.launch(channel="chrome")
            if not args.only_video:
                print("screenshots:")
                screenshots(browser, base, IMAGES)
            if args.video or args.only_video:
                print("walkthrough:")
                walkthrough(browser, base, MEDIA)
            browser.close()
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
