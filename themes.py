"""
Themes: the watchlist, organised the way an investor reads it.

A flat list says nothing about why its names are there or what to measure
them against. A theme does. Each one is a group of companies that share a
driver, plus the benchmark ETF that is the market's yardstick for that
group. Each company carries its role in the theme and, optionally, a note
in the reader's own words about why they're watching it.

Every company belongs to exactly one theme. Peer comparisons are computed
within a theme, so a name counted in two would be compared against two
different peer groups, and theme averages would count it twice.

Storage is one JSON file beside the dashboard, gitignored like the old
watchlist: it's per-machine state, not source.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
THEMES_FILE = PROJECT_ROOT / "web" / "themes.json"
LEGACY_WATCHLIST_FILE = PROJECT_ROOT / "web" / "watchlist.json"

MAX_THEMES = 12
MAX_STOCKS_PER_THEME = 12
# Below this a leave-one-out peer median rests on a single other company,
# which is a comparison with one stock, not with a group.
MIN_STOCKS_FOR_PEERS = 3

TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,11}$")


class ThemeError(ValueError):
    """A request that would leave the themes invalid. The message is shown
    to the user, so it says what to do, not just what went wrong."""


def _stock(ticker: str, role: str) -> dict:
    return {"ticker": ticker, "role": role, "note": ""}


# Roles are factual one-liners about each company's place in the theme.
# Notes start empty: why someone watches a name is theirs to write.
DEFAULT_THEMES = [
    {
        "id": "ai-compute",
        "name": "AI compute",
        "benchmark": "SMH",
        "description": "Accelerators, custom silicon and the foundry that manufactures them.",
        "stocks": [
            _stock("NVDA", "GPU accelerators and data-center systems"),
            _stock("AMD", "Data-center GPUs and CPUs"),
            _stock("AVGO", "Custom AI chips and networking"),
            _stock("TSM", "Contract chip manufacturing (foundry)"),
        ],
    },
    {
        "id": "memory-storage",
        "name": "Memory & storage",
        "benchmark": "SMH",
        "description": (
            "Memory and storage run on their own pricing cycle. No ETF tracks the group "
            "-- SMH holds only MU -- so the peer comparison is the one to read."
        ),
        "stocks": [
            _stock("MU", "DRAM and high-bandwidth memory (HBM)"),
            _stock("SNDK", "NAND flash storage"),
            _stock("WDC", "Hard-disk drives"),
            _stock("STX", "Hard-disk drives"),
        ],
    },
    {
        "id": "megacap-tech",
        "name": "Mega-cap tech",
        "benchmark": "QQQ",
        "description": (
            "A market label more than an industry. These names are a large share of QQQ, "
            "so the comparison with each other matters as much as the one with the ETF."
        ),
        "stocks": [
            _stock("AAPL", "Consumer devices and services"),
            _stock("MSFT", "Cloud (Azure) and software"),
            _stock("GOOGL", "Search, advertising and cloud"),
            _stock("AMZN", "E-commerce and cloud (AWS)"),
            _stock("META", "Social platforms and advertising"),
            _stock("TSLA", "Electric vehicles and energy storage"),
        ],
    },
    {
        "id": "ai-power",
        "name": "AI power & infrastructure",
        "benchmark": "SPY",
        "description": (
            "Where AI capital spending goes after the chips: power generation and the "
            "equipment that delivers it. No ETF spans power producers and electrical "
            "equipment, so SPY is only a broad reference and peers are the real comparison."
        ),
        "stocks": [
            _stock("VST", "Power generation (independent producer)"),
            _stock("CEG", "Power generation, largest US nuclear fleet"),
            _stock("GEV", "Gas turbines and grid equipment"),
            _stock("ETN", "Electrical equipment"),
            _stock("VRT", "Data-center power and cooling"),
        ],
    },
]


# --- reading and writing ---------------------------------------------
def initial_state() -> dict:
    """The default themes, plus anything from the old flat watchlist that
    they don't already cover -- so upgrading never drops a name."""
    state = {"version": 1, "themes": copy.deepcopy(DEFAULT_THEMES)}
    legacy = _read_legacy_watchlist()
    covered = set(all_tickers(state))
    leftovers = [t for t in legacy if t not in covered]
    if leftovers:
        state["themes"].append({
            "id": "other",
            "name": "Other",
            "benchmark": "SPY",
            "description": "Carried over from the old watchlist. Move each name to a theme.",
            "stocks": [_stock(t, "") for t in leftovers],
        })
    return state


def _read_legacy_watchlist() -> list[str]:
    try:
        raw = json.loads(LEGACY_WATCHLIST_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        ticker = str(item).strip().upper()
        if TICKER_RE.match(ticker) and ticker not in seen:
            seen.append(ticker)
    return seen


def load(path: Path | None = None) -> dict:
    path = path or THEMES_FILE
    if not path.exists():
        state = initial_state()
        save(state, path)
        return state
    try:
        state = json.loads(path.read_text())
        _check_shape(state)
        return state
    except (json.JSONDecodeError, ThemeError, OSError) as exc:
        # Keep the unreadable file rather than overwrite it -- it may be
        # hand-edited work -- and start again from the defaults.
        backup = path.with_name(f"themes.unreadable-{datetime.now():%Y%m%d-%H%M%S}.json")
        path.rename(backup)
        print(f"themes.json could not be read ({exc}); moved it to {backup.name} "
              f"and started from the default themes.")
        state = initial_state()
        save(state, path)
        return state


def save(state: dict, path: Path | None = None) -> None:
    path = path or THEMES_FILE
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(path)  # atomic: a crash mid-write can't leave half a file


def _check_shape(state) -> None:
    if not isinstance(state, dict) or not isinstance(state.get("themes"), list):
        raise ThemeError("themes.json has no list of themes.")
    for theme in state["themes"]:
        if not isinstance(theme, dict) or not theme.get("id") or not isinstance(theme.get("stocks"), list):
            raise ThemeError("a theme is missing its id or its list of stocks.")


# --- queries ----------------------------------------------------------
def all_tickers(state: dict) -> list[str]:
    seen: list[str] = []
    for theme in state["themes"]:
        for stock in theme["stocks"]:
            if stock["ticker"] not in seen:
                seen.append(stock["ticker"])
    return seen


def find_theme(state: dict, theme_id: str) -> dict:
    for theme in state["themes"]:
        if theme["id"] == theme_id:
            return theme
    raise ThemeError(f"There is no theme '{theme_id}'.")


def theme_of(state: dict, ticker: str) -> dict | None:
    for theme in state["themes"]:
        if any(s["ticker"] == ticker for s in theme["stocks"]):
            return theme
    return None


# --- validation -------------------------------------------------------
def clean_ticker(raw) -> str:
    ticker = str(raw or "").strip().upper()
    if not TICKER_RE.match(ticker):
        raise ThemeError(f"'{raw}' doesn't look like a ticker symbol, e.g. NVDA.")
    return ticker


def _clean_text(raw, field: str, limit: int, required: bool = False) -> str:
    text = " ".join(str(raw or "").split())
    if required and not text:
        raise ThemeError(f"A theme needs a {field}.")
    if len(text) > limit:
        raise ThemeError(f"Keep the {field} under {limit} characters.")
    return text


def _slug(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "theme"
    slug, n = base, 2
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1
    return slug


# --- changes ----------------------------------------------------------
# Each function changes `state` in place and raises ThemeError instead of
# leaving it half-changed. Callers save only after a change succeeds.
def create_theme(state: dict, name, benchmark, description="") -> dict:
    if len(state["themes"]) >= MAX_THEMES:
        raise ThemeError(f"There's a limit of {MAX_THEMES} themes. Remove one first.")
    name = _clean_text(name, "name", 40, required=True)
    if any(t["name"].lower() == name.lower() for t in state["themes"]):
        raise ThemeError(f"There's already a theme called '{name}'.")
    theme = {
        "id": _slug(name, {t["id"] for t in state["themes"]}),
        "name": name,
        "benchmark": clean_ticker(benchmark or "SPY"),
        "description": _clean_text(description, "description", 300),
        "stocks": [],
    }
    state["themes"].append(theme)
    return theme


def update_theme(state: dict, theme_id: str, name=None, benchmark=None, description=None) -> dict:
    theme = find_theme(state, theme_id)
    if name is not None:
        name = _clean_text(name, "name", 40, required=True)
        if any(t is not theme and t["name"].lower() == name.lower() for t in state["themes"]):
            raise ThemeError(f"There's already a theme called '{name}'.")
        theme["name"] = name
    if benchmark is not None:
        theme["benchmark"] = clean_ticker(benchmark)
    if description is not None:
        theme["description"] = _clean_text(description, "description", 300)
    return theme


def delete_theme(state: dict, theme_id: str) -> None:
    theme = find_theme(state, theme_id)
    state["themes"].remove(theme)


def add_stock(state: dict, theme_id: str, ticker, note="", role="") -> dict:
    theme = find_theme(state, theme_id)
    ticker = clean_ticker(ticker)
    current = theme_of(state, ticker)
    if current is theme:
        raise ThemeError(f"{ticker} is already in {theme['name']}.")
    if current is not None:
        raise ThemeError(f"{ticker} is already in {current['name']}. Each company belongs to one "
                         f"theme -- move it there instead.")
    if len(theme["stocks"]) >= MAX_STOCKS_PER_THEME:
        raise ThemeError(f"A theme holds at most {MAX_STOCKS_PER_THEME} companies.")
    stock = {"ticker": ticker, "role": _clean_text(role, "role", 80),
             "note": _clean_text(note, "note", 200)}
    theme["stocks"].append(stock)
    return stock


def remove_stock(state: dict, theme_id: str, ticker) -> None:
    theme = find_theme(state, theme_id)
    ticker = clean_ticker(ticker)
    before = len(theme["stocks"])
    theme["stocks"] = [s for s in theme["stocks"] if s["ticker"] != ticker]
    if len(theme["stocks"]) == before:
        raise ThemeError(f"{ticker} isn't in {theme['name']}.")


def update_stock(state: dict, theme_id: str, ticker, note=None, move_to=None) -> dict:
    theme = find_theme(state, theme_id)
    ticker = clean_ticker(ticker)
    stock = next((s for s in theme["stocks"] if s["ticker"] == ticker), None)
    if stock is None:
        raise ThemeError(f"{ticker} isn't in {theme['name']}.")
    # Validate everything before changing anything.
    new_note = _clean_text(note, "note", 200) if note is not None else None
    target = None
    if move_to is not None and move_to != theme_id:
        target = find_theme(state, move_to)
        if len(target["stocks"]) >= MAX_STOCKS_PER_THEME:
            raise ThemeError(f"{target['name']} already holds {MAX_STOCKS_PER_THEME} companies.")
    if new_note is not None:
        stock["note"] = new_note
    if target is not None:
        theme["stocks"].remove(stock)
        target["stocks"].append(stock)
    return stock
