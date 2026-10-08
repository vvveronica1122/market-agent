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
