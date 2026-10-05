"""
Relative performance within a theme: is a move the theme's, or the company's?

A stock's move on its own says little. Down 8% means one thing when its
closest peers are down 8% too, and another when they're flat. This module
answers that with two comparisons per company:

  - against the theme's benchmark ETF -- the market's standard yardstick;
  - against its peers -- the MEDIAN move of the OTHER companies in the same
    theme: the typical peer.

The second exists because cap-weighted ETFs are dominated by the very names
being measured: NVDA is over a fifth of SMH, so "NVDA vs SMH" is partly NVDA
against itself. Leaving the company out of its own peer group removes that.

The median rather than the mean because themes are small. With three or
four peers, one extreme name decides an average: when VRT jumped 6% and its
three peers sat flat, each flat peer's "peer average" became +2%, so all
three were labelled as diverging -- the eval fixture built to test the
brief caught it. Over long windows, SNDK's 625% year-to-date run put WDC 229
points behind its "peers". The median is the typical peer, and one outlier
doesn't move it.

Plain arithmetic on daily percentage changes, no data fetching -- so every
rule here can be tested exactly.
"""

from __future__ import annotations

from statistics import mean, median, pstdev

# A peer median needs at least this many OTHER companies with data; fewer is
# a comparison with one stock, not with a group.
MIN_PEERS = 2

# Moves smaller than this (in percentage points) are left unattributed:
# splitting a 0.4% move into "theme" and "company" parts is noise.
QUIET_MOVE = 1.0

# Attribution measures the GAP between a company and its peers -- own move
# minus peer median, the part its peers don't share -- as a share of the
# larger of the two moves. At or below THEME_GAP it moved with its theme; at
# or above COMPANY_GAP it diverged; in between it's partly shared.
#
# Two rules came before this one, and the first live run broke both.
#
# The first asked whether peers explained at least half the move, with one
# cut-off. Two hard-disk makers fell 10.10% and 10.19% together; their
# peers explained 50.0% of one move and 49.3% of the other, so one came out
# "theme" and the other "company". A single threshold turns near-identical
# moves into opposite labels whenever they sit near it -- hence a middle
# band, so a coin-flip case is reported as one.
#
# The second measured the share of the company's OWN move its peers
# accounted for. That called MU "with theme" for falling 1.40% while its
# peers fell 7.95%: peers "accounted for" more than all of it. But MU's
# story that day was that it didn't fall with them. Scaling the gap by the
# larger move counts holding up, or falling further, as a divergence.
THEME_GAP = 0.4
COMPANY_GAP = 0.6


def peer_median(changes: dict[str, float | None], ticker: str) -> float | None:
    """Median move of every other company in the theme -- the typical peer."""
    peers = [v for t, v in changes.items() if t != ticker and v is not None]
    if len(peers) < MIN_PEERS:
        return None
    return median(peers)


def attribute(own: float | None, peers: float | None) -> str | None:
    """Label a move "theme", "mixed", "company" or "quiet".

      - "quiet"   neither the company nor its peers moved as much as
                  QUIET_MOVE -- nothing to attribute;
      - "theme"   it tracked its peers: within QUIET_MOVE points of them, or
                  a gap no more than THEME_GAP of the larger move;
      - "company" the gap is at least COMPANY_GAP of the larger move -- it
                  moved alone, against its peers, or held up while they fell;
      - "mixed"   in between.

    None when there are no peers to compare a real move with.
    """
    if own is None:
        return None
    if peers is None:
        return "quiet" if abs(own) < QUIET_MOVE else None
    scale = max(abs(own), abs(peers))
    if scale < QUIET_MOVE:
        return "quiet"
    gap = abs(own - peers)
    if gap < QUIET_MOVE:
        return "theme"
    ratio = gap / scale
    if ratio <= THEME_GAP:
        return "theme"
    if ratio >= COMPANY_GAP:
        return "company"
    return "mixed"


def relative_rows(changes: dict[str, float | None],
                  benchmark_change: float | None) -> dict[str, dict]:
    """Both comparisons, and the attribution, for every company."""
    out = {}
    for ticker, own in changes.items():
        peers = peer_median(changes, ticker)
        out[ticker] = {
            "vs_benchmark": None if own is None or benchmark_change is None
            else own - benchmark_change,
            "peer_median": peers,
            "vs_peers": None if own is None or peers is None else own - peers,
            "attribution": attribute(own, peers),
        }
    return out


def theme_summary(changes: dict[str, float | None],
                  benchmark_change: float | None) -> dict:
    """How the theme did as a whole.

    average     equal-weighted -- each company counts once, however large
    beat_count  how many companies beat the benchmark (breadth)
    dispersion  standard deviation of the companies' moves: low means they
                moved together, high means they went their own ways
    """
    values = [v for v in changes.values() if v is not None]
    if not values:
        return {"average": None, "vs_benchmark": None, "beat_count": None,
                "count": 0, "dispersion": None}
    average = mean(values)
    return {
        "average": average,
        "vs_benchmark": None if benchmark_change is None else average - benchmark_change,
        "beat_count": None if benchmark_change is None
        else sum(1 for v in values if v > benchmark_change),
        "count": len(values),
        "dispersion": pstdev(values) if len(values) >= 2 else None,
    }
