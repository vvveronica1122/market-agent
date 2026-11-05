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
