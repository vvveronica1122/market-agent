"""
Market Agent -- web dashboard.

This is a different, complementary pattern from agent.py's chat loop: here
we already know exactly which data every card needs (price, trend, news,
events), so instead of letting Claude decide what to look up, the server
calls all four tools directly and only asks Claude once per ticker, to
turn already-fetched data into a short plain-English summary.

Rule of thumb: use the full "let the model choose tools" agentic loop when
the request is open-ended and you don't know in advance what's needed
(agent.py). Call tools directly and use the LLM only for the parts that
need language when you already know exactly what data you want (this
file). Both are "agents" in the broad sense; this one is just simpler and
faster because the tool-selection problem doesn't exist here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from anthropic import Anthropic

# Make the project root importable so `from tools.market_data import ...`
# works no matter where `python app.py` is run from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.market_data import (
    get_stock_price,
    get_recent_news,
    get_upcoming_events,
    get_price_history,
)

load_dotenv(PROJECT_ROOT / ".env")

app = Flask(__name__, static_folder="static")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-5"

WATCHLIST_FILE = Path(__file__).resolve().parent / "watchlist.json"
DEFAULT_WATCHLIST = ["AAPL", "TSLA", "MSFT"]


def load_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers: list[str]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(tickers, indent=2))


def summarize(ticker: str, data: dict) -> str:
    """Ask Claude for a short narrative from data we've already fetched."""
    have_anything = "price" in data or "news" in data or "events" in data
    if not have_anything:
        return "No data available for this ticker right now."

    prompt = (
        f"Given this data about {ticker}, write a 2-3 sentence plain-English "
        "summary for a dashboard card. Mention the price move and the most "
        "notable news or event if there is one. Don't just restate numbers "
        "that are already shown elsewhere on the card -- focus on what it means.\n\n"
        f"Data:\n{json.dumps(data, indent=2, default=str)}"
    )
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return f"(Could not generate summary: {exc})"


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist_route():
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    body = request.get_json(force=True, silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    watchlist = load_watchlist()
    if ticker not in watchlist:
        watchlist.append(ticker)
        save_watchlist(watchlist)
    return jsonify(watchlist)


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def remove_from_watchlist(ticker: str):
    ticker = ticker.strip().upper()
    watchlist = [t for t in load_watchlist() if t != ticker]
    save_watchlist(watchlist)
    return jsonify(watchlist)


@app.route("/api/analysis/<ticker>")
def analysis(ticker: str):
    ticker = ticker.strip().upper()
    result: dict = {"ticker": ticker}

    try:
        result["price"] = get_stock_price(ticker)
    except Exception as exc:
        result["price_error"] = str(exc)

    try:
        result["history"] = get_price_history(ticker)
    except Exception as exc:
        result["history_error"] = str(exc)

    try:
        result["news"] = get_recent_news(ticker, limit=4)
    except Exception as exc:
        result["news_error"] = str(exc)

    try:
        result["events"] = get_upcoming_events(ticker)
    except Exception as exc:
        result["events_error"] = str(exc)

    result["summary"] = summarize(ticker, result)
    return jsonify(result)


if __name__ == "__main__":
    print("\nMarket Agent dashboard -- open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
