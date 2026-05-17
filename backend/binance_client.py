"""
Binance REST API Client for RLdC Trading Bot
"""

import hashlib
import hmac
import logging
import math
import os
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import requests
# Import Client tylko runtime, nie przy imporcie modułu
try:
    from binance.client import Client
except ImportError:
    Client = None
from binance.exceptions import BinanceAPIException, BinanceRequestException
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

logger = logging.getLogger(__name__)

# Kody błędów Binance wskazujące na chwilowe przeciążenie / rate limit
_TRANSIENT_CODES = {-1003, -1015, -1016, 429, 503}
# Maksymalna liczba prób dla metod z retry
_MAX_RETRIES = 3


def _binance_retry(func):
    """Dekorator: ponawia wywołanie Binance przy przejściowych błędach sieciowych / rate limit.

    Reaguje na:
    - BinanceAPIException z kodem w _TRANSIENT_CODES (rate limit, serwis niedostępny)
    - requests.ConnectionError / requests.Timeout (problemy sieciowe)

    Strategia: exp. backoff 1s → 2s → 4s, łącznie 3 próby.
    Błędy -1121 (invalid symbol) i inne nie są powtarzane.
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        delay = 1.0
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except BinanceAPIException as exc:
                code = getattr(exc, "code", None)
                if code in _TRANSIENT_CODES and attempt < _MAX_RETRIES:
                    logger.warning(
                        "⏳ Binance rate limit / przeciążenie (kod %s), próba %d/%d, czekam %.0fs…",
                        code,
                        attempt,
                        _MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "⏳ Błąd sieciowy Binance, próba %d/%d, czekam %.0fs… (%s)",
                        attempt,
                        _MAX_RETRIES,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise
        raise RuntimeError("_binance_retry: exhausted without result — unreachable state")

    return wrapper


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
            logger.info(
                "⚠️  Binance client initialized without API keys (public data only)"
            )

        self._sync_time()

    def _sync_time(self):
        """Synchronizuj czas z serwerem Binance (ważne dla signed endpoints)."""
        try:
            server_time = self.client.get_server_time()
            local_ms = int(time.time() * 1000)
            self.time_offset_ms = (
                int(server_time.get("serverTime", local_ms)) - local_ms
            )
            # python-binance używa timestamp_offset w częściach klienta
            try:
                self.client.timestamp_offset = self.time_offset_ms
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"⚠️  Cannot sync Binance server time: {str(exc)}")

    @_binance_retry
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
            return {"symbol": ticker["symbol"], "price": float(ticker["price"])}
        except BinanceAPIException as e:
            # -1121 = Invalid symbol — normalny fallback przy sprawdzaniu par, logujemy na DEBUG
            if getattr(e, "code", None) == -1121:
                logger.debug(f"⚠️ Symbol {symbol} nie istnieje na Binance (fallback)")
            else:
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
                {"symbol": t["symbol"], "price": float(t["price"])} for t in tickers
            ]
        except Exception as e:
            logger.error(f"❌ Error getting all tickers: {str(e)}")
            return []

    @_binance_retry
    def get_klines(
        self, symbol: str, interval: str = "1h", limit: int = 100
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
                symbol=symbol, interval=interval, limit=limit
            )

            result = []
            for k in klines:
                result.append(
                    {
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
                        "taker_buy_quote": float(k[10]),
                    }
                )

            return result

        except BinanceAPIException as e:
            logger.error(f"❌ Binance API error for klines {symbol}: {e.message}")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting klines for {symbol}: {str(e)}")
            return None

    @_binance_retry
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
                "timestamp": orderbook.get("lastUpdateId"),
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
                    balances.append(
                        {
                            "asset": bal["asset"],
                            "free": free,
                            "locked": locked,
                            "total": free + locked,
                        }
                    )

            return {
                "can_trade": account.get("canTrade", False),
                "can_withdraw": account.get("canWithdraw", False),
                "can_deposit": account.get("canDeposit", False),
                "balances": balances,
                "update_time": account.get("updateTime"),
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
                "count": ticker["count"],
            }
        except Exception as e:
            logger.error(f"❌ Error getting 24h ticker for {symbol}: {str(e)}")
            return None

    def _signed_request(
        self, base_url: str, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Optional[Any]:
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️  Cannot call signed endpoint without API keys")
            return None
        params = params or {}
        params["timestamp"] = int(time.time() * 1000) + int(self.time_offset_ms or 0)
        query_string = urlencode(params, quote_via=quote, safe="~")
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
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
        return self._signed_request(
            "https://api.binance.com", "/sapi/v1/simple-earn/account"
        )

    def get_simple_earn_flexible_positions(self) -> Optional[Dict]:
        return self._signed_request(
            "https://api.binance.com", "/sapi/v1/simple-earn/flexible/position"
        )

    def get_simple_earn_locked_positions(self) -> Optional[Dict]:
        return self._signed_request(
            "https://api.binance.com", "/sapi/v1/simple-earn/locked/position"
        )

    def get_futures_balance(self) -> Optional[Any]:
        return self._signed_request("https://fapi.binance.com", "/fapi/v2/balance")

    def get_futures_account(self) -> Optional[Dict]:
        return self._signed_request("https://fapi.binance.com", "/fapi/v2/account")

    def get_my_trades(
        self,
        symbol: str,
        limit: int = 500,
        from_id: Optional[int] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[List[Dict]]:
        if not symbol:
            return None
        params = {"symbol": symbol, "limit": min(int(limit or 500), 1000)}
        if from_id is not None:
            params["fromId"] = int(from_id)
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        return self._signed_request(
            "https://api.binance.com", "/api/v3/myTrades", params=params
        )

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

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: float = 0.0,
        price: Optional[float] = None,
        quote_qty: float = 0.0,
    ) -> Optional[Dict]:
        """
        Złóż zlecenie na Binance (wymaga API keys).

        Args:
            symbol:     Para walutowa (np. BTCEUR)
            side:       'BUY' lub 'SELL'
            order_type: 'MARKET' lub 'LIMIT'
            quantity:   Ilość base asset (alternatywnie użyj quote_qty)
            price:      Cena (tylko dla LIMIT)
            quote_qty:  Kwota quote currency do wydania (np. EUR) — dla market buy

        Returns:
            Dict z odpowiedzią Binance lub None przy błędzie.
        """
        if not self.api_key or not self.api_secret:
            logger.error(
                "❌ place_order: brak kluczy API — ustaw BINANCE_API_KEY i BINANCE_API_SECRET"
            )
            return None
        if quantity <= 0 and quote_qty <= 0:
            logger.error(
                f"❌ place_order: nieprawidłowa ilość {quantity} / quote_qty={quote_qty}"
            )
            return None

        try:
            kwargs: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "type": order_type,
            }
            if quote_qty > 0:
                kwargs["quoteOrderQty"] = round(quote_qty, 2)
            else:
                # Zaokrąglij qty do step_size (LOT_SIZE filter) — zapobiega odrzuceniu przez Binance
                try:
                    sym_info = (self.get_allowed_symbols() or {}).get(symbol, {})
                    step = float(sym_info.get("step_size") or 0)
                    if step > 0:
                        quantity = math.floor(quantity / step) * step
                        # Normalizacja: usuń błędy zmiennoprzecinkowe
                        decimals = max(0, -int(math.floor(math.log10(step))))
                        quantity = round(quantity, decimals)
                except Exception as step_exc:
                    logger.warning(
                        "⚠️ place_order: nie udało się znormalizować qty do step_size dla %s: %s — wysyłam oryginalną wartość qty=%s",
                        symbol, step_exc, quantity,
                    )
                kwargs["quantity"] = quantity
            if order_type == "LIMIT":
                if price is None:
                    logger.error("❌ place_order: LIMIT wymaga ceny")
                    return None
                kwargs["price"] = f"{price:.8f}"
                kwargs["timeInForce"] = "GTC"

            # Uwzględnij przesunięcie czasu
            kwargs["recvWindow"] = 5000
            _log_qty = (
                quantity
                if quantity > 0
                else f"quoteQty={kwargs.get('quoteOrderQty', 0)}"
            )
            logger.info(
                "📤 place_order SEND: %s %s %s qty=%s price=%s",
                side, _log_qty, symbol, kwargs.get("quantity"), kwargs.get("price", "MARKET"),
            )
            try:
                result = self.client.create_order(**kwargs)
            except BinanceAPIException as e:
                if getattr(e, "code", None) == -1021:
                    # Timestamp out of range — synchronizuj czas i powtórz
                    logger.warning("⏳ place_order: timestamp out of range dla %s — sync czasu i retry", symbol)
                    self._sync_time()
                    result = self.client.create_order(**kwargs)
                else:
                    raise
            order_id = result.get("orderId")
            binance_status = result.get("status", "UNKNOWN")
            exec_qty = result.get("executedQty", "?")
            cum_quote = result.get("cummulativeQuoteQty", "?")
            fills_count = len(result.get("fills") or [])
            logger.info(
                "✅ place_order RESPONSE: %s %s %s → orderId=%s status=%s executedQty=%s cumQuote=%s fills=%d",
                side, _log_qty, symbol, order_id, binance_status, exec_qty, cum_quote, fills_count,
            )
            return result
        except BinanceAPIException as e:
            logger.error(
                "❌ place_order Binance API error %s: code=%s msg=%s",
                symbol, e.status_code, e.message,
            )
            return {
                "_error": True,
                "error_code": e.status_code,
                "error_message": e.message,
            }
        except Exception as e:
            logger.error(
                "❌ place_order nieoczekiwany błąd %s: %s — %s",
                symbol, type(e).__name__, str(e),
            )
            return {
                "_error": True,
                "error_code": None,
                "error_message": f"{type(e).__name__}: {str(e)}",
            }

    def get_order_fills(self, symbol: str, order_id: int) -> Optional[Dict]:
        """
        Pobierz szczegóły wypełnionego zlecenia (fills).

        Returns:
            Dict z polami: executed_price (float), executed_qty (float), fee (float), fee_asset (str)
        """
        if not self.api_key or not self.api_secret:
            return None
        try:
            order = self.client.get_order(
                symbol=symbol, orderId=order_id, recvWindow=5000
            )
            fills = order.get("fills", [])
            exec_price = float(order.get("cummulativeQuoteQty", 0) or 0)
            exec_qty = float(order.get("executedQty", 0) or 0)
            avg_price = (
                exec_price / exec_qty
                if exec_qty > 0
                else float(order.get("price", 0) or 0)
            )
            total_fee = sum(float(f.get("commission", 0)) for f in fills)
            fee_asset = fills[0].get("commissionAsset", "") if fills else ""
            return {
                "order_id": order_id,
                "status": order.get("status"),
                "executed_price": round(avg_price, 8),
                "executed_qty": round(exec_qty, 8),
                "fee": round(total_fee, 8),
                "fee_asset": fee_asset,
            }
        except Exception as e:
            logger.error(f"❌ get_order_fills {symbol} #{order_id}: {str(e)}")
            return None

    # ── Cache dla exchange info (TTL 5 minut) ────────────────────────────────
    _allowed_cache_data: Optional[Dict[str, Dict]] = None
    _allowed_cache_ts: float = 0.0
    _ALLOWED_TTL: float = 300.0  # 5 minut

    def get_allowed_symbols(
        self, quotes: Optional[List[str]] = None
    ) -> Dict[str, Dict]:
        """
        Pobierz zestaw symboli SPOT dozwolonych do handlu na giełdzie Binance.
        Buforuje wynik na 5 minut (exchangeInfo zmienia się rzadko).

        Args:
            quotes: Lista kwot (np. ["EUR", "USDC"]) — filtruje wyniki.
                    None = zwróć wszystkie SPOT symbole.

        Returns:
            Dict[symbol, {base_asset, quote_asset, min_qty, step_size, min_notional}]
        """
        now = time.time()
        if (
            self._allowed_cache_data is not None
            and (now - self._allowed_cache_ts) < self._ALLOWED_TTL
        ):
            data = self._allowed_cache_data
        else:
            data = self._fetch_exchange_info()
            self.__class__._allowed_cache_data = data
            self.__class__._allowed_cache_ts = now

        if not quotes:
            return data
        quotes_set = {q.upper() for q in quotes}
        return {s: v for s, v in data.items() if v["quote_asset"] in quotes_set}

    def _fetch_exchange_info(self) -> Dict[str, Dict]:
        """Pobierz i zparsuj exchangeInfo z Binance."""
        try:
            info = self.client.get_exchange_info()
            result: Dict[str, Dict] = {}
            for sym in info.get("symbols", []):
                if sym.get("status") != "TRADING":
                    continue
                # Sprawdź uprawnienie SPOT
                perms = sym.get("permissions", [])
                perm_sets = sym.get("permissionSets", [])
                spot_ok = "SPOT" in perms
                if not spot_ok and perm_sets:
                    # nowszy format: [[...], ...]
                    for ps in perm_sets:
                        if "SPOT" in ps:
                            spot_ok = True
                            break
                if not spot_ok:
                    continue

                symbol = sym["symbol"]
                min_qty = min_notional = step_size = None
                for f in sym.get("filters", []):
                    ft = f.get("filterType", "")
                    if ft == "LOT_SIZE":
                        try:
                            min_qty = float(f.get("minQty", 0))
                            step_size = float(f.get("stepSize", 0))
                        except (ValueError, TypeError):
                            pass
                    elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                        try:
                            min_notional = float(f.get("minNotional", 0))
                        except (ValueError, TypeError):
                            pass

                result[symbol] = {
                    "base_asset": sym["baseAsset"],
                    "quote_asset": sym["quoteAsset"],
                    "min_qty": min_qty,
                    "step_size": step_size,
                    "min_notional": min_notional,
                }
            logger.info(
                f"✅ ExchangeInfo: {len(result)} aktywnych symboli SPOT załadowanych"
            )
            return result
        except Exception as exc:
            logger.error(f"❌ Błąd pobierania exchangeInfo: {str(exc)}")
            return {}

    @_binance_retry
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
                    balances.append(
                        {
                            "asset": bal.get("asset"),
                            "free": free,
                            "locked": locked,
                            "total": free + locked,
                        }
                    )
            return balances
        except Exception as e:
            logger.error(f"❌ Error getting balances: {str(e)}")
            return []

    def get_book_ticker(self, symbol: str) -> Optional[Dict]:
        """
        Pobierz najlepszy bid/ask dla symbolu (bookTicker).

        Returns:
            {"bid_price": float, "ask_price": float, "bid_qty": float, "ask_qty": float}
        """
        try:
            r = self.client.get_orderbook_ticker(symbol=symbol) or {}
            return {
                "bid_price": float(r.get("bidPrice", 0) or 0),
                "ask_price": float(r.get("askPrice", 0) or 0),
                "bid_qty": float(r.get("bidQty", 0) or 0),
                "ask_qty": float(r.get("askQty", 0) or 0),
            }
        except Exception as exc:
            logger.error("❌ get_book_ticker %s: %s", symbol, exc)
            return None

    def get_avg_price(self, symbol: str) -> Optional[float]:
        """
        Pobierz 5-minutową średnią cenę z Binance (GET /api/v3/avgPrice).
        Używana do walidacji PERCENT_PRICE_BY_SIDE przed złożeniem zlecenia.
        """
        try:
            r = self.client.get_avg_price(symbol=symbol) or {}
            return float(r.get("price", 0) or 0)
        except Exception as exc:
            logger.error("❌ get_avg_price %s: %s", symbol, exc)
            return None

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Pobierz otwarte zlecenia z Binance.

        Args:
            symbol: jeśli podany — tylko dla tego symbolu; jeśli None — wszystkie

        Returns:
            Lista słowników ze zleceniami Binance.
        """
        if not self.api_key or not self.api_secret:
            return []
        try:
            kwargs: Dict[str, Any] = {"recvWindow": 5000}
            if symbol:
                kwargs["symbol"] = symbol
            try:
                orders = self.client.get_open_orders(**kwargs) or []
            except BinanceAPIException as e:
                if getattr(e, "code", None) == -1021:
                    self._sync_time()
                    orders = self.client.get_open_orders(**kwargs) or []
                else:
                    raise
            return list(orders)
        except Exception as exc:
            logger.error("❌ get_open_orders %s: %s", symbol or "ALL", exc)
            return []

    def get_order(self, symbol: str, order_id: str) -> Optional[Dict]:
        """
        Pobierz status zlecenia po orderId.

        Returns:
            Słownik ze statusem zlecenia lub None przy błędzie.
        """
        if not self.api_key or not self.api_secret:
            return None
        try:
            try:
                r = self.client.get_order(
                    symbol=symbol, orderId=int(order_id), recvWindow=5000
                )
            except BinanceAPIException as e:
                if getattr(e, "code", None) == -1021:
                    self._sync_time()
                    r = self.client.get_order(
                        symbol=symbol, orderId=int(order_id), recvWindow=5000
                    )
                elif getattr(e, "code", None) == -2013:
                    # Order not found
                    return None
                else:
                    raise
            return r
        except Exception as exc:
            logger.error("❌ get_order %s #%s: %s", symbol, order_id, exc)
            return None

    def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        list_client_order_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Anuluj zlecenie lub OCO na Binance.

        Args:
            symbol:                 Para walutowa
            order_id:               orderId (liczba jako string) — anuluj pojedyncze
            list_client_order_id:   listClientOrderId — anuluj całe OCO

        Returns:
            Odpowiedź Binance lub None przy błędzie.
        """
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ cancel_order: brak kluczy API")
            return None
        try:
            if list_client_order_id:
                # Anuluj OCO
                try:
                    r = self.client.cancel_order(
                        symbol=symbol,
                        listClientOrderId=list_client_order_id,
                        recvWindow=5000,
                    )
                except BinanceAPIException as e:
                    if getattr(e, "code", None) == -1021:
                        self._sync_time()
                        r = self.client.cancel_order(
                            symbol=symbol,
                            listClientOrderId=list_client_order_id,
                            recvWindow=5000,
                        )
                    else:
                        raise
            elif order_id:
                try:
                    r = self.client.cancel_order(
                        symbol=symbol,
                        orderId=int(order_id),
                        recvWindow=5000,
                    )
                except BinanceAPIException as e:
                    if getattr(e, "code", None) == -1021:
                        self._sync_time()
                        r = self.client.cancel_order(
                            symbol=symbol,
                            orderId=int(order_id),
                            recvWindow=5000,
                        )
                    else:
                        raise
            else:
                logger.error("cancel_order: wymagany order_id lub list_client_order_id")
                return None
            logger.info("✅ cancel_order: %s %s", symbol, order_id or list_client_order_id)
            return r
        except BinanceAPIException as e:
            if getattr(e, "code", None) == -2011:
                # Unknown order sent — prawdopodobnie już anulowane
                logger.info("ℹ️ cancel_order %s: order już nieaktywny (code -2011)", symbol)
                return {"_already_cancelled": True}
            logger.error("❌ cancel_order %s: code=%s msg=%s", symbol, e.status_code, e.message)
            return {"_error": True, "error_code": e.status_code, "error_message": e.message}
        except Exception as exc:
            logger.error("❌ cancel_order %s: %s", symbol, exc)
            return None

    def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        stop_price: float,
        stop_limit_price: float,
        time_in_force: str = "GTC",
    ) -> Optional[Dict]:
        """
        Złóż zlecenie OCO (One-Cancels-the-Other) na Binance.

        Dla SELL OCO:
          - price         = limit TP (Take Profit)
          - stop_price    = cena triggeru SL
          - stop_limit_price = limit price SL (musi być niższy niż stop_price)

        Returns:
            Odpowiedź Binance lub {"_error": True, ...} przy błędzie.
        """
        if not self.api_key or not self.api_secret:
            logger.error("❌ place_oco_order: brak kluczy API")
            return None
        try:
            params: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
                "price": f"{price:.8f}".rstrip("0").rstrip("."),
                "stopPrice": f"{stop_price:.8f}".rstrip("0").rstrip("."),
                "stopLimitPrice": f"{stop_limit_price:.8f}".rstrip("0").rstrip("."),
                "stopLimitTimeInForce": time_in_force,
                "recvWindow": 5000,
            }
            logger.info(
                "📤 place_oco_order SEND: %s %s qty=%s tp=%.6f sl_stop=%.6f sl_limit=%.6f",
                side, symbol, quantity, price, stop_price, stop_limit_price,
            )
            try:
                result = self.client.create_oco_order(**params)
            except BinanceAPIException as e:
                if getattr(e, "code", None) == -1021:
                    self._sync_time()
                    result = self.client.create_oco_order(**params)
                else:
                    raise
            logger.info(
                "✅ place_oco_order RESPONSE: %s listClientOrderId=%s",
                symbol, (result or {}).get("listClientOrderId"),
            )
            return result
        except BinanceAPIException as e:
            logger.error(
                "❌ place_oco_order %s: code=%s msg=%s",
                symbol, e.status_code, e.message,
            )
            return {"_error": True, "error_code": e.status_code, "error_message": e.message}
        except Exception as exc:
            logger.error("❌ place_oco_order %s: %s", symbol, exc)
            return {"_error": True, "error_code": None, "error_message": str(exc)}


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
