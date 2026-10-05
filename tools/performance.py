"""
Returns over time, and the market model for earnings reactions.

Two questions the daily comparison in relative.py can't answer:

1. How has a company done over weeks and months, against its ETF and its
   peers? `period_returns` gives the raw numbers for each window; the
   comparisons reuse relative.py, which works on any set of returns.

2. How much of an earnings-day move was the earnings? A stock that rose 6%
   on a day the market rose 3% didn't react 6% to its report. The standard
   answer is the event-study market model: estimate how the stock normally
   moves with the market (by least squares over a window that ends before
   the report), then compare the reaction session with what that predicts.
   The difference is the abnormal return.

   The expectation uses beta only -- beta times the market's move -- and
   leaves the fitted alpha out. On the first real run, a 120-session window
   during 2026's memory rally fitted alphas of 0.5-0.9% a DAY; projected
   over the 20 sessions before a report, alpha alone "expected" a further
   10-18%, so a stock that merely paused came out 25-32% short. A past drift
   isn't something a stock is expected to repeat. Alpha is still estimated
   and returned, so the size of what was left out stays visible.

   Dividing it by the stock's normal day-to-day noise (the residual
   standard deviation from the same fit) says how unusual the reaction
   was: a 4% abnormal return is routine for a stock whose ordinary days
   swing 3%, and remarkable for one whose days swing 0.8%.

Pure arithmetic on pandas Series of closing prices indexed by date -- no
fetching -- so every number here can be checked against hand-built data.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# Trading days per window. Calendar months vary; trading-day counts are what
# the price history is indexed by.
PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}

# The model is estimated over ESTIMATION_DAYS of returns that end GAP_DAYS
# before the report, so the run-up into the event can't leak into what
# "normal" looks like. Fewer than MIN_ESTIMATION_DAYS of usable returns (a
# recent listing) and the fit is too noisy to call anything abnormal.
ESTIMATION_DAYS = 120
GAP_DAYS = 10
MIN_ESTIMATION_DAYS = 60

# The run-up: how the stock did against its model over the sessions just
# before the report -- how much was moving into it.
RUNUP_DAYS = 20


def _day(stamp) -> pd.Timestamp:
    """A date with no timezone. Yahoo's timestamps carry New York time and
    pandas refuses to compare those with plain dates -- the first run on
    real data failed exactly there, after every synthetic test had passed."""
    ts = pd.Timestamp(stamp)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def _naive(series: pd.Series) -> pd.Series:
    """Strip timezones and keep one close per date, sorted."""
    s = series.dropna().copy()
    index = pd.DatetimeIndex(s.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    s.index = index.normalize()
    return s[~s.index.duplicated(keep="last")].sort_index()


def period_returns(closes: pd.Series, today: date | None = None) -> dict[str, float | None]:
    """Percent return over each window in PERIODS, plus year to date.

    A window longer than the history comes back None rather than quietly
    measuring a shorter span -- a 1Y figure for a company listed eight
    months ago would be a different number under the same label.
    """
    s = _naive(closes)
    out: dict[str, float | None] = {}
    if len(s) < 2:
        return {**{k: None for k in PERIODS}, "YTD": None}
    last = float(s.iloc[-1])
    for label, days in PERIODS.items():
        out[label] = (last / float(s.iloc[-1 - days]) - 1) * 100 if len(s) > days else None

    year = (today or s.index[-1].date()).year
    before = s[s.index < pd.Timestamp(year=year, month=1, day=1)]
    out["YTD"] = (last / float(before.iloc[-1]) - 1) * 100 if len(before) else None
    return out


def fit_market_model(stock: pd.Series, market: pd.Series, event: pd.Timestamp) -> dict | None:
    """Alpha, beta and residual noise of daily returns, estimated before `event`.

    Uses the ESTIMATION_DAYS daily returns ending GAP_DAYS sessions before
    the event. Returns None when fewer than MIN_ESTIMATION_DAYS are
    available.
    """
    s, m = _naive(stock), _naive(market)
    joined = pd.concat([s.pct_change(), m.pct_change()], axis=1, join="inner").dropna()
    joined.columns = ["stock", "market"]
    before = joined[joined.index < _day(event)]
    window = before.iloc[: max(0, len(before) - GAP_DAYS)].iloc[-ESTIMATION_DAYS:]
    if len(window) < MIN_ESTIMATION_DAYS:
        return None

    x, y = window["market"], window["stock"]
    variance = float(x.var(ddof=1))
    if variance == 0:
        return None
    beta = float(((x - x.mean()) * (y - y.mean())).sum() / ((len(x) - 1) * variance))
    alpha = float(y.mean() - beta * x.mean())
    residuals = y - (alpha + beta * x)
    # n - 2: two parameters were estimated from the same data.
    resid_sd = float((residuals.pow(2).sum() / (len(window) - 2)) ** 0.5)
    return {"alpha": alpha, "beta": beta, "resid_sd": resid_sd, "days": len(window)}


def abnormal_return(stock: pd.Series, market: pd.Series, start: pd.Timestamp,
                    end: pd.Timestamp, model: dict) -> dict | None:
    """Abnormal return from the close on `start` to the close on `end`.

    For one session (adjacent closes) this is the abnormal return; for
    several it's the cumulative abnormal return, the daily abnormal returns
    summed. Expected = beta x market, alpha excluded (see the module notes).
    Percent figures throughout.

    `standardized` is the abnormal return in units of the stock's normal
    noise over that many days (resid_sd * sqrt(days)). Roughly: beyond 2,
    the move was outside what the stock's ordinary days produce.
    """
    s, m = _naive(stock), _naive(market)
    joined = pd.concat([s.pct_change(), m.pct_change()], axis=1, join="inner").dropna()
    joined.columns = ["stock", "market"]
    span = joined[(joined.index > _day(start)) & (joined.index <= _day(end))]
    if span.empty:
        return None
    expected = model["beta"] * span["market"]
    daily_abnormal = span["stock"] - expected
    days = len(span)
    car = float(daily_abnormal.sum())
    noise = model["resid_sd"] * days ** 0.5
    return {
        "stock_return": float((1 + span["stock"]).prod() - 1) * 100,
        "market_return": float((1 + span["market"]).prod() - 1) * 100,
        "expected_return": float(expected.sum()) * 100,
        "abnormal_return": car * 100,
        "standardized": car / noise if noise else None,
        "days": days,
    }


def rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Spearman's rank correlation, ties given their average rank.

    Ranks rather than values because earnings data has outliers -- one 300%
    surprise would otherwise decide a Pearson correlation on its own. Below
    MIN_CORRELATION_POINTS pairs it returns None: a correlation of five
    points is a coincidence with a decimal point.
    """
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < MIN_CORRELATION_POINTS:
        return None
    rx = pd.Series([p[0] for p in pairs]).rank(method="average")
    ry = pd.Series([p[1] for p in pairs]).rank(method="average")
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(rx.corr(ry))


MIN_CORRELATION_POINTS = 8


def runup(stock: pd.Series, market: pd.Series, before: pd.Timestamp, model: dict) -> dict | None:
    """Cumulative abnormal return over the RUNUP_DAYS sessions ending at the
    close before the report -- what was already moving into it."""
    s = _naive(stock)
    prior = s[s.index <= _day(before)]
    if len(prior) <= RUNUP_DAYS:
        return None
    return abnormal_return(stock, market, prior.index[-1 - RUNUP_DAYS], prior.index[-1], model)
