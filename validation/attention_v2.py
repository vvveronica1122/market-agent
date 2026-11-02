"""
Candidates for a reworked attention score, against the October baselines.

The plan, its split and its decision rules are in validation/attention-2026-11.md,
written before this was run. Everything is measured on the selection window
unless --held-out names the one candidate the author picked; the held-out
window is meant to be used once.

    python3 validation/attention_v2.py                      # selection window
    python3 validation/attention_v2.py --held-out anomaly   # once, after the pick

Reuses validation/attention.py's data (its cache) and measures, so the two
scripts score the same days the same way.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import attention as base  # noqa: E402

SPLIT = pd.Timestamp("2026-03-31")   # last session of the selection window
CAP = 5.0                            # in typical daily moves
REACTION_BONUS = 2.0                 # in typical daily moves
HIGH_SHARE, MEDIUM_SHARE = 0.075, 0.20

CANDIDATES = {
    "score": "the current score, news part zero",
    "abs_move": "baseline: the size of the day's move",
    "z_move": "baseline: the move in units of the stock's typical daily move",
    "anomaly": "min(z_move, 5) + min(z_gap, 5)",
    "anomaly_er": "anomaly + 2 on a report's reaction sessions",
}
OUTCOMES = ("volume_today", "next_gap_z")


def with_candidates(obs: pd.DataFrame) -> pd.DataFrame:
    z_gap = obs["gap"] / obs["sigma"]
    # The report date (a before-open report's reaction) and the session after
    # it (an after-close report's); the cache has dates, not report times.
    reaction = (obs["days_to_report"] == 0) | (obs["since_report"] == 1)
    anomaly = obs["z_move"].clip(upper=CAP) + z_gap.clip(upper=CAP)
    return obs.assign(z_gap=z_gap, reaction=reaction, anomaly=anomaly,
                      anomaly_er=anomaly + REACTION_BONUS * reaction)


def ic_with_interval(obs, signal, outcome, rng):
    series = base.daily_ic(obs, signal, outcome)
    low, high = base.block_bootstrap(series, rng)
    return series.mean(), low, high


def paired(obs, a, b, outcome, rng):
    diff = (base.daily_ic(obs, a, outcome) - base.daily_ic(obs, b, outcome)).dropna()
    low, high = base.block_bootstrap(diff, rng)
    return diff.mean(), low, high


def levels(obs: pd.DataFrame, signal: str, thresholds: tuple[float, float]) -> list[str]:
    high, medium = thresholds
    rows = []
    for name, part in (("high", obs[obs[signal] >= high]),
                       ("medium", obs[(obs[signal] >= medium) & (obs[signal] < high)]),
                       ("quiet", obs[obs[signal] < medium])):
        rows.append(f"| {name} | {len(part) / len(obs):.1%} | {np.exp(part['volume_today'].median()):.2f}x | "
                    f"{part['next_gap_z'].median():.2f} |")
    return rows


def selection_report(obs: pd.DataFrame) -> str:
    rng = np.random.default_rng(base.SEED)
    out = [f"Selection window: {obs['date'].min().date()} to {obs['date'].max().date()}, "
           f"{obs['date'].nunique()} sessions, {len(obs)} company-days.\n"]

    out += ["### IC against each outcome\n", "| Candidate | " + " | ".join(OUTCOMES) + " |",
            "|---|" + "---|" * len(OUTCOMES)]
    for c in CANDIDATES:
        cells = [f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]" for m, lo, hi in
                 (ic_with_interval(obs, c, o, rng) for o in OUTCOMES)]
        out.append(f"| `{c}` | " + " | ".join(cells) + " |")
    out.append("")

    out += ["### Paired differences in daily IC\n", "| Comparison | volume_today | next_gap_z |", "|---|---|---|"]
    pairs = [("anomaly", "z_move"), ("anomaly_er", "anomaly"), ("anomaly_er", "z_move"),
             ("z_move", "score"), ("anomaly", "score"), ("anomaly_er", "score"), ("z_move", "abs_move")]
    results = {}
    for a, b in pairs:
        cells = []
        for o in OUTCOMES:
            m, lo, hi = paired(obs, a, b, o, rng)
            results[(a, b, o)] = (m, lo, hi)
            cells.append(f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]")
        out.append(f"| `{a}` - `{b}` | " + " | ".join(cells) + " |")
    out.append("")

    out += ["### Top pick: share of theme-days the first-ranked company had the largest outcome\n",
            "| Candidate | volume_today | next_gap_z | chance |", "|---|---|---|---|"]
    for c in CANDIDATES:
        v, chance = base.top_pick_rate(obs, c, "volume_today")
        g, _ = base.top_pick_rate(obs, c, "next_gap_z")
        out.append(f"| `{c}` | {v:.1%} | {g:.1%} | {chance:.1%} |")
    out.append("")

    out += ["### Who gets ranked first, by candidate (share of theme-days)\n",
            "| Theme | Company | Typical move (%) | " + " | ".join(f"`{c}`" for c in CANDIDATES) + " | even |",
            "|---|---|---|" + "---|" * (len(CANDIDATES) + 1)]
    for theme, group in obs.groupby("theme"):
        tops = {c: group.dropna(subset=[c]).pipe(lambda g: g.loc[g.groupby("date")[c].idxmax(), "ticker"])
                .value_counts(normalize=True) for c in CANDIDATES}
        even = 1 / group.groupby("date")["ticker"].count().mean()
        for ticker in sorted(group["ticker"].unique()):
            sigma = group.loc[group["ticker"] == ticker, "sigma"].median()
            out.append(f"| {theme} | {ticker} | {sigma:.1f} | "
                       + " | ".join(f"{tops[c].get(ticker, 0):.0%}" for c in CANDIDATES) + f" | {even:.0%} |")
    out.append("")

    out += ["### Earnings: same-day volume by where the day sits around a report\n",
            "| Day | Company-days | Median volume vs normal |", "|---|---|---|"]
    for label, mask in (("1-7 days before (score gives 25)", obs["days_to_report"].between(1, 7)),
                        ("8-14 days before (score gives 12)", obs["days_to_report"].between(8, 14)),
                        ("reaction sessions (anomaly_er gives +2)", obs["reaction"]),
                        ("all other days", ~obs["reaction"] & ~obs["days_to_report"].between(1, 14))):
        part = obs[mask]
        out.append(f"| {label} | {len(part)} | {np.exp(part['volume_today'].median()):.2f}x |")
    out.append("")

    out += ["### Levels set by frequency on this window\n"]
    for c in ("z_move", "anomaly", "anomaly_er"):
        values = obs[c].dropna()
        thresholds = (values.quantile(1 - HIGH_SHARE), values.quantile(1 - HIGH_SHARE - MEDIUM_SHARE))
        out += [f"`{c}`: high at {thresholds[0]:.2f}, medium at {thresholds[1]:.2f}\n",
                "| Level | Share | Median volume vs normal | Median next_gap_z |", "|---|---|---|---|"]
        out += levels(obs.dropna(subset=[c]), c, thresholds) + [""]
    out += ["`score` (today's thresholds, 45 and 20):\n",
            "| Level | Share | Median volume vs normal | Median next_gap_z |", "|---|---|---|---|"]
    out += levels(obs, "score", (45, 20)) + [""]

    # The decision rules, as written in the plan before this ran.
    def beats(a, b):
        return results[(a, b, "volume_today")][1] > 0
    pick = "anomaly" if beats("anomaly", "z_move") else "z_move"
    if beats("anomaly_er", pick):
        pick = "anomaly_er"
    # From the table above, so the rule and the table can't disagree.
    vs_score = results[(pick, "score", "volume_today")]
    keep_current = vs_score[2] <= 0
    out += ["### What the plan's rules recommend\n",
            f"- Rule 1: `anomaly` beats `z_move` on volume_today: {beats('anomaly', 'z_move')}.",
            f"- Rule 2: `anomaly_er` beats the rule-1 choice: {pick == 'anomaly_er'}.",
            f"- Rule 3: `{pick}` against `score` on volume_today: {vs_score[0]:+.3f} "
            f"[{vs_score[1]:+.3f}, {vs_score[2]:+.3f}]; not worse: {not keep_current}.",
            f"- **Recommendation: {'keep the current score, move the calendar out' if keep_current else pick}.**", ""]
    return "\n".join(out)


def held_out_report(obs: pd.DataFrame, pick: str, selection: pd.DataFrame) -> str:
    rng = np.random.default_rng(base.SEED)
    out = [f"Held-out window: {obs['date'].min().date()} to {obs['date'].max().date()}, "
           f"{obs['date'].nunique()} sessions, {len(obs)} company-days. Pick: `{pick}`.\n",
           "| Candidate | volume_today | next_gap_z |", "|---|---|---|"]
    for c in dict.fromkeys([pick, "z_move", "score"]):
        cells = [f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]" for m, lo, hi in
                 (ic_with_interval(obs, c, o, rng) for o in OUTCOMES)]
        out.append(f"| `{c}` | " + " | ".join(cells) + " |")
    out += ["", "| Comparison | volume_today | next_gap_z |", "|---|---|---|"]
    for b in [x for x in ("z_move", "score") if x != pick]:
        cells = [f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]" for m, lo, hi in
                 (paired(obs, pick, b, o, rng) for o in OUTCOMES)]
        out.append(f"| `{pick}` - `{b}` | " + " | ".join(cells) + " |")
    out += ["", "| Candidate | top pick, volume_today | chance |", "|---|---|---|"]
    for c in dict.fromkeys([pick, "z_move", "score"]):
        v, chance = base.top_pick_rate(obs, c, "volume_today")
        out.append(f"| `{c}` | {v:.1%} | {chance:.1%} |")
    if pick != "score":
        values = selection[pick].dropna()
        thresholds = (values.quantile(1 - HIGH_SHARE), values.quantile(1 - HIGH_SHARE - MEDIUM_SHARE))
        out += ["", f"Levels with the selection window's thresholds ({thresholds[0]:.2f}, {thresholds[1]:.2f}):\n",
                "| Level | Share | Median volume vs normal | Median next_gap_z |", "|---|---|---|---|"]
        out += levels(obs.dropna(subset=[pick]), pick, thresholds)
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--held-out", metavar="CANDIDATE", choices=list(CANDIDATES),
                        help="run the picked candidate once on the held-out window")
    args = parser.parse_args()
    themes, tickers = base.universe()
    closes, volumes, reports = base.load(tickers)
    obs = with_candidates(base.observations(themes, closes, volumes, reports))
    selection, held_out = obs[obs["date"] <= SPLIT], obs[obs["date"] > SPLIT]
    if args.held_out:
        print(held_out_report(held_out, args.held_out, selection))
    else:
        print(selection_report(selection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
