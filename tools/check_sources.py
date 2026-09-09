"""
Check which live data sources actually work from this machine.

Network access differs by machine and network -- a corporate or campus
network may block some of these. Run this before debugging the app itself,
so you know whether a problem is your code or your connection:

    python3 tools/check_sources.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def timed(label, fn):
    start = time.time()
    try:
        result = fn()
        elapsed = time.time() - start
        print(f"  [OK]   {label}  ({elapsed:.1f}s)")
        return result
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  [FAIL] {label}  ({elapsed:.1f}s)")
        print(f"         {type(exc).__name__}: {str(exc)[:160]}")
        return None


def main() -> int:
    print("\nChecking live data sources...\n")

    from tools.market_data import get_stock_price, get_recent_news, get_upcoming_events
    from tools.market_scan import get_market_movers, get_market_news, filter_quality

    price = timed("single quote (AAPL)", lambda: get_stock_price("AAPL"))
    if price:
        print(f"         AAPL ${price['price']} ({price['change_percent']:+}%)")

    news = timed("per-ticker news (AAPL)", lambda: get_recent_news("AAPL", limit=3))
    if news:
        print(f"         {len(news)} headlines, e.g. {news[0]['title'][:70]}")

    timed("earnings calendar (AAPL)", lambda: get_upcoming_events("AAPL"))

    from tools.fundamentals import get_earnings_schedule, get_quarterly_results

    sched = timed("earnings schedule (AAPL)", lambda: get_earnings_schedule("AAPL"))
    if sched:
        if sched.get("next_date"):
            print(f"         next {sched['next_date']} (in {sched['days_away']}d) "
                  f"via {sched['source']}")
            if sched["source"] == "calendar":
                print("         note: the richer earnings_dates endpoint gave nothing,")
                print("         so EPS estimates and last-quarter surprise may be missing.")
        else:
            print("         NO DATE FOUND -- the Earnings page will be empty for this ticker.")

    quarters = timed("quarterly financials (AAPL)", lambda: get_quarterly_results("AAPL"))
    if quarters:
        print(f"         {len(quarters)} quarters, latest {quarters[-1]['period']} "
              f"revenue {quarters[-1]['revenue']:,.0f}")

    movers = timed("market-wide screener", get_market_movers)
    if movers:
        clean = filter_quality(movers)
        print(f"         {len(movers)} names scanned, {len(clean)} pass the quality filter")
        top = sorted(clean, key=lambda m: abs(m.get("change_percent") or 0), reverse=True)[:3]
        for m in top:
            print(f"         {m['ticker']:<6} {m.get('change_percent', 0):+.1f}%  {str(m.get('name'))[:40]}")
    elif movers == []:
        print("         Screener returned nothing -- Discover will use its fallback list.")

    headlines = timed("broad market news search", get_market_news)
    if headlines:
        print(f"         {len(headlines)} headlines, e.g. {headlines[0]['title'][:70]}")

    print("\nIf the screener failed but single quotes worked, Discover still")
    print("works -- it falls back to a fixed list of large caps.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
