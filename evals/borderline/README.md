# Borderline cases

Real model output that sat right on the edge of a rubric, saved verbatim.

These exist because a normal eval run generates fresh text every time, so
the moment you want to pin down *one specific ambiguous sentence* you
can't — it won't reappear on demand. Saving it turns a one-off argument
into a fixture you can re-judge whenever the rubric changes.

Judge one repeatedly:

    python3 evals/run_evals.py --judge-stability 5 --scenario quiet_day \
        --text evals/borderline/quiet_day_catalysts.txt

If the verdict is split on identical text, the standard itself is
ambiguous there, and the honest fix is to sharpen the rubric — not to keep
tuning the brief until this particular phrasing stops appearing.

## quiet_day_catalysts.txt

Failed 1 of 2 runs on rule (b), for: *"If you're watching for catalysts,
the calendar isn't offering any just yet."*

The substance is factual — there genuinely are no scheduled events. What
made it borderline is the second-person conditional framing, which edges
from describing the calendar toward describing what the reader should be
doing about it.

**Resolved: 0/5 on identical text, same reason every run.** The judge is
not ambiguous here at all — it reliably reads that sentence as telling the
reader to wait. So the 1-of-2 failure in normal runs was generation
variance: the brief writes that phrasing sometimes and not others.

Decision: comply rather than argue. The judge is arguably a shade strict,
but the compliant phrasing ("nothing scheduled this week") states the same
fact more directly and reads better, so there is no cost to conforming.
The prompt now says to state calendar facts plainly instead of framing
them around what the reader might be doing.

Worth separating two things that look alike: tuning the brief to meet a
standard that is demonstrably consistent is legitimate. Loosening the
standard so the brief passes is not. The stability run is what tells you
which situation you are in — and here it said the standard was solid.
