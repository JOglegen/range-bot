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
run_from_screener.py    trades top screener BUYs through Alpaca paper
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
2. Send the SMS summary through Twilio, if Twilio secrets are configured.
3. Paper-trade the top BUY signals through Alpaca paper using
   `run_from_screener.py`.
4. Save `portal/data/screener_results.json` and commit it back to the repo.
5. The portal deploy workflow publishes the latest scan to Netlify.

Required GitHub secrets for alerts:

```text
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM
TWILIO_TO
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
