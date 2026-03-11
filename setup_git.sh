#!/bin/bash

# Git Setup Script for Momentum Trading System

echo "Setting up Git repository..."

cd momentum_trading_system

# Initialize
git init

# Add files
git add .

# Initial commit
git commit -m "Initial commit: S&P 500 momentum trading system

Features:
- Backtesting framework (27% annualized, Sharpe 1.23)
- Live trading infrastructure
- Paper broker with real prices
- Database-backed tracking
- Quarterly rebalancing automation
- Ready for Alpaca/IBKR integration"

echo ""
echo "✓ Git repository initialized"
echo ""
echo "Next steps:"
echo "1. Create repository on GitHub: https://github.com/new"
echo "2. Run: git remote add origin https://github.com/YOUR_USERNAME/momentum-trading-system.git"
echo "3. Run: git push -u origin main"
echo ""
