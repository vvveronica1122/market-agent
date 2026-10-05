"""
Tests for period returns and the market model. Free, offline, instant.

The price series are built so the right answers are known in advance: a
stock constructed to move 1.5x the market should come out with a beta near
1.5, and a 5% jump planted on one day should come out as a 5% abnormal
return.

    python3 tools/test_performance.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import performance as perf


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def build(days=300, beta=1.5, alpha=0.0005, noise=0.01, jump_at=None, jump=0.05, seed=0):
    """Market and stock closes where stock return = alpha + beta*market + noise."""
    rng = np.random.RandomState(seed)
    index = pd.bdate_range("2025-01-02", periods=days)
    market_r = rng.normal(0.0004, 0.01, days)
    noise_r = rng.normal(0, noise, days)
    stock_r = alpha + beta * market_r + noise_r
    if jump_at is not None:
        stock_r[jump_at] = alpha + beta * market_r[jump_at] + jump  # the event, no noise
    market = pd.Series(100 * np.cumprod(1 + market_r), index=index)
    stock = pd.Series(50 * np.cumprod(1 + stock_r), index=index)
    return stock, market


def main() -> int:
    failures = 0

    print("\nPeriod returns")
    index = pd.bdate_range("2025-06-02", periods=300)
    closes = pd.Series(np.linspace(100, 160, 300), index=index)
    r = perf.period_returns(closes)
    failures += not check("1M is the return over 21 trading days",
                          abs(r["1M"] - (closes.iloc[-1] / closes.iloc[-22] - 1) * 100) < 1e-9)
    failures += not check("1Y is the return over 252 trading days",
                          abs(r["1Y"] - (closes.iloc[-1] / closes.iloc[-253] - 1) * 100) < 1e-9)
    last_of_year = closes[closes.index < "2026-01-01"].iloc[-1]
    failures += not check("year to date starts from the last close of the previous year",
                          abs(r["YTD"] - (closes.iloc[-1] / last_of_year - 1) * 100) < 1e-9)
    short = perf.period_returns(closes.iloc[-80:])
    failures += not check("a window longer than the history is None, not a shorter window",
                          short["6M"] is None and short["1Y"] is None and short["3M"] is not None,
                          str(short))
    tz = closes.copy()
    tz.index = tz.index.tz_localize("America/New_York")
    failures += not check("timezone-aware prices give the same answer",
                          abs(perf.period_returns(tz)["3M"] - r["3M"]) < 1e-9)

    print("\nMarket model")
    stock, market = build(jump_at=250)
    event = stock.index[250]
    model = perf.fit_market_model(stock, market, event)
    failures += not check("recovers the beta the stock was built with",
                          model is not None and abs(model["beta"] - 1.5) < 0.15,
                          str(model and round(model["beta"], 3)))
    failures += not check("residual noise matches the noise put in (1% a day)",
                          model is not None and 0.008 < model["resid_sd"] < 0.012,
                          str(model and round(model["resid_sd"], 4)))
    failures += not check("estimates over the stated window",
                          model["days"] == perf.ESTIMATION_DAYS)

    reaction = perf.abnormal_return(stock, market, stock.index[249], event, model)
    failures += not check("a 5% jump planted on the event day comes out as ~5% abnormal",
                          abs(reaction["abnormal_return"] - 5.0) < 0.4,
                          str(round(reaction["abnormal_return"], 3)))
    failures += not check("abnormal = actual - what the model expected",
                          abs(reaction["stock_return"] - reaction["expected_return"]
                              - reaction["abnormal_return"]) < 0.05)
    failures += not check("a 5% jump on a stock whose days swing ~1% is far outside the norm",
                          reaction["standardized"] > 3, str(round(reaction["standardized"], 2)))
    quiet = perf.abnormal_return(stock, market, stock.index[199], stock.index[200], model)
    failures += not check("an ordinary day is not abnormal",
                          abs(quiet["standardized"]) < 3, str(round(quiet["standardized"], 2)))

    # Yahoo's timestamps carry New York time; the first real run crashed
    # comparing them with plain dates after all of the above had passed.
    ny_stock, ny_market = stock.copy(), market.copy()
    ny_stock.index = ny_stock.index.tz_localize("America/New_York")
    ny_market.index = ny_market.index.tz_localize("America/New_York")
    ny_event = ny_stock.index[250]
    ny_model = perf.fit_market_model(ny_stock, ny_market, ny_event)
    ny_reaction = perf.abnormal_return(ny_stock, ny_market, ny_stock.index[249], ny_event, ny_model)
    failures += not check("timezone-aware dates, as Yahoo sends them, give the same answer",
                          ny_model is not None and abs(ny_model["beta"] - model["beta"]) < 1e-12
                          and abs(ny_reaction["abnormal_return"] - reaction["abnormal_return"]) < 1e-9)

    print("\nThe gap before the event")
    calm_stock, calm_market = build(seed=3)
    event = calm_stock.index[250]
    clean = perf.fit_market_model(calm_stock, calm_market, event)
    spiked = calm_stock.copy()
    spiked.iloc[245:] = spiked.iloc[245:] * 1.30  # a 30% run-up inside the gap
    leaked = perf.fit_market_model(spiked, calm_market, event)
    failures += not check("a run-up just before the report doesn't change what 'normal' is",
                          abs(clean["beta"] - leaked["beta"]) < 1e-9 and
                          abs(clean["resid_sd"] - leaked["resid_sd"]) < 1e-9)

    print("\nA past trend is not projected forward")
    # The first real run: alphas of 0.5-0.9% a day, fitted during a rally,
    # "expected" another 10-18% over 20 sessions and called a pause a slump.
    rng = np.random.RandomState(7)
    n = 270
    idx = pd.bdate_range("2025-01-02", periods=n)
    m_r = rng.normal(0.0003, 0.01, n)
    drift = np.where(np.arange(n) < 240, 0.008, 0.0)  # a rally that stops
    s_r = drift + 1.2 * m_r + rng.normal(0, 0.002, n)
    trend_stock = pd.Series(100 * np.cumprod(1 + s_r), index=idx)
    trend_market = pd.Series(100 * np.cumprod(1 + m_r), index=idx)
    trend_model = perf.fit_market_model(trend_stock, trend_market, idx[265])
    paused = perf.runup(trend_stock, trend_market, idx[265], trend_model)
    failures += not check("the rally's drift shows up as a large fitted alpha",
                          trend_model["alpha"] > 0.004, str(round(trend_model["alpha"], 4)))
    failures += not check("but a stock that simply stops rallying isn't called a slump",
                          abs(paused["abnormal_return"]) < 3, str(round(paused["abnormal_return"], 2)))

    print("\nRun-up")
    up = perf.runup(spiked, calm_market, calm_stock.index[249], clean)
    failures += not check("the run-up window catches the move into the report",
                          up is not None and up["abnormal_return"] > 20, str(up and round(up["abnormal_return"], 1)))
    failures += not check("the run-up spans the stated number of sessions",
                          up["days"] == perf.RUNUP_DAYS)

    print("\nRank correlation")
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    failures += not check("perfectly ordered pairs correlate at 1",
                          abs(perf.rank_correlation(xs, [10, 20, 30, 40, 50, 60, 70, 80, 90]) - 1) < 1e-12)
    failures += not check("reversed order correlates at -1",
                          abs(perf.rank_correlation(xs, list(reversed(xs))) + 1) < 1e-12)
    outlier = perf.rank_correlation(xs, [1, 2, 3, 4, 5, 6, 7, 8, 9000])
    failures += not check("one huge outlier doesn't change a rank correlation",
                          abs(outlier - 1) < 1e-12, str(outlier))
    failures += not check("too few pairs gives no correlation rather than a coincidence",
                          perf.rank_correlation([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) is None)
    failures += not check("missing values are dropped pairwise",
                          perf.rank_correlation(xs + [None], xs + [3]) is not None)

    print("\nShort histories")
    young_stock, young_market = build(days=70)
    failures += not check("too little history before the event gives no model, not a noisy one",
                          perf.fit_market_model(young_stock, young_market, young_stock.index[65]) is None)
    flat = pd.Series(100.0, index=young_market.index)
    failures += not check("a market that never moved can't define a beta",
                          perf.fit_market_model(young_stock, flat, young_stock.index[-1]) is None)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
