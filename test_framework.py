#!/usr/bin/env python3
"""
Comprehensive test suite for the backtesting framework.

This script validates all major components of the framework.
"""

import pandas as pd
import numpy as np
from backtesting import HistoricalDataLoader, Backtester
from backtesting.analytics import (
    calculate_total_return,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_sharpe_ratio,
    generate_report,
    print_report
)
from example_strategies import sma_crossover, buy_and_hold


def create_test_data():
    """Create sample OHLCV data for testing."""
    dates = pd.date_range(start='2024-01-01', periods=100, freq='h')
    base_price = 30000
    
    close_prices = base_price + np.cumsum(np.random.randn(100) * 100)
    
    data = pd.DataFrame({
        'timestamp': dates,
        'open': close_prices - np.random.rand(100) * 50,
        'high': close_prices + np.random.rand(100) * 100,
        'low': close_prices - np.random.rand(100) * 100,
        'close': close_prices,
        'volume': np.random.rand(100) * 1000
    })
    
    return data


def test_data_loader():
    """Test the HistoricalDataLoader class."""
    print("\n" + "="*60)
    print("TEST 1: Data Loader")
    print("="*60)
    
    # Create a data loader
    loader = HistoricalDataLoader()
    assert loader is not None, "Failed to create data loader"
    print("✓ Data loader created successfully")
    
    # Create sample data
    data = create_test_data()
    loader.data = data
    
    # Test save/load functionality
    test_file = '/tmp/test_data.csv'
    loader.save_to_csv(test_file)
    print(f"✓ Data saved to {test_file}")
    
    loaded_data = loader.load_from_csv(test_file)
    assert len(loaded_data) == len(data), "Data length mismatch after save/load"
    print(f"✓ Data loaded successfully ({len(loaded_data)} rows)")
    
    # Verify data types
    assert loaded_data['close'].dtype == float, "Close price is not float"
    assert isinstance(loaded_data['timestamp'].iloc[0], pd.Timestamp), "Timestamp type incorrect"
    print("✓ Data types are correct")
    
    print("\nData Loader: PASSED ✓")
    return True


def test_backtester():
    """Test the Backtester class."""
    print("\n" + "="*60)
    print("TEST 2: Backtester")
    print("="*60)
    
    # Create backtester
    backtester = Backtester(initial_capital=10000, commission_rate=0.001)
    assert backtester.initial_capital == 10000, "Initial capital not set correctly"
    assert backtester.commission_rate == 0.001, "Commission rate not set correctly"
    print("✓ Backtester initialized correctly")
    
    # Create test data and strategy
    data = create_test_data()
    strategy = buy_and_hold()
    
    # Run backtest
    results = backtester.run(data, strategy)
    assert 'equity_curve' in results, "Missing equity_curve in results"
    assert 'trade_history' in results, "Missing trade_history in results"
    assert 'final_value' in results, "Missing final_value in results"
    print("✓ Backtest executed successfully")
    
    # Verify equity curve
    assert len(results['equity_curve']) == len(data), "Equity curve length incorrect"
    print(f"✓ Equity curve has {len(results['equity_curve'])} entries")
    
    # Verify trade history
    if len(results['trade_history']) > 0:
        assert 'type' in results['trade_history'].columns, "Missing 'type' in trade history"
        assert 'price' in results['trade_history'].columns, "Missing 'price' in trade history"
        print(f"✓ Trade history has {len(results['trade_history'])} trades")
    else:
        print("✓ Trade history is empty (no trades executed)")
    
    print("\nBacktester: PASSED ✓")
    return True


def test_analytics():
    """Test the analytics functions."""
    print("\n" + "="*60)
    print("TEST 3: Performance Analytics")
    print("="*60)
    
    # Create sample backtest results
    data = create_test_data()
    backtester = Backtester(initial_capital=10000)
    strategy = sma_crossover(5, 10)
    results = backtester.run(data, strategy)
    
    equity_curve = results['equity_curve']
    trade_history = results['trade_history']
    initial_capital = backtester.initial_capital
    
    # Test total return
    total_return = calculate_total_return(equity_curve, initial_capital)
    assert isinstance(total_return, (int, float)), "Total return is not numeric"
    print(f"✓ Total return calculated: {total_return:.2f}%")
    
    # Test max drawdown
    max_drawdown = calculate_max_drawdown(equity_curve)
    assert isinstance(max_drawdown, (int, float)), "Max drawdown is not numeric"
    assert max_drawdown >= 0, "Max drawdown should be non-negative"
    print(f"✓ Max drawdown calculated: {max_drawdown:.2f}%")
    
    # Test win rate
    win_rate = calculate_win_rate(trade_history)
    assert isinstance(win_rate, (int, float)), "Win rate is not numeric"
    assert 0 <= win_rate <= 100, "Win rate should be between 0 and 100"
    print(f"✓ Win rate calculated: {win_rate:.2f}%")
    
    # Test Sharpe ratio
    sharpe = calculate_sharpe_ratio(equity_curve)
    assert isinstance(sharpe, (int, float)), "Sharpe ratio is not numeric"
    print(f"✓ Sharpe ratio calculated: {sharpe:.2f}")
    
    # Test generate_report
    report = generate_report(equity_curve, trade_history, initial_capital)
    required_keys = ['initial_capital', 'final_value', 'total_return_pct', 
                     'max_drawdown_pct', 'sharpe_ratio', 'win_rate_pct', 
                     'num_trades', 'avg_pnl', 'avg_pnl_pct']
    
    for key in required_keys:
        assert key in report, f"Missing key '{key}' in report"
    print("✓ Report contains all required metrics")
    
    print("\nPerformance Analytics: PASSED ✓")
    return True


def test_strategies():
    """Test the example strategies."""
    print("\n" + "="*60)
    print("TEST 4: Example Strategies")
    print("="*60)
    
    data = create_test_data()
    backtester = Backtester(initial_capital=10000)
    
    # Test SMA crossover
    strategy = sma_crossover(5, 10)
    results = backtester.run(data, strategy)
    assert results is not None, "SMA strategy failed"
    print("✓ SMA crossover strategy works")
    
    # Test buy and hold
    strategy = buy_and_hold()
    results = backtester.run(data, strategy)
    assert results is not None, "Buy and hold strategy failed"
    print("✓ Buy and hold strategy works")
    
    print("\nExample Strategies: PASSED ✓")
    return True


def test_integration():
    """Test full integration of all components."""
    print("\n" + "="*60)
    print("TEST 5: Full Integration")
    print("="*60)
    
    # Create and save data
    loader = HistoricalDataLoader()
    data = create_test_data()
    loader.data = data
    
    test_file = '/tmp/integration_test.csv'
    loader.save_to_csv(test_file)
    print("✓ Data created and saved")
    
    # Load data
    loaded_data = loader.load_from_csv(test_file)
    print("✓ Data loaded")
    
    # Run backtest
    backtester = Backtester(initial_capital=10000, commission_rate=0.001)
    strategy = sma_crossover(10, 20)
    results = backtester.run(loaded_data, strategy)
    print("✓ Backtest executed")
    
    # Generate report
    report = generate_report(
        results['equity_curve'],
        results['trade_history'],
        backtester.initial_capital
    )
    print("✓ Report generated")
    
    # Display report
    print("\nSample Report:")
    print_report(report)
    
    print("Full Integration: PASSED ✓")
    return True


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("BACKTESTING FRAMEWORK - COMPREHENSIVE TEST SUITE")
    print("="*60)
    
    tests = [
        test_data_loader,
        test_backtester,
        test_analytics,
        test_strategies,
        test_integration
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(('PASS', test.__name__))
        except Exception as e:
            results.append(('FAIL', test.__name__, str(e)))
            print(f"\nERROR: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results if r[0] == 'PASS')
    failed = len(results) - passed
    
    for result in results:
        status = result[0]
        test_name = result[1]
        symbol = "✓" if status == "PASS" else "✗"
        print(f"{symbol} {test_name}: {status}")
    
    print("="*60)
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print("="*60)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! Framework is ready to use.")
        return 0
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review.")
        return 1


if __name__ == '__main__':
    exit(main())
