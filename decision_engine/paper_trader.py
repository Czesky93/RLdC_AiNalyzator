"""
Paper Trading Module
Simulates trading with virtual balance for testing strategies without real money.
"""

from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from .aggregator import TradeSignal, Action


@dataclass
class Trade:
    """
    Represents a single trade execution.
    
    Attributes:
        timestamp: When the trade was executed
        action: The action taken (BUY/SELL/HOLD)
        price: The price at which the trade was executed
        amount: The amount of asset traded
        fee: The fee charged for the trade
        balance_after: Virtual balance after the trade
        holdings_after: Asset holdings after the trade
        reason: Reason for the trade
    """
    timestamp: datetime
    action: Action
    price: float
    amount: float
    fee: float
    balance_after: float
    holdings_after: float
    reason: Optional[str] = None


class PaperTrader:
    """
    Paper trading system for simulating trades with virtual balance.
    
    Tracks virtual balance, asset holdings, and maintains a trade history.
    Simulates trading fees to provide realistic results.
    """
    
    def __init__(
        self,
        virtual_balance: float = 10000.0,
        fee_rate: float = 0.001,
        min_trade_amount: float = 10.0
    ):
        """
        Initialize the paper trader.
        
        Args:
            virtual_balance: Starting balance in USDT (default: 10,000)
            fee_rate: Trading fee rate as decimal (default: 0.001 = 0.1%)
            min_trade_amount: Minimum trade amount in USDT (default: 10.0)
        """
        self.initial_balance = virtual_balance
        self.balance = virtual_balance
        self.holdings = 0.0  # Amount of asset held
        self.fee_rate = fee_rate
        self.min_trade_amount = min_trade_amount
        self.trade_history: List[Trade] = []
    
    def get_portfolio_value(self, current_price: float) -> float:
        """
        Calculate total portfolio value (balance + holdings value).
        
        Args:
            current_price: Current price of the asset
        
        Returns:
            Total portfolio value in USDT
        """
        return self.balance + (self.holdings * current_price)
    
    def get_profit_loss(self, current_price: float) -> Dict[str, float]:
        """
        Calculate profit/loss statistics.
        
        Args:
            current_price: Current price of the asset
        
        Returns:
            Dictionary with profit/loss metrics
        """
        current_value = self.get_portfolio_value(current_price)
        absolute_pl = current_value - self.initial_balance
        percentage_pl = (absolute_pl / self.initial_balance) * 100
        
        return {
            'absolute': absolute_pl,
            'percentage': percentage_pl,
            'current_value': current_value,
            'initial_value': self.initial_balance
        }
    
    def _calculate_fee(self, trade_amount: float) -> float:
        """
        Calculate trading fee for a given trade amount.
        
        Args:
            trade_amount: The trade amount in USDT
        
        Returns:
            Fee amount in USDT
        """
        return trade_amount * self.fee_rate
    
    def _log_trade(
        self,
        action: Action,
        price: float,
        amount: float,
        fee: float,
        reason: Optional[str] = None
    ) -> Trade:
        """
        Log a trade to the history.
        
        Args:
            action: The action taken
            price: Execution price
            amount: Amount traded
            fee: Fee charged
            reason: Reason for the trade
        
        Returns:
            The created Trade object
        """
        trade = Trade(
            timestamp=datetime.now(),
            action=action,
            price=price,
            amount=amount,
            fee=fee,
            balance_after=self.balance,
            holdings_after=self.holdings,
            reason=reason
        )
        self.trade_history.append(trade)
        return trade
    
    def execute_order(
        self,
        signal: TradeSignal,
        current_price: float,
        trade_percentage: float = 1.0
    ) -> Optional[Trade]:
        """
        Execute a trade based on the given signal.
        
        Args:
            signal: TradeSignal containing action and confidence
            current_price: Current market price of the asset
            trade_percentage: Percentage of available funds to trade (0.0-1.0)
        
        Returns:
            Trade object if executed, None if HOLD or insufficient funds
        """
        if not 0.0 <= trade_percentage <= 1.0:
            raise ValueError(f"trade_percentage must be between 0.0 and 1.0, got {trade_percentage}")
        
        if signal.action == Action.HOLD:
            # Log HOLD action but don't execute any trade
            self._log_trade(
                action=Action.HOLD,
                price=current_price,
                amount=0.0,
                fee=0.0,
                reason=signal.reason
            )
            return None
        
        if signal.action == Action.BUY:
            # Calculate amount to buy based on available balance
            available_balance = self.balance * trade_percentage
            
            if available_balance < self.min_trade_amount:
                # Insufficient funds
                self._log_trade(
                    action=Action.HOLD,
                    price=current_price,
                    amount=0.0,
                    fee=0.0,
                    reason=f"Insufficient balance for BUY: {available_balance:.2f} USDT < {self.min_trade_amount:.2f} USDT"
                )
                return None
            
            # Calculate fee and actual purchase amount
            fee = self._calculate_fee(available_balance)
            amount_after_fee = available_balance - fee
            asset_amount = amount_after_fee / current_price
            
            # Update balance and holdings
            self.balance -= available_balance
            self.holdings += asset_amount
            
            # Log the trade
            return self._log_trade(
                action=Action.BUY,
                price=current_price,
                amount=asset_amount,
                fee=fee,
                reason=signal.reason
            )
        
        elif signal.action == Action.SELL:
            # Calculate amount to sell based on current holdings
            asset_to_sell = self.holdings * trade_percentage
            
            if asset_to_sell <= 0:
                # No assets to sell
                self._log_trade(
                    action=Action.HOLD,
                    price=current_price,
                    amount=0.0,
                    fee=0.0,
                    reason="No assets to sell"
                )
                return None
            
            # Calculate sale proceeds
            sale_proceeds = asset_to_sell * current_price
            
            if sale_proceeds < self.min_trade_amount:
                # Trade amount too small
                self._log_trade(
                    action=Action.HOLD,
                    price=current_price,
                    amount=0.0,
                    fee=0.0,
                    reason=f"Sale amount too small: {sale_proceeds:.2f} USDT < {self.min_trade_amount:.2f} USDT"
                )
                return None
            
            # Calculate fee and final proceeds
            fee = self._calculate_fee(sale_proceeds)
            proceeds_after_fee = sale_proceeds - fee
            
            # Update balance and holdings
            self.balance += proceeds_after_fee
            self.holdings -= asset_to_sell
            
            # Log the trade
            return self._log_trade(
                action=Action.SELL,
                price=current_price,
                amount=asset_to_sell,
                fee=fee,
                reason=signal.reason
            )
        
        return None
    
    def reset(self, new_balance: Optional[float] = None):
        """
        Reset the paper trader to initial state.
        
        Args:
            new_balance: New starting balance (uses initial_balance if None)
        """
        if new_balance is not None:
            self.initial_balance = new_balance
        self.balance = self.initial_balance
        self.holdings = 0.0
        self.trade_history = []
    
    def get_trade_summary(self) -> Dict[str, Any]:
        """
        Get a summary of trading activity.
        
        Returns:
            Dictionary with trading statistics
        """
        if not self.trade_history:
            return {
                'total_trades': 0,
                'buy_count': 0,
                'sell_count': 0,
                'hold_count': 0,
                'total_fees': 0.0
            }
        
        buy_count = sum(1 for t in self.trade_history if t.action == Action.BUY)
        sell_count = sum(1 for t in self.trade_history if t.action == Action.SELL)
        hold_count = sum(1 for t in self.trade_history if t.action == Action.HOLD)
        total_fees = sum(t.fee for t in self.trade_history)
        
        return {
            'total_trades': len(self.trade_history),
            'buy_count': buy_count,
            'sell_count': sell_count,
            'hold_count': hold_count,
            'total_fees': total_fees,
            'current_balance': self.balance,
            'current_holdings': self.holdings
        }
