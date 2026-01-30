"""
Mock data generator for testing when network is unavailable
"""

import numpy as np
import pandas as pd


def generate_mock_ohlcv(
    n_candles: int = 1000,
    base_price: float = 50000.0,
    volatility: float = 0.02,
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate mock OHLCV data for testing purposes.
    
    Args:
        n_candles: Number of candles to generate
        base_price: Starting price
        volatility: Price volatility (standard deviation of returns)
        seed: Random seed for reproducibility
        
    Returns:
        DataFrame with mock OHLCV data
    """
    np.random.seed(seed)
    
    # Generate timestamps
    timestamps = pd.date_range(start='2024-01-01', periods=n_candles, freq='1h')
    
    # Generate price data using geometric Brownian motion
    dt = 1.0  # time step
    mu = 0.0001  # drift (slight upward trend)
    sigma = volatility  # volatility
    
    # Generate price path
    returns = np.random.normal(mu * dt, sigma * np.sqrt(dt), n_candles)
    prices = base_price * np.exp(np.cumsum(returns))
    
    # Create OHLCV data
    data = []
    for i, close_price in enumerate(prices):
        # Generate realistic OHLC from close price
        intra_volatility = np.random.uniform(0.001, 0.005)
        
        # Open is previous close or slight variation
        if i == 0:
            open_price = close_price * np.random.uniform(0.998, 1.002)
        else:
            open_price = prices[i-1] * np.random.uniform(0.998, 1.002)
        
        # High and low based on open/close
        max_oc = max(open_price, close_price)
        min_oc = min(open_price, close_price)
        
        high_price = max_oc * (1 + np.random.uniform(0, intra_volatility))
        low_price = min_oc * (1 - np.random.uniform(0, intra_volatility))
        
        # Volume with some randomness
        base_volume = 100 + np.random.exponential(200)
        # Volume tends to be higher on larger price moves
        price_change = abs(close_price - open_price) / open_price
        volume = base_volume * (1 + price_change * 10)
        
        data.append({
            'timestamp': timestamps[i],
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'close': close_price,
            'volume': volume
        })
    
    df = pd.DataFrame(data)
    
    # Ensure high is highest and low is lowest
    df['high'] = df[['open', 'high', 'low', 'close']].max(axis=1)
    df['low'] = df[['open', 'high', 'low', 'close']].min(axis=1)
    
    return df
