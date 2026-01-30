"""
Tests for the SignalAggregator module.
"""

import pytest
from decision_engine.aggregator import SignalAggregator, TradeSignal, Action


class TestTradeSignal:
    """Tests for TradeSignal dataclass."""
    
    def test_trade_signal_creation(self):
        """Test creating a valid TradeSignal."""
        signal = TradeSignal(action=Action.BUY, confidence=0.75)
        assert signal.action == Action.BUY
        assert signal.confidence == 0.75
        assert signal.reason is None
    
    def test_trade_signal_with_reason(self):
        """Test creating a TradeSignal with reason."""
        signal = TradeSignal(
            action=Action.SELL,
            confidence=0.9,
            reason="Strong bearish signal"
        )
        assert signal.reason == "Strong bearish signal"
    
    def test_confidence_validation(self):
        """Test that confidence must be between 0.0 and 1.0."""
        with pytest.raises(ValueError):
            TradeSignal(action=Action.BUY, confidence=1.5)
        
        with pytest.raises(ValueError):
            TradeSignal(action=Action.BUY, confidence=-0.1)


class TestSignalAggregator:
    """Tests for SignalAggregator class."""
    
    def test_initialization_default_weights(self):
        """Test initialization with default weights."""
        aggregator = SignalAggregator()
        assert aggregator.sentiment_weight == 0.3
        assert aggregator.quantum_weight == 0.2
        assert aggregator.ai_weight == 0.5
    
    def test_initialization_custom_weights(self):
        """Test initialization with custom weights."""
        aggregator = SignalAggregator(
            sentiment_weight=0.4,
            quantum_weight=0.3,
            ai_weight=0.3
        )
        assert aggregator.sentiment_weight == 0.4
        assert aggregator.quantum_weight == 0.3
        assert aggregator.ai_weight == 0.3
    
    def test_weights_must_sum_to_one(self):
        """Test that weights must sum to 1.0."""
        with pytest.raises(ValueError):
            SignalAggregator(
                sentiment_weight=0.5,
                quantum_weight=0.3,
                ai_weight=0.1  # Sum = 0.9, not 1.0
            )
    
    def test_normalize_value(self):
        """Test value normalization."""
        aggregator = SignalAggregator()
        
        # Test normalization within bounds
        assert aggregator._normalize_value(0.5) == 0.5
        assert aggregator._normalize_value(-0.5) == -0.5
        
        # Test clamping
        assert aggregator._normalize_value(2.0) == 1.0
        assert aggregator._normalize_value(-2.0) == -1.0
    
    def test_aggregate_bullish_signal(self):
        """Test aggregation with bullish signals."""
        aggregator = SignalAggregator()
        
        # Strong bullish signal across all inputs
        signal = aggregator.aggregate_signals(
            sentiment_data=0.8,
            quantum_data=0.7,
            ai_prediction=0.9
        )
        
        assert signal.action == Action.BUY
        assert signal.confidence > 0.0
    
    def test_aggregate_bearish_signal(self):
        """Test aggregation with bearish signals."""
        aggregator = SignalAggregator()
        
        # Strong bearish signal across all inputs
        signal = aggregator.aggregate_signals(
            sentiment_data=-0.8,
            quantum_data=-0.7,
            ai_prediction=-0.9
        )
        
        assert signal.action == Action.SELL
        assert signal.confidence > 0.0
    
    def test_aggregate_neutral_signal(self):
        """Test aggregation with neutral signals."""
        aggregator = SignalAggregator()
        
        # Neutral signal
        signal = aggregator.aggregate_signals(
            sentiment_data=0.1,
            quantum_data=-0.1,
            ai_prediction=0.0
        )
        
        assert signal.action == Action.HOLD
    
    def test_veto_rule_negative_sentiment(self):
        """Test veto rule for strong negative sentiment."""
        aggregator = SignalAggregator()
        
        # Strong negative sentiment should trigger veto
        signal = aggregator.aggregate_signals(
            sentiment_data=-0.9,
            quantum_data=0.5,
            ai_prediction=0.5
        )
        
        # Should force HOLD or SELL, not BUY
        assert signal.action in [Action.HOLD, Action.SELL]
        assert "Veto" in signal.reason
    
    def test_veto_rule_positive_sentiment_ai_agreement(self):
        """Test veto rule for strong positive sentiment with AI agreement."""
        aggregator = SignalAggregator()
        
        # Strong positive sentiment with AI agreement
        signal = aggregator.aggregate_signals(
            sentiment_data=0.85,
            quantum_data=0.0,
            ai_prediction=0.7
        )
        
        assert signal.action == Action.BUY
        assert "Veto" in signal.reason
    
    def test_weighted_aggregation(self):
        """Test that weights are properly applied."""
        aggregator = SignalAggregator(
            sentiment_weight=0.0,
            quantum_weight=0.0,
            ai_weight=1.0  # Only AI matters
        )
        
        # Strong AI signal should dominate
        signal = aggregator.aggregate_signals(
            sentiment_data=-0.5,
            quantum_data=-0.5,
            ai_prediction=0.8
        )
        
        assert signal.action == Action.BUY
    
    def test_confidence_calculation(self):
        """Test confidence calculation based on signal strength."""
        aggregator = SignalAggregator()
        
        # Strong signal should have higher confidence
        strong_signal = aggregator.aggregate_signals(
            sentiment_data=0.9,
            quantum_data=0.9,
            ai_prediction=0.9
        )
        
        # Weak signal should have lower confidence
        weak_signal = aggregator.aggregate_signals(
            sentiment_data=0.4,
            quantum_data=0.3,
            ai_prediction=0.4
        )
        
        assert strong_signal.confidence > weak_signal.confidence
