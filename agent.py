"""
Market Agent -- a small tool-using agent built on the Anthropic API.

This is the core "agentic loop", the pattern almost every AI agent is
built on, no matter how complex:

  1. Send the user's request to Claude, along with a list of tools it's
     allowed to use.
  2. If Claude's response asks to use a tool, run that tool in plain
     Python and send the result back.
  3. Repeat until Claude has enough information to give a final answer.

Claude never runs the Python functions itself -- it only sees the tool
*schemas* below and decides, from those descriptions, which tool to call
and with what arguments. This file is the "brain" that wires that
decision up to the real functions in tools/market_data.py.
"""

from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv
from anthropic import Anthropic

from tools.market_data import get_stock_price, get_recent_news, get_upcoming_events

load_dotenv()

# Check https://docs.claude.com/en/docs/about-claude/models for the latest
# model names -- this one was current as of this project's creation.
MODEL = "claude-sonnet-4-5"

SYSTEM_PROMPT = """You are a helpful market research assistant. You have tools to
look up live stock prices, recent news, and upcoming events (like earnings dates)
for stock tickers. Use them whenever the user asks about a specific company or
ticker. Always base your answer on what the tools return rather than your own
memory, since markets change constantly and your training data may be outdated.
If a tool returns no data or an error, say so plainly instead of guessing.
Keep answers concise and skimmable."""

# --- Tool schemas -----------------------------------------------------
# This is how we describe each tool to Claude: a name, a plain-language
# description (Claude decides relevance from this text, so be specific),
# and a JSON schema for the arguments.
TOOLS = [
    {
        "name": "get_stock_price",
        "description": "Get the latest price, previous close, and day change for a stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL, TSLA"}
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_recent_news",
        "description": "Get recent news headlines related to a stock ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL, TSLA"},
                "limit": {"type": "integer", "description": "Max number of headlines to return (default 5)"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_upcoming_events",
        "description": "Get upcoming events for a stock ticker, such as the next earnings date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "Stock ticker symbol, e.g. AAPL, TSLA"}
            },
            "required": ["ticker"],
        },
    },
]

# Map each tool name to the real Python function that implements it.
# Claude only ever sees the schema above, never this dict.
TOOL_FUNCTIONS = {
    "get_stock_price": lambda ticker: get_stock_price(ticker),
    "get_recent_news": lambda ticker, limit=5: get_recent_news(ticker, limit),
    "get_upcoming_events": lambda ticker: get_upcoming_events(ticker),
}


def run_tool(name: str, tool_input: dict) -> str:
    """Execute a tool by name and return a JSON string of the result (or error)."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return json.dumps({"error": f"Unknown tool '{name}'"})
    try:
        result = func(**tool_input)
        return json.dumps(result, default=str)
    except Exception as exc:
        # Never let a tool crash the whole agent -- hand the error back to
        # Claude as data so it can explain the problem instead of the
        # whole program dying.
        return json.dumps({"error": str(exc)})


def ask_agent(client: Anthropic, user_message: str, verbose: bool = True) -> str:
    """Run the full agentic loop for one user request and return the final text answer."""
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if response.stop_reason != "tool_use" or not tool_uses:
            # Claude is done calling tools -- pull out and return its text answer.
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks).strip()

        # Claude wants to use one or more tools. Record its request, run
        # each tool, and feed the results back as the next turn.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_use in tool_uses:
            if verbose:
                print(f"  -> calling {tool_use.name}({tool_use.input})")
            result_text = run_tool(tool_use.name, tool_use.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Missing ANTHROPIC_API_KEY. Copy .env.example to .env and add your key.")
        sys.exit(1)

    client = Anthropic(api_key=api_key)

    if len(sys.argv) > 1:
        # CLI mode: `python agent.py AAPL TSLA` -> one quick digest.
        tickers = " ".join(sys.argv[1:])
        question = (
            f"Give me a quick market update on: {tickers}. "
            "Cover price, notable recent news, and any upcoming events."
        )
        print(f"\nAsking about: {tickers}\n")
        answer = ask_agent(client, question)
        print("\n" + answer + "\n")
    else:
        # Interactive mode: free-form questions.
        print("Market Agent -- ask about any stock ticker. Type 'quit' to exit.\n")
        while True:
            try:
                question = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question or question.lower() in {"quit", "exit"}:
                break
            answer = ask_agent(client, question)
            print(f"\nAgent: {answer}\n")


if __name__ == "__main__":
    main()
