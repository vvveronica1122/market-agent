"""
Tests for the forward log of the shipped attention rule. Free, offline,
instant: synthetic prices and a stand-in for the app.

    python3 validation/test_forward_log.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import attention  # noqa: E402
import forward_log as fl  # noqa: E402


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def synthetic(sessions=90, tickers=("SPY", "AAA", "BBB", "CCC", "DDD"), seed=3):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-06-01", periods=sessions)
    closes = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.02, sessions)) for t in tickers},
                          index=index)
    volumes = pd.DataFrame({t: rng.integers(1_000_000, 3_000_000, sessions).astype(float) for t in tickers},
                           index=index)
    return closes, volumes


def blocks_for(day_moves: dict, sigmas: dict, missing=()) -> dict:
    """compute_blocks()' shape, as much of it as the log reads."""
    rows = [{"ticker": t, "price": {"change_percent": m}, "sigma": sigmas[t],
             "relative": {"peer_median": 0.1},
             "attention": {"score": 3.0 - i, "level": "high" if i == 0 else "quiet",
                           "parts": {"move": 1.5, "relative": 1.5 - i, "reaction": 0.0},
                           "reference": "peers", "earnings_days": None,
                           "missing": list(missing) if t == "CCC" else []}}
            for i, (t, m) in enumerate(day_moves.items())]
    return {"market_change_percent": 0.2, "themes": [{"id": "test", "rows": rows}]}


def main() -> int:
    failures = 0

    print("\nWhat a session's record holds")
    rows = fl.rank_rows(blocks_for({"AAA": 4.0, "BBB": 1.0, "CCC": -0.5}, {"AAA": 2, "BBB": 2, "CCC": 2},
                                   missing=("news",)), "2026-11-05", "2026-11-05T16:30-05:00")
    failures += not check("one row per company, ranked in the order the page shows them",
                          [(r["ticker"], r["rank"], r["count"]) for r in rows]
                          == [("AAA", 1, 3), ("BBB", 2, 3), ("CCC", 3, 3)], str(rows[:1]))
    failures += not check("with the score's parts and what failed to load",
                          rows[0]["move_part"] == 1.5 and rows[1]["relative_part"] == 0.5
                          and rows[2]["missing"] == "news" and rows[0]["missing"] == "")
    failures += not check("and outcomes left empty until they exist",
                          all(r[k] == "" for r in rows for k in fl.OUTCOME_FIELDS))

    print("\nOutcomes are the backtest's")
    # The backtest's observations() over the same synthetic prices, so the
    # log can't drift from the definitions its result is compared with.
    closes, volumes = synthetic()
    themes = [{"id": "test", "tickers": ["AAA", "BBB", "CCC", "DDD"]}]
    obs = attention.observations(themes, closes, volumes, {})
    day = closes.index[75]
    want = obs[obs["date"] == day].set_index("ticker")
    returns = closes.pct_change(fill_method=None) * 100
    logged = fl.rank_rows(blocks_for({t: returns.at[day, t] for t in themes[0]["tickers"]},
                                     {t: want.at[t, "sigma"] for t in themes[0]["tickers"]}),
                          day.date().isoformat(), "x")
    changed = fl.fill_outcomes(logged, closes, volumes)
    got = {r["ticker"]: r for r in logged}
    failures += not check("every outcome is filled when the next session exists",
                          changed == 12 and all(r[k] != "" for r in logged for k in fl.OUTCOME_FIELDS))
    failures += not check("volume_today and next_gap_z equal observations()' to rounding",
                          all(abs(got[t]["volume_today"] - want.at[t, "volume_today"]) < 1e-4
                              and abs(got[t]["next_gap_z"] - want.at[t, "next_gap_z"]) < 1e-4
                              for t in themes[0]["tickers"]),
                          str({t: (got[t]["volume_today"], round(want.at[t, "volume_today"], 4)) for t in got}))
    after = closes.index[76]
    next_obs = obs[obs["date"] == after].set_index("ticker")
    failures += not check("volume_next is the next session's volume_today",
                          all(abs(got[t]["volume_next"] - next_obs.at[t, "volume_today"]) < 1e-4
                              for t in themes[0]["tickers"]))
    last = closes.index[-1]
    pending = fl.rank_rows(blocks_for({t: 0.0 for t in themes[0]["tickers"]}, {t: 2.0 for t in themes[0]["tickers"]}),
                           last.date().isoformat(), "x")
    fl.fill_outcomes(pending, closes, volumes)
    failures += not check("the last session gets its own volume; the next session's wait",
                          all(r["volume_today"] != "" and r["volume_next"] == "" and r["next_gap_z"] == ""
                              for r in pending))
    failures += not check("a filled value is left alone on the next run",
                          fl.fill_outcomes(logged, closes, volumes) == 0)

    print("\nRecording a session")
    tmp = Path(tempfile.mkdtemp()) / "ranks.csv"
    real_log = fl.LOG
    fl.LOG = tmp
    fake = types.ModuleType("app")
    fake.SCORE_PERIOD = "6mo"
    fake.state = "after-hours"
    fake.market_status = lambda: {"state": fake.state}
    fake.history_of = lambda ticker, period: [{"date": "2026-11-04"}, {"date": "2026-11-05"}]
    fake.load_themes = lambda: {"themes": []}
    fake.compute_blocks = lambda state, themes: blocks_for({"AAA": 4.0, "BBB": 1.0, "CCC": -0.5},
                                                           {"AAA": 2, "BBB": 2, "CCC": 2})
    real_app = sys.modules.get("app")
    sys.modules["app"] = fake
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fake.state = "open"
            refused = fl.record()
            wrote_while_open = tmp.exists()
            fake.state = "after-hours"
            first = fl.record()
            second = fl.record()
        log = fl.read_log()
        failures += not check("refuses while the session is open",
                              refused == 1 and not wrote_while_open)
        failures += not check("records the session the prices come from, once",
                              first == 0 and second == 0 and len(log) == 3
                              and {r["session"] for r in log} == {"2026-11-05"}, str(len(log)))
        failures += not check("and reads back what it wrote",
                              [r["ticker"] for r in log] == ["AAA", "BBB", "CCC"] and log[0]["score"] == "3.0")
    finally:
        fl.LOG = real_log
        if real_app is not None:
            sys.modules["app"] = real_app
        else:
            sys.modules.pop("app", None)

    print("\nThe report")
    failures += not check("says nothing about the measures before 20 sessions",
                          "none are reported yet" in fl.report(log), fl.report(log))
    many = []
    for k in range(65, 88):
        d = closes.index[k]
        day_rows = fl.rank_rows(blocks_for({t: returns.at[d, t] for t in themes[0]["tickers"]},
                                           {t: 2.0 for t in themes[0]["tickers"]}), d.date().isoformat(), "x")
        for r, score in zip(day_rows, abs(returns.loc[d, themes[0]["tickers"]]).to_numpy()):
            r["score"] = float(score)
        many += day_rows
    fl.fill_outcomes(many, closes, volumes)
    text = fl.report(many)
    failures += not check("from 20 sessions on, gives each outcome's IC, interval and top-pick rate",
                          "| volume_today | " in text and "| next_gap_z | " in text and "[" in text, text)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
