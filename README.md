# RLdC_AiNalyzator

A cryptocurrency trading analysis and backtesting framework.

## Features

### Backtesting Framework ✨

Test your trading strategies against historical data before risking real capital!

- **Historical Data Loading**: Fetch OHLCV data from exchanges using ccxt
- **Strategy Simulation**: Test custom trading logic on past market data
- **Performance Analytics**: Comprehensive metrics including returns, drawdown, Sharpe ratio, and win rate
- **Multiple Strategies**: Ready-to-use examples including SMA crossover, RSI, momentum, and more

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Run a Backtest

```bash
# Run the example SMA crossover strategy
python run_backtest.py

# Test with sample data (no internet required)
python test_backtest.py

# Compare multiple strategies
python test_strategies.py

# Run comprehensive tests
python test_framework.py
```

## Documentation

- **[Backtesting Framework Guide](BACKTESTING_README.md)** - Complete documentation for the backtesting system
- **[Example Strategies](example_strategies.py)** - Ready-to-use strategy implementations

## Project Structure

```
backtesting/              # Core backtesting framework
├── data_loader.py       # Historical data fetching and caching
├── engine.py            # Backtesting simulation engine
└── analytics.py         # Performance metrics calculation

example_strategies.py    # Example trading strategies
run_backtest.py          # Main runner script
test_backtest.py         # Quick test with sample data
test_strategies.py       # Strategy comparison tests
test_framework.py        # Comprehensive test suite
```

## Example Usage

```python
from backtesting import HistoricalDataLoader, Backtester
from backtesting.analytics import generate_report, print_report
from example_strategies import sma_crossover

# Load historical data
loader = HistoricalDataLoader()
data = loader.fetch_data('BTC/USDT', timeframe='1h', days_back=30)

# Run backtest
backtester = Backtester(initial_capital=10000, commission_rate=0.001)
strategy = sma_crossover(short_window=10, long_window=30)
results = backtester.run(data, strategy)

# View performance
report = generate_report(results['equity_curve'], results['trade_history'], 10000)
print_report(report)
```

## Available Strategies

1. **Buy and Hold** - Simple baseline strategy
2. **SMA Crossover** - Moving average crossover
3. **RSI Strategy** - Relative Strength Index based
4. **Momentum** - Trend following strategy
5. **Breakout** - Price breakout detection
6. **Mean Reversion** - Statistical reversion strategy

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is open source and available under the MIT License.