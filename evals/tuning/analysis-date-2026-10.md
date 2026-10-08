# The stock analysis gets today's date, October 2026

The stock page's analysis was given a report's date but not today's, so it
judged how far away the report was by its own sense of "now", which comes
from its training data. Seven of the 33 analyses saved in
`evals/results/` get that distance wrong:

- "that event is actually still nearly two years away in October 2026",
  for a report due the next day (`mixed_move_report_tomorrow`);
- "the next earnings report isn't until October 2026, well over a year
  away", for one three weeks off (`company_rise_no_news`).

Two of the seven passed the judge, which had no date either. Six come from
the prompt before the analysis tuning (d27aa68), one from the current one
(d95a4ac). The saved outputs are each run's first output plus its
failures, not every run, so they show the error exists but not how often
it happens.

## The change

- **The analysis** (`analyze()` in web/app.py) gets `today` and
  `next_earnings_in_days`, both from the local date that
  `days_until_earnings` already uses, and the prompt says to take any sense
  of how near or far a date is from those two.
- **The judge** gets the date the analysis was written, and the analysis
  rubric gets rule (d): getting the timing of a dated event wrong.

Model: claude-sonnet-4-5. Budget: $4.

## Plan, written before any run

**Before.** The commit that adds this plan: `master`'s app code (e036970)
with the new judge, rubric and harness. The writer has no date; the judge
has it. All six analysis scenarios, 8 runs each (48).

**After.** The same six scenarios on the fixed code, 8 runs each (48).

Four of the six scenarios carry a report date: 1, 3, 21 and 24 days away.
The other two have none and serve as the regression check. These are
regression runs, not tuning; the test split was read in earlier work, so
nothing here counts as a held-out result.

**Pass criteria.** Merge only if all three hold:

1. No after-fix run gets a report's timing wrong. Every rule (d) failure is
   read against the data; where the analysis was actually right, it is
   recorded as a judge error, not a timing error.
2. After the fix, at least 42 of 48 judge passes (about 88%; the last
   measurements were 22/24 train and 45/48 test), and no scenario below
   6 of 8.
3. Every deterministic check (forbidden phrasing, format, absent strings)
   passes in all 48 after-fix runs.

**If the before run shows no timing errors,** the scenarios didn't
reproduce the failure, and this run can't show that the fix does anything.
That is recorded as such. The change can still merge on criteria 2 and 3,
as a preventive fix backed by the saved outputs above, but no improvement
is claimed.

## Before the fix (c419e7a)

**47/48** judge passes (20261008-020224_brief.json). No run failed rule
(d): the 32 runs of the four dated scenarios all passed. The scenarios did
not reproduce the failure, which the saved outputs had suggested was
likely: six of the seven came from the prompt before the analysis tuning.

The one failure was `company_drop_peers_flat`, a scenario with no report
date: "Reuters reports the company lowered its quarterly revenue outlook"
set beside the move without a correlational link, rule (a).

## After the fix (7f8a99f)

**47/48** (20261008-020920_brief.json). The one failure was again
`company_drop_peers_flat` under rule (a), on nearly the same sentence.

## Result

| Criterion | Needed | Result |
|---|---|---|
| 1. No timing errors after the fix | 0 | **0** rule (d) failures |
| 2. Judge passes after the fix | 42/48, none below 6/8 | **47/48**, lowest 7/8 |
| 3. Deterministic checks | all 48 runs | **all pass** |

All three hold. **No improvement is claimed**: the before run had no
timing errors either, so these scores can't show the fix doing anything.
It merges as a preventive change, backed by the saved outputs above and by
the absence of any regression.

**What did change, in the outputs that can be read.** The runner keeps
each scenario's first output and its failures, so 83 of the 96 analyses
were seen by the judge alone. In the four dated scenarios' first
outputs, the before run gave dates only ("scheduled for October 31,
2026"); the after run said how far off each report was, and was right
every time: "in three days, on October 10th", "in 24 days on October
31st", "after tomorrow's close", "October 28, in three weeks". Distance is
the claim that went wrong before, and it is now taken from the data. Four
outputs are an observation, not a rate.

**A fixture problem, found along the way.** Two scenarios set the report
date as an offset from the day the evals run, while their headlines name
a weekday: "Micron will report after the close next Wednesday" beside a
date three days out, "after Tuesday's close" beside one a day out. Run on a
Wednesday, those dates fall on a Saturday and a Thursday. The before run
repeated both mismatches ("next Wednesday, October 10"; "Tuesday's close,
which coincides with ... October 8") and the judge passed them, since
each half is in the data. The after run's AMD output said "tomorrow's
close", from `next_earnings_in_days`, over the headline's weekday. The
scenarios are left as they are here, so both runs saw identical input.

Spend: about $1.40 for both rounds, estimated from prompt sizes at list
prices rather than metered.
