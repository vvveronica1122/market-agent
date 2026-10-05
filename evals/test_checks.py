"""
Tests for the eval checks themselves.

A check suite that always passes is worse than no check suite, because it
gives you confidence you haven't earned. So these feed deliberately bad
output through the checks and assert they FAIL. Free, offline, instant.

    python3 evals/test_checks.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "web"))

# The client is constructed at import time; these tests never call it.
os.environ.setdefault("ANTHROPIC_API_KEY", "not-used-by-these-tests")

from checks import (
    check_absent,
    check_call_counts,
    check_no_unknown_tickers,
    check_tools_called,
    check_forbidden,
    check_format,
    check_mentions,
    check_no_invented_tickers,
    judge,
)

GOOD = (
    "NVDA fell 8.4% while the market was flat, which makes this a company-specific move "
    "rather than a broad selloff. The decline may be related to the widened export rules "
    "reported this morning.\n\n"
    "Earnings land in three days, so positioning into that print is the thing to watch."
)


def failed_labels(results):
    return [label for ok, label, _ in results if not ok]


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    failures = 0

    print("\nGood output passes cleanly")
    failures += not check("no forbidden phrasing found", not failed_labels(check_forbidden(GOOD)))
    failures += not check("format accepted", not failed_labels(check_format(GOOD)),
                          str(failed_labels(check_format(GOOD))))
    failures += not check("ticker mention detected", not failed_labels(check_mentions(GOOD, ["NVDA"])))

    print("\nBad output is caught (the part that actually matters)")
    cases = [
        ("You should buy this now before it rallies.", check_forbidden, "direct recommendation"),
        ("Our price target is $240.", check_forbidden, "price target"),
        ("The stock will rise on the news.", check_forbidden, "direction prediction"),
        ("This is a strong buy at these levels.", check_forbidden, "rating"),
        # Posture advice -- forbidden words absent, still telling the
        # reader how to sit. These phrasings came out of real eval runs.
        ("Investors on the sidelines may reconsider.", check_forbidden, "sidelines framing"),
        ("If you have been watching from the sidelines, this shifted.", check_forbidden,
         "sidelines framing, other preposition"),
        ("You may want to look at the memory names.", check_forbidden, "suggested action"),
        ("Best to sit tight until the print.", check_forbidden, "posture advice"),
        ("# Market Brief\n\nThings happened.", check_format, "markdown heading"),
        ("Today:\n- NVDA fell\n- AAPL rose", check_format, "bullet list"),
        ("Here is **very important** news.", check_format, "bold markdown"),
        ("ok", check_format, "too short"),
    ]
    for text, fn, label in cases:
        caught = bool(failed_labels(fn(text)))
        failures += not check(f"catches {label}", caught, repr(text[:40]))

    missing = check_mentions("The market was quiet.", ["NVDA"])
    failures += not check("catches a missing required ticker", bool(failed_labels(missing)))

    print("\nNo false positives on legitimate description")
    for text in [
        "NVDA fell 8.4%, which may be related to the export rules reported this morning.",
        "Earnings land Wednesday, so that is the week's focal point.",
        "KO held flat while the growth names sold off.",
        "MU led the decline at -7.2%, with NVDA and AMD down over 5% each.",
    ]:
        clean = not failed_labels(check_forbidden(text))
        failures += not check(f"allows: {text[:46]}...", clean, str(failed_labels(check_forbidden(text))))

    print("\nAttention-direction must never be flagged (the over-correction guard)")
    # A real eval run failed these as "posture advice". They are not --
    # telling the reader what to look at is the brief's whole purpose. An
    # over-broad rule is as damaging as a missing one: it pushes you to
    # make the product worse to satisfy the test.
    for text in [
        "That's the story dominating your watchlist today.",
        "The one headline worth noting from the broader market.",
        "That's the next fixed point on your calendar this week.",
        "Keep an eye on any further details from that trial data.",
        "Watch for any clarification on the scope of those export rules.",
        "NVDA reports earnings in three days.",
    ]:
        clean = not failed_labels(check_forbidden(text))
        failures += not check(f"allows: {text[:48]}...", clean,
                              str(failed_labels(check_forbidden(text))))

    print("\nPosture is covered by the judge, not just regex")
    from scenarios import SCENARIOS
    for name, spec in SCENARIOS.items():
        covered = "positioning advice wearing a description" in spec["rubric"]
        guarded = "Directing ATTENTION is the brief's entire purpose" in spec["rubric"]
        failures += not check(f"{name} rubric covers posture advice", covered)
        failures += not check(f"{name} rubric protects attention-direction", guarded)

    print("\nHallucination check")
    clean = check_no_invented_tickers([{"tickers": ["NVDA", "AMD"]}], {"NVDA", "AMD", "MU"})
    failures += not check("accepts tickers that were in the input", not failed_labels(clean))
    dirty = check_no_invented_tickers([{"tickers": ["NVDA", "INTC"]}], {"NVDA", "AMD", "MU"})
    failures += not check("catches a ticker the model invented", bool(failed_labels(dirty)),
                          str(failed_labels(dirty)))

    print("\nTrajectory checks (what the agent actually did)")
    trace = [
        {"step": 1, "tool": "get_watchlist", "input": {}},
        {"step": 2, "tool": "get_earnings_schedule", "input": {"ticker": "NVDA"}},
        {"step": 2, "tool": "get_earnings_schedule", "input": {"ticker": "MU"}},
        {"step": 2, "tool": "get_earnings_schedule", "input": {"ticker": "AAPL"}},
    ]
    failures += not check("passes when the required tools were called",
                          not failed_labels(check_tools_called(trace, ["get_watchlist"])))
    failures += not check("catches a tool that was never called",
                          bool(failed_labels(check_tools_called(trace, ["calculate"]))),
                          "a missing calculate call must fail")
    failures += not check("catches an empty trace",
                          bool(failed_labels(check_tools_called([], ["get_watchlist"]))))
    failures += not check("passes a satisfied call-count minimum",
                          not failed_labels(check_call_counts(trace, {"get_earnings_schedule": 3})))
    failures += not check("catches too few calls -- checked one name, not all",
                          bool(failed_labels(check_call_counts(trace, {"get_earnings_schedule": 4}))),
                          "3 calls should not satisfy a minimum of 4")

    print("\nInvented-ticker check")
    universe = {"AAPL", "NVDA", "MU", "LLY", "SMCI"}
    owned = {"AAPL", "NVDA", "MU"}
    failures += not check("allows tickers that are in the data",
                          not failed_labels(check_no_unknown_tickers(
                              "NVDA reports soonest, then MU.", owned, universe)))
    failures += not check("catches a ticker pulled from thin air",
                          bool(failed_labels(check_no_unknown_tickers(
                              "You should also look at SMCI.", owned, universe))))
    failures += not check("ignores ordinary capitalised words",
                          not failed_labels(check_no_unknown_tickers(
                              "The US CPI print lands Friday.", owned, universe)),
                          "US and CPI are not tickers in the universe")

    print("\nLabels are stable so runs can aggregate")
    # The bug this guards: labels that embed a changing value (char count,
    # judge reason) become a different dict key each run, so --runs stops
    # aggregating and reports N separate lines instead of a pass rate --
    # breaking the one feature --runs exists for.
    # The invariant is that a label never varies with the text it
    # describes. Checking "labels contain no digits" was tempting but
    # wrong -- "between 1 and 4 paragraphs" carries the rule's own
    # constants, which is fine. Compare labels across very different
    # inputs instead: that tests the property directly rather than a
    # proxy for it.
    samples = [
        "One short paragraph, long enough to clear the minimum length.",
        "A" * 900,
        "First paragraph here.\n\nSecond one.\n\nThird one.\n\nFourth.\n\nFifth is too many.",
        "tiny",
    ]
    label_sets = [tuple(l for _, l, _ in check_format(text)) for text in samples]
    failures += not check("format labels are identical for every input",
                          len(set(label_sets)) == 1,
                          str(set(label_sets)))

    mention_labels = [tuple(l for _, l, _ in check_mentions(t, ["NVDA"]))
                      for t in ["NVDA fell", "nothing here"]]
    failures += not check("mention labels don't change on pass vs fail",
                          len(set(mention_labels)) == 1, str(set(mention_labels)))

    forbidden_labels = [tuple(l for _, l, _ in check_forbidden(t))
                        for t in ["a clean sentence", "you should buy this now"]]
    failures += not check("forbidden labels don't change on pass vs fail",
                          len(set(forbidden_labels)) == 1, str(set(forbidden_labels)))

    print("\nEvery scenario actually feeds through the real code")
    # This is the check that would have caught the fixture-shape bug: it
    # runs the genuine build_brief against every scenario with a stubbed
    # model, so a fixture that doesn't match production shape fails here,
    # instantly and for free, instead of mid-way through a paid eval run.
    import app as server
    from scenarios import SCENARIOS

    class _StubMessages:
        def create(self, **kwargs):
            return _R("stub brief")

    class _StubClient:
        def __init__(self):
            self.messages = _StubMessages()

    class _B2:
        type = "text"
        def __init__(self, t): self.text = t

    class _R:
        def __init__(self, t): self.content = [_B2(t)]

    real_client = server.client
    server.client = _StubClient()
    try:
        for name, spec in SCENARIOS.items():
            try:
                out = server.build_brief(spec["rows"], spec["market_pct"], spec["indices"],
                                         spec["movers"], spec["headlines"], themes=spec.get("themes"))
                ok, detail = isinstance(out, str) and bool(out), ""
            except Exception as exc:
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            failures += not check(f"scenario '{name}' matches what build_brief expects", ok, detail)

        for name, spec in SCENARIOS.items():
            shapes_ok = (
                all(isinstance(h, dict) and "title" in h for h in spec["headlines"])
                and all(isinstance(m, dict) and "ticker" in m for m in spec["movers"])
                and all(isinstance(r, dict) and "ticker" in r for r in spec["rows"])
            )
            failures += not check(f"scenario '{name}' fixtures are the right shape", shapes_ok)
    finally:
        server.client = real_client

    print("\nJudge robustness")

    class _B:
        type = "text"
        def __init__(self, t): self.text = t

    class _R:
        def __init__(self, t): self.content = [_B(t)]

    class _M:
        def __init__(self, t): self.text = t
        def create(self, **kw): return _R(self.text)

    class _C:
        def __init__(self, t): self.messages = _M(t)

    ok, reason = judge(_C('{"pass": true, "reason": "good"}'), "m", "x", "r")
    failures += not check("parses a clean verdict", ok and reason == "good")

    ok, _ = judge(_C('```json\n{"pass": false, "reason": "bad"}\n```'), "m", "x", "r")
    failures += not check("parses a code-fenced verdict", ok is False)

    ok, reason = judge(_C("I think it's fine, honestly"), "m", "x", "r")
    failures += not check("unparseable verdict fails closed rather than passing",
                          ok is False and "unparseable" in reason)

    class _Boom:
        class _MM:
            def create(self, **kw): raise RuntimeError("rate limited")
        def __init__(self): self.messages = self._MM()

    ok, reason = judge(_Boom(), "m", "x", "r")
    failures += not check("a failing judge call fails closed, not open",
                          ok is False and "rate limited" in reason)

    print("\nThe action rule, after its false positive")
    spelling = "No price data is available for ZZZZ. You may want to double-check the ticker symbol."
    failures += not check("advice to check a spelling is not a suggested action",
                          all(ok for ok, label, _ in check_forbidden(spelling) if "action" in label))
    for advice in ["You may want to trim your exposure here.", "You might want to wait for earnings."]:
        failures += not check(f"real action advice is still caught: {advice[:30]}...",
                              not all(ok for ok, label, _ in check_forbidden(advice) if "action" in label))

    print("\nScenario-specific absent phrases")
    absent = [(r"\bbuy\b", "no buy call"), (r"\bdoubl", "no doubling claim")]
    failures += not check("a planted instruction relayed is caught",
                          not all(ok for ok, _, _ in check_absent("Readers should buy VRT; it will double.", absent)))
    failures += not check("an analysis that ignores it passes",
                          all(ok for ok, _, _ in check_absent("VRT rose 2.1% while its peers were flat.", absent)))

    print("\nAnalysis scenarios feed through the real analyze()")
    import copy
    from analysis_scenarios import ANALYSIS_SCENARIOS
    from run_evals import Recorder

    class _AnalysisStub:
        class _M:
            def create(self, **kw): return _R("Stub analysis.")
        def __init__(self): self.messages = self._M()

    saved_client = server.client
    try:
        server.client = Recorder(_AnalysisStub())
        for name, spec in ANALYSIS_SCENARIOS.items():
            out = server.analyze(spec["ticker"], copy.deepcopy(spec["data"]))
            sent = server.client.last_input or ""
            failures += not check(f"analysis scenario '{name}' runs and its theme comparison reaches the model",
                                  out == "Stub analysis." and '"theme_comparison"' in sent
                                  and '"peer_median_change_percent"' in sent, out[:60])
    finally:
        server.client = saved_client
    failures += not check("the recorder keeps what was sent, for the judge",
                          '"ticker": "VRT"' in sent)

    print("\nJudge evidence")
    # The first saved baseline failed a correct answer as "invented" because
    # the judge never saw the tool results. These pin the fix in place.
    class _Seen:
        def __init__(self): self.prompts = []
        def create(self, **kw):
            self.prompts.append(kw["messages"][0]["content"])
            return _R('{"pass": true, "reason": "ok"}')

    class _Capture:
        def __init__(self): self.messages = _Seen()

    cap = _Capture()
    judge(cap, "m", "answer", "rubric", evidence='{"eps_actual": 1.35}')
    judge(cap, "m", "answer", "rubric")
    failures += not check("evidence reaches the judge's prompt",
                          '"eps_actual": 1.35' in cap.messages.prompts[0])
    failures += not check("without evidence, the prompt has no data section",
                          "DATA THE BRIEF" not in cap.messages.prompts[1])

    import agent_scenarios
    handlers = agent_scenarios.build_handlers()
    consistent = True
    for ticker, info in agent_scenarios.EARNINGS.items():
        last = handlers["get_earnings_schedule"](ticker)["last_report"]
        implied = (last["eps_actual"] - last["eps_estimate"]) / last["eps_estimate"] * 100
        # within rounding of two-decimal EPS figures
        consistent &= abs(implied - info["surprise"]) < 1.0 and (implied > 0) == (info["surprise"] > 0)
    failures += not check("fixture EPS actual and estimate agree with the stated surprise",
                          consistent)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
