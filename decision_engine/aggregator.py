"""
Signal Aggregator Module
Aggregates signals from sentiment analysis, quantum indicators, and AI predictions
to generate final trade decisions.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(Enum):
    """Trade action enumeration."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradeSignal:
    """
    Represents a final trade signal with action and confidence level.
    
    Attributes:
        action: The recommended trading action (BUY/SELL/HOLD)
        confidence: Confidence level between 0.0 and 1.0
        reason: Optional explanation for the signal
    """
    action: Action
    confidence: float
    reason: Optional[str] = None

    def __post_init__(self):
        """Validate confidence is within bounds."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")


class SignalAggregator:
    """
    Aggregates signals from multiple sources using weighted logic and veto rules.
    
    Weights:
        - Sentiment: 0.3
        - Quantum: 0.2
        - AI Prediction: 0.5
    
    Veto Rules:
        - If sentiment < -0.8, force SELL or HOLD
        - If sentiment > 0.8 and AI agrees, boost BUY confidence
    """
    
    def __init__(
        self,
        sentiment_weight: float = 0.3,
        quantum_weight: float = 0.2,
        ai_weight: float = 0.5
    ):
        """
        Initialize the signal aggregator with custom weights.
        
        Args:
            sentiment_weight: Weight for sentiment analysis (default: 0.3)
            quantum_weight: Weight for quantum indicators (default: 0.2)
            ai_weight: Weight for AI predictions (default: 0.5)
        
        Raises:
            ValueError: If weights don't sum to 1.0
        """
        total_weight = sentiment_weight + quantum_weight + ai_weight
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")
        
        self.sentiment_weight = sentiment_weight
        self.quantum_weight = quantum_weight
        self.ai_weight = ai_weight
    
    def _normalize_value(self, value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
        """
        Normalize a value to the range [-1, 1].
        
        Note: By default, assumes input is already in [-1, 1] range. If the input
        is already normalized, this acts as a validation and clamping operation.
        For inputs in a different range, provide the actual min_val and max_val.
        
        Args:
            value: The value to normalize
            min_val: Minimum expected value (default: -1.0)
            max_val: Maximum expected value (default: 1.0)
        
        Returns:
            Normalized value between -1 and 1
        """
        if min_val == max_val:
            return 0.0
        
        # Normalize to [0, 1] first
        normalized = (value - min_val) / (max_val - min_val)
        # Scale to [-1, 1]
        normalized = 2 * normalized - 1
        # Clamp to bounds
        return max(-1.0, min(1.0, normalized))
    
    def _apply_veto_rules(
        self,
        sentiment_data: float,
        quantum_data: float,
        ai_prediction: float,
        weighted_score: float
    ) -> tuple[Action, str]:
        """
        Apply veto rules to override normal aggregation logic.
        
        Args:
            sentiment_data: Normalized sentiment score [-1, 1]
            quantum_data: Normalized quantum score [-1, 1]
            ai_prediction: Normalized AI prediction [-1, 1]
            weighted_score: The calculated weighted score
        
        Returns:
            Tuple of (Action, reason) if veto applies, otherwise (None, None)
        """
        # Veto Rule 1: Strong negative sentiment forces SELL or HOLD
        if sentiment_data < -0.8:
            if weighted_score < -0.5:
                return Action.SELL, "Veto: Strong negative sentiment with negative overall signal"
            else:
                return Action.HOLD, "Veto: Strong negative sentiment prevents buying"
        
        # Veto Rule 2: Strong positive sentiment with AI agreement boosts BUY
        if sentiment_data > 0.8 and ai_prediction > 0.6:
            return Action.BUY, "Veto: Strong positive sentiment confirmed by AI"
        
        # Veto Rule 3: Extreme quantum divergence suggests HOLD
        if abs(quantum_data) > 0.9 and abs(quantum_data - weighted_score) > 0.5:
            return Action.HOLD, "Veto: Quantum indicator shows extreme divergence"
        
        return None, None
    
    def aggregate_signals(
        self,
        sentiment_data: float,
        quantum_data: float,
        ai_prediction: float
    ) -> TradeSignal:
        """
        Aggregate signals from multiple sources into a final trade decision.
        
        The method:
        1. Normalizes all inputs to [-1, 1] range
        2. Applies weighted aggregation
        3. Checks veto rules
        4. Determines action based on final score
        
        Args:
            sentiment_data: Sentiment analysis score (will be normalized)
            quantum_data: Quantum indicator score (will be normalized)
            ai_prediction: AI prediction score (will be normalized)
        
        Returns:
            TradeSignal with action, confidence, and reason
        """
        # Normalize inputs (assuming they might come in different ranges)
        # If already normalized, this is a no-op
        norm_sentiment = self._normalize_value(sentiment_data)
        norm_quantum = self._normalize_value(quantum_data)
        norm_ai = self._normalize_value(ai_prediction)
        
        # Calculate weighted score
        weighted_score = (
            norm_sentiment * self.sentiment_weight +
            norm_quantum * self.quantum_weight +
            norm_ai * self.ai_weight
        )
        
        # Apply veto rules
        veto_action, veto_reason = self._apply_veto_rules(
            norm_sentiment, norm_quantum, norm_ai, weighted_score
        )
        
        if veto_action is not None:
            # Veto rule triggered
            confidence = min(0.95, abs(weighted_score))  # Cap at 95% for veto decisions
            return TradeSignal(action=veto_action, confidence=confidence, reason=veto_reason)
        
        # Normal aggregation logic
        # Determine action based on weighted score thresholds
        if weighted_score > 0.3:
            action = Action.BUY
            reason = "Weighted score indicates bullish signal"
        elif weighted_score < -0.3:
            action = Action.SELL
            reason = "Weighted score indicates bearish signal"
        else:
            action = Action.HOLD
            reason = "Weighted score suggests neutral market"
        
        # Calculate confidence based on strength of signal
        confidence = min(1.0, abs(weighted_score))
        
        return TradeSignal(action=action, confidence=confidence, reason=reason)
