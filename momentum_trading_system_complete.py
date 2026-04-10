#!/usr/bin/env python3
"""
MOMENTUM TRADING SYSTEM - COMPLETE ALL-IN-ONE FILE
S&P/TSX Composite Momentum Strategy (J=6, K=3)
Author: Mo Xiang

Universe: S&P/TSX Composite Index (Wikipedia), ~220 Canadian stocks (.TO suffix)
Note: To execute live trades you need a broker that supports TSX-listed equities
      (e.g. Interactive Brokers, Questrade). Alpaca only supports US stocks.

Just run: python momentum_trading_system_complete.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import requests
from io import StringIO
from datetime import datetime, timedelta
import sqlite3
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """All configuration in one place"""

    # Strategy Parameters
    LOOKBACK_MONTHS = 6
    HOLDING_MONTHS  = 3
    SKIP_DAYS       = 21

    # Portfolio split: 50% auto-traded S&P 500, 50% manual TSX
    N_SP500    = 10   # auto-traded via IBKR
    N_TSX      = 10   # printed for manual execution
    N_POSITIONS = N_SP500  # only S&P 500 positions count for IBKR auto-trading

    # Derived
    LOOKBACK_DAYS = LOOKBACK_MONTHS * 21
    HOLDING_DAYS  = HOLDING_MONTHS  * 21

    # Portfolio (S&P 500 half = 50% of capital, since TSX half is managed manually)
    INITIAL_CAPITAL  = 100000
    SP500_ALLOCATION = 0.50   # fraction of portfolio auto-allocated to S&P 500
    CASH_BUFFER      = 0.02   # 2% cash buffer within the S&P 500 allocation
    
    # Database
    DATA_DIR = Path('live_trading_data')
    DB_FILE = DATA_DIR / 'trading_system.db'
    
    def __init__(self):
        self.DATA_DIR.mkdir(exist_ok=True)


# ============================================================================
# DATABASE
# ============================================================================

def init_database(db_file):
    """Initialize SQLite database"""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    # Positions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            ticker TEXT PRIMARY KEY,
            shares INTEGER,
            entry_price REAL,
            entry_date TEXT,
            current_value REAL,
            last_updated TEXT
        )
    ''')
    
    # Trades
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ticker TEXT,
            action TEXT,
            shares INTEGER,
            price REAL,
            value REAL,
            status TEXT
        )
    ''')
    
    # Portfolio History
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_history (
            date TEXT PRIMARY KEY,
            total_value REAL,
            cash REAL,
            positions_value REAL,
            num_positions INTEGER
        )
    ''')
    
    # Rebalance Log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rebalance_log (
            date TEXT PRIMARY KEY,
            num_buys INTEGER,
            num_sells INTEGER,
            portfolio_value_before REAL,
            portfolio_value_after REAL,
            notes TEXT
        )
    ''')
    
    # Signals
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            date TEXT,
            ticker TEXT,
            momentum_score REAL,
            rank INTEGER,
            selected BOOLEAN,
            PRIMARY KEY (date, ticker)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✓ Database initialized: {db_file}")


def initialize_portfolio(db_file, initial_capital):
    """Initialize portfolio with starting cash"""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM portfolio_history")
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute('''
            INSERT INTO portfolio_history 
            (date, total_value, cash, positions_value, num_positions)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime('%Y-%m-%d'),
            initial_capital,
            initial_capital,
            0,
            0
        ))
        conn.commit()
        print(f"✓ Portfolio initialized with ${initial_capital:,.2f}")
    else:
        print(f"✓ Portfolio already initialized")
    
    conn.close()


# ============================================================================
# DATA PIPELINE
# ============================================================================

def get_sp500_tickers():
    """Get S&P 500 tickers from Wikipedia."""
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    table = pd.read_html(StringIO(response.text))[0]
    tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
    print(f"✓ Retrieved {len(tickers)} S&P 500 tickers from Wikipedia")
    return tickers


def get_tsx_tickers():
    """
    Get S&P/TSX Composite tickers from Wikipedia.
    Returns tickers with .TO suffix for Yahoo Finance (e.g. RY.TO, TD.TO).
    """
    url = 'https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index'
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    tables = pd.read_html(StringIO(response.text))

    for table in tables:
        # Convert all column names to str to avoid AttributeError on integer headers
        str_cols = {c: str(c).lower() for c in table.columns}
        if any(v in ['symbol', 'ticker', 'stock symbol'] for v in str_cols.values()):
            col = next(c for c, v in str_cols.items()
                       if v in ['symbol', 'ticker', 'stock symbol'])
            tickers = table[col].dropna().tolist()
            tickers = [
                str(t).strip() + '.TO'
                if not str(t).strip().endswith('.TO') else str(t).strip()
                for t in tickers
            ]
            print(f"✓ Retrieved {len(tickers)} S&P/TSX Composite tickers from Wikipedia")
            return tickers

    raise RuntimeError("Could not find ticker column in Wikipedia TSX table.")


def fetch_prices(tickers, days_back=300):
    """Fetch price data"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    print(f"Fetching prices for {len(tickers)} tickers...")
    
    data = yf.download(tickers, start=start_date, end=end_date,
                      auto_adjust=True, progress=False)

    # With auto_adjust=True, adjusted prices are in 'Close'; fallback to 'Adj Close' for older yfinance
    top_level = data.columns.get_level_values(0) if hasattr(data.columns, 'levels') else data.columns
    if 'Close' in top_level:
        adj_close = data['Close']
    elif 'Adj Close' in top_level:
        adj_close = data['Adj Close']
    else:
        raise ValueError(f"Could not find price column. Available columns: {data.columns.tolist()}")
    
    if isinstance(adj_close, pd.Series):
        adj_close = adj_close.to_frame()

    # Drop trailing rows that are entirely NaN (e.g. today's date before market close)
    adj_close = adj_close.loc[adj_close.notna().any(axis=1)]

    print(f"✓ Fetched {adj_close.shape[0]} days, {adj_close.shape[1]} stocks")
    return adj_close


def fetch_current_prices(tickers):
    """Fetch current/intraday prices for order execution.

    Separate from fetch_prices() which is for historical momentum calculation.
    Uses 1-minute intraday data during market hours, falls back to daily close
    outside market hours / on weekends.
    """
    print(f"Fetching current prices for {len(tickers)} tickers...")

    # Try intraday first (~15-min delayed during market hours)
    data = yf.download(tickers, period='1d', interval='1m', auto_adjust=True, progress=False)

    if data.empty:
        # Market closed or weekend — use most recent daily close
        print("  Intraday data unavailable, falling back to recent daily close...")
        data = yf.download(tickers, period='5d', interval='1d', auto_adjust=True, progress=False)

    top_level = data.columns.get_level_values(0) if hasattr(data.columns, 'levels') else data.columns
    prices_df = data['Close'] if 'Close' in top_level else data['Adj Close']

    if isinstance(prices_df, pd.Series):
        prices_df = prices_df.to_frame()

    current = prices_df.ffill().iloc[-1]
    result = {k: v for k, v in current.to_dict().items() if pd.notna(v)}
    print(f"✓ Got current prices for {len(result)} tickers")
    return result


# ============================================================================
# SIGNAL GENERATION
# ============================================================================

def calculate_momentum(adj_close, lookback_days=126, skip_days=21):
    """Calculate momentum scores"""
    latest_date = adj_close.index[-1]
    
    if len(adj_close) < lookback_days:
        print(f"⚠ Warning: Only {len(adj_close)} days available")
        return pd.DataFrame()
    
    prices_lookback = adj_close.iloc[-lookback_days]
    prices_skip = adj_close.iloc[-skip_days]
    
    momentum_scores = (prices_skip / prices_lookback) - 1
    momentum_scores = momentum_scores.dropna()
    
    df = pd.DataFrame({
        'ticker': momentum_scores.index,
        'momentum_score': momentum_scores.values
    })
    
    df = df.sort_values('momentum_score', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    df['date'] = latest_date.strftime('%Y-%m-%d')
    
    print(f"\n✓ Calculated momentum for {len(df)} stocks")
    print(f"  Top 5: {df.head(5)['ticker'].tolist()}")
    print(f"  Top score: {df.iloc[0]['momentum_score']*100:.2f}%")
    
    return df


def select_portfolio(momentum_df, n_positions=50):
    """Select top N stocks"""
    selected = momentum_df.head(n_positions).copy()
    selected['selected'] = True
    
    print(f"✓ Selected {len(selected)} stocks for portfolio")
    return selected['ticker'].tolist()


# ============================================================================
# ORDER EXECUTION
# ============================================================================

def execute_rebalance(target_tickers, adj_close, db_file, portfolio_value, 
                     n_positions=50, cash_buffer=0.02):
    """
    Execute rebalance with PROPER share calculation
    
    Key fix: Get current prices CORRECTLY from adj_close
    """
    print("\n" + "="*80)
    print("EXECUTING REBALANCE")
    print("="*80)
    
    # Get current prices — fetched fresh as intraday data, separate from historical momentum data
    current_prices = fetch_current_prices(target_tickers)
    
    print(f"\nPortfolio Value: ${portfolio_value:,.2f}")
    print(f"Valid prices available: {len(current_prices)}")
    
    # Calculate target position size
    investable = portfolio_value * (1 - cash_buffer)
    target_value = investable / n_positions
    
    print(f"Target per position: ${target_value:,.2f}\n")
    
    # Execute orders
    executed = 0
    failed = 0
    
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    
    print(f"Executing {len(target_tickers)} BUY orders...")
    
    for i, ticker in enumerate(target_tickers):
        try:
            # Get price
            price = current_prices.get(ticker)
            
            if price is None or pd.isna(price):
                print(f"  ⚠️  Skipping {ticker}: No price available")
                failed += 1
                continue
            
            # Calculate shares
            shares = int(target_value / price)
            
            if shares == 0:
                print(f"  ⚠️  Skipping {ticker}: 0 shares (price ${price:.2f})")
                failed += 1
                continue
            
            # Execute order (simulated)
            actual_cost = shares * price
            
            # Save to database
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (ticker, shares, entry_price, entry_date, current_value, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                ticker,
                shares,
                price,
                datetime.now().strftime('%Y-%m-%d'),
                actual_cost,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            
            # Log trade
            cursor.execute('''
                INSERT INTO trades 
                (timestamp, ticker, action, shares, price, value, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                ticker,
                'BUY',
                shares,
                price,
                actual_cost,
                'filled'
            ))
            
            executed += 1
            
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i+1}/{len(target_tickers)} ({executed} successful)")
                
        except Exception as e:
            print(f"  ❌ Error buying {ticker}: {e}")
            failed += 1
    
    # Log rebalance
    cursor.execute('''
        INSERT OR REPLACE INTO rebalance_log 
        (date, num_buys, num_sells, portfolio_value_before, portfolio_value_after, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime('%Y-%m-%d'),
        executed,
        0,
        portfolio_value,
        portfolio_value,
        f"Executed {executed} buys, {failed} failed"
    ))
    
    conn.commit()
    conn.close()
    
    print(f"\n✓ Executed {executed} buys")
    if failed > 0:
        print(f"❌ Failed: {failed}")
    
    print("="*80)
    
    return {
        'executed': executed,
        'failed': failed
    }


# ============================================================================
# MAIN SYSTEM
# ============================================================================

def run_rebalance(config):
    """Run complete rebalance"""
    
    print("\n" + "="*80)
    print("MOMENTUM TRADING SYSTEM - REBALANCE")
    print("="*80)
    
    # 1. Fetch data
    print("\n1. Fetching S&P/TSX Composite data...")
    tickers = get_tsx_tickers()
    adj_close = fetch_prices(tickers, days_back=300)
    
    # 2. Calculate signals
    print("\n2. Calculating momentum signals...")
    momentum_df = calculate_momentum(adj_close, config.LOOKBACK_DAYS, config.SKIP_DAYS)
    target_tickers = select_portfolio(momentum_df, config.N_POSITIONS)
    
    # 3. Execute rebalance
    print("\n3. Executing rebalance...")
    result = execute_rebalance(
        target_tickers,
        adj_close,
        config.DB_FILE,
        config.INITIAL_CAPITAL,
        config.N_POSITIONS,
        config.CASH_BUFFER
    )
    
    return result


def main():
    """Main entry point"""
    
    print("="*80)
    print("S&P/TSX COMPOSITE MOMENTUM TRADING SYSTEM")
    print("="*80)
    print("Strategy: J=6, K=3 | Quarterly Rebalancing | Universe: TSX Wikipedia")
    print("="*80 + "\n")
    
    # Initialize
    config = Config()
    
    print("Initializing system...")
    init_database(config.DB_FILE)
    initialize_portfolio(config.DB_FILE, config.INITIAL_CAPITAL)
    
    # Run rebalance
    result = run_rebalance(config)
    
    # Summary
    print("\n" + "="*80)
    print("SETUP COMPLETE!")
    print("="*80)
    print(f"\n✓ Positions created: {result['executed']}")
    if result['failed'] > 0:
        print(f"⚠️  Failed orders: {result['failed']}")
    
    print(f"\nDatabase: {config.DB_FILE}")
    print("\nNext steps:")
    print("  1. View dashboard: streamlit run dashboard.py")
    print("  2. Check database for positions and trades")
    print("="*80)


if __name__ == "__main__":
    main()
