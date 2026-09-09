"""
Quick standalone smoke test for the data tools -- no LLM/API key needed.

Run this after `pip install -r requirements.txt` to confirm the tools can
actually reach Yahoo Finance and parse real data, *before* wiring them up
to the agent. Testing tools in isolation like this is good practice: if
something breaks later, you'll already know the tools themselves are fine
and the bug is in the agent loop instead (or vice versa).

Usage:
    python test_tools.py [TICKER]
"""

import json
import sys

from tools.market_data import get_stock_price, get_recent_news, get_upcoming_events


def main() -> None:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"

    print(f"\n== get_stock_price({ticker!r}) ==")
    print(json.dumps(get_stock_price(ticker), indent=2, default=str))

    print(f"\n== get_recent_news({ticker!r}) ==")
    print(json.dumps(get_recent_news(ticker, limit=3), indent=2, default=str))

    print(f"\n== get_upcoming_events({ticker!r}) ==")
    print(json.dumps(get_upcoming_events(ticker), indent=2, default=str))
    print()


if __name__ == "__main__":
    main()
