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

from tools import performance


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

    Two sources, deliberately. `earnings_dates` is richer -- it carries the
    EPS estimate and the last quarter's surprise -- but it hits a Yahoo
    endpoint that is frequently unavailable. `calendar` is plainer but far
    more reliable.

    So: try the rich one, and if it yields no future date, fall back to the
    reliable one. The `source` field records which answered, because "the
    date is missing" and "the rich endpoint is down" need different fixes
    and you can't tell them apart otherwise.
    """
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "next_date": None,
        "days_away": None,
        "eps_estimate": None,
        "last_report": None,
        "source": None,
        "unavailable_reason": None,
    }

    _from_earnings_dates(ticker, result)
    if result["next_date"] is None:
        _from_calendar(ticker, result)

    if result["next_date"]:
        try:
            when = datetime.fromisoformat(result["next_date"]).date()
            # The same "today" as the rest of the app (days_until_earnings):
            # the local date. UTC's rolled over at 8 PM New York time, so
            # every evening the calendar counted a report a day closer than
            # the dashboard and the brief did.
            result["days_away"] = (when - datetime.now().date()).days
        except ValueError:
            result["days_away"] = None

    return result


def _from_earnings_dates(ticker: str, result: dict) -> None:
    """Rich source: estimate plus last quarter's surprise."""
    try:
        frame = yf.Ticker(ticker).earnings_dates
    except ImportError as exc:
        # Distinct on purpose. "The endpoint is down" and "you are missing
        # a package" produce the same empty page but need opposite fixes,
        # and this project has already lost time to that confusion once.
        result["unavailable_reason"] = f"missing dependency: {exc}"
        return
    except Exception as exc:
        result["unavailable_reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return
    if frame is None or getattr(frame, "empty", True):
        return

    now = datetime.now(timezone.utc)
    upcoming, past = [], []
    try:
        for stamp in frame.index:
            when = stamp.to_pydatetime() if hasattr(stamp, "to_pydatetime") else stamp
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            (upcoming if when > now else past).append((when, stamp))
    except Exception:
        return

    if upcoming:
        when, key = min(upcoming, key=lambda pair: pair[0])
        result["next_date"] = when.date().isoformat()
        result["eps_estimate"] = _clean(_field(frame.loc[key], "EPS Estimate"))
        result["source"] = "earnings_dates"

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


def _from_calendar(ticker: str, result: dict) -> None:
    """Reliable fallback: the plain calendar, which is what the rest of the
    app has been using successfully all along."""
    try:
        calendar = yf.Ticker(ticker).calendar
    except Exception:
        return
    if not isinstance(calendar, dict):
        return

    value = calendar.get("Earnings Date")
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return

    text = str(value)[:10]
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return

    result["next_date"] = text
    result["source"] = "calendar"

    estimate = calendar.get("Earnings Average")
    if result["eps_estimate"] is None and estimate is not None:
        result["eps_estimate"] = _clean(estimate)


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


def _percent(value) -> float | None:
    """yfinance gives margins and growth as fractions; pages show percent."""
    number = _clean(value)
    return round(number * 100, 1) if number is not None else None


def figure_caveats(stats: dict) -> list[str]:
    """Plain-language warnings for figures that would mislead on their own.

    They travel with the figures: the peer table shows them as footnotes,
    and the agent receives them in get_key_stats' result. Before that, the
    agent ranked WDC first on a 72.9% net margin -- above its 48.9% gross
    margin, which only one-off gains can produce -- without a word of
    warning, while the dashboard's peer table flagged the same figure.
    """
    caveats = []
    net, gross = stats.get("profit_margin_percent"), stats.get("gross_margin_percent")
    if net is not None and gross is not None and net > gross:
        caveats.append("Net margin is above gross margin, so the last twelve months include "
                       "one-off gains; net margin overstates the business.")
    operating = stats.get("operating_margin_percent")
    if operating is not None and gross is not None and operating > gross:
        caveats.append("Operating margin (latest quarter) is above gross margin (last twelve "
                       "months): margins rose fast enough that the two periods disagree.")
    fpe = stats.get("forward_pe")
    if fpe is not None and (fpe <= 0 or fpe > 100):
        caveats.append("Forward P/E is above 100 or negative: expected earnings are too small "
                       "for P/E to compare usefully with peers.")
    growth = stats.get("revenue_growth_percent")
    if growth is not None and growth > 100:
        caveats.append("Revenue more than doubled from a year earlier; growth rates this large "
                       "say as much about the starting point as the trend.")
    return caveats


def get_key_stats(ticker: str) -> dict[str, Any]:
    """Headline valuation, growth and profitability figures.

    All from Yahoo's summary: gross and net margins are trailing twelve
    months, but the operating margin is the most recent quarter -- checked
    against the quarterly statements, where SNDK's 78.5% matched its latest
    quarter, not the 61.6% of its last four. Revenue and earnings growth are
    the latest quarter against the same quarter a year earlier, forward P/E
    is on next fiscal year's consensus EPS, and beta is Yahoo's (five years
    of monthly returns against the S&P 500).
    """
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}

    stats = {
        "market_cap": _clean(info.get("marketCap")),
        "trailing_pe": _clean(info.get("trailingPE")),
        "forward_pe": _clean(info.get("forwardPE")),
        "ev_to_sales": _clean(info.get("enterpriseToRevenue")),
        "profit_margin_percent": _percent(info.get("profitMargins")),
        "gross_margin_percent": _percent(info.get("grossMargins")),
        "operating_margin_percent": _percent(info.get("operatingMargins")),
        "revenue_growth_percent": _percent(info.get("revenueGrowth")),
        "earnings_growth_percent": _percent(info.get("earningsGrowth")),
        "beta": _clean(info.get("beta")),
        "analysts": _clean(info.get("numberOfAnalystOpinions")),
        "sector": info.get("sector"),
        "name": info.get("shortName") or info.get("longName"),
    }
    stats["caveats"] = figure_caveats(stats)
    return stats


def get_estimate_revisions(ticker: str) -> dict[str, Any]:
    """How analysts' EPS estimate for next fiscal year has moved.

    Next fiscal year rather than this quarter because it's what forward P/E
    is built on, so it's the estimate valuation hinges on. Percent changes
    are withheld when the old estimate is zero or negative -- "up 300% from
    -$0.10" describes the base, not the revision.
    """
    out: dict[str, Any] = {"period": "next fiscal year", "current": None,
                           "change_30d_percent": None, "change_90d_percent": None,
                           "up_30d": None, "down_30d": None}
    stock = yf.Ticker(ticker)
    try:
        trend = stock.eps_trend
        if trend is not None and not trend.empty and "+1y" in trend.index:
            row = trend.loc["+1y"]
            current = _clean(row.get("current"))
            out["current"] = current
            for key, column in (("change_30d_percent", "30daysAgo"), ("change_90d_percent", "90daysAgo")):
                base = _clean(row.get(column))
                if current is not None and base is not None and base > 0:
                    out[key] = round((current / base - 1) * 100, 1)
    except Exception:
        pass
    try:
        revisions = stock.eps_revisions
        if revisions is not None and not revisions.empty and "+1y" in revisions.index:
            row = revisions.loc["+1y"]
            out["up_30d"] = _clean(row.get("upLast30days"))
            out["down_30d"] = _clean(row.get("downLast30days"))
    except Exception:
        pass
    return out


def get_earnings_setup(ticker: str, events: int = 8, market_history=None) -> dict[str, Any]:
    """What the evidence says about how this stock handles earnings.

    Nothing here predicts the next move -- that isn't knowable. It answers
    the answerable question instead: what has actually happened around
    this company's past reports, and where are expectations set going into
    the next one.

    Each reaction records exactly what was compared -- `from_close`,
    `to_close`, and whether the report landed before the open or after the
    close -- because "the stock moved 15%" is meaningless without knowing
    between which two prices.

    The most useful field is `beat_but_fell`. Markets trade the result
    against what was already priced in, not against the analyst number, so
    a company can beat every quarter and still fall half the time. When
    that is true of a stock, "will it rise if they beat?" has a documented
    answer for that name, and it is "not reliably".

    Each reaction also carries its ABNORMAL return (tools/performance.py):
    the move minus what the stock's market model predicted for that
    session, given what SPY did. A 6% rise on a day the market rose 3%
    wasn't a 6% reaction to the report. `standardized` says how unusual
    the reaction was against the stock's ordinary daily noise, and
    `runup_abnormal` how much the stock had moved, beyond the market, in
    the 20 sessions before the report. `market_history` lets a caller
    share one SPY download across many companies; without it, SPY is
    fetched here.
    """
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "reactions": [],
        "median_abs_move": None,
        "moves_over_5pct": None,
        "up_count": 0,
        "down_count": 0,
        "beat_count": 0,
        "miss_count": 0,
        "beat_but_fell": 0,
        "estimate_trend": None,
        "unavailable_reason": None,
    }

    try:
        stock = yf.Ticker(ticker)
        frame = stock.earnings_dates
    except ImportError as exc:
        result["unavailable_reason"] = f"missing dependency: {exc}"
        return result
    except Exception as exc:
        result["unavailable_reason"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return result

    if frame is None or getattr(frame, "empty", True):
        result["unavailable_reason"] = "no earnings history returned"
        return result

    try:
        history = stock.history(period="2y")
    except Exception as exc:
        result["unavailable_reason"] = f"no price history: {type(exc).__name__}"
        history = None

    if market_history is None:
        try:
            market_history = yf.Ticker("SPY").history(period="2y")
        except Exception:
            market_history = None
    market_closes = (market_history["Close"] if market_history is not None
                     and len(market_history) else None)

    if history is not None and len(history):
        index = history.index.tz_localize(None) if history.index.tz is not None else history.index

        for stamp in frame.index:
            if len(result["reactions"]) >= events:
                break
            try:
                local = stamp
                hour = local.hour
                day = (local.tz_localize(None) if local.tzinfo else local).normalize()
            except Exception:
                continue

            # WHICH SESSION ACTUALLY REACTED
            #
            # US companies report either before the open or after the
            # close, and the reacting session differs:
            #
            #   after the close (e.g. 16:00) -> the market first responds
            #     the NEXT day, so compare that day's close to this one.
            #   before the open (e.g. 07:00) -> the market responds the
            #     SAME day, so compare that day's close to the PREVIOUS
            #     one.
            #
            # Ignoring the clock and always taking "next day" silently
            # measures the wrong window for every before-open reporter --
            # usually a day with no news in it at all.
            before_open = hour < 12

            if before_open:
                prior_rows = history.loc[index < day]
                reaction_rows = history.loc[index == day]
                if not len(reaction_rows):
                    reaction_rows = history.loc[index > day]
            else:
                prior_rows = history.loc[index <= day]
                reaction_rows = history.loc[index > day]

            if not len(prior_rows) or not len(reaction_rows):
                continue

            prior_close = float(prior_rows["Close"].iloc[-1])
            reaction_close = float(reaction_rows["Close"].iloc[0])
            if not prior_close:
                continue
            move = (reaction_close - prior_close) / prior_close * 100

            row = frame.loc[stamp]
            surprise = _clean(_field(row, "Surprise(%)"))

            reaction = {
                "date": day.date().isoformat(),
                "surprise_percent": round(surprise, 1) if surprise is not None else None,
                "next_session_move": round(move, 2),
                "timing": "before open" if before_open else "after close",
                "from_close": round(prior_close, 2),
                "to_close": round(reaction_close, 2),
                "market_move": None, "expected_move": None, "abnormal_move": None,
                "standardized": None, "runup_abnormal": None, "beta": None,
            }
            if market_closes is not None:
                _add_abnormal(reaction, history["Close"], market_closes,
                              prior_rows.index[-1], reaction_rows.index[0])
            result["reactions"].append(reaction)

    for reaction in result["reactions"]:
        move = reaction["next_session_move"]
        surprise = reaction["surprise_percent"]
        if move >= 0:
            result["up_count"] += 1
        else:
            result["down_count"] += 1
        if surprise is None:
            continue
        if surprise >= 0:
            result["beat_count"] += 1
            if move < 0:
                result["beat_but_fell"] += 1
        else:
            result["miss_count"] += 1

    moves = [abs(r["next_session_move"]) for r in result["reactions"]]
    if moves:
        result["median_abs_move"] = round(_median(moves), 1)
        result["moves_over_5pct"] = sum(1 for m in moves if m >= 5)

    # The same counts on abnormal returns: "beat but underperformed what its
    # model expected" is the cleaner version of beat-but-fell, since a beat
    # on a day the whole market fell 3% isn't the same story.
    modelled = [r for r in result["reactions"] if r["abnormal_move"] is not None]
    result["modelled_count"] = len(modelled)
    result["median_abs_abnormal"] = (round(_median([abs(r["abnormal_move"]) for r in modelled]), 1)
                                     if modelled else None)
    result["beat_but_lagged"] = sum(1 for r in modelled if (r["surprise_percent"] or 0) > 0
                                    and r["abnormal_move"] < 0)
    result["unusual_count"] = sum(1 for r in modelled
                                  if r["standardized"] is not None and abs(r["standardized"]) >= 2)

    result["estimate_trend"] = _estimate_trend(stock)
    return result


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _add_abnormal(reaction: dict, closes, market_closes, prior_day, reaction_day) -> None:
    """Fill in the market-model fields for one reaction, or leave them None
    when the history before the report is too short to fit a model."""
    # A failure here costs the abnormal figures, never the reaction itself:
    # the raw move is still worth showing.
    try:
        model = performance.fit_market_model(closes, market_closes, prior_day)
        if model is None:
            return
        ar = performance.abnormal_return(closes, market_closes, prior_day, reaction_day, model)
        if ar is None:
            return
        run = performance.runup(closes, market_closes, prior_day, model)
    except Exception:
        return
    reaction.update({
        "market_move": round(ar["market_return"], 2),
        "expected_move": round(ar["expected_return"], 2),
        "abnormal_move": round(ar["abnormal_return"], 2),
        "standardized": round(ar["standardized"], 1) if ar["standardized"] is not None else None,
        "runup_abnormal": round(run["abnormal_return"], 2) if run else None,
        "beta": round(model["beta"], 2),
    })


def _estimate_trend(stock) -> dict[str, Any] | None:
    """Where the analyst estimate for the coming quarter has been heading.

    Two different signals, and they can disagree: the 90-day trajectory
    shows the direction of travel, while last month's revision counts show
    what is happening at the margin. A number revised sharply up over the
    quarter but trimmed in the last few weeks is a different setup from
    one still climbing.
    """
    trend: dict[str, Any] = {}

    try:
        table = stock.eps_trend
        if table is not None and not table.empty and "0q" in table.index:
            row = table.loc["0q"]
            trend["current"] = _clean(row.get("current"))
            trend["days_30"] = _clean(row.get("30daysAgo"))
            trend["days_90"] = _clean(row.get("90daysAgo"))
    except Exception:
        pass

    try:
        table = stock.eps_revisions
        if table is not None and not table.empty and "0q" in table.index:
            row = table.loc["0q"]
            trend["up_last_30_days"] = _clean(row.get("upLast30days"))
            trend["down_last_30_days"] = _clean(row.get("downLast30days"))
    except Exception:
        pass

    return trend or None
