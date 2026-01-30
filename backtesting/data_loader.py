"""
Historical Data Loader for fetching and caching OHLCV data from exchanges.
"""

import ccxt
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


class HistoricalDataLoader:
    """
    Handles fetching and caching historical OHLCV data from cryptocurrency exchanges.
    """
    
    def __init__(self, exchange_id: str = 'binance'):
        """
        Initialize the data loader with a specific exchange.
        
        Args:
            exchange_id: The ccxt exchange ID (default: 'binance')
        """
        # Validate exchange_id against supported exchanges
        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"Exchange '{exchange_id}' is not supported by ccxt")
        
        try:
            self.exchange = getattr(ccxt, exchange_id)()
        except Exception as e:
            raise ValueError(f"Failed to initialize exchange '{exchange_id}': {e}")
        self.data = None
    
    def fetch_data(self, symbol: str, timeframe: str = '1h', days_back: int = 30) -> pd.DataFrame:
        """
        Fetch OHLCV data from the exchange.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            timeframe: Candlestick timeframe (e.g., '1m', '5m', '1h', '1d')
            days_back: Number of days of historical data to fetch
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        # Calculate the start time
        since = int((datetime.now() - timedelta(days=days_back)).timestamp() * 1000)
        
        # Fetch OHLCV data
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=since)
        
        # Convert to DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Set proper data types
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # Store the data
        self.data = df
        
        return df
    
    def save_to_csv(self, filename: str) -> None:
        """
        Save the fetched data to a CSV file.
        
        Args:
            filename: Path to the CSV file
        """
        if self.data is None:
            raise ValueError("No data to save. Call fetch_data() first.")
        
        self.data.to_csv(filename, index=False)
    
    def load_from_csv(self, filename: str) -> pd.DataFrame:
        """
        Load historical data from a CSV file.
        
        Args:
            filename: Path to the CSV file
            
        Returns:
            DataFrame with OHLCV data
        """
        df = pd.read_csv(filename)
        
        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Ensure proper data types
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # Store the data
        self.data = df
        
        return df
