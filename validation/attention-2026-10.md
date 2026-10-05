# Does the attention score work? (October 2026)

The dashboard orders each theme's companies by an attention score
(`compute_attention` in `web/app.py`). The weights were set by hand:

| Part | Points |
|---|---|
| Size of the day's move | `min(abs(move %) x 8, 45)`, so the cap is reached at 5.6% |
| Diverging from peers | 12 if the move is 1.5pt or more from the peer median |
| Upcoming report | 25 if it's within 7 calendar days, 12 if within 14 |
| Headlines | 3 per headline, at most 12 |

The levels are *high* at 45 or more and *medium* at 20 or more. Until now
nothing had checked whether this ranks companies sensibly. This note
reports a backtest. **No rule has been changed as a result.** The
recommendations at the end are proposals.

Reproduce with `python3 validation/attention.py` (fetches from Yahoo and
caches) or `--offline`. Data fetched 2026-10-05.

## The question, made testable

"Needs attention" has no ground truth, so the score was tested against two
things it never sees:

1. **Same-day abnormal volume.** This is the day's volume against the
   stock's own 50-session median. Volume is the market's own record of
   attention, and it is the usual proxy in finance research (Barber &
   Odean, 2008, use it alongside extreme returns and news). If the score
   picks out the companies people were actually trading, it's doing its
   job.
2. **The next session's gap from peers.** This asks whether a flagged
   company stayed the one moving. It's measured raw, and also in units of
   the stock's own typical daily move, because otherwise volatile stocks
   win simply by being volatile.

Each day, within each theme, the companies were ranked by a signal and by
an outcome. The two rankings were compared with a Spearman correlation,
and the daily figures averaged into an information coefficient (IC).

- Days cluster (earnings seasons, volatile stretches), so the 95% intervals
  come from a 20-session block bootstrap rather than from treating days as
  independent.
- The backtest calls the production function, so it measures the rule the
  app runs, not a re-implementation.
- The universe is the four default themes (19 companies), from 2 January
  2025 to 2 October 2026: 439 sessions and 8,312 company-days.

## What it found

**1. The score does pick out what the market was paying attention to.**

- Its IC against same-day abnormal volume is **+0.29 [+0.26, +0.33]**.
- The theme's top-ranked company had the theme's most unusual volume on
  **42%** of theme-days, against 22% by chance.
- The levels are in the right order: median volume was 1.34x normal on
  *high* days, 1.04x on *medium* and 0.88x on *quiet*.

**2. It describes today; it doesn't forecast tomorrow.**

- Against the next session's raw gap from peers, the IC is +0.09
  [+0.06, +0.11].
- Measured in the stock's own typical move, that falls to **+0.00
  [−0.02, +0.03]**. The apparent forecasting came entirely from volatile
  stocks moving more on every day.
- A high rank means "look at this today", not "this will keep moving".
  That matches what the page claims ("ordered by what needs attention
  today"), and it is worth saying explicitly.

**3. Raw percentages favour volatile stocks.**

- Some companies top their theme far more often than an even split would
  give, and some far less:

  | Company | Theme | Top of theme | Even split |
  |---|---|---|---|
  | TSLA | mega-cap | 41% | 17% |
  | AMD | AI compute | 37% | 25% |
  | SNDK | memory | 36% | 25% |
  | VRT | AI power | 31% | 20% |
  | MSFT | mega-cap | 7% | 17% |

- SNDK's move part sat at the 45-point cap on 30% of its days. A 5.6% move
  is close to an ordinary day for a stock whose typical daily move is 6.4%.
- Scaling the move by the stock's own volatility (`z_move`) evens this out:
  TSLA falls to 21%, SNDK to 21% and MSFT rises to 15%.
- It also matches the market's attention *better* than the raw move part:
  **+0.033 [+0.005, +0.058]** in paired IC. On its own it is as good as the
  whole current score (+0.006 [−0.025, +0.037]).

**4. Earnings points arrive before the report and are gone by the reaction.**

- Two to seven days before a report, volume is normal (0.99x), yet the
  score gives the full 25 points.
- On the report day it's 1.72x. On the session after, it's **2.09x, the
  busiest day of the whole cycle**, and the score gives **0** earnings
  points: the "next report" is now a quarter away.
- Most of these companies report after the close, so that session is the
  reaction itself. The move part still catches the price move, but the
  "earnings" factor, and its label, disappear on the day the report is
  the story.

**5. The peer part earns its place, modestly.** The peer and earnings parts
together add **+0.026 [+0.007, +0.046]** to the move part on its own.

**6. The news part couldn't be tested, and live it barely varies.**

- Yahoo keeps no news history, so the news part was zero throughout.
- Live, it counts the latest five headlines whatever their age. On 5
  October 2026 every one of the 19 companies had five, which is the
  12-point maximum.
- That changes no ranking, but it shifts the levels. With 12 points added
  for everyone, *high* goes from 18% of company-days to 31%, and *quiet*
  from 47% to 21%.
- Even without news, *high* fires on 18% of company-days: about one
  company per theme on an average day.

## What I'd change (not applied)

These came from looking at this sample. Tuning weights to maximise IC on
the same 21 months would overfit them. Each change should be checked on
data the change wasn't designed on: either the months after it ships, or a
held-out final six months, set aside before anything is tuned.

1. **Score the move in the stock's own units.** Use the move divided by its
   60-session typical daily move, capped, in place of `abs(move %) x 8`.
2. **Put the earnings points where the attention is.** Give them on the
   report day and the session after it (the reaction to an after-close
   report), and fewer in the week before. Keep a calendar line ("reports in
   5 days") as information, separate from the rank.
3. **Count only recent headlines.** Only headlines published since the
   previous close should count. As it stands, the news part is a constant.
4. **Reset the level thresholds** after 1–3, by how often each level should
   fire (say *high* on 5–10% of company-days) rather than by hand-picked
   points.

## Limits of this check

- **Small sample.** It covers 19 companies over 21 months, in one strong
  regime (the AI rally). The comparisons *between* signals are more
  trustworthy than the absolute IC levels.
- **Volume only proxies attention.** Part of the link is mechanical (big
  moves bring volume), which is why the move part scores well. It can't
  say whether the ranked list is useful to a reader.
- **Report dates.** These come from Yahoo, and are assumed to be known in
  advance, as scheduled reports usually are. SNDK has seven since its
  February 2025 spin-off, and GEV eleven.
- **No correction for multiple comparisons.** Six signals were tested
  against three outcomes and the intervals aren't adjusted. The headline
  findings sit well clear of zero; the small paired differences (+0.026,
  +0.033) sit closer to it.

## Full output


Data fetched 2026-10-05.

Scored days: 439 sessions, 2025-01-02 to 2026-10-02; 8312 company-days across 4 themes and 19 companies.

#### Information coefficient: each signal against each outcome

Mean daily Spearman correlation within themes; 95% interval from a 20-session block bootstrap. 0 is no relationship.

| Signal | volume_today | next_gap | next_gap_z |
|---|---|---|---|
| `score` | +0.29 [+0.26, +0.33] | +0.09 [+0.06, +0.11] | +0.00 [-0.02, +0.03] |
| `move` | +0.27 [+0.24, +0.30] | +0.08 [+0.06, +0.11] | -0.01 [-0.04, +0.01] |
| `relative` | +0.21 [+0.17, +0.25] | +0.08 [+0.05, +0.12] | +0.02 [-0.02, +0.05] |
| `earnings` | +0.17 [+0.12, +0.25] | +0.01 [-0.04, +0.06] | +0.03 [-0.04, +0.09] |
| `z_move` | +0.30 [+0.27, +0.32] | +0.03 [+0.00, +0.05] | +0.05 [+0.02, +0.07] |
| `gap` | +0.19 [+0.15, +0.22] | +0.08 [+0.06, +0.11] | +0.01 [-0.01, +0.04] |

- `score`: the score as the app computes it (news part zero)
- `move`: its move part alone: min(|move| x 8, 45)
- `relative`: its peer part alone: 12 if 1.5pt or more from the peer median
- `earnings`: its earnings part alone: 25 within a week, 12 within two
- `z_move`: alternative: the move in units of the stock's own typical daily move
- `gap`: alternative: the distance from the peer median, unbucketed
- `volume_today`: same-day volume against the stock's 50-session median (log ratio)
- `next_gap`: next session's distance from the peer median, |own - peers|
- `next_gap_z`: the same, in units of the stock's own typical daily move

#### Paired differences

Two signals' daily ICs subtracted day by day, so the comparison isn't blurred by how much IC varies from one day to the next.

| Comparison | Outcome | Difference in IC |
|---|---|---|
| `score` - `move` (what the peer and earnings parts add) | volume_today | +0.026 [+0.007, +0.046] |
| `z_move` - `move` (scaling the move by the stock's own volatility) | volume_today | +0.033 [+0.005, +0.058] |
| `z_move` - `score` (the scaled move alone against the whole score) | volume_today | +0.006 [-0.025, +0.037] |
| `z_move` - `move` (the same scaling, judged by the next session) | next_gap_z | +0.062 [+0.045, +0.075] |

#### Top pick: does the first-ranked company have the largest outcome?

| Signal | volume_today | next_gap | chance |
|---|---|---|---|
| `score` | 42% | 29% | 22% |
| `move` | 41% | 29% | 22% |
| `z_move` | 43% | 24% | 22% |
| `gap` | 38% | 28% | 22% |

#### The levels: how often each fires, and what follows

| Level | Share of company-days | Median volume vs normal | Median next_gap (pt) |
|---|---|---|---|
| high | 18% | 1.34x | 1.72 |
| medium | 35% | 1.04x | 1.35 |
| quiet | 47% | 0.88x | 1.02 |

If every company also carried the news part's 12-point maximum, as every one did on 5 October 2026, rankings wouldn't change but the levels would: high 31%, medium 47%, quiet 21% of company-days.

#### Who gets ranked first

Share of theme-days each company tops its theme, on the score and on the volatility-scaled move, against an even split.

| Theme | Company | First on score | First on z_move | Even split | Typical daily move (std, %) |
|---|---|---|---|---|---|
| ai-compute | NVDA | 24% | 27% | 25% | 2.4 |
| ai-compute | AMD | 37% | 26% | 25% | 4.3 |
| ai-compute | AVGO | 22% | 21% | 25% | 3.1 |
| ai-compute | TSM | 18% | 26% | 25% | 2.6 |
| ai-power | VST | 23% | 19% | 20% | 3.1 |
| ai-power | CEG | 15% | 18% | 20% | 3.1 |
| ai-power | GEV | 20% | 22% | 20% | 3.5 |
| ai-power | ETN | 10% | 22% | 20% | 2.3 |
| ai-power | VRT | 31% | 18% | 20% | 4.3 |
| megacap-tech | AAPL | 11% | 18% | 17% | 1.6 |
| megacap-tech | MSFT | 7% | 15% | 17% | 1.7 |
| megacap-tech | GOOGL | 13% | 17% | 17% | 2.0 |
| megacap-tech | AMZN | 13% | 14% | 17% | 1.9 |
| megacap-tech | META | 16% | 15% | 17% | 2.2 |
| megacap-tech | TSLA | 41% | 21% | 17% | 3.2 |
| memory-storage | MU | 34% | 32% | 25% | 4.4 |
| memory-storage | WDC | 12% | 21% | 25% | 4.3 |
| memory-storage | STX | 17% | 27% | 25% | 4.1 |
| memory-storage | SNDK | 36% | 21% | 25% | 6.4 |

#### The move part's cap

The move part reaches its cap of 45 at a 5.6% move: 8.7% of company-days. Share of each company's days at the cap:

SNDK 30%, MU 18%, STX 16%, WDC 16%, VRT 15%, AMD 14%, VST 9%, GEV 8%, CEG 8%, TSLA 8%, AVGO 5%, NVDA 5%, META 4%, TSM 4%, ETN 3%, GOOGL 2%, AAPL 1%, AMZN 1%, MSFT 1%

#### Earnings proximity, day by day

Median same-day volume against normal, by calendar days to the next report.

| Days to report | Company-days | Median volume vs normal | Points the score gives |
|---|---|---|---|
| 0 | 132 | 1.72x | 25 |
| 1 | 128 | 1.15x | 25 |
| 2-7 | 520 | 0.99x | 25 |
| 8-14 | 627 | 0.96x | 12 |
| 15-30 | 1509 | 0.98x | 0 |
| 31-120 | 5396 | 0.99x | 0 |

Median same-day volume against normal, by trading sessions since the last report (the reaction to an after-close report lands on session 1).

| Sessions since report | Company-days | Median volume vs normal | Median earnings points |
|---|---|---|---|
| 1 | 132 | 2.09x | 0 |
| 2 | 132 | 1.44x | 0 |
| 3-5 | 393 | 1.08x | 0 |
| 6-20 | 1985 | 0.96x | 0 |

