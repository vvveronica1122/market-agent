"""
Build the static demo: the dashboard with every page's data captured once.

Running the real app publicly would mean paying for every visitor's AI
calls, inviting abuse of the key, and being rate-limited by Yahoo from a
cloud server. Instead this walks the live app once -- real data, real
model -- saves each API response as a JSON file, and copies the frontend
beside them. The frontend notices demo-config.js and reads those files
instead of calling a server. The result is a folder any static host can
serve: no server, no key, nothing fetched at view time.

What's captured: the overview, themes, home, brief, earnings calendar and
Discover; each theme's four tabs; the stock page for every company in a
theme or on Discover; search for those tickers; and the Ask panel's
suggested questions, answered by the real agent with its tool calls.

    python3 demo/build.py                      # writes demo/site/
    python3 demo/build.py --out /tmp/demo      # somewhere else
    python3 demo/build.py --repo-url https://github.com/you/market-agent
    python3 demo/build.py --assets-only        # refresh the frontend, keep the data

It needs ANTHROPIC_API_KEY (the brief, the analyses and the agent are real
model output) and network access to Yahoo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import app as server  # noqa: E402

STATIC = ROOT / "web" / "static"
DEFAULT_OUT = Path(__file__).resolve().parent / "site"

QUESTIONS = [
    "Which of my stocks reports soonest, and how did they do last quarter?",
    "What moved most in the market today that isn't on my watchlist?",
    "Compare the profit margins of the companies in my Memory & storage theme.",
]


class CaptureError(RuntimeError):
    pass


def build(out: Path = DEFAULT_OUT, questions: list[str] = QUESTIONS,
          repo_url: str | None = None, log=print) -> dict:
    """Capture everything into `out`. Returns a summary of what was written."""
    client = server.app.test_client()
    if out.exists():
        shutil.rmtree(out)
    data_dir = out / "data"
    data_dir.mkdir(parents=True)
    written: list[str] = []

    def save(name: str, payload) -> None:
        path = data_dir / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, separators=(",", ":"), default=str))
        written.append(name)

    def get(url: str):
        res = client.get(url)
        if res.status_code != 200:
            raise CaptureError(f"{url} returned {res.status_code}: {res.get_data(as_text=True)[:200]}")
        payload = res.get_json()
        save(url[len("/api/"):].split("?")[0], payload)
        return payload

    log("capturing overview, themes, home, brief, earnings, discover...")
    overview = get("/api/overview")
    themes = get("/api/themes")
    get("/api/home")
    get("/api/brief")
    get("/api/earnings")
    discover = get("/api/discover")

    for theme in themes["themes"]:
        log(f"capturing theme {theme['id']}...")
        base = f"/api/theme/{theme['id']}"
        get(base)
        for tab in ("performance", "earnings", "peers"):
            get(f"{base}/{tab}")

    # Every company a page links to: theme members first, then Discover.
    tickers: list[str] = []
    for theme in themes["themes"]:
        for stock in theme["stocks"]:
            if stock["ticker"] not in tickers:
                tickers.append(stock["ticker"])
    for row in discover.get("rows", []):
        if row["ticker"] not in tickers:
            tickers.append(row["ticker"])

    for ticker in tickers:
        log(f"capturing stock {ticker}...")
        get(f"/api/stock/{ticker}")
        res = client.get(f"/api/search?q={ticker}")
        save(f"search/{ticker}", res.get_json())

    chats = []
    for question in questions:
        log(f"asking the agent: {question}")
        res = client.post("/api/chat", json={"message": question, "history": []})
        body = res.get_json() or {}
        if res.status_code == 200 and body.get("answer"):
            chats.append({"question": question, "answer": body["answer"],
                          "trace": body.get("trace", [])})
        else:
            log(f"  skipped: {body.get('error', res.status_code)}")

    captured = datetime.now(ZoneInfo("America/New_York"))
    config = {
        "snapshot_session": overview.get("last_session"),
        "captured_at": captured.isoformat(timespec="minutes"),
        "captured_label": captured.strftime("%a, %b %-d, %Y"),
        "model": server.MODEL,
        "repo_url": repo_url,
        "chat": chats,
    }
    (out / "demo-config.js").write_text(
        "// Written by demo/build.py. Its presence switches the app into the static demo.\n"
        "window.MARKET_AGENT_DEMO = " + json.dumps(config, indent=1) + ";\n")

    copy_assets(out)

    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    summary = {"files": len(written), "stocks": len(tickers), "chats": len(chats),
               "bytes": size, "session": config["snapshot_session"]}
    log(f"done: {summary}")
    return summary


def copy_assets(out: Path) -> None:
    """The frontend files, rewritten to load by relative path. Separate from
    the capture so a frontend fix doesn't need a new snapshot (or new model
    calls)."""
    shutil.copy(STATIC / "app.js", out / "app.js")
    shutil.copy(STATIC / "style.css", out / "style.css")
    html = (STATIC / "index.html").read_text()
    # Relative paths, so the folder works at any address -- a domain root or
    # a subpath like /projects/market-agent/demo/.
    html = html.replace('href="/static/style.css"', 'href="style.css"')
    html = html.replace('<script src="/static/app.js"></script>',
                        '<script src="demo-config.js"></script>\n  <script src="app.js"></script>')
    html = html.replace("<title>Market Agent</title>", "<title>Market Agent · demo</title>")
    if "/static/" in html:
        raise CaptureError("index.html still references /static/; the demo couldn't load its assets")
    (out / "index.html").write_text(html)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--repo-url", help="link shown in the demo banner")
    parser.add_argument("--assets-only", action="store_true",
                        help="copy the current frontend into an existing build; no capture")
    args = parser.parse_args()
    if args.assets_only:
        if not (args.out / "demo-config.js").exists():
            print(f"No demo build in {args.out} to refresh -- run without --assets-only first.")
            return 1
        copy_assets(args.out)
        print(f"frontend refreshed in {args.out}")
        return 0
    if not server.os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY -- the demo's AI text is real model output.")
        return 1
    try:
        build(args.out, repo_url=args.repo_url)
    except CaptureError as exc:
        print(f"capture failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
