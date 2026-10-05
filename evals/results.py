"""
Save an eval run to a file, so a result can be cited later.

A pass rate printed to the terminal is gone when the window closes, and
"it passed when I ran it" isn't evidence anyone else can check. A saved run
records what was measured AND what it was measured against: the model, the
commit (which pins the prompts), and how many runs each rate is out of.

Results land in evals/results/ and are meant to be committed. Dry runs are
saved with a "_dry-run" suffix and gitignored -- they exercise the saving
code, but their canned answers measure nothing.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def summarize(totals: dict[str, list[tuple[bool, str]]]) -> dict[str, dict]:
    """Per-check pass counts from the runners' {label: [(ok, detail), ...]}.

    Keeps one failure reason per check: a rate says how often something
    failed, the reason says what failing looked like.
    """
    return {
        label: {
            "passed": sum(ok for ok, _ in outcomes),
            "runs": len(outcomes),
            "failure": next((detail for ok, detail in outcomes if not ok), None),
        }
        for label, outcomes in totals.items()
    }


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=RESULTS_DIR.parent, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def save_run(kind: str, model: str, settings: dict, scenarios: dict,
             dry_run: bool = False, directory: Path = RESULTS_DIR) -> Path:
    now = datetime.now(timezone.utc)
    status = _git("status", "--porcelain", "--untracked-files=no")
    record = {
        "kind": kind,
        "timestamp": now.isoformat(timespec="seconds"),
        "model": model,
        "commit": _git("rev-parse", "--short", "HEAD"),
        # Uncommitted edits mean the commit alone doesn't say which prompts
        # ran. None means git couldn't be asked.
        "uncommitted_changes": None if status is None else bool(status),
        "dry_run": dry_run,
        "settings": settings,
        "scenarios": scenarios,
    }
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{now:%Y%m%d-%H%M%S}_{kind}{'_dry-run' if dry_run else ''}.json"
    path = directory / name
    path.write_text(json.dumps(record, indent=2, default=str) + "\n")
    return path
