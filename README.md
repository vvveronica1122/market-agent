# Market Agent

A small, real, tool-using AI agent: ask it about a stock, and it looks up
live price data, recent news, and upcoming events (like earnings dates)
before answering -- instead of guessing from stale training data.

This project exists to learn, hands-on, how agentic AI apps are actually
built. Everything here is deliberately kept small so the underlying
pattern stays visible.

## What this teaches

- **Tool schemas** -- how you describe a function to an LLM (name,
  description, JSON argument schema) so it can decide when to call it.
  See the `TOOLS` list in `agent.py`.
- **The agentic loop** -- the request/tool-call/tool-result/repeat cycle
  that almost every AI agent is built on, however complex it eventually
  gets. See `ask_agent()` in `agent.py`.
- **Separating tools from the agent** -- `tools/market_data.py` has zero
  knowledge of Claude or the agent loop; it's just plain, testable Python.
  That separation is what makes agents debuggable: you can verify a tool
  works *before* trusting an LLM to call it correctly.
- **Designing for messy/failing data** -- news APIs return inconsistent
  shapes, tickers can be wrong, fields can be missing. The tools return
  errors as data (not crashes) so the agent can explain problems instead
  of falling over.

## Project layout

```
market-agent/
  agent.py              the agent loop + CLI entry point
  tools/
    market_data.py       the three tools: price, news, upcoming events
  test_tools.py           standalone test of the tools (no API key needed)
  requirements.txt
  .env.example             copy to .env and add your real API key
```

## Setup

**1. Get an Anthropic API key**

Go to <https://console.anthropic.com>, sign up/sign in, open **API Keys**,
and create a new key. You'll also need to add a small amount of prepaid
credit under **Billing** to actually make calls (a few dollars covers a
lot of experimentation with this project).

**2. Install dependencies**

Run these in your own Terminal app (not through Claude) from inside this
folder -- Claude's sandboxed tools can reach the Anthropic API but are
deliberately blocked from general package registries like PyPI, so this
one step has to happen in your regular Terminal:

```bash
cd ~/Documents/market-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Add your API key**

```bash
cp .env.example .env
```

Then open `.env` and paste your real key in place of `sk-ant-...`.

## Running it

Make sure your virtualenv is active (`source .venv/bin/activate` if it
isn't already), then:

```bash
# Test the data tools alone, no API key needed:
python test_tools.py AAPL

# Ask about specific tickers:
python agent.py AAPL TSLA

# Or run it interactively:
python agent.py
```

## How it works, in short

1. You ask a question ("what's going on with AAPL?").
2. Claude reads the question plus the list of available tools and decides
   it needs `get_stock_price`, maybe `get_recent_news` too.
3. `agent.py` actually runs those Python functions and sends the results
   back to Claude as a new turn in the conversation.
4. Claude reads the results and writes a final answer grounded in real,
   current data -- then the loop ends.

You can watch this happen: `ask_agent()` prints each tool call as it's
made (`-> calling get_stock_price({'ticker': 'AAPL'})`), so you can see
the agent's reasoning in real time.

## Ideas for where to take this next

Once this is working, here are natural next steps that build on it:

- **More tools**: sector performance, analyst ratings, insider trades,
  broader market indices.
- **Memory**: remember a watchlist across runs (a simple JSON file is
  enough to start) so you don't have to type tickers every time.
- **Scheduling**: run it once a day and save/email yourself a digest.
- **Evals**: write a small set of test questions with expected behavior
  (e.g. "does it call get_stock_price when asked for a price?") to check
  changes don't quietly break things -- this is what separates a hobby
  script from something you'd trust.
- **Guardrails**: this project is read-only (it only looks things up), so
  it's a safe place to practice -- but if you ever add tools that *take
  actions* (placing trades, sending emails), that's where you'd add
  confirmation steps before anything irreversible happens.

## A note on financial use

This is a learning project, not investment advice, and the data sources
(free, unauthenticated Yahoo Finance endpoints via `yfinance`) can be
delayed, incomplete, or occasionally wrong. Don't make real financial
decisions based solely on what it tells you.

## Web dashboard

A local dashboard at `web/app.py`. The organising idea: a watchlist sorted
**by what needs attention today**, not alphabetically. Most finance sites
show fifty numbers at equal visual weight and leave you to work out which
two matter; this one does that ranking for you.

Each name is scored in plain Python on four factors -- size of today's
move, how that move compares to the market (SPY), how close earnings are,
and how much news there is -- then the list is sorted by that score and
the reasons are shown as chips on the row. Clicking a row opens a detail
view with a six-month chart, the AI analysis, headlines and the next
earnings date. Search resolves any ticker, on your list or not.

### Two front doors, one agent

The same agent answers in two places:

```bash
python3 agent.py                 # in the terminal
python3 web/app.py               # then click "Ask" in the sidebar
```

The web panel posts to `/api/chat`, which calls the identical `ask_agent`
loop — not a reimplementation. Both show **every tool call the agent
made** before answering, which is deliberate: the whole point of an agent
is that it chose what to look up, and hiding that turns a legible chain of
reasoning into a black box you have to take on faith.

Chat history is held in the browser and sent with each message; the server
keeps no session. Only text turns are replayed — earlier tool results are
dropped rather than reconstructed, so the model keeps what it concluded
without re-sending a growing pile of JSON every message. Everything
arriving from the browser is treated as untrusted: roles are filtered to
user/assistant, content must be a string, length and turn count are
capped, and a forged `system` turn can't reach the model.

### The agent, and how a tool gets connected

`agent.py` is the conversational half — ask it anything and it decides
which tools to call. It now has ten, including the market scanner, the
earnings schedule and company financials, so it can answer questions that
need several lookups chained: *"which of my stocks reports soonest, and how
did they do last quarter?"* takes the watchlist, then each name's schedule,
then a comparison.

Connecting a tool has exactly three parts, and the surprising one is the
second:

1. **A plain Python function.** The code in `tools/` knows nothing about
   Claude and never has.
2. **A JSON schema** — name, plain-language description, arguments. This is
   *the only thing the model ever sees.* It cannot read your source. It
   decides whether a tool is relevant purely by reading that description,
   which makes writing descriptions prompt engineering rather than
   documentation. "Get events" and "Get the next scheduled earnings date,
   the analyst EPS estimate, and whether the company beat last quarter"
   produce very different behaviour from the identical function.
3. **A dispatch table** mapping the schema name back to the real function,
   so something actually runs when the model asks.

In `agent.py` all three live in one `TOOLS` entry per tool, so adding a
capability is a single edit rather than three that can silently drift apart.

Two robustness details worth stealing: a tool that raises returns its error
*as data* the model can explain, rather than crashing the program; and the
loop has a step cap, because a model that keeps calling tools and never
answers will otherwise burn tokens until you kill it.

### The two agent patterns, side by side

Worth comparing `agent.py` and `web/app.py`, because they solve the same
problem differently:

- `agent.py` runs the **full agentic loop** -- Claude sees the tool
  schemas and decides what to call. Right when the request is open-ended
  and you can't know in advance what's needed.
- `web/app.py` calls the tools **directly, in parallel**, because every
  row needs the same four things, and computes the ranking in ordinary
  Python. Claude is used for exactly one job: writing the analysis on the
  detail page.

The general lesson: LLMs make poor sorting functions -- slow, costly, and
inconsistent between runs -- and good explainers. Rank with rules;
interpret with the model.

### Running it

```bash
cd ~/Documents/market-agent
source .venv/bin/activate
pip install -r requirements.txt   # flask, added for the dashboard
python3 web/app.py
```

Open <http://127.0.0.1:5050>. Your watchlist saves to `web/watchlist.json`
(gitignored -- it's per-machine state, not source). Ctrl+C stops it.

### Starting it without the terminal

Double-click `start.command` in Finder. It activates the virtualenv,
starts the server and opens the browser for you. Closing the window stops
it. (macOS may ask you to confirm the first time, since it's a script you
downloaded rather than an app — right-click → Open once, then double-click
works from then on.)

### Tests, and the two kinds of them

There are two categories here and the distinction matters more than it
looks.

**Free, offline, instant** — run these constantly:

```bash
python3 web/test_app.py        # dashboard: scoring, filtering, routes, chat, degradation
python3 test_agent.py          # agent loop: chaining, errors, runaway protection
python3 tools/test_calc.py     # the calculator, mostly what it refuses
python3 evals/test_checks.py   # the eval checks themselves
```

None of these touch the network or call a model. They stub everything, so
they're fast and can't fail because Yahoo rate-limited you — a test that
fails for reasons unrelated to your code teaches you nothing. Stubbing also
lets you construct exact scenarios ("a stock down 6% with earnings in three
days") that you could never arrange with live data.

That third suite exists because **a check suite that always passes is worse
than none** — it hands you confidence you haven't earned. So it feeds
deliberately bad output through the checks and asserts they FAIL.

**Costs money, calls the real model** — run these when you change a prompt:

```bash
python3 evals/run_evals.py             # the brief's writing
python3 evals/run_agent_evals.py       # the agent's tool choices
python3 evals/run_evals.py --runs 3    # three times each, for variance
python3 evals/run_evals.py --dry-run   # exercise the harness, no API calls
```

### Agent evals: real model, fake data

`test_agent.py` and `run_agent_evals.py` look similar and test opposite
things:

| | model | data | question answered |
|---|---|---|---|
| `test_agent.py` | fake | fake | does the **loop** work? |
| `run_agent_evals.py` | **real** | fake | does the **model choose** well? |

The distinction matters. A stub model replays a script someone wrote, so
asserting that it "chose the right tool" is marking your own homework —
tool selection is a decision the real model makes by reading tool
descriptions, and only the real model can be tested on it. The data stays
stubbed so assertions can be exact: "NVDA reports soonest" is checkable
only if we control the dates. Swap the data, keep the brain.

These evals assert on the **trace as much as the text**, because a right
answer reached by guessing and a right answer reached by looking things up
read identically — only the tool calls tell them apart. So a scenario can
require that `get_watchlist` was called before claiming to know what you
own, that `get_earnings_schedule` ran at least three times rather than
checking one name and generalising, and that `calculate` was used instead
of mental arithmetic.

### "Will it go up after earnings?"

It won't answer that, and the reason isn't policy. Short-term direction
around a print isn't knowable, so an answer would be invention delivered
in a confident voice — the exact failure this project spends its evals
defending against.

The question underneath it *is* answerable, though, and the app was doing
a poor job of it. So the detail page has a **Going into earnings** panel
built entirely from things that already happened:

- The actual next-session move after each of the last eight reports,
  drawn as a diverging bar chart, with the typical size stated as a
  single figure.
- How often the company beat, and — the useful part — **how often it beat
  and the stock fell anyway**.
- Where the analyst estimate has moved over ninety days, and whether it's
  being revised up or down in the last month.

That third pairing is what makes it more than a data dump. For MU the
evidence reads: beat the estimate in **8 of 8** reports, and still fell
the next session **5 times**. Anyone asking "will it rise if they beat?"
has a documented answer for that name — *not reliably* — because the
market prices the expectation, not the analyst number. Meanwhile the
estimate is up 38% over ninety days while being trimmed twice in the last
month: expectations set high, softening at the margin.

None of that predicts the next move. All of it is evidence about the
setup, which is the honest version of what the question was after.

**What each bar compares**, since a percentage with unstated endpoints is
a number taken on faith: the closing price just before the news, against
the close of the first session that could react to it. Hovering a bar
shows both prices, the date, whether the report landed before the open or
after the close, and the EPS surprise.

That last detail is not cosmetic. US companies report either before the
open or after the close, and the reacting session differs — a company
reporting at 16:00 is first traded on the news the *next* day, one
reporting at 07:00 is traded on it the *same* day. The first version
ignored the clock and always took the next day, which for every
before-open reporter measured a session with no news in it at all. The
timestamp was there the whole time; it just wasn't being read.

Worth noting how that bug surfaced: someone asked what the number was
comparing. The answer was fuzzy in the UI *and* in the code, and those two
turned out to be the same fault.

### News: summaries, not just headlines

The detail page's "What's going on" panel synthesises the coverage on one
stock. For a while it was doing that from **headlines alone**, because
`get_recent_news` captured title, publisher, link and time and threw the
rest away.

That's a real limitation, not a cosmetic one: two articles under near
identical headlines routinely give different reasons, and a headline-only
summary cannot tell them apart — which is exactly the distinction someone
who doesn't want to open six tabs is looking for.

`tools/probe_news.py` settled it by dumping the actual payload rather than
guessing: every item carries a `summary` of a couple of hundred plain-text
characters, plus an HTML `description`. Both were being discarded. They're
captured now, the analysis prompt is told to use them and to say when the
pieces disagree, and each headline in the UI shows its summary underneath
so the list is skimmable without clicking.

The probe also turned up something worth surfacing: a good share of items
are `contentType: VIDEO`. Offering a "summary" of something the reader can
only watch is a small lie, so videos are tagged as such in the list.

The general habit: **check what the data actually contains before
designing around what you assume it contains.** One probe script turned a
speculative feature discussion into a ten-line change — and a second one,
for earnings data, found that the "unavailable endpoint" behind the empty
Earnings page had been a missing `lxml` package the whole time.

### When your own sense of "plausible" is out of date

Reviewing an early agent answer, I said MU revenue of $41.5B "looks wrong
— Micron's quarterly revenue is around $10B." The probe later showed 33
analysts expecting $50.8B, against $11.3B a year earlier, and an EPS
series climbing 0.62 → 1.18 → 4.78 → 12.20 → 25.11.

The data was real. My sense of normal came from training data months out
of date, which is precisely the mistake the prompts warn the model about.

So the agent's instruction changed. It used to say a figure that looks
implausible should be called out as probably wrong. It now says to state
the comparison — "revenue of $50.8B, roughly 4.5x the $11.3B a year
earlier" — and let the reader judge. **Asserting that real data is an
error is its own kind of confident mistake**, and a model's priors are
staler than the data it just fetched.

### A watchlist is not a portfolio

The first agent eval run produced *"Nvidia, which you do own"*. Nothing in
this app knows what anyone owns — it tracks a list of names. Claiming
ownership is a factual assertion with no basis, and it would be a
genuinely bad one to make in a finance tool.

What made it instructive: **my own scenario question caused it.** I had
written "what moved most that I don't already own", so the agent simply
adopted the framing back. The conflation had also spread to the brief's
prompt, a tool description, a chat starter and a section heading — four
places, all written by me, none noticed until a judge objected to the
wording.

Both prompts now state the distinction outright, and `test_agent.py`
scans the source for `you own` / `your holdings` / `your position` so the
phrasing can't quietly return. That check is a lint rather than a proof:
the rules that ban the phrasing have to quote it, so a window around each
hit is searched for a prohibition marker. It's verified in both
directions — clean tree passes, an injected violation fails.

### The calculator, and why not eval()

Language models do arithmetic in their heads and are unreliable at it —
confidently so, which is the dangerous half. The first real terminal run
reported MU revenue and margins far outside anything plausible for the
company, stated as fact. `tools/calc.py` moves the arithmetic to Python,
and the agent's prompt tells it to use the tool for every computation.

The obvious implementation is `eval(expression)`. Don't: eval runs
arbitrary Python, so any string reaching it — from a model, a user, a
request — can import modules, read files, open sockets. It doesn't matter
that this runs locally; the habit is the problem. Instead the expression
is parsed to a syntax tree and walked, permitting only the node types
arithmetic needs. `__import__("os").system(...)`, `(1).__class__`,
attribute access, lambdas and comprehensions are structurally absent
rather than merely discouraged, and `tools/test_calc.py` spends most of
its assertions proving each one is refused.

### Evals — testing the part that isn't deterministic

Everything above tests code that either works or doesn't. Evals test the
writing, which is the only part of this that's actually AI. Without them
the brief could drift into giving investment advice, or miss the one thing
that mattered, and nothing would catch it — you'd find out by reading it.

Four scenarios, each built around a specific failure mode: does it
manufacture drama on a quiet day, does it find the single name that
matters, does it see a sector selloff as one story rather than three, does
it look beyond the watchlist when something bigger happened elsewhere.

Checks come in two kinds, and the split is the important idea. **Cheap
checks** are regex and string work — did it name the ticker, did it avoid
every phrasing that would make it advice, is it the right shape. Free,
instant, completely reliable. **Expensive checks** need judgement ("did it
identify the right thing as most important?"), so a second model call
grades the output against a written rubric. That judge is slower, costs
money, and is itself fallible — which is exactly why anything regexable
gets regexed instead. The judge also fails *closed*: an unparseable or
errored verdict counts as a failure, never a pass.

The themes eval carries one check worth copying into any project that
groups things: **no invented tickers**. The model is handed a set of names
and asked to cluster them, and the tempting failure is to add a plausible
peer that was never in the input. That's the hallucination shape this
feature actually has, so that's what gets tested.

**On variance:** a single run is an anecdote, not a measurement. The same
prompt can pass once and fail the next time. When you change a prompt and
want to know whether it genuinely improved, use `--runs 3` or more and
compare pass *rates*, not single outcomes.

For that to work, **check labels must be stable across runs** — the label
is the aggregation key. An early version put the measured value into the
label (`reasonable length (got 823 chars)`, and the judge's reason), so
every run produced a different key and `--runs 3` printed three separate
lines instead of one pass rate. The check that most needed variance
reporting was precisely the one where it silently didn't work. Labels are
now fixed strings and the varying part is printed separately as detail.

### When to stop tuning

Chasing 100% is a trap. An eval that always passes has stopped telling you
anything, and the way you get there is by loosening rubrics until nothing
can fail — which quietly destroys the thing you built them for.

Read the *shape* of the failures instead of the count:

**0/N — systematic.** Something is genuinely wrong. Usually the rule, not
the model: two scenarios failing every run is what exposed an over-broad
posture rule that was flagging the product's core purpose.

**N/N — passing.** Good, but only meaningful if the check can fail; that's
what `evals/test_checks.py` exists to prove.

**Mixed, on borderline wording — probably noise.** Here you need to know
whether the *brief* varied or the *judge* did, and that's what
`--judge-stability N` answers: it generates one brief and judges that same
fixed text N times. If verdicts differ on identical input, the
disagreement belongs to the judge, and no amount of prompt-tuning on the
brief will settle it.

```bash
python3 evals/run_evals.py --judge-stability 5 --scenario quiet_day
```

There's a catch worth knowing: that command generates a *fresh* brief, so
you get whatever the model wrote this time — rarely the borderline one you
actually wanted to examine. The first real use of it came back 5/5 on a
perfectly clean brief, which proved the judge was consistent but said
nothing about the ambiguous sentence that prompted the question.

So genuinely borderline output gets saved to `evals/borderline/` and
judged as fixed text:

```bash
python3 evals/run_evals.py --judge-stability 5 --scenario quiet_day \
    --text evals/borderline/quiet_day_catalysts.txt
```

Now the input is constant and only the judge varies. A split verdict on
identical text means the *standard* is ambiguous there, and the honest fix
is to sharpen the rubric rather than tune the brief until that phrasing
stops appearing.

**Tuning toward a standard is not the same as loosening one.** The
stability run is what tells you which you're doing. When the saved
borderline case came back 0/5 with the same reason every time, the
standard was demonstrably solid and the brief was intermittently missing
it — so changing the brief's prompt was legitimate. Had it come back 3/5,
the standard itself would have been the ambiguous thing, and changing the
brief would have been training the model to dodge a question nobody had
answered.

A residual failure rate on genuinely ambiguous sentences is healthy. It
means the standard still has teeth.

### What the first real eval run found

Worth recording, because it's what evals are for.

The judge caught one failure: the brief wrote "NVDA took an 8.4% hit **as**
the U.S. expanded chip export restrictions", asserting causation the data
doesn't establish. The same run hedged correctly in a different scenario
("moves that **appear related to** a trial readout") — so the model wasn't
incapable, it was inconsistent, which no single run could have revealed.

Reading the output caught two more the checks missed. **Posture advice**
using no forbidden word — "days like this are about preservation, not
action", "if you've been watching from the sidelines" — and **invented
detail** not present in the input ("precisely what Nvidia uses in its AI
accelerators"). The prompt now bans all three explicitly, with a worked
example of hedged versus asserted causation.

Then a lesson about the checks themselves: the first attempt to catch
posture advice with regex caught *neither* real sentence — one used "from
the sidelines" where the pattern said "on", and the other was not an idiom
at all. Chasing it with patterns overfits to one run; the next says "today
rewards patience" and walks through. So fixed idioms stay in regex and the
general case moved to the judge. **Regex what is fixed, judge what is
not** — and verify new patterns against the actual failing sentences,
plus legitimate ones, so you can see the false-positive rate.

After the prompt fix, `--runs 3` on that scenario passed 3/3.

### Known limits### Known limits

- Free delayed data via yfinance; no intraday streaming, options flow, or
  dark pool data.
- Market open/closed doesn't account for holidays.
- Notes and alerts are not built yet. Real alerts (fire while you're not
  looking) need a background scheduler, not just a web server.
- Discover depends on Yahoo's screener endpoint; if it's unavailable the
  page falls back to a fixed large-cap list and labels itself as such.
- Nothing here is financial advice, and the prompts explicitly forbid the
  model from giving buy/sell/hold opinions or price targets. It describes
  and contextualises; it doesn't recommend.
