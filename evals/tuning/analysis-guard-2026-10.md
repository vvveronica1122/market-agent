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

## After the fix (a6841e1)

| Run | Judge | Multiples check | Rewrites |
|---|---|---|---|
| Seven scenarios, 8 each (20261008-225702_brief.json) | 54/56 | 56/56 | 1 |
| `mixed_move_report_tomorrow`, 16 more (20261008-230004_brief.json) | 16/16 | 16/16 | 0 |
| `headlines_only`, 16 more (20261008-230230_brief.json) | 14/16 | 16/16 | 0 |

**The one rewrite**, in `headlines_only`, changed one sentence and nothing
else:

- Before: "peers including Nvidia, AMD, and Broadcom declined less than 1%,
  while TSM dropped nearly four times that amount". That is wrong: 4.75 to
  9.5 times.
- After: "peers including Nvidia, AMD, and Broadcom declined less than 1%,
  with TSM falling 3.2 points more than the median peer", which is
  `vs_peers`.

That run then passed the judge.

**The judge's failures**, read against the data:

- `headlines_only`, three of 24. Two look like the judge's errors: each
  attributes its points to headlines ("the headlines point to analyst
  disagreement over 2027 capital expenditure"), and one adds "without
  article text the specific content behind those headlines isn't
  available". The third is real if small: "analyst disagreement over the
  company's 2027 capital expenditure plans", where the headline is about
  Taiwan chip stocks, not TSM's own plans.
- `company_drop_peers_flat`, one of 8: "suggests the weakness is tied to
  Western Digital's customer base", rule (a), the known borderline.

## Result

| Criterion | Needed | Result |
|---|---|---|
| 1. Multiples check | at most 1 of 88 | **0 of 88** |
| 2. `headlines_only` judge | 21/24 | **21/24** (two failures probably the judge's) |
| 3. Other six scenarios | 42/48, none below 6/8; 13/16 extra | **47/48**, lowest 7/8; **16/16** |
| 4. Other deterministic checks | all 88 runs | **all pass** |
| 5. Rewrites add nothing | every rewrite | **1 rewrite, one sentence changed, correctly** |

All five hold, so this branch, and `news-degraded` with it, can merge.

Multiples in the shown text went from 5 in 112 runs without the guard to
0 in 88 with it (Fisher's exact test, two-sided, p = 0.07). Most of that
gap is the model's own variation, not the guard: in these 88 runs the
model wrote a multiple only once, and the guard caught that one. So the
run shows the mechanism working on the case it met, not a measured rate.
What the mechanism changes is structural: for a multiple to reach the
page, the model now has to write one twice in a row.

The guard asked for a rewrite in 1 of 88 analyses, so its cost is about
one extra model call per hundred stock pages.

Spend: about $1.30, estimated from prompt sizes at list prices rather than
metered.
