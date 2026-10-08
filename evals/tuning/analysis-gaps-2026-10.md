# The stock analysis compares moves in points, October 2026

The stock page's analysis has no calculator, so any comparison it makes
between two moves is arithmetic done in its head. Of the 46 analyses
saved in `evals/results/`, four state one move as a multiple of another,
all in `mixed_move_report_tomorrow` (AMD -4.2%, peer median -2.0%, NVDA
-2.0%, AVGO -1.8%, SPY -0.6%):

- "declining roughly twice as much as the broader market's 0.6% drop".
  It is seven times. This one passed the judge.
- Three more say "roughly twice" against the peers or NVDA and AVGO,
  which is about right (2.1 to 2.3 times).

Right or wrong, a multiple of a small move exaggerates: against a flat
market any move is many times larger. The app already gives the gap to
the peers and to the benchmark in points (`vs_peers`, `vs_benchmark`);
the gap to the market was missing, so the model worked it out itself.

## The change

- **The analysis** gets `vs_market` in `market_comparison`: the company's
  move minus SPY's, in points, computed in `analyze()` like the other two
  gaps. The prompt says to compare moves with those gaps and never as
  multiples.
- **The evals** get a regex check, "never states a move as a multiple of
  another", run on every analysis. Multiples are fixed phrasing ("twice",
  "three times as", "7x", "half as"), so this is regex, not the judge. The
  pattern was checked against the four saved sentences and against
  legitimate ones ("half of those beats", "double-digit", "three of those
  beats", "3.6 points more than the market"), and it flags none of the
  other 42 saved analyses.

The judge and rubric are unchanged.

Model: claude-sonnet-4-5. Budget: $4.

## Plan, written before any run

**Before.** The commit that adds this plan: the new check, with
`master`'s app code (eb2381d).

- All six analysis scenarios, 8 runs each (48), for regression.
- `mixed_move_report_tomorrow`, 16 more runs, because every saved
  multiple came from it. With the 8 above, 24 runs of that scenario.

**After.** The same 64 runs on the fixed code.

These are regression runs, not tuning; the test split was read in earlier
work, so nothing here counts as a held-out result.

**Pass criteria.** Merge only if all three hold:

1. The multiples check fails in at most 1 of the 64 after-fix runs.
2. Judge passes after the fix: at least 42 of 48 in the six-scenario run,
   none below 6 of 8; and at least 13 of 16 in the extra
   `mixed_move_report_tomorrow` run (its held-out result was 13/16).
3. Every other deterministic check passes in all 64 after-fix runs.

**If the before run shows no multiples** in its 24 runs of
`mixed_move_report_tomorrow`, the failure didn't reproduce and these runs
can't show the fix doing anything. That is recorded as such; the change
can still merge on criteria 2 and 3 as a preventive fix, with no
improvement claimed.
