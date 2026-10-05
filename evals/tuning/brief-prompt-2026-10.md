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
