from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from backend.symbol_universe import get_symbol_registry, validate_symbol

logger = logging.getLogger(__name__)

_QUOTE_CACHE_LOCK = threading.Lock()
_QUOTE_CACHE: Dict[str, Dict[str, Any]] = {}
_QUOTE_CACHE_TTL = float(30.0)


def _cache_get(symbol: str) -> Optional[Dict[str, Any]]:
    with _QUOTE_CACHE_LOCK:
        item = _QUOTE_CACHE.get(symbol)
        if not item:
            return None
        if (time.time() - float(item.get("cached_at") or 0.0)) > _QUOTE_CACHE_TTL:
            return None
        return dict(item)


def _cache_set(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    data["cached_at"] = time.time()
    with _QUOTE_CACHE_LOCK:
        _QUOTE_CACHE[symbol] = data
    return data


def invalidate_quote_cache(symbol: Optional[str] = None) -> None:
    with _QUOTE_CACHE_LOCK:
        if symbol:
            _QUOTE_CACHE.pop(symbol, None)
        else:
            _QUOTE_CACHE.clear()


def get_validated_quote(
    symbol: str,
    *,
    binance_client: Any = None,
    retries: int = 2,
    allow_cache: bool = True,
) -> Dict[str, Any]:
    registry = get_symbol_registry(binance_client=binance_client)
    validation = validate_symbol(symbol, registry=registry)
    normalized = validation.get("symbol") or ""
    if not validation.get("valid"):
        cached = _cache_get(normalized) if allow_cache else None
        return {
            "success": False,
            "symbol": normalized,
            "error": "invalid_symbol",
            "validated_symbol": False,
            "quote_source": "cache" if cached else "validation",
            "cached_quote": cached,
        }

    if allow_cache:
        cached = _cache_get(normalized)
        if cached:
            cached["success"] = True
            cached["symbol"] = normalized
            cached["validated_symbol"] = True
            cached["quote_source"] = "cache"
            return cached

    if binance_client is None:
        try:
            from backend.binance_client import get_binance_client

            binance_client = get_binance_client()
        except Exception as exc:
            return {
                "success": False,
                "symbol": normalized,
                "error": f"binance_client_unavailable:{exc}",
                "validated_symbol": True,
                "quote_source": "none",
            }

    last_error = ""
    for attempt in range(max(1, retries) + 1):
        try:
            ticker = binance_client.get_ticker_price(normalized) or {}
            price = float(ticker.get("price") or 0.0)
            if price > 0:
                orderbook = {}
                try:
                    orderbook = binance_client.get_orderbook(normalized, 5) or {}
                except Exception:
                    orderbook = {}
                payload = {
                    "success": True,
                    "symbol": normalized,
                    "price": price,
                    "bid": float(((orderbook.get("bids") or [[0]])[0][0]) or 0.0),
                    "ask": float(((orderbook.get("asks") or [[0]])[0][0]) or 0.0),
                    "quote_source": "binance",
                    "validated_symbol": True,
                    "attempt": attempt + 1,
                }
                return _cache_set(normalized, payload)
            last_error = "empty_price"
        except Exception as exc:
            text = str(exc).lower()
            last_error = str(exc)
            if "404" in text or "invalid symbol" in text:
                break

    cached = _cache_get(normalized) if allow_cache else None
    if cached:
        cached["success"] = True
        cached["symbol"] = normalized
        cached["validated_symbol"] = True
        cached["quote_source"] = "cache"
        cached["fallback_reason"] = last_error or "primary_quote_failed"
        return cached

    logger.warning(
        "[quote_service_soft_fail] symbol=%s reason=%s",
        normalized,
        last_error or "unknown",
    )
    return {
        "success": False,
        "symbol": normalized,
        "error": "quote_unavailable",
        "validated_symbol": True,
        "quote_source": "soft_fail",
        "fallback_reason": last_error or "unknown",
    }
