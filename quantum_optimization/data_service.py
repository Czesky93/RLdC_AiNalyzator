"""
Real Market Data Service using CCXT
Fetches live OHLCV data from cryptocurrency exchanges and computes
expected returns and covariance matrices for portfolio optimization.
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_market_data(symbols, days=90, exchange_name='binance'):
    """
    Fetch real market data from a cryptocurrency exchange.
    
    Args:
        symbols: List of trading pairs (e.g., ['BTC/USDT', 'ETH/USDT'])
        days: Number of days of historical data to fetch (default: 90)
        exchange_name: Name of the exchange to use (default: 'binance')
    
    Returns:
        tuple: (expected_returns, covariance_matrix)
            - expected_returns: numpy array of mean historical returns
            - covariance_matrix: numpy array of return covariances
    """
    print(f"Fetching market data from {exchange_name} for {len(symbols)} symbols...")
    
    # Initialize exchange
    exchange_class = getattr(ccxt, exchange_name)
    exchange = exchange_class({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot'
        }
    })
    
    # Calculate timeframe
    since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
    
    # Fetch OHLCV data for each symbol
    price_data = {}
    
    for symbol in symbols:
        try:
            print(f"  Fetching {symbol}...")
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', since=since, limit=days)
            
            if not ohlcv:
                print(f"  Warning: No data received for {symbol}")
                continue
                
            # Convert to DataFrame
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Store closing prices
            price_data[symbol] = df['close']
            print(f"  ✓ Fetched {len(df)} data points for {symbol}")
            
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
            continue
    
    if not price_data:
        raise ValueError("No market data could be fetched. Please check symbols and exchange.")
    
    # Create combined DataFrame with all closing prices
    prices_df = pd.DataFrame(price_data)
    
    # Handle missing data
    prices_df = prices_df.fillna(method='ffill').fillna(method='bfill')
    
    # Calculate daily returns
    returns_df = prices_df.pct_change().dropna()
    
    print(f"\nCalculating risk/return metrics from {len(returns_df)} days of data...")
    
    # Calculate expected returns (mean of historical returns)
    expected_returns = returns_df.mean().values
    
    # Calculate covariance matrix (risk)
    covariance_matrix = returns_df.cov().values
    
    print(f"Expected returns: {expected_returns}")
    print(f"Covariance matrix shape: {covariance_matrix.shape}")
    
    return expected_returns, covariance_matrix, list(prices_df.columns)


def validate_data(expected_returns, covariance_matrix):
    """
    Validate that the market data is suitable for optimization.
    
    Args:
        expected_returns: numpy array of expected returns
        covariance_matrix: numpy array of covariances
    
    Raises:
        ValueError: If data is invalid
    """
    if len(expected_returns) == 0:
        raise ValueError("Expected returns array is empty")
    
    if covariance_matrix.shape[0] != covariance_matrix.shape[1]:
        raise ValueError("Covariance matrix must be square")
    
    if len(expected_returns) != covariance_matrix.shape[0]:
        raise ValueError("Dimensions of returns and covariance matrix don't match")
    
    if not np.allclose(covariance_matrix, covariance_matrix.T):
        # Ensure symmetry
        covariance_matrix = (covariance_matrix + covariance_matrix.T) / 2
    
    print("✓ Data validation passed")
    return True
