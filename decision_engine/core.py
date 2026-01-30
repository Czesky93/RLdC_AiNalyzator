"""
Bot Kernel Module
Core orchestration layer that unifies all subsystems into a single acting entity.
"""

from typing import Optional, Dict, Any, Callable
from datetime import datetime
import logging
from .aggregator import SignalAggregator, TradeSignal
from .paper_trader import PaperTrader, Trade


class BotKernel:
    """
    Core bot kernel that orchestrates all trading subsystems.
    
    The kernel integrates:
    - Sentiment Analysis
    - Quantum Indicators
    - AI Predictions
    - Signal Aggregation
    - Paper Trading Execution
    
    And provides a unified step() method for running the complete trading cycle.
    """
    
    def __init__(
        self,
        sentiment_fetcher: Optional[Callable[[], float]] = None,
        quantum_fetcher: Optional[Callable[[], float]] = None,
        ai_predictor: Optional[Callable[[], float]] = None,
        price_fetcher: Optional[Callable[[], float]] = None,
        virtual_balance: float = 10000.0,
        sentiment_weight: float = 0.3,
        quantum_weight: float = 0.2,
        ai_weight: float = 0.5,
        fee_rate: float = 0.001,
        trade_percentage: float = 1.0
    ):
        """
        Initialize the bot kernel with subsystems.
        
        Args:
            sentiment_fetcher: Function to fetch sentiment data (returns float -1 to 1)
            quantum_fetcher: Function to fetch quantum indicators (returns float -1 to 1)
            ai_predictor: Function to get AI predictions (returns float -1 to 1)
            price_fetcher: Function to fetch current market price
            virtual_balance: Starting balance for paper trading (default: 10,000 USDT)
            sentiment_weight: Weight for sentiment in aggregation (default: 0.3)
            quantum_weight: Weight for quantum in aggregation (default: 0.2)
            ai_weight: Weight for AI in aggregation (default: 0.5)
            fee_rate: Trading fee rate (default: 0.001 = 0.1%)
            trade_percentage: Percentage of funds to use per trade (default: 1.0 = 100%)
        """
        # Initialize subsystems
        self.aggregator = SignalAggregator(
            sentiment_weight=sentiment_weight,
            quantum_weight=quantum_weight,
            ai_weight=ai_weight
        )
        self.paper_trader = PaperTrader(
            virtual_balance=virtual_balance,
            fee_rate=fee_rate
        )
        
        # Store data fetchers
        self.sentiment_fetcher = sentiment_fetcher
        self.quantum_fetcher = quantum_fetcher
        self.ai_predictor = ai_predictor
        self.price_fetcher = price_fetcher
        
        # Trading parameters
        self.trade_percentage = trade_percentage
        
        # Logging
        self.logger = logging.getLogger(self.__class__.__name__)
        self.step_count = 0
        
        # Cache for latest data
        self._latest_sentiment = None
        self._latest_quantum = None
        self._latest_ai = None
        self._latest_price = None
        self._latest_signal = None
    
    def _fetch_sentiment_data(self) -> float:
        """
        Fetch sentiment data from the sentiment analysis subsystem.
        
        Returns:
            Sentiment score (normalized to -1 to 1)
        """
        if self.sentiment_fetcher is None:
            self.logger.warning("No sentiment fetcher configured, using default value 0.0")
            return 0.0
        
        try:
            sentiment = self.sentiment_fetcher()
            self._latest_sentiment = sentiment
            self.logger.debug(f"Fetched sentiment data: {sentiment:.4f}")
            return sentiment
        except Exception as e:
            self.logger.error(f"Error fetching sentiment data: {e}")
            return 0.0
    
    def _fetch_quantum_data(self) -> float:
        """
        Fetch quantum indicator data.
        
        Returns:
            Quantum indicator score (normalized to -1 to 1)
        """
        if self.quantum_fetcher is None:
            self.logger.warning("No quantum fetcher configured, using default value 0.0")
            return 0.0
        
        try:
            quantum = self.quantum_fetcher()
            self._latest_quantum = quantum
            self.logger.debug(f"Fetched quantum data: {quantum:.4f}")
            return quantum
        except Exception as e:
            self.logger.error(f"Error fetching quantum data: {e}")
            return 0.0
    
    def _fetch_ai_prediction(self) -> float:
        """
        Fetch AI prediction data.
        
        Returns:
            AI prediction score (normalized to -1 to 1)
        """
        if self.ai_predictor is None:
            self.logger.warning("No AI predictor configured, using default value 0.0")
            return 0.0
        
        try:
            prediction = self.ai_predictor()
            self._latest_ai = prediction
            self.logger.debug(f"Fetched AI prediction: {prediction:.4f}")
            return prediction
        except Exception as e:
            self.logger.error(f"Error fetching AI prediction: {e}")
            return 0.0
    
    def _fetch_current_price(self) -> float:
        """
        Fetch current market price.
        
        Returns:
            Current price (must be > 0)
        """
        if self.price_fetcher is None:
            self.logger.warning("No price fetcher configured, using default value 1.0")
            return 1.0
        
        try:
            price = self.price_fetcher()
            if price <= 0:
                self.logger.error(f"Invalid price received: {price}, using cached or default")
                return self._latest_price if self._latest_price is not None else 1.0
            
            self._latest_price = price
            self.logger.debug(f"Fetched current price: {price:.2f}")
            return price
        except Exception as e:
            self.logger.error(f"Error fetching current price: {e}")
            return self._latest_price if self._latest_price is not None else 1.0
    
    def step(self) -> Dict[str, Any]:
        """
        Execute one complete trading cycle.
        
        Steps:
        1. Fetch data from all sources (Sentiment, Quantum, AI, Price)
        2. Aggregate signals using the SignalAggregator
        3. Execute trade using PaperTrader (if applicable)
        4. Log results
        
        Returns:
            Dictionary containing step results:
            - step: Step number
            - timestamp: Execution timestamp
            - sentiment: Sentiment score
            - quantum: Quantum indicator score
            - ai: AI prediction score
            - price: Current market price
            - signal: Generated TradeSignal
            - trade: Executed Trade (if any)
            - portfolio_value: Current portfolio value
            - profit_loss: Profit/loss statistics
        """
        self.step_count += 1
        timestamp = datetime.now()
        
        self.logger.info(f"=== Step {self.step_count} started at {timestamp} ===")
        
        # Step 1: Fetch data
        self.logger.info("Fetching data from all sources...")
        sentiment = self._fetch_sentiment_data()
        quantum = self._fetch_quantum_data()
        ai_prediction = self._fetch_ai_prediction()
        current_price = self._fetch_current_price()
        
        self.logger.info(f"Data fetched - Sentiment: {sentiment:.4f}, "
                        f"Quantum: {quantum:.4f}, AI: {ai_prediction:.4f}, "
                        f"Price: {current_price:.2f}")
        
        # Step 2: Aggregate signals
        self.logger.info("Aggregating signals...")
        signal = self.aggregator.aggregate_signals(
            sentiment_data=sentiment,
            quantum_data=quantum,
            ai_prediction=ai_prediction
        )
        self._latest_signal = signal
        
        self.logger.info(f"Signal generated - Action: {signal.action.value}, "
                        f"Confidence: {signal.confidence:.2f}, "
                        f"Reason: {signal.reason}")
        
        # Step 3: Execute trade (paper trading)
        self.logger.info("Executing trade order...")
        trade = self.paper_trader.execute_order(
            signal=signal,
            current_price=current_price,
            trade_percentage=self.trade_percentage
        )
        
        if trade:
            self.logger.info(f"Trade executed - {trade.action.value} {trade.amount:.6f} "
                           f"at {trade.price:.2f}, Fee: {trade.fee:.2f}, "
                           f"Balance: {trade.balance_after:.2f}, "
                           f"Holdings: {trade.holdings_after:.6f}")
        else:
            self.logger.info(f"No trade executed (action was {signal.action.value})")
        
        # Step 4: Calculate portfolio metrics
        portfolio_value = self.paper_trader.get_portfolio_value(current_price)
        profit_loss = self.paper_trader.get_profit_loss(current_price)
        
        self.logger.info(f"Portfolio - Value: {portfolio_value:.2f}, "
                        f"P/L: {profit_loss['absolute']:.2f} "
                        f"({profit_loss['percentage']:.2f}%)")
        
        self.logger.info(f"=== Step {self.step_count} completed ===\n")
        
        # Return comprehensive step results
        return {
            'step': self.step_count,
            'timestamp': timestamp,
            'sentiment': sentiment,
            'quantum': quantum,
            'ai': ai_prediction,
            'price': current_price,
            'signal': signal,
            'trade': trade,
            'portfolio_value': portfolio_value,
            'profit_loss': profit_loss
        }
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current bot status and statistics.
        
        Returns:
            Dictionary with bot status information
        """
        current_price = self._latest_price if self._latest_price is not None else 0.0
        
        return {
            'step_count': self.step_count,
            'latest_sentiment': self._latest_sentiment,
            'latest_quantum': self._latest_quantum,
            'latest_ai': self._latest_ai,
            'latest_price': self._latest_price,
            'latest_signal': self._latest_signal,
            'portfolio_value': self.paper_trader.get_portfolio_value(current_price),
            'profit_loss': self.paper_trader.get_profit_loss(current_price),
            'trade_summary': self.paper_trader.get_trade_summary()
        }
    
    def reset(self, new_balance: Optional[float] = None):
        """
        Reset the bot to initial state.
        
        Args:
            new_balance: New starting balance (optional)
        """
        self.logger.info("Resetting bot kernel...")
        self.paper_trader.reset(new_balance)
        self.step_count = 0
        self._latest_sentiment = None
        self._latest_quantum = None
        self._latest_ai = None
        self._latest_price = None
        self._latest_signal = None
        self.logger.info("Bot kernel reset complete")
