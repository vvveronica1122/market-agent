"""
Find out what the news payload actually contains.

Before designing a summary feature it's worth knowing whether the source
gives us article text, a publisher-written summary, or only headlines --
those support three very different products, and guessing would mean
building for data we may not have.

    python3 tools/probe_news.py [TICKER]
"""

from __future__ import annotations

import json
import sys

import yfinance as yf


def walk(value, prefix="", depth=0):
    """Print the shape of the payload, truncating long text."""
    pad = "  " * depth
    if isinstance(value, dict):
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(inner, (dict, list)):
                print(f"{pad}{key}:")
                walk(inner, path, depth + 1)
            else:
                text = str(inner)
                shown = text[:110] + ("..." if len(text) > 110 else "")
                print(f"{pad}{key} ({type(inner).__name__}, len={len(text)}): {shown}")
    elif isinstance(value, list):
        print(f"{pad}[{len(value)} items]")
        if value:
            walk(value[0], prefix, depth + 1)


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"\nFetching news for {ticker}...\n")

    items = yf.Ticker(ticker).news or []
    if not items:
        print("No news returned.")
        return 1

    print(f"{len(items)} items. Structure of the first one:\n")
    walk(items[0])

    print("\n" + "=" * 70)
    print("Which text fields are present across all items:")
    print("=" * 70)

    def probe(item, *names):
        content = item.get("content", item)
        found = {}
        for name in names:
            value = content.get(name) or item.get(name)
            if isinstance(value, str) and value.strip():
                found[name] = len(value)
        return found

    for i, item in enumerate(items[:5], 1):
        fields = probe(item, "title", "summary", "description", "body", "content_text")
        title = (item.get("content", item).get("title") or "")[:52]
        print(f"\n  {i}. {title}")
        for name, length in fields.items():
            print(f"       {name}: {length} chars")
        if "summary" not in fields and "description" not in fields:
            print("       (headline only -- no summary text)")

    print("\nIf only 'title' appears, any 'summary' this app writes is a")
    print("summary OF HEADLINES, and should say so rather than implying")
    print("the articles were read.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
