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
available (a third of the size, no visible change for a UI).

The video is rendered frame by frame rather than screen-recorded:
Playwright's recorder captured frames mid-repaint, so scrolling showed
stale strips of the previous position over the new one, which read as a
shake. Here each frame is a screenshot taken once the page has painted,
the scroll and the pointer move a fixed step per frame, and the frames are
encoded at 25 per second: WebM with Playwright's bundled ffmpeg, MP4 with
demo/frames_to_mp4.swift on macOS. Playwright draws no mouse pointer, so
the page gets one injected.
"""

from __future__ import annotations

import argparse
import functools
import glob
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
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


FPS = 25


def ease(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


class Frames:
    """A video built one finished frame at a time."""

    def __init__(self, page, folder: Path):
        self.page, self.folder, self.count = page, folder, 0
        self.pointer = (720.0, 450.0)
        self.last: bytes | None = None

    def _write(self, data: bytes) -> None:
        self.count += 1
        (self.folder / f"{self.count:05d}.jpg").write_bytes(data)
        self.last = data

    def shot(self) -> None:
        self._write(self.page.screenshot(type="jpeg", quality=92))

    def hold(self, seconds: float) -> None:
        if self.last is None:
            self.shot()
        for _ in range(round(seconds * FPS)):
            self._write(self.last)

    def scroll(self, dy: int, seconds: float = 1.1) -> None:
        start = self.page.evaluate("window.scrollY")
        steps = round(seconds * FPS)
        for i in range(1, steps + 1):
            self.page.evaluate(f"window.scrollTo(0, {start + dy * ease(i / steps):.1f})")
            self.shot()

    def glide(self, selector: str, seconds: float = 0.6) -> None:
        box = self.page.locator(selector).first.bounding_box()
        target = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        x0, y0 = self.pointer
        steps = round(seconds * FPS)
        for i in range(1, steps + 1):
            t = ease(i / steps)
            self.pointer = (x0 + (target[0] - x0) * t, y0 + (target[1] - y0) * t)
            self.page.mouse.move(*self.pointer)
            self.shot()

    def click(self, selector: str) -> None:
        self.glide(selector)
        self.page.mouse.down()
        self.hold(0.12)
        self.page.mouse.up()             # the click itself, where the pointer is
        settle(self.page)
        self.page.mouse.move(*self.pointer)
        self.shot()


def encode(frames: Path, out: Path) -> list[Path]:
    """WebM through Playwright's ffmpeg, MP4 through AVFoundation, and the
    first frame as a poster -- whichever tools this machine has."""
    written = []
    files = sorted(frames.glob("*.jpg"))
    ffmpeg = sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/ffmpeg-*/ffmpeg-*"))
                    + glob.glob(os.path.expanduser("~/.cache/ms-playwright/ffmpeg-*/ffmpeg-*")))
    if ffmpeg:
        webm = out / "walkthrough.webm"
        proc = subprocess.Popen([ffmpeg[-1], "-y", "-loglevel", "error", "-f", "image2pipe",
                                 "-c:v", "mjpeg", "-r", str(FPS), "-i", "pipe:0", "-c:v", "libvpx",
                                 "-b:v", "1500k", "-qmin", "2", "-qmax", "30", str(webm)],
                                stdin=subprocess.PIPE)
        for f in files:
            proc.stdin.write(f.read_bytes())
        proc.stdin.close()
        if proc.wait() == 0:
            written.append(webm)
    if shutil.which("swift"):
        mp4 = out / "walkthrough.mp4"
        result = subprocess.run(["swift", str(ROOT / "demo" / "frames_to_mp4.swift"), str(frames),
                                 str(mp4), str(FPS), "1200000"], capture_output=True, text=True)
        if result.returncode == 0:
            written.append(mp4)
        else:
            print(result.stderr[-400:])
    poster = out / "walkthrough-poster.png"
    try:
        from PIL import Image
        Image.open(files[0]).convert("RGB").save(poster, optimize=True)
        shrink(poster)
        written.append(poster)
    except ImportError:
        pass
    return written


def walkthrough(browser, base: str, out: Path) -> list[Path]:
    """About a minute: home and the brief, a theme's tabs, a company, Ask."""
    out.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport=DESKTOP)
    context.add_init_script(POINTER_JS)
    page = context.new_page()
    folder = Path(tempfile.mkdtemp(prefix="walkthrough-"))
    v = Frames(page, folder)

    page.goto(base + "#/")
    settle(page)
    page.mouse.move(*v.pointer)
    v.shot()
    v.hold(1.8)
    v.scroll(500); v.hold(1.6)                       # the brief, then the theme cards
    v.scroll(600); v.hold(1.6)
    v.scroll(-1100, 1.0); v.hold(0.4)

    v.click('.nav-themes a[href="#/theme/memory-storage"]')
    v.hold(1.8)
    v.scroll(400); v.hold(1.4)
    v.scroll(-400, 0.8); v.hold(0.3)
    for tab in ("performance", "earnings", "peers"):
        v.click(f'.tabs a[href="#/theme/memory-storage/{tab}"]')
        v.hold(1.5)
        v.scroll(450); v.hold(1.3)
        v.scroll(-450, 0.8); v.hold(0.3)

    v.click('.tabs a[href="#/theme/memory-storage"]')
    v.hold(0.6)
    v.click('.theme-row[aria-label^="MU,"]')
    v.hold(1.5)
    v.scroll(500); v.hold(1.5)
    v.scroll(-500, 0.8); v.hold(0.3)
    v.click('.tabs a[href="#/stock/MU/earnings"]')
    v.hold(1.3)
    v.scroll(500); v.hold(1.5)
    v.scroll(-500, 0.8); v.hold(0.3)

    v.click('.nav-item[href="#/ask"]')
    v.hold(0.9)
    v.click(".starter")
    v.hold(1.2)
    v.click(".trace summary")
    v.hold(1.0)
    v.glide(".assistant-turn .bubble.agent")
    v.hold(3.0)
    context.close()

    written = encode(folder, out)
    shutil.rmtree(folder, ignore_errors=True)
    for path in written:
        print(f"  {path.relative_to(ROOT)}")
    print(f"  ({v.count} frames, {v.count / FPS:.0f} seconds)")
    return written


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
