"""
MOMENTUM TRADING SYSTEM DASHBOARD
Real-time monitoring and performance tracking
"""

import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import plotly.graph_objects as go
from datetime import datetime
from pathlib import Path
import yfinance as yf
import time

# Page config
st.set_page_config(
    page_title="Momentum Trading Dashboard", page_icon="📊", layout="wide"
)

# Constants
DB_FILE = Path("live_trading_data/trading_system.db")

# Title
st.title("📊 S&P 500 Momentum Trading System")
st.markdown("**Strategy:** J=6, K=3 | **Rebalance:** Quarterly | **Universe:** S&P 500")

# Sidebar
st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Select Page", ["Overview", "Positions", "Performance", "Trades", "System Health"]
)


# Load data function
@st.cache_data(ttl=60)
def load_data():
    """Load all data from database"""
    if not DB_FILE.exists():
        return None

    conn = sqlite3.connect(DB_FILE)

    data = {
        "positions": pd.read_sql("SELECT * FROM positions", conn),
        "trades": pd.read_sql("SELECT * FROM trades ORDER BY timestamp DESC", conn),
        "portfolio_history": pd.read_sql(
            "SELECT * FROM portfolio_history ORDER BY date", conn
        ),
        "rebalances": pd.read_sql(
            "SELECT * FROM rebalance_log ORDER BY date DESC", conn
        ),
        "signals": pd.read_sql("SELECT * FROM signals ORDER BY date DESC", conn),
    }

    conn.close()
    return data


@st.cache_data(ttl=30)
def fetch_live_prices(tickers):
    """Fetch current market prices (~15-min delayed during market hours)."""
    if not tickers:
        return {}
    try:
        data = yf.download(list(tickers), period='1d', interval='1m',
                           auto_adjust=True, progress=False)
        if data.empty:
            data = yf.download(list(tickers), period='5d', interval='1d',
                               auto_adjust=True, progress=False)
        top_level = data.columns.get_level_values(0) if hasattr(data.columns, 'levels') else data.columns
        prices_df = data['Close'] if 'Close' in top_level else data['Adj Close']
        if isinstance(prices_df, pd.Series):
            prices_df = prices_df.to_frame()
        current = prices_df.ffill().iloc[-1]
        return {k: float(v) for k, v in current.to_dict().items() if pd.notna(v)}
    except Exception as e:
        st.warning(f"Could not fetch live prices: {e}")
        return {}

@st.cache_data(ttl=30)
def fetch_broker_positions():
    """Fetch live positions from Alpaca if configured."""
    try:
        import os
        from dotenv import load_dotenv
        from broker import AlpacaBroker
        load_dotenv()
        if not os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_API_KEY") == "your_api_key_here":
            return None
        broker = AlpacaBroker()
        return broker.get_positions()
    except Exception as e:
        st.warning(f"Could not fetch Alpaca positions: {e}")
        return None

@st.cache_data(ttl=30)
def fetch_broker_account():
    """Fetch live account stats from Alpaca if configured."""
    try:
        import os
        from dotenv import load_dotenv
        from broker import AlpacaBroker
        load_dotenv()
        if not os.environ.get("ALPACA_API_KEY") or os.environ.get("ALPACA_API_KEY") == "your_api_key_here":
            return None
        broker = AlpacaBroker()
        return {
            "portfolio_value": broker.get_portfolio_value(),
            "cash": broker.get_cash()
        }
    except Exception:
        return None

# Load data
data = load_data()

if data is None:
    st.error("❌ Database not found. Run the trading system first.")
    st.stop()

###################
# PAGE: OVERVIEW
###################
if page == "Overview":
    st.header("📈 Portfolio Overview")

    # Get latest portfolio state
    if not data["portfolio_history"].empty:
        latest = data["portfolio_history"].iloc[-1].to_dict()
        
        # Override with live Alpaca data if available
        alpaca_acct = fetch_broker_account()
        alpaca_pos = fetch_broker_positions()
        
        if alpaca_acct is not None:
            latest['total_value'] = alpaca_acct['portfolio_value']
            latest['cash'] = alpaca_acct['cash']
            latest['positions_value'] = latest['total_value'] - latest['cash']
            
        if alpaca_pos is not None:
            latest['num_positions'] = len(alpaca_pos)

        # KPI Metrics
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "Portfolio Value",
                f"${latest['total_value']:,.2f}",
                delta=f"{(latest['total_value']/100000 - 1)*100:.2f}%",
            )

        with col2:
            st.metric(
                "Cash",
                f"${latest['cash']:,.2f}",
                delta=f"{latest['cash']/latest['total_value']*100:.1f}%",
            )

        with col3:
            st.metric("Positions Value", f"${latest['positions_value']:,.2f}")

        with col4:
            st.metric("Number of Stocks", int(latest["num_positions"]))

        # Portfolio composition pie chart
        st.subheader("💼 Portfolio Composition")

        fig = go.Figure(
            data=[
                go.Pie(
                    labels=["Positions", "Cash"],
                    values=[latest["positions_value"], latest["cash"]],
                    hole=0.3,
                )
            ]
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    # Recent activity
    st.subheader("🔄 Recent Rebalances")
    if not data["rebalances"].empty:
        st.dataframe(
            data["rebalances"].head(5), use_container_width=True, hide_index=True
        )
    else:
        st.info("No rebalances yet")

###################
# PAGE: POSITIONS
###################
elif page == "Positions":
    st.header("📊 Current Positions")

    db_positions = data["positions"].copy() if not data["positions"].empty else pd.DataFrame()

    alpaca_dict = fetch_broker_positions()
    if alpaca_dict is not None and len(alpaca_dict) > 0:
        st.success("✅ Synced with Live Alpaca Positions")
        alpaca_df = pd.DataFrame.from_dict(alpaca_dict, orient='index').reset_index()
        alpaca_df.rename(columns={'index': 'ticker', 'qty': 'shares', 'avg_entry_price': 'entry_price'}, inplace=True)
        if not db_positions.empty:
            positions = pd.merge(alpaca_df, db_positions[['ticker', 'entry_date']], on='ticker', how='left')
        else:
            positions = alpaca_df.copy()
            positions['entry_date'] = 'Sync'
        positions['entry_date'] = positions['entry_date'].fillna('Sync')
        positions['current_value'] = alpaca_df['market_value']
    else:
        if not db_positions.empty:
            st.info("ℹ️ Showing Database Positions")
            positions = db_positions
        else:
            positions = pd.DataFrame()

    if not positions.empty:
        # Fetch live market prices
        tickers = tuple(positions["ticker"].tolist())
        live_prices = fetch_live_prices(tickers)
        last_price_update = datetime.now().strftime('%H:%M:%S')

        # Use live price; fall back to stored price if live fetch failed
        positions["current_price"] = positions["ticker"].map(live_prices)
        missing = positions["current_price"].isna()
        
        has_fallback = positions["current_value"].notna() & (positions["shares"] > 0)
        positions.loc[missing & has_fallback, "current_price"] = (
            positions.loc[missing & has_fallback, "current_value"] / positions.loc[missing & has_fallback, "shares"]
        )

        # Recalculate values with live prices
        positions["current_value"] = positions["shares"] * positions["current_price"]
        positions["total_cost"] = positions["shares"] * positions["entry_price"]
        positions["pnl"] = positions["current_value"] - positions["total_cost"]
        positions["pnl_pct"] = (positions["pnl"] / positions["total_cost"]) * 100

        live_count = (~missing).sum()
        st.caption(f"Live prices: {live_count}/{len(positions)} tickers | Last updated: {last_price_update}")

        # Summary stats
        col1, col2, col3 = st.columns(3)

        with col1:
            total_pnl = positions["pnl"].sum()
            st.metric("Total P&L", f"${total_pnl:,.2f}")

        with col2:
            winners = (positions["pnl"] > 0).sum()
            st.metric("Winners", f"{winners}/{len(positions)}")

        with col3:
            avg_pnl = positions["pnl_pct"].mean()
            st.metric("Avg P&L %", f"{avg_pnl:.2f}%")

        # Position table
        st.subheader("Holdings")

        display_df = positions[
            [
                "ticker",
                "shares",
                "entry_price",
                "current_price",
                "current_value",
                "pnl",
                "pnl_pct",
                "entry_date",
            ]
        ].copy()

        # Format columns
        display_df["entry_price"] = display_df["entry_price"].apply(
            lambda x: f"${x:.2f}"
        )
        display_df["current_price"] = display_df["current_price"].apply(
            lambda x: f"${x:.2f}"
        )
        display_df["current_value"] = display_df["current_value"].apply(
            lambda x: f"${x:,.2f}"
        )
        display_df["pnl"] = display_df["pnl"].apply(lambda x: f"${x:,.2f}")
        display_df["pnl_pct"] = display_df["pnl_pct"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # Top/Bottom performers
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🚀 Top 5 Performers")
            top5 = positions.nlargest(5, "pnl_pct")[["ticker", "pnl_pct"]]
            for _, row in top5.iterrows():
                st.success(f"{row['ticker']}: +{row['pnl_pct']:.2f}%")

        with col2:
            st.subheader("📉 Bottom 5 Performers")
            bottom5 = positions.nsmallest(5, "pnl_pct")[["ticker", "pnl_pct"]]
            for _, row in bottom5.iterrows():
                st.error(f"{row['ticker']}: {row['pnl_pct']:.2f}%")

    else:
        st.info("No positions currently")

###################
# PAGE: PERFORMANCE
###################
elif page == "Performance":
    st.header("📈 Performance Analysis")

    if not data["portfolio_history"].empty:
        history = data["portfolio_history"].copy()
        history["date"] = pd.to_datetime(history["date"])

        # Calculate returns
        history["return"] = history["total_value"].pct_change()
        history["cumulative_return"] = (
            history["total_value"] / history["total_value"].iloc[0] - 1
        ) * 100

        # Portfolio value over time
        st.subheader("Portfolio Value Over Time")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=history["date"],
                y=history["total_value"],
                mode="lines",
                name="Portfolio Value",
                line=dict(color="#2E86AB", width=3),
            )
        )

        fig.update_layout(
            height=500,
            xaxis_title="Date",
            yaxis_title="Portfolio Value ($)",
            hovermode="x unified",
        )

        st.plotly_chart(fig, use_container_width=True)

        # Performance metrics
        st.subheader("Performance Metrics")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            total_return = history["cumulative_return"].iloc[-1]
            st.metric("Total Return", f"{total_return:.2f}%")

        with col2:
            if len(history) > 1:
                days = (history["date"].iloc[-1] - history["date"].iloc[0]).days
                years = days / 365.25
                ann_return = (
                    history["total_value"].iloc[-1] / history["total_value"].iloc[0]
                ) ** (1 / years) - 1
                st.metric("Annualized Return", f"{ann_return*100:.2f}%")

        with col3:
            volatility = history["return"].std() * np.sqrt(252) * 100
            st.metric("Volatility (Ann.)", f"{volatility:.2f}%")

        with col4:
            max_val = history["total_value"].cummax()
            drawdown = (history["total_value"] - max_val) / max_val * 100
            max_dd = drawdown.min()
            st.metric("Max Drawdown", f"{max_dd:.2f}%")

        # Drawdown chart
        st.subheader("Drawdown Analysis")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=history["date"],
                y=drawdown,
                mode="lines",
                fill="tozeroy",
                name="Drawdown",
                line=dict(color="red"),
            )
        )

        fig.update_layout(
            height=300,
            xaxis_title="Date",
            yaxis_title="Drawdown (%)",
            hovermode="x unified",
        )

        st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("No performance history yet")

###################
# PAGE: TRADES
###################
elif page == "Trades":
    st.header("💰 Trade History")

    if not data["trades"].empty:
        trades = data["trades"].copy()

        # Summary stats
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Total Trades", len(trades))

        with col2:
            buys = (trades["action"] == "BUY").sum()
            st.metric("Buy Orders", buys)

        with col3:
            sells = (trades["action"] == "SELL").sum()
            st.metric("Sell Orders", sells)

        with col4:
            total_value = trades["value"].sum()
            st.metric("Total Volume", f"${total_value:,.2f}")

        # Trade table
        st.subheader("Recent Trades")

        display_trades = (
            trades[
                ["timestamp", "ticker", "action", "shares", "price", "value", "status"]
            ]
            .head(50)
            .copy()
        )

        # Format
        display_trades["price"] = display_trades["price"].apply(lambda x: f"${x:.2f}")
        display_trades["value"] = display_trades["value"].apply(lambda x: f"${x:,.2f}")

        st.dataframe(display_trades, use_container_width=True, hide_index=True)

    else:
        st.info("No trades yet")

###################
# PAGE: SYSTEM HEALTH
###################
elif page == "System Health":
    st.header("🏥 System Health")

    # Database status
    st.subheader("Database Status")
    col1, col2 = st.columns(2)

    with col1:
        st.metric("Database", "✅ Connected" if DB_FILE.exists() else "❌ Not Found")

    with col2:
        db_size = DB_FILE.stat().st_size / 1024 / 1024 if DB_FILE.exists() else 0
        st.metric("Database Size", f"{db_size:.2f} MB")

    # Table record counts
    st.subheader("Data Records")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Positions", len(data["positions"]))

    with col2:
        st.metric("Trades", len(data["trades"]))

    with col3:
        st.metric("Rebalances", len(data["rebalances"]))

    # Latest signals
    st.subheader("Latest Momentum Signals")

    if not data["signals"].empty:
        latest_date = data["signals"]["date"].max()
        latest_signals = data["signals"][data["signals"]["date"] == latest_date]

        top_signals = latest_signals.nlargest(10, "momentum_score")[
            ["ticker", "momentum_score", "rank", "selected"]
        ]

        st.dataframe(top_signals, use_container_width=True, hide_index=True)

    # System info
    st.subheader("System Information")
    st.info(
        f"""
    **Strategy:** S&P 500 Momentum (J=6, K=3)  
    **Universe:** S&P 500 (503 stocks)  
    **Rebalance:** Quarterly (Mar, Jun, Sep, Dec)  
    **Position Size:** Equal weight ({50} stocks)  
    **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
    )

# Footer
st.sidebar.markdown("---")
st.sidebar.info(
    """
**Momentum Trading System**  
Built by Xiangru Mo  
Strategy: J=6, K=3  
Rebalance: Quarterly
"""
)

# Refresh controls
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()

refresh_options = {"Off": 0, "30 sec": 30, "1 min": 60, "5 min": 300}
refresh_label = st.sidebar.selectbox("Auto-refresh", list(refresh_options.keys()), index=1)
refresh_secs = refresh_options[refresh_label]

st.sidebar.caption("Prices refresh every 30s from market data")

if refresh_secs > 0:
    time.sleep(refresh_secs)
    st.rerun()
