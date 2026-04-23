"""
market_scanner.py — Globalny pipeline skanowania rynku.

Odpowiada za:
 1. Budowanie trade universe (primary + extended)
 2. Skanowanie wszystkich symboli z DB/ENV
 3. Budowanie rankingu (analityczny)
 4. Walidację każdego kandydata — z zachowaniem listy rejected
 5. Wybór best_analytical_candidate i best_executable_candidate
 6. Zwrócenie MarketScanSnapshot z pełną diagnostyką

ZASADA: kandydat nr 1 odrzucony ≠ brak okazji.
Pipeline zawsze sprawdza następnych kandydatów.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger("market_scanner")

# ─────────────────────────────────────────────────────────────────────────────
# KODY ODRZUCEŃ — stałe, kanoniczne
# ─────────────────────────────────────────────────────────────────────────────
REJECTION_CODES: Dict[str, str] = {
    "SELL_WITHOUT_POSITION": "SELL bez otwartej pozycji — brak aktywa w portfelu",
    "BUY_BLOCKED_BY_RISK": "BUY zablokowany przez silnik ryzyka",
    "CONFIDENCE_TOO_LOW": "Pewność sygnału poniżej progu minimalnego",
    "SCORE_TOO_LOW": "Score okazji poniżej progu minimalnego",
    "TARGET_EVAL_UNAVAILABLE": "Brak oceny celu / walidacji wejścia",
    "SPREAD_TOO_HIGH": "Spread powyżej limitu",
    "VOLUME_TOO_LOW": "Wolumen 24h poniżej minimum",
    "MARKET_DATA_PARTIAL": "Niekompletne dane rynkowe",
    "SYMBOL_DISABLED": "Symbol wyłączony lub na blackliście",
    "COOLDOWN_ACTIVE": "Cooldown aktywny po ostatniej transakcji",
    "MAX_POSITIONS_REACHED": "Osiągnięto limit otwartych pozycji",
    "POSITION_ALREADY_OPEN": "Pozycja na tym symbolu już otwarta",
    "EXECUTION_MODE_BLOCKED": "Tryb wykonania zablokowany",
    "MIN_NOTIONAL_GUARD": "Brak wystarczającej gotówki na minimalne zlecenie",
    "KILL_SWITCH_ACTIVE": "Kill switch aktywny — handel zatrzymany",
    "INSUFFICIENT_EDGE_AFTER_COSTS": "Edge po kosztach za mały (expected_move ≤ koszt × 1.8)",
    "NO_TREND_CONFIRMATION": "Brak potwierdzenia trendu dla BUY",
    "HOLD_SIGNAL": "Sygnał HOLD — brak wyraźnego kierunku",
    "DATA_TOO_OLD": "Dane sygnału zbyt stare",
    "DUPLICATE_ENTRY": "Pozycja znacząca już otwarta na tym symbolu",
}

FINAL_MARKET_STATUSES = {
    "ENTRY_FOUND": "Znaleziono wykonalną okazję wejścia",
    "WAIT": "Brak wykonalnej okazji — czekaj na warunki",
    "NO_EXECUTABLE_CANDIDATE": "Żaden kandydat nie przeszedł walidacji",
    "DEGRADED": "Skan zdegradowany — brak lub stale dane dla większości symboli",
    "ERROR": "Błąd skanowania",
}

# ─────────────────────────────────────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────────────────────────────────────
_scan_cache: Optional[Dict[str, Any]] = None
_scan_cache_ts: float = 0.0
_scan_cache_mode: str = ""
_scan_cache_ttl: float = 18.0  # sekundy
_scan_cache_lock = threading.Lock()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE UNIVERSE
# ─────────────────────────────────────────────────────────────────────────────


def get_trade_universe(db: Session, extended: bool = False) -> List[str]:
    """
    Zwraca kanoniczny zbiór symboli do skanowania.

    Priorytet (primary universe):
    1. Watchlista z runtime_settings — rozszerzona o obie quote waluty
    2. Symbole z MarketData (zbierane przez collector)
    3. ENV WATCHLIST fallback

    Extended universe:
    4. Symbole z Binance spot (aktywa użytkownika)
    5. Pary USDT (gdy SCAN_EXTENDED_QUOTES zawiera USDT)

    Filtrowanie końcowe:
    - QUOTE_CURRENCY_MODE → USDC | EUR | BOTH
    - Blacklist z ENV SYMBOL_BLACKLIST
    """
    from backend.database import MarketData
    from backend.quote_currency import (
        expand_watchlist_for_mode,
        filter_symbols_by_quote_mode,
    )
    from backend.symbol_universe import get_rotating_universe_slice, get_symbol_registry

    seen: set[str] = set()
    result: List[str] = []

    def _add(sym: str) -> None:
        s = sym.strip().upper()
        if s and s not in seen:
            seen.add(s)
            result.append(s)

    qcm = os.getenv("QUOTE_CURRENCY_MODE", "USDC").strip().upper()
    blacklist = {
        s.strip().upper()
        for s in os.getenv("SYMBOL_BLACKLIST", "").split(",")
        if s.strip()
    }

    runtime_watchlist: List[str] = []
    # 1. Watchlista runtime
    try:
        from backend.runtime_settings import get_runtime_config

        rs = get_runtime_config(db)
        wl = rs.get("watchlist_override") or ""
        if isinstance(wl, str):
            runtime_watchlist = [s.strip() for s in wl.split(",") if s.strip()]
        elif isinstance(wl, list):
            runtime_watchlist = [str(s) for s in wl]
        if runtime_watchlist:
            for sym in expand_watchlist_for_mode(runtime_watchlist, "BOTH"):
                _add(sym)
    except Exception:
        pass

    if os.getenv("ENABLE_DYNAMIC_UNIVERSE", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        registry = get_symbol_registry(user_watchlist=runtime_watchlist)
        for sym in registry.get("user_watchlist") or []:
            _add(sym)
        dynamic_slice, _next_offset = get_rotating_universe_slice(
            registry=registry,
            limit=int(os.getenv("MAX_SYMBOL_SCAN_PER_CYCLE", "100") or 100),
        )
        for sym in dynamic_slice:
            _add(sym)

    # 2. Symbole z MarketData
    md_symbols = [
        row[0] for row in db.query(MarketData.symbol).distinct().all() if row[0]
    ]
    for s in md_symbols:
        _add(s)

    # 3. ENV WATCHLIST fallback
    if not result:
        raw = os.getenv("WATCHLIST", "")
        if raw.strip():
            for sym in expand_watchlist_for_mode(
                [s.strip() for s in raw.split(",") if s.strip()], "BOTH"
            ):
                _add(sym)

    # 4 + 5. Extended universe
    if extended:
        logger.info("market_scanner: extended_scan_started — rozszerzone universe")
        extended_quotes = [
            q.strip().upper()
            for q in os.getenv("SCAN_EXTENDED_QUOTES", "USDT").split(",")
            if q.strip()
        ]
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            from backend.routers.positions import _get_live_spot_positions

            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_get_live_spot_positions, db)
                try:
                    for sp in fut.result(timeout=3.0):
                        _add(sp["symbol"])
                except FuturesTimeoutError:
                    pass
        except Exception:
            pass

        # Pary z rozszerzonymi quote currencies
        for q in extended_quotes:
            for sym in md_symbols:
                if sym.endswith(q):
                    _add(sym)

    # Filtr quote mode + blacklist
    # PRIMARY universe: filtruj wg QCM (tylko wybrane quote currencies dla trade)
    # EXTENDED universe: NIE filtruj wg QCM — skanuj wszystko dostępne w MarketData
    if extended:
        # Extended mode: zwróć wszystkie dostępne symbole niezależnie od quote currency
        # Decyzja execution i tak jest filtrowana w walidacji kandydatów
        final = [s for s in result if s not in blacklist]
    else:
        filtered = filter_symbols_by_quote_mode(result, qcm)
        if not filtered:
            filtered = result  # nie zeruj — lepiej mieć coś niż nic
        final = [s for s in filtered if s not in blacklist]

    logger.debug(
        "trade_universe_loaded: primary=%d, after_filter=%d, extended=%s",
        len(result),
        len(final),
        extended,
    )
    return final


def get_scanner_universe_stats(db: Session) -> Dict[str, Any]:
    from backend.symbol_universe import get_symbol_registry, get_symbol_universe_stats

    stats = get_symbol_universe_stats()
    universe = get_trade_universe(db, extended=False)
    stats["scanner_active_count"] = len(universe)
    stats["scanner_sample"] = universe[:10]
    stats["watchlist_priority_count"] = len(
        (get_symbol_registry().get("user_watchlist") or [])
    )
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# WALIDACJA KANDYDATÓW — PORTFOLIO + BRAMKI RYZYKA
# ─────────────────────────────────────────────────────────────────────────────


def _validate_candidate(
    cand: Dict[str, Any],
    open_symbols: set,
    significant_open_symbols: set,
    open_count: int,
    cash: float,
    config: Dict[str, Any],
    mode: str,
    db: Session,
    now: datetime,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Sprawdź jeden kandydat pod kątem bramek portfelowych i ryzyka.
    Zwraca (rejection_code, rejection_text) lub (None, None) gdy OK.
    """
    from backend.database import Order as Ord
    from backend.runtime_settings import AGGRESSIVENESS_PROFILES

    sym = cand["symbol"]
    score = float(cand.get("score", 0))
    confidence = float(cand.get("confidence", 0))
    signal_type = cand.get("signal_type", "HOLD")
    ind = cand.get("indicators") or {}

    aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
    aggr_profile = AGGRESSIVENESS_PROFILES.get(
        aggressiveness, AGGRESSIVENESS_PROFILES["balanced"]
    )

    kill_switch = bool(config.get("kill_switch_enabled", True)) and bool(
        config.get("kill_switch_active", False)
    )
    max_open_positions = int(
        config.get("max_open_positions", aggr_profile["max_open_positions"])
    )
    min_order_notional = float(config.get("min_order_notional", 25.0))
    min_conf = float(
        config.get(
            "demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]
        )
    )
    min_score = float(
        config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"])
    )
    base_cooldown_s = int(
        float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60
    )
    dust_threshold = float(os.getenv("DUST_THRESHOLD_EUR", "1.0"))
    # ── Świeżość sygnału ──────────────────────────────────────────
    max_signal_age_s = int(os.getenv("MAX_SIGNAL_AGE_MINUTES", "90")) * 60
    ts_str = cand.get("timestamp") or cand.get("signal_timestamp")
    if ts_str:
        try:
            sig_ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
            age_s = (now - sig_ts).total_seconds()
            if age_s > max_signal_age_s:
                return "DATA_TOO_OLD", (
                    f"Sygnał sprzed {age_s/60:.0f} min > limit {max_signal_age_s//60} min — "
                    f"{REJECTION_CODES['DATA_TOO_OLD']}"
                )
        except Exception:
            pass
    # ── Kill switch ──────────────────────────────────────────────────────
    if kill_switch:
        return "KILL_SWITCH_ACTIVE", REJECTION_CODES["KILL_SWITCH_ACTIVE"]

    # ── SELL bez pozycji ─────────────────────────────────────────────────
    if signal_type == "SELL" and sym not in open_symbols:
        return "SELL_WITHOUT_POSITION", REJECTION_CODES["SELL_WITHOUT_POSITION"]

    # ── Score ────────────────────────────────────────────────────────────
    if score < min_score:
        return (
            "SCORE_TOO_LOW",
            f"Score {score:.1f}/100 < {min_score:.0f} — {REJECTION_CODES['SCORE_TOO_LOW']}",
        )

    # ── Confidence ───────────────────────────────────────────────────────
    if confidence < min_conf:
        return (
            "CONFIDENCE_TOO_LOW",
            f"Pewność {confidence:.0%} < {min_conf:.0%} — {REJECTION_CODES['CONFIDENCE_TOO_LOW']}",
        )

    # ── Reżim trendu dla BUY ─────────────────────────────────────────────
    if signal_type == "BUY":
        regime = (
            ind.get("market_regime")
            or ind.get("regime")
            or cand.get("market_regime")
            or "UNKNOWN"
        )
        if regime not in ("TREND_UP", "UNKNOWN"):
            return (
                "NO_TREND_CONFIRMATION",
                f"Reżim {regime} — {REJECTION_CODES['NO_TREND_CONFIRMATION']}",
            )

    # ── Edge vs koszt dla BUY ────────────────────────────────────────────
    if signal_type == "BUY":
        em_pct = float(
            cand.get("expected_profit_pct") or ind.get("expected_move_pct") or 0
        )
        tc_pct = float(ind.get("total_cost_pct") or 0)
        if em_pct > 0 and tc_pct > 0 and em_pct <= tc_pct * 1.8:
            return "INSUFFICIENT_EDGE_AFTER_COSTS", (
                f"Edge {em_pct:.2f}% ≤ koszt {tc_pct:.2f}%×1.8 — "
                f"{REJECTION_CODES['INSUFFICIENT_EDGE_AFTER_COSTS']}"
            )

    # ── Limity portfelowe (tylko BUY) ────────────────────────────────────
    if signal_type == "BUY":
        if open_count >= max_open_positions:
            return "MAX_POSITIONS_REACHED", (
                f"Limit {max_open_positions} pozycji osiągnięty — "
                f"{REJECTION_CODES['MAX_POSITIONS_REACHED']}"
            )
        if sym in significant_open_symbols:
            return "DUPLICATE_ENTRY", (
                f"Pozycja >{dust_threshold} EUR już otwarta na {sym} — "
                f"{REJECTION_CODES['DUPLICATE_ENTRY']}"
            )
        if cash < min_order_notional:
            return "MIN_NOTIONAL_GUARD", (
                f"Gotówka {cash:.2f} < {min_order_notional} — "
                f"{REJECTION_CODES['MIN_NOTIONAL_GUARD']}"
            )
        # Cooldown
        try:
            last_ord = (
                db.query(Ord)
                .filter(Ord.symbol == sym, Ord.mode == mode)
                .order_by(Ord.timestamp.desc())
                .first()
            )
            if (
                last_ord
                and (now - last_ord.timestamp).total_seconds() < base_cooldown_s
            ):
                elapsed = int((now - last_ord.timestamp).total_seconds())
                remaining = base_cooldown_s - elapsed
                return "COOLDOWN_ACTIVE", (
                    f"Cooldown — ostatnia transakcja {elapsed}s temu, pozostało {remaining}s. "
                    f"{REJECTION_CODES['COOLDOWN_ACTIVE']}"
                )
        except Exception:
            pass

    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# GŁÓWNY PIPELINE SKANOWANIA
# ─────────────────────────────────────────────────────────────────────────────


def run_market_scan(
    db: Session,
    mode: str = "demo",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Kanoniczny pipeline skanowania rynku.

    Etapy:
    A. Pobierz universe (primary, potem opcjonalnie extended)
    B. Załaduj i wygeneruj sygnały
    C. Policz score dla każdego kandydata
    D. Zbuduj ranking analityczny
    E. Dla każdego kandydata — walidacja; zapisz rejected
    F. Pierwszy przechodzący → best_executable_candidate
    G. Jeśli brak w primary → extended scan
    H. Zwróć MarketScanSnapshot

    Caching: 18s per mode.
    """
    import time as _time

    global _scan_cache, _scan_cache_ts, _scan_cache_mode

    now_mono = _time.monotonic()
    with _scan_cache_lock:
        if (
            not force
            and _scan_cache is not None
            and _scan_cache_mode == mode
            and (now_mono - _scan_cache_ts) < _scan_cache_ttl
        ):
            return _scan_cache

    cycle_id = str(uuid.uuid4())[:12]
    snapshot_id = str(uuid.uuid4())
    generated_at = _utc_now().isoformat() + "Z"
    now = _utc_now()

    logger.info("market_scan_started: cycle_id=%s mode=%s", cycle_id, mode)

    try:
        from backend.accounting import compute_demo_account_state
        from backend.database import AccountSnapshot, Position
        from backend.runtime_settings import build_runtime_state

        # ── Config ──────────────────────────────────────────────────────
        runtime_ctx = build_runtime_state(db)
        config = runtime_ctx.get("config", {})

        # ── Gotówka i pozycje ────────────────────────────────────────────
        demo_quote_ccy = os.getenv("DEMO_QUOTE_CCY", "EUR")
        if mode == "demo":
            account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy)
            cash = float(account_state.get("cash") or 0.0)
        else:
            try:
                from backend.routers.portfolio import _build_live_spot_portfolio

                live_data = _build_live_spot_portfolio(db)
                if live_data.get("error"):
                    snap = (
                        db.query(AccountSnapshot)
                        .filter(AccountSnapshot.mode == "live")
                        .order_by(AccountSnapshot.timestamp.desc())
                        .first()
                    )
                    cash = float(snap.free_margin or 0.0) if snap else 0.0
                else:
                    cash = float(live_data.get("free_cash_eur", 0.0))
            except Exception:
                cash = 0.0

        open_positions = db.query(Position).filter(Position.mode == mode).all()
        open_symbols: set[str] = {p.symbol for p in open_positions}
        significant_open_symbols: set[str] = set()
        dust_threshold = float(os.getenv("DUST_THRESHOLD_EUR", "1.0"))

        for p in open_positions:
            pos_val = float(getattr(p, "quantity", 0) or 0) * float(
                getattr(p, "current_price", 0) or 0
            )
            if pos_val >= dust_threshold:
                significant_open_symbols.add(p.symbol)
            else:
                significant_open_symbols.add(p.symbol)

        if mode == "live":
            try:
                from backend.routers.positions import _get_live_spot_positions

                for sp in _get_live_spot_positions(db):
                    sym_sp = sp["symbol"]
                    val_sp = float(sp.get("value_eur") or 0)
                    open_symbols.add(sym_sp)
                    if val_sp >= dust_threshold:
                        significant_open_symbols.add(sym_sp)
                open_count = sum(
                    1
                    for sp in _get_live_spot_positions(db)
                    if float(sp.get("value_eur") or 0) >= dust_threshold
                )
            except Exception:
                open_count = len(open_positions)
        else:
            open_count = len(open_positions)

        # pozycje snapshot do zwrócenia w dashboardzie
        positions_snapshot = _build_positions_snapshot(db, mode, open_positions)

        # ── Etap A: Universe ─────────────────────────────────────────────
        primary_symbols = get_trade_universe(db, extended=False)
        extended_enabled = os.getenv("EXTENDED_SCAN_ENABLED", "true").lower() == "true"
        extended_performed = False

        # ── Etap B+C+D: Sygnały + scoring + ranking ──────────────────────
        scan_result = _scan_symbols(db, primary_symbols, cycle_id)
        scanned_count = scan_result["scanned_count"]
        analyzed_count = scan_result["analyzed_count"]
        ranked = scan_result["ranked"]  # lista kandydatów, sortowana wg score DESC

        logger.info(
            "market_scan_symbol_analyzed: cycle=%s scanned=%d analyzed=%d ranked=%d",
            cycle_id,
            scanned_count,
            analyzed_count,
            len(ranked),
        )

        # Best analytical (bez walidacji portfelowej) — najwyższy score z BUY/SELL
        best_analytical = next(
            (c for c in ranked if c.get("signal_type") != "HOLD"), None
        )

        # ── Etap E+F: Walidacja każdego kandydata ────────────────────────
        allowed_candidates: List[Dict[str, Any]] = []
        rejected_candidates: List[Dict[str, Any]] = []

        for cand in ranked:
            if cand.get("signal_type") == "HOLD":
                rejected_candidates.append(
                    {
                        "symbol": cand["symbol"],
                        "score": cand.get("score", 0),
                        "confidence": cand.get("confidence", 0),
                        "signal": cand.get("signal_type", "HOLD"),
                        "rejection_reason_code": "HOLD_SIGNAL",
                        "rejection_reason_text": REJECTION_CODES["HOLD_SIGNAL"],
                    }
                )
                continue

            rej_code, rej_text = _validate_candidate(
                cand,
                open_symbols,
                significant_open_symbols,
                open_count,
                cash,
                config,
                mode,
                db,
                now,
            )
            if rej_code:
                logger.debug(
                    "candidate_rejected: cycle=%s sym=%s code=%s",
                    cycle_id,
                    cand["symbol"],
                    rej_code,
                )
                rejected_candidates.append(
                    {
                        "symbol": cand["symbol"],
                        "score": cand.get("score", 0),
                        "confidence": cand.get("confidence", 0),
                        "signal": cand.get("signal_type"),
                        "rejection_reason_code": rej_code,
                        "rejection_reason_text": rej_text,
                    }
                )
            else:
                logger.info(
                    "candidate_ranked: cycle=%s sym=%s score=%.1f signal=%s",
                    cycle_id,
                    cand["symbol"],
                    cand.get("score", 0),
                    cand.get("signal_type"),
                )
                allowed_candidates.append(cand)

        best_executable = allowed_candidates[0] if allowed_candidates else None

        # ── Etap G: Extended scan gdy brak w primary ─────────────────────
        extended_scan_info: Optional[Dict[str, Any]] = None
        if best_executable is None and extended_enabled:
            logger.info("extended_scan_started: cycle=%s primary_failed", cycle_id)
            extended_performed = True
            extended_symbols = get_trade_universe(db, extended=True)
            new_symbols = [s for s in extended_symbols if s not in set(primary_symbols)]

            extended_scan_info = {
                "extended_universe_total": len(extended_symbols),
                "primary_size": len(primary_symbols),
                "new_symbols_found": len(new_symbols),
                "new_symbols": new_symbols[:20],
                "new_symbols_checked": 0,
                "additional_allowed": 0,
            }

            if new_symbols:
                # Extended skan używa max_signal_age_minutes=120 aby generować świeże sygnały
                # dla symboli które nie były w primary (mogą mieć starsze rekordy w DB)
                ext_scan = _scan_symbols(
                    db,
                    new_symbols,
                    cycle_id,
                    prefix="EXT",
                    max_signal_age_minutes=120,
                )
                for cand in ext_scan["ranked"]:
                    if cand.get("signal_type") == "HOLD":
                        continue
                    rej_code, rej_text = _validate_candidate(
                        cand,
                        open_symbols,
                        significant_open_symbols,
                        open_count,
                        cash,
                        config,
                        mode,
                        db,
                        now,
                    )
                    if rej_code:
                        rejected_candidates.append(
                            {
                                "symbol": cand["symbol"],
                                "score": cand.get("score", 0),
                                "confidence": cand.get("confidence", 0),
                                "signal": cand.get("signal_type"),
                                "rejection_reason_code": rej_code,
                                "rejection_reason_text": rej_text,
                                "universe": "extended",
                            }
                        )
                    else:
                        allowed_candidates.append(cand)

                best_executable = allowed_candidates[0] if allowed_candidates else None
                extended_scan_info["new_symbols_checked"] = ext_scan["scanned_count"]
                extended_scan_info["additional_allowed"] = len(allowed_candidates)
                scanned_count += ext_scan["scanned_count"]
                analyzed_count += ext_scan["analyzed_count"]
            else:
                logger.info(
                    "extended_scan_no_new_symbols: cycle=%s extended_universe_same_as_primary",
                    cycle_id,
                )

        if best_executable:
            logger.info(
                "executable_candidate_selected: cycle=%s sym=%s score=%.1f signal=%s",
                cycle_id,
                best_executable["symbol"],
                best_executable.get("score", 0),
                best_executable.get("signal_type"),
            )
        else:
            logger.info(
                "no_executable_candidate_found: cycle=%s rejected=%d",
                cycle_id,
                len(rejected_candidates),
            )

        # ── Etap H: Finalna decyzja ──────────────────────────────────────
        if best_executable:
            final_status = "ENTRY_FOUND"
            final_user_message = _build_entry_message(
                best_executable, allowed_candidates
            )
        else:
            if not ranked:
                final_status = "DEGRADED"
                final_user_message = (
                    f"Brak danych rynkowych — przeskanowano {scanned_count} symboli, "
                    f"przeanalizowano {analyzed_count}."
                )
            else:
                final_status = "NO_EXECUTABLE_CANDIDATE"
                top_rejections = _describe_top_rejections(rejected_candidates)
                final_user_message = (
                    f"Przeskanowano {scanned_count} symboli, przeanalizowano {analyzed_count}. "
                    f"Odrzucono {len(rejected_candidates)} kandydatów. "
                    f"Główne powody: {top_rejections}"
                )
                if extended_performed:
                    final_user_message += " [Extended scan wykonany]"

        # Sekcja market distribution (rozkład sygnałów)
        buy_count = sum(1 for c in ranked if c.get("signal_type") == "BUY")
        sell_count = sum(1 for c in ranked if c.get("signal_type") == "SELL")
        hold_count = sum(1 for c in ranked if c.get("signal_type") == "HOLD")

        market_distribution = {
            "buy": buy_count,
            "sell": sell_count,
            "hold": hold_count,
            "total": len(ranked),
        }

        # Portfolio constraints summary
        portfolio_constraints = {
            "open_positions_count": open_count,
            "max_open_positions": int(config.get("max_open_positions", 3)),
            "free_cash": round(cash, 2),
            "kill_switch_active": bool(config.get("kill_switch_active", False)),
            "extended_scan_performed": extended_performed,
        }

        # Top N okazji (analityczne — bez walidacji portfela dla rankingi)
        opportunities_top_n = [
            _format_opportunity(c)
            for c in ranked[:10]
            if c.get("signal_type") != "HOLD"
        ]

        # Odrzuci posortowane wg score
        rejected_sorted = sorted(
            [r for r in rejected_candidates if r.get("signal") != "HOLD"],
            key=lambda x: -float(x.get("score", 0)),
        )

        snapshot: Dict[str, Any] = {
            "snapshot_id": snapshot_id,
            "cycle_id": cycle_id,
            "generated_at": generated_at,
            "mode": mode,
            "scanned_symbols_count": scanned_count,
            "analyzed_symbols_count": analyzed_count,
            "ranked_candidates_count": len(ranked),
            "best_analytical_candidate": (
                _format_candidate(best_analytical) if best_analytical else None
            ),
            "best_executable_candidate": (
                _format_candidate(best_executable) if best_executable else None
            ),
            "rejected_candidates": rejected_sorted[:20],
            "rejected_count": len(rejected_sorted),
            "final_market_status": final_status,
            "final_market_status_pl": FINAL_MARKET_STATUSES.get(
                final_status, final_status
            ),
            "final_user_message": final_user_message,
            "opportunities_top_n": opportunities_top_n,
            "market_distribution": market_distribution,
            "portfolio_constraints_summary": portfolio_constraints,
            "positions_snapshot": positions_snapshot,
            "extended_scan_performed": extended_performed,
            "extended_scan_info": extended_scan_info,
        }

        logger.info(
            "dashboard_snapshot_created: cycle=%s status=%s executable=%s",
            cycle_id,
            final_status,
            best_executable["symbol"] if best_executable else "None",
        )

        with _scan_cache_lock:
            _scan_cache = snapshot
            _scan_cache_ts = now_mono
            _scan_cache_mode = mode

        return snapshot

    except Exception as exc:
        logger.error("market_scan_error: %s", str(exc), exc_info=True)
        return {
            "snapshot_id": snapshot_id,
            "cycle_id": cycle_id,
            "generated_at": generated_at,
            "mode": mode,
            "final_market_status": "ERROR",
            "final_market_status_pl": FINAL_MARKET_STATUSES["ERROR"],
            "final_user_message": f"Błąd skanowania: {type(exc).__name__}",
            "scanned_symbols_count": 0,
            "analyzed_symbols_count": 0,
            "ranked_candidates_count": 0,
            "best_analytical_candidate": None,
            "best_executable_candidate": None,
            "rejected_candidates": [],
            "rejected_count": 0,
            "opportunities_top_n": [],
            "market_distribution": {"buy": 0, "sell": 0, "hold": 0, "total": 0},
            "portfolio_constraints_summary": {},
            "positions_snapshot": [],
            "extended_scan_performed": False,
            "extended_scan_info": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# SKANOWANIE SYMBOLI — B+C+D
# ─────────────────────────────────────────────────────────────────────────────


def _scan_symbols(
    db: Session,
    symbols: List[str],
    cycle_id: str,
    prefix: str = "PRIMARY",
    max_signal_age_minutes: int = 90,
) -> Dict[str, Any]:
    """
    Dla listy symboli: załaduj sygnały z DB (fallback do live), policz score, zrankinguj.

    max_signal_age_minutes: sygnały starsze niż ten limit są regenerowane przez live fallback.
    """
    from backend.routers.signals import (
        _load_signals_from_db_or_live,
        _score_opportunity,
    )

    if not symbols:
        return {"scanned_count": 0, "analyzed_count": 0, "ranked": []}

    scanned_count = len(symbols)
    live = _load_signals_from_db_or_live(
        db, symbols, max_age_minutes=max_signal_age_minutes
    )
    analyzed_count = len(live)

    scored: List[Dict[str, Any]] = []
    for sig in live:
        try:
            scored_sig = _score_opportunity(sig, db)
            scored.append(scored_sig)
        except Exception as _e:
            logger.debug("score_failed: sym=%s err=%s", sig.get("symbol"), str(_e))
            scored.append(sig)

    # Ranking: score DESC, HOLD na końcu
    scored.sort(
        key=lambda x: (-float(x.get("score", 0)), x.get("signal_type") == "HOLD")
    )
    return {
        "scanned_count": scanned_count,
        "analyzed_count": analyzed_count,
        "ranked": scored,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FORMATOWANIE WYNIKÓW
# ─────────────────────────────────────────────────────────────────────────────


def _format_candidate(c: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not c:
        return None
    ind = c.get("indicators") or {}
    return {
        "symbol": c.get("symbol"),
        "signal": c.get("signal_type"),
        "score": round(float(c.get("score", 0)), 1),
        "confidence": round(float(c.get("confidence", 0)), 3),
        "price": c.get("price"),
        "expected_profit_pct": c.get("expected_profit_pct"),
        "risk_pct": c.get("risk_pct"),
        "rsi": c.get("rsi") or ind.get("rsi") or ind.get("rsi_14"),
        "market_regime": c.get("market_regime")
        or ind.get("market_regime")
        or ind.get("regime"),
        "reason": c.get("reason"),
        "timestamp": c.get("timestamp"),
        "score_breakdown": c.get("score_breakdown"),
    }


def _format_opportunity(c: Dict[str, Any]) -> Dict[str, Any]:
    ind = c.get("indicators") or {}
    return {
        "symbol": c.get("symbol"),
        "signal": c.get("signal_type"),
        "score": round(float(c.get("score", 0)), 1),
        "confidence": round(float(c.get("confidence", 0)), 3),
        "price": c.get("price"),
        "rsi": c.get("rsi") or ind.get("rsi") or ind.get("rsi_14"),
        "trend": (
            "WZROSTOWY"
            if (c.get("market_regime") or ind.get("market_regime")) == "TREND_UP"
            else (
                "SPADKOWY"
                if (c.get("market_regime") or ind.get("market_regime")) == "TREND_DOWN"
                else "BOCZNY"
            )
        ),
        "reason": c.get("reason"),
        "expected_profit_pct": c.get("expected_profit_pct"),
    }


def _build_entry_message(
    best: Dict[str, Any], all_allowed: List[Dict[str, Any]]
) -> str:
    sym = best.get("symbol", "?")
    sig = best.get("signal_type", "?")
    conf = round(float(best.get("confidence", 0)) * 100)
    score = round(float(best.get("score", 0)), 1)
    sig_pl = {"BUY": "KUP", "SELL": "SPRZEDAJ"}.get(sig, sig)
    runner_up = ""
    if len(all_allowed) > 1:
        r = all_allowed[1]
        runner_up = f" Kolejny: {r['symbol']} ({r.get('signal_type')}, score={r.get('score', 0):.1f})"
    return f"{sig_pl} {sym} — pewność {conf}%, score {score}/100.{runner_up}"


def _describe_top_rejections(rejected: List[Dict[str, Any]]) -> str:
    if not rejected:
        return "brak kandydatów z BUY/SELL"
    # Grupuj po kodzie
    code_counts: Dict[str, int] = {}
    for r in rejected:
        code = r.get("rejection_reason_code", "UNKNOWN")
        code_counts[code] = code_counts.get(code, 0) + 1
    top = sorted(code_counts.items(), key=lambda x: -x[1])[:3]
    parts = []
    for code, cnt in top:
        desc = REJECTION_CODES.get(code, code)
        parts.append(f"{desc} ({cnt}×)")
    return "; ".join(parts)


def _build_positions_snapshot(
    db: Session,
    mode: str,
    open_positions: list,
) -> List[Dict[str, Any]]:
    """Zwraca snapshot aktywnych pozycji (z bazy, bez Binance call)."""
    result = []
    for p in open_positions:
        try:
            qty = float(getattr(p, "quantity", 0) or 0)
            entry = float(getattr(p, "entry_price", 0) or 0)
            current = float(getattr(p, "current_price", 0) or 0)
            val_eur = qty * current if current > 0 else qty * entry
            pnl_pct = (
                ((current - entry) / entry * 100) if entry > 0 and current > 0 else 0
            )
            result.append(
                {
                    "symbol": p.symbol,
                    "qty": round(qty, 8),
                    "entry_price": round(entry, 8),
                    "current_price": round(current, 8) if current else None,
                    "value_eur": round(val_eur, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "mode": p.mode,
                }
            )
        except Exception:
            pass
    return result
