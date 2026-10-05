"""
Find out what data exists for the theme metrics, before designing them.

The next features measure each company more rigorously: returns over
several periods against its ETF and peers, the market-model abnormal return
on each earnings reaction, the run-up before a report, and a peer table of
valuation, growth, margins and estimate revisions. Each needs a specific
field from Yahoo, and Yahoo's coverage differs company by company -- a
recent spin-off has a short price history, a foreign listing may lack
estimate data. Guessing would mean designing around fields that aren't
there.

    python3 tools/probe_theme_data.py            # every company in your themes
    python3 tools/probe_theme_data.py MU SNDK    # just these
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yfinance as yf

import themes as theme_store

INFO_FIELDS = [
    ("forwardPE", "fwd P/E"),
    ("trailingPE", "trail P/E"),
    ("enterpriseToRevenue", "EV/sales"),
    ("revenueGrowth", "rev growth"),
    ("earningsGrowth", "EPS growth"),
    ("grossMargins", "gross m"),
    ("operatingMargins", "op m"),
    ("profitMargins", "net m"),
    ("beta", "beta"),
    ("numberOfAnalystOpinions", "analysts"),
]


def probe(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    out: dict = {"ticker": ticker}

    try:
        hist = t.history(period="2y")
        out["days"] = len(hist)
        out["first"] = hist.index[0].date().isoformat() if len(hist) else None
    except Exception as exc:
        out["days"], out["first"] = 0, f"ERR {type(exc).__name__}"

    try:
        frame = t.earnings_dates
        if frame is None or frame.empty:
            out["reports"] = "none"
        else:
            import pandas as pd
            now = pd.Timestamp.now(tz=frame.index.tz)
            past = frame[frame.index < now]
            with_surprise = past["Surprise(%)"].notna().sum() if "Surprise(%)" in past else 0
            hours = sorted({s.hour for s in past.index})
            out["reports"] = f"{len(past)} past, {with_surprise} w/ surprise, hours {hours}"
    except Exception as exc:
        out["reports"] = f"ERR {type(exc).__name__}: {str(exc)[:40]}"

    try:
        trend = t.eps_trend
        revisions = t.eps_revisions
        out["eps_trend"] = "yes" if trend is not None and not trend.empty and "0q" in trend.index else "no"
        out["revisions"] = ("yes" if revisions is not None and not revisions.empty
                            and "0q" in revisions.index else "no")
    except Exception as exc:
        out["eps_trend"] = out["revisions"] = f"ERR {type(exc).__name__}"

    try:
        info = t.info or {}
        for key, label in INFO_FIELDS:
            value = info.get(key)
            out[label] = "--" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))
    except Exception as exc:
        for _, label in INFO_FIELDS:
            out[label] = "ERR"

    try:
        out["options"] = len(t.options or [])
    except Exception:
        out["options"] = "ERR"
    try:
        out["news"] = len(t.news or [])
    except Exception:
        out["news"] = "ERR"
    return out


def main() -> None:
    if len(sys.argv) > 1:
        tickers = [a.upper() for a in sys.argv[1:]]
    else:
        state = theme_store.load()
        tickers = theme_store.all_tickers(state) + sorted({t["benchmark"] for t in state["themes"]})

    for ticker in tickers:
        r = probe(ticker)
        print(f"\n{ticker}")
        print(f"  price history : {r['days']} days from {r['first']}")
        print(f"  earnings      : {r['reports']}")
        print(f"  eps trend     : {r['eps_trend']}   revisions: {r['revisions']}")
        print("  info          : " + "  ".join(f"{label}={r[label]}" for _, label in INFO_FIELDS))
        print(f"  options expiries: {r['options']}   news items: {r['news']}")


if __name__ == "__main__":
    main()
