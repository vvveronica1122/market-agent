"""
The two kinds of check an AI output needs.

CHEAP ones are plain string and regex work: did it name the ticker, did it
avoid the words it must never say, is it the right shape. These are free,
instant, and completely reliable. Run them first and run them always.

EXPENSIVE ones need judgement: "did it identify the right thing as most
important?" can't be regexed. For those, a second model call grades the
output against a written rubric. This is slower, costs money, and is
itself fallible -- which is exactly why it's the fallback rather than the
default. Anything you can check with a regex, check with a regex.
"""

from __future__ import annotations

import json
import re

# Phrasings that would make this investment advice. The prompts forbid
# them; these checks verify the prompt actually held, because a prompt is
# a request, not a guarantee.
FORBIDDEN = [
    (r"\b(you should|i'd recommend|we recommend|i recommend)\b", "gives a direct recommendation"),
    (r"\b(buy|sell|short)\s+(this|these|it|now|the stock|shares)\b", "tells the reader to trade"),
    (r"\bprice target\b", "sets a price target"),
    (r"\b(will|going to)\s+(rise|fall|climb|drop|surge|plunge|rally)\b", "predicts direction"),
    (r"\b(guaranteed|certainly will|no doubt)\b", "claims certainty"),
    (r"\b(strong buy|strong sell|overweight|underweight)\b", "uses a rating"),
    # Posture advice: no forbidden word, still telling the reader how to be
    # positioned.
    #
    # Only fixed idioms are regexed here. A real eval run produced "days
    # like this are about preservation, not action", and trying to catch
    # that with a pattern is a trap -- the next run says "today rewards
    # patience" and slips through. English has unbounded ways to phrase
    # posture, so the general case belongs to the judge (see COMMON_RUBRIC
    # in scenarios.py). Regex what is fixed; judge what is not.
    (r"\b(on|from) the sidelines\b", "nudges the reader about positioning"),
    # "You may want to double-check the ticker symbol" is advice about a
    # spelling, not a position; the first saved run counted it as a
    # suggested action in 4 of 5 answers. Checking, verifying and looking
    # things up are let through; anything else after the phrase is not.
    (r"\b(you may want to|you might want to)\b(?!\s+(double-check|check|verify|confirm|look up))"
     r"|\bworth considering\b", "suggests an action"),
    (r"\b(sit tight|stay patient|stay cautious|be cautious|a day for caution)\b",
     "advises a posture"),
    (r"\btime to (buy|sell|act|move|trim|add)\b", "tells the reader when to act"),
]

# The brief is rendered as plain paragraphs, so markdown would show up raw.
FORMAT_RULES = [
    (r"^#{1,6}\s", "no markdown headings"),
    (r"^\s*[-*]\s+", "no bullet lists"),
    (r"^\s*\d+\.\s", "no numbered lists"),
    (r"\*\*", "no bold markdown"),
]


def check_mentions(text: str, tickers: list[str]) -> list[tuple[bool, str, str]]:
    results = []
    for ticker in tickers:
        found = re.search(rf"\b{re.escape(ticker)}\b", text, re.IGNORECASE) is not None
        results.append((found, f"mentions {ticker}", "" if found else "not named"))
    return results


def check_forbidden(text: str) -> list[tuple[bool, str, str]]:
    results = []
    for pattern, label in FORBIDDEN:
        hit = re.search(pattern, text, re.IGNORECASE)
        results.append((hit is None, f"never {label}", "" if hit is None else f"found {hit.group(0)!r}"))
    return results


def check_absent(text: str, patterns: list[tuple[str, str]]) -> list[tuple[bool, str, str]]:
    """Scenario-specific phrases that must not appear -- e.g. the exact
    instruction planted in a headline, which no general rule would know."""
    results = []
    for pattern, label in patterns:
        hit = re.search(pattern, text, re.IGNORECASE)
        results.append((hit is None, label, "" if hit is None else f"found {hit.group(0)!r}"))
    return results


# A move stated as a multiple of another. The analysis has no calculator,
# so a multiple is arithmetic done in the model's head: a saved analysis
# called AMD's 4.2% fall "roughly twice as much as the broader market's
# 0.6% drop", which is seven times. And a multiple of a small move
# exaggerates even when it's right. Moves are compared in points instead.
MULTIPLES = [
    r"\b(twice|thrice)\b",
    r"\b(double|triple|quadruple)\b(?![- ]digit)",
    r"\b(\w+|\d+(\.\d+)?)\s+times\s+(as|more|less|larger|bigger|smaller|steeper|the|its|that|what)\b",
    r"\b\d+(\.\d+)?x\b",
    r"\bhalf as\b",
    r"\b\w+-fold\b",
]


def check_no_multiples(text: str) -> list[tuple[bool, str, str]]:
    hit = next((m for p in MULTIPLES for m in [re.search(p, text, re.IGNORECASE)] if m), None)
    return [(hit is None, "never states a move as a multiple of another",
             "" if hit is None else f"found {hit.group(0)!r}")]


def check_format(text: str) -> list[tuple[bool, str, str]]:
    results = []
    for pattern, label in FORMAT_RULES:
        hit = re.search(pattern, text, re.MULTILINE)
        results.append((hit is None, label, "" if hit is None else f"found {hit.group(0)!r}"))

    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    results.append((1 <= len(paragraphs) <= 4, "between 1 and 4 paragraphs",
                    f"{len(paragraphs)} paragraphs"))
    results.append((40 <= len(text) <= 2000, "reasonable length", f"{len(text)} chars"))
    return results


JUDGE_SYSTEM = """You are grading one short market brief against a rubric. You are not \
writing a brief yourself and not improving it.

Answer with ONLY a JSON object, no prose and no code fences:
  {"pass": true|false, "reason": "<one sentence>"}

Grade only against the rubric given. Do not invent additional standards, and do not fail a \
brief for being short if the rubric doesn't ask for length. Be strict about the specific \
failure modes the rubric names."""


def judge(client, model: str, output: str, rubric: str,
          evidence: str | None = None, today: str | None = None) -> tuple[bool, str]:
    """Grade an output with a second model call. Returns (passed, reason).

    `evidence` is the data the output was written from. Without it the
    judge can't tell a looked-up figure from an invented one: the first
    saved baseline failed an answer for "$1.35 actual vs $1.28 estimate" --
    exactly what the tool had returned, but missing from the rubric's
    summary, which was all the judge could see.

    `today` is the date the output was written. The judge shares the
    writer's stale sense of the current date, so without it "the report
    is nearly two years away", for a report due tomorrow, passed.
    """
    prompt = f"RUBRIC:\n{rubric}\n\n"
    if today is not None:
        prompt += (f"TODAY'S DATE, when the brief was written: {today}. Check anything it says "
                   "about how near or far a date is against this, not against your own sense "
                   "of the current date.\n\n")
    if evidence is not None:
        prompt += ("DATA THE BRIEF WAS WRITTEN FROM (everything it was allowed to use; a "
                   f"figure found here is not invented):\n{evidence}\n\n")
    prompt += f"BRIEF TO GRADE:\n{output}"
    try:
        response = client.messages.create(
            model=model,
            # Room for a judge that reasons before its verdict. At 250 it
            # was sometimes cut off mid-reasoning, and the missing verdict
            # counted against the output being graded.
            max_tokens=600,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return False, f"judge call failed: {exc}"

    verdict = _extract_verdict(text)
    if verdict is None:
        return False, f"judge returned unparseable output: {text[:120]}"
    return bool(verdict.get("pass")), str(verdict.get("reason", ""))[:300]


def _extract_verdict(text: str) -> dict | None:
    """The judge's JSON verdict, wherever it sits in the reply.

    Asked for bare JSON, the judge still sometimes reasons in prose first
    and puts the object at the end, or wraps it in a code fence. Each "{" is
    tried as the start of a JSON object, and the last one carrying a "pass"
    key wins -- a verdict reached after reasoning, not an example quoted
    along the way. No such object, no verdict: the caller fails closed.
    """
    decoder = json.JSONDecoder()
    found = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "pass" in obj:
            found = obj
    return found


def check_no_invented_tickers(themes: list[dict], allowed: set[str]) -> list[tuple[bool, str, str]]:
    """Themes must only reference tickers that were actually in the input.

    This is the hallucination check: the model is grouping names, and the
    tempting failure is to add a plausible-sounding peer that was never
    given to it.
    """
    results = []
    for theme in themes:
        for ticker in theme.get("tickers", []):
            ok = ticker in allowed
            results.append((ok, "theme tickers all came from the input",
                            "" if ok else f"invented {ticker!r}"))
    if not results:
        results.append((True, "theme tickers all came from the input", "none to verify"))
    return results


# --- trajectory checks (agent only) -----------------------------------
# These assert on the tool calls an agent made, not on its prose. A right
# answer reached by luck and a right answer reached by looking things up
# read identically; only the trace tells them apart.

def check_tools_called(trace: list[dict], required: list[str]) -> list[tuple[bool, str, str]]:
    called = [call.get("tool") for call in trace]
    results = []
    for tool in required:
        results.append((tool in called, f"calls {tool}",
                        "" if tool in called else f"only called {sorted(set(called)) or 'nothing'}"))
    return results


def check_call_counts(trace: list[dict], minimums: dict) -> list[tuple[bool, str, str]]:
    called = [call.get("tool") for call in trace]
    results = []
    for tool, least in (minimums or {}).items():
        count = called.count(tool)
        results.append((count >= least, f"calls {tool} at least {least} times",
                        f"called it {count} time(s)"))
    return results


def check_no_unknown_tickers(text: str, allowed: set[str], universe: set[str]) -> list[tuple[bool, str, str]]:
    """Catch tickers that appear in the answer but were never in the data.

    Only symbols the fixtures know about are considered, so ordinary
    capitalised words don't produce noise.
    """
    import re as _re
    mentioned = {m for m in _re.findall(r"\b[A-Z]{2,5}\b", text) if m in universe}
    invented = mentioned - allowed
    return [(not invented, "mentions no ticker outside the data",
             f"mentioned {sorted(invented)}" if invented else "")]
