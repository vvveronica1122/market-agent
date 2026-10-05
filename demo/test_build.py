"""
Tests for the static demo build. Free, offline, instant.

Runs the real exporter against the dashboard tests' fake market data and
fake model, then checks the folder it writes is complete and self-contained:
every page the frontend asks for has a file, every file is valid JSON, and
the HTML loads its assets by relative path with the demo switch in front.

    python3 demo/test_build.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_app as fixtures  # the dashboard tests' fakes  # noqa: E402
import build  # noqa: E402

server = fixtures.server


class _FakeAgent:
    """Stands in for agent.py: answers and records one lookup."""

    @staticmethod
    def ask_agent(client, question, verbose=False, history=None, trace=None):
        if trace is not None:
            trace.append({"step": 1, "tool": "get_watchlist", "input": {}})
        return f"Recorded answer to: {question}"


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    failures = 0
    fixtures.install_stubs()
    server.client = fixtures.FakeClient()
    real_agent = server.conversational_agent
    server.conversational_agent = _FakeAgent
    out = Path(tempfile.mkdtemp()) / "site"
    try:
        summary = build.build(out, questions=["Which reports soonest?"], log=lambda *_: None)
    finally:
        server.conversational_agent = real_agent

    print("\nWhat the build writes")
    data = out / "data"
    for name in ["overview", "themes", "home", "brief", "earnings", "discover",
                 "theme/chips", "theme/chips/performance", "theme/chips/earnings",
                 "theme/chips/peers", "theme/other", "stock/CRASH", "search/CRASH"]:
        failures += not check(f"data/{name}.json exists", (data / f"{name}.json").exists())
    failures += not check("a stock page for every company in a theme and on Discover",
                          all((data / f"stock/{t}.json").exists()
                              for t in ["CRASH", "PEER1", "PEER2", "QUIET", "SOLO", "CALM", "SURGE"]))
    bad = []
    for path in data.rglob("*.json"):
        try:
            json.loads(path.read_text())
        except json.JSONDecodeError:
            bad.append(path.name)
    failures += not check("every data file is valid JSON", not bad, str(bad))
    failures += not check("the summary counts what was written",
                          summary["files"] == len(list(data.rglob("*.json"))), str(summary))

    print("\nThe page that serves it")
    html = (out / "index.html").read_text()
    failures += not check("assets load by relative path, so any address works",
                          'href="style.css"' in html and 'src="app.js"' in html and "/static/" not in html)
    failures += not check("the demo switch loads before the app",
                          html.index("demo-config.js") < html.index('src="app.js"'))
    failures += not check("the app and styles are copied beside it",
                          (out / "app.js").exists() and (out / "style.css").exists())

    print("\nThe demo switch")
    config_js = (out / "demo-config.js").read_text()
    config = json.loads(config_js.split("window.MARKET_AGENT_DEMO = ", 1)[1].rstrip().rstrip(";"))
    failures += not check("it records which session the snapshot is of",
                          config["snapshot_session"] == "2026-09-10", str(config["snapshot_session"]))
    failures += not check("Ask's recorded conversations keep the answer and the lookups",
                          config["chat"] == [{"question": "Which reports soonest?",
                                              "answer": "Recorded answer to: Which reports soonest?",
                                              "trace": [{"step": 1, "tool": "get_watchlist", "input": {}}]}],
                          str(config["chat"]))
    failures += not check("it says which model wrote the AI text", bool(config.get("model")))

    print("\nThe frontend reads it")
    app_js = (out / "app.js").read_text()
    failures += not check("app.js maps requests to the captured files",
                          "window.MARKET_AGENT_DEMO" in app_js and "data/${path}.json" in app_js)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
