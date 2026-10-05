# Tuning the brief prompt, October 2026

What changed in `BRIEF_SYSTEM` (web/app.py), why, and what it did to the
eval. Model: claude-sonnet-4-5 throughout; 8 runs per scenario.

## Setup (committed before the baseline, d4684a7)

- **Train** (failures read, prompt changed against them): quiet_day,
  sector_selloff, outside_mover, theme_selloff_one_holds_up -- 32 trials.
- **Test** (held out; outputs not read until tuning ends): single_crash,
  quiet_themes_one_mover, and three scenarios written for this --
  quiet_themes_no_events, single_mover_with_headline,
  theme_rally_policy_headline -- 40 trials.
- One rubric fix first: rule (a) split 2/5 on a saved brief that hedged one
  sentence and asserted the next; after adding "a hedge in one sentence
  doesn't license an assertion in another" it was 0/5, and a fully hedged
  brief still passed 3/3.
- Noise: with ~32 trials a set, a difference under ~25 percentage points
  isn't distinguishable from run-to-run variation.
- Budget: $8 for the whole exercise; at most 3 rounds.

## Baseline (d4684a7)

| | judge pass |
|---|---|
| Train | 13/32 (41%) |
| Test | 14/40 (35%) |

Every deterministic check passed; all failures were judge verdicts. Reading
the 19 train failures:

- **Posture or verdict, 10.** quiet_day 7: a closing line passing judgement on
  the day or forecasting it -- "It's a holding pattern until something changes
  the setup", "a waiting day across the board", "any movement will come from
  general market direction". outside_mover 3: conditionals about the reader --
  "If you're tracking anything in pharma...".
- **Asserted cause, 8.** sector_selloff 4 and theme_selloff 4, all through
  idioms the rule didn't name: "on news that", "following a report that",
  "after contract prices fell", "is driving", "the immediate driver".
- **Other, 1.** Background the data didn't contain.

The prompt itself invites both. Its causation rule names only
"as/after/because", and its outline ends with "What's coming this week they
should prepare for" -- an instruction to tell the reader how to approach the
week.

## Round 1 -- the causation rule is about meaning (ec3e672)

Change: the rule now says any wording that makes a headline the thing moving
prices states the cause, with generic examples ("on news that...", "is
driving...", "weighing on"), and requires a correlational link in every
sentence that pairs a headline with a move.

| | baseline | round 1 |
|---|---|---|
| sector_selloff | 4/8 | 6/8 |
| theme_selloff_one_holds_up | 4/8 | 7/8 |
| outside_mover | 4/8 | 5/8 |
| quiet_day | 1/8 | 1/8 |
| **Train** | **13/32 (41%)** | **19/32 (59%)** |

Asserted-cause failures fell from 8 to 3, and the two scenarios the change
aimed at went from 8/16 to 13/16 -- beyond the noise floor on their own,
though the train total's +18 points is just under it. quiet_day, which the
change didn't address, didn't move.

Reading quiet_day's 7 failures turned up a conflict inside the prompt. Five
are closing verdicts ("A day to check in briefly rather than scrutinize").
Two failed rule (c) for "AAPL, MSFT and KO have nothing scheduled this week"
-- the scenario carries no calendar data at all -- and that sentence is,
word for word, the prompt's own example of how to state calendar facts.
The prompt was teaching an ungrounded claim.

## Round 2 -- end on a fact; describe the market, not the reader (485465a)

Change: outline item 4 asks for earnings in the next week as the data gives
them, and to leave the item out rather than fill it with a verdict; the
posture rule names where advice hides (the closing line, a conditional about
the reader) and says to end on the last fact; the ungrounded calendar
example is replaced with a grounded one.

| | baseline | round 1 | round 2 |
|---|---|---|---|
| quiet_day | 1/8 | 1/8 | 4/8 |
| sector_selloff | 4/8 | 6/8 | 8/8 |
| outside_mover | 4/8 | 5/8 | 7/8 |
| theme_selloff_one_holds_up | 4/8 | 7/8 | 8/8 |
| **Train** | **13/32 (41%)** | **19/32 (59%)** | **27/32 (84%)** |

Train passed the 80% stopping line after two of the three rounds allowed.
Of the five remaining failures, one was the judge itself returning prose
instead of JSON (which counts as a failure by design), one an asserted cause
("up 0.2% on a headline"), one background the data didn't contain
("pre-market volumes are typically light"), one borderline ("no
company-specific news driving any of the three names").

## Result: the held-out test set (485465a)

Run once, after tuning stopped; none of these outputs had been read before.

| Test scenario | baseline | after |
|---|---|---|
| single_crash | 4/8 | 7/8 |
| quiet_themes_one_mover | 2/8 | 5/8 |
| quiet_themes_no_events | 4/8 | 7/8 |
| single_mover_with_headline | 1/8 | 6/8 |
| theme_rally_policy_headline | 3/8 | 6/8 |
| **Test** | **14/40 (35%)** | **31/40 (78%)** |

**+43 points on cases the changes weren't fitted to**, about twice the
noise floor, and every test scenario improved -- including the three written
for this, whose surface details (a recall, a grid-connection ruling, an
all-quiet theme day) don't appear in the train set.

What's left, and what would address it:

- **Calendar claims, 4.** "No earnings reports scheduled for the coming
  week." The brief's input doesn't say whether a name reports soon -- only
  an attention reason like "earnings in 3d" does, when there is one -- so
  the prompt can't make the claim checkable. The fix is in the code: give
  each name its next report date in the brief's input. (One of the four was
  "No earnings scheduled in the data provided", which is literally true; the
  judge was strict there.)
- **Asserted cause, 4.** Fewer and subtler: "the one headline driving
  action", "investors are weighing both the direct costs...".
- **Judge format, 1.** A prose verdict instead of JSON. Parsing the JSON out
  of a prose reply would stop the harness charging the brief for the
  judge's formatting.

Spend: about $5 of the $8 budget -- baseline $2, two train rounds about
$0.9 each, the test run about $1, judge-stability checks about $0.1.

## Afterwards: the two fixes outside the prompt (97176f2, 65a8e2d)

The leftovers above pointed at the harness and the brief's input rather than
the prompt, so both were fixed and the eval rerun.

- **The judge's verdict is read wherever it sits**, with room to finish
  (max_tokens 250 -> 600). The prose replies had been cut off before any
  verdict and charged to the brief.
- **Each name carries next_earnings_in_days** in the brief's input, null when
  no date is known; the prompt says how to read it.

| | after tuning (485465a) | after the fixes (65a8e2d) |
|---|---|---|
| Train | 27/32 (84%) | 30/32 (94%) |
| Test | 31/40 (78%) | 38/40 (95%) |

The calendar failures and the judge-format failures are gone; quiet_day went
4/8 -> 8/8 and theme_rally_policy_headline 6/8 -> 8/8. Four failures remain:
two subtler asserted causes ("whatever drove VRT", "the only headline
mattering to these three names"), one real slip (LLY and NVO "on your
watchlist's radar" -- they aren't on it), and one judge misreading -- it
called "AAPL and KO report earnings in roughly 30 days" invented when the
data says exactly that.

Strictly, the test set has now been read, so 95% is no longer an untouched
held-out number; the honest headline for the prompt work stays 35% -> 78%,
and this table shows what fixing the input and the harness added on top.
