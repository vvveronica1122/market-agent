"""
Find out what evidence exists for describing an earnings setup.

The question "will it go up or down" is unanswerable. The question
"what does the setup look like, and what would count as a surprise" is
answerable -- but only from data we actually have, so check first.

Four things worth having, in rough order of usefulness:

  1. How the stock ACTUALLY moved after each of its past earnings. The
     hardest evidence available: if a name routinely swings 8% on the
     print, that is a fact about it, not a forecast.
  2. Whether it has been beating or missing, and by how much.
  3. Whether analysts have been raising or cutting estimates into the
     print.
  4. Which way revenue and margin have been trending.

    python3 tools/probe_earnings_setup.py MU
"""

from __future__ import annotations

import sys
from datetime import timedelta

import yfinance as yf


def section(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def probe(ticker: str) -> int:
    t = yf.Ticker(ticker)

    section(f"1. Past earnings dates and surprises -- {ticker}")
    try:
        frame = t.earnings_dates
        if frame is None or frame.empty:
            print("  earnings_dates: EMPTY (this is the endpoint that failed before)")
        else:
            print(f"  columns: {list(frame.columns)}")
            print(f"  {len(frame)} rows\n")
            print(frame.head(10).to_string())
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    section("2. Can we compute the move AFTER each past earnings?")
    try:
        history = t.history(period="2y")
        print(f"  price history rows: {len(history)}")
        frame = t.earnings_dates
        if frame is not None and not frame.empty and len(history):
            import pandas as pd
            past = [d for d in frame.index if d.tz_localize(None) if True]
            shown = 0
            for stamp in list(frame.index):
                day = stamp.tz_localize(None).normalize() if stamp.tzinfo else stamp.normalize()
                after = history.loc[history.index.tz_localize(None) > day]
                before = history.loc[history.index.tz_localize(None) <= day]
                if len(after) and len(before):
                    move = (after["Close"].iloc[0] - before["Close"].iloc[-1]) / before["Close"].iloc[-1] * 100
                    print(f"  {day.date()}  next-session move: {move:+.2f}%")
                    shown += 1
                if shown >= 8:
                    break
            if not shown:
                print("  could not line up any earnings date with price data")
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")

    section("3. Analyst estimate trend and revisions")
    for name in ("eps_trend", "eps_revisions", "earnings_estimate", "revenue_estimate",
                 "growth_estimates"):
        try:
            value = getattr(t, name)
            if value is None or (hasattr(value, "empty") and value.empty):
                print(f"  {name}: EMPTY")
            else:
                print(f"\n  {name}:")
                print("    " + value.to_string().replace("\n", "\n    ")[:900])
        except Exception as exc:
            print(f"  {name}: FAILED ({type(exc).__name__}: {exc})")

    print("\n" + "=" * 68)
    print("Anything marked EMPTY or FAILED cannot be built on.")
    print("=" * 68 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(probe(sys.argv[1] if len(sys.argv) > 1 else "MU"))
