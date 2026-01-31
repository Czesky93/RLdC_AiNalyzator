"""
Binance REST API Client for RLdC Trading Bot
"""
import os
import time
from typing import List, Dict, Optional
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)


class BinanceClient:
    """Klient REST API Binance z obsługą błędów i rate limiting"""
    
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Inicjalizacja klienta Binance
        
        Args:
            api_key: Klucz API Binance (opcjonalny dla publicznych danych)
            api_secret: Sekret API Binance (opcjonalny dla publicznych danych)
        """
        self.api_key = api_key or os.getenv("BINANCE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")
        
        # Inicjalizacja klienta - działa bez kluczy dla publicznych danych
        if self.api_key and self.api_secret:
            self.client = Client(self.api_key, self.api_secret)
            logger.info("✅ Binance client initialized with API keys")
        else:
            self.client = Client()
            logger.info("⚠️  Binance client initialized without API keys (public data only)")
    
    def get_ticker_price(self, symbol: str) -> Optional[Dict]:
        """
        Pobierz aktualną cenę symbolu
        
        Args:
            symbol: Symbol (np. BTCUSDT)
        
        Returns:
            Dict z ceną lub None w przypadku błędu
        """
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return {
                "symbol": ticker["symbol"],
                "price": float(ticker["price"])
            }
        except BinanceAPIException as e:
            logger.error(f"❌ Binance API error for {symbol}: {e.message}")
            return None
        except BinanceRequestException as e:
            logger.error(f"❌ Binance request error for {symbol}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error getting ticker for {symbol}: {str(e)}")
            return None
    
    def get_all_tickers(self) -> List[Dict]:
        """
        Pobierz ceny wszystkich symboli
        
        Returns:
            Lista słowników z cenami
        """
        try:
            tickers = self.client.get_all_tickers()
            return [
                {"symbol": t["symbol"], "price": float(t["price"])}
                for t in tickers
            ]
        except Exception as e:
            logger.error(f"❌ Error getting all tickers: {str(e)}")
            return []
    
    def get_klines(
        self, 
        symbol: str, 
        interval: str = "1h", 
        limit: int = 100
    ) -> Optional[List[Dict]]:
        """
        Pobierz dane świecowe (OHLCV)
        
        Args:
            symbol: Symbol (np. BTCUSDT)
            interval: Timeframe (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Liczba świec (max 1000)
        
        Returns:
            Lista świec lub None w przypadku błędu
        """
        try:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            result = []
            for k in klines:
                result.append({
                    "open_time": k[0],
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": k[6],
                    "quote_volume": float(k[7]),
                    "trades": int(k[8]),
                    "taker_buy_base": float(k[9]),
                    "taker_buy_quote": float(k[10])
                })
            
            return result
            
        except BinanceAPIException as e:
            logger.error(f"❌ Binance API error for klines {symbol}: {e.message}")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting klines for {symbol}: {str(e)}")
            return None
    
    def get_orderbook(self, symbol: str, limit: int = 20) -> Optional[Dict]:
        """
        Pobierz orderbook (księgę zleceń)
        
        Args:
            symbol: Symbol (np. BTCUSDT)
            limit: Głębokość (5, 10, 20, 50, 100, 500, 1000)
        
        Returns:
            Dict z bids i asks lub None w przypadku błędu
        """
        try:
            orderbook = self.client.get_order_book(symbol=symbol, limit=limit)
            return {
                "symbol": symbol,
                "bids": [[float(b[0]), float(b[1])] for b in orderbook["bids"][:limit]],
                "asks": [[float(a[0]), float(a[1])] for a in orderbook["asks"][:limit]],
                "timestamp": orderbook.get("lastUpdateId")
            }
        except Exception as e:
            logger.error(f"❌ Error getting orderbook for {symbol}: {str(e)}")
            return None
    
    def get_account_info(self) -> Optional[Dict]:
        """
        Pobierz informacje o koncie (wymaga API keys)
        TRYB LIVE - READ ONLY
        
        Returns:
            Dict z informacjami o koncie lub None
        """
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️  Cannot get account info without API keys")
            return None
        
        try:
            account = self.client.get_account()
            
            # Parse balances
            balances = []
            for bal in account["balances"]:
                free = float(bal["free"])
                locked = float(bal["locked"])
                if free > 0 or locked > 0:
                    balances.append({
                        "asset": bal["asset"],
                        "free": free,
                        "locked": locked,
                        "total": free + locked
                    })
            
            return {
                "can_trade": account.get("canTrade", False),
                "can_withdraw": account.get("canWithdraw", False),
                "can_deposit": account.get("canDeposit", False),
                "balances": balances,
                "update_time": account.get("updateTime")
            }
            
        except BinanceAPIException as e:
            logger.error(f"❌ Binance API error getting account: {e.message}")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting account info: {str(e)}")
            return None
    
    def get_24hr_ticker(self, symbol: str) -> Optional[Dict]:
        """
        Pobierz statystyki 24h dla symbolu
        
        Args:
            symbol: Symbol (np. BTCUSDT)
        
        Returns:
            Dict ze statystykami lub None
        """
        try:
            ticker = self.client.get_ticker(symbol=symbol)
            return {
                "symbol": ticker["symbol"],
                "price_change": float(ticker["priceChange"]),
                "price_change_percent": float(ticker["priceChangePercent"]),
                "weighted_avg_price": float(ticker["weightedAvgPrice"]),
                "prev_close_price": float(ticker["prevClosePrice"]),
                "last_price": float(ticker["lastPrice"]),
                "bid_price": float(ticker["bidPrice"]),
                "ask_price": float(ticker["askPrice"]),
                "open_price": float(ticker["openPrice"]),
                "high_price": float(ticker["highPrice"]),
                "low_price": float(ticker["lowPrice"]),
                "volume": float(ticker["volume"]),
                "quote_volume": float(ticker["quoteVolume"]),
                "open_time": ticker["openTime"],
                "close_time": ticker["closeTime"],
                "count": ticker["count"]
            }
        except Exception as e:
            logger.error(f"❌ Error getting 24h ticker for {symbol}: {str(e)}")
            return None


# Singleton instance
_binance_client = None

def get_binance_client() -> BinanceClient:
    """Get singleton Binance client instance"""
    global _binance_client
    if _binance_client is None:
        _binance_client = BinanceClient()
    return _binance_client


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    
    client = BinanceClient()
    
    # Test ticker
    print("\n📊 Test: Pobieranie ceny BTC")
    btc = client.get_ticker_price("BTCUSDT")
    print(f"BTC/USDT: ${btc['price']}" if btc else "❌ Błąd")
    
    # Test klines
    print("\n📈 Test: Pobieranie świec BTC (1h)")
    klines = client.get_klines("BTCUSDT", "1h", 5)
    if klines:
        print(f"Pobrano {len(klines)} świec")
        print(f"Ostatnia: Close=${klines[-1]['close']}")
    
    # Test orderbook
    print("\n📖 Test: Orderbook BTC")
    ob = client.get_orderbook("BTCUSDT", 5)
    if ob:
        print(f"Best bid: ${ob['bids'][0][0]}")
        print(f"Best ask: ${ob['asks'][0][0]}")
