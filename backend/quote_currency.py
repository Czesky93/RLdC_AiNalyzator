"""
quote_currency.py — Quote Currency Mode: EUR / USDC / BOTH

Odpowiada za:
- filtrowanie symboli wg aktywnego trybu
- mapowanie asset bazowego → para rynkowa preferowanej waluty kwotowanej
- ocenę potrzeby auto-konwersji EUR→USDC
- wykonanie konwersji (przez Binance EURUSDC)
- reason codes dla każdej decyzji

Reason codes:
  quote_mode_eur_only_blocked       — para USDC odrzucona w trybie EUR
  quote_mode_usdc_only_blocked      — para EUR odrzucona w trybie USDC
  quote_mode_both_allowed           — oba tryby dozwolone
  funding_conversion_skipped_small  — za mało EUR do konwersji
  funding_conversion_cooldown       — cooldown aktywny
  funding_conversion_insufficient   — brak wystarczającego EUR po rezerwie
  funding_conversion_executed       — konwersja wykonana
  funding_conversion_failed         — błąd konwersji
  usdc_balance_sufficient           — wystarczające USDC, konwersja zbędna
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Mapa: asset bazowy → (symbol EUR, symbol USDC)
_ASSET_QUOTE_MAP: dict[str, tuple[str, str]] = {
    "BTC": ("BTCEUR", "BTCUSDC"),
    "ETH": ("ETHEUR", "ETHUSDC"),
    "SOL": ("SOLEUR", "SOLUSDC"),
    "BNB": ("BNBEUR", "BNBUSDC"),
    "XRP": ("XRPEUR", "XRPUSDC"),
    "ADA": ("ADAEUR", "ADAUSDC"),
    "DOGE": ("DOGEEUR", "DOGEUSDC"),
    "SHIB": ("SHIBEUR", "SHIBUSDC"),
    "ETC": ("ETCEUR", "ETCUSDC"),
    "SXT": ("SXTEUR", "SXTUSDC"),
    "WLFI": ("WLFIEUR", "WLFIUSDC"),
    # Dodatkowe aktywa z watchlisty
    "PEPE": ("PEPEEUR", "PEPEUSDC"),
    "AVAX": ("AVAXEUR", "AVAXUSDC"),
    "MATIC": ("MATICEUR", "MATICUSDC"),
    "DOT": ("DOTEUR", "DOTUSDC"),
    "LINK": ("LINKEUR", "LINKUSDC"),
    "UNI": ("UNIEUR", "UNIUSDC"),
    "ARB": ("ARBEUR", "ARBUSDC"),
    "OP": ("OPEUR", "OPUSDC"),
    "EGLD": ("EGLDEUR", "EGLDUSDC"),
    "TON": ("TONEUR", "TONUSDC"),
    "TRX": ("TRXEUR", "TRXUSDC"),
    "LTC": ("LTCEUR", "LTCUSDC"),
    "ATOM": ("ATOMEUR", "ATOMUSDC"),
    "FIL": ("FILEUR", "FILUSDC"),
    "APT": ("APTEUR", "APTUSDC"),
    "SUI": ("SUIEUR", "SUIUSDC"),
    "INJ": ("INJEUR", "INJUSDC"),
    "FTM": ("FTMEUR", "FTMUSDC"),
    "NEAR": ("NEAREUR", "NEARUSDC"),
    "ICP": ("ICPEUR", "ICPUSDC"),
    # Dodatkowe aktywa z watchlisty
    "PEPE": ("PEPEEUR", "PEPEUSDC"),
    "AVAX": ("AVAXEUR", "AVAXUSDC"),
    "MATIC": ("MATICEUR", "MATICUSDC"),
    "DOT": ("DOTEUR", "DOTUSDC"),
    "LINK": ("LINKEUR", "LINKUSDC"),
    "UNI": ("UNIEUR", "UNIUSDC"),
    "ARB": ("ARBEUR", "ARBUSDC"),
    "OP": ("OPEUR", "OPUSDC"),
    "EGLD": ("EGLDEUR", "EGLDUSDC"),
    "TON": ("TONEUR", "TONUSDC"),
    "TRX": ("TRXEUR", "TRXUSDC"),
    "LTC": ("LTCEUR", "LTCUSDC"),
    "ATOM": ("ATOMEUR", "ATOMUSDC"),
    "FIL": ("FILEUR", "FILUSDC"),
    "APT": ("APTEUR", "APTUSDC"),
    "SUI": ("SUIEUR", "SUIUSDC"),
    "INJ": ("INJEUR", "INJUSDC"),
    "FTM": ("FTMEUR", "FTMUSDC"),
    "NEAR": ("NEAREUR", "NEARUSDC"),
    "ICP": ("ICPEUR", "ICPUSDC"),
}

# Para konwersji EUR→USDC na Binance
_EUR_USDC_PAIR = "EURUSDC"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_required_quote_usdc(
    min_buy_reference_eur: float,
    binance_client: Any = None,
    *,
    exchange_min_notional: float = 0.0,
) -> tuple[float, dict]:
    """
    Warstwa referencyjna → USDC.

    Przelicza minimalny zakup wyrażony referencyjnie w EUR na USDC (canonical quote).
    Zwraca (required_usdc, meta).

    Cel: JEDYNE miejsce gdzie min_buy_reference_eur jest używany do obliczeń.
    Po tym kroku cały execution layer operuje wyłącznie na USDC.
    """
    rate, rate_source = resolve_eur_usdc_rate(binance_client)
    ref_eur = max(0.0, float(min_buy_reference_eur or 0.0))
    usdc_from_ref = ref_eur * max(rate, 1e-9)
    required_usdc = max(usdc_from_ref, float(exchange_min_notional or 0.0))
    return required_usdc, {
        "quote_asset": "USDC",
        "min_buy_reference_eur": ref_eur,
        "eur_usdc_rate": rate,
        "rate_source": rate_source,
        "required_quote_usdc": required_usdc,
        "exchange_min_notional": float(exchange_min_notional or 0.0),
    }


def fund_usdc_from_eur_if_needed(
    binance_client: Any,
    *,
    required_usdc: float,
    available_usdc: float,
    available_eur: float,
    fee_buffer_pct: float = 0.01,
    db: Any = None,
) -> dict:
    """
    Funding conversion layer: EUR → USDC tylko gdy potrzebne.

    Logika:
      1. Jeśli dostępne USDC ≥ required_usdc → OK, brak konwersji.
      2. Jeśli USDC za mało, ale EUR wystarczy na brakującą kwotę → konwertuj EUR→USDC.
      3. Jeśli ani USDC ani EUR nie wystarczają → błąd z USDC-first komunikatem.

    Zwraca dict z:
      - ok (bool)
      - reason_code
      - available_usdc_after
      - missing_usdc (jeśli ok=False)
      - converted (bool)
      - conversion_result (jeśli konwersja)
    """
    req = max(0.0, float(required_usdc or 0.0))
    avail_usdc = max(0.0, float(available_usdc or 0.0))
    avail_eur = max(0.0, float(available_eur or 0.0))

    if avail_usdc >= req:
        return {
            "ok": True,
            "reason_code": "usdc_balance_sufficient",
            "available_usdc_after": avail_usdc,
            "converted": False,
            "funding_added_usdc": 0.0,
            "missing_usdc": 0.0,
            "required_usdc": req,
        }

    missing_usdc = req - avail_usdc
    rate, rate_source = resolve_eur_usdc_rate(binance_client)
    eur_needed = missing_usdc / max(rate, 1e-9) * (1.0 + fee_buffer_pct)

    if avail_eur < eur_needed:
        return {
            "ok": False,
            "reason_code": "insufficient_usdc_and_eur",
            "available_usdc": avail_usdc,
            "available_eur": avail_eur,
            "required_usdc": req,
            "missing_usdc": round(missing_usdc, 6),
            "eur_needed_for_conversion": round(eur_needed, 6),
            "eur_usdc_rate": rate,
            "rate_source": rate_source,
            "message": (
                f"Za mało USDC: dostępne {avail_usdc:.4f} USDC, "
                f"wymagane {req:.4f} USDC. "
                f"Brak EUR do konwersji: dostępne {avail_eur:.2f} EUR, "
                f"potrzebne {eur_needed:.2f} EUR"
            ),
        }

    # Wykonaj konwersję fundingową
    logger.info(
        "funding_conversion_started: brakuje %.4f USDC, konwertuję %.2f EUR (rate=%.6f, source=%s)",
        missing_usdc,
        eur_needed,
        rate,
        rate_source,
    )
    if db is not None:
        try:
            from backend.system_logger import log_to_db

            log_to_db(
                "INFO",
                "funding_conversion",
                f"funding_conversion_started: missing_usdc={missing_usdc:.4f} "
                f"eur_to_convert={eur_needed:.2f} rate={rate:.6f} source={rate_source}",
                db=db,
            )
        except Exception:
            pass

    conv_result = execute_conversion_eur_to_usdc(
        binance_client, amount_eur=eur_needed, db=db
    )

    if not conv_result.get("executed"):
        conversion_reason_code = str(
            conv_result.get("reason_code") or "funding_conversion_failed"
        )
        logger.error(
            "funding_conversion_failed: reason=%s detail=%s",
            conversion_reason_code,
            conv_result.get("detail"),
        )
        if db is not None:
            try:
                from backend.system_logger import log_to_db

                log_to_db(
                    "ERROR",
                    "funding_conversion",
                    f"funding_conversion_failed: reason={conv_result.get('reason_code')} "
                    f"detail={conv_result.get('detail')}",
                    db=db,
                )
            except Exception:
                pass
        return {
            "ok": False,
            "reason_code": "funding_conversion_failed",
            "conversion_reason_code": conversion_reason_code,
            "conversion_detail": conv_result.get("detail"),
            "available_usdc": avail_usdc,
            "required_usdc": req,
            "missing_usdc": round(missing_usdc, 6),
            "converted": False,
            "funding_added_usdc": 0.0,
            "conversion_result": conv_result,
            "message": (
                "Konwersja EUR->USDC nie powiodła się: "
                f"{conversion_reason_code} ({conv_result.get('detail') or 'brak szczegółów'})"
            ),
        }

    # Konwersja udana — odśwież saldo
    try:
        refreshed_balances = binance_client.get_balances() or []
        usdc_after = next(
            (
                float(b.get("free", 0))
                for b in refreshed_balances
                if b.get("asset") == "USDC"
            ),
            avail_usdc + missing_usdc,
        )
    except Exception:
        usdc_after = avail_usdc + missing_usdc

    logger.info(
        "funding_conversion_filled: USDC before=%.4f after=%.4f orderId=%s",
        avail_usdc,
        usdc_after,
        conv_result.get("order_id"),
    )
    if db is not None:
        try:
            from backend.system_logger import log_to_db

            log_to_db(
                "INFO",
                "funding_conversion",
                f"funding_conversion_filled: usdc_before={avail_usdc:.4f} "
                f"usdc_after={usdc_after:.4f} orderId={conv_result.get('order_id')}",
                db=db,
            )
        except Exception:
            pass

    if usdc_after < req:
        return {
            "ok": False,
            "reason_code": "insufficient_usdc_after_conversion",
            "available_usdc": usdc_after,
            "required_usdc": req,
            "missing_usdc": round(req - usdc_after, 6),
            "converted": True,
            "conversion_result": conv_result,
        }

    return {
        "ok": True,
        "reason_code": "funding_conversion_filled",
        "available_usdc_after": usdc_after,
        "converted": True,
        "funding_added_usdc": max(0.0, usdc_after - avail_usdc),
        "missing_usdc": 0.0,
        "required_usdc": req,
        "conversion_result": conv_result,
    }


def ensure_usdc_balance_for_order(
    binance_client: Any,
    *,
    symbol: str,
    required_usdc: float,
    fee_buffer_pct: float = 0.01,
    db: Any = None,
) -> dict:
    """
    Upewnij się, że konto ma wystarczające USDC dla zlecenia XXXUSDC.
    Używa fund_usdc_from_eur_if_needed jako fallback.

    Dla par EUR (XXXEUR): sprawdza tylko saldo EUR, bez konwersji.
    """
    quote = _get_quote_from_symbol(str(symbol or "").upper()) or "USDC"
    try:
        balances = binance_client.get_balances() or []
        bal_map = {
            str(b.get("asset") or "").upper(): float(b.get("free", 0) or 0)
            for b in balances
        }
    except Exception:
        bal_map = {}

    if quote == "USDC":
        avail_usdc = bal_map.get("USDC", 0.0)
        avail_eur = bal_map.get("EUR", 0.0)
        return fund_usdc_from_eur_if_needed(
            binance_client,
            required_usdc=required_usdc,
            available_usdc=avail_usdc,
            available_eur=avail_eur,
            fee_buffer_pct=fee_buffer_pct,
            db=db,
        )

    # Para EUR — sprawdź EUR (bez konwersji)
    avail_eur = bal_map.get("EUR", 0.0)
    if avail_eur >= required_usdc:  # required_usdc jest tu w EUR dla par EUR
        return {
            "ok": True,
            "reason_code": "eur_balance_sufficient",
            "available_eur": avail_eur,
            "required_eur": required_usdc,
            "converted": False,
        }
    return {
        "ok": False,
        "reason_code": "insufficient_eur",
        "available_eur": avail_eur,
        "required_eur": required_usdc,
        "missing_eur": round(required_usdc - avail_eur, 6),
        "message": (
            f"Za mało EUR: dostępne {avail_eur:.2f} EUR, wymagane {required_usdc:.2f} EUR"
        ),
    }


def enforce_final_min_quote_usdc(
    qty: float,
    price: float,
    required_min_notional: float,
    step_size: float = 0.0,
) -> tuple[float, dict]:
    """
    Ostatnia linia obrony przed wysłaniem za małego orderu na giełdę.

    Wywołaj tuż przed create_order. Jeżeli qty * price < required_min_notional,
    podnosimy qty do minimalnego poziomu (z uwzględnieniem step_size).

    Zwraca (final_qty, meta_dict).
    meta_dict["bumped"] = True gdy qty zostało podniesione.
    """
    import math

    final_qty = max(0.0, float(qty))
    current_notional = final_qty * float(price) if float(price) > 0 else 0.0
    min_notional = float(required_min_notional)

    if min_notional <= 0 or float(price) <= 0:
        return final_qty, {
            "bumped": False,
            "old_qty": final_qty,
            "new_qty": final_qty,
            "current_notional": current_notional,
            "required_min_notional": min_notional,
            "reason": "no_min_or_no_price",
        }

    if current_notional >= min_notional:
        return final_qty, {
            "bumped": False,
            "old_qty": final_qty,
            "new_qty": final_qty,
            "current_notional": current_notional,
            "required_min_notional": min_notional,
            "reason": "already_sufficient",
        }

    # Qty jest za mała — podnosimy
    old_qty = final_qty
    needed_qty = min_notional / float(price)
    step = float(step_size)
    if step > 0:
        needed_qty = math.ceil(needed_qty / step) * step
        decimals = max(0, -int(math.floor(math.log10(step))))
        needed_qty = round(needed_qty, decimals)
    final_qty = max(final_qty, needed_qty)

    return final_qty, {
        "bumped": True,
        "old_qty": old_qty,
        "new_qty": final_qty,
        "old_notional": current_notional,
        "new_notional": final_qty * float(price),
        "required_min_notional": min_notional,
        "reason": "bumped_to_meet_min_notional",
    }


def _get_quote_from_symbol(symbol: str) -> Optional[str]:
    """Zwraca walutę kwotowaną symbolu: 'EUR', 'USDC' albo None."""
    if symbol.endswith("USDC"):
        return "USDC"
    if symbol.endswith("EUR"):
        return "EUR"
    return None


def is_test_symbol(symbol: str) -> bool:
    """Zwraca True dla symboli testowych, które nie powinny trafiać do LIVE."""
    sym = str(symbol or "").strip().upper()
    return sym.startswith("TEST") or "TEST" in sym


def get_base_asset(symbol: str) -> Optional[str]:
    """Zwraca asset bazowy z symbolu (np. BTCEUR → BTC)."""
    if symbol.endswith("USDC"):
        return symbol[:-4]
    if symbol.endswith("EUR"):
        return symbol[:-3]
    return None


def get_supported_base_assets() -> list[str]:
    """Zwraca listę wszystkich wspieranych aktywów bazowych (mają obie quote currencies)."""
    return list(_ASSET_QUOTE_MAP.keys())


def resolve_eur_usdc_rate(binance_client: Any = None) -> tuple[float, str]:
    """
    Zwraca kurs EUR->USDC.
    Kolejność: EURUSDC, potem odwrotność USDCEUR, na końcu bezpieczny fallback 1.0.
    """
    try:
        if binance_client is not None:
            t = binance_client.get_ticker_price("EURUSDC")
            if t and float(t.get("price") or 0) > 0:
                return float(t["price"]), "eurusdc_direct"
    except Exception:
        pass

    try:
        if binance_client is not None:
            t = binance_client.get_ticker_price("USDCEUR")
            p = float(t.get("price") or 0) if t else 0.0
            if p > 0:
                return 1.0 / p, "usdceur_inverse"
    except Exception:
        pass

    return 1.0, "stable_fallback_1_to_1"


def convert_eur_amount_to_quote(
    eur_amount: float,
    quote_asset: str,
    *,
    eur_usdc_rate: Optional[float] = None,
) -> float:
    """Przelicza kwotę EUR na docelową walutę quote (EUR/USDC)."""
    q = str(quote_asset or "EUR").upper()
    amount = max(0.0, float(eur_amount or 0.0))
    if q == "EUR":
        return amount
    if q == "USDC":
        rate = float(eur_usdc_rate or 0.0)
        if rate <= 0:
            rate = 1.0
        return amount * rate
    return amount


def get_markets_for_asset(asset: str) -> dict[str, str]:
    """
    Zwraca dostępne rynki dla aktywa bazowego.

    Returns: {"EUR": "BTCEUR", "USDC": "BTCUSDC"} lub {} jeśli nieznane aktywo.
    """
    entry = _ASSET_QUOTE_MAP.get(asset.upper())
    if not entry:
        return {}
    eur_sym, usdc_sym = entry
    return {"EUR": eur_sym, "USDC": usdc_sym}


def build_symbol_set(base_assets: list[str], mode: str) -> list[str]:
    """
    Buduje zestaw symboli dla podanych aktywów bazowych wg trybu quote currency.

    base_assets: ["BTC", "ETH", "SOL", ...]  (aktywa bazowe)
    mode: EUR | USDC | BOTH

    Returns: lista symboli do analizy/handlu, np. ["BTCEUR", "BTCUSDC", "ETHEUR", ...]
    """
    mode = (mode or "BOTH").upper()
    result: list[str] = []
    for asset in base_assets:
        entry = _ASSET_QUOTE_MAP.get(asset.upper())
        if not entry:
            continue
        eur_sym, usdc_sym = entry
        if mode == "EUR":
            if eur_sym not in result:
                result.append(eur_sym)
        elif mode == "USDC":
            if usdc_sym not in result:
                result.append(usdc_sym)
        else:  # BOTH
            if eur_sym not in result:
                result.append(eur_sym)
            if usdc_sym not in result:
                result.append(usdc_sym)
    return result


def expand_watchlist_for_mode(symbols: list[str], mode: str = "BOTH") -> list[str]:
    """
    Rozszerza listę symboli o brakujące warianty quote currency.

    Dla każdego symbolu wyciąga asset bazowy i na podstawie _ASSET_QUOTE_MAP
    dodaje brakujące warianty EUR/USDC/BOTH.

    Akceptuje zarówno symbole (BTCEUR, BTCUSDC) jak i bare base assets (BTC, ETH).
    Symbole spoza _ASSET_QUOTE_MAP są zachowane bez zmian.

    mode: BOTH → dodaje oba warianty (używaj przy budowaniu puli przed filtrowaniem)
          EUR  → zwraca tylko EUR warianty znanych aktywów
          USDC → zwraca tylko USDC warianty znanych aktywów

    Reason: warstwa logiczna — nie prosty filter końcówek.
    """
    mode = (mode or "BOTH").upper()

    # Zbierz base assets z listy (obsługuje "BTC", "BTCEUR", "BTCUSDC")
    known_bases: list[str] = []
    unknown_syms: list[str] = []
    for sym in symbols:
        sym_up = sym.upper().strip()
        if not sym_up:
            continue
        # Bare base asset
        if sym_up in _ASSET_QUOTE_MAP:
            if sym_up not in known_bases:
                known_bases.append(sym_up)
            continue
        # Symbol z quote currency
        base = get_base_asset(sym_up)
        if base and base in _ASSET_QUOTE_MAP:
            if base not in known_bases:
                known_bases.append(base)
        else:
            # Nieznany symbol — zachowaj bez zmian
            if sym_up not in unknown_syms:
                unknown_syms.append(sym_up)

    result: list[str] = []
    for base in known_bases:
        eur_sym, usdc_sym = _ASSET_QUOTE_MAP[base]
        if mode == "EUR":
            if eur_sym not in result:
                result.append(eur_sym)
        elif mode == "USDC":
            if usdc_sym not in result:
                result.append(usdc_sym)
        else:  # BOTH
            if eur_sym not in result:
                result.append(eur_sym)
            if usdc_sym not in result:
                result.append(usdc_sym)

    # Dołącz nieznane symbole bez zmian
    for sym in unknown_syms:
        if sym not in result:
            result.append(sym)

    return result


def preferred_symbol_for_asset(
    asset: str, mode: str, primary_quote: str
) -> Optional[str]:
    """
    Zwraca preferowany symbol dla danego assetu bazowego w aktualnym trybie.

    mode: EUR | USDC | BOTH
    primary_quote: EUR | USDC
    """
    asset = asset.upper()
    entry = _ASSET_QUOTE_MAP.get(asset)
    if not entry:
        return None
    eur_sym, usdc_sym = entry
    mode = (mode or "BOTH").upper()
    primary_quote = (primary_quote or "EUR").upper()

    if mode == "EUR":
        return eur_sym
    if mode == "USDC":
        return usdc_sym
    # BOTH — preferuj primary_quote
    if primary_quote == "USDC":
        return usdc_sym
    return eur_sym


# ---------------------------------------------------------------------------
# Symbol filter
# ---------------------------------------------------------------------------


def filter_symbols_by_quote_mode(symbols: list[str], mode: str) -> list[str]:
    """
    Zwraca tylko te symbole, które pasują do aktywnego trybu.

    mode: EUR | USDC | BOTH
    """
    mode = (mode or "BOTH").upper()
    if mode == "BOTH":
        return symbols
    result = []
    for sym in symbols:
        q = _get_quote_from_symbol(sym)
        if q == mode:
            result.append(sym)
    return result


def check_symbol_allowed(symbol: str, mode: str) -> tuple[bool, str]:
    """
    Sprawdza czy symbol jest dozwolony w danym trybie.
    Zwraca (allowed, reason_code).
    """
    mode = (mode or "BOTH").upper()
    if mode == "BOTH":
        return True, "quote_mode_both_allowed"
    q = _get_quote_from_symbol(symbol)
    if q is None:
        return True, "quote_mode_unknown_symbol"
    if q == mode:
        return True, f"quote_mode_{mode.lower()}_allowed"
    blocked_mode = "eur_only" if mode == "EUR" else "usdc_only"
    return False, f"quote_mode_{blocked_mode}_blocked"


# ---------------------------------------------------------------------------
# Natural language → quote mode
# ---------------------------------------------------------------------------

_NL_USDC_PHRASES = (
    "tylko usdc",
    "handluj tylko na usdc",
    "handluj na usdc",
    "ustaw quote usdc",
    "quote currency usdc",
    "primary usdc",
    "tryb usdc",
)
_NL_EUR_PHRASES = (
    "tylko eur",
    "handluj tylko na eur",
    "handluj na eur",
    "quote currency eur",
    "quote eur",
    "primary eur",
    "ustaw eur",
    "tryb eur",
)
_NL_BOTH_PHRASES = (
    "eur i usdc",
    "usdc i eur",
    "oba tryby",
    "tryb both",
    "tryb oba",
)
_NL_CONVERT_PHRASES = (
    "zamień eur na usdc",
    "zamien eur na usdc",
    "konwertuj eur",
    "skonwertuj eur do usdc",
)


def parse_nl_quote_command(text: str) -> Optional[dict]:
    """
    Parsuje naturalny język na polecenie quote-currency.
    Zwraca None jeśli nie dotyczy, lub dict z 'action' i parametrami.
    """
    t = " ".join((text or "").lower().split())
    if not t:
        return None

    # Trading ma wyższy priorytet: jeśli wykryto intencję handlową, nie interpretuj jako config.
    if re.search(r"\b(kup|sprzedaj|wymus|wymuś|zamknij|analizuj)\b", t):
        return None

    # Symbole pełnych par (np. SOLUSDC) nie są komendą quote-mode.
    if re.search(r"\b[a-z]{2,12}(usdc|usdt|usd|eur)\b", t):
        return None

    for phrase in _NL_CONVERT_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            return {"action": "convert_eur_to_usdc"}
    for phrase in _NL_BOTH_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            return {"action": "set_quote_mode", "mode": "BOTH"}
    for phrase in _NL_USDC_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            return {"action": "set_quote_mode", "mode": "USDC"}
    for phrase in _NL_EUR_PHRASES:
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            return {"action": "set_quote_mode", "mode": "EUR"}
    return None


# ---------------------------------------------------------------------------
# Auto-convert EUR → USDC
# ---------------------------------------------------------------------------

_last_conversion_time: Optional[datetime] = None
_conversion_timestamps: list[datetime] = []


def should_convert_eur_to_usdc(
    free_eur: float,
    free_usdc: float,
    target_usdc_buffer: float,
    min_eur_reserve: float,
    min_conversion_notional: float,
    conversion_cooldown_minutes: int,
    max_conversion_per_hour: int = 2,
) -> tuple[bool, str, float]:
    """
    Decyduje czy należy konwertować EUR→USDC.
    Zwraca (should_convert, reason_code, amount_to_convert).
    """
    global _last_conversion_time, _conversion_timestamps

    if free_usdc >= target_usdc_buffer:
        return False, "usdc_balance_sufficient", 0.0

    if _last_conversion_time is not None:
        elapsed = (
            datetime.now(timezone.utc) - _last_conversion_time
        ).total_seconds() / 60
        if elapsed < conversion_cooldown_minutes:
            return False, "funding_conversion_cooldown", 0.0

    now = datetime.now(timezone.utc)
    _conversion_timestamps = [
        ts for ts in _conversion_timestamps if (now - ts).total_seconds() <= 3600
    ]
    if len(_conversion_timestamps) >= max(1, int(max_conversion_per_hour or 1)):
        return False, "funding_conversion_cooldown", 0.0

    available_eur = free_eur - min_eur_reserve
    if available_eur < min_conversion_notional:
        if available_eur <= 0:
            return False, "funding_conversion_insufficient", 0.0
        return False, "funding_conversion_skipped_small", 0.0

    needed = target_usdc_buffer - free_usdc
    amount = min(available_eur, needed * 1.01)  # lekki naddatek na spread
    amount = max(0.0, amount)

    if amount < min_conversion_notional:
        return False, "funding_conversion_skipped_small", 0.0

    return True, "funding_conversion_required", round(amount, 2)


def execute_conversion_eur_to_usdc(
    binance_client: Any,
    amount_eur: float,
    db: Any = None,
) -> dict:
    """
    Wykonuje konwersję EUR→USDC na Binance (market order EURUSDC).
    Zwraca wynik z reason_code.
    """
    global _last_conversion_time, _conversion_timestamps
    result = {
        "action_type": "FUNDING_CONVERSION",
        "symbol": _EUR_USDC_PAIR,
        "direction": "EUR_TO_USDC",
        "amount_eur": amount_eur,
        "executed": False,
        "reason_code": "funding_conversion_failed",
        "detail": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # Dostosuj quantity do step_size EURUSDC (np. 0.1)
        import math as _math

        try:
            _sym_info = (binance_client.get_allowed_symbols() or {}).get(
                _EUR_USDC_PAIR, {}
            )
            _step = float(_sym_info.get("step_size") or 0.1)
            _min_qty = float(_sym_info.get("min_qty") or 0.1)
        except Exception:
            _step = 0.1
            _min_qty = 0.1
        adj_qty = _math.floor(amount_eur / _step) * _step
        adj_qty = round(adj_qty, max(0, int(round(-_math.log10(_step)))))
        if adj_qty < _min_qty:
            result["reason_code"] = "funding_conversion_skipped_small"
            result["detail"] = f"adj_qty={adj_qty} < min_qty={_min_qty}"
            return result

        order = binance_client.place_order(
            symbol=_EUR_USDC_PAIR,
            side="SELL",  # SELL EUR → otrzymujesz USDC
            order_type="MARKET",
            quantity=adj_qty,
        )
        # Sprawdź czy order się udał (nie ma _error)
        if not order or order.get("_error"):
            err_msg = (order or {}).get("error_message", "brak odpowiedzi Binance")
            result["detail"] = err_msg
            result["reason_code"] = "funding_conversion_failed"
            logger.error("Funding conversion EUR→USDC rejected: %s", err_msg)
            if db is not None:
                try:
                    from backend.system_logger import log_to_db

                    log_to_db(
                        "ERROR",
                        "quote_currency",
                        f"funding_conversion_rejected eur={adj_qty:.2f} err={err_msg}",
                        db=db,
                    )
                except Exception:
                    pass
            return result

        result["executed"] = True
        result["reason_code"] = "funding_conversion_executed"
        result["order_id"] = order.get("orderId")
        result["filled_qty"] = order.get("executedQty")
        _last_conversion_time = datetime.now(timezone.utc)
        _conversion_timestamps.append(_last_conversion_time)
        logger.info(
            "Funding conversion EUR→USDC executed: %.2f EUR, orderId=%s",
            adj_qty,
            order.get("orderId"),
        )
        if db is not None:
            try:
                from backend.system_logger import log_to_db

                log_to_db(
                    "INFO",
                    "quote_currency",
                    f"funding_conversion_executed eur={adj_qty:.2f} orderId={order.get('orderId')}",
                    db=db,
                )
            except Exception:
                pass
    except Exception as exc:
        result["detail"] = str(exc)
        logger.error("Funding conversion EUR→USDC failed: %s", exc)
        if db is not None:
            try:
                from backend.system_logger import log_to_db

                log_to_db(
                    "ERROR",
                    "quote_currency",
                    f"funding_conversion_failed eur={amount_eur:.2f} err={exc}",
                    db=db,
                )
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# Portfolio-level quote currency status
# ---------------------------------------------------------------------------


def get_quote_currency_status(
    free_eur: float,
    free_usdc: float,
    mode: str,
    primary_quote: str,
    target_usdc_buffer: float,
    min_eur_reserve: float,
    allow_auto_convert: bool,
) -> dict:
    """
    Zwraca status quote currency do wyświetlenia w WWW/Telegram.
    """
    mode = (mode or "BOTH").upper()
    primary_quote = (primary_quote or "EUR").upper()
    return {
        "mode": mode,
        "primary_quote": primary_quote,
        "free_eur": round(free_eur, 4),
        "free_usdc": round(free_usdc, 4),
        "target_usdc_buffer": round(target_usdc_buffer, 2),
        "min_eur_reserve": round(min_eur_reserve, 2),
        "auto_convert_enabled": allow_auto_convert,
        "usdc_sufficient": free_usdc >= target_usdc_buffer,
        "last_conversion": (
            _last_conversion_time.isoformat() if _last_conversion_time else None
        ),
    }
