# Multiples guarded in the home brief, October 2026

The stock analysis is now checked in code for moves stated as multiples
and rewritten once on a hit ([analysis-guard-2026-10.md](analysis-guard-2026-10.md)).
The home page's brief had no such rule, in its prompt or in code. Of the
177 briefs saved in `evals/results/`, three state a multiple, two of them
wrong:

- "The Nasdaq 100 is off 1.2%, more than triple the S&P's -0.4%"; it is
  exactly triple.
- "all five names up between 4.9% and 6.1% -- roughly ten times the
  broader market's 0.4% gain"; it is 12 to 15 times.
- "more than twice the S&P's 0.4% decline", for the same 1.2%: true, and
  understated.

No eval checked for multiples when those briefs were written, so a
passing brief with one was never saved; the real rate is unknown.

## The change

- **`build_brief()`** runs the same guard as the analysis: the shared
  patterns in `guards.py`, one rewrite on a hit quoting the sentence, the
  rewrite used only if clean. The brief's rewrite request asks for the
  moves side by side as their own percentages, which needs no arithmetic.
- **The brief prompt is not changed.** A brief without a multiple comes
  from exactly the same call as before, so only rewritten briefs can
  differ, and those are graded and read one by one.
- **The brief evals** now run the multiples check and keep each rewrite
  beside its original.

Model: claude-sonnet-4-5. Budget: $4.

## Plan, written before any run

**Scenarios.** The two the saved multiples came from:
`sector_selloff` (Nasdaq against the S&P) and
`theme_rally_policy_headline` (a theme against the market). 24 runs of
each, on both sides: 96 runs, about $2.20 plus any rewrites.

- **Before:** the commit that adds this plan: the new check, with
  `master`'s app code (7a1ed85).
- **After:** the fix commit.

These are regression runs, not tuning; the brief's test split was read in
earlier work.

**Pass criteria.** Merge only if all four hold:

1. The multiples check fails in at most 1 of the 48 after-fix runs.
2. Every rewrite, read beside its original, changes the multiple and adds
   nothing that is in neither the original nor the data.
3. Every rewritten brief passes the judge, or, where one fails, reading it
   against its original shows the failure was already in the original.
4. The other deterministic checks (tickers mentioned, forbidden phrasing,
   format) pass in all 48 after-fix runs.

**If the before run shows no multiples in its 48 runs,** the scenarios
didn't reproduce the problem and these runs can't show the guard doing
anything. That is recorded as such. The change can still merge on
criteria 2 to 4, since the guard does nothing unless it finds a multiple.

The judge's pass rates are recorded on both sides for information. Away
from rewrites the two sides make the same call, so a difference there is
run-to-run noise.

## Before the fix (929f45f)

| Scenario, 24 runs each | Multiples | Judge |
|---|---|---|
| `sector_selloff` (20261009-002245_brief.json) | 4 | 19/24 |
| `theme_rally_policy_headline` (20261009-005147_brief.json) | 3 | 21/24 |
| **Total** | **7 of 48** | |

**It reproduced, at about 15%**, far more often than the saved briefs had
suggested. Four of the seven were wrong:

- "The Nasdaq 100 closed down 1.2%, twice the S&P's -0.4% decline", twice
  over; it is three times.
- "roughly ten times the broader market's gain", twice over; it is 12 to
  15 times.

The other three were "more than double" (true, and understated) twice, and
"10 to 15 times" (about right) once.

## After the fix (c19c8da)

| Scenario, 24 runs each | Multiples | Rewrites | Judge |
|---|---|---|---|
| `sector_selloff` (20261009-005539_brief.json) | 0 | 3 | 24/24 |
| `theme_rally_policy_headline` (20261009-005929_brief.json) | 0 | 3 | 21/24 |
| **Total** | **0 of 48** | **6** | |

**Every rewrite**, read sentence by sentence against its original, swapped
the multiple for the two figures side by side and added nothing:

- "more than twice the S&P 500's 0.4% decline" became "while the S&P 500
  fell 0.4%"; "twice the S&P's decline" became "while the S&P fell 0.4%";
  "roughly double" likewise.
- "at least ten times", "more than ten times" (twice) became "while the
  broader market gained 0.4%".
- Two rewrites also reworded the clause after the multiple, with the same
  meaning: "reflecting the weight semiconductors carry in that index"
  became "with tech-heavy names driving the gap"; "consistent with
  tech-heavy selling" became "with tech names bearing more of the
  selling". One merged two sentences about the five names into one.

No rewritten brief failed the judge. The three judge failures, all in
`theme_rally_policy_headline`, were in briefs the guard didn't touch:
two causation calls and one for reporting the names one by one.

## Result

| Criterion | Needed | Result |
|---|---|---|
| 1. Multiples check after the fix | at most 1 of 48 | **0 of 48** |
| 2. Rewrites add nothing | every rewrite | **6 of 6** |
| 3. Rewritten briefs pass the judge | every rewrite | **6 of 6** |
| 4. Other deterministic checks | all 48 runs | **all pass** |

All four hold.

This time the effect is the guard's, not the model's variation: the model
wrote a multiple about as often after the fix (6 of 48) as before (7 of
48; the prompt is unchanged), and the guard rewrote every one. In the text
a reader sees, multiples went from 7 of 48 to 0 of 48 (Fisher's exact test,
two-sided, p = 0.01).

The judge moved from 40/48 to 45/48 over the two scenarios. Outside the
six rewritten briefs the two sides make the same call, so most of that is
run-to-run noise, not the guard.

Cost: the guard asked for a rewrite in 6 of 48 briefs, one extra call
each. The brief is cached for 15 minutes (or until Refresh), so that is
per regeneration, not per page view.

Spend: about $2.40 for both rounds and the rewrites, estimated from prompt
sizes at list prices rather than metered.
