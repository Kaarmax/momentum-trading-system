"""
IBKR broker integration for live/paper order execution via ib_insync.

Prerequisites:
  1. Install: pip install ib_insync
  2. Run TWS or IB Gateway and log in
  3. Enable API in TWS: File > Global Configuration > API > Settings
       ☑ Enable ActiveX and Socket Clients
       ☑ Allow connections from localhost only
       Socket port: 7497 (TWS paper) | 7496 (TWS live)
                    4002 (Gateway paper) | 4001 (Gateway live)

Connection settings are read from .env (see .env.example).
No API keys needed — authentication is handled by TWS/Gateway login.

Usage:
    from broker import IBKRBroker
    broker = IBKRBroker(paper=True)   # paper=False for real money
    broker.disconnect()               # always disconnect when done
"""

import os
from datetime import datetime, time
from dotenv import load_dotenv

try:
    from ib_insync import IB, Stock, MarketOrder
except ImportError:
    raise ImportError(
        "ib_insync is not installed. Run: pip install ib_insync"
    )

import pytz

_TORONTO = pytz.timezone('America/Toronto')


class IBKRBroker:
    def __init__(self, paper: bool = True):
        load_dotenv()
        self.paper = paper

        # Connection settings from .env, with sensible defaults
        self.host      = os.environ.get('IBKR_HOST', '127.0.0.1')
        self.port      = int(os.environ.get('IBKR_PORT',
                             7497 if paper else 7496))
        self.client_id = int(os.environ.get('IBKR_CLIENT_ID', 1))

        self.ib = IB()
        self.ib.connect(self.host, self.port, clientId=self.client_id)

        mode = "PAPER" if paper else "LIVE"
        print(f"[IBKR] Connected ({mode}) → {self.host}:{self.port}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _contract(self, ticker: str):
        """
        Build a qualified Stock contract for either TSX or US equities.
          'RY.TO'  → Stock('RY',   'SMART', 'CAD'), primaryExch='TSE'  (Canadian)
          'AAPL'   → Stock('AAPL', 'SMART', 'USD')                     (US)
          'BRK-B'  → Stock('BRK B','SMART', 'USD')  (Yahoo '-' → IBKR ' ')
        """
        if ticker.upper().endswith('.TO'):
            symbol   = ticker.upper().replace('.TO', '')
            contract = Stock(symbol, 'SMART', 'CAD')
            contract.primaryExch = 'TSE'
        else:
            symbol   = ticker.upper().replace('-', ' ')   # BRK-B → BRK B
            contract = Stock(symbol, 'SMART', 'USD')
        self.ib.qualifyContracts(contract)
        return contract

    def _account_tag(self, tag: str, currency: str = 'CAD') -> float:
        """Pull a single numeric tag from accountSummary."""
        for v in self.ib.accountSummary():
            if v.tag == tag and v.currency == currency:
                return float(v.value)
        return 0.0

    # ── Account info ─────────────────────────────────────────────────────────

    def get_portfolio_value(self) -> float:
        """Total account net liquidation value in CAD."""
        return self._account_tag('NetLiquidation', currency='CAD')

    def get_portfolio_value_usd(self) -> float:
        """Total account net liquidation value in USD.

        IBKR multi-currency accounts report NetLiquidation in both currencies.
        Falls back to converting CAD using USD_CAD_RATE from .env if needed.
        """
        usd = self._account_tag('NetLiquidation', currency='USD')
        if usd > 0:
            return usd
        cad  = self._account_tag('NetLiquidation', currency='CAD')
        rate = float(os.environ.get('USD_CAD_RATE', '1.38'))
        return cad / rate

    def get_cash(self) -> float:
        """Available cash in CAD."""
        return self._account_tag('TotalCashValue')

    def get_positions(self) -> dict:
        """
        Returns all equity positions (both USD and CAD) as:
          { 'AAPL':  {'qty': float, 'market_value': float, 'avg_entry_price': float} }
          { 'RY.TO': {'qty': float, 'market_value': float, 'avg_entry_price': float} }
        TSX positions get the '.TO' suffix re-attached; US positions use plain symbol.
        """
        positions = {}
        for item in self.ib.portfolio():
            c = item.contract
            if c.secType == 'STK' and float(item.position) != 0:
                if c.currency == 'CAD':
                    ticker = c.symbol + '.TO'
                else:
                    ticker = c.symbol          # USD — plain symbol matches Yahoo Finance
                positions[ticker] = {
                    'qty':             float(item.position),
                    'market_value':    float(item.marketValue),
                    'avg_entry_price': float(item.averageCost),
                }
        return positions

    # ── Order execution ──────────────────────────────────────────────────────

    def close_position(self, ticker: str):
        """Close (sell) all shares of a TSX position at market."""
        positions = self.get_positions()
        if ticker not in positions:
            print(f"  [SELL] No open position found for {ticker}, skipping")
            return None

        qty = int(positions[ticker]['qty'])
        if qty <= 0:
            return None

        contract   = self._contract(ticker)
        order      = MarketOrder('SELL', qty)
        order.tif  = 'DAY'
        trade      = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)   # brief pause to let the order register
        print(f"  [SELL] {ticker}: {qty} shares → order {trade.order.orderId}")
        return trade

    def place_market_buy(self, ticker: str, qty: int):
        """Place a market day order to buy qty shares of a TSX stock."""
        if qty <= 0:
            return None

        contract   = self._contract(ticker)
        order      = MarketOrder('BUY', qty)
        order.tif  = 'DAY'
        trade      = self.ib.placeOrder(contract, order)
        self.ib.sleep(1)
        print(f"  [BUY]  {ticker}: {qty} shares → order {trade.order.orderId}")
        return trade

    # ── Market hours ─────────────────────────────────────────────────────────

    def is_market_open(self) -> bool:
        """
        Returns True if NYSE is currently open:
          - Monday–Friday
          - 09:30–16:00 ET
          - Not a market holiday (including Good Friday)
        """
        now = datetime.now(_TORONTO)
        if now.weekday() >= 5:
            return False
        t = now.time()
        if not (time(9, 30) <= t <= time(16, 0)):
            return False
        try:
            import pandas_market_calendars as mcal
            import pandas as pd
            nyse  = mcal.get_calendar('NYSE')
            today = pd.Timestamp(now.date())
            return len(nyse.valid_days(start_date=today, end_date=today)) > 0
        except ImportError:
            return True   # if library missing, skip holiday check

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def disconnect(self):
        """Disconnect from TWS / IB Gateway."""
        self.ib.disconnect()
        print("[IBKR] Disconnected")
