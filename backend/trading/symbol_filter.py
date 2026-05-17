"""
symbol_filter.py — Pełny parser exchangeInfo Binance Spot.

Pobiera WSZYSTKIE pary TRADING z uprawnieniami SPOT z exchangeInfo.
Wyciąga i waliduje wszystkie filtry potrzebne do wysyłania zleceń:
  - LOT_SIZE          → min_qty, max_qty, step_size
  - PRICE_FILTER      → min_price, max_price, tick_size
  - PERCENT_PRICE_BY_SIDE → bidMultiplierUp/Down, askMultiplierUp/Down
  - MIN_NOTIONAL / NOTIONAL → min_notional
  - MAX_NUM_ORDERS    → maxNumOrders
  - MAX_NUM_ALGO_ORDERS → maxNumAlgoOrders

Wynik: dict symbol → SymbolMeta (namedtuple)

Przykład użycia:
    from backend.trading.symbol_filter import load_symbol_universe, can_trade
    universe = load_symbol_universe(client)
    meta = universe.get("BTCUSDC")
    if meta and can_trade(meta, quote="USDC"):
        ...
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_CACHE: Dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SEC = 300  # 5 minut


class SymbolMeta:
    """Metadane symbolu z exchangeInfo Binance Spot."""

    __slots__ = (
        "symbol", "base_asset", "quote_asset",
        "status", "is_spot", "oco_allowed",
        # LOT_SIZE
        "min_qty", "max_qty", "step_size",
        # PRICE_FILTER
        "tick_size", "min_price", "max_price",
        # PERCENT_PRICE_BY_SIDE
        "bid_mult_up", "bid_mult_down",
        "ask_mult_up", "ask_mult_down",
        # NOTIONAL
        "min_notional", "max_notional", "apply_min_to_market",
        # ORDER LIMITS
        "max_num_orders", "max_num_algo_orders",
        # Precision helpers (liczba miejsc dziesiętnych)
        "qty_precision", "price_precision",
    )

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    def __repr__(self) -> str:
        return (
            f"SymbolMeta({self.symbol} "
            f"step={self.step_size} tick={self.tick_size} "
            f"min_notional={self.min_notional})"
        )


def _extract_lot_size(filters: List[dict]) -> Tuple[float, float, float]:
    """Zwraca (min_qty, max_qty, step_size) z LOT_SIZE filter."""
    for f in filters:
        if f.get("filterType") == "LOT_SIZE":
            return (
                float(f.get("minQty") or 0),
                float(f.get("maxQty") or 0),
                float(f.get("stepSize") or 0),
            )
    return 0.0, 0.0, 0.0


def _extract_price_filter(filters: List[dict]) -> Tuple[float, float, float]:
    """Zwraca (min_price, max_price, tick_size) z PRICE_FILTER."""
    for f in filters:
        if f.get("filterType") == "PRICE_FILTER":
            return (
                float(f.get("minPrice") or 0),
                float(f.get("maxPrice") or 0),
                float(f.get("tickSize") or 0),
            )
    return 0.0, 0.0, 0.0


def _extract_percent_price(filters: List[dict]) -> Tuple[float, float, float, float]:
    """Zwraca (bidMultUp, bidMultDown, askMultUp, askMultDown) z PERCENT_PRICE_BY_SIDE."""
    for f in filters:
        if f.get("filterType") in ("PERCENT_PRICE_BY_SIDE", "PERCENT_PRICE"):
            return (
                float(f.get("bidMultiplierUp") or f.get("multiplierUp") or 5.0),
                float(f.get("bidMultiplierDown") or f.get("multiplierDown") or 0.2),
                float(f.get("askMultiplierUp") or f.get("multiplierUp") or 5.0),
                float(f.get("askMultiplierDown") or f.get("multiplierDown") or 0.2),
            )
    return 5.0, 0.2, 5.0, 0.2


def _extract_notional(filters: List[dict]) -> Tuple[float, float, bool]:
    """Zwraca (min_notional, max_notional, apply_min_to_market) z NOTIONAL lub MIN_NOTIONAL."""
    for f in filters:
        ft = f.get("filterType", "")
        if ft in ("NOTIONAL", "MIN_NOTIONAL"):
            min_n = float(f.get("minNotional") or 0)
            max_n = float(f.get("maxNotional") or 0)
            apply_market = f.get("applyMinToMarket", True)
            if isinstance(apply_market, str):
                apply_market = apply_market.lower() not in ("false", "0", "no")
            return min_n, max_n, bool(apply_market)
    return 0.0, 0.0, True


def _extract_order_limits(filters: List[dict]) -> Tuple[int, int]:
    """Zwraca (maxNumOrders, maxNumAlgoOrders)."""
    max_orders = 0
    max_algo = 0
    for f in filters:
        ft = f.get("filterType", "")
        if ft == "MAX_NUM_ORDERS":
            max_orders = int(f.get("maxNumOrders") or 0)
        elif ft == "MAX_NUM_ALGO_ORDERS":
            max_algo = int(f.get("maxNumAlgoOrders") or 0)
    return max_orders, max_algo


def _precision_from_step(step: float) -> int:
    """Oblicz liczbę miejsc dziesiętnych z step_size."""
    if step <= 0:
        return 8
    if step >= 1:
        return 0
    try:
        return max(0, -int(math.floor(math.log10(step))))
    except (ValueError, ZeroDivisionError):
        return 8


def _has_spot_permission(symbol_info: dict) -> bool:
    """Sprawdź czy symbol ma uprawnienia SPOT (permissionSets lub permissions)."""
    # Nowy format: permissionSets — lista list uprawnień
    permission_sets = symbol_info.get("permissionSets") or []
    if permission_sets:
        for pset in permission_sets:
            if isinstance(pset, list) and "SPOT" in pset:
                return True
        return False
    # Stary format: permissions — lista string
    perms = symbol_info.get("permissions") or []
    return "SPOT" in perms


def _parse_symbol_info(sym: dict) -> Optional[SymbolMeta]:
    """Parsuj jeden rekord z exchangeInfo.symbols → SymbolMeta lub None."""
    if sym.get("status") != "TRADING":
        return None
    if not _has_spot_permission(sym):
        return None

    symbol = sym.get("symbol", "")
    if not symbol:
        return None

    filters = sym.get("filters") or []
    min_qty, max_qty, step_size = _extract_lot_size(filters)
    min_price, max_price, tick_size = _extract_price_filter(filters)
    bid_up, bid_down, ask_up, ask_down = _extract_percent_price(filters)
    min_notional, max_notional, apply_min_market = _extract_notional(filters)
    max_num_orders, max_num_algo = _extract_order_limits(filters)

    qty_prec = _precision_from_step(step_size)
    price_prec = _precision_from_step(tick_size)

    oco_allowed = bool(sym.get("ocoAllowed", False))

    return SymbolMeta(
        symbol=symbol,
        base_asset=sym.get("baseAsset", ""),
        quote_asset=sym.get("quoteAsset", ""),
        status="TRADING",
        is_spot=True,
        oco_allowed=oco_allowed,
        min_qty=min_qty,
        max_qty=max_qty,
        step_size=step_size,
        tick_size=tick_size,
        min_price=min_price,
        max_price=max_price,
        bid_mult_up=bid_up,
        bid_mult_down=bid_down,
        ask_mult_up=ask_up,
        ask_mult_down=ask_down,
        min_notional=min_notional,
        max_notional=max_notional,
        apply_min_to_market=apply_min_market,
        max_num_orders=max_num_orders,
        max_num_algo_orders=max_num_algo,
        qty_precision=qty_prec,
        price_precision=price_prec,
    )


def load_symbol_universe(
    binance_client,
    allowed_quotes: Optional[List[str]] = None,
    force_refresh: bool = False,
) -> Dict[str, SymbolMeta]:
    """
    Pobierz i parsuj pełny exchangeInfo Binance.

    Zwraca dict: symbol (str) → SymbolMeta.
    Wyniki są cache'owane przez _CACHE_TTL_SEC sekund.

    Args:
        binance_client:  instancja BinanceClient z metodą get_exchange_info()
        allowed_quotes:  lista walut quote do filtrowania (None = wszystkie)
        force_refresh:   pomiń cache
    """
    cache_key = "universe"
    with _CACHE_LOCK:
        if not force_refresh:
            cached = _CACHE.get(cache_key)
            if cached and (time.monotonic() - cached["ts"]) < _CACHE_TTL_SEC:
                return cached["data"]

    try:
        raw = binance_client.get_exchange_info()
    except Exception as exc:
        logger.error("load_symbol_universe: błąd get_exchange_info: %s", exc)
        with _CACHE_LOCK:
            stale = _CACHE.get(cache_key)
        return stale["data"] if stale else {}

    if not raw or "symbols" not in raw:
        logger.warning("load_symbol_universe: pusta odpowiedź exchangeInfo")
        with _CACHE_LOCK:
            stale = _CACHE.get(cache_key)
        return stale["data"] if stale else {}

    result: Dict[str, SymbolMeta] = {}
    skipped_perms = 0
    skipped_status = 0
    parsed = 0

    for sym in raw.get("symbols") or []:
        if sym.get("status") != "TRADING":
            skipped_status += 1
            continue
        if not _has_spot_permission(sym):
            skipped_perms += 1
            continue
        meta = _parse_symbol_info(sym)
        if meta is None:
            continue
        # Filtruj wg allowed_quotes jeśli podano
        if allowed_quotes:
            if (meta.quote_asset or "").upper() not in [q.upper() for q in allowed_quotes]:
                continue
        result[meta.symbol] = meta
        parsed += 1

    logger.info(
        "load_symbol_universe: parsed=%d skipped_status=%d skipped_perms=%d total_trading=%d",
        parsed, skipped_status, skipped_perms, len(result),
    )

    with _CACHE_LOCK:
        _CACHE[cache_key] = {"data": result, "ts": time.monotonic()}

    return result


def can_trade(meta: SymbolMeta, quote: Optional[str] = None) -> bool:
    """Sprawdź czy symbol nadaje się do handlu (wszystkie filtry spełnione)."""
    if meta is None or meta.status != "TRADING" or not meta.is_spot:
        return False
    if meta.step_size is None or meta.step_size <= 0:
        return False
    if meta.tick_size is None or meta.tick_size <= 0:
        return False
    if quote and (meta.quote_asset or "").upper() != quote.upper():
        return False
    return True


def round_qty(qty: float, meta: SymbolMeta) -> float:
    """
    Zaokrąglij qty do step_size (floor — nigdy przekroczymy saldo).
    Zwraca 0.0 jeśli wynik < min_qty.
    """
    step = meta.step_size or 0
    if step <= 0:
        return round(qty, 8)
    floored = math.floor(qty / step) * step
    prec = meta.qty_precision or 8
    floored = round(floored, prec)
    min_q = meta.min_qty or 0
    return floored if floored >= min_q else 0.0


def round_price(price: float, meta: SymbolMeta) -> float:
    """Zaokrąglij cenę do tick_size."""
    tick = meta.tick_size or 0
    if tick <= 0:
        return round(price, 8)
    rounded = round(price / tick) * tick
    prec = meta.price_precision or 8
    return round(rounded, prec)


def meets_min_notional(qty: float, price: float, meta: SymbolMeta) -> bool:
    """Sprawdź czy qty*price >= min_notional (zgodnie z apply_min_to_market)."""
    min_n = meta.min_notional or 0
    if min_n <= 0:
        return True
    # Dla market order sprawdzamy apply_min_to_market
    if not meta.apply_min_to_market:
        return True
    notional = qty * price
    return notional >= min_n


def check_price_filter(price: float, meta: SymbolMeta) -> Tuple[bool, str]:
    """
    Sprawdź PRICE_FILTER i PERCENT_PRICE_BY_SIDE.
    Zwraca (ok, reason_code).

    UWAGA: PERCENT_PRICE_BY_SIDE wymaga average_price z Binance.
    Jeśli average_price = 0, walidacja PERCENT jest pomijana.
    """
    if meta.min_price and meta.min_price > 0 and price < meta.min_price:
        return False, "price_below_min_price_filter"
    if meta.max_price and meta.max_price > 0 and price > meta.max_price:
        return False, "price_above_max_price_filter"
    return True, ""


def check_percent_price_side(
    price: float,
    side: str,
    avg_price: float,
    meta: SymbolMeta,
) -> Tuple[bool, str]:
    """
    Walidacja PERCENT_PRICE_BY_SIDE.
    avg_price = aktualna cena referencyjna (np. z 5-minutowego avg).
    Jeśli avg_price <= 0, pomijamy (nie mamy danych).
    """
    if avg_price <= 0:
        return True, ""
    s = side.upper()
    if s == "BUY":
        up = meta.bid_mult_up or 5.0
        down = meta.bid_mult_down or 0.2
        if price > avg_price * up:
            return False, "price_exceeds_percent_price_bid_up"
        if price < avg_price * down:
            return False, "price_below_percent_price_bid_down"
    elif s == "SELL":
        up = meta.ask_mult_up or 5.0
        down = meta.ask_mult_down or 0.2
        if price > avg_price * up:
            return False, "price_exceeds_percent_price_ask_up"
        if price < avg_price * down:
            return False, "price_below_percent_price_ask_down"
    return True, ""


def validate_order(
    symbol: str,
    side: str,
    qty: float,
    price: float,
    meta: SymbolMeta,
    avg_price: float = 0.0,
) -> Tuple[bool, str]:
    """
    Pełna walidacja zlecenia przed wysłaniem na Binance.

    Sprawdza:
      1. LOT_SIZE (min_qty, max_qty, step_size zgodność)
      2. PRICE_FILTER (min_price, max_price)
      3. PERCENT_PRICE_BY_SIDE (relative price bounds)
      4. MIN_NOTIONAL / NOTIONAL

    Zwraca (True, "") jeśli ok, (False, reason_code) jeśli błąd.
    """
    if not can_trade(meta):
        return False, "symbol_not_tradable"

    # LOT_SIZE
    if meta.min_qty and meta.min_qty > 0 and qty < meta.min_qty:
        return False, "qty_below_min_lot_size"
    if meta.max_qty and meta.max_qty > 0 and qty > meta.max_qty:
        return False, "qty_above_max_lot_size"
    if meta.step_size and meta.step_size > 0:
        remainder = abs(qty % meta.step_size)
        tol = meta.step_size * 1e-6
        if remainder > tol and (meta.step_size - remainder) > tol:
            return False, "qty_not_multiple_of_step_size"

    # PRICE_FILTER
    ok, code = check_price_filter(price, meta)
    if not ok:
        return False, code

    # PERCENT_PRICE_BY_SIDE
    ok, code = check_percent_price_side(price, side, avg_price, meta)
    if not ok:
        return False, code

    # NOTIONAL
    if not meets_min_notional(qty, price, meta):
        return False, "notional_below_min_notional_filter"

    return True, ""


def invalidate_cache() -> None:
    """Wyczyść cache (używaj po zmianie API keys / środowiska)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def set_cache_ttl(seconds: int) -> None:
    """Ustaw TTL cache (domyślnie 300s)."""
    global _CACHE_TTL_SEC
    _CACHE_TTL_SEC = max(10, int(seconds))
