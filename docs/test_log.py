"""
The project log keeps up with the records it summarises.

docs/LOG.md is the one place that says, in order, what the project did and
what was decided. Each tuning or validation record is written when its
work is done, and the log is easy to forget, so this checks that every
record is linked from the log and that every file the log links exists.

    python3 docs/test_log.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "docs" / "LOG.md"


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    failures = 0
    text = LOG.read_text()
    links = {(LOG.parent / target.split("#")[0]).resolve()
             for target in re.findall(r"\]\(([^)\s]+)\)", text)
             if not target.startswith(("http://", "https://", "#"))}

    print("\nEvery record is in the log")
    records = sorted(list((ROOT / "evals" / "tuning").glob("*.md")) + list((ROOT / "validation").glob("*.md")))
    missing = [str(r.relative_to(ROOT)) for r in records if r.resolve() not in links]
    failures += not check(f"all {len(records)} tuning and validation records are linked from docs/LOG.md",
                          not missing, ", ".join(missing))

    print("\nEvery link in the log goes somewhere")
    broken = [str(l) for l in links if not l.exists()]
    failures += not check(f"all {len(links)} local links resolve", not broken, ", ".join(broken))

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
