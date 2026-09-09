"""
Evaluate the AI writing, not the plumbing.

test_app.py and test_agent.py check deterministic code and cost nothing.
This is different: it calls the real model, so it costs money and takes
time, and it is the only thing here that can catch the brief being
confidently wrong, drifting into giving advice, or missing the one thing
that mattered.

Usage:
    python3 evals/run_evals.py                  # every scenario, once
    python3 evals/run_evals.py --runs 3         # three times each, for variance
    python3 evals/run_evals.py --scenario quiet_day
    python3 evals/run_evals.py --dry-run        # exercise the harness, no API calls

On variance: a single run is an anecdote, not a measurement. The same
prompt can pass on one attempt and fail on the next, so when you change a
prompt and want to know whether it actually improved, use --runs 3 or more
and compare pass RATES.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "evals"))

import app as server  # noqa: E402
from checks import (  # noqa: E402
    check_forbidden,
    check_format,
    check_mentions,
    check_no_invented_tickers,
    judge,
)
from scenarios import SCENARIOS  # noqa: E402

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

CANNED = (
    "The watchlist was quiet today, with nothing moving more than a fraction of a percent "
    "and no headlines worth acting on.\n\n"
    "Nothing on the list reports this week, so the next scheduled event is some way off."
)


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Reply:
    def __init__(self, text):
        self.content = [_Block(text)]


class DryRunClient:
    """Returns canned text so the harness can be exercised for free."""

    class _Messages:
        def create(self, **kwargs):
            if "grading" in kwargs.get("system", "").lower() or "RUBRIC" in str(kwargs.get("messages")):
                return _Reply('{"pass": true, "reason": "dry run -- not actually graded"}')
            return _Reply(CANNED)

    def __init__(self):
        self.messages = self._Messages()


def run_scenario(name: str, spec: dict, runs: int) -> dict:
    print(f"\n{'=' * 74}\n{name}  {DIM}{spec['description']}{RESET}\n{'=' * 74}")

    totals: dict[str, list[bool]] = {}
    for attempt in range(runs):
        brief = server.build_brief(
            spec["rows"], spec["market_pct"], spec["indices"], spec["movers"], spec["headlines"]
        )

        if attempt == 0:
            print(f"\n{DIM}--- what the model wrote ---{RESET}")
            for line in brief.split("\n"):
                print(f"  {line}")
            print(f"{DIM}--- end ---{RESET}\n")

        results: list[tuple[bool, str, str]] = []
        results += check_mentions(brief, spec["must_mention"])
        results += check_forbidden(brief)
        results += check_format(brief)

        passed, reason = judge(server.client, server.MODEL, brief, spec["rubric"])
        results.append((passed, "judge verdict", reason))

        for ok, label, detail in results:
            totals.setdefault(label, []).append((ok, detail))

    for label, outcomes in totals.items():
        oks = [ok for ok, _ in outcomes]
        mark = f"{GREEN}PASS{RESET}" if all(oks) else f"{RED}FAIL{RESET}"
        suffix = "" if len(oks) == 1 else f"  ({sum(oks)}/{len(oks)} runs)"
        print(f"  [{mark}] {label}{suffix}")
        # Show why: a failing run if there is one, otherwise the last detail.
        detail = next((d for ok, d in outcomes if not ok), outcomes[-1][1])
        if detail:
            print(f"        {DIM}{detail}{RESET}")

    failed = sum(1 for outcomes in totals.values() if not all(ok for ok, _ in outcomes))
    return {"checks": len(totals), "failed": failed}


def run_theme_eval() -> dict:
    """Themes get one specific check: no invented tickers."""
    print(f"\n{'=' * 74}\nthemes  {DIM}Grouping movers into stories without inventing names{RESET}\n{'=' * 74}")

    movers = [
        {"ticker": "NVDA", "name": "Nvidia", "change_percent": -6.1, "top_headline": "Chip rules widen"},
        {"ticker": "AMD", "name": "AMD", "change_percent": -5.4, "top_headline": "AMD falls with peers"},
        {"ticker": "MU", "name": "Micron", "change_percent": -7.2, "top_headline": "Memory rules tighten"},
        {"ticker": "LLY", "name": "Eli Lilly", "change_percent": 11.4, "top_headline": "Obesity trial beats"},
    ]
    allowed = {m["ticker"] for m in movers}
    themes = server.extract_themes(movers, [{"title": "Chip export rules widen"}])

    print(f"\n{DIM}--- themes returned ---{RESET}")
    for theme in themes:
        print(f"  {theme.get('theme')}  {theme.get('tickers')}")
        print(f"    {DIM}{theme.get('what')}{RESET}")
    print(f"{DIM}--- end ---{RESET}\n")

    results = [(bool(themes), "returned at least one theme", "")]
    results += check_no_invented_tickers(themes, allowed)
    chip_theme = any(
        {"NVDA", "AMD", "MU"}.issubset(set(t.get("tickers", []))) for t in themes
    )
    results.append((chip_theme, "groups the three chip names into one theme", ""))

    for ok, label, detail in results:
        print(f"  [{GREEN}PASS{RESET}]" if ok else f"  [{RED}FAIL{RESET}]", label)
        if detail and not ok:
            print(f"        {DIM}{detail}{RESET}")

    return {"checks": len(results), "failed": sum(1 for ok, _, _ in results if not ok)}


def judge_stability(name: str, times: int) -> int:
    """Judge ONE fixed brief repeatedly.

    Once results stop being 0/N or N/N and start coming back mixed, you
    need to know whether the brief varied or the judge did. Holding the
    brief constant and re-judging separates the two: if verdicts differ on
    identical text, the disagreement belongs to the judge, and no amount
    of tuning the brief's prompt will settle it.
    """
    spec = SCENARIOS[name]
    print(f"\n{'=' * 74}\njudge stability -- {name}, one brief judged {times} times\n{'=' * 74}")

    brief = server.build_brief(spec["rows"], spec["market_pct"], spec["indices"],
                               spec["movers"], spec["headlines"])
    print(f"\n{DIM}--- the brief being judged (identical every time) ---{RESET}")
    for line in brief.split("\n"):
        print(f"  {line}")
    print(f"{DIM}--- end ---{RESET}\n")

    verdicts = []
    for i in range(times):
        passed, reason = judge(server.client, server.MODEL, brief, spec["rubric"])
        verdicts.append(passed)
        mark = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  [{mark}] run {i + 1}: {DIM}{reason[:110]}{RESET}")

    agreed = sum(verdicts)
    print(f"\n  verdict: {agreed}/{times} pass on identical text")
    if agreed in (0, times):
        print(f"  {DIM}The judge is consistent here. A mixed result in a normal run would")
        print(f"  mean the brief varied, not the judge.{RESET}")
    else:
        print(f"  {DIM}The judge disagrees with itself on the same text. Treat borderline")
        print(f"  failures in this scenario as noise, not something to tune away.{RESET}")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1, help="runs per scenario (variance)")
    parser.add_argument("--scenario", help="run only this scenario")
    parser.add_argument("--dry-run", action="store_true", help="no API calls; exercise the harness")
    parser.add_argument("--skip-themes", action="store_true")
    parser.add_argument("--judge-stability", type=int, metavar="N",
                        help="generate ONE brief, then judge it N times, to measure how much "
                             "of a mixed result is the judge's own noise rather than the brief")
    args = parser.parse_args()

    if args.dry_run:
        server.client = DryRunClient()
        print(f"\n{DIM}{'-' * 74}\nDRY RUN -- no API calls. Every scenario gets the same canned\n"
              f"'quiet day' text, so content checks WILL fail and that is correct.\n"
              f"This only proves the harness runs end to end.\n{'-' * 74}{RESET}")
    elif not server.os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY -- these evals call the real model.")
        print("Use --dry-run to exercise the harness without it.")
        return 1

    if args.judge_stability:
        return judge_stability(args.scenario or "quiet_day", args.judge_stability)

    chosen = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS
    if args.scenario and args.scenario not in SCENARIOS:
        print(f"Unknown scenario. Available: {', '.join(SCENARIOS)}")
        return 1

    checks = failed = 0
    for name, spec in chosen.items():
        outcome = run_scenario(name, spec, args.runs)
        checks += outcome["checks"]
        failed += outcome["failed"]

    if not args.scenario and not args.skip_themes:
        outcome = run_theme_eval()
        checks += outcome["checks"]
        failed += outcome["failed"]

    print(f"\n{'=' * 74}")
    if args.dry_run:
        print(f"{DIM}Dry run complete: {checks} checks executed, {failed} failed.\n"
              f"Failures here are expected -- the canned text can't satisfy every scenario.\n"
              f"What matters is that all {len(chosen)} scenarios ran without crashing.{RESET}")
        print(f"{'=' * 74}\n")
        return 0
    if failed:
        print(f"{RED}{failed} of {checks} checks failed.{RESET}")
    else:
        print(f"{GREEN}All {checks} checks passed.{RESET}")
    print(f"{'=' * 74}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
