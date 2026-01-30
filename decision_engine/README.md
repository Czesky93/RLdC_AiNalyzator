# Decision Engine Module

A comprehensive decision-making and paper trading system for algorithmic trading. This module aggregates signals from multiple sources (Sentiment Analysis, Quantum Indicators, AI Predictions) and executes trades in a safe paper trading environment.

## Features

- **Multi-Source Signal Aggregation**: Combines sentiment analysis, quantum indicators, and AI predictions with customizable weights
- **Intelligent Veto Rules**: Override normal logic when extreme conditions are detected
- **Paper Trading**: Risk-free simulation with realistic fee modeling
- **Complete Bot Orchestration**: Unified kernel for running full trading cycles
- **Comprehensive Logging**: Track every decision and trade execution

## Architecture

The module consists of three main components:

1. **SignalAggregator** (`decision_engine/aggregator.py`)
   - Aggregates signals from multiple sources
   - Applies weighted logic (default: Sentiment=30%, Quantum=20%, AI=50%)
   - Implements veto rules for extreme market conditions
   - Returns TradeSignal with action (BUY/SELL/HOLD) and confidence (0.0-1.0)

2. **PaperTrader** (`decision_engine/paper_trader.py`)
   - Simulates trading with virtual balance (default: 10,000 USDT)
   - Tracks balance, asset holdings, and trade history
   - Simulates trading fees (default: 0.1%)
   - Provides profit/loss tracking and trade summaries

3. **BotKernel** (`decision_engine/core.py`)
   - Orchestrates all sub-systems
   - Implements complete trading cycle: Fetch Data → Aggregate → Execute → Log
   - Handles errors gracefully
   - Provides status and reset capabilities

## Installation

```bash
# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### Basic Signal Aggregation

```python
from decision_engine import SignalAggregator

# Create aggregator with default weights
aggregator = SignalAggregator()

# Aggregate signals from multiple sources
signal = aggregator.aggregate_signals(
    sentiment_data=0.7,   # Bullish sentiment
    quantum_data=0.5,     # Moderate quantum signal
    ai_prediction=0.8     # Strong AI prediction
)

print(f"Action: {signal.action.value}")           # BUY
print(f"Confidence: {signal.confidence:.2f}")     # 0.68
print(f"Reason: {signal.reason}")
```

### Paper Trading

```python
from decision_engine import PaperTrader, TradeSignal
from decision_engine.aggregator import Action

# Initialize paper trader with 10,000 USDT
trader = PaperTrader(virtual_balance=10000.0)

# Execute a buy order
buy_signal = TradeSignal(action=Action.BUY, confidence=0.8)
trade = trader.execute_order(buy_signal, current_price=100.0)

# Execute a sell order
sell_signal = TradeSignal(action=Action.SELL, confidence=0.7)
trade = trader.execute_order(sell_signal, current_price=120.0)

# Get profit/loss
pl = trader.get_profit_loss(current_price=120.0)
print(f"Profit: ${pl['absolute']:.2f} ({pl['percentage']:.2f}%)")
```

### Full Bot Integration

```python
from decision_engine import BotKernel

# Define data fetchers
def get_sentiment():
    return 0.7  # Your sentiment analysis

def get_quantum():
    return 0.5  # Your quantum indicators

def get_ai_prediction():
    return 0.8  # Your AI model prediction

def get_price():
    return 100.0  # Current market price

# Initialize bot kernel
bot = BotKernel(
    sentiment_fetcher=get_sentiment,
    quantum_fetcher=get_quantum,
    ai_predictor=get_ai_prediction,
    price_fetcher=get_price,
    virtual_balance=10000.0
)

# Execute one trading cycle
result = bot.step()

print(f"Signal: {result['signal'].action.value}")
print(f"Portfolio Value: ${result['portfolio_value']:.2f}")
print(f"Profit/Loss: ${result['profit_loss']['absolute']:.2f}")
```

## Configuration

### Custom Signal Weights

```python
aggregator = SignalAggregator(
    sentiment_weight=0.4,  # 40% weight
    quantum_weight=0.3,    # 30% weight
    ai_weight=0.3          # 30% weight
)
```

### Custom Trading Parameters

```python
trader = PaperTrader(
    virtual_balance=50000.0,    # Start with 50,000 USDT
    fee_rate=0.002,              # 0.2% trading fee
    min_trade_amount=20.0        # Minimum 20 USDT per trade
)

bot = BotKernel(
    virtual_balance=10000.0,
    trade_percentage=0.5,        # Use only 50% of available funds per trade
    fee_rate=0.001
)
```

## Veto Rules

The system implements intelligent veto rules that override normal aggregation logic:

1. **Strong Negative Sentiment** (sentiment < -0.8): Forces SELL or HOLD, prevents buying
2. **Strong Positive Sentiment + AI Agreement** (sentiment > 0.8 and AI > 0.6): Forces BUY
3. **Extreme Quantum Divergence** (|quantum| > 0.9 with large divergence): Forces HOLD

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
pytest tests/ -v

# Run specific test module
pytest tests/test_aggregator.py -v
pytest tests/test_paper_trader.py -v
pytest tests/test_core.py -v
```

## Demo

Run the demo script to see all components in action:

```bash
python demo.py
```

The demo includes:
1. Signal aggregation with various scenarios
2. Paper trading simulation with multiple trades
3. Full bot kernel with 10-step market simulation

## API Reference

### SignalAggregator

```python
class SignalAggregator:
    def __init__(self, sentiment_weight=0.3, quantum_weight=0.2, ai_weight=0.5)
    def aggregate_signals(sentiment_data, quantum_data, ai_prediction) -> TradeSignal
```

### PaperTrader

```python
class PaperTrader:
    def __init__(self, virtual_balance=10000.0, fee_rate=0.001, min_trade_amount=10.0)
    def execute_order(signal, current_price, trade_percentage=1.0) -> Optional[Trade]
    def get_portfolio_value(current_price) -> float
    def get_profit_loss(current_price) -> Dict
    def get_trade_summary() -> Dict
    def reset(new_balance=None)
```

### BotKernel

```python
class BotKernel:
    def __init__(self, sentiment_fetcher=None, quantum_fetcher=None, 
                 ai_predictor=None, price_fetcher=None, **kwargs)
    def step() -> Dict
    def get_status() -> Dict
    def reset(new_balance=None)
```

## License

This module is part of the RLdC_AiNalyzator project.

## Contributing

Contributions are welcome! Please ensure all tests pass before submitting:

```bash
pytest tests/
```
