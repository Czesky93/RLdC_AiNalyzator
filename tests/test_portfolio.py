"""Unit tests for Portfolio Management Module."""

import unittest
from datetime import datetime
from portfolio_management import Transaction, PortfolioManager, RiskEngine
from portfolio_management.portfolio import InsufficientFundsError, InsufficientHoldingsError


class TestTransaction(unittest.TestCase):
    """Test Transaction dataclass."""
    
    def test_transaction_creation(self):
        """Test creating a transaction."""
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.5,
            price=50000.0,
            fee=10.0,
            total_cost=25010.0
        )
        self.assertEqual(tx.id, "tx-001")
        self.assertEqual(tx.symbol, "BTC/USD")
        self.assertEqual(tx.side, "buy")
        self.assertEqual(tx.amount, 0.5)
        self.assertEqual(tx.price, 50000.0)
        self.assertEqual(tx.fee, 10.0)
        self.assertEqual(tx.total_cost, 25010.0)


class TestPortfolioManager(unittest.TestCase):
    """Test PortfolioManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = PortfolioManager(initial_cash=10000.0)
    
    def test_initial_balance(self):
        """Test initial cash balance."""
        self.assertEqual(self.portfolio.cash_balance, 10000.0)
        self.assertEqual(len(self.portfolio.positions), 0)
    
    def test_deposit(self):
        """Test depositing funds."""
        self.portfolio.deposit(5000.0)
        self.assertEqual(self.portfolio.cash_balance, 15000.0)
    
    def test_deposit_negative_raises_error(self):
        """Test that negative deposits raise an error."""
        with self.assertRaises(ValueError):
            self.portfolio.deposit(-100.0)
    
    def test_withdraw(self):
        """Test withdrawing funds."""
        self.portfolio.withdraw(3000.0)
        self.assertEqual(self.portfolio.cash_balance, 7000.0)
    
    def test_withdraw_negative_raises_error(self):
        """Test that negative withdrawals raise an error."""
        with self.assertRaises(ValueError):
            self.portfolio.withdraw(-100.0)
    
    def test_withdraw_insufficient_funds(self):
        """Test withdrawing more than available balance."""
        with self.assertRaises(InsufficientFundsError):
            self.portfolio.withdraw(15000.0)
    
    def test_execute_buy_trade(self):
        """Test executing a buy order."""
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0  # 0.1 * 50000 + 5
        )
        self.portfolio.execute_trade(tx)
        
        self.assertEqual(self.portfolio.cash_balance, 4995.0)  # 10000 - 5005
        self.assertEqual(self.portfolio.positions["BTC/USD"], 0.1)
    
    def test_execute_multiple_buy_trades(self):
        """Test executing multiple buy orders for same symbol."""
        tx1 = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        tx2 = Transaction(
            id="tx-002",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.05,
            price=51000.0,
            fee=2.5,
            total_cost=2552.5  # 0.05 * 51000 + 2.5
        )
        
        self.portfolio.execute_trade(tx1)
        self.portfolio.execute_trade(tx2)
        
        self.assertAlmostEqual(self.portfolio.cash_balance, 2442.5, places=2)  # 10000 - 5005 - 2552.5
        self.assertAlmostEqual(self.portfolio.positions["BTC/USD"], 0.15, places=2)
    
    def test_execute_buy_insufficient_funds(self):
        """Test buying with insufficient funds."""
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=1.0,
            price=50000.0,
            fee=10.0,
            total_cost=50010.0
        )
        
        with self.assertRaises(InsufficientFundsError):
            self.portfolio.execute_trade(tx)
    
    def test_execute_sell_trade(self):
        """Test executing a sell order."""
        # First buy some BTC
        buy_tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.15,
            price=50000.0,
            fee=7.5,
            total_cost=7507.5  # 0.15 * 50000 + 7.5
        )
        self.portfolio.execute_trade(buy_tx)
        
        # Now sell some BTC
        sell_tx = Transaction(
            id="tx-002",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="sell",
            amount=0.1,
            price=51000.0,
            fee=5.0,
            total_cost=5095.0  # 0.1 * 51000 - 5
        )
        self.portfolio.execute_trade(sell_tx)
        
        self.assertAlmostEqual(self.portfolio.cash_balance, 7587.5, places=2)  # 10000 - 7507.5 + 5095
        self.assertAlmostEqual(self.portfolio.positions["BTC/USD"], 0.05, places=2)
    
    def test_execute_sell_all_removes_position(self):
        """Test that selling all of a position removes it from positions dict."""
        # Buy
        buy_tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        self.portfolio.execute_trade(buy_tx)
        
        # Sell all
        sell_tx = Transaction(
            id="tx-002",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="sell",
            amount=0.1,
            price=51000.0,
            fee=5.0,
            total_cost=5095.0
        )
        self.portfolio.execute_trade(sell_tx)
        
        self.assertNotIn("BTC/USD", self.portfolio.positions)
    
    def test_execute_sell_insufficient_holdings(self):
        """Test selling with insufficient holdings."""
        sell_tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="sell",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=4995.0
        )
        
        with self.assertRaises(InsufficientHoldingsError):
            self.portfolio.execute_trade(sell_tx)
    
    def test_get_total_value(self):
        """Test calculating total portfolio value."""
        # Buy some assets
        btc_tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        eth_tx = Transaction(
            id="tx-002",
            timestamp=datetime.now(),
            symbol="ETH/USD",
            side="buy",
            amount=2.0,
            price=2000.0,
            fee=4.0,
            total_cost=4004.0
        )
        
        self.portfolio.execute_trade(btc_tx)
        self.portfolio.execute_trade(eth_tx)
        
        # Calculate total value with current prices
        current_prices = {
            "BTC/USD": 52000.0,  # Price increased
            "ETH/USD": 2100.0    # Price increased
        }
        
        total_value = self.portfolio.get_total_value(current_prices)
        
        # Cash: 10000 - 5005 - 4004 = 991
        # BTC: 0.1 * 52000 = 5200
        # ETH: 2.0 * 2100 = 4200
        # Total: 991 + 5200 + 4200 = 10391
        self.assertAlmostEqual(total_value, 10391.0, places=2)
    
    def test_get_total_value_missing_price(self):
        """Test total value calculation with missing price data."""
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        self.portfolio.execute_trade(tx)
        
        # Missing BTC price - should default to 0
        total_value = self.portfolio.get_total_value({})
        
        # Only cash remains: 10000 - 5005 = 4995
        self.assertAlmostEqual(total_value, 4995.0, places=2)
    
    def test_get_portfolio_state(self):
        """Test getting portfolio state."""
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        self.portfolio.execute_trade(tx)
        
        state = self.portfolio.get_portfolio_state()
        
        self.assertEqual(state['cash_balance'], 4995.0)
        self.assertEqual(state['positions']['BTC/USD'], 0.1)
        
        # Verify it's a copy (modifying returned state doesn't affect portfolio)
        state['positions']['ETH/USD'] = 1.0
        self.assertNotIn('ETH/USD', self.portfolio.positions)


class TestRiskEngine(unittest.TestCase):
    """Test RiskEngine class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.portfolio = PortfolioManager(initial_cash=10000.0)
        self.risk_engine = RiskEngine(
            max_position_size_pct=0.25,  # 25%
            max_drawdown_pct=0.20  # 20%
        )
    
    def test_initial_state(self):
        """Test initial risk engine state."""
        self.assertEqual(self.risk_engine.max_position_size_pct, 0.25)
        self.assertEqual(self.risk_engine.max_drawdown_pct, 0.20)
        self.assertEqual(self.risk_engine.initial_balance, 0.0)
    
    def test_set_initial_balance(self):
        """Test setting initial balance."""
        self.risk_engine.set_initial_balance(10000.0)
        self.assertEqual(self.risk_engine.initial_balance, 10000.0)
    
    def test_check_trade_risk_within_limits(self):
        """Test trade within position size limits."""
        current_prices = {"BTC/USD": 50000.0}
        
        # Trade value: 0.04 * 50000 = 2000 (20% of 10000 portfolio)
        result = self.risk_engine.check_trade_risk(
            portfolio=self.portfolio,
            symbol="BTC/USD",
            side="buy",
            amount=0.04,
            price=50000.0,
            current_prices=current_prices
        )
        
        self.assertTrue(result)
    
    def test_check_trade_risk_exceeds_position_limit(self):
        """Test trade exceeding max position size."""
        current_prices = {"BTC/USD": 50000.0}
        
        # Trade value: 0.06 * 50000 = 3000 (30% of 10000 portfolio)
        result = self.risk_engine.check_trade_risk(
            portfolio=self.portfolio,
            symbol="BTC/USD",
            side="buy",
            amount=0.06,
            price=50000.0,
            current_prices=current_prices
        )
        
        self.assertFalse(result)
    
    def test_check_trade_risk_no_prices(self):
        """Test trade risk check without current prices."""
        result = self.risk_engine.check_trade_risk(
            portfolio=self.portfolio,
            symbol="BTC/USD",
            side="buy",
            amount=0.04,
            price=50000.0,
            current_prices=None
        )
        
        self.assertFalse(result)
    
    def test_check_trade_risk_sell_order(self):
        """Test risk check for sell orders (should pass position size check)."""
        # First buy some BTC
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        self.portfolio.execute_trade(tx)
        
        current_prices = {"BTC/USD": 50000.0}
        
        # Sell orders don't check position size
        result = self.risk_engine.check_trade_risk(
            portfolio=self.portfolio,
            symbol="BTC/USD",
            side="sell",
            amount=0.05,
            price=50000.0,
            current_prices=current_prices
        )
        
        self.assertTrue(result)
    
    def test_check_max_drawdown_within_limits(self):
        """Test drawdown within limits."""
        self.risk_engine.set_initial_balance(10000.0)
        
        # Buy and lose value
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.1,
            price=50000.0,
            fee=5.0,
            total_cost=5005.0
        )
        self.portfolio.execute_trade(tx)
        
        # Price drops but not below 20% drawdown
        # Cash: 4995, BTC value: 0.1 * 45000 = 4500, Total: 9495 (< 20% drawdown from 10000)
        current_prices = {"BTC/USD": 45000.0}
        
        result = self.risk_engine.check_max_drawdown(self.portfolio, current_prices)
        self.assertTrue(result)
    
    def test_check_max_drawdown_exceeds_limit(self):
        """Test drawdown exceeding limits."""
        self.risk_engine.set_initial_balance(10000.0)
        
        # Buy
        tx = Transaction(
            id="tx-001",
            timestamp=datetime.now(),
            symbol="BTC/USD",
            side="buy",
            amount=0.15,
            price=50000.0,
            fee=5.0,
            total_cost=7505.0
        )
        self.portfolio.execute_trade(tx)
        
        # Price crashes
        # Cash: 2495, BTC value: 0.15 * 30000 = 4500, Total: 6995 (30% drawdown from 10000)
        current_prices = {"BTC/USD": 30000.0}
        
        result = self.risk_engine.check_max_drawdown(self.portfolio, current_prices)
        self.assertFalse(result)
    
    def test_check_max_drawdown_no_initial_balance(self):
        """Test drawdown check without initial balance set."""
        result = self.risk_engine.check_max_drawdown(self.portfolio, {})
        self.assertTrue(result)  # Should pass when initial balance not set
    
    def test_check_trade_risk_with_drawdown(self):
        """Test trade risk check includes drawdown check."""
        self.risk_engine.set_initial_balance(10000.0)
        
        # Simulate a portfolio in significant drawdown
        # Withdraw funds to simulate losses
        self.portfolio.withdraw(2500.0)  # 25% drawdown
        
        current_prices = {"BTC/USD": 50000.0}
        
        # Even though trade is within position size, it should fail due to drawdown
        result = self.risk_engine.check_trade_risk(
            portfolio=self.portfolio,
            symbol="BTC/USD",
            side="buy",
            amount=0.01,
            price=50000.0,
            current_prices=current_prices
        )
        
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
