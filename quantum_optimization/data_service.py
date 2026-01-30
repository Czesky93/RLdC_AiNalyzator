"""
Real Market Data Service using CCXT
Fetches live OHLCV data from cryptocurrency exchanges and computes
expected returns and covariance matrices for portfolio optimization.
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings


def fetch_market_data(symbols, days=90, exchange_name='binance', use_demo_on_fail=True):
    """
    Fetch real market data from a cryptocurrency exchange.
    
    Args:
        symbols: List of trading pairs (e.g., ['BTC/USDT', 'ETH/USDT'])
        days: Number of days of historical data to fetch (default: 90)
        exchange_name: Name of the exchange to use (default: 'binance')
        use_demo_on_fail: If True, use demo data when live fetch fails (default: True)
    
    Returns:
        tuple: (expected_returns, covariance_matrix, symbol_names)
            - expected_returns: numpy array of mean historical returns
            - covariance_matrix: numpy array of return covariances
            - symbol_names: list of symbol names matching the data
    """
    print(f"Fetching market data from {exchange_name} for {len(symbols)} symbols...")
    
    try:
        # Initialize exchange
        exchange_class = getattr(ccxt, exchange_name)
        exchange = exchange_class({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            },
            'timeout': 10000  # 10 second timeout
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
                print(f"  Error fetching {symbol}: {str(e)[:100]}")
                continue
        
        if not price_data:
            raise ValueError("No market data could be fetched from exchange")
        
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
        
    except Exception as e:
        if use_demo_on_fail:
            warnings.warn(
                f"Failed to fetch live market data: {str(e)[:100]}. "
                "Using realistic demo data instead."
            )
            print(f"\n⚠️  Live data fetch failed: {str(e)[:100]}")
            print("⚠️  Falling back to REALISTIC DEMO DATA based on historical patterns")
            return _generate_realistic_demo_data(symbols, days)
        else:
            raise


def _generate_realistic_demo_data(symbols, days=90):
    """
    Generate realistic demo data based on historical cryptocurrency market patterns.
    This is used as a fallback when live data cannot be fetched.
    
    Args:
        symbols: List of trading pairs
        days: Number of days to simulate
    
    Returns:
        tuple: (expected_returns, covariance_matrix, symbol_names)
    """
    print(f"\nGenerating realistic demo data for {len(symbols)} assets over {days} days...")
    
    # Realistic parameters based on cryptocurrency market history
    # These are approximate values based on common crypto market patterns
    asset_params = {
        'BTC/USDT': {'mean_return': 0.0015, 'volatility': 0.04},   # ~0.15% daily return, 4% volatility
        'ETH/USDT': {'mean_return': 0.0018, 'volatility': 0.05},   # ~0.18% daily return, 5% volatility
        'BNB/USDT': {'mean_return': 0.0012, 'volatility': 0.045},  # ~0.12% daily return, 4.5% volatility
        'SOL/USDT': {'mean_return': 0.0020, 'volatility': 0.06},   # ~0.20% daily return, 6% volatility
        'ADA/USDT': {'mean_return': 0.0010, 'volatility': 0.055},
        'DOT/USDT': {'mean_return': 0.0011, 'volatility': 0.052},
    }
    
    # Default parameters for unknown symbols
    default_params = {'mean_return': 0.0012, 'volatility': 0.05}
    
    # Generate correlated returns
    num_assets = len(symbols)
    
    # Create correlation matrix (cryptos are typically positively correlated)
    correlation = np.eye(num_assets)
    for i in range(num_assets):
        for j in range(i+1, num_assets):
            # Cryptocurrencies typically have correlation between 0.5 and 0.8
            correlation[i, j] = correlation[j, i] = np.random.uniform(0.5, 0.8)
    
    # Generate returns for each asset
    returns_data = {}
    
    for idx, symbol in enumerate(symbols):
        params = asset_params.get(symbol, default_params)
        
        # Generate correlated random returns
        base_returns = np.random.normal(
            params['mean_return'], 
            params['volatility'], 
            days
        )
        
        # Add market-wide correlation
        if idx > 0:
            # Add correlation with previous assets
            market_factor = np.mean(list(returns_data.values()), axis=0)
            base_returns = 0.7 * base_returns + 0.3 * market_factor
        
        returns_data[symbol] = base_returns
    
    # Create DataFrame and calculate metrics
    returns_df = pd.DataFrame(returns_data)
    
    expected_returns = returns_df.mean().values
    covariance_matrix = returns_df.cov().values
    
    print(f"Demo expected returns: {expected_returns}")
    print(f"Demo covariance matrix shape: {covariance_matrix.shape}")
    print("✓ Demo data generation complete")
    
    return expected_returns, covariance_matrix, list(returns_df.columns)


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
