# S&P 500 Momentum Trading System Structure

This system implements an automated quantitative trading strategy based on price momentum (J=6, K=3). It calculates 6-month historical returns to identify the top 50 performing S&P 500 stocks, buys them, and holds them for 3 months (quarterly rebalancing).

The files in the project work together in three main phases: **Data & Signals**, **Execution (Brokerage)**, and **Monitoring (Dashboard)**.

---

## 🏗️ 1. The Core Components

### `broker.py`
**The Bridge to the Real World.**
This file contains the `AlpacaBroker` class. Its single responsibility is talking to the Alpaca API over the internet.
- **What it does:** Uses the API keys stored in your `.env` file to log into your account.
- **Key Functions:** `get_portfolio_value()`, `get_cash()`, `get_positions()`, and `place_market_buy()`.
- **How it fits in:** Whenever the trading algorithm decides it wants to execute a trade or needs to know how much cash you actually have, it calls methods from this file. It prevents the complex Alpaca API code from cluttering up your trading logic.

### `live_trader.py`
**The Brains of the Operation.**
This is the main script that you run whenever it is time to rebalance your portfolio (e.g. `python live_trader.py`).
- **Phase 1 (Data Fetching):** It scrapes Wikipedia to get the current list of S&P 500 tickers, then downloads the last 300 days of historical price data from Yahoo Finance (`yfinance`).
- **Phase 2 (Signal Generation):** It runs the `calculate_momentum` function. This looks at the price 6 months ago versus the price 1 month ago (skipping the most recent month to avoid short-term mean reversion) and ranks the top 50 stocks.
- **Phase 3 (Execution):** It calculates how many shares to buy of each of those 50 stocks based on your total `portfolio_value`. It then calls the `broker.py` file to actually *send* those orders to Alpaca.
- **Phase 4 (Local Logging):** It saves a log of everything it just did (the trades made, the signals generated) into a local SQLite database so the dashboard can read it later.

### `dashboard.py`
**The User Interface.**
This uses the Streamlit library (`streamlit run dashboard.py`) to give you a visual representation of what the algorithm is doing.
- **What it does:** It provides tabs for Overview, Positions, Performance, and Trades.
- **How it fits in:** It reads the internal logs and history from the local SQLite database (`trading_system.db`) to show past performance. However, for the **"Positions"** tab, we recently upgraded it to talk directly to `broker.py` so it pulls your *live* active holdings straight from Alpaca, comparing them against live Yahoo Finance prices to calculate your real-time Profit & Loss (P&L).

### `momentum_trading_system_complete.py`
**The Offline Simulator (Legacy/Testing).**
- This file contains the exact same momentum logic as `live_trader.py`, but instead of connecting to Alpaca, it just "pretends" to execute trades and logs the pretend results into the database.
- **How it fits in:** You use this when you want to run the system in a purely simulated environment without touching even a paper brokerage account.

---

## ⚙️ 2. Configuration & Data Files

### `.env`
**The Secret Vault.**
- This file stores your `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`.
- Because this file contains sensitive passwords, it is ignored by Git, ensuring you don't accidentally push your keys to a public GitHub repository.

### `live_trading_data/trading_system.db`
**The Local Memory.**
- A local SQLite database file automatically created by the system.
- It stores historical logs of your portfolio value over time, a record of every simulated or real trade the system has attempted, and the historical momentum signals it generated.
- `dashboard.py` heavily relies on this file to draw its charts.

---

## 🔄 3. How It All Connects (The Workflow)

1. **Rebalancing Day (e.g., end of Quarter):**
   You (or a scheduled server task) run `python live_trader.py`.
2. **Analysis:**
   `live_trader.py` downloads prices from Yahoo Finance and calculates the top 50 stocks.
3. **Execution:**
   `live_trader.py` imports `broker.py` and says, *"Broker, buy these 50 stocks for me on Alpaca."*
4. **Recording:**
   `live_trader.py` writes down what it just did in `trading_system.db`.
5. **Monitoring (Every Day):**
   You open your browser to the Streamlit dashboard (`dashboard.py`). The dashboard reads the historical logs from `trading_system.db` to show you past performance, and it asks `broker.py` for your *current* Alpaca holdings to calculate your live P&L today.
