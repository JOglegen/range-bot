# Range Bot - 20-day trading-range scanner and paper trader

Range Bot scans liquid US stocks for 20-day range setups, alerts entry/exit
levels, shows the latest scan in a Netlify portal, and can paper-trade the top
BUY signals through Alpaca. Schwab support exists as a live target, but live
execution should stay gated until it has been tested against your approved
Schwab developer app.

> Not investment advice. This is a rules engine and research tool. Paper-trade
> it first, verify fills and exits, and keep real-money execution behind
> explicit approvals.

## What is here

```text
strategy.py             range and breakout signal math
screener.py             S&P 500 scanner using yfinance
run_screener.py         daily scan, JSON output, SMS alerts
run_study_list.py       focused issue-driven study list scan
run_paper_challenge.py  $1,000 paper-only doubling challenge ledger
run_from_screener.py    trades top screener BUYs through Alpaca paper
monthly_dividend.py     verifies monthly dividend cadence and income quality
run_monthly_income.py   monthly dividend scanner, JSON output, SMS alerts
build_action_center.py  merges scans into one ranked operational action list
runner.py               broker-backed execution loop with risk checks
risk.py                 position sizing and account guardrails
backtest.py             portfolio backtester
portal/                 Netlify dashboard and scanner UI
brokers/alpaca.py       Alpaca paper/live adapter
brokers/schwab.py       Schwab adapter, live target, still needs validation
```

## Install and self-test

```bash
pip install -r requirements.txt
python selftest.py
python runner.py --broker mock --mode range --dry-run
```

`selftest.py` should print `ALL GOOD`.

## Daily operating flow

The `Range Bot - S&P 500 Screener + SMS` GitHub Action now does the full
paper workflow:

1. Scan the S&P 500 for 20-day range BUY, WATCH, EXIT, and BREAKDOWN signals.
2. Scan a monthly dividend universe for income candidates using live dividend
   history, trailing yield, monthly cadence, drawdown, and trend filters.
3. Scan the focused study list for symbols requested in GitHub issues.
4. Send the SMS summaries through Twilio, if Twilio secrets are configured.
5. Paper-trade the top range BUY signals through Alpaca paper using
   `run_from_screener.py`.
6. Update the `$1,000` paper-only challenge ledger from the latest BUY list.
7. Build `action_center.json`, a ranked operational list of trade entries,
   study-list alerts, watch/exit alerts, and monthly income candidates.
8. Save `portal/data/screener_results.json`, `portal/data/monthly_income.json`,
   `portal/data/study_results.json`, `portal/data/action_center.json`, and
   `portal/data/paper_challenge.json` back to the repo.
9. The portal deploy workflow publishes the latest scan to Netlify.

Required GitHub secrets for alerts:

```text
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM
TWILIO_TO
```

`TWILIO_TO` can be one number or several numbers separated by commas, spaces,
or new lines:

```text
+14175551234,+14175559876
```

Required GitHub secrets for Alpaca paper execution:

```text
ALPACA_API_KEY
ALPACA_API_SECRET
```

## Manual commands

Run the full range scan and SMS path:

```bash
python run_screener.py --mode range
```

Print the SMS without sending it:

```bash
python run_screener.py --mode range --dry-run
```

Run the monthly dividend income scanner:

```bash
python run_monthly_income.py --dry-run
```

Run the focused study list from issue #5:

```bash
python run_study_list.py --dry-run
```

Update the issue #6 paper challenge from a screener file:

```bash
python run_paper_challenge.py --screener screener_results.json
```

The paper challenge starts with `$1,000`, targets `$2,000`, uses fractional
paper shares, and never calls a broker. Entries come from 20-day range BUY
signals; exits come from stop, target, EXIT, or BREAKDOWN.
It also tracks a `$1,000` buy-and-hold `SPY` benchmark from the same start so
the dashboard can show whether RangeBot is ahead or behind the S&P 500 proxy.

Its default filters look for monthly payers with a trailing yield between 4%
and 15%, at least 10 paid months in the last year, and an income-quality score
of at least 55. This is an alert/watchlist tool, not an auto-buy rule.

Build the action center from existing scan files:

```bash
python build_action_center.py --screener screener_results.json --income monthly_income.json
```

The portal Action Center is the operational view. `TRADE ENTRY` rows are
paper-bot eligible, but Alpaca rechecks them before any paper order. `INCOME
WATCH` rows are alert-only and require manual review.

Paper-trade the latest BUY list after a scan:

```bash
python run_from_screener.py --input screener_results.json --broker alpaca_paper --top 5
```

Dry-run that same execution path:

```bash
python run_from_screener.py --input screener_results.json --broker alpaca_paper --top 5 --dry-run
```

## Safety model

- `run_from_screener.py` only allows `alpaca_paper` or `mock`.
- Every paper order is recomputed from broker market data before submission.
- Nothing reaches a broker without passing the risk manager.
- Bracket orders attach take-profit and stop-loss levels when enabled.
- Live brokers still require the explicit `--i-understand-live` flag in
  `runner.py`.

## Schwab live target

Schwab is not the next switch to flip. Before live Schwab execution, validate:

1. Approved Schwab developer app with trading and market-data products.
2. OAuth token refresh and account hash retrieval.
3. Read-only account, position, and price-history calls.
4. Tiny live or sandbox order tests for market, limit, stop, and bracket/OCO
   payloads.
5. A final manual approval gate for real-money execution.

The adapter is in `brokers/schwab.py`, but treat it as an integration target
until those checks pass.
