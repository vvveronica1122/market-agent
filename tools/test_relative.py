"""
Tests for the theme-relative arithmetic. Free, offline, instant.

The numbers are chosen so each answer can be checked by hand.

    python3 tools/test_relative.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.relative import attribute, peer_average, relative_rows, theme_summary


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def close(a, b):
    return a is not None and abs(a - b) < 1e-9


def main() -> int:
    failures = 0

    print("\nPeer average")
    changes = {"MU": -8.4, "SNDK": -7.0, "WDC": -8.0, "STX": -8.4}
    failures += not check("leaves the company out of its own average",
                          close(peer_average(changes, "MU"), (-7.0 - 8.0 - 8.4) / 3),
                          str(peer_average(changes, "MU")))
    failures += not check("needs at least two other companies with data",
                          peer_average({"A": 1.0, "B": 2.0}, "A") is None)
    failures += not check("skips peers with no data rather than counting them as flat",
                          close(peer_average({"A": 5.0, "B": None, "C": 2.0, "D": 4.0}, "A"), 3.0))

    print("\nAttribution")
    failures += not check("falling with the peers is a theme move",
                          attribute(-8.4, -7.8) == "theme")
    # The first live run: MU fell 1.40% while its peers fell 7.95%. An
    # earlier rule called that "with theme"; holding up is the story.
    failures += not check("holding up while the peers fall is the company's own story",
                          attribute(-1.40, -7.95) == "company")
    failures += not check("falling much further than the peers is the company's own story",
                          attribute(-9.0, -2.0) == "company")
    failures += not check("moving while the peers sit still is a company move",
                          attribute(-6.0, -0.5) == "company")
    failures += not check("moving against the peers is a company move",
                          attribute(4.0, -1.5) == "company")
    failures += not check("about half shared is reported as mixed, not forced either way",
                          attribute(-4.0, -2.0) == "mixed")
    # The first live run: two hard-disk makers fell together, and a single
    # 50% cut-off labelled one "theme" and the other "company".
    failures += not check("near-identical moves either side of a half get the same label",
                          attribute(-10.10, -5.05) == attribute(-10.19, -5.02) == "mixed",
                          f"{attribute(-10.10, -5.05)} / {attribute(-10.19, -5.02)}")
    failures += not check("a gap of 40% of the move still tracks the theme (the edge)",
                          attribute(-10.0, -6.0) == "theme")
    failures += not check("a gap of 60% of the move is a divergence (the edge)",
                          attribute(-10.0, -4.0) == "company")
    failures += not check("a quiet day for the company and its peers is left as quiet",
                          attribute(0.6, -0.4) == "quiet")
    failures += not check("sitting flat while the peers fall 3% is not quiet -- it diverged",
                          attribute(0.6, -3.0) == "company")
    failures += not check("within a point of the peers is moving with them",
                          attribute(-2.5, -1.8) == "theme")
    failures += not check("no peers means no attribution, not a guess",
                          attribute(-5.0, None) is None)
    failures += not check("a small move with no peers is still just quiet",
                          attribute(0.4, None) == "quiet")
    failures += not check("flat peers can't explain a move",
                          attribute(2.0, 0.0) == "company")

    print("\nPer-company rows")
    rows = relative_rows({"A": -6.0, "B": -5.5, "C": -6.5, "D": None}, benchmark_change=-5.0)
    failures += not check("vs benchmark is the plain difference",
                          close(rows["A"]["vs_benchmark"], -1.0))
    failures += not check("vs peers uses the leave-one-out average",
                          close(rows["A"]["vs_peers"], -6.0 - (-6.0)))
    failures += not check("a company with no price gets no comparisons",
                          rows["D"]["vs_benchmark"] is None and rows["D"]["attribution"] is None)
    no_bench = relative_rows({"A": 1.5, "B": 1.0, "C": 2.0}, benchmark_change=None)
    failures += not check("a missing benchmark leaves vs-benchmark empty but peers intact",
                          no_bench["A"]["vs_benchmark"] is None and no_bench["A"]["vs_peers"] is not None)

    print("\nTheme summary")
    s = theme_summary({"A": 2.0, "B": -1.0, "C": 5.0, "D": None}, benchmark_change=1.0)
    failures += not check("average is equal-weighted over companies with data",
                          close(s["average"], 2.0), str(s["average"]))
    failures += not check("breadth counts companies that beat the benchmark",
                          s["beat_count"] == 2 and s["count"] == 3, str(s))
    failures += not check("dispersion is the spread of the moves",
                          close(s["dispersion"], (6.0) ** 0.5), str(s["dispersion"]))
    together = theme_summary({"A": -5.0, "B": -5.2, "C": -4.8}, -4.0)["dispersion"]
    apart = theme_summary({"A": -5.0, "B": 3.0, "C": 0.5}, -4.0)["dispersion"]
    failures += not check("names moving together disperse less than names going their own ways",
                          together < apart, f"{together} vs {apart}")
    empty = theme_summary({"A": None}, 1.0)
    failures += not check("a theme with no data summarises to nothing, not zero",
                          empty["average"] is None and empty["count"] == 0)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
