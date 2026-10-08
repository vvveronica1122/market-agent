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
