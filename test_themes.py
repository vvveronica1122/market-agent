"""
Tests for theme storage. Free, offline, instant.

Every test works in a temporary folder, so your real themes.json is never
touched.

    python3 test_themes.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import themes
from themes import ThemeError


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def raises(fn, *args, **kwargs) -> str | None:
    """The ThemeError message if fn raises one, else None."""
    try:
        fn(*args, **kwargs)
    except ThemeError as exc:
        return str(exc)
    return None


def main() -> int:
    failures = 0
    tmp = Path(tempfile.mkdtemp())
    themes.THEMES_FILE = tmp / "themes.json"
    themes.LEGACY_WATCHLIST_FILE = tmp / "watchlist.json"

    print("\nDefaults")
    state = themes.initial_state()
    tickers = themes.all_tickers(state)
    failures += not check("no company appears in two default themes",
                          len(tickers) == len(set(tickers)), str(tickers))
    failures += not check("every default theme has enough companies for a peer comparison",
                          all(len(t["stocks"]) >= themes.MIN_STOCKS_FOR_PEERS for t in state["themes"]))
    failures += not check("every default company says what it does in the theme",
                          all(s["role"] for t in state["themes"] for s in t["stocks"]))
    failures += not check("notes start empty -- they're the reader's to write",
                          all(s["note"] == "" for t in state["themes"] for s in t["stocks"]))

    print("\nUpgrading from the old watchlist")
    themes.LEGACY_WATCHLIST_FILE.write_text(json.dumps(["NVDA", "mu", "PLTR", "PLTR", "bad ticker!"]))
    migrated = themes.load()
    other = next((t for t in migrated["themes"] if t["id"] == "other"), None)
    failures += not check("names already in a theme aren't duplicated",
                          themes.all_tickers(migrated).count("NVDA") == 1)
    failures += not check("names no theme covers are kept, in an 'Other' theme",
                          other is not None and [s["ticker"] for s in other["stocks"]] == ["PLTR"],
                          str(other))
    failures += not check("the result is saved, so the upgrade happens once",
                          themes.THEMES_FILE.exists())
    themes.LEGACY_WATCHLIST_FILE.unlink()

    print("\nUnreadable file")
    themes.THEMES_FILE.write_text("{ this is not json")
    recovered = themes.load()
    backups = list(tmp.glob("themes.unreadable-*.json"))
    failures += not check("an unreadable file is set aside, not overwritten",
                          len(backups) == 1 and backups[0].read_text() == "{ this is not json")
    failures += not check("and the dashboard starts from the defaults",
                          [t["id"] for t in recovered["themes"]][:4] ==
                          [t["id"] for t in themes.DEFAULT_THEMES])

    print("\nCreating and editing themes")
    state = themes.initial_state()
    new = themes.create_theme(state, "  Quantum   computing ", "qtum", "Early-stage hardware.")
    failures += not check("names are tidied and ids are made from them",
                          new["name"] == "Quantum computing" and new["id"] == "quantum-computing",
                          str(new))
    failures += not check("benchmarks are upper-cased tickers", new["benchmark"] == "QTUM")
    failures += not check("a duplicate name is refused",
                          raises(themes.create_theme, state, "quantum COMPUTING", "SPY") is not None)
    failures += not check("a nameless theme is refused",
                          raises(themes.create_theme, state, "   ", "SPY") is not None)
    failures += not check("a malformed benchmark is refused",
                          raises(themes.update_theme, state, new["id"], benchmark="not a ticker") is not None)
    themes.update_theme(state, new["id"], name="Quantum")
    failures += not check("renaming keeps the id, so links keep working",
                          themes.find_theme(state, "quantum-computing")["name"] == "Quantum")

    print("\nAdding, moving and removing companies")
    themes.add_stock(state, "quantum-computing", "ionq", note="Watching for a first commercial order.")
    failures += not check("a company is added with the reader's note",
                          themes.find_theme(state, "quantum-computing")["stocks"][0]["note"]
                          == "Watching for a first commercial order.")
    message = raises(themes.add_stock, state, "quantum-computing", "NVDA")
    failures += not check("a company already in another theme is refused, with where it is",
                          message is not None and "AI compute" in message, str(message))
    failures += not check("a nonsense ticker is refused",
                          raises(themes.add_stock, state, "quantum-computing", "two words") is not None)

    themes.update_stock(state, "ai-compute", "TSM", note="Monthly sales are the AI demand read.",
                        move_to="quantum-computing")
    failures += not check("moving a company carries its note with it",
                          themes.theme_of(state, "TSM")["id"] == "quantum-computing"
                          and next(s for s in themes.find_theme(state, "quantum-computing")["stocks"]
                                   if s["ticker"] == "TSM")["note"].startswith("Monthly"))

    before = json.dumps(state, sort_keys=True)
    failed = raises(themes.update_stock, state, "quantum-computing", "TSM",
                    note="changed", move_to="no-such-theme")
    failures += not check("a failed move changes nothing, not even the note",
                          failed is not None and json.dumps(state, sort_keys=True) == before)

    themes.remove_stock(state, "quantum-computing", "IONQ")
    failures += not check("a company can be removed",
                          themes.theme_of(state, "IONQ") is None)
    failures += not check("removing a company that isn't there says so",
                          raises(themes.remove_stock, state, "quantum-computing", "IONQ") is not None)
    themes.delete_theme(state, "quantum-computing")
    failures += not check("a theme can be deleted",
                          raises(themes.find_theme, state, "quantum-computing") is not None)

    print("\nLimits")
    full = themes.initial_state()
    for i in range(themes.MAX_STOCKS_PER_THEME - len(themes.find_theme(full, "ai-power")["stocks"])):
        themes.add_stock(full, "ai-power", f"ZZ{i}")
    failures += not check("a theme can't grow past its limit",
                          raises(themes.add_stock, full, "ai-power", "ZZX") is not None)

    print("\nSaving")
    themes.save(state)
    failures += not check("what's saved reads back identically",
                          themes.load() == state)
    failures += not check("no temporary file is left behind",
                          not list(tmp.glob("*.tmp")))

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
