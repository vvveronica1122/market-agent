"""
Market Agent -- the conversational, tool-using agent.

HOW CONNECTING A TOOL ACTUALLY WORKS
------------------------------------
There are only three moving parts, and the surprising one is the second.

1. A plain Python function. Nothing special about it -- the functions in
   tools/ know nothing about Claude and never did.

2. A JSON schema describing that function: its name, a plain-language
   description, and its arguments. **This is the only thing the model ever
   sees.** It cannot read your code. It decides whether a tool is relevant
   entirely by reading that description text, which means writing the
   description is prompt engineering, not documentation. "Get events" and
   "Get the next scheduled earnings report date, the analyst EPS estimate
   for it, and whether the company beat or missed last quarter" produce
   very different behaviour from the same function.

3. A dispatch table mapping the schema's name back to the real function,
   so that when the model says "call get_earnings_schedule with
   ticker=AAPL", something actually runs.

Then the loop: send the question plus the schemas -> the model replies
either with text (done) or with a request to call tools -> you run them
and send the results back as a new turn -> repeat until it stops asking.

Below, all three parts live together in TOOLS, one entry per tool, so
adding a capability is a single edit instead of three that can drift apart.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.market_data import (
    get_stock_price,
    get_recent_news,
    get_upcoming_events,
    get_price_history,
)
from tools.market_scan import get_market_movers, filter_quality, get_market_news
from tools.fundamentals import (
    get_earnings_schedule,
    get_quarterly_results,
    get_key_stats,
    get_earnings_setup,
)
from tools.calc import calculate

load_dotenv(PROJECT_ROOT / ".env")

MODEL = "claude-sonnet-4-5"

# A runaway tool loop is a real failure mode: the model keeps calling
# tools and never answers, burning tokens until you kill it. Cap it.
MAX_STEPS = 12

WATCHLIST_FILE = PROJECT_ROOT / "web" / "watchlist.json"

SYSTEM_PROMPT = """You are a market research assistant with tools for live prices, news,
earnings schedules, company financials, and a market-wide scanner.

Use the tools rather than your memory -- markets change constantly and your training data
is old. When a question involves "my stocks" or "my watchlist", call get_watchlist first to
find out which ones those are.

The watchlist is a list of names the user is TRACKING. It is not a portfolio and this app
has no idea what they own. Never say "you own", "your holdings", or "your position" -- say
"on your watchlist" or "you're tracking". If the user's own question assumes ownership,
answer about the watchlist without repeating the assumption back as fact.

Refer to companies by ticker symbol at least once -- "Eli Lilly (LLY)" or just "LLY" --
since tickers are how they appear everywhere else on screen.

Chain tools when a question needs it: to answer "which of my stocks reports soonest", get
the watchlist, then check each one's earnings schedule, then compare. Don't ask permission
between steps, just do it.

ANSWER THE QUESTION THAT WAS ASKED. This matters more than any detail you gather. If asked
which one, name it in the first sentence -- don't do the lookups and then leave the reader
to infer the answer from the data you present. If the question has two parts, answer both
parts explicitly.

Plain prose only. No markdown: no ** bold **, no bullet lists, no headings. This is read in
a terminal and in a plain chat panel, where that syntax shows up as literal characters.

Never do arithmetic in your head. Use the calculate tool for every computation --
percentages, differences, ratios, averages, totals, growth rates -- even ones that look
easy. You are unreliable at mental arithmetic and reliably confident about the result,
which is the worst combination. Fetch the numbers with a data tool, then compute with
calculate.

When a figure looks surprising, describe how it compares to the company's own recent
history -- "revenue of 50.8B, roughly 4.5 times the 11.3B a year earlier" -- rather than
declaring it wrong. Your sense of what is normal for a company comes from training data
that is months out of date, so a number that contradicts your expectation may simply be
newer than you are. Give the reader the comparison and let them judge; asserting that
real data is an error is its own kind of confident mistake.

Stick to what the tools returned. Don't add background about a company from your own
memory -- not its history, not its usual volatility, not what a product is used for. Your
training data is old and the reader cannot tell which half of your sentence came from a
live lookup and which half you recalled. An unverifiable aside costs more trust than the
context it adds.

When a tool returns an error or no data, say so plainly instead of guessing or filling the
gap from memory.

Do not give buy/sell/hold recommendations or price targets. Explain what the data shows and
let the reader decide. Keep answers concise.

If asked whether a stock will rise or fall -- around earnings or otherwise -- say plainly
that direction isn't knowable, then answer the useful question instead: call
get_earnings_setup and describe what the evidence shows. How large the move usually is,
whether beating estimates has historically meant the stock rose, where expectations sit
now. That is analysis. Naming a direction would be invention with a confident tone, and
the reader cannot tell the two apart."""


def read_watchlist() -> list[str]:
    """The watchlist the web dashboard maintains -- shared state between
    the two halves of this project."""
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return ["AAPL", "TSLA", "MSFT", "NVDA"]


def scan_market(limit: int = 10) -> list[dict]:
    """Top market-wide movers, already quality-filtered."""
    movers = filter_quality(get_market_movers())
    movers.sort(key=lambda m: abs(m.get("change_percent") or 0), reverse=True)
    return movers[:limit]


TICKER_ARG = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL, TSLA"}
    },
    "required": ["ticker"],
}

# Schema and implementation together, so they can't drift apart.
TOOLS = [
    {
        "name": "get_watchlist",
        "description": (
            "Get the list of ticker symbols the user is currently watching. Call this first "
            "whenever the question refers to 'my stocks', 'my watchlist', or 'the ones I follow'."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda: read_watchlist(),
    },
    {
        "name": "get_stock_price",
        "description": "Get the latest price, previous close, and today's change for one ticker.",
        "input_schema": TICKER_ARG,
        "handler": lambda ticker: get_stock_price(ticker),
    },
    {
        "name": "get_recent_news",
        "description": "Get recent news headlines about one specific company.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "limit": {"type": "integer", "description": "Max headlines to return (default 5)"},
            },
            "required": ["ticker"],
        },
        "handler": lambda ticker, limit=5: get_recent_news(ticker, limit),
    },
    {
        "name": "get_price_history",
        "description": (
            "Get daily closing prices over a period, for judging a trend rather than a single "
            "day. Period accepts values like 5d, 1mo, 3mo, 6mo, 1y."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "period": {"type": "string", "description": "Time span, e.g. 1mo, 6mo, 1y"},
            },
            "required": ["ticker"],
        },
        "handler": lambda ticker, period="1mo": get_price_history(ticker, period),
    },
    {
        "name": "get_earnings_schedule",
        "description": (
            "Get the next scheduled earnings report date for a company, the analyst EPS estimate "
            "for it, and whether the company beat or missed expectations last quarter. Use this "
            "for any question about when a company reports or how its last report went."
        ),
        "input_schema": TICKER_ARG,
        "handler": lambda ticker: get_earnings_schedule(ticker),
    },
    {
        "name": "get_quarterly_results",
        "description": (
            "Get recent quarterly revenue, net income and profit margin for a company, oldest "
            "first. Use this for questions about whether a business is growing or shrinking, or "
            "about seasonality."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol"},
                "quarters": {"type": "integer", "description": "How many quarters (default 6)"},
            },
            "required": ["ticker"],
        },
        "handler": lambda ticker, quarters=6: get_quarterly_results(ticker, quarters),
    },
    {
        "name": "get_key_stats",
        "description": (
            "Get company size and valuation figures: market cap, trailing and forward P/E, "
            "profit margin, revenue growth, and sector."
        ),
        "input_schema": TICKER_ARG,
        "handler": lambda ticker: get_key_stats(ticker),
    },
    {
        "name": "scan_market",
        "description": (
            "Scan the whole US market for today's biggest movers and most actively traded "
            "companies, filtered to real companies above $2B in value. Use this to find names "
            "that are NOT on the user's watchlist, or to see what the market as a whole is doing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many names to return (default 10)"}
            },
        },
        "handler": lambda limit=10: scan_market(limit),
    },
    {
        "name": "get_market_news",
        "description": (
            "Get broad market headlines not tied to any single company -- macro data, policy, "
            "sector-wide stories."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "handler": lambda: get_market_news(),
    },
    {
        "name": "get_earnings_setup",
        "description": (
            "Get the evidence on how a stock has behaved around its past earnings: the actual "
            "next-session price move after each of the last several reports, whether it beat or "
            "missed each time, the typical size of the move, how often it beat and STILL fell, "
            "and which way analyst estimates have been revised. Use this for any question about "
            "what to expect from an upcoming earnings report. It describes the setup; it does "
            "not predict the outcome, and neither should you."
        ),
        "input_schema": TICKER_ARG,
        "handler": lambda ticker: get_earnings_setup(ticker),
    },
    {
        "name": "calculate",
        "description": (
            "Evaluate an arithmetic expression and return the exact result. Use this for ALL "
            "computation -- percentage change, differences, ratios, averages, sums, growth "
            "rates -- rather than working it out yourself. Accepts ordinary arithmetic plus "
            "abs, round, min, max, sum, len, sorted, sqrt, floor, ceil. "
            "Examples: '(312.14 - 316.34) / 316.34 * 100' for a percent change, "
            "'sum([182.4, 312.1, 511.0]) / 3' for an average."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "An arithmetic expression, e.g. '(44.1 - 26.9) / 26.9 * 100'",
                }
            },
            "required": ["expression"],
        },
        "handler": lambda expression: calculate(expression),
    },
    {
        "name": "get_upcoming_events",
        "description": "Get upcoming dated events for a company, such as an ex-dividend date.",
        "input_schema": TICKER_ARG,
        "handler": lambda ticker: get_upcoming_events(ticker),
    },
]

# What the model sees: everything except the handler.
TOOL_SCHEMAS = [{k: v for k, v in tool.items() if k != "handler"} for tool in TOOLS]
HANDLERS = {tool["name"]: tool["handler"] for tool in TOOLS}


def run_tool(name: str, tool_input: dict) -> str:
    """Execute one tool and return its result as JSON text."""
    handler = HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool '{name}'"})
    try:
        return json.dumps(handler(**tool_input), default=str)
    except Exception as exc:
        # Hand errors back as data. A crashed tool should become something
        # the model can explain, not something that kills the program.
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})


def ask_agent(client: Anthropic, user_message: str, verbose: bool = True,
              history: list[dict] | None = None, trace: list[dict] | None = None) -> str:
    """Run the agentic loop for one request and return the final answer.

    `history` seeds earlier turns so follow-up questions work in a chat.
    `trace`, if given, is filled with the tool calls made -- the web UI
    shows these, because hiding them would turn a visible chain of
    reasoning into a black box.
    """
    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": user_message})

    for step in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if response.stop_reason != "tool_use" or not tool_uses:
            return "\n".join(b.text for b in response.content if b.type == "text").strip()

        messages.append({"role": "assistant", "content": response.content})

        results = []
        for use in tool_uses:
            if verbose:
                args = ", ".join(f"{k}={v!r}" for k, v in use.input.items())
                print(f"  [{step + 1}] {use.name}({args})")
            if trace is not None:
                trace.append({"step": step + 1, "tool": use.name, "input": dict(use.input)})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": use.id,
                    "content": run_tool(use.name, use.input),
                }
            )

        messages.append({"role": "user", "content": results})

    return ("I hit the tool-call limit before finishing. That usually means the question "
            "needs breaking into smaller parts.")


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Missing ANTHROPIC_API_KEY. Copy .env.example to .env and add your key.")
        sys.exit(1)

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        # A bare ticker is a shorthand for "brief me on this".
        if len(sys.argv) == 2 and sys.argv[1].isupper() and len(sys.argv[1]) <= 5:
            question = (f"Give me a quick update on {sys.argv[1]}: price, notable news, "
                        f"and when it next reports.")
        print(f"\n{question}\n")
        print(ask_agent(client, question) + "\n")
        return

    print("Market Agent. Ask anything about your watchlist or the market.")
    print("Try: 'which of my stocks reports soonest, and how did they do last quarter?'")
    print("Type 'quit' to exit.\n")
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"quit", "exit"}:
            break
        print()
        print(f"\nAgent: {ask_agent(client, question)}\n")


if __name__ == "__main__":
    main()
