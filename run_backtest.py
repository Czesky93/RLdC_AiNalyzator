#!/usr/bin/env python3
"""
Runner script for backtesting trading strategies.

This script demonstrates how to use the backtesting framework with a simple
Moving Average crossover strategy.
"""

import pandas as pd
from backtesting import HistoricalDataLoader, Backtester
from backtesting.analytics import generate_report, print_report


def simple_sma_strategy(short_window: int = 10, long_window: int = 30):
    """
    Create a Simple Moving Average crossover strategy.
    
    Args:
        short_window: Period for short-term SMA
        long_window: Period for long-term SMA
        
    Returns:
        Strategy function that can be used with Backtester
    """
    sma_short = []
    sma_long = []
    prices = []
    
    def strategy_logic(row):
        """Strategy logic for SMA crossover."""
        prices.append(row['close'])
        
        # Calculate SMAs
        if len(prices) >= long_window:
            sma_short_val = sum(prices[-short_window:]) / short_window
            sma_long_val = sum(prices[-long_window:]) / long_window
            sma_short.append(sma_short_val)
            sma_long.append(sma_long_val)
            
            # Generate signals
            if len(sma_short) >= 2:
                # Bullish crossover: short SMA crosses above long SMA
                if sma_short[-2] <= sma_long[-2] and sma_short[-1] > sma_long[-1]:
                    return 'BUY'
                # Bearish crossover: short SMA crosses below long SMA
                elif sma_short[-2] >= sma_long[-2] and sma_short[-1] < sma_long[-1]:
                    return 'SELL'
        
        return 'HOLD'
    
    return strategy_logic


def main():
    """Main function to run the backtest."""
    print("Starting Backtest...")
    print("-" * 60)
    
    # Configuration
    symbol = 'BTC/USDT'
    timeframe = '1h'
    days_back = 30
    initial_capital = 10000.0
    commission_rate = 0.001  # 0.1%
    
    print(f"Symbol: {symbol}")
    print(f"Timeframe: {timeframe}")
    print(f"Days Back: {days_back}")
    print(f"Initial Capital: ${initial_capital:,.2f}")
    print(f"Commission Rate: {commission_rate*100}%")
    print("-" * 60)
    
    # Load historical data
    print("\nFetching historical data...")
    data_loader = HistoricalDataLoader(exchange_id='binance')
    
    try:
        data = data_loader.fetch_data(symbol, timeframe, days_back)
        print(f"Fetched {len(data)} candlesticks")
        
        # Save data for future use
        csv_filename = f"btc_usdt_{timeframe}_{days_back}d.csv"
        data_loader.save_to_csv(csv_filename)
        print(f"Saved data to {csv_filename}")
        
    except Exception as e:
        print(f"Error fetching data: {e}")
        print("Trying to load from cached file...")
        try:
            data = data_loader.load_from_csv(csv_filename)
            print(f"Loaded {len(data)} candlesticks from cache")
        except:
            print("No cached data available. Exiting.")
            return
    
    # Initialize backtester
    print("\nInitializing backtester...")
    backtester = Backtester(
        initial_capital=initial_capital,
        commission_rate=commission_rate
    )
    
    # Create strategy
    print("Creating SMA crossover strategy (10/30)...")
    strategy = simple_sma_strategy(short_window=10, long_window=30)
    
    # Run backtest
    print("Running backtest...")
    results = backtester.run(data, strategy)
    
    # Generate and print report
    report = generate_report(
        results['equity_curve'],
        results['trade_history'],
        initial_capital
    )
    
    print_report(report)
    
    # Show some trade details
    if not results['trade_history'].empty:
        print("Recent Trades:")
        print("-" * 60)
        trade_df = results['trade_history'].tail(10)
        for idx, trade in trade_df.iterrows():
            trade_type = trade['type']
            timestamp = trade['timestamp']
            price = trade['price']
            if trade_type == 'BUY':
                print(f"{timestamp} | BUY  @ ${price:,.2f}")
            else:
                pnl = trade.get('pnl', 0)
                pnl_pct = trade.get('pnl_pct', 0)
                print(f"{timestamp} | SELL @ ${price:,.2f} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")
        print("-" * 60)
    else:
        print("No trades executed during the backtest period.")


if __name__ == '__main__':
    main()
