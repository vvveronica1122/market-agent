"""
Rules on AI-written text that the code enforces, not just the prompt.

A rule stated in a prompt holds most of the time and leaks the rest. "Never
compare moves as multiples" held in about 1% of stock analyses, then leaked
in 3 of 40 once a change left the model less news to write about
(evals/tuning/news-degraded-2026-10.md). A pattern checked in code holds
whatever the prompt around it says.

The evals check the same patterns, so what the app enforces and what the
evals measure can't drift apart.
"""

from __future__ import annotations

import re

# A move stated as a multiple of another. The analysis has no calculator,
# so a multiple is arithmetic done in the model's head: a saved analysis
# called AMD's 4.2% fall "roughly twice as much as the broader market's
# 0.6% drop", which is seven times. And a multiple of a small move
# exaggerates even when it's right. Moves are compared in points instead.
# "Twice" needs a comparison after it: alone it can be a count, as in
# "posted negative abnormal moves twice", which the first version flagged.
MULTIPLES = [
    r"\b(twice|thrice)\s+(as|the|that|what|its|their)\b",
    r"\b(double|triple|quadruple)\b(?![- ]digit)",
    r"\b(\w+|\d+(\.\d+)?)\s+times\s+(as|more|less|larger|bigger|smaller|steeper|the|its|that|what)\b",
    r"\b\d+(\.\d+)?x\b",
    r"\bhalf as\b",
    r"\b\w+-fold\b",
]


def find_multiple(text: str) -> re.Match | None:
    """The first place `text` states a move as a multiple, or None."""
    for pattern in MULTIPLES:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match
    return None


def _sentence_span(text: str, match: re.Match) -> tuple[int, int]:
    before = [text.rfind(sep, 0, match.start()) for sep in (". ", "\n")]
    start = max((i + 1 for i in before if i >= 0), default=0)
    after = [i for i in (text.find(". ", match.end()), text.find("\n", match.end())) if i >= 0]
    end = min(after) + 1 if after else len(text)
    return start, end


def sentence_around(text: str, match: re.Match) -> str:
    """The sentence containing `match`. Sentences end at ". " or a line
    break, not at any full stop, so "4.2%" doesn't split one."""
    start, end = _sentence_span(text, match)
    return text[start:end].strip()


def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"(?<=\.) |\n", text) if s.strip()])


def without_multiple_sentence(text: str) -> str | None:
    """`text` with its one sentence stating a multiple taken out, or None
    when that can't be done cleanly: more than one such sentence, or fewer
    than two sentences left to read."""
    match = find_multiple(text)
    if match is None:
        return text
    start, end = _sentence_span(text, match)
    rest = text[:start] + text[end:]
    rest = re.sub(r"[ \t]*\n[ \t]*", "\n", re.sub(r"[ \t]{2,}", " ", rest))
    rest = re.sub(r"\n{3,}", "\n\n", rest).strip()
    if find_multiple(rest) is not None or _sentence_count(rest) < 2:
        return None
    return rest
