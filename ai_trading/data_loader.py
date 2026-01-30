"""
Data Loader Module for AI Trading PoC
Fetches historical OHLCV data using ccxt
"""

import ccxt
import pandas as pd
from typing import Optional, Tuple
import time


class DataLoader:
    """
    Data loader for fetching historical OHLCV (Open, High, Low, Close, Volume) data
    from cryptocurrency exchanges using ccxt.
    """
    
    def __init__(self, exchange_name: str = 'binance'):
        """
        Initialize the data loader with a specific exchange.
        
        Args:
            exchange_name: Name of the exchange (default: 'binance')
        """
        self.exchange_name = exchange_name
        self.exchange = None
        self._initialize_exchange()
    
    def _initialize_exchange(self):
        """Initialize the exchange connection."""
        try:
            exchange_class = getattr(ccxt, self.exchange_name)
            self.exchange = exchange_class({
                'enableRateLimit': True,
                'timeout': 30000,
            })
        except AttributeError:
            raise ValueError(f"Exchange '{self.exchange_name}' not supported by ccxt")
        except Exception as e:
            raise ConnectionError(f"Failed to initialize exchange: {str(e)}")
    
    def fetch_ohlcv(
        self,
        symbol: str = 'BTC/USDT',
        timeframe: str = '1h',
        limit: int = 1000,
        retries: int = 3
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data from the exchange.
        
        Args:
            symbol: Trading pair symbol (default: 'BTC/USDT')
            timeframe: Candlestick timeframe (default: '1h')
            limit: Number of candles to fetch (default: 1000)
            retries: Number of retry attempts on failure (default: 3)
            
        Returns:
            Pandas DataFrame with columns: timestamp, open, high, low, close, volume
            
        Raises:
            ConnectionError: If unable to fetch data after retries
            ValueError: If the data returned is invalid
        """
        for attempt in range(retries):
            try:
                if not self.exchange:
                    self._initialize_exchange()
                
                # Fetch OHLCV data
                ohlcv = self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit
                )
                
                if not ohlcv:
                    raise ValueError("No data returned from exchange")
                
                # Convert to DataFrame
                df = pd.DataFrame(
                    ohlcv,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                
                # Clean and prepare data
                df = self._clean_data(df)
                
                return df
                
            except ccxt.NetworkError as e:
                if attempt < retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"Network error, retrying in {wait_time}s... ({attempt + 1}/{retries})")
                    time.sleep(wait_time)
                else:
                    raise ConnectionError(f"Failed to fetch data after {retries} attempts: {str(e)}")
            
            except ccxt.ExchangeError as e:
                raise ConnectionError(f"Exchange error: {str(e)}")
            
            except Exception as e:
                raise ConnectionError(f"Unexpected error fetching data: {str(e)}")
        
        raise ConnectionError(f"Failed to fetch data after {retries} attempts")
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and prepare the OHLCV data.
        
        Args:
            df: Raw DataFrame from exchange
            
        Returns:
            Cleaned DataFrame ready for use
        """
        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Remove any duplicates
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # Check for missing values
        if df.isnull().any().any():
            print("Warning: Found missing values, forward-filling...")
            df = df.ffill().bfill()
        
        # Ensure all price/volume columns are float
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        return df
    
    def get_latest_price(self, symbol: str = 'BTC/USDT') -> Optional[float]:
        """
        Get the latest ticker price for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Latest price or None if unavailable
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            print(f"Error fetching latest price: {str(e)}")
            return None


def load_data(
    symbol: str = 'BTC/USDT',
    timeframe: str = '1h',
    limit: int = 1000,
    exchange: str = 'binance'
) -> pd.DataFrame:
    """
    Convenience function to load OHLCV data.
    
    Args:
        symbol: Trading pair symbol
        timeframe: Candlestick timeframe
        limit: Number of candles to fetch
        exchange: Exchange name
        
    Returns:
        Cleaned Pandas DataFrame with OHLCV data
    """
    loader = DataLoader(exchange_name=exchange)
    return loader.fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
