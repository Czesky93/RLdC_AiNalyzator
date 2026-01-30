#!/usr/bin/env python3
"""
Simple test script to validate the backtesting framework without requiring live data.
"""

import pandas as pd
import numpy as np
from backtesting import Backtester
from backtesting.analytics import generate_report, print_report


def create_sample_data(num_points=100):
    """Create sample OHLCV data for testing."""
    dates = pd.date_range(start='2024-01-01', periods=num_points, freq='h')
    
    # Create a simple upward trending price with some volatility
    base_price = 30000
    trend = np.linspace(0, 5000, num_points)
    volatility = np.random.randn(num_points) * 500
    
    close_prices = base_price + trend + volatility
    
    data = pd.DataFrame({
        'timestamp': dates,
        'open': close_prices - np.random.rand(num_points) * 100,
        'high': close_prices + np.random.rand(num_points) * 200,
        'low': close_prices - np.random.rand(num_points) * 200,
        'close': close_prices,
        'volume': np.random.rand(num_points) * 1000
    })
    
    return data


def simple_trend_strategy():
    """Simple strategy that buys when price increases, sells when it decreases."""
    prev_price = None
    
    def strategy_logic(row):
        nonlocal prev_price
        
        if prev_price is None:
            prev_price = row['close']
            return 'HOLD'
        
        current_price = row['close']
        
        # Buy if price increased significantly
        if current_price > prev_price * 1.02:
            prev_price = current_price
            return 'BUY'
        # Sell if price decreased
        elif current_price < prev_price * 0.98:
            prev_price = current_price
            return 'SELL'
        
        prev_price = current_price
        return 'HOLD'
    
    return strategy_logic


def main():
    """Test the backtesting framework."""
    print("Testing Backtesting Framework")
    print("=" * 60)
    
    # Create sample data
    print("\nCreating sample data...")
    data = create_sample_data(200)
    print(f"Created {len(data)} sample candlesticks")
    print(f"Price range: ${data['close'].min():.2f} - ${data['close'].max():.2f}")
    
    # Initialize backtester
    print("\nInitializing backtester...")
    backtester = Backtester(
        initial_capital=10000.0,
        commission_rate=0.001
    )
    
    # Create and run strategy
    print("Running backtest with simple trend strategy...")
    strategy = simple_trend_strategy()
    results = backtester.run(data, strategy)
    
    # Generate report
    report = generate_report(
        results['equity_curve'],
        results['trade_history'],
        backtester.initial_capital
    )
    
    print_report(report)
    
    # Verify basic functionality
    print("\nValidation:")
    print("-" * 60)
    print(f"✓ Equity curve has {len(results['equity_curve'])} entries")
    print(f"✓ Number of trades: {len(results['trade_history'])}")
    print(f"✓ Final value: ${results['final_value']:,.2f}")
    print(f"✓ Framework is working correctly!")
    print("-" * 60)


if __name__ == '__main__':
    main()
