"""
Earnings schedule and financial statement tools.

Everything else in this project is reactive -- it tells you what already
happened to a price. Earnings dates are the one thing you can know in
advance, which makes them the most genuinely useful data here: they let
you prepare instead of react.

The quarterly figures answer the follow-up question. A date alone tells
you *when* to pay attention; revenue and margin trends tell you what the
company was doing on the way there.

yfinance returns pandas objects with inconsistent row labels between
companies, so every lookup here is defensive: missing data comes back as
None rather than raising, because a partial picture is still useful.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import yfinance as yf


def _clean(value: Any) -> float | None:
    """pandas NaN, numpy types and None all have to collapse to None/float."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _row(frame, *candidates: str):
    """Find a statement row by any of several possible labels.

    Companies don't all use the same line-item names ("Total Revenue" vs
    "Operating Revenue"), so we try a few and then fall back to a
    case-insensitive contains match.
    """
    if frame is None or getattr(frame, "empty", True):
        return None
    labels = {str(i).lower(): i for i in frame.index}
    for name in candidates:
        key = name.lower()
        if key in labels:
            return frame.loc[labels[key]]
    for name in candidates:
        for lower, original in labels.items():
            if name.lower() in lower:
                return frame.loc[original]
    return None


def get_earnings_schedule(ticker: str) -> dict[str, Any]:
    """Next earnings date, the estimate for it, and how the last one went.

    "How the last one went" matters as much as the date: a company that
    missed last quarter carries different risk into the next print than
    one that beat.
    """
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "next_date": None,
        "days_away": None,
        "eps_estimate": None,
        "last_report": None,
    }

    try:
        frame = yf.Ticker(ticker).earnings_dates
    except Exception:
        frame = None

    if frame is None or getattr(frame, "empty", True):
        return result

    now = datetime.now(timezone.utc)
    try:
        index = frame.index
        upcoming, past = [], []
        for stamp in index:
            when = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            (upcoming if when > now else past).append((when, stamp))
    except Exception:
        return result

    if upcoming:
        when, key = min(upcoming, key=lambda pair: pair[0])
        row = frame.loc[key]
        result["next_date"] = when.date().isoformat()
        result["days_away"] = (when.date() - now.date()).days
        result["eps_estimate"] = _clean(_field(row, "EPS Estimate"))

    if past:
        when, key = max(past, key=lambda pair: pair[0])
        row = frame.loc[key]
        estimate = _clean(_field(row, "EPS Estimate"))
        actual = _clean(_field(row, "Reported EPS"))
        surprise = _clean(_field(row, "Surprise(%)"))
        if surprise is None and estimate not in (None, 0) and actual is not None:
            surprise = (actual - estimate) / abs(estimate) * 100
        result["last_report"] = {
            "date": when.date().isoformat(),
            "eps_estimate": estimate,
            "eps_actual": actual,
            "surprise_percent": round(surprise, 1) if surprise is not None else None,
        }

    return result


def _field(row, name):
    try:
        value = row[name]
    except Exception:
        return None
    # A duplicated index can hand back a Series instead of a scalar.
    if hasattr(value, "iloc"):
        try:
            value = value.iloc[0]
        except Exception:
            return None
    return value


def get_quarterly_results(ticker: str, quarters: int = 6) -> list[dict[str, Any]]:
    """Recent quarterly revenue and net income, oldest first.

    Quarterly rather than annual on purpose -- annual figures hide the
    seasonality that makes a retailer's December look nothing like its
    March.
    """
    try:
        frame = yf.Ticker(ticker).quarterly_income_stmt
    except Exception:
        return []

    if frame is None or getattr(frame, "empty", True):
        return []

    revenue = _row(frame, "Total Revenue", "Operating Revenue", "Revenue")
    income = _row(frame, "Net Income", "Net Income Common Stockholders",
                  "Net Income From Continuing Operation Net Minority Interest")
    if revenue is None:
        return []

    periods = []
    for column in list(frame.columns)[:quarters]:
        rev = _clean(revenue.get(column)) if hasattr(revenue, "get") else None
        net = _clean(income.get(column)) if income is not None and hasattr(income, "get") else None
        if rev is None:
            continue
        label = column.date().isoformat() if hasattr(column, "date") else str(column)[:10]
        periods.append(
            {
                "period": label,
                "revenue": rev,
                "net_income": net,
                "net_margin": round(net / rev * 100, 1) if net is not None and rev else None,
            }
        )

    periods.reverse()  # oldest first, so a chart reads left to right
    return periods


def get_key_stats(ticker: str) -> dict[str, Any]:
    """Headline valuation and profitability figures."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}

    growth = _clean(info.get("revenueGrowth"))
    margin = _clean(info.get("profitMargins"))
    return {
        "market_cap": _clean(info.get("marketCap")),
        "trailing_pe": _clean(info.get("trailingPE")),
        "forward_pe": _clean(info.get("forwardPE")),
        # yfinance returns these as fractions; percent is what gets displayed.
        "profit_margin_percent": round(margin * 100, 1) if margin is not None else None,
        "revenue_growth_percent": round(growth * 100, 1) if growth is not None else None,
        "sector": info.get("sector"),
        "name": info.get("shortName") or info.get("longName"),
    }
