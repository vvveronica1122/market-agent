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


# Claims a brief can't make about a name whose lookup failed: that it had
# no news, or that nothing reports in a window its unknown date could fall
# in. The prompt asks for neither and the brief still made them in about
# one run in ten (evals/tuning/batch1-2026-11.md); these are read off
# those runs. A sentence limited to known dates, or to the other names,
# passes.
_ABSENCE = re.compile(
    r"\b(?:nothing|none|no (?:\w+ )?(?:reports?|earnings|compan(?:y|ies)|names?|one)"
    r"|only (?:\w+ ){0,2}(?:reports?|names?|compan(?:y|ies)|one|date))\b", re.IGNORECASE)
_WINDOW = re.compile(
    r"\b(?:this|next|coming) (?:week|seven days|7 days)\b|\bweek ahead\b"
    r"|\bwithin (?:a|the next|the coming) week\b|\bsoon\b", re.IGNORECASE)
_WHOLE_LIST = re.compile(
    r"\bacross the board\b|\beverything on (?:the|your|this) (?:list|watchlist)\b"
    r"|\bevery name\b|\bentire watchlist\b", re.IGNORECASE)
_LIMITED = re.compile(r"\bknown\b|\b(?:rest|others?) of\b|\bother names\b|\bremaining\b",
                      re.IGNORECASE)
_NEWS_ABSENCE = re.compile(
    r"\bno (?:\w+[- ]){0,2}(?:news|headlines?)\b|\bnothing (?:\w+ ){0,2}in the (?:news|headlines)\b"
    r"|\b(?:minimal|little) news\b|\bquiet on (?:the )?news\b|\bwithout (?:any )?(?:news|headlines)\b"
    r"|\b(?:didn't|did not|nor) generat\w* headlines\b|\bnothing company-specific\b"
    r"|\bno company-specific (?:news|headlines?|catalysts?|drivers?)\b", re.IGNORECASE)
_GROUP = re.compile(r"\b(?:all three|the three|these (?:three|names)|the group|that group"
                    r"|any of them|none of them|each of them|them)\b", re.IGNORECASE)


def _paragraph_sentences(text: str) -> list[list[str]]:
    return [[s.strip() for s in re.split(r"(?<=[.!?])\s+", para.strip()) if s.strip()]
            for para in re.split(r"\n\s*\n", text)]


def find_failed_data_claims(text: str, news_failed: list[str], dates_unknown: list[str]) -> list[str]:
    """The sentences of a brief that claim what a failed lookup can't
    support. `news_failed` are names whose headlines didn't load;
    `dates_unknown` names whose next report date isn't known. A news claim
    counts when its sentence names a failed name, speaks of a group, or
    follows a sentence naming one."""
    names = [re.compile(rf"\b{re.escape(t)}\b") for t in news_failed]
    flagged = []
    for sentences in _paragraph_sentences(text):
        for i, s in enumerate(sentences):
            calendar = bool(dates_unknown) and not _LIMITED.search(s) and (
                (_ABSENCE.search(s) and _WINDOW.search(s))
                or (_WHOLE_LIST.search(s) and re.search(r"report|earnings", s, re.IGNORECASE)))
            news = bool(names) and _NEWS_ABSENCE.search(s) and (
                any(n.search(s) for n in names) or _GROUP.search(s)
                or (i > 0 and any(n.search(sentences[i - 1]) for n in names)))
            if calendar or news:
                flagged.append(s)
    return flagged


def without_sentences(text: str, sentences: list[str]) -> str | None:
    """`text` with these sentences taken out, or None when fewer than two
    sentences would be left."""
    rest = text
    for s in sentences:
        rest = rest.replace(s, "", 1)
    rest = re.sub(r"[ \t]*\n[ \t]*", "\n", re.sub(r"[ \t]{2,}", " ", rest))
    rest = re.sub(r"\n{3,}", "\n\n", rest).strip()
    if sum(len(p) for p in _paragraph_sentences(rest)) < 2:
        return None
    return rest
