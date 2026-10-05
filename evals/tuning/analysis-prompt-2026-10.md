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
