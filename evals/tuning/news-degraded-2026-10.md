# Headline-only news, said as such, October 2026

When a ticker's own Yahoo news feed is empty, `get_recent_news` falls back
to Yahoo's search, which returns a headline and a publisher and no
summary. A live check on 8 October found every ticker's feed empty (NVDA,
AAPL, MU, VRT, TSM, GOOGL: 0 items each, 6 returned from search, 0 with a
summary), so today every stock page's news is headlines only.

Nothing said so:

- **The items** carried no mark of where they came from; an empty
  `summary` was the only trace.
- **The analysis prompt** told the model "Each headline now comes with a
  short summary of the piece. Use them", and to say what the coverage
  "collectively says". For every stock page today that is false, and it
  invites describing articles the model never saw.
- **The page** showed the headlines with nothing underneath and no note,
  so a reader couldn't tell a thin feed from a short one.

The saved evals can't show what this does to the analysis: every scenario
had summaries. So the evidence for the change is the live check and the
prompt's wording, not an observed failure.

## The change

- **The news items** get `source`: `"feed"` from the ticker's own feed,
  `"search"` from the fallback.
- **The analysis prompt** says feed items carry a summary to use, and
  search items are headlines only: report what the headline says, nothing
  about what the article reports beyond it.
- **The stock page** notes under "Recent news" when the headlines came
  from search, without summaries.
- **The evals** get `headlines_only`: TSM down 3.8% on a company-specific
  move, whose only news is three search headlines with empty summaries,
  each one inviting elaboration ("analysts split over 2027 capex", "what
  investors are watching"). It fails an analysis that describes an
  article's content beyond its headline.

Model: claude-sonnet-4-5. Budget: $4.

## Plan, written before any run

**Before.** The commit that adds this plan: the new scenario, in the
shape production gave before the fix (no `source` field, empty
summaries), with `master`'s app code (c6b6212).

- `headlines_only`, 16 runs.
- The other six analysis scenarios, 8 runs each (48), for regression:
  the prompt's paragraph on summaries is rewritten, and every scenario
  reads it.

**After.** The same 64 runs on the fixed code, where the fixtures carry
`source` as production then does.

`headlines_only` is a new scenario for a regression check, not a tuning
target, so it sits in the train split; nothing here is a held-out result.

**Pass criteria.** Merge only if all three hold:

1. `headlines_only` passes the judge in at least 14 of 16 after-fix runs.
   Every failure is read; where the analysis kept to the headlines and
   the judge was wrong, that is recorded as a judge error.
2. The other six scenarios: at least 42 of 48 judge passes after the fix,
   none below 6 of 8.
3. Every deterministic check passes in all 64 after-fix runs.

**If the before run passes `headlines_only` in 15 or 16 of 16,** the
scenario didn't reproduce a failure, and these runs can't show the fix
doing anything for the analysis. That is recorded as such; the change can
still merge on criteria 2 and 3, since the item mark and the page note
are true statements about the data whatever the model does.

## Before the fix (10ec41e)

| Run | `headlines_only` judge | Other six, judge | Deterministic checks |
|---|---|---|---|
| All seven scenarios, 8 each (20261008-194622_brief.json) | 5/8 | 44/48 | all pass |
| `headlines_only`, 8 more (20261008-194732_brief.json) | 5/8 | -- | all pass |

**The failure reproduced: `headlines_only` passed 10 of 16.** All six
failures wrote about the headlines as articles that had been read: "the
coverage ... discusses divided analyst views on 2027 capital
expenditure", "another piece focused on what investors are watching in
monthly sales data", "Coverage mentions uncertainty around the company's
2027 capital expenditure plans". Several said in the same breath that
"the summaries don't detail" more, so the model saw the empty summaries
and described the articles anyway.

Of the other six scenarios, `company_drop_peers_flat` passed 5 of 8: all
three failures were rule (a) on the company's own reason for its outlook
cut ("citing slower hard-drive orders"), the borderline the analysis
tuning already recorded. `theme_drop_before_earnings` lost one run for
misreading the setup ("four of the last four beats" lagged; it was four of
eight).

## After the fix (aa85a70)

| Run | `headlines_only` judge | Other six, judge | Deterministic checks |
|---|---|---|---|
| All seven scenarios, 8 each (20261008-195550_brief.json) | 6/8 | 48/48 | multiples check 1 failure |
| `headlines_only`, 8 more (20261008-195700_brief.json) | 8/8 | -- | multiples check 1 failure |

**`headlines_only`: 14 of 16.** Read against the data:

- One failure looks like the judge's error. "One headline noting analyst
  disagreement over 2027 capital expenditure plans, while another
  references investor focus on monthly sales figures" attributes each
  point to a headline and paraphrases it.
- One is borderline. It too says "one headline noting analysts are split",
  but then "a third piece discusses the stock after its pullback", which
  writes about an article as if read.
- The judge passed one output that opens "The coverage addresses Taiwan
  chip stocks slipping amid analyst disagreement...", the old way of
  writing. So the judge is noisy at this boundary in both directions.

The change in kind is clearer than the count. Of the five saved
after-fix outputs, four attribute their points to headlines ("one headline
noting...", "the headlines point to...", "headlines on..."), and one says
outright that "without article text the specific content behind these
headlines isn't available". Before the fix, every saved output wrote
about "the coverage" or "another piece".

**The multiples check failed twice**, after 0 failures in the 64 runs
before:

- `mixed_move_report_tomorrow`: "declining roughly twice as much as its AI
  compute peers", about right (4.2 against 2.0).
- `headlines_only`: "TSM dropped nearly four times as much" as NVDA, AMD
  and AVGO, which fell 0.4% to 0.8%. That is wrong: 4.75 to 9.5 times.

## Result

| Criterion | Needed | Result |
|---|---|---|
| 1. `headlines_only` judge after the fix | 14/16 | **14/16** (one failure probably the judge's) |
| 2. Other six scenarios | 42/48, none below 6/8 | **48/48** |
| 3. Every deterministic check, all 64 runs | 64/64 | **62/64**: the multiples check failed twice |

**Criterion 3 fails, so by this plan the branch is not merged.**

What the numbers can and can't say:

- `headlines_only` went from 6 failures in 16 to 2 (Fisher's exact test,
  two-sided, p = 0.22). That is not significant on its own; the change in
  how the analyses describe the headlines is the stronger evidence.
- The multiples went from 0 of 64 to 2 of 64 (p = 0.50). That doesn't show
  the change caused them. Across all three runs since the gaps fix the
  rate is 2 in 192, about 1%, against 6 in 24 on the AMD scenario before
  it. The prompt edit here touched only the news paragraph.
- Criterion 3 was written to include the multiples check, at zero
  tolerance. Relaxing it now, having seen the result, is what this method
  exists to prevent, so the branch waits for a decision on a new,
  separately planned check rather than merging on a reading of this one.

Spend: about $1.80 for both rounds, estimated from prompt sizes at list
prices rather than metered.

## Follow-up: did the news change bring the multiples back?

Planned and committed before running, after criterion 3 failed.

**The question.** The multiples check failed in 2 of 64 runs after the fix
and 0 of 64 before. Did the rewritten news paragraph weaken the gaps
fix's rule against multiples, or is this its ordinary residue?

**Runs.** The two scenarios where the multiples appeared, 24 runs each,
on both sides:

- Before: 10ec41e (the plan's commit, without the fix).
- After: this section's commit, whose app code is aa85a70's.

That is 48 runs a side, 96 in all, about $1.35. Only the multiples check
decides; the judge's results are recorded but don't count.

**Decision rule.** Merge if the after-fix runs state a multiple in **at
most 2 of 48**, and **no more than 2 more** than the before-fix runs.
Otherwise don't merge, and look for how the news paragraph interacts with
the multiples rule.

At the roughly 1% rate seen since the gaps fix, 3 or more in 48 would
happen about 1% of the time by chance; at 10%, the kind of regression
worth catching, about 87% of the time. The check is the narrowed one from
c6b6212, on both sides.

## Follow-up result

| Scenario, 24 runs each | Before (10ec41e) | After (d730a21) |
|---|---|---|
| `mixed_move_report_tomorrow`, multiples | 1 (20261008-222558_brief.json) | 1 (20261008-223313_brief.json) |
| `headlines_only`, multiples | 0 (20261008-222915_brief.json) | **2** (20261008-223629_brief.json) |
| **Total** | **1 of 48** | **3 of 48** |

**3 of 48 is more than 2, so by the rule the branch is not merged.**

Every extra multiple came from `headlines_only`: "TSM's drop was more than
five times steeper" and "nearly four times steeper", after "nearly four
times as much" in the first after-fix run. Counting both rounds, that
scenario stated a multiple in 0 of 40 runs before the fix and 3 of 40
after (p = 0.24). The AMD scenario stayed at 1 in 24 on both sides.

A likely reading, not a demonstrated one: before the fix the model spent
its sentences describing "the coverage"; told to keep to the headlines,
it has less to say about the news and more about the move, and TSM's
3.8% fall against peers' 0.4-0.8% invites a multiple. Two of the three
were wrong ("nearly four times"; it is 4.75 to 9.5).

The judge, which doesn't decide here: `headlines_only` passed 17 of 24
before and 19 of 24 after; with the first round, 27 of 40 against 33 of
40 (p = 0.20).

So the news change does what it was for, and the prompt's rule against
multiples, which held at about 1% elsewhere, leaks more when the news is
thin. A prompt rule that leaks under one change will leak under the
next; the branch waits for a fix to that, planned on its own.

Spend for the follow-up: about $1.35, estimated, not metered.

## Merged with the guard

The fix for the multiples was planned and run on its own
([analysis-guard-2026-10.md](analysis-guard-2026-10.md)): the analysis is
now checked for multiples in code and rewritten once on a hit. Built on
this branch, its 88 runs re-measured this change too, and all its criteria
held: `headlines_only` passed the judge in 21 of 24, the multiples check
in 88 of 88. This branch merges with it.
