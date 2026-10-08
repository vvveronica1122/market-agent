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

## Before the fix (f43b558)

| Run | Judge | Multiples check |
|---|---|---|
| Six scenarios, 8 each (20261008-040221_brief.json) | 46/48 | 46/48 |
| `mixed_move_report_tomorrow`, 16 more (20261008-040501_brief.json) | 16/16 | 12/16 |

**The failure reproduced: 6 of 24 runs of `mixed_move_report_tomorrow`
stated a multiple**, and none of the other five scenarios did. All six
compared AMD with its peers ("roughly twice as much as its semiconductor
peer group", "twice as deep"), which is about right; none repeated the
wrong "twice the market". The judge passed every one of them.

The judge's two failures were unrelated to the change: a causal "dropped
following the company's announcement" in `company_drop_peers_flat`, and
AMD's fall called wholly company-specific when it was partly shared.

**The six-scenario run crossed midnight.** It was saved at 00:02 on
8 October after about seven minutes, so it started a few minutes before
midnight. The fixtures' report dates are computed once, when the
scenarios are imported, while `today` is read on every call, so a
scenario run after midnight gets a report a day nearer than written. All
three saved AMD outputs from that run put the report "today"; every saved
AMD output from the runs that stayed within the 8th (the 16-run batch and
both after-fix runs) says "tomorrow". That changes its timing, not its
moves, so the multiples count stands.

## After the fix (df00fa6)

| Run | Judge | Multiples check |
|---|---|---|
| Six scenarios, 8 each (20261008-041221_brief.json) | 47/48 | 48/48 |
| `mixed_move_report_tomorrow`, 16 more (20261008-041442_brief.json) | 16/16 | 15/16 |

**The one multiples failure was the check's error, not the model's.** It
flagged "in the last three quarters it beat estimates each time yet posted
negative abnormal moves twice", a count of reports, not a comparison of
moves. The same output compared the moves in points: "3.6 points more
than the market and 2.2 points more than the median of its AI compute
peers". So after the fix, **0 of 64 runs stated a multiple**.

The judge's one failure was `company_drop_peers_flat` again, rule (a):
"suggests the guidance cut and customer-specific weakness are being read
as issues particular to Western Digital".

## Result

| Criterion | Needed | Result |
|---|---|---|
| 1. Multiples check after the fix | at most 1 of 64 | **1 of 64**, a false positive; 0 real |
| 2. Judge after the fix | 42/48, none below 6/8; 13/16 extra | **47/48**, lowest 7/8; **16/16** |
| 3. Other deterministic checks | all 64 runs | **all pass** |

All three hold.

**Before and after, `mixed_move_report_tomorrow`:** 6 of 24 runs stated a
multiple before, 0 of 24 after (Fisher's exact test, two-sided, p = 0.02).
Counting only the 16-run batches, whose dates match, it is 4 of 16 against
0 of 16 (p = 0.10), which on its own would not clear the noise. The
multiples the fix removed were roughly right ones; the wrong kind, "twice
the market", didn't appear in either run, so the run shows the habit going,
not a wrong figure being prevented.

**The analyses now cite the gaps.** Every saved after-fix AMD output gives
both gaps in points, "3.6 points more than the market", the figure that
had been missing from its input; WDC's gave "9.8 points steeper than its
peer group", which is `vs_peers`.

## The check, corrected afterwards

`\b(twice|thrice)\b` caught "twice" as a count. It now needs a comparison
after it ("twice as", "twice the" and similar), with the false-positive
sentence added to the tests as one that must pass. Re-scoring the saved
outputs with the narrower pattern is exact, because every output the old
pattern flagged was saved as a failed run, and a narrower pattern can only
flag fewer: the before runs still show all 6, the after runs 0, and across
all 69 saved analyses only that one flag goes.

**An unrelated judge miss, for the record.** One after-fix AMD output said
the fall "may reflect positioning ahead of the event rather than any
specific news today", a cause no data supplied. The judge passed it. Rule
(a) is meant to catch exactly that.

Spend: about $1.80 for both rounds, estimated from prompt sizes at list
prices rather than metered.
