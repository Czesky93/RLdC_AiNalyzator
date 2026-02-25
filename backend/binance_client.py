"""
Binance REST API Client for RLdC Trading Bot
"""
import os
import time
import hmac
import hashlib
from typing import List, Dict, Optional, Any
from urllib.parse import urlencode, quote
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv
import logging
from functools import lru_cache

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

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
        self.time_offset_ms = 0
        
        # Inicjalizacja klienta - działa bez kluczy dla publicznych danych
        if self.api_key and self.api_secret:
            self.client = Client(self.api_key, self.api_secret)
            logger.info("✅ Binance client initialized with API keys")
        else:
            self.client = Client()
            logger.info("⚠️  Binance client initialized without API keys (public data only)")

        self._sync_time()

    def _sync_time(self):
        """Synchronizuj czas z serwerem Binance (ważne dla signed endpoints)."""
        try:
            server_time = self.client.get_server_time()
            local_ms = int(time.time() * 1000)
            self.time_offset_ms = int(server_time.get("serverTime", local_ms)) - local_ms
            # python-binance używa timestamp_offset w częściach klienta
            try:
                self.client.timestamp_offset = self.time_offset_ms
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"⚠️  Cannot sync Binance server time: {str(exc)}")
    
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
            try:
                account = self.client.get_account(recvWindow=5000)
            except BinanceAPIException as e:
                # Timestamp drift
                if getattr(e, "code", None) == -1021:
                    self._sync_time()
                    account = self.client.get_account(recvWindow=5000)
                else:
                    raise
            
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

    def _signed_request(self, base_url: str, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️  Cannot call signed endpoint without API keys")
            return None
        params = params or {}
        params["timestamp"] = int(time.time() * 1000) + int(self.time_offset_ms or 0)
        query_string = urlencode(params, quote_via=quote, safe="~")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        url = f"{base_url}{path}?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"❌ Signed request error {path}: {str(e)}")
            return None

    def get_simple_earn_account(self) -> Optional[Dict]:
        return self._signed_request("https://api.binance.com", "/sapi/v1/simple-earn/account")

    def get_simple_earn_flexible_positions(self) -> Optional[Dict]:
        return self._signed_request("https://api.binance.com", "/sapi/v1/simple-earn/flexible/position")

    def get_simple_earn_locked_positions(self) -> Optional[Dict]:
        return self._signed_request("https://api.binance.com", "/sapi/v1/simple-earn/locked/position")

    def get_futures_balance(self) -> Optional[Any]:
        return self._signed_request("https://fapi.binance.com", "/fapi/v2/balance")

    def get_futures_account(self) -> Optional[Dict]:
        return self._signed_request("https://fapi.binance.com", "/fapi/v2/account")

    def get_my_trades(self, symbol: str, limit: int = 500) -> Optional[List[Dict]]:
        if not symbol:
            return None
        params = {"symbol": symbol, "limit": limit}
        return self._signed_request("https://api.binance.com", "/api/v3/myTrades", params=params)

    def get_avg_buy_price(self, symbol: str) -> Optional[float]:
        trades = self.get_my_trades(symbol)
        if not trades:
            return None
        buy_qty = 0.0
        buy_cost = 0.0
        for t in trades:
            if t.get("isBuyer"):
                qty = float(t.get("qty", 0))
                price = float(t.get("price", 0))
                buy_qty += qty
                buy_cost += qty * price
        if buy_qty <= 0:
            return None
        return buy_cost / buy_qty

    @lru_cache(maxsize=1)
    def _exchange_info(self) -> Dict:
        """Pobierz i cache'uj exchange info."""
        return self.client.get_exchange_info()

    def resolve_symbol(self, pair: str) -> Optional[str]:
        """
        Rozwiąż parę w formacie BASE/QUOTE lub BASEQUOTE do rzeczywistego symbolu Binance.
        """
        if not pair:
            return None

        raw = pair.strip().upper()
        direct = raw.replace("/", "")

        try:
            info = self._exchange_info()
            symbols = info.get("symbols", [])

            # Direct match
            for s in symbols:
                if s.get("symbol") == direct:
                    return direct

            # Match by base/quote
            if "/" in raw:
                base, quote = raw.split("/", 1)
            else:
                # Try infer base/quote from balances
                base = raw[:-3]
                quote = raw[-3:]

            for s in symbols:
                if s.get("baseAsset") == base and s.get("quoteAsset") == quote:
                    return s.get("symbol")
        except Exception as e:
            logger.error(f"❌ Error resolving symbol {pair}: {str(e)}")

        return None

    def get_balances(self) -> List[Dict]:
        """Pobierz saldo konta (wymaga API keys)."""
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️  Cannot get balances without API keys")
            return []
        try:
            try:
                account = self.client.get_account(recvWindow=5000)
            except BinanceAPIException as e:
                if getattr(e, "code", None) == -1021:
                    self._sync_time()
                    account = self.client.get_account(recvWindow=5000)
                else:
                    raise
            balances = []
            for bal in account.get("balances", []):
                free = float(bal.get("free", 0))
                locked = float(bal.get("locked", 0))
                if free > 0 or locked > 0:
                    balances.append({
                        "asset": bal.get("asset"),
                        "free": free,
                        "locked": locked,
                        "total": free + locked,
                    })
            return balances
        except Exception as e:
            logger.error(f"❌ Error getting balances: {str(e)}")
            return []


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
