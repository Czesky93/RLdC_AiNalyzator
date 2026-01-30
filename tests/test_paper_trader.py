"""
Tests for the PaperTrader module.
"""

import pytest
from decision_engine.paper_trader import PaperTrader, Trade
from decision_engine.aggregator import TradeSignal, Action


class TestPaperTrader:
    """Tests for PaperTrader class."""
    
    def test_initialization_default(self):
        """Test initialization with default parameters."""
        trader = PaperTrader()
        assert trader.balance == 10000.0
        assert trader.initial_balance == 10000.0
        assert trader.holdings == 0.0
        assert trader.fee_rate == 0.001
        assert len(trader.trade_history) == 0
    
    def test_initialization_custom(self):
        """Test initialization with custom parameters."""
        trader = PaperTrader(
            virtual_balance=50000.0,
            fee_rate=0.002,
            min_trade_amount=20.0
        )
        assert trader.balance == 50000.0
        assert trader.fee_rate == 0.002
        assert trader.min_trade_amount == 20.0
    
    def test_get_portfolio_value(self):
        """Test portfolio value calculation."""
        trader = PaperTrader(virtual_balance=10000.0)
        trader.holdings = 5.0
        current_price = 100.0
        
        portfolio_value = trader.get_portfolio_value(current_price)
        # 10000 balance + 5 holdings * 100 price = 10500
        assert portfolio_value == 10500.0
    
    def test_get_profit_loss(self):
        """Test profit/loss calculation."""
        trader = PaperTrader(virtual_balance=10000.0)
        trader.balance = 12000.0
        trader.holdings = 0.0
        
        pl = trader.get_profit_loss(100.0)
        assert pl['absolute'] == 2000.0
        assert pl['percentage'] == 20.0
        assert pl['current_value'] == 12000.0
        assert pl['initial_value'] == 10000.0
    
    def test_execute_buy_order(self):
        """Test executing a BUY order."""
        trader = PaperTrader(virtual_balance=10000.0)
        signal = TradeSignal(action=Action.BUY, confidence=0.8)
        current_price = 100.0
        
        trade = trader.execute_order(signal, current_price)
        
        assert trade is not None
        assert trade.action == Action.BUY
        assert trader.balance < 10000.0  # Balance should decrease
        assert trader.holdings > 0  # Should have holdings
        assert trade.fee > 0  # Should have paid fees
    
    def test_execute_sell_order(self):
        """Test executing a SELL order."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        # First buy some assets
        buy_signal = TradeSignal(action=Action.BUY, confidence=0.8)
        trader.execute_order(buy_signal, 100.0)
        
        # Now sell
        sell_signal = TradeSignal(action=Action.SELL, confidence=0.7)
        initial_holdings = trader.holdings
        trade = trader.execute_order(sell_signal, 120.0)
        
        assert trade is not None
        assert trade.action == Action.SELL
        assert trader.holdings < initial_holdings  # Holdings should decrease
        assert trade.fee > 0  # Should have paid fees
    
    def test_execute_hold_order(self):
        """Test executing a HOLD order."""
        trader = PaperTrader(virtual_balance=10000.0)
        signal = TradeSignal(action=Action.HOLD, confidence=0.5)
        
        initial_balance = trader.balance
        initial_holdings = trader.holdings
        
        trade = trader.execute_order(signal, 100.0)
        
        assert trade is None  # HOLD doesn't return a trade
        assert trader.balance == initial_balance  # Balance unchanged
        assert trader.holdings == initial_holdings  # Holdings unchanged
    
    def test_execute_sell_without_holdings(self):
        """Test attempting to sell without holdings."""
        trader = PaperTrader(virtual_balance=10000.0)
        signal = TradeSignal(action=Action.SELL, confidence=0.8)
        
        trade = trader.execute_order(signal, 100.0)
        
        assert trade is None  # Can't sell without holdings
    
    def test_execute_buy_with_partial_percentage(self):
        """Test buying with partial percentage of balance."""
        trader = PaperTrader(virtual_balance=10000.0)
        signal = TradeSignal(action=Action.BUY, confidence=0.8)
        
        trade = trader.execute_order(signal, 100.0, trade_percentage=0.5)
        
        assert trade is not None
        # Should use about half the balance
        assert trader.balance >= 5000.0  # At least half remaining
        assert trader.balance < 10000.0  # But less than full balance
    
    def test_fee_calculation(self):
        """Test that fees are correctly calculated and applied."""
        trader = PaperTrader(virtual_balance=10000.0, fee_rate=0.001)
        signal = TradeSignal(action=Action.BUY, confidence=0.8)
        
        trade = trader.execute_order(signal, 100.0)
        
        # Fee should be 0.1% of the allocated balance (not the final asset purchase)
        expected_fee = 10000.0 * 0.001
        assert abs(trade.fee - expected_fee) < 0.01
    
    def test_trade_history_logging(self):
        """Test that trades are logged in history."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        # Execute multiple trades
        trader.execute_order(TradeSignal(Action.BUY, 0.8), 100.0)
        trader.execute_order(TradeSignal(Action.SELL, 0.7), 110.0)
        trader.execute_order(TradeSignal(Action.HOLD, 0.5), 105.0)
        
        assert len(trader.trade_history) == 3
        assert trader.trade_history[0].action == Action.BUY
        assert trader.trade_history[1].action == Action.SELL
        assert trader.trade_history[2].action == Action.HOLD
    
    def test_reset(self):
        """Test resetting the trader."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        # Make some trades
        trader.execute_order(TradeSignal(Action.BUY, 0.8), 100.0)
        trader.execute_order(TradeSignal(Action.SELL, 0.7), 110.0)
        
        # Reset
        trader.reset()
        
        assert trader.balance == 10000.0
        assert trader.holdings == 0.0
        assert len(trader.trade_history) == 0
    
    def test_reset_with_new_balance(self):
        """Test resetting with a new balance."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        trader.reset(new_balance=50000.0)
        
        assert trader.balance == 50000.0
        assert trader.initial_balance == 50000.0
    
    def test_get_trade_summary(self):
        """Test trade summary generation."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        # Execute various trades
        # First buy uses all available balance
        trader.execute_order(TradeSignal(Action.BUY, 0.8), 100.0)
        # Second buy will fail due to insufficient balance and log as HOLD
        trader.execute_order(TradeSignal(Action.BUY, 0.8), 105.0)
        # Sell the holdings
        trader.execute_order(TradeSignal(Action.SELL, 0.7), 110.0)
        # Explicit hold
        trader.execute_order(TradeSignal(Action.HOLD, 0.5), 108.0)
        
        summary = trader.get_trade_summary()
        
        assert summary['total_trades'] == 4
        # First BUY succeeds, second fails (insufficient funds) -> becomes HOLD
        assert summary['buy_count'] == 1
        assert summary['sell_count'] == 1
        # Failed BUY + explicit HOLD = 2
        assert summary['hold_count'] == 2
        assert summary['total_fees'] > 0
    
    def test_min_trade_amount(self):
        """Test minimum trade amount enforcement."""
        trader = PaperTrader(virtual_balance=5.0, min_trade_amount=10.0)
        signal = TradeSignal(action=Action.BUY, confidence=0.8)
        
        trade = trader.execute_order(signal, 100.0)
        
        # Should not execute due to insufficient balance
        assert trade is None
    
    def test_realistic_trading_scenario(self):
        """Test a realistic trading scenario with profit."""
        trader = PaperTrader(virtual_balance=10000.0)
        
        # Buy at 100
        buy_signal = TradeSignal(action=Action.BUY, confidence=0.8)
        trader.execute_order(buy_signal, 100.0, trade_percentage=1.0)
        
        # Price goes up, sell at 120
        sell_signal = TradeSignal(action=Action.SELL, confidence=0.7)
        trader.execute_order(sell_signal, 120.0, trade_percentage=1.0)
        
        # Calculate profit
        pl = trader.get_profit_loss(120.0)
        
        # Should have made profit (accounting for fees)
        assert pl['absolute'] > 0
        assert trader.balance > 10000.0
