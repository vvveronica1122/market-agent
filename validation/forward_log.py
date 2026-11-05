"""
Log the attention rule as shipped, one session at a time, and score it
against what happened after.

The November rework (validation/attention-2026-11.md) picked the rule on
21 months the October report had already looked at, so even its held-out
window wasn't pristine. Sessions after the rule shipped are: nothing about
it was chosen on them. This records what the home page ranked each session
-- live quotes, failed lookups and all, which a backtest can't reproduce --
and later fills in the outcomes the backtest measured, from price and
volume history fetched once they exist.

    python3 validation/forward_log.py record     # after the close: the session's ranks
    python3 validation/forward_log.py outcomes   # fill in what has happened since
    python3 validation/forward_log.py report     # the measures, from 20 sessions on

`record` refuses while the market is open, since the moves are still
moving. The log is validation/forward/ranks.csv, one row per company and
session, gitignored like validation/cache: it holds Yahoo's figures.

Outcomes, as in validation/attention.py:

  volume_today  the session's volume against the stock's 50-session median
                ending the day before (log ratio) -- the backtest's deciding
                outcome
  volume_next   the same for the next session: whether a flagged company is
                still being traded on, which the rank can't have seen
  next_gap_z    the next session's distance from its theme's median move,
                in the typical daily moves logged with the rank
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "web"))
sys.path.insert(0, str(ROOT / "validation"))

from attention import BLOCK, SEED, VOLUME_WINDOW, block_bootstrap, daily_ic, top_pick_rate  # noqa: E402
from tools.relative import peer_median  # noqa: E402

LOG = ROOT / "validation" / "forward" / "ranks.csv"
RANK_FIELDS = ["session", "recorded_at", "theme", "ticker", "rank", "count", "score", "level",
               "move_part", "relative_part", "reaction_part", "reference", "change_percent",
               "sigma", "peer_median", "earnings_days", "missing"]
OUTCOME_FIELDS = ["volume_today", "volume_next", "next_gap_z"]
FIELDS = RANK_FIELDS + OUTCOME_FIELDS


def read_log(path: Path | None = None) -> list[dict]:
    path = path or LOG
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_log(rows: list[dict], path: Path | None = None) -> None:
    path = path or LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def rank_rows(blocks: dict, session: str, recorded_at: str) -> list[dict]:
    """One log row per company, from compute_blocks()' themes, each already
    sorted by score as the pages show them."""
    out = []
    for theme in blocks["themes"]:
        for rank, row in enumerate(theme["rows"], 1):
            attention = row.get("attention") or {}
            parts = attention.get("parts") or {}
            out.append({
                "session": session, "recorded_at": recorded_at, "theme": theme["id"],
                "ticker": row["ticker"], "rank": rank, "count": len(theme["rows"]),
                "score": attention.get("score"), "level": attention.get("level"),
                "move_part": parts.get("move"), "relative_part": parts.get("relative"),
                "reaction_part": parts.get("reaction"), "reference": attention.get("reference"),
                "change_percent": (row.get("price") or {}).get("change_percent"),
                "sigma": row.get("sigma"), "peer_median": (row.get("relative") or {}).get("peer_median"),
                "earnings_days": attention.get("earnings_days"),
                "missing": ";".join(attention.get("missing") or []),
                **{k: "" for k in OUTCOME_FIELDS},
            })
    return out


def record(force: bool = False) -> int:
    import app as server

    status = server.market_status()
    if status["state"] == "open" and not force:
        print("The session is still open; record after the close.")
        return 1
    spy = server.history_of("SPY", server.SCORE_PERIOD)
    if not spy:
        print("SPY's history didn't load, so the session date is unknown; nothing recorded.")
        return 1
    session = spy[-1]["date"]
    rows = read_log()
    if any(r["session"] == session for r in rows):
        print(f"{session} is already in the log.")
        return 0
    state = server.load_themes()
    recorded_at = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="minutes")
    new = rank_rows(server.compute_blocks(state, state["themes"]), session, recorded_at)
    write_log(rows + new)
    missing = sum(1 for r in new if r["missing"])
    print(f"Recorded {session}: {len(new)} companies in {len({r['theme'] for r in new})} themes"
          + (f", {missing} with an input missing" if missing else "")
          + f". {LOG.relative_to(ROOT) if LOG.is_relative_to(ROOT) else LOG}")
    return 0


def fill_outcomes(rows: list[dict], closes: pd.DataFrame, volumes: pd.DataFrame) -> int:
    """Fill each row's outcomes where the history now covers them. Returns
    how many rows changed. `closes` and `volumes` are indexed by session
    date, one column per ticker."""
    returns = closes.pct_change(fill_method=None) * 100
    normal = volumes.rolling(VOLUME_WINDOW, min_periods=VOLUME_WINDOW).median().shift(1)
    abnormal = np.log(volumes / normal)
    sessions = list(returns.index)
    by_theme_session: dict[tuple, list[str]] = {}
    for r in rows:
        by_theme_session.setdefault((r["session"], r["theme"]), []).append(r["ticker"])

    def value(frame, day, ticker):
        if ticker not in frame.columns or day not in frame.index:
            return None
        v = frame.at[day, ticker]
        return None if pd.isna(v) else float(v)

    changed = 0
    for r in rows:
        if all(r[k] != "" for k in OUTCOME_FIELDS):
            continue
        day = pd.Timestamp(r["session"])
        if day not in returns.index:
            continue
        k = sessions.index(day)
        after = sessions[k + 1] if k + 1 < len(sessions) else None
        filled = {"volume_today": value(abnormal, day, r["ticker"])}
        if after is not None:
            filled["volume_next"] = value(abnormal, after, r["ticker"])
            moves = {t: value(returns, after, t) for t in by_theme_session[(r["session"], r["theme"])]}
            own, peers = moves.get(r["ticker"]), peer_median(moves, r["ticker"])
            sigma = float(r["sigma"]) if r["sigma"] not in ("", "None") else None
            if own is not None and peers is not None and sigma:
                filled["next_gap_z"] = abs(own - peers) / sigma
        for key, v in filled.items():
            if r[key] == "" and v is not None:
                r[key] = round(v, 4)
                changed += 1
    return changed


def outcomes() -> int:
    import yfinance as yf

    rows = read_log()
    pending = [r for r in rows if any(r[k] == "" for k in OUTCOME_FIELDS)]
    if not pending:
        print("Nothing waiting for outcomes.")
        return 0
    closes, volumes = {}, {}
    for ticker in sorted({r["ticker"] for r in pending}):
        history = yf.Ticker(ticker).history(period="1y")
        if history is None or history.empty:
            print(f"  {ticker}: no history; its outcomes wait for the next run")
            continue
        history.index = history.index.tz_localize(None).normalize()
        closes[ticker], volumes[ticker] = history["Close"], history["Volume"]
    changed = fill_outcomes(rows, pd.DataFrame(closes), pd.DataFrame(volumes))
    write_log(rows)
    print(f"Filled {changed} outcome values; "
          f"{sum(1 for r in rows if any(r[k] == '' for k in OUTCOME_FIELDS))} rows still wait.")
    return 0


def report(rows: list[dict] | None = None) -> str:
    rows = read_log() if rows is None else rows
    frame = pd.DataFrame(rows)
    if frame.empty:
        return "The log is empty."
    for column in ["score", *OUTCOME_FIELDS]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(frame["session"])
    sessions = frame["date"].nunique()
    lines = [f"{sessions} sessions logged, {frame['date'].min().date()} to {frame['date'].max().date()}, "
             f"{len(frame)} company-sessions."]
    shares = frame["level"].value_counts(normalize=True)
    lines.append("Levels: " + ", ".join(f"{level} {shares.get(level, 0):.1%}"
                                        for level in ("high", "medium", "quiet", "incomplete")))
    if sessions < BLOCK:
        lines.append(f"The measures need at least {BLOCK} sessions with outcomes, as the backtest's "
                     f"bootstrap does; none are reported yet.")
        return "\n".join(lines)
    rng = np.random.default_rng(SEED)
    lines += ["", "| Outcome | IC of the score | Top pick | Chance |", "|---|---|---|---|"]
    for outcome in OUTCOME_FIELDS:
        ic = daily_ic(frame, "score", outcome)
        if len(ic) < BLOCK:
            lines.append(f"| {outcome} | {len(ic)} sessions so far | | |")
            continue
        low, high = block_bootstrap(ic, rng)
        hit, chance = top_pick_rate(frame, "score", outcome)
        lines.append(f"| {outcome} | {ic.mean():+.3f} [{low:+.3f}, {high:+.3f}] | {hit:.1%} | {chance:.1%} |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["record", "outcomes", "report"])
    parser.add_argument("--force", action="store_true", help="record even while the market is open")
    args = parser.parse_args()
    if args.command == "record":
        return record(args.force)
    if args.command == "outcomes":
        return outcomes()
    print(report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
