"""
symbol_universe.py — Dynamiczne budowanie universe symboli tradingowych

Odpowiada za:
1. Pobranie pełnej listy symboli z Binance
2. Filtrowanie: test, dev, inactive, broken metadata
3. Budowanie universe wg quote_currency_mode: USDC | EUR | BOTH
4. Priorytetyzacja symboli z WATCHLIST
5. Trzy warstwy: exchange → eligible → priority

Architektura:
- Exchange Universe: wszystkie dostępne symbole z Binance
- Eligible Universe: po filtracji (test/dev/inactive usunięte)
- Priority Universe: symbole z WATCHLIST (jeśli WATCHLIST_PRIORITY_ONLY=true)

Semantyka:
- WATCHLIST NIE limituje full universe — to opcjonalna priorytetyzacja
- Full universe zawsze obejmuje wszystkie eligible symbole
- Priority Universe może być podzbiorem dla personalizacji
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REGISTRY_LOCK = threading.Lock()
_REGISTRY_CACHE: Optional[Dict[str, Any]] = None
_REGISTRY_CACHE_AT: float = 0.0
_REGISTRY_CACHE_TTL: float = float(os.getenv("SYMBOL_UNIVERSE_CACHE_TTL", "300") or 300)

# Test/dev symbole, które NIGDY nie powinny być handlowane
TEST_SYMBOLS = {
    "TESTUSDC",
    "TESTEUR",
    "DEVSDC",
    "DEVEUR",
    "DEMOBTC",
    "BTCTEST",
    "ETHTEST",
}

# Symbole które są syntetyczne, zbyteczne itp
SYNTHETIC_SYMBOLS = {
    "BUSDUSDT",
    "USBTC",  # synthetic BTC
    "USETH",  # synthetic ETH
}


def _is_test_or_dev_symbol(symbol: str) -> bool:
    """Zwraca True jeśli symbol wygląda na test/dev."""
    s = symbol.upper()
    if s in TEST_SYMBOLS or s in SYNTHETIC_SYMBOLS:
        return True
    if "TEST" in s or "DEV" in s or "DEMO" in s:
        return True
    return False


def fetch_exchange_symbols(
    binance_client: Any,
    quote_mode: str = "USDC",  # USDC | EUR | BOTH
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """
    Pobierz wszystkie dostępne symbole z Binance.

    Args:
        binance_client: Binance client API
        quote_mode: USDC | EUR | BOTH

    Returns:
        (symbols_list, rejected_list, diagnostics_dict)

    Diagnostyka zawiera:
        - total_symbols: ile pobrano z giełdy
        - test_symbols: ile odrzucono jako test/dev
        - inactive_symbols: ile odrzucono jako nieaktywne
        - broken_metadata: ile ma złe metadane
        - final_count: ile symboli w výsledku
    """
    logger.info("[symbol_universe] fetching exchange symbols quote_mode=%s", quote_mode)

    exchange_info = binance_client.get_exchange_info()
    all_symbols = []
    rejected = []
    diagnostics = {
        "total_symbols": 0,
        "test_symbols": 0,
        "inactive_symbols": 0,
        "broken_metadata": 0,
        "wrong_quote": 0,
        "final_count": 0,
    }

    symbols_to_check = exchange_info.get("symbols", [])
    diagnostics["total_symbols"] = len(symbols_to_check)

    for sym_info in symbols_to_check:
        symbol = sym_info.get("symbol", "").upper()
        if not symbol:
            continue

        # 1. Test/dev check
        if _is_test_or_dev_symbol(symbol):
            diagnostics["test_symbols"] += 1
            rejected.append(f"{symbol} (test/dev)")
            continue

        # 2. Status check (musi być TRADING)
        status = sym_info.get("status", "").upper()
        if status != "TRADING":
            diagnostics["inactive_symbols"] += 1
            rejected.append(f"{symbol} (status={status})")
            continue

        # 3. Quote currency check
        quote_currency = symbol[-4:].upper()  # ostatnie 4 znaki to zwykle quote
        # Dokładniejszy check: ostatni element podzielony
        for filter_info in sym_info.get("filters", []):
            if filter_info.get("filterType") == "NOTIONAL":
                # OK, ma NOTIONAL filter = jest poprawny
                break
        else:
            # Brak NOTIONAL filter = podejrzane metadane
            diagnostics["broken_metadata"] += 1
            rejected.append(f"{symbol} (no NOTIONAL filter)")
            continue

        # 4. Quote mode check
        if quote_mode.upper() == "USDC":
            if not symbol.endswith("USDC"):
                diagnostics["wrong_quote"] += 1
                continue
        elif quote_mode.upper() == "EUR":
            if not symbol.endswith("EUR"):
                diagnostics["wrong_quote"] += 1
                continue
        elif quote_mode.upper() != "BOTH":
            continue

        # BOTH mode: akceptuj zarówno EUR jak i USDC
        if quote_mode.upper() == "BOTH":
            if not (symbol.endswith("USDC") or symbol.endswith("EUR")):
                diagnostics["wrong_quote"] += 1
                continue

        all_symbols.append(symbol)

    diagnostics["final_count"] = len(all_symbols)

    logger.info(
        "[symbol_universe_fetched] total=%d test=%d inactive=%d broken=%d wrong_quote=%d final=%d",
        diagnostics["total_symbols"],
        diagnostics["test_symbols"],
        diagnostics["inactive_symbols"],
        diagnostics["broken_metadata"],
        diagnostics["wrong_quote"],
        diagnostics["final_count"],
    )

    return all_symbols, rejected, diagnostics


def build_priority_symbols_from_watchlist(
    watchlist: str,  # "BTC,ETH,SOL,..."
    quote_mode: str = "USDC",
) -> List[str]:
    """
    Buduj priority universe z WATCHLIST.

    Args:
        watchlist: "BTC,ETH,SOL,..." — aktywa bazowe bez quote currency
        quote_mode: USDC | EUR | BOTH

    Returns:
        Lista symboli np. ["BTCUSDC", "ETHUSDC", ...]
    """
    if not watchlist or not watchlist.strip():
        return []

    symbols = []
    assets = [a.strip().upper() for a in watchlist.split(",") if a.strip()]

    for asset in assets:
        if quote_mode.upper() in ("USDC", "BOTH"):
            symbols.append(f"{asset}USDC")
        if quote_mode.upper() in ("EUR", "BOTH"):
            symbols.append(f"{asset}EUR")

    logger.debug(
        "[priority_symbols] watchlist=%d assets=%d symbols=%d",
        len(assets),
        len(assets),
        len(symbols),
    )

    return symbols


def merge_universes(
    eligible: List[str],
    priority: List[str],
    priority_only: bool = False,
) -> Tuple[List[str], List[str], List[str]]:
    """
    Scal universe eligible (pełne) i priority (watchlist).

    Args:
        eligible: pełna lista symboli po filtracji
        priority: symbole z WATCHLIST
        priority_only: jeśli True, zwróć TYLKO priority (podzbiór); jeśli False, zwróć eligible + priority sorted

    Returns:
        (final_universe, eligible_only, priority_set)

    Jeśli priority_only=True: final_universe = priority ∩ eligible (przecięcie)
    Jeśli priority_only=False: final_universe = eligible + priority (union, priority first)
    """
    priority_set = set(priority)
    eligible_set = set(eligible)

    if priority_only:
        # Zwróć TYLKO symbole które są zarówno na prioritylist jak i w eligible universe
        final = sorted(priority_set & eligible_set)
        eligible_only = sorted(eligible_set - priority_set)
    else:
        # Zwróć eligible universe, ale sort by priority (priority symbole na czoło)
        final = sorted(priority_set) + sorted(eligible_set - priority_set)
        eligible_only = sorted(eligible_set - priority_set)

    logger.debug(
        "[merge_universes] priority_only=%s eligible=%d priority=%d final=%d",
        priority_only,
        len(eligible),
        len(priority),
        len(final),
    )

    return final, eligible_only, sorted(priority_set)


def get_universe_diagnostics(
    exchange_total: int,
    eligible_count: int,
    priority_count: int,
    rejected_details: Dict[str, int],
) -> str:
    """Formatuj diagnostykę universe."""
    msg = (
        f"Exchange symbols total: {exchange_total}\n"
        f"Eligible (after filter): {eligible_count}\n"
        f"Priority (watchlist): {priority_count}\n"
        f"Rejected breakdown: {rejected_details}"
    )
    return msg


def _normalize_symbol(symbol: Optional[str]) -> str:
    return (
        str(symbol or "")
        .strip()
        .replace(" ", "")
        .replace("/", "")
        .replace("-", "")
        .upper()
    )


def _allowed_quotes() -> List[str]:
    raw = os.getenv("ALLOWED_QUOTES", "USDC,USDT,EUR")
    quotes: List[str] = []
    for item in str(raw).split(","):
        q = item.strip().upper()
        if q and q not in quotes:
            quotes.append(q)
    return quotes or ["USDC", "USDT", "EUR"]


def _watchlist_symbols(user_watchlist: Optional[List[str]], quotes: List[str]) -> List[str]:
    watchlist = list(user_watchlist or [])
    out: List[str] = []
    for item in watchlist:
        normalized = _normalize_symbol(item)
        if not normalized:
            continue
        if any(normalized.endswith(q) for q in quotes):
            if normalized not in out:
                out.append(normalized)
            continue
        for q in quotes:
            sym = f"{normalized}{q}"
            if sym not in out:
                out.append(sym)
    return out


def build_symbol_registry(
    binance_client: Any,
    *,
    allowed_quotes: Optional[List[str]] = None,
    user_watchlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    quotes = [q.upper() for q in (allowed_quotes or _allowed_quotes()) if q]
    allowed_symbols = binance_client.get_allowed_symbols() or {}

    metadata: Dict[str, Dict[str, Any]] = {}
    full_universe: List[str] = []
    tradable_universe: List[str] = []
    quote_filtered_universe: List[str] = []
    by_base: Dict[str, List[str]] = {}

    for symbol, meta in allowed_symbols.items():
        sym = _normalize_symbol(symbol)
        if not sym or _is_test_or_dev_symbol(sym):
            continue
        quote_asset = str((meta or {}).get("quote_asset") or "").upper()
        base_asset = str((meta or {}).get("base_asset") or "").upper()
        md = {
            "symbol": sym,
            "base_asset": base_asset,
            "quote_asset": quote_asset,
            "min_qty": (meta or {}).get("min_qty"),
            "step_size": (meta or {}).get("step_size"),
            "min_notional": (meta or {}).get("min_notional"),
            "tradable": True,
            "quote_allowed": quote_asset in quotes,
        }
        metadata[sym] = md
        full_universe.append(sym)
        tradable_universe.append(sym)
        by_base.setdefault(base_asset, []).append(sym)
        if quote_asset in quotes:
            quote_filtered_universe.append(sym)

    full_universe = sorted(full_universe)
    tradable_universe = sorted(tradable_universe)
    quote_filtered_universe = sorted(quote_filtered_universe)
    watchlist_symbols = [
        s for s in _watchlist_symbols(user_watchlist, quotes) if s in metadata
    ]

    return {
        "checked_at": time.time(),
        "allowed_quotes": quotes,
        "metadata": metadata,
        "full_universe": full_universe,
        "tradable_universe": tradable_universe,
        "quote_filtered_universe": quote_filtered_universe,
        "user_watchlist": sorted(watchlist_symbols),
        "by_base_asset": {k: sorted(v) for k, v in by_base.items()},
    }


def get_symbol_registry(
    *,
    force: bool = False,
    binance_client: Any = None,
    allowed_quotes: Optional[List[str]] = None,
    user_watchlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    global _REGISTRY_CACHE, _REGISTRY_CACHE_AT

    now = time.monotonic()
    with _REGISTRY_LOCK:
        if (
            not force
            and _REGISTRY_CACHE is not None
            and (now - _REGISTRY_CACHE_AT) < _REGISTRY_CACHE_TTL
        ):
            return _REGISTRY_CACHE

    if binance_client is None:
        try:
            from backend.binance_client import get_binance_client

            binance_client = get_binance_client()
        except Exception:
            binance_client = None

    registry = {
        "checked_at": time.time(),
        "allowed_quotes": [q.upper() for q in (allowed_quotes or _allowed_quotes())],
        "metadata": {},
        "full_universe": [],
        "tradable_universe": [],
        "quote_filtered_universe": [],
        "user_watchlist": [],
        "by_base_asset": {},
        "error": None,
    }
    if binance_client is not None:
        try:
            registry = build_symbol_registry(
                binance_client,
                allowed_quotes=allowed_quotes,
                user_watchlist=user_watchlist,
            )
        except Exception as exc:
            registry["error"] = str(exc)

    with _REGISTRY_LOCK:
        if registry.get("metadata"):
            _REGISTRY_CACHE = registry
            _REGISTRY_CACHE_AT = now
            return registry
        if _REGISTRY_CACHE is not None:
            return _REGISTRY_CACHE
    return registry


def validate_symbol(
    symbol: Optional[str],
    *,
    registry: Optional[Dict[str, Any]] = None,
    require_quote_filtered: bool = True,
) -> Dict[str, Any]:
    registry = registry or get_symbol_registry()
    sym = _normalize_symbol(symbol)
    metadata = (registry.get("metadata") or {}).get(sym)
    allowed_set_name = "quote_filtered_universe" if require_quote_filtered else "tradable_universe"
    allowed_set = set(registry.get(allowed_set_name) or [])
    valid = bool(metadata) and sym in allowed_set
    return {
        "symbol": sym,
        "valid": valid,
        "exists_on_exchange": bool(metadata),
        "in_active_universe": sym in allowed_set,
        "metadata": metadata,
        "reason": (
            "ok"
            if valid
            else (
                "not_in_exchange"
                if not metadata
                else "not_in_active_universe"
            )
        ),
    }


def resolve_asset_symbol(
    asset_or_symbol: Optional[str],
    *,
    registry: Optional[Dict[str, Any]] = None,
    preferred_quotes: Optional[List[str]] = None,
) -> Optional[str]:
    registry = registry or get_symbol_registry()
    raw = _normalize_symbol(asset_or_symbol)
    if not raw:
        return None
    validation = validate_symbol(raw, registry=registry)
    if validation.get("valid"):
        return raw

    quotes = [q.upper() for q in (preferred_quotes or registry.get("allowed_quotes") or [])]
    metadata = registry.get("metadata") or {}
    for quote in quotes:
        sym = f"{raw}{quote}"
        if sym in metadata and sym in set(registry.get("quote_filtered_universe") or []):
            return sym

    by_base = registry.get("by_base_asset") or {}
    for sym in by_base.get(raw, []):
        if sym in set(registry.get("quote_filtered_universe") or []):
            return sym
    return None


def get_symbol_universe_stats() -> Dict[str, Any]:
    registry = get_symbol_registry()
    filtered = registry.get("quote_filtered_universe") or []
    scan_cap = int(os.getenv("MAX_SYMBOL_SCAN_PER_CYCLE", "100") or 100)
    return {
        "full_count": len(registry.get("full_universe") or []),
        "tradable_count": len(registry.get("tradable_universe") or []),
        "filtered_count": len(filtered),
        "watchlist_count": len(registry.get("user_watchlist") or []),
        "active_scanned_count": min(len(filtered), max(1, scan_cap)),
        "allowed_quotes": registry.get("allowed_quotes") or [],
        "registry_error": registry.get("error"),
    }


def get_rotating_universe_slice(
    *,
    registry: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Tuple[List[str], int]:
    registry = registry or get_symbol_registry()
    universe = list(registry.get("quote_filtered_universe") or [])
    if not universe:
        return [], 0
    size = max(1, int(limit or int(os.getenv("MAX_SYMBOL_SCAN_PER_CYCLE", "100") or 100)))
    start = max(0, int(offset or 0)) % len(universe)
    if len(universe) <= size:
        return universe, 0
    end = start + size
    if end <= len(universe):
        slice_symbols = universe[start:end]
    else:
        slice_symbols = universe[start:] + universe[: end - len(universe)]
    return slice_symbols, end % len(universe)
