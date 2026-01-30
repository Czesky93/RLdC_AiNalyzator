"""
Tests for the BotKernel module.
"""

import pytest
from decision_engine.core import BotKernel
from decision_engine.aggregator import Action


class TestBotKernel:
    """Tests for BotKernel class."""
    
    def test_initialization_default(self):
        """Test initialization with default parameters."""
        kernel = BotKernel()
        
        assert kernel.aggregator is not None
        assert kernel.paper_trader is not None
        assert kernel.step_count == 0
        assert kernel.trade_percentage == 1.0
    
    def test_initialization_with_custom_parameters(self):
        """Test initialization with custom parameters."""
        kernel = BotKernel(
            virtual_balance=50000.0,
            sentiment_weight=0.4,
            quantum_weight=0.3,
            ai_weight=0.3,
            fee_rate=0.002,
            trade_percentage=0.5
        )
        
        assert kernel.paper_trader.initial_balance == 50000.0
        assert kernel.aggregator.sentiment_weight == 0.4
        assert kernel.trade_percentage == 0.5
    
    def test_step_with_no_fetchers(self):
        """Test step execution with no data fetchers."""
        kernel = BotKernel()
        
        result = kernel.step()
        
        assert result is not None
        assert result['step'] == 1
        assert 'timestamp' in result
        assert 'sentiment' in result
        assert 'quantum' in result
        assert 'ai' in result
        assert 'price' in result
        assert 'signal' in result
        assert 'portfolio_value' in result
    
    def test_step_with_custom_fetchers(self):
        """Test step execution with custom data fetchers."""
        # Mock data fetchers
        def sentiment_fetcher():
            return 0.7
        
        def quantum_fetcher():
            return 0.5
        
        def ai_predictor():
            return 0.8
        
        def price_fetcher():
            return 100.0
        
        kernel = BotKernel(
            sentiment_fetcher=sentiment_fetcher,
            quantum_fetcher=quantum_fetcher,
            ai_predictor=ai_predictor,
            price_fetcher=price_fetcher
        )
        
        result = kernel.step()
        
        assert result['sentiment'] == 0.7
        assert result['quantum'] == 0.5
        assert result['ai'] == 0.8
        assert result['price'] == 100.0
    
    def test_multiple_steps(self):
        """Test executing multiple steps."""
        kernel = BotKernel()
        
        result1 = kernel.step()
        result2 = kernel.step()
        result3 = kernel.step()
        
        assert result1['step'] == 1
        assert result2['step'] == 2
        assert result3['step'] == 3
        assert kernel.step_count == 3
    
    def test_step_with_bullish_signals(self):
        """Test step with bullish signals leads to BUY."""
        def sentiment_fetcher():
            return 0.8
        
        def quantum_fetcher():
            return 0.7
        
        def ai_predictor():
            return 0.9
        
        def price_fetcher():
            return 100.0
        
        kernel = BotKernel(
            sentiment_fetcher=sentiment_fetcher,
            quantum_fetcher=quantum_fetcher,
            ai_predictor=ai_predictor,
            price_fetcher=price_fetcher
        )
        
        result = kernel.step()
        
        assert result['signal'].action == Action.BUY
        assert result['trade'] is not None
    
    def test_step_with_bearish_signals_after_buy(self):
        """Test step with bearish signals leads to SELL after initial BUY."""
        step_counter = {'count': 0}
        
        def sentiment_fetcher():
            step_counter['count'] += 1
            return 0.8 if step_counter['count'] == 1 else -0.8
        
        def quantum_fetcher():
            return 0.7 if step_counter['count'] == 1 else -0.7
        
        def ai_predictor():
            return 0.9 if step_counter['count'] == 1 else -0.9
        
        def price_fetcher():
            return 100.0 if step_counter['count'] == 1 else 120.0
        
        kernel = BotKernel(
            sentiment_fetcher=sentiment_fetcher,
            quantum_fetcher=quantum_fetcher,
            ai_predictor=ai_predictor,
            price_fetcher=price_fetcher
        )
        
        # First step: BUY
        result1 = kernel.step()
        assert result1['signal'].action == Action.BUY
        
        # Second step: SELL
        result2 = kernel.step()
        assert result2['signal'].action == Action.SELL
    
    def test_get_status(self):
        """Test getting bot status."""
        kernel = BotKernel()
        
        # Execute a few steps
        kernel.step()
        kernel.step()
        
        status = kernel.get_status()
        
        assert status['step_count'] == 2
        assert 'latest_sentiment' in status
        assert 'latest_quantum' in status
        assert 'latest_ai' in status
        assert 'latest_price' in status
        assert 'latest_signal' in status
        assert 'portfolio_value' in status
        assert 'profit_loss' in status
        assert 'trade_summary' in status
    
    def test_reset(self):
        """Test resetting the bot kernel."""
        kernel = BotKernel()
        
        # Execute some steps
        kernel.step()
        kernel.step()
        
        # Reset
        kernel.reset()
        
        assert kernel.step_count == 0
        assert kernel._latest_sentiment is None
        assert kernel._latest_quantum is None
        assert kernel._latest_ai is None
        assert kernel._latest_price is None
        assert kernel._latest_signal is None
        assert kernel.paper_trader.balance == kernel.paper_trader.initial_balance
    
    def test_reset_with_new_balance(self):
        """Test resetting with a new balance."""
        kernel = BotKernel(virtual_balance=10000.0)
        
        kernel.reset(new_balance=50000.0)
        
        assert kernel.paper_trader.balance == 50000.0
        assert kernel.paper_trader.initial_balance == 50000.0
    
    def test_error_handling_in_fetchers(self):
        """Test that errors in fetchers are handled gracefully."""
        def failing_fetcher():
            raise Exception("Fetcher error")
        
        kernel = BotKernel(
            sentiment_fetcher=failing_fetcher,
            quantum_fetcher=failing_fetcher,
            ai_predictor=failing_fetcher,
            price_fetcher=lambda: 100.0  # Price fetcher works
        )
        
        # Should not raise, should use default values
        result = kernel.step()
        
        assert result is not None
        assert result['sentiment'] == 0.0  # Default fallback
        assert result['quantum'] == 0.0  # Default fallback
        assert result['ai'] == 0.0  # Default fallback
    
    def test_profit_tracking(self):
        """Test profit tracking across multiple steps."""
        step_counter = {'count': 0}
        
        def price_fetcher():
            step_counter['count'] += 1
            # Price increases over time
            return 100.0 + (step_counter['count'] * 10.0)
        
        def bullish_sentiment():
            return 0.8
        
        kernel = BotKernel(
            sentiment_fetcher=bullish_sentiment,
            quantum_fetcher=bullish_sentiment,
            ai_predictor=bullish_sentiment,
            price_fetcher=price_fetcher
        )
        
        # Buy at 100
        result1 = kernel.step()
        
        # Hold/observe price increase
        result2 = kernel.step()
        result3 = kernel.step()
        
        # Portfolio value should reflect price increase
        assert result3['portfolio_value'] > result1['portfolio_value']
    
    def test_trade_percentage(self):
        """Test that trade_percentage limits position size."""
        kernel = BotKernel(
            virtual_balance=10000.0,
            trade_percentage=0.5  # Only use 50% of balance
        )
        
        # Mock bullish signal
        kernel.sentiment_fetcher = lambda: 0.8
        kernel.quantum_fetcher = lambda: 0.7
        kernel.ai_predictor = lambda: 0.9
        kernel.price_fetcher = lambda: 100.0
        
        result = kernel.step()
        
        # Should have balance remaining (used only 50%)
        assert kernel.paper_trader.balance > 0
        assert kernel.paper_trader.balance > 4000.0  # More than half remaining
