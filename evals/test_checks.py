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
    return [label for ok, label in results if not ok]


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

    print("\nPosture is covered by the judge, not just regex")
    from scenarios import SCENARIOS
    for name, spec in SCENARIOS.items():
        covered = "positioning advice wearing a description" in spec["rubric"]
        failures += not check(f"{name} rubric covers posture advice", covered)

    print("\nHallucination check")
    clean = check_no_invented_tickers([{"tickers": ["NVDA", "AMD"]}], {"NVDA", "AMD", "MU"})
    failures += not check("accepts tickers that were in the input", not failed_labels(clean))
    dirty = check_no_invented_tickers([{"tickers": ["NVDA", "INTC"]}], {"NVDA", "AMD", "MU"})
    failures += not check("catches a ticker the model invented", bool(failed_labels(dirty)),
                          str(failed_labels(dirty)))

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
                                         spec["movers"], spec["headlines"])
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

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
