# Reworking the attention score (November 2026)

The October backtest ([attention-2026-10.md](attention-2026-10.md)) found the
score ranks companies about as well as simple alternatives: its top pick had
the theme's most unusual volume on 42% of theme-days, against 41% for the raw
move and 43% for the move scaled by the stock's own volatility. It also found
three things the rule does that it shouldn't:

- it favours volatile stocks, because a 3% move scores the same for a stock
  that moves 1% a day and one that moves 4%;
- it gives earnings points in the week before a report, when volume is
  ordinary, and takes them away on the reaction day, when volume is highest;
- its news part counts the latest headlines whatever their age, so live it
  is the same 12 points for nearly every company.

The outside review (docs/MarketAgent_Review_and_Improvement_Plan.md, section
6) asks to split two jobs the score mixes: **what moved unusually today**
and **what is coming up**. This note tests a replacement for the first, with
the second moved out of the rank into its own calendar block.

## Plan, written before any of the new variants was run

**Data.** The October cache: 19 companies in four themes, 439 scored
sessions from 2 January 2025 to 2 October 2026.

**A split, fixed now.**

- Selection window: 2 January 2025 to 31 March 2026, 311 sessions. All
  comparisons between candidates are made here.
- Held-out window: 1 April to 2 October 2026, 128 sessions. Used once, for
  the candidate the author picks, after the pick.

The held-out window is not pristine: the October report looked at all 21
months, and its recommendations -- scale by volatility, put earnings on the
reaction day, drop the news count -- came from that look. What the split
guarantees is narrower: nothing about choosing among the candidates below
is fitted to those 128 sessions. A clean test needs sessions that didn't
exist in October; logging the shipped rule's ranks and the next day's volume
from now on gives that.

**Candidates, all specified before running; no weight is tuned.**

| Name | Rule |
|---|---|
| `score` | the current score, news part zero (as in October) |
| `abs_move` | baseline: the size of the day's move |
| `z_move` | baseline: the move in units of the stock's typical daily move (60-session std, ending the day before) |
| `anomaly` | `min(z_move, 5) + min(z_gap, 5)`, where `z_gap` is the distance from the peer median in the same units |
| `anomaly_er` | `anomaly`, plus 2 on a report's reaction sessions (the report date and the session after it) |

The caps (5 typical moves) and the +2 (about the size of a typical
earnings reaction in these units) are set here, not fitted. Earnings
proximity before a report is not in any candidate: it moves to the calendar
block. Volume is not a candidate input: it is the outcome.

**Outcomes.** `volume_today` (same-day volume against the 50-session median,
log ratio), the attention proxy, decides. `next_gap_z` (the next session's
distance from peers, in typical moves) is reported beside it: does a
flagged company stay the one moving?

**Measures**, as in October: the mean daily Spearman IC within themes, with
a 20-session block bootstrap 95% interval; paired daily IC differences;
the top-pick rate against chance; who gets ranked first.

**Levels.** Today's thresholds (45 and 20 points) fire "high" on 18% of
company-days and "medium" on 35%. For the new rank, thresholds are set as
quantiles of the selection window: "high" for the top 7.5% of company-days,
"medium" for the next 20%. In the held-out window: how often each fires,
and the median volume behind it.

**What I'll recommend, decided now.**

1. If `anomaly` beats `z_move` on `volume_today` in the selection window
   (paired IC difference with a lower 95% bound above 0), recommend it;
   otherwise recommend `z_move` alone, the simpler rule.
2. If `anomaly_er` beats the recommended one the same way, recommend
   `anomaly_er` instead.
3. Whatever is recommended must not do worse than `score` on `volume_today`
   (paired difference with an upper 95% bound above 0); otherwise the
   recommendation is to keep the current rule and only move the calendar out.

The author then picks; the pick, with `score` and `z_move` beside it, is run
once on the held-out window, and that result is reported whatever it shows.
