"""
Evaluate the agent: does it pick the right tools and answer the question?

Different from run_evals.py, which grades one prompt's prose. Here the
model is choosing what to do, so the trace of tool calls is as much the
output as the text is -- a right answer reached by guessing and a right
answer reached by looking things up read identically, and only the trace
separates them.

Real model (tool choice is a model decision), fake data (so assertions can
be exact). Costs money.

    python3 evals/run_agent_evals.py
    python3 evals/run_agent_evals.py --runs 3
    python3 evals/run_agent_evals.py --scenario needs_math
    python3 evals/run_agent_evals.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "evals"))

import agent  # noqa: E402
from agent_scenarios import SCENARIOS, WATCHLIST, MOVERS, build_handlers  # noqa: E402
from checks import (  # noqa: E402
    check_call_counts,
    check_forbidden,
    check_mentions,
    check_no_unknown_tickers,
    check_tools_called,
    judge,
)

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

KNOWN_TICKERS = set(WATCHLIST) | {m["ticker"] for m in MOVERS} | {"ZZZZ", "SPY", "QQQ"}


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Reply:
    def __init__(self, text):
        self.content = [_Block(text)]
        self.stop_reason = "end_turn"


class DryRunClient:
    class _Messages:
        def create(self, **kwargs):
            if "grading" in str(kwargs.get("system", "")).lower():
                return _Reply('{"pass": true, "reason": "dry run -- not graded"}')
            return _Reply("NVDA reports soonest, in three days, and beat by 10.1% last quarter.")

    def __init__(self):
        self.messages = self._Messages()


def check_markdown(text: str) -> list[tuple[bool, str, str]]:
    """The answer is read in a terminal and a plain chat panel, where
    markdown syntax shows up as literal characters."""
    import re
    results = []
    for pattern, label in [(r"\*\*", "no bold markdown"), (r"^\s*[-*]\s+", "no bullet lists"),
                           (r"^#{1,6}\s", "no markdown headings")]:
        hit = re.search(pattern, text, re.MULTILINE)
        results.append((hit is None, label, "" if hit is None else f"found {hit.group(0)!r}"))
    return results


def run_scenario(name: str, spec: dict, runs: int) -> dict:
    print(f"\n{'=' * 74}\n{name}  {DIM}{spec['description']}{RESET}\n{'=' * 74}")
    print(f"{DIM}Q: {spec['question']}{RESET}")

    totals: dict[str, list[tuple[bool, str]]] = {}

    for attempt in range(runs):
        trace: list[dict] = []
        try:
            answer = agent.ask_agent(agent._eval_client, spec["question"],
                                     verbose=False, trace=trace)
        except Exception as exc:
            answer = f"(agent raised {type(exc).__name__}: {exc})"

        if attempt == 0:
            print(f"\n{DIM}--- tools it chose ---{RESET}")
            for call in trace:
                args = ", ".join(f"{k}={v!r}" for k, v in (call.get("input") or {}).items())
                print(f"  [{call.get('step')}] {call.get('tool')}({args})")
            if not trace:
                print("  (none)")
            print(f"\n{DIM}--- what it answered ---{RESET}")
            for line in answer.split("\n"):
                print(f"  {line}")
            print(f"{DIM}--- end ---{RESET}\n")

        results: list[tuple[bool, str, str]] = []
        results += check_tools_called(trace, spec.get("must_call", []))
        results += check_call_counts(trace, spec.get("min_calls"))
        results += check_mentions(answer, spec.get("must_mention", []))
        results += check_forbidden(answer)
        results += check_markdown(answer)
        # A ticker the user asked about is fair to repeat back, even when
        # it has no data -- saying "no data for ZZZZ" is the correct
        # answer, not an invention.
        asked_about = {w for w in re.findall(r"\b[A-Z]{2,5}\b", spec["question"])}
        allowed = set(WATCHLIST) | {m["ticker"] for m in MOVERS} | asked_about
        results += check_no_unknown_tickers(answer, allowed, KNOWN_TICKERS)

        passed, reason = judge(agent._eval_client, agent.MODEL, answer, spec["rubric"])
        results.append((passed, "judge verdict", reason))

        for ok, label, detail in results:
            totals.setdefault(label, []).append((ok, detail))

    for label, outcomes in totals.items():
        oks = [ok for ok, _ in outcomes]
        mark = f"{GREEN}PASS{RESET}" if all(oks) else f"{RED}FAIL{RESET}"
        suffix = "" if len(oks) == 1 else f"  ({sum(oks)}/{len(oks)} runs)"
        print(f"  [{mark}] {label}{suffix}")
        detail = next((d for ok, d in outcomes if not ok), outcomes[-1][1])
        if detail:
            print(f"        {DIM}{detail}{RESET}")

    failed = sum(1 for outcomes in totals.values() if not all(ok for ok, _ in outcomes))
    return {"checks": len(totals), "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--scenario")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.scenario and args.scenario not in SCENARIOS:
        print(f"Unknown scenario. Available: {', '.join(SCENARIOS)}")
        return 1

    # Swap the data, keep the brain: fixture handlers, real model.
    fixtures = build_handlers()
    agent.HANDLERS.update(fixtures)
    print(f"{DIM}Data stubbed for {len(fixtures)} tools; 'calculate' left real on purpose.{RESET}")

    if args.dry_run:
        agent._eval_client = DryRunClient()
        print(f"{DIM}DRY RUN -- no API calls. Canned answers, so content checks will fail.{RESET}")
    else:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            print("Missing ANTHROPIC_API_KEY -- these evals call the real model.")
            return 1
        agent._eval_client = agent.Anthropic(api_key=key)

    chosen = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS
    checks = failed = 0
    for name, spec in chosen.items():
        outcome = run_scenario(name, spec, args.runs)
        checks += outcome["checks"]
        failed += outcome["failed"]

    print(f"\n{'=' * 74}")
    if args.dry_run:
        print(f"{DIM}Dry run complete: {checks} checks, {failed} failed -- expected with canned "
              f"answers. What matters is that every scenario ran.{RESET}")
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
