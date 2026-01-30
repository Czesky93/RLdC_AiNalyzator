# Backtesting Framework

A comprehensive backtesting framework for validating trading strategies against historical cryptocurrency data.

## Features

- **Historical Data Loading**: Fetch OHLCV data from exchanges using ccxt
- **Data Caching**: Save and load data locally to avoid rate limits
- **Strategy Simulation**: Run custom trading strategies on historical data
- **Commission Simulation**: Realistic trading costs with configurable commission rates
- **Performance Analytics**: Calculate key metrics including returns, drawdown, win rate, and Sharpe ratio
- **Trade History**: Track all buy/sell transactions and their profitability

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Run the Example Backtest

The repository includes a ready-to-run example with a Simple Moving Average (SMA) crossover strategy:

```bash
python run_backtest.py
```

This will:
- Fetch 30 days of BTC/USDT hourly data from Binance
- Run an SMA(10/30) crossover strategy
- Display performance metrics and recent trades

### 2. Test with Sample Data

For testing without live data access:

```bash
python test_backtest.py
```

## Usage Guide

### Loading Historical Data

```python
from backtesting import HistoricalDataLoader

# Initialize the data loader
loader = HistoricalDataLoader(exchange_id='binance')

# Fetch historical data
data = loader.fetch_data(
    symbol='BTC/USDT',
    timeframe='1h',      # 1m, 5m, 15m, 1h, 4h, 1d, etc.
    days_back=30
)

# Save data for later use
loader.save_to_csv('btc_data.csv')

# Load cached data
data = loader.load_from_csv('btc_data.csv')
```

### Creating a Strategy

A strategy is a function that takes a data row and returns a signal ('BUY', 'SELL', or 'HOLD'):

```python
def my_strategy():
    """Simple momentum strategy example."""
    prices = []
    in_position = False
    
    def strategy_logic(row):
        nonlocal in_position
        
        prices.append(row['close'])
        
        if len(prices) < 20:
            return 'HOLD'
        
        # Buy if price is above 20-period average
        avg = sum(prices[-20:]) / 20
        if row['close'] > avg * 1.02 and not in_position:
            in_position = True
            return 'BUY'
        elif row['close'] < avg * 0.98 and in_position:
            in_position = False
            return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic
```

### Running a Backtest

```python
from backtesting import Backtester
from backtesting.analytics import generate_report, print_report

# Initialize backtester
backtester = Backtester(
    initial_capital=10000.0,  # Starting capital in quote currency
    commission_rate=0.001      # 0.1% commission per trade
)

# Run the backtest
strategy = my_strategy()
results = backtester.run(data, strategy)

# Generate and display performance report
report = generate_report(
    results['equity_curve'],
    results['trade_history'],
    backtester.initial_capital
)

print_report(report)
```

### Performance Metrics

The framework calculates the following metrics:

- **Total Return**: Percentage gain/loss from initial capital
- **Maximum Drawdown**: Largest peak-to-valley decline
- **Sharpe Ratio**: Risk-adjusted return measure
- **Win Rate**: Percentage of profitable trades
- **Average PnL**: Mean profit/loss per trade
- **Number of Trades**: Total completed trades

### Accessing Results

```python
# Results dictionary contains:
results = {
    'equity_curve': pd.DataFrame,    # Portfolio value over time
    'trade_history': pd.DataFrame,   # All buy/sell transactions
    'final_value': float,            # Final portfolio value
    'initial_capital': float         # Starting capital
}

# Equity curve columns: timestamp, total_value, cash, asset_value
equity_curve = results['equity_curve']

# Trade history columns: timestamp, type, price, amount, commission, pnl, pnl_pct
trades = results['trade_history']
```

## Module Structure

```
backtesting/
├── __init__.py         # Package initialization
├── data_loader.py      # Historical data fetching and caching
├── engine.py           # Backtesting simulation engine
└── analytics.py        # Performance metrics calculation

run_backtest.py         # Example runner script
test_backtest.py        # Test script with sample data
requirements.txt        # Python dependencies
```

## Example Strategies

### 1. Simple Moving Average Crossover

```python
def sma_crossover(short_window=10, long_window=30):
    prices = []
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        if len(prices) < long_window:
            return 'HOLD'
        
        short_sma = sum(prices[-short_window:]) / short_window
        long_sma = sum(prices[-long_window:]) / long_window
        
        # Bullish crossover
        if short_sma > long_sma:
            return 'BUY'
        # Bearish crossover
        elif short_sma < long_sma:
            return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic
```

### 2. RSI Strategy

```python
def rsi_strategy(period=14, oversold=30, overbought=70):
    prices = []
    
    def calculate_rsi(prices, period):
        if len(prices) < period + 1:
            return 50
        
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(c, 0) for c in changes[-period:]]
        losses = [abs(min(c, 0)) for c in changes[-period:]]
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def strategy_logic(row):
        prices.append(row['close'])
        
        rsi = calculate_rsi(prices, period)
        
        if rsi < oversold:
            return 'BUY'
        elif rsi > overbought:
            return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic
```

## Best Practices

1. **Data Quality**: Always verify data quality before backtesting
2. **Avoid Overfitting**: Test strategies on multiple time periods
3. **Commission Costs**: Use realistic commission rates (0.1% - 0.2% typical)
4. **Slippage**: Consider adding slippage simulation for more realistic results
5. **Position Sizing**: The current implementation uses 100% of capital per trade
6. **Walk-Forward Testing**: Test on out-of-sample data
7. **Multiple Assets**: Test strategies across different cryptocurrencies

## Limitations

- **Single Asset**: Currently supports one trading pair at a time
- **Long Only**: Only supports long positions (buy and hold)
- **No Stop Loss**: No automatic stop-loss or take-profit orders
- **100% Position**: Uses all available capital for each trade
- **No Shorting**: Cannot simulate short positions

## Future Enhancements

- Support for multiple trading pairs
- Short position support
- Configurable position sizing (e.g., fixed amount, percentage)
- Stop-loss and take-profit orders
- Multiple position tracking
- Slippage simulation
- Advanced order types (limit, market, stop)
- Multi-timeframe analysis
- Parameter optimization
- Walk-forward analysis

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is open source and available under the MIT License.
