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

## Selection-window results

`python3 validation/attention_v2.py`: 311 sessions, 5,880 company-days, 2 January
2025 to 31 March 2026. The held-out window has not been run.

| Candidate | IC, volume_today | IC, next_gap_z | Top pick, volume_today (chance 22%) |
|---|---|---|---|
| `score` | +0.298 [+0.251, +0.344] | -0.000 [-0.028, +0.031] | 41.6% |
| `abs_move` | +0.274 [+0.237, +0.316] | -0.015 [-0.038, +0.013] | 42.3% |
| `z_move` | +0.304 [+0.274, +0.335] | +0.058 [+0.034, +0.088] | 42.8% |
| `anomaly` | +0.311 [+0.267, +0.346] | +0.103 [+0.064, +0.140] | 43.4% |
| `anomaly_er` | +0.343 [+0.301, +0.378] | +0.117 [+0.083, +0.156] | 46.1% |

Paired differences in daily IC, volume_today: `anomaly` - `z_move` +0.007
[-0.023, +0.028]; `anomaly_er` - `z_move` +0.038 [+0.007, +0.062];
`anomaly_er` - `anomaly` +0.031 [+0.022, +0.043]; `anomaly_er` - `score`
+0.045 [+0.000, +0.084].

**The plan's rules:** `anomaly` does not beat `z_move` on volume_today (rule
1), so the rule-1 choice is `z_move`; `anomaly_er` beats it (rule 2); and it
is not worse than `score` (rule 3). **The rules recommend `anomaly_er`.**

What the numbers say, and don't:

- **On today's attention, the gain is small.** Against the current score,
  +0.045 in IC with an interval reaching 0, and the top pick right on 46%
  of theme-days instead of 42%. All of it comes from the reaction-day
  bonus: without it, `anomaly` is level with `z_move` and with `score`.
- **On whether a flagged name stays the one moving, the gain is large.**
  The current score has no relationship with the next session's gap (IC
  -0.000); `anomaly_er` has +0.117. The peer gap in volatility units is
  what adds it (`anomaly` - `z_move`: +0.045 on next_gap_z).
- **The earnings points move to where the attention is.** Reaction
  sessions ran at 1.89 times normal volume; the week before a report, where
  the score gives 25 points, at 1.04 times, no different from other days.
- **Volatile names stop dominating.** TSLA topped mega-cap tech on 43% of
  days under the score, against 17% for an even split; 22% under
  `anomaly_er`. SNDK 37% to 25%. The quiet names come up instead: MSFT 5%
  to 16%, ETN 8% to 28%. ETN now tops AI power more often than an even split
  (20%), which is worth watching: a low-volatility stock's ordinary move
  scores high in its own units.
- **"High" would mean more.** With thresholds set by frequency, high fires
  on 7.5% of company-days with a median volume of 1.77 times normal; today's
  high fires on 16.6% at 1.42 times.

The pick is the author's. Whatever it is, it runs once on the held-out
window, beside `score` and `z_move`.

## Held-out result: `anomaly_er`, run once

The author picked `anomaly_er`, with the calendar moved out of the rank and
the news count out of the score. `python3 validation/attention_v2.py
--held-out anomaly_er`: 128 sessions, 2,432 company-days, 1 April to
2 October 2026.

| Candidate | IC, volume_today | IC, next_gap_z | Top pick, volume_today (chance 22%) |
|---|---|---|---|
| `anomaly_er` | +0.305 [+0.256, +0.364] | +0.080 [+0.003, +0.150] | 43.9% |
| `z_move` | +0.282 [+0.249, +0.322] | +0.024 [-0.037, +0.091] | 43.2% |
| `score` | +0.279 [+0.234, +0.319] | +0.013 [-0.040, +0.065] | 42.4% |

Paired: `anomaly_er` - `score`, volume_today +0.026 [+0.005, +0.054],
next_gap_z +0.066 [+0.025, +0.095]; `anomaly_er` - `z_move`, volume_today
+0.023 [-0.006, +0.051], next_gap_z +0.056 [+0.020, +0.081].

Levels with the selection window's thresholds: high on 7.1% of company-days
(median volume 1.56 times normal), medium 20.5% (1.12 times), quiet 72.5%
(0.87 times).

**It holds, smaller.** On the held-out months `anomaly_er` still beats the
current score on same-day volume, now with an interval clear of 0 (+0.026),
and on whether a flagged name stays the one moving (+0.066, against +0.118
in the selection window). It is not distinguishable from the plain scaled
move on same-day volume (+0.023, interval through 0). The top pick moves
from 42% to 44%, a modest change a reader may not notice day to day. The
levels keep their order and roughly their frequency, but "high" means less
volume than in the window it was set on (1.56 against 1.77 times normal):
thresholds set on one stretch of a market drift on the next.

So the rework is worth making for what it fixes -- earnings points on the
wrong days, volatile names topping their themes, a news count that is a
constant, a "high" that fires on one company-day in six -- more than for a
large gain in ranking. A clean measure of that needs sessions after this
change ships: log the shipped ranks and the next day's volume.
