# Range Bot — 20-day trading-range bot

Trades your tested 20-day range strategy. Starts on **Alpaca paper** (virtual
money, real prices) and flips to **Schwab live** when you've proven it. Hard
risk controls gate every order. Designed to run **once per day** on a schedule.

> Not investment advice. This strategy has **not** been backtested or shown to
> make money — it's a rule set. Prove it on paper for weeks before a real dollar
> goes near it. You own the risk.

## What's in here

```
strategy.py        the brain — range/breakout math (pure functions)
risk.py            position sizing + daily-loss / position-count guardrails
runner.py          the once-a-day loop and CLI
config.py          all tunable settings (edit these)
selftest.py        proves the whole pipeline offline, no keys needed
brokers/
  base.py          common broker interface
  alpaca.py        Alpaca adapter (paper + live)   <- you run this first
  schwab.py        Schwab adapter (live target)
  mock.py          offline fake for the self-test
```

## 1. Install & self-test (no keys)

```bash
pip install -r requirements.txt
python selftest.py          # should print ALL GOOD ✓
python runner.py --broker mock --mode range --dry-run   # watch a full pass
```

## 2. Paper trading on Alpaca

1. Make a free account at **app.alpaca.markets**, open a Paper account, and
   generate paper API keys.
2. `cp .env.example .env` and paste the keys into `ALPACA_API_KEY` /
   `ALPACA_API_SECRET`.
3. Dry run (prints intended orders, submits nothing):
   ```bash
   python runner.py --broker alpaca_paper --dry-run
   ```
4. Let it actually place paper orders:
   ```bash
   python runner.py --broker alpaca_paper
   ```

Watch it in the Alpaca dashboard. Run it daily and judge it over weeks across
different market conditions before you trust it.

## 3. Configure

Edit `config.py`. The knobs that matter most:

| setting | default | meaning |
|---|---|---|
| `watchlist` | 8 large caps | symbols to scan |
| `mode` | `range` | `range` (buy support) or `breakout` (buy strength) |
| `min_score` | 60 | skip setups weaker than this (0–100) |
| `risk_per_trade_pct` | 0.01 | risk 1% of equity between entry and stop |
| `max_position_pct` | 0.25 | max 25% of equity in one name |
| `max_open_positions` | 4 | concurrent position cap |
| `daily_loss_limit_pct` | 0.03 | freeze new entries if down 3% on the day |

Every entry is a **bracket order**: a stop-loss and take-profit attach
automatically, so exits happen even if the bot isn't running.

## 4. Schedule it (run once a day)

It's a daily-bar strategy — run it a few minutes before the close.

- **macOS/Linux cron** (3:55pm ET weekdays):
  ```
  55 15 * * 1-5  cd /path/to/range_bot && /usr/bin/python3 runner.py --broker alpaca_paper >> bot.log 2>&1
  ```
- **Windows**: Task Scheduler, same command.
- **GitHub Actions**: a scheduled workflow with your keys as secrets.

## 5. Going live on Schwab (only after it proves out)

One-time setup:

1. Schwab brokerage account with **thinkorswim enabled**.
2. Register an **Individual Developer** app at developer.schwab.com — add the
   "Accounts and Trading Production" + "Market Data Production" products,
   callback `https://127.0.0.1`. Approval takes a few days.
3. Mint your refresh token:
   ```bash
   python -c "from brokers.schwab import get_schwab_refresh_token as g; g('APPKEY','APPSECRET')"
   ```
   Put the result in `.env` as `SCHWAB_REFRESH_TOKEN`, plus your
   `SCHWAB_ACCOUNT_HASH`.
4. Run it — note the explicit real-money flag is required:
   ```bash
   python runner.py --broker schwab --i-understand-live
   ```

Heads up: Schwab's **refresh token expires every ~7 days**, so you'll redo the
browser login weekly. That's a Schwab limitation, not the bot's.

## Safety model

- Defaults to the mock broker; `--dry-run` submits nothing.
- Real-money brokers (`alpaca_live`, `schwab`) refuse to run without
  `--i-understand-live`.
- Nothing reaches a broker without passing the risk manager.

## Not built yet (good next steps)

A **backtest** over historical data — to see how these rules would actually have
done, and how often breakouts failed — before risking even paper conviction.
Ask and I'll add it.
