# Momentum Trading System

A quantitative momentum strategy that automatically rebalances a 20-stock portfolio every quarter — 10 S&P 500 stocks traded automatically via IBKR, and 10 TSX stocks recommended for manual execution.

**Strategy:** 6-month momentum signal, 21-day skip, quarterly rebalance (`QE`)  
**Universe:** S&P 500 (top 10) + S&P/TSX Composite (top 10)  
**Execution:** S&P 500 auto-traded via IBKR · TSX emailed as manual instructions

---

## Backtest results (2006–2026)

Tested on 20 years of data (2006-03-18 → 2026-03-18), $100,000 starting capital.

| Metric | 50/50 Blended | TSX Index |
|--------|:-------------:|:---------:|
| **Total Return** | **8,368%** | 146% |
| **Annualized Return** | **25.20%** | 4.72% |
| Annualized Volatility | 26.32% | 14.96% |
| **Sharpe Ratio** | **0.84** | 0.11 |
| Sortino Ratio | 1.20 | 0.13 |
| Max Drawdown | -51.75% | -39.72% |
| Win Rate (quarterly) | 72.2% | 65.4% |
| Avg Winning Quarter | +12.56% | +5.44% |
| Avg Losing Quarter | -9.70% | -6.61% |

### Year-by-year

| Year | Strategy | TSX Index | Alpha |
|------|:--------:|:---------:|:-----:|
| 2007 | +49.73% | +7.16% | +42.57% |
| 2008 | -41.15% | -35.03% | -6.12% |
| 2009 | +25.46% | +30.69% | -5.23% |
| 2010 | +57.25% | +14.45% | +42.81% |
| 2011 | -18.16% | -11.07% | -7.09% |
| 2012 | +7.16% | +4.00% | +3.16% |
| 2013 | +56.05% | +9.56% | +46.50% |
| 2014 | +8.41% | +7.42% | +0.99% |
| 2015 | +20.84% | -11.09% | +31.93% |
| 2016 | +29.31% | +17.51% | +11.81% |
| 2017 | +19.93% | +6.03% | +13.90% |
| 2018 | -2.20% | -11.64% | +9.43% |
| 2019 | +40.30% | +19.13% | +21.17% |
| 2020 | +74.74% | +2.17% | +72.57% |
| 2021 | +79.68% | +21.74% | +57.94% |
| 2022 | +3.79% | -8.66% | +12.45% |
| 2023 | +46.65% | +8.12% | +38.53% |
| 2024 | +33.85% | +17.99% | +15.87% |
| 2025 | +62.14% | +28.25% | +33.89% |

The strategy outperformed the TSX index in **16 of 19 years**.

![Performance chart](blended_momentum_performance.png)
![Annual returns](blended_annual_returns.png)

> **Note:** Returns are in local currency (CAD for TSX positions, USD for S&P 500 positions). Past performance does not guarantee future results.

---

## How it works

Each quarter the system:
1. Downloads ~700 S&P 500 + ~200 TSX prices from Yahoo Finance
2. Ranks stocks by 6-month momentum (skipping the most recent month)
3. Selects the top 10 from each universe
4. **S&P 500 side** — sells exited positions and buys new ones automatically via IBKR
5. **TSX side** — prints and emails exact share counts for you to place manually

---

## Project structure

```
momentum/
├── momentum_trading_system_complete.py   Signal generation & portfolio selection
├── broker.py                             IBKR order execution (ib_insync)
├── live_trader.py                        Full rebalance: auto S&P 500 + manual TSX
├── rebalance_job.py                      Cron entry point — logs + email notification
├── dashboard.py                          Streamlit portfolio dashboard
├── tsx_backtest.ipynb                    50/50 blended backtest (S&P 500 + TSX)
├── live_trading_system.ipynb            Development & testing workspace
├── .env                                  Your credentials (not committed)
├── .env.example                          Template for .env
└── requirements.txt                      Python dependencies
```

---

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|----------|-------------|
| `IBKR_HOST` | TWS host, usually `127.0.0.1` |
| `IBKR_PORT` | `7497` (TWS paper) · `7496` (TWS live) · `4002` (Gateway paper) |
| `IBKR_PAPER` | `true` for paper trading, `false` for real money |
| `USD_CAD_RATE` | Fallback FX rate if IBKR doesn't report USD portfolio value |
| `EMAIL_FROM` | Gmail address to send notifications from |
| `EMAIL_TO` | Email address to receive rebalance reports |
| `EMAIL_APP_PASSWORD` | Gmail app password (16 characters) |

**Gmail app password:** myaccount.google.com → Security → App passwords

### 3. Enable IBKR API

In TWS: `Edit → Global Configuration → API → Settings`
- Enable ActiveX and Socket Clients
- Socket port: 7497 (paper) or 7496 (live)

### 4. Register the quarterly cron

```bash
crontab -e
```

Add this line:
```
35 9 15 3,6,9,12 * cd "/Users/xiangrumo/Documents/Quantitative Trading Systems/momentum" && .venv/bin/python rebalance_job.py >> live_trading_data/logs/cron.log 2>&1
```

This fires at **9:35 AM on the 15th of March, June, September, December**.

### 5. Auto-wake your Mac (if not using a server)

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 09:20:00
```

Also add TWS to **System Settings → General → Login Items** so it opens automatically.

---

## Running manually

```bash
# Paper trading (default)
python live_trader.py

# Real money
python live_trader.py --live
```

On rebalance day, the output shows:

```
======================================================================
  TSX MANUAL TRADING INSTRUCTIONS
  TSX allocation: $49,000.00 CAD  |  Per position: $4,900.00 CAD

  SELL — 2 position(s) dropped out of top 10:
    SELL  CNQ.TO          150 shares  (avg cost $42.30)

  HOLD — 7 position(s) remain in top 10:
    HOLD  RY.TO          rank #1   momentum +24.3%

  BUY — 1 new position(s) entered top 10:
    BUY   BCE.TO            82 shares  @ ~$   59.75  = $4,899.50 CAD
======================================================================

======================================================================
  S&P 500 AUTO-REBALANCE PLAN  (orders placed automatically)
  S&P 500 allocation (50%): $36,000.00 USD  |  Per position: $3,600.00 USD

  SELL — 1 position(s) dropped out of top 10:
    SELL  META           20 shares  @ ~$  512.30  ≈  $10,246.00 USD

  BUY — 1 new position(s) entered top 10:
    BUY   ORCL           20 shares  @ ~$  174.25  =   $3,485.00 USD

  Placing orders now...
======================================================================
```

After the run, the full log is emailed to `EMAIL_TO` (if configured).

---

## Dashboard

```bash
streamlit run dashboard.py
```

---

## Backtest

Open `tsx_backtest.ipynb` to run the 50/50 blended backtest (S&P 500 + TSX).

---

## Cloud deployment (optional)

To run without keeping your Mac on, deploy to a VPS with IB Gateway + Docker:

```yaml
# docker-compose.yml
services:
  ib-gateway:
    image: ghcr.io/gnzsnz/ib-gateway:stable
    environment:
      TWS_USERID: "your_ibkr_username"
      TWS_PASSWORD: "your_ibkr_password"
      TRADING_MODE: paper
    ports:
      - "4002:4002"
```

Update `.env`: `IBKR_PORT=4002`

Then register the same cron on the VPS — it runs 24/7 with no action required from you.
