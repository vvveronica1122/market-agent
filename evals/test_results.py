"""
Tests for saving eval runs. Free, offline, instant.

A saved result is only worth citing if it says what it was measured
against, so these check the file records the model, the commit, the run
count behind each rate, and whether it was a dry run.

    python3 evals/test_results.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from results import _git, save_run, summarize


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    failures = 0

    print("\nSummarizing runs")
    totals = {
        "names NVDA": [(True, ""), (True, ""), (True, "")],
        "judge verdict": [(True, "fine"), (False, "asserted causation"), (True, "fine")],
    }
    summary = summarize(totals)
    failures += not check("counts passes out of runs",
                          summary["judge verdict"]["passed"] == 2
                          and summary["judge verdict"]["runs"] == 3, str(summary["judge verdict"]))
    failures += not check("keeps the reason a run failed",
                          summary["judge verdict"]["failure"] == "asserted causation")
    failures += not check("a check that never failed has no failure reason",
                          summary["names NVDA"]["failure"] is None)

    print("\nSaving a run")
    with tempfile.TemporaryDirectory() as tmp:
        real = save_run("brief", "model-x", {"runs": 3}, {"quiet_day": {"checks": summary}},
                        directory=Path(tmp))
        dry = save_run("brief", "model-x", {"runs": 3}, {}, dry_run=True, directory=Path(tmp))
        saved = json.loads(real.read_text())

        failures += not check("records the model", saved["model"] == "model-x")
        if _git("rev-parse", "--git-dir") is not None:
            failures += not check("records the commit the prompts came from",
                                  isinstance(saved["commit"], str) and len(saved["commit"]) >= 7,
                                  repr(saved["commit"]))
            failures += not check("says whether there were uncommitted changes",
                                  isinstance(saved["uncommitted_changes"], bool))
        else:
            # e.g. a zip download: no history to cite, so say so rather than guess
            failures += not check("outside git, commit and changes are recorded as unknown",
                                  saved["commit"] is None and saved["uncommitted_changes"] is None)
        failures += not check("keeps the settings, so a rate's denominator is known",
                              saved["settings"] == {"runs": 3})
        failures += not check("keeps the per-check results",
                              saved["scenarios"]["quiet_day"]["checks"]["judge verdict"]["passed"] == 2)
        failures += not check("a real run is not marked as a dry run", saved["dry_run"] is False)
        failures += not check("a dry run is marked in the file and the name",
                              json.loads(dry.read_text())["dry_run"] is True
                              and dry.name.endswith("_dry-run.json"), dry.name)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
