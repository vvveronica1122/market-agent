"""
Judge saved analysis outputs again, with the scenario's current rubric.

A judge verdict on one text is itself a sample: the same text can pass once
and fail the next time. When two sides of a comparison differ by a few
verdicts, re-judging the texts both sides already wrote, several times
each, with one rubric, separates the judge's noise from a real change in
the writing -- and costs only judge calls, no new analyses.

    python3 evals/rejudge.py --scenario company_drop_peers_flat --times 2 \\
        evals/results/BEFORE.json evals/results/AFTER.json --save

The judge sees the same data the analysis was written from, rebuilt by
running the real analyze() against a stub that records the prompt.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "evals"))

import app as server  # noqa: E402
from analysis_scenarios import ANALYSIS_SCENARIOS  # noqa: E402
from checks import judge  # noqa: E402
from results import save_run  # noqa: E402
import run_evals  # noqa: E402


class _Capture:
    """Stands in for the client while analyze() builds its prompt."""

    def __init__(self):
        self.messages = self
        self.prompt = None

    def create(self, **kwargs):
        self.prompt = kwargs["messages"][0]["content"]
        return run_evals._Reply("Captured.")


def evidence_for(name: str) -> str:
    """The data the scenario's analysis is written from, as analyze() sends it."""
    spec = ANALYSIS_SCENARIOS[name]
    real, capture = server.client, _Capture()
    server.client = capture
    try:
        server.analyze(spec["ticker"], copy.deepcopy(spec["data"]))
    finally:
        server.client = real
    return capture.prompt


def rejudge(paths: list[str], name: str, times: int, client) -> dict:
    spec = ANALYSIS_SCENARIOS[name]
    evidence = evidence_for(name)
    today = server.local_today().isoformat()
    record = {"scenario": name, "times": times, "rubric": spec["rubric"], "files": []}
    for path in paths:
        saved = json.loads(Path(path).read_text())
        outputs = saved["scenarios"][f"analysis:{name}"]["outputs"]
        texts = []
        for i, text in enumerate(outputs, 1):
            verdicts = []
            for _ in range(times):
                passed, reason = judge(client, server.MODEL, text, spec["rubric"], evidence, today=today)
                verdicts.append({"pass": passed, "reason": reason})
            texts.append({"run": i, "text": text, "verdicts": verdicts})
        fails = sum(not v["pass"] for t in texts for v in t["verdicts"])
        record["files"].append({"file": Path(path).name, "commit": saved.get("commit"),
                                "texts": texts, "verdicts": len(texts) * times, "failed": fails})
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="saved result files holding the scenario's outputs")
    parser.add_argument("--scenario", required=True, help="an analysis scenario")
    parser.add_argument("--times", type=int, default=2, help="verdicts per saved text")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    if args.scenario not in ANALYSIS_SCENARIOS:
        print(f"Not an analysis scenario: {args.scenario}")
        return 1
    if not server.os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY -- the judge calls the real model.")
        return 1
    run_evals.pin_run_date()
    record = rejudge(args.paths, args.scenario, args.times, server.client)
    for f in record["files"]:
        print(f"{f['file']} ({f['commit']}): {f['failed']} of {f['verdicts']} verdicts failed")
    if args.save:
        settings = {"scenario": args.scenario, "times": args.times, "paths": args.paths}
        path = save_run("rejudge", server.MODEL, settings, record, False)
        print(f"Saved to {path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
