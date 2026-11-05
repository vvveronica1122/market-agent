# A model check for "no news" claims about a failed name (November 2026)

Batch 1 ([batch1-2026-11.md](batch1-2026-11.md)) left one item open. When a
watchlist name's news lookup failed, the brief still said, in about 1 run
in 10, that the name or its group had no news. A pattern list in
`guards.py` caught the wordings it was written from and missed the rest:
"without notable headlines", "Nothing newsworthy emerged on those three",
"None generated headlines", "no particular company story explains the
divergence". The eval judge, a model reading for meaning, caught all of
them.

## The change

When a brief's input has a name whose news failed, one extra model call --
a checker with its own short instructions -- reads the brief and lists the
sentences that say or imply that name, alone or as part of a group ("all
three", "the group", "them"), had no news, headlines, stories, catalysts or
developments. It is told not to list sentences only about other named
names, sentences saying the headlines couldn't be loaded, "quiet" about
prices, or calendar sentences. Its sentences join the existing pattern
flags, and the existing rewrite path handles them. If the checker call
fails or its answer can't be read, the pattern flags are used alone. With
no failed news, it makes no call.

## Plan, written before any run

**Fixtures.** Since 7776cb8 every brief fixture row is scored by the app
under test, so the brief's input matches what production sends under the
November attention rule. Runs saved before that were graded on the old
input; none of them is used as a side here.

**Scenarios.**

- `theme_name_data_failed` (train): STX's news and calendar failed.
- `payments_name_data_failed` (test): PYPL's news and calendar failed; V
  reports in five days.
- `news_only_failed` (test, new, written before the checker): AMGN's news
  failed in a quiet biotech group; its report date is known.

**Runs.**

- Before: the commit that adds this plan (the app as on master, with the
  pattern guard and no checker). 24 runs a scenario: enough to show the
  rate the checker starts from.
- After: the checker commit. 48 runs a scenario. At a true failure rate of
  10%, at most 2 of 48 happens by chance 13% of the time; at 2%, 93%.

**Reading**, as in batch 1's fourth follow-up: every run on both sides read
in full; every sentence with news-absence wording listed by a scan of the
whole text; each judge reason set beside the reading, disagreements
re-read. Result files are chosen by commit and scenario. A run fails if it:

1. says or implies the failed name had no news or headlines, by name or as
   part of a group ("them", "the three", "the group", "these names"):
   "quiet on news", "nothing company-specific there", "no headlines";
2. where a report date is unknown, makes an unqualified absence claim about
   the watchlist's calendar ("nothing reports this week", "V is the only
   report this week"), whether or not the name is excepted after it;
3. gives the watchlist's next reports with no word on a name whose date is
   unknown, or excepts it with an absence ("no scheduled date").

It passes with absences limited to known dates or to the other names,
"its headlines couldn't be loaded", and "quiet" about prices alone.

**Criteria, all needed.**

- F1. In each scenario, at most 2 of the 48 after-fix runs fail.
- F2. Every guard intervention, read beside its original, adds nothing
  absent from the data and leaves no reference to a dropped sentence. The
  checker's false flags (sentences it listed that pass the rules) are
  counted, and none of the rewrites they caused may change what a correct
  sentence says.
- F3. Every deterministic check passes in every after-fix run.

The brief scenarios without a failed name are not rerun for this change:
there the checker makes no call (an offline test pins that), and the
pattern guard is unchanged.

**Merge** if F1 to F3 hold; otherwise the branch stays unmerged and the
result is recorded here.

About $7: 72 before-side runs at about $0.025, 144 after-side runs at
about $0.035 with the checker call, plus rewrites.

## Result: F1 and F3 hold, F2 fails; the checker is not merged

Before: `evals/results/20261105-211036_brief.json` (a47146f, 24 runs a
scenario). After: `evals/results/20261105-212920_brief.json` (be8b20c,
48 runs a scenario). Both clean checkouts. Every run read in full, each
rewrite set beside its original, each flagged sentence classified.

| Scenario | Before: fails the rules | After: fails the rules | Judge passes, before / after |
|---|---|---|---|
| `theme_name_data_failed` | 2 of 24 (one borderline) | 1 of 48 (borderline) | 20/24, 44/48 |
| `payments_name_data_failed` | 3 of 24 | 1 of 48 | 23/24, 39/48 |
| `news_only_failed` | 1 of 24 | 1 of 48 | 24/24, 47/48 |

What failed, before:

- theme run 23: "MU, WDC and STX all moved less than a percent ...,
  though none had notable company-specific news";
- theme run 22, borderline: "The group was quiet otherwise";
- payments run 7: "None moved meaningfully or had company-specific
  news";
- payments runs 1 and 11: "Nothing notable on any of them today" and
  "Nothing notable there beyond the divergence from software";
- news-only run 10: "-- the only notable headline across the watchlist".

What failed, after:

- theme run 41, borderline: "The capex headline is the one development
  that appears across your watchlist today";
- payments run 34: "After that the calendar is quiet until CRM in 18
  days", an absence claim about the calendar with no "known", which
  neither guard catches;
- news-only run 21: "-- the only notable item on the list today".

Two readings had to be settled on the way, and each was applied the same
way on both sides:

- "quiet" passes when its sentence is about moves, and fails when worded
  past them ("quiet otherwise", "quiet on news");
- a claim that one item is the *only* news across the whole watchlist
  fails. Ranking a headline among the ones given passes ("the headline
  that matters", which the prompt asks for).

The judge passed all nine of these failures. Over the news and calendar
wording, it also failed ten runs the rules pass. Eight were for "no
known report falls within the next week" or "the only known report this
week", the wording the prompt asks for. Two were for "NOW and ADBE had
no company-specific headlines" and "REGN had no headline", where those
names' news did load and had none. Its other failures were asserted
causes, which the rubric fails and these rules don't cover, and one real
error: "CRM's headlines couldn't be loaded" (payments after, run 10),
when CRM's headline is in the data.

**F1 holds**: one failure in 48 in each scenario. **F3 holds**: all 17
deterministic checks pass in all 144 after-fix runs (and in all 72
before).

**F2 fails.** The guard rewrote 22, 35 and 38 of the 48 after-fix runs
(the before side: 4, 5 and 4 of 24). The checker listed 86 sentences
across 78 rewrites. The pattern list added 7, and 5 of those were real.

- **5 of the checker's 86 sentences fail the rules.** In payments: "All
  three moved little, with no notable company-specific drivers",
  "Nothing eventful there", "Nothing notable moved either the group or
  any individual name", "Nothing notable happened in this group today".
  In news-only: "VRTX, REGN and AMGN all held near flat while presenting
  trial data or lacking news".
- **3 are borderline**: "all three were quiet on the day", "showed no
  company-specific action", "REGN and AMGN were both quiet, though AMGN's
  headlines couldn't be loaded".
- **78 pass the rules**, against its instructions:
  - price-only "quiet": 33 of the 37 news-only flags are "The biotech
    names were quiet, each moving less than 0.3%" and the like;
  - sentences about other named names: "NOW and ADBE moved in step
    without company-specific news", 20 times in payments;
  - the correct disclosure itself: "PYPL's news and events data couldn't
    be loaded", 3 times.

What the rewrites did:

- **Added what isn't in the data.**
  - Payments run 2, after a false flag on NOW and ADBE: "S&P 500" became
    "S&P 100".
  - Payments run 47, after a true catch by the pattern list: "V and MA had
    no headlines today". V's headline is in the data.
- **Removed correct facts, after false flags:**
  - "NOW and ADBE ... without company-specific news" in six runs
    (payments 14, 21, 31, 33, 35, 43);
  - IGV's 2.1% fall (payments 29);
  - STX's move (theme 26);
  - AMGN's move (news-only 14, 24, 26);
  - the S&P and Nasdaq moves (news-only 44).

So the change takes the failure rate from 6 of 72 to 3 of 144, and five of
the runs it saves are the checker's true catches. But it pays for that
with rewrites on most briefs that have a failed name, and some of those
rewrites corrupt or remove correct content. Under the plan the checker
commit (be8b20c) is not merged. The branch `batch2-news-check` keeps it.
The fixture scoring (7776cb8), this plan and this record go to master.

A follow-up would need its own plan. What it would have to fix shows
here:

- the checker lists sentences about other named names and about prices,
  though its instructions say not to;
- rewriting the whole brief to remove one clause also changes other
  sentences.

Two of the five true catches also talk about prices ("moved little",
"held near flat"), so a filter that drops price sentences would lose
them. Nothing has been tried.

## Found on the way, outside this change

- **The new attention chips are read as volume.** The chip "+3.6% move,
  1.6x usual" means 1.6 times the stock's usual daily move. Briefs wrote
  "on nearly twice their typical volume" and "1.6x its usual volume", and
  in news-only run 18 the multiples guard turned the correct "moving 1.6x
  its usual pace" into "on volume 60% above usual". Run 42's final text
  still reads "on activity 60% above its usual level". No volume is in
  the data. This came in with the November attention rule, so the brief
  regression run after it needs to look for it.
- **The multiples guard misses "N times harder".** "dropped six times
  harder than memory" (theme run 36) and "fell three to five times harder"
  (theme run 5) both pass `find_multiple`.
- **Headlines get a time the data doesn't give.** "reported this morning"
  (news-only after, run 9) and "A headline this morning" (before,
  payments 8 and news-only 15). The headline payload carries no time, and
  the prompt's own example says "reported this morning".
- **Calendar arithmetic.** "AMGN reports in nine days, the only name on
  your watchlist reporting within the week" (news-only after, run 39).
