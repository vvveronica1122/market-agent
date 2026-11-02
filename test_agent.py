"""
Tests for the agent loop, with the model and the tools both stubbed.

The interesting thing to test here isn't any single tool -- it's the loop:
does the agent actually chain calls, does a broken tool become data rather
than a crash, and does it stop instead of looping forever.

No network, no API key. Run with:

    python3 test_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent


# --- a fake model -----------------------------------------------------
class _Text:
    type = "text"

    def __init__(self, text):
        self.text = text


class _ToolUse:
    type = "tool_use"

    def __init__(self, name, tool_input, id_="tu_1"):
        self.name = name
        self.input = tool_input
        self.id = id_


class _Reply:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class ScriptedMessages:
    """Replays a fixed sequence of model replies and records what it saw."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.script.pop(0) if self.script else _Reply([_Text("done")], "end_turn")
        return reply


class ScriptedClient:
    def __init__(self, script):
        self.messages = ScriptedMessages(script)


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    failures = 0

    print("\nTool wiring")
    failures += not check("every schema has a handler behind it",
                          {t["name"] for t in agent.TOOL_SCHEMAS} == set(agent.HANDLERS))
    failures += not check("handlers are never sent to the model",
                          all("handler" not in t for t in agent.TOOL_SCHEMAS))
    failures += not check("every tool describes itself in more than a few words",
                          all(len(t["description"]) > 40 for t in agent.TOOL_SCHEMAS),
                          str([t["name"] for t in agent.TOOL_SCHEMAS if len(t["description"]) <= 40]))

    print("\nChaining across steps")
    agent.HANDLERS["get_watchlist"] = lambda: ["AAPL", "NVDA"]
    agent.HANDLERS["get_earnings_schedule"] = lambda ticker: {
        "ticker": ticker, "next_date": "2026-10-29" if ticker == "AAPL" else "2026-09-12",
        "days_away": 50 if ticker == "AAPL" else 3,
    }

    client = ScriptedClient([
        _Reply([_ToolUse("get_watchlist", {})], "tool_use"),
        _Reply([_ToolUse("get_earnings_schedule", {"ticker": "AAPL"}, "a"),
                _ToolUse("get_earnings_schedule", {"ticker": "NVDA"}, "b")], "tool_use"),
        _Reply([_Text("NVDA reports first, in 3 days.")], "end_turn"),
    ])
    answer = agent.ask_agent(client, "which of my stocks reports soonest?", verbose=False)
    failures += not check("returns the model's final text", answer == "NVDA reports first, in 3 days.", answer)
    failures += not check("took three turns: ask, look up, answer",
                          len(client.messages.calls) == 3, str(len(client.messages.calls)))

    sent = client.messages.calls[-1]["messages"]
    tool_results = [m for m in sent if isinstance(m.get("content"), list)
                    and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"])]
    failures += not check("tool results are fed back into the conversation", len(tool_results) == 2,
                          str(len(tool_results)))
    failures += not check("both parallel tool calls in one turn were executed",
                          len(tool_results[-1]["content"]) == 2)
    failures += not check("the looked-up data actually reaches the model",
                          "2026-09-12" in json.dumps(tool_results[-1]["content"]))

    print("\nFailure handling")
    out = agent.run_tool("no_such_tool", {})
    failures += not check("an unknown tool name returns an error, not a crash",
                          json.loads(out).get("error", "").startswith("Unknown tool"))

    agent.HANDLERS["get_stock_price"] = lambda ticker: (_ for _ in ()).throw(ValueError("Yahoo is down"))
    out = agent.run_tool("get_stock_price", {"ticker": "AAPL"})
    failures += not check("a raising tool becomes data the model can explain",
                          "Yahoo is down" in json.loads(out).get("error", ""), out)

    out = agent.run_tool("get_watchlist", {"bogus": 1})
    failures += not check("bad arguments are caught too", "error" in json.loads(out), out)

    print("\nA trace an answer can be checked against")
    # The trace used to keep only which tool ran with what input. To check
    # an answer against its data, each step also says whether the lookup
    # worked, how long it took, what came back and how old that data is.
    agent.HANDLERS["get_price_history"] = lambda ticker, period="1mo": [
        {"date": f"2026-08-{day:02d}", "close": 100.0 + day} for day in range(1, 31)]
    agent.HANDLERS["get_key_stats"] = lambda ticker: {"ticker": ticker, "sector": "x" * 2000}
    client = ScriptedClient([
        _Reply([_ToolUse("get_price_history", {"ticker": "AAPL"}, "a"),
                _ToolUse("get_stock_price", {"ticker": "AAPL"}, "b"),
                _ToolUse("get_key_stats", {"ticker": "AAPL"}, "c")], "tool_use"),
        _Reply([_Text("AAPL rose over August.")], "end_turn"),
    ])
    trace = []
    agent.ask_agent(client, "how did AAPL do?", verbose=False, trace=trace)
    by_tool = {s["tool"]: s for s in trace}
    history, price, stats = (by_tool.get(n, {}) for n in
                             ("get_price_history", "get_stock_price", "get_key_stats"))
    failures += not check("the step, tool and input keep their meaning",
                          [(s["step"], s["tool"], s["input"]) for s in trace] ==
                          [(1, "get_price_history", {"ticker": "AAPL"}),
                           (1, "get_stock_price", {"ticker": "AAPL"}),
                           (1, "get_key_stats", {"ticker": "AAPL"})], str(trace))
    failures += not check("a successful lookup records status ok", history.get("status") == "ok",
                          str(history))
    failures += not check("every step records a non-negative elapsed_ms",
                          all(isinstance(s.get("elapsed_ms"), int) and s["elapsed_ms"] >= 0
                              for s in trace), str([s.get("elapsed_ms") for s in trace]))
    failures += not check("the summary is a digest of the result, not the payload",
                          history.get("summary", "").startswith("30 items; first date=2026-08-01")
                          and "last date=2026-08-30, close=130.0" in history["summary"]
                          and "2026-08-15" not in history["summary"], history.get("summary"))
    failures += not check("a dated result records as_of, from its latest date",
                          history.get("as_of") == "2026-08-30", str(history.get("as_of")))
    failures += not check("a raising tool records status error with its message",
                          price.get("status") == "error"
                          and "Yahoo is down" in price.get("summary", ""), str(price))
    failures += not check("an undated or failed result has no invented as_of",
                          "as_of" not in price and "as_of" not in stats, str([price, stats]))
    failures += not check("summaries are capped in length",
                          stats.get("status") == "ok"
                          and len(stats.get("summary", "")) <= agent.SUMMARY_CHARS
                          and all(len(s["summary"]) <= agent.SUMMARY_CHARS for s in trace),
                          str(len(stats.get("summary", ""))))
    long_error = agent.describe_result(json.dumps({"error": "E" * 5000}))
    failures += not check("a long error is capped too",
                          long_error["status"] == "error"
                          and len(long_error["summary"]) <= agent.SUMMARY_CHARS, str(long_error)[:80])
    unknown = agent.describe_result(agent.run_tool("no_such_tool", {}))
    failures += not check("an unknown tool is an error step",
                          unknown["status"] == "error" and "Unknown tool" in unknown["summary"],
                          str(unknown))
    failures += not check("a step's detail never changes what the model is handed",
                          json.loads(client.messages.calls[-1]["messages"][-1]["content"][0]
                                     ["content"])[-1] == {"date": "2026-08-30", "close": 130.0})

    print("\nCommand-line shorthand")
    one = agent.question_from_args(["AAPL"])
    failures += not check("a bare ticker becomes a briefing request",
                          one.startswith("Give me a quick update on AAPL"), one)
    two = agent.question_from_args(["AAPL", "TSLA"])
    failures += not check("several bare tickers are all briefed, not sent as a question",
                          "AAPL" in two and "TSLA" in two and two != "AAPL TSLA", two)
    plain = agent.question_from_args(["what", "moved", "NVDA?"])
    failures += not check("an ordinary question passes through unchanged",
                          plain == "what moved NVDA?", plain)

    print("\nWatchlist is not a portfolio")
    # An eval caught the agent writing "Nvidia, which you do own". Nothing
    # here knows what anyone owns -- it tracks a list of names. The same
    # conflation had spread to the brief prompt, a tool description, a
    # chat starter and a section heading, so this scans for it returning.
    #
    # This is a lint, not a proof. The rules that BAN the phrasing have to
    # quote it, and in a multi-line prompt string the word "never" may sit
    # several lines above the quote -- so a window around each hit is
    # checked for a prohibition marker rather than the line alone.
    # "own holdings" and "not_owned" were added after both slipped past the
    # first list: one in an eval rubric, one as a JSON key in the brief's
    # payload -- the model reads key names too. The key is now caught. The
    # rubric case is a known blind spot: rubrics say "FAIL it if...", which
    # the window below reads as a prohibition, so phrasing inside a rubric
    # is skipped.
    banned = ["you own", "don't own", "already own", "your holdings", "your position",
              "own holdings", "not_owned"]
    root = Path(__file__).resolve().parent
    sources = ["agent.py", "web/app.py", "web/static/app.js", "web/static/index.html",
               "evals/agent_scenarios.py", "evals/scenarios.py"]
    offenders = []
    for name in sources:
        path = root / name
        if not path.exists():
            continue
        lines = path.read_text().splitlines()
        for number, line in enumerate(lines, 1):
            lowered = line.lower()
            if not any(phrase in lowered for phrase in banned):
                continue
            window = " ".join(lines[max(0, number - 5):number + 3]).lower()
            if any(marker in window for marker in ("never", "fail", "not a portfolio")):
                continue
            offenders.append(f"{name}:{number} {line.strip()[:60]}")
    failures += not check("no source claims the user owns anything",
                          not offenders, "; ".join(offenders[:3]))

    print("\nRunaway protection")
    forever = ScriptedClient([_Reply([_ToolUse("get_watchlist", {})], "tool_use")] * 50)
    answer = agent.ask_agent(forever, "loop forever", verbose=False)
    failures += not check("stops at the step limit instead of looping forever",
                          len(forever.messages.calls) == agent.MAX_STEPS,
                          f"{len(forever.messages.calls)} calls")
    failures += not check("says why it stopped rather than returning nothing",
                          "limit" in answer.lower(), answer)

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
