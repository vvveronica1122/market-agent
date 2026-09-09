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
    (r"\b(you may want to|you might want to|worth considering)\b", "suggests an action"),
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


def judge(client, model: str, output: str, rubric: str) -> tuple[bool, str]:
    """Grade an output with a second model call. Returns (passed, reason)."""
    prompt = f"RUBRIC:\n{rubric}\n\nBRIEF TO GRADE:\n{output}"
    try:
        response = client.messages.create(
            model=model,
            max_tokens=250,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return False, f"judge call failed: {exc}"

    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        return False, f"judge returned unparseable output: {text[:120]}"

    return bool(verdict.get("pass")), str(verdict.get("reason", ""))[:300]


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
