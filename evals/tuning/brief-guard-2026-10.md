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
