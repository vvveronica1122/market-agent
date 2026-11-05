// Written by demo/build.py. Its presence switches the app into the static demo.
window.MARKET_AGENT_DEMO = {
 "snapshot_session": "2026-11-05",
 "captured_at": "2026-11-05T17:23-05:00",
 "captured_label": "Thu, Nov 5, 2026",
 "captured_time": "5:17 PM ET",
 "market_state": "after-hours",
 "model": "claude-sonnet-4-5",
 "repo_url": "https://github.com/vvveronica1122/market-agent",
 "chat": [
  {
   "question": "Which of my stocks reports soonest, and how did they do last quarter?",
   "answer": "Vistra (VST) reports soonest, tomorrow on November 6. Last quarter they missed badly on earnings, posting EPS of $0.76 versus the $1.63 estimate, a 53.4% miss. \n\nLooking at their quarterly results, revenue in Q2 2026 (ended June 30) was $4.02 billion with net income of $305 million and a 7.6% net margin. That was down sharply from Q1 when they had revenue of $5.64 billion, net income of $1.03 billion, and an 18.2% margin. The results show significant quarter-to-quarter variation, with both revenue and profitability swinging substantially between periods.",
   "trace": [
    {
     "elapsed_ms": 1,
     "input": {},
     "status": "ok",
     "step": 1,
     "summary": "themes=[4 items], all_tickers=[19 items]",
     "tool": "get_watchlist"
    },
    {
     "elapsed_ms": 627,
     "input": {
      "ticker": "NVDA"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=NVDA, next_date=2026-11-17, days_away=12, eps_estimate=2.47, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 482,
     "input": {
      "ticker": "AMD"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=AMD, next_date=2027-02-02, days_away=89, eps_estimate=2.95, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 514,
     "input": {
      "ticker": "AVGO"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=AVGO, next_date=2026-12-09, days_away=34, eps_estimate=3.84, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 587,
     "input": {
      "ticker": "TSM"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=TSM, next_date=2027-01-14, days_away=70, eps_estimate=5.16, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 565,
     "input": {
      "ticker": "MU"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=MU, next_date=2026-12-23, days_away=48, eps_estimate=38.29, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 410,
     "input": {
      "ticker": "SNDK"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=SNDK, next_date=2027-02-15, days_away=102, eps_estimate=57.12, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 461,
     "input": {
      "ticker": "WDC"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=WDC, next_date=2027-01-28, days_away=84, eps_estimate=5.87, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 600,
     "input": {
      "ticker": "STX"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=STX, next_date=2027-01-26, days_away=82, eps_estimate=9.27, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 484,
     "input": {
      "ticker": "AAPL"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=AAPL, next_date=2027-01-28, days_away=84, eps_estimate=2.9, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 488,
     "input": {
      "ticker": "MSFT"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=MSFT, next_date=2027-01-27, days_away=83, eps_estimate=4.86, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 458,
     "input": {
      "ticker": "GOOGL"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=GOOGL, next_date=2027-02-03, days_away=90, eps_estimate=3.2, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 489,
     "input": {
      "ticker": "AMZN"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=AMZN, next_date=2027-02-04, days_away=91, eps_estimate=2.41, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 527,
     "input": {
      "ticker": "META"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=META, next_date=2027-01-27, days_away=83, eps_estimate=8.33, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 611,
     "input": {
      "ticker": "TSLA"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=TSLA, next_date=2027-01-27, days_away=83, eps_estimate=0.5, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 439,
     "input": {
      "ticker": "VST"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=VST, next_date=2026-11-06, days_away=1, eps_estimate=2.43, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 443,
     "input": {
      "ticker": "CEG"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=CEG, next_date=2026-11-09, days_away=4, eps_estimate=3.88, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 467,
     "input": {
      "ticker": "GEV"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=GEV, next_date=2027-01-27, days_away=83, eps_estimate=6.91, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 639,
     "input": {
      "ticker": "ETN"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=ETN, next_date=2027-02-02, days_away=89, eps_estimate=4.12, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "elapsed_ms": 544,
     "input": {
      "ticker": "VRT"
     },
     "status": "ok",
     "step": 2,
     "summary": "ticker=VRT, next_date=2027-02-10, days_away=97, eps_estimate=2.28, last_report={...}, source=earnings_dates, unavailable_reason=None",
     "tool": "get_earnings_schedule"
    },
    {
     "as_of": "2026-06-30",
     "elapsed_ms": 419,
     "input": {
      "quarters": 4,
      "ticker": "VST"
     },
     "status": "ok",
     "step": 3,
     "summary": "4 items; first period=2025-09-30, revenue=4971000000.0, net_income=652000000.0, net_margin=13.1, currency=USD; last period=2026-06-30, revenue=4017000000.0, net_income=305000000.0, net_margin=7.6, currency=USD",
     "tool": "get_quarterly_results"
    }
   ]
  },
  {
   "question": "What moved most in the market today that isn't on my watchlist?",
   "answer": "Applovin (APP) was the biggest mover today that isn't on your watchlist, up 31.0% to $356.10. The company has a market cap of about $120 billion and saw very heavy trading volume with over 22 million shares changing hands.\n\nOn the downside, Fastly (FSLY) fell the most at -26.9% to $15.38, though it's much smaller at a $2.5 billion market cap.\n\nAmong other notable moves not on your list: Encore Capital (ECPG) gained 26.3%, ADMA Biologics (ADMA) rose 26.0%, and EPAM Systems (EPAM) climbed 20.6%. On the losing side, AXT Inc (AXTI) dropped 22.8%, MaxLinear (MXL) fell 22.1%, and Astera Labs (ALAB) declined 19.6%.\n\nNote that SNDK appears in the scan results down 22.3%, but that ticker is on your Memory & storage watchlist, so excluding it per your question.",
   "trace": [
    {
     "elapsed_ms": 2,
     "input": {},
     "status": "ok",
     "step": 1,
     "summary": "themes=[4 items], all_tickers=[19 items]",
     "tool": "get_watchlist"
    },
    {
     "elapsed_ms": 383,
     "input": {
      "limit": 20
     },
     "status": "ok",
     "step": 1,
     "summary": "20 items; first ticker=APP, name=Applovin Corporation, price=356.1, change_percent=31.03956, volume=22122914.0, market_cap=119628062720.0, screens=[1 items]; last ticker=ALAB, name=Astera Labs, Inc., price=179.47, change_percent=-19.617504, volume=11894931.0, market_cap=31368140800.0, screens=[1 it\u2026",
     "tool": "scan_market"
    }
   ]
  },
  {
   "question": "Compare the profit margins of the companies in my Memory & storage theme.",
   "answer": "In your Memory & storage theme, the profit margins show a wide range. Micron (MU) reports a 63.8% net margin, SanDisk (SNDK) 67.0%, and Western Digital (WDC) 69.2%. Seagate (STX) sits notably lower at 31.9%.\n\nWDC's net margin has a caveat: it exceeds the gross margin, meaning the last twelve months included one-off gains, so the 69.2% net margin overstates the ongoing business profitability. SNDK and MU show similar headline net margins without that warning, though both have gross and operating margins near 80%, while WDC's gross margin is only 52.6% and STX's is 50.4%.\n\nAt the operating margin level, which strips out non-operating items, MU and SNDK both show around 80%, WDC 47.7%, and STX 48.9%. That tells a clearer story than the net figures: MU and SNDK run at much higher operating profitability than WDC and STX.",
   "trace": [
    {
     "elapsed_ms": 2,
     "input": {},
     "status": "ok",
     "step": 1,
     "summary": "themes=[4 items], all_tickers=[19 items]",
     "tool": "get_watchlist"
    },
    {
     "elapsed_ms": 241,
     "input": {
      "ticker": "MU"
     },
     "status": "ok",
     "step": 2,
     "summary": "market_cap=742654935040.0, trailing_pe=8.830754, forward_pe=3.1593592, ev_to_sales=6.468, profit_margin_percent=63.8, gross_margin_percent=80.7, operating_margin_percent=80.7, revenue_growth_percent=379.3, earnings_growth_percent=1059.5, beta=2.398, analysts=45.0, sector=Technology, name=Micron Tec\u2026",
     "tool": "get_key_stats"
    },
    {
     "elapsed_ms": 197,
     "input": {
      "ticker": "SNDK"
     },
     "status": "ok",
     "step": 2,
     "summary": "market_cap=114746408960.0, trailing_pe=6.4452524, forward_pe=2.8073325, ev_to_sales=4.922, profit_margin_percent=67.0, gross_margin_percent=80.0, operating_margin_percent=79.6, revenue_growth_percent=377.9, earnings_growth_percent=6913.3, beta=None, analysts=24.0, sector=Technology, name=Sandisk Co\u2026",
     "tool": "get_key_stats"
    },
    {
     "elapsed_ms": 213,
     "input": {
      "ticker": "WDC"
     },
     "status": "ok",
     "step": 2,
     "summary": "market_cap=100180140032.0, trailing_pe=9.413648, forward_pe=6.6237116, ev_to_sales=8.343, profit_margin_percent=69.2, gross_margin_percent=52.6, operating_margin_percent=47.7, revenue_growth_percent=55.5, earnings_growth_percent=50.9, beta=2.344, analysts=24.0, sector=Technology, name=Western Digit\u2026",
     "tool": "get_key_stats"
    },
    {
     "elapsed_ms": 166,
     "input": {
      "ticker": "STX"
     },
     "status": "ok",
     "step": 2,
     "summary": "market_cap=107097145344.0, trailing_pe=24.46408, forward_pe=7.1398654, ev_to_sales=9.37, profit_margin_percent=31.9, gross_margin_percent=50.4, operating_margin_percent=48.9, revenue_growth_percent=61.0, earnings_growth_percent=212.3, beta=2.201, analysts=24.0, sector=Technology, name=Seagate Techn\u2026",
     "tool": "get_key_stats"
    }
   ]
  }
 ]
};
