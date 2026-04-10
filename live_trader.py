"""
LIVE TRADING - Real IBKR order execution.

Reuses signal generation from momentum_trading_system_complete.py.
Executes orders against TWS or IB Gateway via ib_insync.
Writes all trades and positions back to the SQLite DB so the dashboard works.

Prerequisites:
    TWS or IB Gateway must be running and logged in before executing this script.
    See broker.py for connection setup instructions.

Run manually:
    python live_trader.py             # paper trading (default, TWS port 7497)
    python live_trader.py --live      # real money (TWS port 7496)
"""

import os
import sqlite3
import time
import argparse
from datetime import datetime
from dotenv import load_dotenv

from momentum_trading_system_complete import (
    Config,
    get_tsx_tickers,
    get_sp500_tickers,
    fetch_prices,
    calculate_momentum,
    select_portfolio,
    init_database,
)
from broker import IBKRBroker


# ============================================================================
# DATABASE HELPERS
# ============================================================================

def _log_trade(db_file, ticker, action, shares, price, status="filled"):
    conn = sqlite3.connect(db_file)
    conn.execute(
        """INSERT INTO trades (timestamp, ticker, action, shares, price, value, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ticker, action,
            shares, price,
            shares * price,
            status,
        ),
    )
    conn.commit()
    conn.close()


def _log_rebalance(db_file, num_buys, num_sells, value_before, value_after, notes):
    conn = sqlite3.connect(db_file)
    conn.execute(
        """INSERT OR REPLACE INTO rebalance_log
           (date, num_buys, num_sells, portfolio_value_before, portfolio_value_after, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            num_buys, num_sells,
            value_before, value_after,
            notes,
        ),
    )
    conn.commit()
    conn.close()


def _sync_positions_to_db(db_file, broker_positions: dict):
    """Replace positions table with current IBKR state."""
    conn = sqlite3.connect(db_file)
    conn.execute("DELETE FROM positions")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    for ticker, p in broker_positions.items():
        conn.execute(
            """INSERT INTO positions
               (ticker, shares, entry_price, entry_date, current_value, last_updated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                ticker,
                p["qty"],
                p["avg_entry_price"],
                today,
                p["market_value"],
                now,
            ),
        )
    conn.commit()
    conn.close()


def _update_portfolio_history(db_file, broker: IBKRBroker):
    portfolio_value = broker.get_portfolio_value()
    positions = broker.get_positions()
    positions_value = sum(p["market_value"] for p in positions.values())
    cash = portfolio_value - positions_value
    conn = sqlite3.connect(db_file)
    conn.execute(
        """INSERT OR REPLACE INTO portfolio_history
           (date, total_value, cash, positions_value, num_positions)
           VALUES (?, ?, ?, ?, ?)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            portfolio_value,
            cash,
            positions_value,
            len(positions),
        ),
    )
    conn.commit()
    conn.close()


# ============================================================================
# MAIN REBALANCE
# ============================================================================

def run_live_rebalance(paper: bool = True) -> dict:
    """
    Run a full quarterly rebalance against a real (or paper) IBKR account.

    Steps:
      1. Fetch current portfolio value from IBKR
      2. Compute momentum signals for S&P/TSX Composite
      3. Sell positions that are no longer in the top-N
      4. Buy new positions that entered the top-N
      5. Sync positions and portfolio history to SQLite (dashboard reads from here)

    Args:
        paper: True = paper account, False = live account (real money)

    Returns:
        dict with keys 'sold', 'bought', 'failed'
    """
    load_dotenv()
    config = Config()
    init_database(config.DB_FILE)

    broker = IBKRBroker(paper=paper)

    # ------------------------------------------------------------------
    # 1. Account state
    # ------------------------------------------------------------------
    print("\n1. Getting account value from IBKR...")
    portfolio_value_cad = broker.get_portfolio_value()
    portfolio_value_usd = broker.get_portfolio_value_usd()
    print(f"   Portfolio value: ${portfolio_value_cad:,.2f} CAD  /  ${portfolio_value_usd:,.2f} USD")

    if not broker.is_market_open():
        print("\n⚠  Market is currently closed. Re-run between 09:30–16:00 ET on a weekday.")
        broker.disconnect()
        return {"sold": 0, "bought": 0, "failed": 0}

    # ------------------------------------------------------------------
    # 2. Momentum signals — both universes
    # ------------------------------------------------------------------
    print("\n2. Computing momentum signals...")

    print("   → S&P 500 universe")
    sp500_tickers  = get_sp500_tickers()
    sp500_prices   = fetch_prices(sp500_tickers, days_back=300)
    sp500_momentum = calculate_momentum(sp500_prices, config.LOOKBACK_DAYS, config.SKIP_DAYS)
    sp500_target   = set(select_portfolio(sp500_momentum, config.N_SP500))

    print("   → S&P/TSX Composite universe")
    tsx_tickers    = get_tsx_tickers()
    tsx_prices     = fetch_prices(tsx_tickers, days_back=300)
    tsx_momentum   = calculate_momentum(tsx_prices, config.LOOKBACK_DAYS, config.SKIP_DAYS)
    tsx_target     = select_portfolio(tsx_momentum, config.N_TSX)

    # ------------------------------------------------------------------
    # 3. Get current positions (needed for both TSX diff and S&P 500 diff)
    # ------------------------------------------------------------------
    print("\n3. Getting current positions from IBKR...")
    all_positions    = broker.get_positions()
    current_tsx      = {k: v for k, v in all_positions.items() if k.endswith('.TO')}
    current_sp500    = {k: v for k, v in all_positions.items() if not k.endswith('.TO')}
    print(f"   TSX positions: {len(current_tsx)}  |  S&P 500 positions: {len(current_sp500)}")

    # ------------------------------------------------------------------
    # TSX manual instructions — what to sell, hold, and buy
    # ------------------------------------------------------------------
    tsx_target_set = set(tsx_target)
    tsx_to_sell    = set(current_tsx.keys()) - tsx_target_set
    tsx_to_hold    = set(current_tsx.keys()) & tsx_target_set
    tsx_to_buy     = tsx_target_set - set(current_tsx.keys())

    tsx_allocation    = portfolio_value_cad * (1 - config.SP500_ALLOCATION) * (1 - config.CASH_BUFFER)
    tsx_per_position  = tsx_allocation / config.N_TSX

    print("\n" + "=" * 70)
    print("  TSX MANUAL TRADING INSTRUCTIONS")
    print(f"  TSX allocation: ${tsx_allocation:,.2f} CAD  |  Per position: ${tsx_per_position:,.2f} CAD")
    print("=" * 70)

    if tsx_to_sell:
        print(f"\n  SELL — {len(tsx_to_sell)} position(s) dropped out of top {config.N_TSX}:")
        for t in sorted(tsx_to_sell):
            p = current_tsx[t]
            print(f"    SELL  {t:<14}  {int(p['qty']):>5} shares  (avg cost ${p['avg_entry_price']:,.2f})")
    else:
        print("\n  SELL — nothing to sell")

    if tsx_to_hold:
        print(f"\n  HOLD — {len(tsx_to_hold)} position(s) remain in top {config.N_TSX}:")
        for t in sorted(tsx_to_hold):
            rank = tsx_target.index(t) + 1
            row  = tsx_momentum[tsx_momentum['ticker'] == t].iloc[0]
            print(f"    HOLD  {t:<14}  rank #{rank:<2}  momentum {row['momentum_score']*100:+.1f}%")

    if tsx_to_buy:
        print(f"\n  BUY — {len(tsx_to_buy)} new position(s) entered top {config.N_TSX}:")
        for t in sorted(tsx_to_buy):
            rank = tsx_target.index(t) + 1
            row  = tsx_momentum[tsx_momentum['ticker'] == t].iloc[0]
            if t in tsx_prices.columns:
                price  = float(tsx_prices[t].dropna().iloc[-1])
                shares = int(tsx_per_position / price)
                cost   = shares * price
                print(f"    BUY   {t:<14}  {shares:>5} shares  @ ~${price:>8.2f}  = ${cost:>9,.2f} CAD"
                      f"  (rank #{rank}, mom {row['momentum_score']*100:+.1f}%)")
            else:
                print(f"    BUY   {t:<14}  rank #{rank}  momentum {row['momentum_score']*100:+.1f}%"
                      f"  (no price — look up manually)")
    else:
        print(f"\n  BUY — nothing new to buy")

    print("\n  ↑ Log in to TWS or the IBKR mobile app and place these orders.")
    print("=" * 70 + "\n")

    # ------------------------------------------------------------------
    # 4. S&P 500 — pre-execution plan
    # ------------------------------------------------------------------
    sp500_allocation    = portfolio_value_usd * config.SP500_ALLOCATION * (1 - config.CASH_BUFFER)
    target_per_position = sp500_allocation / config.N_SP500

    current_tickers = set(current_sp500.keys())
    sp500_to_hold   = current_tickers & sp500_target
    to_sell         = current_tickers - sp500_target
    to_buy          = sp500_target    - current_tickers

    print("\n" + "=" * 70)
    print("  S&P 500 AUTO-REBALANCE PLAN  (orders will be placed automatically)")
    print(f"  S&P 500 allocation (50%): ${sp500_allocation:,.2f} USD  |  Per position: ${target_per_position:,.2f} USD")
    print("=" * 70)

    if to_sell:
        print(f"\n  SELL — {len(to_sell)} position(s) dropped out of top {config.N_SP500}:")
        for t in sorted(to_sell):
            p = current_sp500[t]
            est_price = float(sp500_prices[t].dropna().iloc[-1]) if t in sp500_prices.columns else p["avg_entry_price"]
            proceeds  = int(p["qty"]) * est_price
            print(f"    SELL  {t:<10}  {int(p['qty']):>5} shares  @ ~${est_price:>8.2f}  ≈ ${proceeds:>9,.2f} USD")
    else:
        print("\n  SELL — nothing to sell")

    if sp500_to_hold:
        print(f"\n  HOLD — {len(sp500_to_hold)} position(s) remain in top {config.N_SP500}:")
        for t in sorted(sp500_to_hold):
            row = sp500_momentum[sp500_momentum['ticker'] == t].iloc[0]
            print(f"    HOLD  {t:<10}  rank #{int(row['rank']):<2}  momentum {row['momentum_score']*100:+.1f}%")

    if to_buy:
        print(f"\n  BUY — {len(to_buy)} new position(s) entered top {config.N_SP500}:")
        for t in sorted(to_buy):
            row = sp500_momentum[sp500_momentum['ticker'] == t].iloc[0]
            if t in sp500_prices.columns:
                price  = float(sp500_prices[t].dropna().iloc[-1])
                shares = int(target_per_position / price)
                cost   = shares * price
                print(f"    BUY   {t:<10}  {shares:>5} shares  @ ~${price:>8.2f}  = ${cost:>9,.2f} USD"
                      f"  (rank #{int(row['rank'])}, mom {row['momentum_score']*100:+.1f}%)")
            else:
                print(f"    BUY   {t:<10}  rank #{int(row['rank'])}  momentum {row['momentum_score']*100:+.1f}%"
                      f"  (no price data)")
    else:
        print("\n  BUY — nothing new to buy")

    print("\n  Placing orders now...")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 5. Sell exited S&P 500 positions
    # ------------------------------------------------------------------
    for ticker in sorted(to_sell):
        try:
            p = current_sp500[ticker]
            broker.close_position(ticker)
            _log_trade(config.DB_FILE, ticker, "SELL",
                       int(p["qty"]), p["avg_entry_price"])
        except Exception as e:
            print(f"  ❌ Failed to sell {ticker}: {e}")

    if to_sell:
        time.sleep(3)

    # ------------------------------------------------------------------
    # 6. Buy new S&P 500 positions
    # ------------------------------------------------------------------
    bought, failed = 0, 0
    for ticker in sorted(to_buy):
        try:
            if ticker not in sp500_prices.columns:
                print(f"  ⚠  No price data for {ticker}, skipping")
                failed += 1
                continue
            price  = float(sp500_prices[ticker].dropna().iloc[-1])
            shares = int(target_per_position / price)
            if shares <= 0:
                print(f"  ⚠  {ticker}: 0 shares at ${price:.2f}, skipping")
                failed += 1
                continue
            broker.place_market_buy(ticker, shares)
            _log_trade(config.DB_FILE, ticker, "BUY", shares, price)
            bought += 1
        except Exception as e:
            print(f"  ❌ Failed to buy {ticker}: {e}")
            failed += 1

    # ------------------------------------------------------------------
    # 7. Sync S&P 500 state to DB (dashboard reads from here)
    # ------------------------------------------------------------------
    print("\n7. Syncing state to database...")
    final_all       = broker.get_positions()
    final_sp500     = {k: v for k, v in final_all.items() if not k.endswith('.TO')}
    _sync_positions_to_db(config.DB_FILE, final_sp500)
    _update_portfolio_history(config.DB_FILE, broker)

    final_value = broker.get_portfolio_value()
    _log_rebalance(
        config.DB_FILE,
        bought, len(to_sell),
        portfolio_value_cad, final_value,
        f"S&P500: sold {len(to_sell)}, bought {bought}, failed {failed} | "
        f"TSX manual: {tsx_target}",
    )

    print(f"\n✓ Rebalance complete")
    print(f"  S&P 500 (auto): sold {len(to_sell)}, bought {bought}, failed {failed}")
    print(f"  TSX (manual):   {len(tsx_target)} picks printed above — place orders yourself")
    broker.disconnect()
    return {"sold": len(to_sell), "bought": bought, "failed": failed}


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run quarterly momentum rebalance")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use live account with real money (default: paper trading)",
    )
    args = parser.parse_args()

    if args.live:
        confirm = input(
            "\n⚠  WARNING: This will trade with REAL MONEY on your live IBKR account.\n"
            "   Type 'yes' to confirm: "
        )
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            exit(0)

    run_live_rebalance(paper=not args.live)
