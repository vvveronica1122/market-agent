# Tuning the stock-analysis prompt, October 2026

`ANALYSIS_SYSTEM` (web/app.py) writes the paragraph on every stock page.
Same method as [the brief](brief-prompt-2026-10.md): split committed before
the baseline (04019ac), train failures read, one principle a round, the
held-out test set run once at the end. Model: claude-sonnet-4-5; 8 runs a
scenario.

- **Train**: theme_drop_before_earnings, company_drop_peers_flat,
  injected_headline -- 24 trials.
- **Test** (held out): theme_rally_with_upgrade_headline,
  mixed_move_report_tomorrow, company_rise_no_news -- written for this.

## Baseline (04019ac)

| | judge pass |
|---|---|
| theme_drop_before_earnings | 8/8 |
| company_drop_peers_flat | 3/8 |
| injected_headline | 6/8 |
| **Train** | **17/24 (71%)** |
| **Test** | **18/24 (75%)** |

**A limit worth stating up front.** With 24 trials a set the noise floor is
about +/-28 points, and the test baseline leaves 25 points of headroom: even a
perfect score couldn't clear the noise on 8 runs. The final test run uses 16
runs a scenario to narrow it, and its result should still be read as
directional.

Six of the seven train failures explain the move rather than report it,
mostly through what investors supposedly think: "The magnitude of the
selloff suggests investors are concerned about...", "the sharp divergence
suggests the demand weakness may be specific to...", "the coverage
attributes the sell-off to..." (no item says that). The seventh is
background the data doesn't contain (what Vertiv's equipment does).

The prompt invites it: its outline asks for "what the coverage says may be
driving it, and what is coming up that's worth watching", and its causation
rule is one line -- "may be related to" rather than "because of".

## Round 1 -- report the coverage, don't explain the move (7d703de)

Change: the outline asks for what the coverage reports, set beside the move,
and the next dated event stated as a fact; the causation rule becomes the
brief's (meaning, not "because"), adding that explaining a move through what
investors supposedly think states a cause too, and that coverage can't be said
to attribute a move unless an item does.

| | baseline | round 1 |
|---|---|---|
| theme_drop_before_earnings | 8/8 | 8/8 |
| company_drop_peers_flat | 3/8 | 6/8 |
| injected_headline | 6/8 | 8/8 |
| **Train** | **17/24 (71%)** | **22/24 (92%)** |

Past the 80% line in one round. Both remaining failures are borderline: an
outlook cut reported in the sentence after the move with no connective, and
"due to slower hard-drive orders" -- the company's own stated reason for its
outlook, which is in the data, read by the judge as a cause for the share
price.

## Result: the held-out test set (7d703de, 16 runs a scenario)

| Test scenario | baseline (8 runs) | after (16 runs) |
|---|---|---|
| theme_rally_with_upgrade_headline | 6/8 | 16/16 |
| mixed_move_report_tomorrow | 7/8 | 13/16 |
| company_rise_no_news | 5/8 | 16/16 |
| **Test** | **18/24 (75%)** | **45/48 (94%)** |

**+19 points, with a 95% interval of about +/-19** -- right at the edge, as
the headroom warned. The two scenarios built around the failure modes the
round targeted (a company headline beside a theme-wide move; a solo move with
no coverage) went to 16/16. mixed_move_report_tomorrow's 13/16 is within noise
of its 7/8; of its three failures one is real (describing what "will" happen
after the report), one is the judge's error ("October 6th" is in the data's
events, which it saw), and one is borderline ("today's decline appears
unrelated to imminent earnings").

Spend: about $2.7 for the analysis work (baseline $1.2, one train round $0.5,
the 16-run test $1), on top of $2 rechecking the brief after its fixes.
