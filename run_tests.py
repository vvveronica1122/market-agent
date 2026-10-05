"""
Run every offline test suite with one command.

    python3 run_tests.py

These are the free, instant suites: no network, no model calls, no API key
needed. They're what CI runs on every push. The evals in evals/ call the
real model and cost money, so they are deliberately not included here.

Each suite is its own script with its own exit code, so they run as
separate processes -- a suite that stubs a module can't leak that stub into
the next one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SUITES = [
    ("dashboard", "web/test_app.py"),
    ("agent loop", "test_agent.py"),
    ("calculator", "tools/test_calc.py"),
    ("eval checks", "evals/test_checks.py"),
    ("eval results", "evals/test_results.py"),
]


def main() -> int:
    results = []
    for label, path in SUITES:
        print(f"\n{'=' * 64}\n{label}  ({path})\n{'=' * 64}", flush=True)
        code = subprocess.run([sys.executable, str(ROOT / path)], cwd=ROOT).returncode
        results.append((label, code))

    print(f"\n{'=' * 64}\nSummary")
    for label, code in results:
        print(f"  [{'PASS' if code == 0 else 'FAIL'}] {label}")
    failed = [label for label, code in results if code != 0]
    print(f"\n{'All suites passed.' if not failed else f'{len(failed)} suite(s) FAILED.'}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
