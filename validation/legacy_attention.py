"""
The attention score as the app ran it until November 2026, frozen.

validation/attention.py and validation/attention_v2.py measure this rule as
"score". They used to call the app's compute_attention; when the app moved
to the rule picked in attention-2026-11.md (anomaly_er), this copy kept the
old one so both scripts still print the numbers in their records. It is
web/app.py's compute_attention, days_until_earnings and local_today at
commit 1b98538, unchanged. Nothing in the app imports it.
"""

from __future__ import annotations

from datetime import date, datetime


def local_today() -> date:
    """The app's "today": the local date, read in one place so the evals can
    pin it for a whole run. Read per call, an eval run that crossed midnight
    moved its fixtures' reports a day nearer than written."""
    return datetime.now().date()


def days_until_earnings(events: dict | None) -> int | None:
    raw = (events or {}).get("next_earnings_date")
    if not raw:
        return None
    text = str(raw)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            when = datetime.strptime(text, fmt).date()
            return (when - local_today()).days
        except ValueError:
            continue
    return None


def compute_attention(price, news, events, market_pct, peer_pct=None, missing=()) -> dict:
    """The rank and its reasons. `missing` names the inputs that failed to
    load ("news", "events"); a price without a change counts as missing
    too. Those parts score nothing, so the level can be too low but never
    too high: high and medium stand, and quiet becomes "incomplete" --
    otherwise a broken source reads as a calm company."""
    factors: list[dict] = []
    # Each part kept separately, so the page can show how a company got its
    # rank instead of asking the reader to trust a number.
    parts = {"move": 0.0, "relative": 0.0, "earnings": 0.0, "news": 0.0}

    pct = (price or {}).get("change_percent")
    if pct is not None:
        parts["move"] = min(abs(pct) * 8, 45)
        if abs(pct) >= 2:
            # "move", not "today": outside market hours this is the last
            # session's move, and the page says which session that was.
            factors.append({"label": f"{pct:+.1f}% move", "tone": "up" if pct > 0 else "down"})

        # A move only means something relative to what it should be measured
        # against. Inside a theme that's the company's peers: -6% when its
        # peers are -6% is the theme's story, told once on the theme card;
        # -6% when they're flat is this company's. With no peer group to
        # hand, fall back to the market: -3% on a day SPY is -3% isn't news.
        reference, label = (peer_pct, "vs peers") if peer_pct is not None else (market_pct, "vs market")
        if reference is not None:
            relative = pct - reference
            if abs(relative) >= 1.5:
                parts["relative"] = 12
                factors.append(
                    {
                        "label": f"{relative:+.1f}pt {label}",
                        "tone": "up" if relative > 0 else "down",
                    }
                )

    days = days_until_earnings(events)
    if days is not None and 0 <= days <= 14:
        parts["earnings"] = 25 if days <= 7 else 12
        label = "earnings today" if days == 0 else f"earnings in {days}d"
        factors.append({"label": label, "tone": "neutral"})

    count = len(news or [])
    if count:
        parts["news"] = min(count * 3, 12)
        if count >= 3:
            factors.append({"label": f"{count} headlines", "tone": "neutral"})

    missing = sorted(set(missing) | ({"price"} if pct is None else set()))
    for name in missing:
        factors.append({"label": f"{name} unavailable", "tone": "neutral"})

    score = sum(parts.values())
    level = "high" if score >= 45 else "medium" if score >= 20 else "quiet"
    if missing and level == "quiet":
        level = "incomplete"
    return {"score": round(score, 1), "level": level, "factors": factors,
            "parts": {k: round(v, 1) for k, v in parts.items()},
            "reference": "peers" if peer_pct is not None else "market",
            "missing": missing}
