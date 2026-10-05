"""
Does the attention score point at the right companies?

The score that orders each theme's companies (compute_attention in
web/app.py) was written by hand: points for the size of the day's move, for
diverging from peers, for an upcoming report, and for headlines. This checks
it against two years of what actually happened, using measures the score
never sees:

  1. Same day: trading volume against the stock's own recent normal.
     Abnormal volume is the market's own record of attention -- the usual
     proxy in finance research (Barber & Odean, 2008, use it alongside
     extreme returns and news) -- and volume is not an input to the score.
  2. Next session: how far the stock moved against its peers, i.e. whether
     a flagged company stayed the one moving.

Each day, within each theme, companies are ranked by score and by outcome
and the two rankings compared (Spearman). The average over days is the
score's information coefficient (IC). Days aren't independent -- earnings
seasons and volatile stretches cluster -- so the uncertainty comes from a
moving-block bootstrap over days. Each part of the score is also tested on
its own, alongside two alternatives, to see which parts carry the signal.

It calls the production compute_attention, not a copy, so it measures the
rule the app actually runs.

What it can't check: news (Yahoo keeps no history of it, so that part is
zero throughout), and whether the ranked list is useful to a reader, which
no price series can answer.

    python3 validation/attention.py              # fetches two years from Yahoo, caches it
    python3 validation/attention.py --offline    # reuse the cache
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))

import app as server  # noqa: E402  -- compute_attention, the rule under test
from themes import DEFAULT_THEMES  # noqa: E402
from tools.relative import peer_median  # noqa: E402

CACHE = ROOT / "validation" / "cache"
VOLUME_WINDOW = 50     # sessions behind a day's "normal volume" (median)
VOL_WINDOW = 60        # sessions behind a stock's typical daily move (std)
WARMUP = 60            # sessions of history before the first scored day
BLOCK = 20             # bootstrap block, in sessions: about a month
DRAWS = 2000
SEED = 7

SIGNALS = {
    "score": "the score as the app computes it (news part zero)",
    "move": "its move part alone: min(|move| x 8, 45)",
    "relative": "its peer part alone: 12 if 1.5pt or more from the peer median",
    "earnings": "its earnings part alone: 25 within a week, 12 within two",
    "z_move": "alternative: the move in units of the stock's own typical daily move",
    "gap": "alternative: the distance from the peer median, unbucketed",
}
OUTCOMES = {
    "volume_today": "same-day volume against the stock's 50-session median (log ratio)",
    "next_gap": "next session's distance from the peer median, |own - peers|",
    "next_gap_z": "the same, in units of the stock's own typical daily move",
}


# --- data -----------------------------------------------------------------

def universe() -> tuple[list[dict], list[str]]:
    themes = [{"id": t["id"], "tickers": [s["ticker"] for s in t["stocks"]]} for t in DEFAULT_THEMES]
    tickers = sorted({t for th in themes for t in th["tickers"]} | {"SPY"})
    return themes, tickers


def fetch(tickers: list[str]) -> None:
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)
    reports = {}
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        history = stock.history(period="2y")
        if history is None or history.empty:
            raise SystemExit(f"no price history for {ticker}")
        history.index = history.index.tz_localize(None).normalize()
        history[["Close", "Volume"]].to_csv(CACHE / f"{ticker}.csv")
        if ticker != "SPY":
            frame = stock.get_earnings_dates(limit=24)
            reports[ticker] = sorted({stamp.date().isoformat() for stamp in frame.index})
        print(f"  {ticker}: {len(history)} sessions, {len(reports.get(ticker, []))} report dates")
    (CACHE / "reports.json").write_text(json.dumps(reports, indent=1))
    (CACHE / "fetched.txt").write_text(date.today().isoformat() + "\n")


def load(tickers: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    closes, volumes = {}, {}
    for ticker in tickers:
        frame = pd.read_csv(CACHE / f"{ticker}.csv", index_col=0, parse_dates=True)
        closes[ticker], volumes[ticker] = frame["Close"], frame["Volume"]
    reports = {t: [date.fromisoformat(d) for d in ds]
               for t, ds in json.loads((CACHE / "reports.json").read_text()).items()}
    return pd.DataFrame(closes), pd.DataFrame(volumes), reports


# --- one row per company per day --------------------------------------------

def days_to_report(dates: list[date], today: date) -> int | None:
    upcoming = [d for d in dates if d >= today]
    return (upcoming[0] - today).days if upcoming else None


def sessions_since_report(dates: list[date], sessions: pd.DatetimeIndex, k: int) -> int | None:
    """Trading sessions since the most recent report date before today."""
    today = sessions[k].date()
    past = [d for d in dates if d < today]
    if not past:
        return None
    return int(((sessions[:k + 1].date > past[-1])).sum())


def observations(themes, closes, volumes, reports) -> pd.DataFrame:
    returns = closes.pct_change(fill_method=None) * 100
    # Baselines end the day before, so a day's own move or volume can't
    # inflate the normal it's compared with.
    typical = returns.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std().shift(1)
    normal_volume = volumes.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).median().shift(1)
    abnormal_volume = np.log(volumes / normal_volume)

    # compute_attention counts days from the real today, so a historical
    # report date is passed as the same distance from now.
    real_today = date.today()
    rows = []
    sessions = returns.index
    for k in range(WARMUP, len(sessions) - 1):
        day, after = sessions[k], sessions[k + 1]
        market = returns.at[day, "SPY"]
        for theme in themes:
            today = {t: returns.at[day, t] for t in theme["tickers"] if pd.notna(returns.at[day, t])}
            tomorrow = {t: returns.at[after, t] for t in theme["tickers"]
                        if pd.notna(returns.at[after, t])}
            if len(today) < 3:
                continue
            for ticker, move in today.items():
                peers = peer_median(today, ticker)
                days = days_to_report(reports.get(ticker, []), day.date())
                events = {"next_earnings_date": (real_today + timedelta(days=days)).isoformat()
                          if days is not None else None}
                attention = server.compute_attention({"change_percent": move}, [], events, market, peers)
                next_peers = peer_median(tomorrow, ticker) if ticker in tomorrow else None
                next_gap = (abs(tomorrow[ticker] - next_peers)
                            if next_peers is not None else np.nan)
                sigma = typical.at[day, ticker]
                rows.append({
                    "date": day, "theme": theme["id"], "ticker": ticker,
                    "score": attention["score"], "level": attention["level"],
                    "move": attention["parts"]["move"], "relative": attention["parts"]["relative"],
                    "earnings": attention["parts"]["earnings"],
                    "z_move": abs(move) / sigma if sigma else np.nan,
                    "gap": abs(move - peers) if peers is not None else np.nan,
                    "abs_move": abs(move), "sigma": sigma, "days_to_report": days,
                    "since_report": sessions_since_report(reports.get(ticker, []), sessions, k),
                    "volume_today": abnormal_volume.at[day, ticker],
                    "next_gap": next_gap,
                    "next_gap_z": next_gap / sigma if sigma else np.nan,
                })
    return pd.DataFrame(rows)


# --- measures -----------------------------------------------------------------

def daily_ic(obs: pd.DataFrame, signal: str, outcome: str) -> pd.Series:
    """Spearman correlation within each theme-day, averaged over themes per
    day. Theme-days where the signal or outcome doesn't vary are skipped."""
    frame = obs[["date", "theme", signal, outcome]].dropna()
    ranks = frame.groupby(["date", "theme"])[[signal, outcome]].rank()
    frame = frame.assign(rs=ranks[signal], ro=ranks[outcome])

    def corr(group):
        if group["rs"].nunique() < 2 or group["ro"].nunique() < 2:
            return np.nan
        return np.corrcoef(group["rs"], group["ro"])[0, 1]

    per_theme_day = frame.groupby(["date", "theme"])[["rs", "ro"]].apply(corr)
    return per_theme_day.groupby(level="date").mean().dropna()


def block_bootstrap(series: pd.Series, rng) -> tuple[float, float]:
    values = series.to_numpy()
    n = len(values)
    starts_per_draw = int(np.ceil(n / BLOCK))
    means = np.empty(DRAWS)
    for i in range(DRAWS):
        starts = rng.integers(0, n - BLOCK + 1, size=starts_per_draw)
        sample = np.concatenate([values[s:s + BLOCK] for s in starts])[:n]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def top_pick_rate(obs: pd.DataFrame, signal: str, outcome: str) -> tuple[float, float]:
    """How often the theme's top-ranked company had the day's largest
    outcome, against what picking at random would give (1/n)."""
    frame = obs[["date", "theme", signal, outcome]].dropna()
    hits, chance = [], []
    for _, group in frame.groupby(["date", "theme"]):
        if group[signal].nunique() < 2:
            continue
        hits.append(group.loc[group[signal].idxmax(), outcome] == group[outcome].max())
        chance.append(1 / len(group))
    return float(np.mean(hits)), float(np.mean(chance))


def fmt(x: float, digits: int = 3) -> str:
    return f"{x:+.{digits}f}" if digits else f"{x:.0f}"


def report(obs: pd.DataFrame) -> str:
    rng = np.random.default_rng(SEED)
    lines = []
    span = f"{obs['date'].min().date()} to {obs['date'].max().date()}"
    days = obs["date"].nunique()
    lines.append(f"Scored days: {days} sessions, {span}; {len(obs)} company-days "
                 f"across {obs['theme'].nunique()} themes and {obs['ticker'].nunique()} companies.\n")

    lines.append("### Information coefficient: each signal against each outcome\n")
    lines.append("Mean daily Spearman correlation within themes; 95% interval from a "
                 f"{BLOCK}-session block bootstrap. 0 is no relationship.\n")
    header = "| Signal | " + " | ".join(OUTCOMES) + " |"
    lines += [header, "|" + "---|" * (len(OUTCOMES) + 1)]
    for signal in SIGNALS:
        cells = []
        for outcome in OUTCOMES:
            series = daily_ic(obs, signal, outcome)
            low, high = block_bootstrap(series, rng)
            cells.append(f"{fmt(series.mean(), 2)} [{fmt(low, 2)}, {fmt(high, 2)}]")
        lines.append(f"| `{signal}` | " + " | ".join(cells) + " |")
    lines.append("")
    for name, text in {**SIGNALS, **OUTCOMES}.items():
        lines.append(f"- `{name}`: {text}")
    lines.append("")

    lines.append("### Paired differences\n")
    lines.append("Two signals' daily ICs subtracted day by day, so the comparison isn't blurred by "
                 "how much IC varies from one day to the next.\n")
    lines.append("| Comparison | Outcome | Difference in IC |")
    lines.append("|---|---|---|")
    for a, b, outcome, meaning in (
            ("score", "move", "volume_today", "what the peer and earnings parts add"),
            ("z_move", "move", "volume_today", "scaling the move by the stock's own volatility"),
            ("z_move", "score", "volume_today", "the scaled move alone against the whole score"),
            ("z_move", "move", "next_gap_z", "the same scaling, judged by the next session")):
        diff = (daily_ic(obs, a, outcome) - daily_ic(obs, b, outcome)).dropna()
        low, high = block_bootstrap(diff, rng)
        lines.append(f"| `{a}` - `{b}` ({meaning}) | {outcome} | "
                     f"{fmt(diff.mean())} [{fmt(low)}, {fmt(high)}] |")
    lines.append("")

    lines.append("### Top pick: does the first-ranked company have the largest outcome?\n")
    lines.append("| Signal | volume_today | next_gap | chance |")
    lines.append("|---|---|---|---|")
    for signal in ("score", "move", "z_move", "gap"):
        v, chance = top_pick_rate(obs, signal, "volume_today")
        g, _ = top_pick_rate(obs, signal, "next_gap")
        lines.append(f"| `{signal}` | {v:.0%} | {g:.0%} | {chance:.0%} |")
    lines.append("")

    lines.append("### The levels: how often each fires, and what follows\n")
    lines.append("| Level | Share of company-days | Median volume vs normal | Median next_gap (pt) |")
    lines.append("|---|---|---|---|")
    for level in ("high", "medium", "quiet"):
        part = obs[obs["level"] == level]
        lines.append(f"| {level} | {len(part) / len(obs):.0%} | "
                     f"{np.exp(part['volume_today'].median()):.2f}x | {part['next_gap'].median():.2f} |")
    lines.append("")

    # The news part is zero above: there's no history of it. Live, it counts
    # the latest headlines regardless of age, and on 5 October 2026 every
    # company returned five, the 12-point maximum.
    with_news = obs["score"] + 12
    lines.append("If every company also carried the news part's 12-point maximum, as every one did "
                 "on 5 October 2026, rankings wouldn't change but the levels would: "
                 f"high {(with_news >= 45).mean():.0%}, medium {((with_news >= 20) & (with_news < 45)).mean():.0%}, "
                 f"quiet {(with_news < 20).mean():.0%} of company-days.\n")

    lines.append("### Who gets ranked first\n")
    lines.append("Share of theme-days each company tops its theme, on the score and on the "
                 "volatility-scaled move, against an even split.\n")
    lines.append("| Theme | Company | First on score | First on z_move | Even split | Typical daily move (std, %) |")
    lines.append("|---|---|---|---|---|---|")
    for theme, group in obs.groupby("theme"):
        tops = group.loc[group.groupby("date")["score"].idxmax(), "ticker"].value_counts(normalize=True)
        ztops = (group.dropna(subset=["z_move"])
                 .pipe(lambda g: g.loc[g.groupby("date")["z_move"].idxmax(), "ticker"])
                 .value_counts(normalize=True))
        members = group.groupby("date")["ticker"].count().mean()
        for ticker in group["ticker"].unique():
            sigma = group.loc[group["ticker"] == ticker, "sigma"].median()
            lines.append(f"| {theme} | {ticker} | {tops.get(ticker, 0):.0%} | {ztops.get(ticker, 0):.0%} | "
                         f"{1 / members:.0%} | {sigma:.1f} |")
    lines.append("")

    lines.append("### The move part's cap\n")
    capped = obs["move"] >= 45
    lines.append(f"The move part reaches its cap of 45 at a 5.6% move: {capped.mean():.1%} of company-days. "
                 "Share of each company's days at the cap:\n")
    share = obs.groupby("ticker")["move"].apply(lambda s: (s >= 45).mean()).sort_values(ascending=False)
    lines.append(", ".join(f"{t} {v:.0%}" for t, v in share.items()))
    lines.append("")

    lines.append("### Earnings proximity, day by day\n")
    lines.append("Median same-day volume against normal, by calendar days to the next report.\n")
    lines.append("| Days to report | Company-days | Median volume vs normal | Points the score gives |")
    lines.append("|---|---|---|---|")
    for lo, hi, pts in ((0, 0, 25), (1, 1, 25), (2, 7, 25), (8, 14, 12), (15, 30, 0), (31, 120, 0)):
        part = obs[(obs["days_to_report"] >= lo) & (obs["days_to_report"] <= hi)]
        label = str(lo) if lo == hi else f"{lo}-{hi}"
        if len(part):
            lines.append(f"| {label} | {len(part)} | {np.exp(part['volume_today'].median()):.2f}x | {pts} |")
    lines.append("")

    lines.append("Median same-day volume against normal, by trading sessions since the last report "
                 "(the reaction to an after-close report lands on session 1).\n")
    lines.append("| Sessions since report | Company-days | Median volume vs normal | Median earnings points |")
    lines.append("|---|---|---|---|")
    for lo, hi in ((1, 1), (2, 2), (3, 5), (6, 20)):
        part = obs[(obs["since_report"] >= lo) & (obs["since_report"] <= hi)]
        label = str(lo) if lo == hi else f"{lo}-{hi}"
        if len(part):
            lines.append(f"| {label} | {len(part)} | {np.exp(part['volume_today'].median()):.2f}x | "
                         f"{part['earnings'].median():.0f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="reuse validation/cache")
    args = parser.parse_args()
    themes, tickers = universe()
    if not args.offline:
        print("fetching two years of prices and report dates...")
        fetch(tickers)
    closes, volumes, reports = load(tickers)
    obs = observations(themes, closes, volumes, reports)
    fetched = (CACHE / "fetched.txt").read_text().strip()
    print(f"\nData fetched {fetched}.\n")
    print(report(obs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
