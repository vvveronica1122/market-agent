# Multiples enforced in code, October 2026

The stock analysis is told never to compare moves as multiples ("twice as
much as its peers"). As a prompt rule that held in about 1% of runs, and
leaked in 3 of 40 once the headlines-only change left the model less news
to write about ([news-degraded-2026-10.md](news-degraded-2026-10.md)). That
branch is waiting on this fix.

## The change

- **`guards.py`** holds the multiples patterns, moved out of
  `evals/checks.py`, so the app and the evals use one definition.
- **`analyze()`** checks every analysis with them. On a hit it asks the
  model once to rewrite, quoting the sentence and pointing at the gaps in
  points. The rewrite is used only if it is clean; if it still has a
  multiple, or the call fails, the first text stands, and the evals count
  it.
- **The analysis evals** keep each rewrite beside the text it replaced,
  so what the guard changed can be read.

This is built on `news-degraded`, so its runs also decide that branch.

Model: claude-sonnet-4-5. Budget: $4.

## Plan, written before any run

**Before: no new run.** The app code without the guard is aa85a70's,
already measured with this check on 112 runs (20261008-195550,
20261008-195700, 20261008-223313 and 20261008-223629):

| Scenario | Runs | Multiples |
|---|---|---|
| `mixed_move_report_tomorrow` | 32 | 2 |
| `headlines_only` | 40 | 3 |
| The other five | 40 | 0 |
| **Total** | **112** | **5** |

**After.** On this plan's fix commit:

- All seven analysis scenarios, 8 runs each (56).
- `mixed_move_report_tomorrow` and `headlines_only`, 16 more each, where
  the multiples appeared: 24 runs of each in all.

That is 88 runs, about $1.30 plus any rewrites.

**Pass criteria.** Merge this branch, and with it `news-degraded`, only if
all five hold:

1. The multiples check fails in at most 1 of the 88 runs.
2. `headlines_only` passes the judge in at least 21 of 24 (the headlines-
   only change's own bar, 14 of 16, at this size).
3. The other six scenarios: at least 42 of 48 judge passes in the
   seven-scenario run, none below 6 of 8; and at least 13 of 16 in the
   extra `mixed_move_report_tomorrow` runs.
4. Every other deterministic check passes in all 88 runs.
5. Every rewrite, read beside its original, changes the comparison and
   adds nothing that is in neither the original nor the data.

The rewrite rate is reported as a cost, with no bar: each rewrite is one
more model call on that page.
