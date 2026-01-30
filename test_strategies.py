#!/usr/bin/env python3
"""
Test different strategies from example_strategies.py
"""

import pandas as pd
import numpy as np
from backtesting import Backtester
from backtesting.analytics import generate_report, print_report
from example_strategies import (
    sma_crossover, 
    rsi_strategy, 
    momentum_strategy,
    buy_and_hold,
    mean_reversion_strategy
)


def create_trending_data(num_points=200):
    """Create sample data with an upward trend."""
    dates = pd.date_range(start='2024-01-01', periods=num_points, freq='h')
    
    # Create trending price data
    base_price = 30000
    trend = np.linspace(0, 8000, num_points)
    volatility = np.random.randn(num_points) * 300
    
    close_prices = base_price + trend + volatility
    open_prices = close_prices - np.random.randn(num_points) * 50
    
    data = pd.DataFrame({
        'timestamp': dates,
        'open': open_prices,
        'high': np.maximum(open_prices, close_prices) + np.random.rand(num_points) * 200,
        'low': np.minimum(open_prices, close_prices) - np.random.rand(num_points) * 200,
        'close': close_prices,
        'volume': np.random.rand(num_points) * 1000
    })
    
    return data


def test_strategy(name, strategy, data, initial_capital=10000):
    """Test a single strategy and return results."""
    print(f"\nTesting: {name}")
    print("-" * 60)
    
    backtester = Backtester(
        initial_capital=initial_capital,
        commission_rate=0.001
    )
    
    results = backtester.run(data, strategy)
    
    report = generate_report(
        results['equity_curve'],
        results['trade_history'],
        initial_capital
    )
    
    # Print key metrics
    print(f"Total Return:  {report['total_return_pct']:>8.2f}%")
    print(f"Max Drawdown:  {report['max_drawdown_pct']:>8.2f}%")
    print(f"Sharpe Ratio:  {report['sharpe_ratio']:>8.2f}")
    print(f"Win Rate:      {report['win_rate_pct']:>8.2f}%")
    print(f"Num Trades:    {report['num_trades']:>8}")
    
    return report


def main():
    """Test multiple strategies."""
    print("=" * 60)
    print("STRATEGY COMPARISON TEST")
    print("=" * 60)
    
    # Create sample data
    print("\nGenerating sample market data...")
    data = create_trending_data(300)
    print(f"Created {len(data)} candles")
    print(f"Price range: ${data['close'].min():.2f} - ${data['close'].max():.2f}")
    
    # Test different strategies
    strategies = [
        ("Buy and Hold", buy_and_hold()),
        ("SMA Crossover (10/30)", sma_crossover(10, 30)),
        ("SMA Crossover (20/50)", sma_crossover(20, 50)),
        ("RSI (14, 30/70)", rsi_strategy(14, 30, 70)),
        ("Momentum (20 periods, 2%)", momentum_strategy(20, 0.02)),
        ("Mean Reversion (20, 2σ)", mean_reversion_strategy(20, 2.0)),
    ]
    
    results = []
    for name, strategy in strategies:
        report = test_strategy(name, strategy, data)
        results.append((name, report))
    
    # Summary comparison
    print("\n" + "=" * 60)
    print("SUMMARY COMPARISON")
    print("=" * 60)
    print(f"{'Strategy':<30} {'Return %':>10} {'Trades':>8} {'Win %':>8}")
    print("-" * 60)
    
    for name, report in results:
        print(f"{name:<30} {report['total_return_pct']:>10.2f} {report['num_trades']:>8} {report['win_rate_pct']:>8.2f}")
    
    print("=" * 60)
    
    # Find best strategy
    best_strategy = max(results, key=lambda x: x[1]['total_return_pct'])
    print(f"\nBest performing: {best_strategy[0]}")
    print(f"Return: {best_strategy[1]['total_return_pct']:.2f}%")


if __name__ == '__main__':
    main()
