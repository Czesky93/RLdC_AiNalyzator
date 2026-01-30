"""
Backtesting Engine for simulating trading strategies.
"""

import pandas as pd
from typing import Callable, Dict, List, Tuple
from datetime import datetime


class Backtester:
    """
    Simulates trading strategy execution on historical data.
    """
    
    def __init__(self, initial_capital: float = 10000.0, commission_rate: float = 0.001):
        """
        Initialize the backtester.
        
        Args:
            initial_capital: Starting capital in quote currency
            commission_rate: Trading commission rate (e.g., 0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.equity_curve = []
        self.trade_history = []
        
        # Portfolio state
        self.cash = initial_capital
        self.asset_balance = 0.0
        self.position = None  # 'LONG' or None
    
    def run(self, data: pd.DataFrame, strategy_logic: Callable) -> Dict:
        """
        Run the backtest on historical data.
        
        Args:
            data: DataFrame with OHLCV data
            strategy_logic: Function that takes a row and returns 'BUY', 'SELL', or 'HOLD'
            
        Returns:
            Dictionary with backtest results including equity_curve and trade_history
        """
        # Reset state
        self.cash = self.initial_capital
        self.asset_balance = 0.0
        self.position = None
        self.equity_curve = []
        self.trade_history = []
        
        # Iterate through each time step
        for idx, row in data.iterrows():
            # Get trading signal from strategy
            signal = strategy_logic(row)
            
            # Execute trades based on signal
            if signal == 'BUY' and self.position is None:
                self._execute_buy(row)
            elif signal == 'SELL' and self.position == 'LONG':
                self._execute_sell(row)
            
            # Calculate portfolio value
            if self.position == 'LONG':
                portfolio_value = self.cash + (self.asset_balance * row['close'])
            else:
                portfolio_value = self.cash
            
            # Record equity curve
            self.equity_curve.append({
                'timestamp': row['timestamp'],
                'total_value': portfolio_value,
                'cash': self.cash,
                'asset_value': self.asset_balance * row['close'] if self.position else 0
            })
        
        return {
            'equity_curve': pd.DataFrame(self.equity_curve),
            'trade_history': pd.DataFrame(self.trade_history) if self.trade_history else pd.DataFrame(),
            'final_value': self.equity_curve[-1]['total_value'] if self.equity_curve else self.initial_capital,
            'initial_capital': self.initial_capital
        }
    
    def _execute_buy(self, row: pd.Series) -> None:
        """Execute a buy order."""
        price = row['close']
        commission = self.cash * self.commission_rate
        available_cash = self.cash - commission
        
        if available_cash > 0:
            self.asset_balance = available_cash / price
            self.position = 'LONG'
            
            self.trade_history.append({
                'timestamp': row['timestamp'],
                'type': 'BUY',
                'price': price,
                'amount': self.asset_balance,
                'commission': commission,
                'cash_before': self.cash
            })
            
            self.cash = 0.0
    
    def _execute_sell(self, row: pd.Series) -> None:
        """Execute a sell order."""
        price = row['close']
        proceeds = self.asset_balance * price
        commission = proceeds * self.commission_rate
        
        cash_before = self.cash
        asset_amount = self.asset_balance
        
        self.cash = proceeds - commission
        self.asset_balance = 0.0
        self.position = None
        
        # Calculate profit/loss for this trade
        if len(self.trade_history) > 0:
            last_buy = [t for t in self.trade_history if t['type'] == 'BUY'][-1]
            pnl = self.cash - last_buy['cash_before']
            pnl_pct = (pnl / last_buy['cash_before']) * 100
        else:
            pnl = 0
            pnl_pct = 0
        
        self.trade_history.append({
            'timestamp': row['timestamp'],
            'type': 'SELL',
            'price': price,
            'amount': asset_amount,
            'commission': commission,
            'cash_before': cash_before,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })
