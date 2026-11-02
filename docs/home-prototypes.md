# Home page prototypes

> **Decision, November 2026: B.** The owner chose layout B, the ranked
> list with the brief in a drawer, as the home page. A, C, the switch
> between them and the old theme-card home were removed; this note is kept
> as the record of what was compared and why. The `?home=` parameter no
> longer does anything.

The review (`MarketAgent_Review_and_Improvement_Plan.md`, section 8) found
that the home page opens with the AI brief, which fills the first screen on
a phone, so the reader has to read before they see what to look at. It asks
for the first screen to show the three changes most worth checking -- the
company or theme, the factual reason, the data time, and a way to the
evidence -- with the brief collapsed and upcoming reports shown separately.

Three alternative layouts do that in different ways. They sit behind a
query parameter, and without it the home page is the current one,
unchanged. Pick one; the rest can then be deleted.

## Opening them

```
python3 web/app.py
```

then open:

| Layout | URL |
|---|---|
| Current (default) | http://127.0.0.1:5050/ |
| A · top three cards | http://127.0.0.1:5050/?home=a |
| B · ranked list + brief drawer | http://127.0.0.1:5050/?home=b |
| C · phone-first | http://127.0.0.1:5050/?home=c |

The parameter is a real query string, not part of the `#/` route, so it
stays while you click into a stock or theme and come back with Back or the
sidebar's Home link. Each prototype has a dashed strip at the top for
switching between them. To see the phone layout in a desktop browser, use
the developer tools' device mode at about 390px wide.

All three use only what the home page already loads: `/api/home` (themes,
companies, attention scores and factors), `/api/brief`, `/api/earnings`, and
the session from `/api/overview`. Nothing on the server changed.

## How the top three are chosen

`protoTopThree()` in `web/static/app.js`. Nothing is re-scored; it reads the
attention score, level and reason chips the server already computes for
each company against its own peers (`compute_attention` in `web/app.py`).

1. Candidates are companies at level **high** or **medium** -- a score of
   1.71 or more, "worth a look" on the existing scale. Quiet and incomplete
   names never qualify, so a calm day shows fewer than three (or a line
   saying nothing was worth a look) rather than padding with names that
   didn't move.
2. A company in two themes counts once, at its higher score.
3. Highest score first; a tie goes to the larger gap to its peers, then the
   ticker, so the order doesn't change between loads.
4. A company that **moved with its theme** (attribution "With theme") and
   has **no report coming** within two weeks, and isn't on a report's
   reaction day, is the theme's story, not its own. It becomes
   one entry for the theme, ranked at that company's score, and the theme's
   other such companies are skipped. Without this, three chip companies
   falling 6% together would take all three places with one story. A
   company with a report due stays its own entry even if it moved with its
   theme, because the report is its own.
5. The first three (B shows up to ten).

A company entry shows the server's own reason chips (`-6.0% move, 4.0x
usual`, `earnings in 3d`, `+4.1pt vs peers, 2.0x usual`, `report reaction`,
`news unavailable`) and its With theme / Own move tag, and links to the stock page (chart, news,
analysis, report). A theme entry shows the theme card's own figures --
average move, gap to its benchmark, how many companies moved together, and
the company that led -- and links to the theme page. Hovering a company
entry gives the same score breakdown as the theme cards.

The data time is the session line the pages already use: "Today's session,
as of 2:41 PM ET (delayed)" while the market is open, "Fri, Oct 30 session
-- market pre-market now" before the open, or "Snapshot of ..." in the
static demo.

## A · top three cards

```
+------------------------------------------------------------+
| Home                                                       |
| WORTH CHECKING FIRST          Fri, Oct 30 session -- ...   |
| +----------------+ +----------------+ +----------------+   |
| | 1 CRASH  -6.0% | | 2 Chips  -6.0% | | 3 SOLO   +4.0% |   |
| |   Chips        | |   Theme · 3 co.| |   Other        |   |
| | (-6.0% move)   | | (avg -6.0%)    | | (+4.0% move)   |   |
| | (earnings 3d)  | | (-1.0pt vs ETF)| | (+4.1pt vs pr.)|   |
| | [With theme]   | | (led by PEER2) | | [Own move]     |   |
| | Open CRASH ->  | | Open theme ->  | | Open SOLO ->   |   |
| +----------------+ +----------------+ +----------------+   |
| AI BRIEF                              [Read the brief]     |
| Chips fell together: CRASH -6.0%, PEER1 -5.5% ...          |
| REPORTING IN THE NEXT 14 DAYS                  Calendar -> |
|  in 3d   CRASH  Chips                              Nov 5   |
|  in 12d  QUIET  Other                              Nov 14  |
| THEMES                                                     |
| [current theme cards, unchanged]                           |
```

**First:** three cards, one per change, each with the name, the move, the
reason chips, the session, and a link to the evidence. On a phone they
stack, so the first screen of a 390px phone holds about two cards.

**Then:** the brief cut to its first sentence, with "Read the brief" to
open the rest; reports due in the next two weeks; and the current theme
cards, reading guide and New theme form exactly as today.

**Why:** the smallest change from today's page. It puts a summary above
the page the owner already knows and takes nothing away.

**Trade-offs:** the longest page of the three -- the theme cards repeat
the companies the top three already named. The brief's first sentence is
a model's sentence on the first screen; it may not be the most useful one.
Splitting at ". " followed by a capital can stop early on "U.S. Steel".

## B · ranked list + brief drawer

```
+-----------------------------------------+------------------+
| Home                         [AI brief] |                  |
| Ranked by attention · Fri, Oct 30 ...   |                  |
| +-------------------------------------+ | REPORTING IN THE |
| | 1 CRASH Chips               -6.00%  | | NEXT 14 DAYS     |
| |   (-6.0% move)(earnings 3d)[With th]| |  in 3d  CRASH    |
| | 2 Chips Theme · 3 co.       -6.00%  | |  in 12d QUIET    |
| |   (avg -6.0%)(-1.0pt vs CHIPETF)... | |                  |
| | 3 SOLO Other                +4.00%  | | THEMES           |
| |   (+4.0% move)(+4.1pt vs peers)...  | |  Chips -6.00% .. |
| |-- ALSO WORTH A LOOK ----------------| |  Other +1.27% .. |
| | 4 CALM Other                -0.30%  | |                  |
| +-------------------------------------+ |                  |
+-----------------------------------------+------------------+
  [AI brief] opens a drawer from the right (full width on a phone)
```

**First:** one ranked list of everything worth a look across all themes,
up to ten, the top three set larger and the rest under "Also worth a look".
Beside it (below it on a phone), reports in the next two weeks and every
theme as a single line with its move against its benchmark.

**The brief** is not on the page. The "AI brief" button opens it in a
drawer; Close, the backdrop or Escape shuts it. It is fetched only when
first opened.

**Why:** the review's point taken furthest. The page is the data, the
model's text is something you ask for, and the reader sees the whole
day's ranking without scrolling past theme cards.

**Trade-offs:** no theme cards, so benchmark, breadth and spread are a
click away on each theme page. A reader who relied on the brief has to
know to press the button. Because the brief is fetched on demand, opening
the page no longer costs a model call -- but the first open waits for one.
The drawer reuses the current brief panel, whose footer says "from the data
below", which is slightly off in a drawer. On a phone the ranked list fills
the first screen and the reports block comes after it.

## C · phone-first

```
+----------------------------------+
| 3 changes to check               |
| Fri, Oct 30 session -- ...       |
| +------------------------------+ |
| | CRASH                 -6.00% | |
| | Chips                        | |
| | (-6.0% move)(earnings in 3d) | |
| | [With theme]                 | |
| | Open CRASH: chart, news ->   | |
| +------------------------------+ |
| | Chips                 -6.00% | |
| | ...                          | |
| +------------------------------+ |
| | SOLO                  +4.00% | |
| +------------------------------+ |
| REPORTING THIS WEEK   Calendar ->|
|  in 3d  CRASH  Chips     Nov 5   |
| > AI BRIEF  Chips fell togeth... |
| THEMES                           |
|  Chips   -6.00%  -1.00pt vs ...  |
|  Other   +1.27%  +1.07pt vs SPY  |
+----------------------------------+
```

**First:** the count as the heading ("3 changes to check", or "Nothing
stands out"), the session under it, and the three changes as large tap
targets with the name and move in 20px type.

**Then:** reports this week only, the brief folded into one line (its
first sentence, cut at two lines; tap to open the whole brief), and the
themes as a list. It is one column at most 560px wide, even on a desktop.

**Why:** most of the review's complaint is about the phone. This is built
for a phone first, and everything on it fits a thumb-scroll.

**Trade-offs:** on a desktop it leaves most of the screen empty and drops
the theme cards and the New theme form (themes are still in the sidebar
and the list; new themes need the default page or a theme page). Only
seven days of reports, against fourteen in A and B. The brief still loads
with the page, so the model call is spent whether or not it's opened.

## What to compare first

Open each on a phone (or at 390px) with a real watchlist and ask: without
scrolling, can I name the three things to check and why? Then check that
the theme entry (rule 4 above) reads right on a day when a whole theme
moves -- it's the one judgment the layouts add on top of the existing
score.

## Keeping one

The code is in labelled sections:

- `web/static/app.js`: "home prototypes: shared" (switch, the top-three
  rule, data time, the upcoming and theme-list blocks, the brief teaser),
  then one section each for A, B and C, ending in `HOME_PROTOTYPES`.
- `web/static/style.css`: "home prototypes: shared", then one block each.
- `web/test_app.py`: `check_home_prototypes`.

To keep one, delete the other two variants' sections, their entries in
`HOME_PROTOTYPES` and `buildProtoSwitcher`, then either keep the parameter
or make the variant the default in `showHome()`. Drop the shared helpers
the kept one doesn't call (A uses the brief teaser; C its own brief fold;
B neither).

## Tests

`check_home_prototypes` in `web/test_app.py` (part of `run_tests.py`)
checks that `showHome()` tests the switch first and draws the current page
unchanged after it, that each variant is wired up and has its own sections,
and that `app.js` parses. It then runs the DOM-free slice of the prototype
code in node against the stubbed `/api/home` and `/api/earnings`: the top
three, the theme entry, the reasons, a calm day, the brief's first
sentence and the reports window. Without node those checks print SKIP; CI's
Ubuntu runner has it. No browser runs in the tests, so layout and phone
width were checked by hand.
