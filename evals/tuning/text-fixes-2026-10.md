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

- `next_report_buried` (brief): 8 runs.
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
