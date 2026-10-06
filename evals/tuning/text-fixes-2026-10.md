# Two fixes from the demo snapshot, October 2026

The 5 October demo snapshot's AI text had two errors, both from asking the
model to do work Python should do:

- **The brief named the wrong company as next to report.** It wrote "the
  next scheduled event is VRT and TSLA, both reporting in 16 days", but TSM,
  listed last in its theme, reported in 10.
- **The agent quoted a misleading margin without warning.** Asked to
  compare margins, it ranked WDC first on a 72.9% net margin. That figure
  sits above WDC's 48.9% gross margin, which only one-off gains can
  produce, and the dashboard's peer table flagged it. The agent's tool
  result didn't carry that caveat.

The fixes are on branch `ai-text-fixes`:

- **The brief** gets `upcoming_reports`: the known report dates, sorted
  soonest first in Python.
- **The agent** gets two changes.
  - `get_key_stats` now returns the same caveats the peer table shows, and
    the prompt says to carry a caveat wherever its figure is used.
  - The prompt also says not to supply catalysts the tools didn't return.
    The same snapshot's agent had called Brazilian stocks' rise "likely
    tied to a regional catalyst".

Model: claude-sonnet-4-5. Budget: $6 for all of the runs below.

## Plan, written before any run

**Before.** The two new scenarios, run against the code without the fixes:

- `next_report_buried` (brief): 8 runs. (Replaced; see below.)
- `margins_with_caveat` (agent): 3 runs. Its stub returns no caveats,
  because before the fix production returned none.

**After.** On the fixed branch:

- `next_report_buried`: 8 runs.
- `margins_with_caveat`: 5 runs.
- Regression check on the other 9 brief scenarios: 4 runs each.
- Regression check on the other 4 agent scenarios: 3 runs each.

These are regression runs, not tuning. The brief's test set was read in
earlier work, so these numbers can't serve as a held-out result.

**Pass criteria.** Merge only if all four hold:

1. `next_report_buried` passes at least 7 of 8 after the fix.
2. Across the other brief scenarios: at least 31 of 36 pass (about 86%;
   the last full run was 68 of 72), and no scenario falls below 3 of 4.
3. `margins_with_caveat` passes at least 4 of 5 after the fix.
4. Across the other agent scenarios: at least 10 of 12 judge passes, and
   the tool-call checks fail in no more than one run.

If any criterion fails, the branch is not merged and the failures are read
before anything changes.

## Before the fix

All "before" runs used a worktree of `master` (f9ab266) with the new
scenario files copied in. In the agent's copy, the stub returns no caveats,
as production did before the fix.

**A scenario that didn't reproduce the failure.** `next_report_buried` was a
trimmed version of the snapshot: 12 names in three themes, with no movers
and no headlines. Without the fix it passed **8/8**
(20261006-021706_brief.json), so it couldn't show whether the fix does
anything.

It was replaced by `snapshot_next_report`, which rebuilds the snapshot's own
input from the demo data:

- all 19 names, in four themes, with their moves, attention labels and
  report dates;
- the eight Discover movers;
- the eight market headlines.

No "after" run had been made, so nothing was fitted to results. Criterion 1
now applies to the new scenario.

| Scenario | Before the fix |
|---|---|
| `snapshot_next_report` (brief) | **3/8** (20261006-022036_brief.json) |
| `margins_with_caveat` (agent) | **0/3** (20261006-022131_agent.json) |

**The brief's five failures were all calendar errors:**

- VRT and TSLA named as next;
- TSM said to "follow" them;
- "nothing scheduled before then";
- reports grouped into the wrong week;
- relative days ("four days later") that didn't add up.

**The agent's three answers** all led with MU as having the highest
profit margin, at 58.2%. Two never qualified it. The third did, a
paragraph later, guess at "significant non-operating income or tax
benefits". The rubric fails that one too, because the ranking sentence
carries no caveat and is what a skimming reader keeps. That is strict, and
deliberately so.

Spend so far: about $0.54, measured from token counts at list prices.

## After the fix, round 1 (1dd6c02)

`snapshot_next_report`: **3/8**, which fails criterion 1. Criteria 2-4 were
not run.

The fix did what it was for: none of the eight runs named the wrong
company as next. The five failures were new:

- **Grouping errors, and the judge reading the cut list as the whole data
  (4).** `upcoming_reports` was capped at six entries. The cut fell inside
  the group reporting in 23 days: GEV and GOOGL were in, META and MSFT out.
  Briefs that grouped the calendar ("META, MSFT and AAPL in 23 to 24
  days") were then marked as inventing names missing from the list. Some
  of those verdicts were judge errors, since every name carries its own
  date. The cut list invited both mistakes.
- **A converted date (1).** "STX on January 27th", for a report 22 days
  away (27 October).

## Round 2: every report, with its date

`upcoming_reports` now lists every known report, each with its date as
well as its days away. The prompt says to take timing from that list and
not to convert days into dates. Run on the same scenario before anything
else.

## After round 2 (6668d3a)

`snapshot_next_report`: **5/8**. Still no run named the wrong company as
next, and no converted dates. Of the three failures, two were the rubric's
fault:

- "GOOGL, META, MSFT, GEV and STX -- between 22 and 23 days out" is true,
  and was failed for not listing STX separately.
- Grouping AAPL (24 days) with the 23-day names was failed. The rubric
  listed only part of the calendar, so the judge took its grouping as the
  only correct one.

The third was rule (a), a causation call, on "the AI compute theme drove
today's watchlist". That is a known borderline in the brief, unrelated to
the calendar.

## Round 3: the rubric gets the whole calendar

The rubric now states the full calendar, all 19 names, and says explicitly
that an accurate range is accurate. Without this, the judge was marking
true statements wrong. The brief, the prompt and the input are unchanged
from round 2, so this run re-measures round 2's code with a judge that can
check what it reads.
