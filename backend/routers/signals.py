"""
Signals API Router - endpoints dla sygnałów AI
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.analysis import persist_insights_as_signals
from backend.database import (
    AccountSnapshot,
    DecisionAudit,
    DecisionTrace,
    Kline,
    MarketData,
    PendingOrder,
    Position,
    Signal,
    UserExpectation,
    get_db,
    utc_now_naive,
)
from backend.quote_currency import (
    build_symbol_set,
    convert_eur_amount_to_quote,
    expand_watchlist_for_mode,
    filter_symbols_by_quote_mode,
    get_base_asset,
    get_markets_for_asset,
    get_supported_base_assets,
    is_test_symbol,
    resolve_eur_usdc_rate,
)

router = APIRouter()

_ACTIVE_PENDING_STATUSES = [
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
    "EXCHANGE_SUBMITTED",
    "PARTIALLY_FILLED",
]


@router.get("/quote-mode-status")
def get_quote_mode_status(
    mode: Optional[str] = Query(None, description="Override: EUR | USDC | BOTH"),
    db: Session = Depends(get_db),
):
    """
    Runtime proof: aktywny tryb quote currency, symbole analizowane,
    dostępność obu rynków dla tych samych aktywów bazowych.
    Opcjonalny ?mode=EUR|USDC|BOTH nadpisuje aktywny tryb — tylko dla diagnostyki.
    """
    env_qcm = os.getenv("QUOTE_CURRENCY_MODE", "USDC").strip().upper()
    qcm = mode.strip().upper() if mode else env_qcm
    primary_quote = os.getenv("PRIMARY_QUOTE", "USDC").strip().upper()

    # Pełne universe z DB (bez filtra)
    all_md = sorted(
        set(row[0] for row in db.query(MarketData.symbol).distinct().all() if row[0])
    )
    eur_in_db = [s for s in all_md if s.endswith("EUR")]
    usdc_in_db = [s for s in all_md if s.endswith("USDC")]

    # Universe dla żądanego trybu (respektuje ?mode= override)
    active_symbols = filter_symbols_by_quote_mode(all_md, qcm)

    # Parowanie aktywów: asset bazowy → oba rynki
    asset_market_map: dict = {}
    for sym in all_md:
        base = get_base_asset(sym)
        if base:
            if base not in asset_market_map:
                asset_market_map[base] = {
                    "EUR": None,
                    "USDC": None,
                    "in_active_mode": False,
                }
            if sym.endswith("EUR"):
                asset_market_map[base]["EUR"] = sym
            elif sym.endswith("USDC"):
                asset_market_map[base]["USDC"] = sym

    # Oznacz które aktywa są w aktywnym trybie
    for sym in active_symbols:
        base = get_base_asset(sym)
        if base and base in asset_market_map:
            asset_market_map[base]["in_active_mode"] = True

    # Aktywa z oboma rynkami
    dual_market_assets = [
        a for a, m in asset_market_map.items() if m["EUR"] and m["USDC"]
    ]

    return {
        "quote_currency_mode": qcm,
        "primary_quote": primary_quote,
        "allow_auto_convert": os.getenv(
            "ALLOW_AUTO_CONVERT_EUR_TO_USDC", "false"
        ).lower()
        == "true",
        "db_symbols_total": len(all_md),
        "db_eur_symbols": eur_in_db,
        "db_usdc_symbols": usdc_in_db,
        "active_mode_symbols": sorted(active_symbols),
        "active_mode_eur_count": sum(1 for s in active_symbols if s.endswith("EUR")),
        "active_mode_usdc_count": sum(1 for s in active_symbols if s.endswith("USDC")),
        "dual_market_assets": sorted(dual_market_assets),
        "dual_market_count": len(dual_market_assets),
        "asset_market_map": {k: v for k, v in sorted(asset_market_map.items())},
        "mode_proof": {
            "EUR_symbols_blocked": ("USDC" in qcm if qcm != "BOTH" else False),
            "USDC_symbols_blocked": ("EUR" == qcm if qcm != "BOTH" else False),
            "both_markets_active": qcm == "BOTH",
        },
    }


@router.get("/")
def signals_root():
    """
    Lekki endpoint kompatybilnosci dla zapytan /api/signals/.
    """
    return {
        "success": True,
        "message": "Signals API online",
        "endpoints": [
            "/api/signals/latest",
            "/api/signals/top5",
            "/api/signals/top10",
            "/api/signals/best-opportunity",
            "/api/signals/final-decisions",
            "/api/signals/wait-status",
        ],
    }


def _load_signals_from_db_or_live(
    db: Session,
    symbols: List[str],
    max_age_minutes: int = 90,
) -> List[dict]:
    """
    Pobierz najnowszy sygnał z tabeli Signal dla każdego symbolu (szybko).
    Dla symboli bez rekordu w DB LUB ze zbyt starym rekordem — użyj live_analysis jako fallback.

    max_age_minutes: sygnały starsze niż ten limit są traktowane jak brakujące → live fallback.
    """
    sym_set = {s.strip().upper() for s in symbols}
    stale_cutoff = utc_now_naive() - timedelta(minutes=max_age_minutes)

    # Jednym zapytaniem pobierz najnowszy Signal per symbol
    from sqlalchemy import func as sa_func

    sub = (
        db.query(Signal.symbol, sa_func.max(Signal.timestamp).label("max_ts"))
        .filter(Signal.symbol.in_(list(sym_set)))
        .group_by(Signal.symbol)
        .subquery()
    )
    rows = (
        db.query(Signal)
        .join(sub, (Signal.symbol == sub.c.symbol) & (Signal.timestamp == sub.c.max_ts))
        .all()
    )

    result = []
    found_symbols: set[str] = set()
    stale_symbols: List[str] = []

    for sig in rows:
        try:
            ind = json.loads(sig.indicators) if sig.indicators else {}
        except Exception:
            ind = {}
        # Sprawdź świeżość: stary sygnał → live fallback
        sig_ts = (
            sig.timestamp if sig.timestamp else (utc_now_naive() - timedelta(days=9999))
        )
        if sig_ts < stale_cutoff:
            stale_symbols.append(sig.symbol)
            continue

        result.append(
            {
                "id": sig.id,
                "symbol": sig.symbol,
                "signal_type": sig.signal_type,
                "confidence": sig.confidence,
                "price": sig.price,
                "indicators": ind,
                "reason": sig.reason,
                "timestamp": sig.timestamp.isoformat(),
                "source": "database",
            }
        )
        found_symbols.add(sig.symbol)

    # Fallback: symbole bez rekordu w DB + symbole ze zbyt starym rekordem
    missing = [s for s in symbols if s.strip().upper() not in found_symbols]
    regenerate = list(
        dict.fromkeys(missing + stale_symbols)
    )  # uniq, kolejność zachowana
    if regenerate:
        live_fallback = _build_live_signals(db, regenerate, limit=len(regenerate))
        result.extend(live_fallback)

    result.sort(key=lambda x: (-x["confidence"], x["signal_type"] == "HOLD"))
    return result


def _fetch_and_store_klines_ondemand(
    db: Session, symbol: str, timeframe: str = "1h", limit: int = 120
) -> bool:
    """
    Odśwież klines dla symbolu bezpośrednio z Binance i zapisz brakujące świece do DB.
    """
    try:
        from backend.binance_client import get_binance_client

        client = get_binance_client()
        klines = client.get_klines(symbol=symbol, interval=timeframe, limit=limit)
        if not klines:
            return False

        saved_count = 0
        for k in klines:
            open_time = datetime.fromtimestamp(k["open_time"] / 1000)
            close_time = datetime.fromtimestamp(k["close_time"] / 1000)

            existing = (
                db.query(Kline)
                .filter(
                    Kline.symbol == symbol,
                    Kline.timeframe == timeframe,
                    Kline.open_time == open_time,
                )
                .first()
            )
            if existing:
                continue

            db.add(
                Kline(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=open_time,
                    close_time=close_time,
                    open=k["open"],
                    high=k["high"],
                    low=k["low"],
                    close=k["close"],
                    volume=k["volume"],
                    quote_volume=k.get("quote_volume", 0.0),
                    trades=k.get("trades", 0),
                    taker_buy_base=k.get("taker_buy_base", 0.0),
                    taker_buy_quote=k.get("taker_buy_quote", 0.0),
                )
            )
            saved_count += 1

        if saved_count > 0:
            db.commit()

        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _build_live_signals(db: Session, symbols: List[str], limit: int = 20) -> List[dict]:
    """
    Wygeneruj sygnały oparte o wielowarstwową analizę:
    1. Regime detection (15m + 1h: EMA, RSI, MACD, volume)
    2. Cost filter: expected_move_pct > total_cost_pct * 1.8
    3. Position plan (TP1/TP2/SL/trailing) przy BUY
    4. SELL tylko gdy reżim TREND_DOWN lub silna invalidacja

    Nie używa losowości — czyste wskaźniki i logika ryzyka.
    """
    from backend.analysis import get_regime_indicators
    from backend.risk import (
        build_long_plan,
        detect_regime,
        estimate_trade_costs,
        validate_long_entry,
    )
    from backend.runtime_settings import get_runtime_config

    runtime_config = get_runtime_config(db)
    costs_base = estimate_trade_costs(runtime_config)
    _max_kline_age_h = float(os.getenv("MAX_KLINE_AGE_HOURS", "4"))

    results = []
    for symbol in symbols:
        # Sprawdź świeżość klines (1h) przed analizą — stare klines dają fałszywe wskaźniki
        try:
            latest_kline = (
                db.query(Kline)
                .filter(Kline.symbol == symbol, Kline.timeframe == "1h")
                .order_by(Kline.open_time.desc())
                .first()
            )
            if latest_kline and latest_kline.open_time:
                kline_age_h = (
                    utc_now_naive() - latest_kline.open_time
                ).total_seconds() / 3600
                if kline_age_h > _max_kline_age_h:
                    # Klines zbyt stare — próbuj pobrać świeże z Binance API (fetch-on-demand)
                    _refreshed = _fetch_and_store_klines_ondemand(
                        db, symbol, "1h", limit=120
                    )
                    if not _refreshed:
                        # Nie udało się odświeżyć — skip, nie generuj sygnału na stalenych danych
                        continue
        except Exception:
            pass  # Brak klines w ogóle → get_regime_indicators zwróci None poniżej

        ri = get_regime_indicators(db, symbol)
        if not ri:
            continue

        price = ri.get("close") or ri.get("price")
        if not price or price <= 0:
            continue

        regime_state = detect_regime(
            price=float(price),
            ema21_15m=ri.get("ema21_15m"),
            ema50_15m=ri.get("ema50_15m"),
            ema21_1h=ri.get("ema21_1h"),
            ema50_1h=ri.get("ema50_1h"),
            ema200_1h=ri.get("ema200_1h"),
            rsi_15m=ri.get("rsi_15m"),
            macd_hist_15m=ri.get("macd_hist_15m"),
            volume_ratio_15m=ri.get("volume_ratio_15m"),
        )

        regime = regime_state.regime
        regime_confidence = regime_state.confidence
        rsi = ri.get("rsi_15m") or ri.get("rsi_1h")
        ema_20 = ri.get("ema_20_1h") or ri.get("ema21_1h")
        ema_50 = ri.get("ema_50_1h") or ri.get("ema50_1h")
        atr = ri.get("atr_1h") or 0.0
        volume_ratio = ri.get("volume_ratio_15m") or 1.0
        macd_hist = ri.get("macd_hist_15m") or 0.0

        # ── Dobór sygnału na podstawie reżimu ──────────────────────
        reasons: list = list(regime_state.reasons)
        signal_type = "HOLD"
        confidence = 0.50
        entry_decision = None
        position_plan = None

        if regime == "TREND_UP":
            # Sprawdź czy expected_move uzasadnia koszty
            atr_take_mult = float(os.getenv("ATR_TAKE_MULT", "2.2"))
            atr_stop_mult = float(os.getenv("ATR_STOP_MULT", "1.3"))
            expected_move_pct = (
                (atr * atr_take_mult / price * 100) if atr and price > 0 else 0.0
            )
            risk_pct = (atr * atr_stop_mult / price * 100) if atr and price > 0 else 0.0
            rr = (expected_move_pct / risk_pct) if risk_pct > 0 else 0.0

            # Bazowy confidence: regime_confidence + RSI bonus
            confidence = round(min(0.75, regime_confidence * 0.9), 2)
            if rsi is not None:
                if 52 <= float(rsi) <= 65:
                    confidence += 0.08
                    reasons.append(f"RSI {rsi:.0f} — momentum w strefie BUY")
                elif float(rsi) < 45:
                    confidence += 0.04
                    reasons.append(f"RSI {rsi:.0f} — wyprzedanie w trendzie")
                elif float(rsi) > 72:
                    confidence -= 0.06
                    reasons.append(f"RSI {rsi:.0f} — wykupienie, ostrożność")

            # Walidacja wejścia przez risk engine (score 0–100 ~ confidence*100)
            signal_score = round(confidence * 100, 1)
            entry_decision = validate_long_entry(
                regime=regime,
                signal_score=signal_score,
                expected_move_pct=expected_move_pct,
                risk_reward=rr,
                costs=costs_base,
                min_score=55.0,  # odpowiada ~confidence 0.55
                min_rr=1.5,
            )

            if entry_decision.allowed:
                signal_type = "BUY"
                reasons.append("Wejście zatwierdzone przez silnik ryzyka")
                # Zbuduj plan pozycji
                if atr and atr > 0:
                    position_plan = build_long_plan(
                        entry=price, atr=float(atr), costs=costs_base
                    )
            else:
                signal_type = "HOLD"
                for r in entry_decision.reasons:
                    reasons.append(f"Blokada: {r}")

        elif regime == "TREND_DOWN":
            # W trendzie spadkowym — brak nowych BUY; SELL jako sygnał ostrzegawczy
            signal_type = "SELL"
            confidence = round(min(0.75, regime_confidence * 0.85), 2)
            reasons.append("Trend spadkowy — sygnał wyjścia dla istniejących pozycji")
            if rsi is not None and float(rsi) <= 40:
                confidence += 0.06
                reasons.append(f"RSI {rsi:.0f} — wyprzedanie potwierdza SELL")

        else:
            # SIDEWAYS / niska zmienność — HOLD
            signal_type = "HOLD"
            confidence = round(max(0.45, regime_confidence * 0.60), 2)
            reasons.append("Brak wyraźnego trendu — oczekiwanie na potwierdzenie")

        confidence = round(min(0.95, max(0.40, confidence)), 2)

        results.append(
            {
                "id": None,
                "symbol": symbol,
                "signal_type": signal_type,
                "confidence": confidence,
                "price": price,
                "indicators": {
                    "rsi": round(float(rsi), 1) if rsi is not None else None,
                    "ema_20": round(ema_20, 6) if ema_20 else None,
                    "ema_50": round(ema_50, 6) if ema_50 else None,
                    "atr": round(float(atr), 6) if atr else None,
                    "volume_ratio": round(volume_ratio, 2),
                    "macd_hist": round(macd_hist, 6),
                    "regime": regime,
                    "regime_confidence": regime_confidence,
                },
                "reason": (
                    "; ".join(reasons) if reasons else "Brak wystarczających danych"
                ),
                "position_plan": position_plan,
                "entry_decision": (
                    {
                        "allowed": entry_decision.allowed,
                        "reasons": entry_decision.reasons,
                        "score": entry_decision.score,
                    }
                    if entry_decision
                    else None
                ),
                "timestamp": utc_now_naive().isoformat(),
                "source": "live_analysis",
            }
        )

    results.sort(key=lambda x: (-x["confidence"], x["signal_type"] == "HOLD"))
    return results[:limit]


def _get_symbols_from_db_or_env(db: Session, include_spot: bool = True) -> List[str]:
    """
    Buduje effective universe symboli do analizy z uwzględnieniem QUOTE_CURRENCY_MODE.

    Priorytet:
    1. Watchlista użytkownika (runtime_settings) — rozszerzona o oba warianty quote
    2. Symbole z MarketData (zbierane przez collector) — filtrowane wg trybu
    3. ENV WATCHLIST (fallback)
    4. Symbole z Binance spot (realne aktywa użytkownika)

    Po zbudowaniu puli stosuje filter_symbols_by_quote_mode wg QUOTE_CURRENCY_MODE.
    Tryb BOTH → wszystkie symbole z obu quote currencies.
    Tryb EUR  → tylko *EUR.
    Tryb USDC → tylko *USDC.
    """
    seen: set[str] = set()
    result: List[str] = []

    def _add(sym: str) -> None:
        s = sym.strip().upper()
        if is_test_symbol(s):
            return
        if s and s not in seen:
            seen.add(s)
            result.append(s)

    # Aktywny tryb quote
    _qcm = os.getenv("QUOTE_CURRENCY_MODE", "USDC").strip().upper()

    runtime_watchlist: List[str] = []
    # 1. Watchlist z runtime_settings — rozszerz o oba warianty w puli,
    #    filtrowanie nastąpi na końcu.
    try:
        from backend.runtime_settings import get_runtime_config
        from backend.symbol_universe import get_rotating_universe_slice, get_symbol_registry

        rs = get_runtime_config(db)
        wl = rs.get("watchlist_override") or ""
        if isinstance(wl, str):
            runtime_watchlist = [s.strip() for s in wl.split(",") if s.strip()]
        elif isinstance(wl, list):
            runtime_watchlist = [str(s) for s in wl]
        if runtime_watchlist:
            for sym in expand_watchlist_for_mode(runtime_watchlist, "BOTH"):
                _add(sym)
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
    except Exception:
        pass

    # 2. Symbole z MarketData (aktywnie zbierane)
    md_symbols = [
        row[0] for row in db.query(MarketData.symbol).distinct().all() if row[0]
    ]
    for s in md_symbols:
        _add(s)

    # 3. ENV fallback
    if not result:
        raw = os.getenv("WATCHLIST", "")
        if raw.strip():
            for sym in expand_watchlist_for_mode(
                [s.strip() for s in raw.split(",") if s.strip()], "BOTH"
            ):
                _add(sym)

    # 4. Symbole z Binance spot
    # Timeout 3s — Binance API może być wolne; wzbogacenie symboli nie jest krytyczne
    if include_spot:
        try:
            from concurrent.futures import ThreadPoolExecutor
            from concurrent.futures import TimeoutError as FuturesTimeoutError

            from backend.routers.positions import _get_live_spot_positions

            with ThreadPoolExecutor(max_workers=1) as _pool:
                _future = _pool.submit(_get_live_spot_positions, db)
                try:
                    for sp in _future.result(timeout=3.0):
                        _add(sp["symbol"])
                except FuturesTimeoutError:
                    pass
        except Exception:
            pass

    # Zastosuj quote mode filter — twarde, deterministyczne
    filtered = filter_symbols_by_quote_mode(result, _qcm)
    # Jeśli filtr usunął wszystkie (tryb USDC, ale DB ma tylko EUR) — nie zeruj
    return filtered if filtered else result


@router.get("/latest")
def get_latest_signals(
    limit: int = Query(10, ge=1, le=100, description="Liczba sygnałów"),
    symbol: Optional[str] = Query(None, description="Filtr po symbolu"),
    signal_type: Optional[str] = Query(None, description="Filtr: BUY, SELL, HOLD"),
    db: Session = Depends(get_db),
):
    """
    Najnowsze sygnały — najpierw z bazy (zapisanych przez collector), potem live analiza.
    """
    try:
        # Sygnały z bazy (zapisane przez collector)
        query = db.query(Signal)
        if symbol:
            query = query.filter(Signal.symbol == symbol.strip().upper())
        if signal_type:
            query = query.filter(Signal.signal_type == signal_type)
        db_signals = query.order_by(desc(Signal.timestamp)).limit(limit).all()

        if db_signals:
            result = []
            for sig in db_signals:
                try:
                    ind = json.loads(sig.indicators) if sig.indicators else {}
                except Exception:
                    ind = {}
                result.append(
                    {
                        "id": sig.id,
                        "symbol": sig.symbol,
                        "signal_type": sig.signal_type,
                        "confidence": sig.confidence,
                        "price": sig.price,
                        "indicators": ind,
                        "reason": sig.reason,
                        "timestamp": sig.timestamp.isoformat(),
                        "source": "database",
                    }
                )
            return {"success": True, "data": result, "count": len(result)}

        # Fallback: live analiza — zapisz do DB żeby collector mógł korzystać
        symbols = _get_symbols_from_db_or_env(db)
        live = _build_live_signals(db, symbols, limit=limit)
        if live:
            persist_insights_as_signals(db, live)
        if signal_type:
            live = [s for s in live if s["signal_type"] == signal_type.upper()]
        return {
            "success": True,
            "data": live,
            "count": len(live),
            "source": "live_analysis",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting signals: {str(e)}")


@router.get("/top10")
def get_top10_signals(db: Session = Depends(get_db)):
    """
    Top 10 okazji — live analiza techniczna, sortowana wg confidence.
    Zapisuje wyniki do DB żeby collector mógł z nich korzystać.
    """
    try:
        symbols = _get_symbols_from_db_or_env(db)
        live = _build_live_signals(db, symbols, limit=10)
        return {
            "success": True,
            "data": live,
            "count": len(live),
            "description": "Top 10 — live analiza techniczna",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting top10 signals: {str(e)}"
        )


@router.get("/top5")
def get_top5_signals(db: Session = Depends(get_db)):
    """
    Top 5 okazji BUY/SELL — live analiza, tylko silne sygnały.
    Zapisuje wszystkie sygnały do DB żeby collector mógł korzystać.
    """
    try:
        symbols = _get_symbols_from_db_or_env(db)
        live = _build_live_signals(db, symbols, limit=20)
        # Tylko BUY/SELL z confidence > 0.55
        filtered = [
            s for s in live if s["signal_type"] != "HOLD" and s["confidence"] > 0.55
        ][:5]
        return {
            "success": True,
            "data": filtered,
            "count": len(filtered),
            "description": "Top 5 sygnałów BUY/SELL — live analiza",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting top5 signals: {str(e)}"
        )


def _score_opportunity(signal: dict, db: Session) -> dict:
    """
    Scoring okazji tradingowej — skala 0–100.

    Kategorie:
    - trend_score:         0–30  (wyrównanie trendu 15m + 1h)
    - momentum_score:      0–20  (RSI w strefie zgodnej z kierunkiem)
    - volume_score:        0–15  (volume ratio potwierdzenie)
    - edge_vs_cost_score:  0–20  (expected_move vs koszty, R/R)
    - volatility_quality:  0–10  (ATR / cena — nie za duże, nie za małe)
    - regime_bonus:        0–5   (reżim wprost z detect_regime)

    Wejście dozwolone tylko gdy score >= 60 (konfigurowalne).
    """
    symbol = signal.get("symbol", "")
    signal_type = signal.get("signal_type", "HOLD")
    confidence = float(signal.get("confidence") or 0.5)
    ind = signal.get("indicators") or {}
    price = float(signal.get("price") or 0)

    # Normalizacja kluczy — sygnały z DB używają rsi_14, atr_14 zamiast rsi, atr
    if ind.get("rsi") is None and ind.get("rsi_14") is not None:
        ind = dict(ind)
        ind["rsi"] = ind["rsi_14"]
    if ind.get("atr") is None and ind.get("atr_14") is not None:
        ind = dict(ind)
        ind["atr"] = ind["atr_14"]

    rsi = ind.get("rsi") or signal.get("rsi")
    ema_20 = ind.get("ema_20") or signal.get("ema_20")
    ema_50 = ind.get("ema_50") or signal.get("ema_50")
    atr = ind.get("atr") or signal.get("atr")
    volume_ratio = ind.get("volume_ratio") or signal.get("volume_ratio") or 1.0
    macd_hist = ind.get("macd_hist") or signal.get("macd_hist") or 0.0
    market_regime = ind.get("market_regime") or signal.get("market_regime") or "UNKNOWN"
    regime_confidence = float(
        ind.get("regime_confidence") or signal.get("regime_confidence") or 0.5
    )

    # Pre-computed cost data (jeśli dostępne z _build_live_signals)
    expected_move_pct = float(
        ind.get("expected_move_pct") or signal.get("expected_move_pct") or 0.0
    )
    total_cost_pct = float(
        ind.get("total_cost_pct") or signal.get("total_cost_pct") or 0.0
    )
    risk_reward = float(ind.get("risk_reward") or signal.get("risk_reward") or 0.0)

    # Jeśli brak ATR — pobierz kontekst z DB (fallback)
    if atr is None and price > 0:
        try:
            from backend.analysis import get_live_context

            ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
            if ctx:
                atr = ctx.get("atr")
                if not rsi:
                    rsi = ctx.get("rsi")
                if not ema_20:
                    ema_20 = ctx.get("ema_20")
                if not ema_50:
                    ema_50 = ctx.get("ema_50")
                if not volume_ratio or volume_ratio == 1.0:
                    volume_ratio = ctx.get("volume_ratio") or 1.0
        except Exception:
            pass

    score = 0.0
    breakdown = []

    # ── 1. Trend score (0–30) ─────────────────────────────────────────
    trend_up = ema_20 and ema_50 and float(ema_20) > float(ema_50)
    trend_down = ema_20 and ema_50 and float(ema_20) < float(ema_50)

    # Jeśli reżim nieznany z DB — wnioskuj z wyrównania EMA (po get_live_context fallback)
    if market_regime == "UNKNOWN":
        if trend_up:
            market_regime = "TREND_UP"
        elif trend_down:
            market_regime = "TREND_DOWN"
        elif ema_20 and ema_50:
            market_regime = "SIDEWAYS"

    if signal_type == "BUY":
        if market_regime == "TREND_UP":
            score += 30.0
            breakdown.append("+30 reżim TREND_UP (BUY)")
        elif trend_up and market_regime not in ("TREND_DOWN", "CHAOS"):
            score += 18.0
            breakdown.append("+18 EMA wyrównane w górę, brak potwierdzenia multi-TF")
        elif trend_up:
            score += 8.0
            breakdown.append("+8 EMA wzrostowe, ale reżim przeciwny")
        else:
            score += 0.0
            breakdown.append("+0 BUY bez wyrównania trendu")
    elif signal_type == "SELL":
        if market_regime == "TREND_DOWN":
            score += 30.0
            breakdown.append("+30 reżim TREND_DOWN (SELL)")
        elif trend_down and market_regime not in ("TREND_UP", "CHAOS"):
            score += 18.0
            breakdown.append("+18 EMA wyrównane w dół")
        elif trend_down:
            score += 8.0
            breakdown.append("+8 EMA spadkowe")
        else:
            score += 0.0
            breakdown.append("+0 SELL bez wyrównania trendu")
    else:
        # HOLD/NO_TRADE
        score += 2.0
        breakdown.append("+2 sygnał HOLD/neutralny")

    # ── 2. Momentum score (0–20) ──────────────────────────────────────
    if rsi is not None:
        rsi_f = float(rsi)
        if signal_type == "BUY":
            # Idealny RSI dla BUY: 45–68
            if 52 <= rsi_f <= 65:
                score += 20.0
                breakdown.append(f"+20 RSI {rsi_f:.0f} — momentum BUY")
            elif 45 <= rsi_f < 52 or 65 < rsi_f <= 72:
                score += 12.0
                breakdown.append(f"+12 RSI {rsi_f:.0f} — akceptowalny BUY")
            elif rsi_f < 45:
                score += 6.0
                breakdown.append(f"+6 RSI {rsi_f:.0f} — wyprzedanie, ostrożnie")
            elif rsi_f > 72:
                score += 2.0
                breakdown.append(f"+2 RSI {rsi_f:.0f} — wykupienie, ryzyko korekty")
        elif signal_type == "SELL":
            if rsi_f >= 68:
                score += 20.0
                breakdown.append(f"+20 RSI {rsi_f:.0f} — momentum SELL")
            elif 55 <= rsi_f < 68:
                score += 12.0
                breakdown.append(f"+12 RSI {rsi_f:.0f} — akceptowalny SELL")
            elif rsi_f < 35:
                score += 3.0
                breakdown.append(
                    f"+3 RSI {rsi_f:.0f} — wyprzedany, ryzyko odwrócenia przy SELL"
                )
            else:
                score += 6.0
                breakdown.append(f"+6 RSI {rsi_f:.0f} — neutralny")

    # ── 3. Volume confirmation (0–15) ─────────────────────────────────
    vol_r = float(volume_ratio or 1.0)
    if vol_r >= 1.5:
        score += 15.0
        breakdown.append(f"+15 wolumen {vol_r:.1f}x avg — silne potwierdzenie")
    elif vol_r >= 1.2:
        score += 10.0
        breakdown.append(f"+10 wolumen {vol_r:.1f}x avg — umiarkowane potwierdzenie")
    elif vol_r >= 1.05:
        score += 5.0
        breakdown.append(f"+5 wolumen {vol_r:.1f}x avg — lekkie potwierdzenie")
    else:
        score += 0.0
        breakdown.append(f"+0 wolumen {vol_r:.1f}x avg — brak potwierdzenia")

    # ── 4. Edge vs cost score (0–20) ──────────────────────────────────
    # Oblicz expected_move jeśli nie przekazano
    atr_take_mult = float(os.getenv("ATR_TAKE_MULT", "2.2"))
    atr_stop_mult = float(os.getenv("ATR_STOP_MULT", "1.3"))
    if not expected_move_pct and atr and price and price > 0:
        expected_move_pct = round(float(atr) * atr_take_mult / price * 100, 3)
    if not risk_reward and atr and price and price > 0:
        risk_pct_local = float(atr) * atr_stop_mult / price * 100
        risk_reward = (
            (expected_move_pct / risk_pct_local) if risk_pct_local > 0 else 0.0
        )
    if not total_cost_pct:
        # Szacunek bazowy: 0.2% + spread
        total_cost_pct = 0.25

    if expected_move_pct > 0 and total_cost_pct > 0:
        ratio = expected_move_pct / total_cost_pct
        if ratio >= 3.0:
            score += 20.0
            breakdown.append(
                f"+20 edge {expected_move_pct:.2f}% vs koszt {total_cost_pct:.2f}% (x{ratio:.1f})"
            )
        elif ratio >= 1.8:
            score += 14.0
            breakdown.append(
                f"+14 edge {expected_move_pct:.2f}% vs koszt {total_cost_pct:.2f}% (x{ratio:.1f})"
            )
        elif ratio >= 1.2:
            score += 7.0
            breakdown.append(
                f"+7 edge {expected_move_pct:.2f}% vs koszt {total_cost_pct:.2f}% (x{ratio:.1f})"
            )
        else:
            score += 0.0
            breakdown.append(
                f"+0 edge za mały ({expected_move_pct:.2f}% vs {total_cost_pct:.2f}%)"
            )
    elif expected_move_pct > 0:
        score += 7.0
        breakdown.append(f"+7 expected_move {expected_move_pct:.2f}% (koszty nieznane)")

    # R/R bonus (już 2.0 to dobry sygnał)
    if risk_reward >= 2.5:
        score += 0.0  # już policzony w edge
    elif risk_reward < 1.5 and signal_type == "BUY":
        score -= 5.0
        breakdown.append(f"-5 R/R={risk_reward:.1f} poniżej minimum 1.5")

    # ── 5. Volatility quality (0–10) ──────────────────────────────────
    if atr and price and price > 0:
        atr_pct = float(atr) / float(price) * 100
        # Idealna zmienność dla spot: 0.5%–3% ATR/price
        if 0.5 <= atr_pct <= 3.0:
            score += 10.0
            breakdown.append(f"+10 ATR {atr_pct:.2f}% — dobra zmienność")
        elif 0.3 <= atr_pct < 0.5 or 3.0 < atr_pct <= 5.0:
            score += 5.0
            breakdown.append(f"+5 ATR {atr_pct:.2f}% — akceptowalna zmienność")
        elif atr_pct > 5.0:
            score += 2.0
            breakdown.append(f"+2 ATR {atr_pct:.2f}% — za wysoka zmienność")
        else:
            score += 2.0
            breakdown.append(f"+2 ATR {atr_pct:.2f}% — za niska zmienność")

    # ── 6. Regime bonus (0–5) ─────────────────────────────────────────
    regime_match = (signal_type == "BUY" and market_regime == "TREND_UP") or (
        signal_type == "SELL" and market_regime == "TREND_DOWN"
    )
    if regime_match and regime_confidence >= 0.75:
        score += 5.0
        breakdown.append(
            f"+5 reżim {market_regime} potwierdzony z conf={regime_confidence:.2f}"
        )
    elif regime_match:
        score += 3.0
        breakdown.append(f"+3 reżim {market_regime} (conf={regime_confidence:.2f})")

    # HOLD penalty
    if signal_type == "HOLD":
        score = min(score, 25.0)
        breakdown.append("HOLD — score ograniczony do 25")

    # Clamp 0–100
    score = round(max(0.0, min(100.0, score)), 1)

    result = dict(signal)
    result["score"] = score
    result["expected_profit_pct"] = (
        round(expected_move_pct, 3) if expected_move_pct else None
    )
    result["risk_pct"] = (
        round(float(atr) * atr_stop_mult / float(price) * 100, 3)
        if atr and price
        else None
    )
    result["score_breakdown"] = breakdown
    result["market_regime"] = market_regime
    if rsi is not None:
        result["rsi"] = round(float(rsi), 2)
    return result


@router.get("/best-opportunity")
def get_best_opportunity(
    mode: str = Query("live", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Najlepsza okazja tradingowa — iteruje kandydatów od najwyższego score
    i zwraca PIERWSZEGO, który przechodzi bramki wejścia.
    CZEKAJ tylko gdy ŻADEN kandydat nie przeszedł.
    """
    try:
        from backend.accounting import compute_demo_account_state
        from backend.database import Order as Ord
        from backend.database import PendingOrder as PO
        from backend.database import RuntimeSetting
        from backend.runtime_settings import build_runtime_state, get_runtime_config

        symbols = _get_symbols_from_db_or_env(db)
        if not symbols:
            return {
                "success": True,
                "opportunity": None,
                "action": "CZEKAJ",
                "reason": "Brak danych rynkowych — kolektor jeszcze nie zebrał danych",
                "candidates_evaluated": 0,
            }

        # Konfiguracja gate'ów
        runtime_ctx = build_runtime_state(db)
        config = runtime_ctx.get("config", {})
        kill_switch = bool(config.get("kill_switch_enabled", True)) and bool(
            config.get("kill_switch_active", False)
        )
        max_open_positions = int(config.get("max_open_positions", 3))
        min_order_notional = float(config.get("min_order_notional", 25.0))
        min_buy_eur = float(config.get("min_buy_eur", 60.0))
        required_cash_eur = max(min_order_notional, min_buy_eur)
        demo_min_conf = float(config.get("demo_min_signal_confidence", 0.55))
        base_cooldown_s = int(
            float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60
        )

        # Profil agresywności — dynamiczne progi
        from backend.runtime_settings import AGGRESSIVENESS_PROFILES

        aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
        aggr_profile = AGGRESSIVENESS_PROFILES.get(
            aggressiveness, AGGRESSIVENESS_PROFILES["balanced"]
        )

        # Stan konta
        demo_quote_ccy = os.getenv("DEMO_QUOTE_CCY", "EUR")
        _live_free_usdc = 0.0
        _live_free_eur = 0.0
        if mode == "demo":
            account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy)
            cash = float(account_state.get("cash") or 0.0)
        else:
            from backend.routers.portfolio import _build_live_spot_portfolio

            live_data = _build_live_spot_portfolio(db)
            if live_data.get("error"):
                # Binance timeout / brak kluczy — fallback na ostatni snapshot
                _snap = (
                    db.query(AccountSnapshot)
                    .filter(AccountSnapshot.mode == "live")
                    .order_by(AccountSnapshot.timestamp.desc())
                    .first()
                )
                cash = float(_snap.free_margin or 0.0) if _snap else 0.0
                _live_free_usdc = 0.0
                _live_free_eur = 0.0
            else:
                cash = float(live_data.get("free_cash_eur", 0.0))
                _live_free_usdc = float(live_data.get("free_usdc", 0.0))
                _live_free_eur = float(live_data.get("free_cash_eur", 0.0))

        open_positions = db.query(Position).filter(Position.mode == mode).all()
        open_symbols = {p.symbol for p in open_positions}
        # significant_open_symbols: pozycje powyżej progu (nie dust) — blokuje duplicate BUY
        # open_symbols (pełny): każde holding, nawet dust — blokuje SELL (twarda blokada)
        DUST_THRESHOLD_EUR = float(os.getenv("DUST_THRESHOLD_EUR", "1.0"))
        significant_open_symbols: set[str] = set()
        for p in open_positions:
            pos_val = float(getattr(p, "quantity", 0) or 0) * float(
                getattr(p, "current_price", 0) or 0
            )
            if pos_val >= DUST_THRESHOLD_EUR:
                significant_open_symbols.add(p.symbol)
            else:
                significant_open_symbols.add(
                    p.symbol
                )  # DB positions always count (bot opened them)

        # Dla LIVE: dodaj symbole z Binance spot do obu zbiorów
        if mode == "live":
            from backend.routers.positions import _get_live_spot_positions

            for sp in _get_live_spot_positions(db):
                sym_sp = sp["symbol"]
                val_sp = float(sp.get("value_eur") or 0)
                open_symbols.add(sym_sp)  # do SELL guard ZAWSZE
                if val_sp >= DUST_THRESHOLD_EUR:
                    significant_open_symbols.add(
                        sym_sp
                    )  # do duplicate_entry tylko gdy znacząca
            # open_count — zlicz tylko znaczące pozycje live spot
            open_count = sum(
                1
                for sp in _get_live_spot_positions(db)
                if float(sp.get("value_eur") or 0) >= DUST_THRESHOLD_EUR
            )
        else:
            open_count = len(open_positions)

        now = utc_now_naive()

        live = _load_signals_from_db_or_live(db, symbols)
        actionable = [s for s in live if s["signal_type"] != "HOLD"]

        if not actionable:
            best_hold = max(live, key=lambda x: x["confidence"]) if live else None
            return {
                "success": True,
                "opportunity": None,
                "action": "CZEKAJ",
                "reason": "Wszystkie sygnały HOLD — rynek bez wyraźnego kierunku",
                "best_hold_symbol": best_hold["symbol"] if best_hold else None,
                "candidates_evaluated": len(live),
            }

        scored = [_score_opportunity(s, db) for s in actionable]
        scored.sort(key=lambda x: -x["score"])

        MIN_SCORE = float(
            config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"])
        )
        MIN_CONFIDENCE = float(
            config.get(
                "demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]
            )
        )

        allowed_candidates = []
        blocked_candidates = []

        for cand in scored:
            sym = cand["symbol"]
            score = float(cand.get("score", 0))
            confidence = float(cand.get("confidence", 0))
            cand_signal_type = cand.get("signal_type", "HOLD")
            cand_ind = cand.get("indicators") or {}
            block_reason = None
            block_reason_code = None

            if kill_switch:
                block_reason = "Kill switch aktywny"
                block_reason_code = "kill_switch_gate"

            # ── SELL guard: nie sprzedawaj bez pozycji (TWARDA BLOKADA) ──
            elif cand_signal_type == "SELL" and sym not in open_symbols:
                block_reason = f"SELL bez pozycji ({sym} nie w portfelu)"
                block_reason_code = "sell_blocked_no_position"

            elif score < MIN_SCORE:
                block_reason = (
                    f"Score {score:.1f}/100 < {MIN_SCORE} — insufficient_edge"
                )
                block_reason_code = "insufficient_score"

            elif confidence < MIN_CONFIDENCE:
                block_reason = f"Pewność {confidence:.0%} < {MIN_CONFIDENCE:.0%}"
                block_reason_code = "confidence_below_threshold"

            # ── Filtr reżimu dla BUY: tylko TREND_UP ────────────────────
            elif cand_signal_type == "BUY":
                regime_from_ind = (
                    cand_ind.get("market_regime")
                    or cand.get("market_regime")
                    or "UNKNOWN"
                )
                if regime_from_ind not in ("TREND_UP", "UNKNOWN"):
                    block_reason = (
                        f"BUY zablokowany — reżim {regime_from_ind} (wymagany TREND_UP)"
                    )
                    block_reason_code = "no_trend_confirmation"

            if not block_reason:
                # ── Filtr kosztów: expected_move > total_cost * 1.8 ─────
                if cand_signal_type == "BUY":
                    em_pct = float(
                        cand.get("expected_profit_pct")
                        or cand_ind.get("expected_move_pct")
                        or 0
                    )
                    tc_pct = float(cand_ind.get("total_cost_pct") or 0)
                    if em_pct > 0 and tc_pct > 0 and em_pct <= tc_pct * 1.8:
                        block_reason = f"Edge {em_pct:.2f}% ≤ koszt {tc_pct:.2f}% × 1.8 — insufficient_edge_after_costs"
                        block_reason_code = "insufficient_edge_after_costs"

            if not block_reason:
                # ── Limity portfelowe ────────────────────────────────────
                if cand_signal_type == "BUY" and open_count >= max_open_positions:
                    block_reason = f"Osiągnięto limit {max_open_positions} pozycji"
                    block_reason_code = "max_positions_reached"
                elif cand_signal_type == "BUY" and sym in significant_open_symbols:
                    block_reason = f"Pozycja już otwarta na {sym} (powyżej progu {DUST_THRESHOLD_EUR} EUR)"
                    block_reason_code = "duplicate_entry"
                elif cand_signal_type == "BUY":
                    # ── USDC-first cash gate ──────────────────────────────
                    # Dla par USDC: sprawdź USDC + EUR (fundingowa konwersja dostępna)
                    # Dla par EUR: sprawdź EUR
                    _sym_quote = "USDC" if str(sym).endswith("USDC") else "EUR"
                    if mode == "live" and _sym_quote == "USDC":
                        from backend.quote_currency import (
                            resolve_required_quote_usdc as _rq,
                        )

                        _req_usdc, _rq_meta = _rq(
                            min_buy_eur, exchange_min_notional=min_order_notional
                        )
                        # Saldo: USDC natywne + EUR przeliczony na USDC (funding conversion available)
                        _eur_rate = float(_rq_meta.get("eur_usdc_rate") or 1.0)
                        _total_available_usdc = (
                            _live_free_usdc + _live_free_eur * _eur_rate
                        )
                        if _total_available_usdc < _req_usdc:
                            block_reason = (
                                f"Brak USDC: dostępne {_live_free_usdc:.2f} USDC "
                                f"(+{_live_free_eur:.2f} EUR jako funding) < "
                                f"minimum {_req_usdc:.2f} USDC"
                            )
                            block_reason_code = "min_notional_guard"
                    else:
                        # Demo lub para EUR — klasyczny gate w EUR
                        if cash < required_cash_eur:
                            block_reason = f"Brak gotówki ({cash:.2f} EUR < minimum {required_cash_eur:.2f} EUR)"
                            block_reason_code = "min_notional_guard"
                else:
                    # Cooldown (tylko BUY)
                    if cand_signal_type == "BUY":
                        last_ord = (
                            db.query(Ord)
                            .filter(Ord.symbol == sym, Ord.mode == mode)
                            .order_by(Ord.timestamp.desc())
                            .first()
                        )
                        if (
                            last_ord
                            and (now - last_ord.timestamp).total_seconds()
                            < base_cooldown_s
                        ):
                            block_reason = (
                                f"Cooldown (ostatnia transakcja "
                                f"{int((now - last_ord.timestamp).total_seconds())}s temu)"
                            )
                            block_reason_code = "cooldown_active"

            if block_reason:
                blocked_candidates.append(
                    {
                        "symbol": sym,
                        "action": cand_signal_type,
                        "score": score,
                        "confidence": confidence,
                        "block_reason": block_reason,
                        "block_reason_code": block_reason_code,
                    }
                )
            else:
                allowed_candidates.append(cand)

        if not allowed_candidates:
            top_blocked = blocked_candidates[0] if blocked_candidates else None
            return {
                "success": True,
                "opportunity": None,
                "action": "CZEKAJ",
                "reason": (
                    (
                        f"Najlepszy kandydat ({top_blocked['symbol']} {top_blocked['action']}) "
                        f"zablokowany: {top_blocked['block_reason']}"
                    )
                    if top_blocked
                    else "Brak kandydatów powyżej progu"
                ),
                "best_candidate": top_blocked,
                "candidates_evaluated": len(scored),
                "blocked_count": len(blocked_candidates),
            }

        best = allowed_candidates[0]

        profit_info = (
            f"zysk szac. +{best['expected_profit_pct']}%, ryzyko -{best['risk_pct']}%"
            if best.get("expected_profit_pct") and best.get("risk_pct")
            else "szacunek zysku niedostępny (brak ATR)"
        )
        reason_parts = [
            f"Confidence: {best['confidence']:.0%}",
            f"Score: {best['score']:.1f}/10+",
            profit_info,
        ]
        if best.get("indicators", {}).get("rsi") is not None:
            reason_parts.append(f"RSI: {best['indicators']['rsi']:.0f}")

        return {
            "success": True,
            "opportunity": {
                "symbol": best["symbol"],
                "action": best["signal_type"],
                "confidence": best["confidence"],
                "score": best["score"],
                "expected_profit_pct": best.get("expected_profit_pct"),
                "risk_pct": best.get("risk_pct"),
                "price": best.get("price"),
                "indicators": best.get("indicators"),
                "score_breakdown": best.get("score_breakdown"),
                "timestamp": best.get("timestamp"),
            },
            "action": best["signal_type"],
            "reason": " | ".join(reason_parts),
            "candidates_evaluated": len(scored),
            "allowed_count": len(allowed_candidates),
            "blocked_count": len(blocked_candidates),
            "runner_up": (
                {
                    "symbol": allowed_candidates[1]["symbol"],
                    "action": allowed_candidates[1]["signal_type"],
                    "score": allowed_candidates[1]["score"],
                    "confidence": allowed_candidates[1]["confidence"],
                }
                if len(allowed_candidates) > 1
                else None
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd best-opportunity: {str(e)}")


@router.get("/wait-status")
def get_wait_status(db: Session = Depends(get_db)):
    """
    Szczegółowy status oczekiwania dla każdego symbolu — Na co system czeka?
    Pokazuje brakujące warunki wejścia (confidence, trend, RSI) z konkretnymi wartościami.
    """
    try:
        from backend.runtime_settings import (
            AGGRESSIVENESS_PROFILES,
            build_runtime_state,
            get_runtime_config,
        )

        runtime_ctx = build_runtime_state(db)
        config = runtime_ctx.get("config", {})
        aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
        aggr_profile = AGGRESSIVENESS_PROFILES.get(
            aggressiveness, AGGRESSIVENESS_PROFILES["balanced"]
        )
        MIN_SCORE = float(
            config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"])
        )
        MIN_CONFIDENCE = float(
            config.get(
                "demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]
            )
        )

        symbols = _get_symbols_from_db_or_env(db, include_spot=False)
        if not symbols:
            return {
                "success": True,
                "items": [],
                "note": "Brak danych rynkowych — kolektor nie zebrał jeszcze danych",
            }

        live = _load_signals_from_db_or_live(db, symbols)

        scored_all = [_score_opportunity(s, db) for s in live]
        scored_all.sort(key=lambda x: -x["score"])

        items = []
        for s in scored_all:
            signal_type = s.get("signal_type", "HOLD")
            confidence = float(s.get("confidence") or 0)
            score = float(s.get("score") or 0)
            ind = s.get("indicators") or {}
            rsi = ind.get("rsi")
            ema_20 = ind.get("ema_20")
            ema_50 = ind.get("ema_50")
            price = float(s.get("price") or 0)
            market_regime = (
                ind.get("market_regime") or s.get("market_regime") or "UNKNOWN"
            )
            em_pct = s.get("expected_profit_pct") or ind.get("expected_move_pct") or 0
            tc_pct = ind.get("total_cost_pct") or 0

            # Oblicz brakujące warunki
            missing_conditions = []
            status = "WAIT"

            if signal_type == "HOLD":
                missing_conditions.append(
                    {
                        "condition": "Reżim rynku",
                        "current": f"{market_regime} — brak wyraźnej przewagi",
                        "required": "TREND_UP (BUY) lub TREND_DOWN (SELL)",
                        "met": False,
                    }
                )
                status = "HOLD"
            else:
                # Sprawdź reżim (priorytet 1)
                if signal_type == "BUY" and market_regime not in (
                    "TREND_UP",
                    "UNKNOWN",
                ):
                    missing_conditions.append(
                        {
                            "condition": "Reżim TREND_UP",
                            "current": f"Reżim: {market_regime}",
                            "required": "TREND_UP — wyrównane EMA 15m i 1h w górę",
                            "met": False,
                        }
                    )

                # Sprawdź confidence
                if confidence < MIN_CONFIDENCE:
                    missing_conditions.append(
                        {
                            "condition": "Pewność sygnału",
                            "current": f"{confidence:.0%}",
                            "required": f"{MIN_CONFIDENCE:.0%}",
                            "met": False,
                        }
                    )

                # Sprawdź score (skala 0–100)
                if score < MIN_SCORE:
                    missing_conditions.append(
                        {
                            "condition": "Score okazji",
                            "current": f"{score:.1f}/100",
                            "required": f"{MIN_SCORE:.0f}/100",
                            "met": False,
                        }
                    )

                # Filtr kosztów dla BUY
                if (
                    signal_type == "BUY"
                    and em_pct
                    and tc_pct
                    and float(em_pct) <= float(tc_pct) * 1.8
                ):
                    missing_conditions.append(
                        {
                            "condition": "Edge > koszt × 1.8",
                            "current": f"Edge {float(em_pct):.2f}% vs koszt {float(tc_pct):.2f}%",
                            "required": f"Edge > {float(tc_pct) * 1.8:.2f}%",
                            "met": False,
                        }
                    )

                # RSI
                if rsi is not None:
                    rsi_f = float(rsi)
                    if signal_type == "BUY" and rsi_f > 72:
                        missing_conditions.append(
                            {
                                "condition": "RSI < 72 (nie wykupiony)",
                                "current": f"RSI={rsi_f:.0f}",
                                "required": "RSI 52–72",
                                "met": False,
                            }
                        )
                    elif signal_type == "SELL" and rsi_f < 30:
                        missing_conditions.append(
                            {
                                "condition": "RSI > 30 (nie wyprzedany)",
                                "current": f"RSI={rsi_f:.0f}",
                                "required": "RSI > 45",
                                "met": False,
                            }
                        )

                if not missing_conditions:
                    status = "READY"
                else:
                    status = "WAIT"

            action_pl = {"BUY": "KUP", "SELL": "SPRZEDAJ", "HOLD": "TRZYMAJ"}.get(
                signal_type, signal_type
            )
            status_pl = {
                "READY": "Gotowy do wejścia",
                "WAIT": "Czeka na warunki",
                "HOLD": "W trzymaniu",
            }.get(status, status)

            items.append(
                {
                    "symbol": s["symbol"],
                    "signal_type": signal_type,
                    "action_pl": action_pl,
                    "status": status,
                    "status_pl": status_pl,
                    "confidence": round(confidence, 3),
                    "confidence_min": MIN_CONFIDENCE,
                    "score": round(score, 1),
                    "score_min": MIN_SCORE,
                    "price": round(price, 6) if price else None,
                    "rsi": round(float(rsi), 1) if rsi is not None else None,
                    "ema_20": round(float(ema_20), 6) if ema_20 else None,
                    "ema_50": round(float(ema_50), 6) if ema_50 else None,
                    "market_regime": market_regime,
                    "trend": (
                        "WZROSTOWY"
                        if market_regime == "TREND_UP"
                        else (
                            "SPADKOWY"
                            if market_regime == "TREND_DOWN"
                            else (
                                "WZROSTOWY"
                                if (ema_20 and ema_50 and float(ema_20) > float(ema_50))
                                else (
                                    "SPADKOWY" if (ema_20 and ema_50) else "BRAK DANYCH"
                                )
                            )
                        )
                    ),
                    "missing_conditions": missing_conditions,
                    "expected_profit_pct": s.get("expected_profit_pct"),
                    "total_cost_pct": float(tc_pct) if tc_pct else None,
                    "risk_pct": s.get("risk_pct"),
                    "score_breakdown": s.get("score_breakdown", []),
                }
            )

        ready = [i for i in items if i["status"] == "READY"]
        waiting = [i for i in items if i["status"] == "WAIT"]
        holding = [i for i in items if i["status"] == "HOLD"]

        return {
            "success": True,
            "items": items,
            "summary": {
                "total": len(items),
                "ready": len(ready),
                "waiting": len(waiting),
                "holding": len(holding),
            },
            "min_confidence": MIN_CONFIDENCE,
            "min_score": MIN_SCORE,
            "updated_at": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd wait-status: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# EXPECTATION ENGINE — ocena realności celu użytkownika
# ─────────────────────────────────────────────────────────────────────────────


def _assess_goal_realism(
    symbol_analysis: dict,
    position_state: Optional[dict],
    target_value_eur: Optional[float] = None,
    target_price: Optional[float] = None,
    target_profit_pct: Optional[float] = None,
) -> dict:
    """
    Ocenia, czy cel użytkownika jest realny i kiedy może zostać spełniony.
    Uwzględnia: dystans do celu, trend, RSI, zmienność ATR.
    Zwraca: realism_score (0-1), label, scenariusze (dni), przeszkody.
    """
    if not position_state:
        return {"realism_label": "brak_pozycji", "realism_score": 0.0}

    current_value_eur = position_state.get("position_value_eur") or 0
    current_price = position_state.get("current_price") or 0
    entry_price = position_state.get("entry_price") or 0
    rsi = symbol_analysis.get("rsi")
    trend = symbol_analysis.get("trend", "BRAK DANYCH")
    confidence = float(symbol_analysis.get("confidence") or 0.5)

    # Określ cel i wymagany ruch
    required_move_pct = 0.0
    target_type = None
    target_val = None

    if target_value_eur and current_value_eur > 0:
        target_type = "value_eur"
        target_val = target_value_eur
        required_move_pct = (
            (target_value_eur - current_value_eur) / current_value_eur * 100
        )
    elif target_price and current_price > 0:
        target_type = "price"
        target_val = target_price
        required_move_pct = (target_price - current_price) / current_price * 100
    elif target_profit_pct and entry_price > 0:
        target_type = "pct"
        target_val = target_profit_pct
        current_pnl_pct = (
            (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        )
        required_move_pct = target_profit_pct - current_pnl_pct

    if target_type is None:
        return {"realism_label": "brak_celu", "realism_score": 0.0}

    abs_move = abs(required_move_pct)
    going_up = required_move_pct >= 0

    # Ocena realności: start od bazowego 0.65
    score = 0.65

    # Korekta wg dystansu do celu
    if abs_move < 3:
        score += 0.20
    elif abs_move < 8:
        score += 0.08
    elif abs_move < 15:
        score -= 0.05
    elif abs_move < 25:
        score -= 0.18
    elif abs_move < 40:
        score -= 0.30
    else:
        score -= 0.45

    # Korekta wg trendu
    if going_up:
        if trend == "WZROSTOWY":
            score += 0.12
        elif trend == "SPADKOWY":
            score -= 0.22
    else:
        if trend == "SPADKOWY":
            score += 0.12
        elif trend == "WZROSTOWY":
            score -= 0.22

    # Korekta wg RSI
    if rsi is not None:
        if going_up and rsi < 40:
            score += 0.06
        elif going_up and rsi > 75:
            score -= 0.12
        elif not going_up and rsi > 65:
            score += 0.06
        elif not going_up and rsi < 30:
            score -= 0.12

    # Uwzględnienie pewności sygnału
    score += (confidence - 0.5) * 0.08

    score = max(0.05, min(0.97, score))

    # Label realności
    if score >= 0.80:
        label = "bardzo_realny"
    elif score >= 0.65:
        label = "realny"
    elif score >= 0.50:
        label = "umiarkowanie_realny"
    elif score >= 0.30:
        label = "trudny"
    else:
        label = "mało_realny"

    # Scenariusze czasowe (dni) — zakładamy codzienne ruchy 0.8–4%
    # Im większy dystans, tym więcej dni
    fast_rate = max(0.1, 3.5)  # % dziennie, optymistycznie
    base_rate = max(0.1, 1.8)
    slow_rate = max(0.1, 0.7)

    scenario_fast = round(abs_move / fast_rate, 1) if abs_move > 0 else 0
    scenario_base = round(abs_move / base_rate, 1) if abs_move > 0 else 0
    scenario_slow = round(abs_move / slow_rate, 1) if abs_move > 0 else 0

    # Przeszkody
    blockers = []
    if going_up and trend == "SPADKOWY":
        blockers.append("Obecny trend spadkowy działa przeciwko celowi")
    if going_up and rsi is not None and rsi > 72:
        blockers.append(
            f"RSI {rsi:.0f} — symbol wykupiony, możliwa korekta przed wzrostem"
        )
    if abs_move > 20:
        blockers.append("Duży dystans do celu wymaga prolongowanego trendu")
    if abs_move > 35:
        blockers.append("Cel może wymagać wielu tygodni lub zmian fundamentalnych")

    # Wyniki dla missing_value
    if target_type == "value_eur":
        current_ref = current_value_eur
        missing = round(target_val - current_ref, 2)
    elif target_type == "price":
        current_ref = current_price
        missing = round(abs(target_val - current_ref), 6)
    else:
        current_ref = position_state.get("pnl_pct") or 0
        missing = round(target_profit_pct - current_ref, 2)

    return {
        "target_type": target_type,
        "target_value": round(target_val, 4) if target_val else None,
        "current_value": round(current_ref, 4) if current_ref else None,
        "missing_value": round(abs(missing), 4),
        "required_move_pct": round(required_move_pct, 2),
        "realism_score": round(score, 3),
        "realism_label": label,
        "scenario_fast_days": scenario_fast,
        "scenario_base_days": scenario_base,
        "scenario_slow_days": scenario_slow,
        "blockers": blockers,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FINAL ACTION RESOLVER v2 — 6-warstwowy silnik decyzji
# ─────────────────────────────────────────────────────────────────────────────

_ACTION_PL = {
    "BUY": "KUP",
    "SELL": "SPRZEDAJ",
    "HOLD": "TRZYMAJ",
    "HOLD_TARGET": "TRZYMAJ (CEL)",
    "PREPARE_EXIT": "PRZYGOTUJ SPRZEDAŻ",
    "PARTIAL_EXIT": "SPRZEDAJ CZĘŚĆ",
    "SELL_AT_TARGET": "SPRZEDAJ NA CELU",
    "DO_NOT_ADD": "NIE DOKŁADAJ",
    "NO_NEW_ENTRIES": "BRAK NOWYCH WEJŚĆ",
    "WAIT": "CZEKAJ",
    "WAIT_FOR_SIGNAL": "CZEKAJ NA SYGNAŁ",
    "KANDYDAT_DO_WEJŚCIA": "KANDYDAT DO WEJŚCIA",
    "WEJŚCIE_AKTYWNE": "WEJŚCIE AKTYWNE",
}


def _final_action_resolver(
    symbol: str,
    signal: dict,
    scored: dict,
    position: Optional[object],
    tier_config: dict,
    mode: str,
    user_expectations: Optional[list] = None,
) -> dict:
    """
    6-warstwowy resolver decyzji końcowej:

    Warstwa 1 — Bezpieczeństwo (freeze, brak danych, uszkodzony rynek)
    Warstwa 2 — Oczekiwanie użytkownika (cel wartości, zakazy, profil)
    Warstwa 3 — Reguły portfelowe / tier (hold_mode, no_new_entries)
    Warstwa 4 — Logika pozycji (blisko TP/SL, realizacja zysku)
    Warstwa 5 — Sygnał techniczny (RSI/EMA)

    Zwraca: final_action, blocked_actions, allowed_actions, winning_priority,
            goal_assessment (jeśli aktywny cel), symbol_analysis, position_state
    """
    signal_type = signal.get("signal_type", "HOLD")
    confidence = float(signal.get("confidence") or 0)
    price = float(signal.get("price") or 0)
    ind = signal.get("indicators") or {}
    rsi = ind.get("rsi")
    ema_20 = ind.get("ema_20")
    ema_50 = ind.get("ema_50")
    score = float(scored.get("score") or 0)

    # ── Analiza symbolu (zawsze liczona, niezależnie od priorytetu) ────
    trend = (
        "WZROSTOWY"
        if (ema_20 and ema_50 and float(ema_20) > float(ema_50))
        else "SPADKOWY" if (ema_20 and ema_50) else "BRAK DANYCH"
    )
    symbol_analysis = {
        "signal_type": signal_type,
        "confidence": round(confidence, 3),
        "score": round(score, 2),
        "rsi": round(float(rsi), 1) if rsi is not None else None,
        "trend": trend,
        "price": round(price, 6) if price else None,
        "raw_reason": signal.get("reason"),
    }

    # ── Stan pozycji ──────────────────────────────────────────────────
    position_state = None
    if position is not None:
        entry_price = float(getattr(position, "entry_price", 0) or 0)
        qty = float(getattr(position, "quantity", 0) or 0)
        planned_tp = float(getattr(position, "planned_tp", 0) or 0)
        planned_sl = float(getattr(position, "planned_sl", 0) or 0)
        unrealized_pnl = float(getattr(position, "unrealized_pnl", 0) or 0)
        cur_p = float(getattr(position, "current_price", 0) or 0) or price
        pos_val = qty * (cur_p or price)
        pnl_pct = ((cur_p - entry_price) / entry_price * 100) if entry_price > 0 else 0

        position_state = {
            "entry_price": round(entry_price, 6),
            "quantity": round(qty, 6),
            "current_price": round(cur_p, 6) if cur_p else None,
            "position_value_eur": round(pos_val, 2) if pos_val else None,
            "pnl_pct": round(pnl_pct, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "planned_tp": round(planned_tp, 6) if planned_tp else None,
            "planned_sl": round(planned_sl, 6) if planned_sl else None,
        }

    # Zainicjuj wartości robocze
    final_action = signal_type
    final_reason = "Sygnał techniczny"
    next_trigger: Optional[str] = None
    winning_priority = "symbol_signal"
    portfolio_state = None
    goal_assessment: Optional[dict] = None
    blocked_actions: list = []
    allowed_actions: list = ["HOLD", "BUY", "SELL", "PARTIAL_EXIT"]

    # Aktywne oczekiwanie użytkownika dla tego symbolu (pierwsze aktywne)
    active_exp: Optional[dict] = None
    if user_expectations:
        sym_norm = symbol.strip().upper()
        for exp in user_expectations:
            exp_sym = (exp.get("symbol") or "").strip().upper()
            if exp_sym == sym_norm and exp.get("is_active", True):
                active_exp = exp
                break

    # ──────────────────────────────────────────────────────────────────
    # WARSTWA 1: Bezpieczeństwo — brak danych rynkowych
    # ──────────────────────────────────────────────────────────────────
    if not price or price <= 0:
        final_action = "WAIT"
        final_reason = "Brak aktualnej ceny rynkowej — pomiń decyzję"
        next_trigger = "Poczekaj na zsynchronizowanie danych rynkowych"
        winning_priority = "safety"
        allowed_actions = []
        blocked_actions = ["BUY", "SELL", "PARTIAL_EXIT"]

    # ──────────────────────────────────────────────────────────────────
    # WARSTWA 2: Oczekiwanie użytkownika
    # ──────────────────────────────────────────────────────────────────
    elif active_exp:
        exp_type = active_exp.get("expectation_type", "")
        no_buy = active_exp.get("no_buy", False)
        no_sell = active_exp.get("no_sell", False)
        no_auto_exit = active_exp.get("no_auto_exit", False)
        t_val_eur = float(active_exp.get("target_value_eur") or 0)
        t_price = float(active_exp.get("target_price") or 0)
        t_pct = float(active_exp.get("target_profit_pct") or 0)
        horizon = active_exp.get("preferred_horizon") or "7d"
        profile = active_exp.get("profile_mode") or ""

        winning_priority = "user_goal"

        # Ocena realności celu
        if t_val_eur or t_price or t_pct:
            goal_assessment = _assess_goal_realism(
                symbol_analysis=symbol_analysis,
                position_state=position_state,
                target_value_eur=t_val_eur or None,
                target_price=t_price or None,
                target_profit_pct=t_pct or None,
            )

        # Cel wartości pozycji w EUR
        if t_val_eur and position_state:
            pos_val = position_state.get("position_value_eur") or 0
            remaining = t_val_eur - pos_val
            dist_pct = (remaining / pos_val * 100) if pos_val > 0 else None

            position_state["hold_target_eur"] = t_val_eur
            position_state["remaining_to_target_eur"] = round(remaining, 2)
            position_state["distance_to_target_pct"] = (
                round(dist_pct, 1) if dist_pct is not None else None
            )

            allowed_actions = ["HOLD", "PARTIAL_EXIT", "SELL_AT_TARGET"]
            blocked_actions = ["BUY"]  # nie dokładaj do pozycji z celem

            if dist_pct is not None and dist_pct <= 2:
                final_action = "SELL_AT_TARGET"
                final_reason = f"Cel osiągnięty — wartość pozycji {pos_val:.0f} EUR ≥ {t_val_eur:.0f} EUR"
                next_trigger = f"Sprzedaj całość (cel: {t_val_eur:.0f} EUR)"
            elif dist_pct is not None and dist_pct <= 8:
                final_action = "PREPARE_EXIT"
                final_reason = (
                    f"Blisko celu {t_val_eur:.0f} EUR — "
                    f"brakuje {remaining:.1f} EUR ({dist_pct:.1f}%)"
                )
                next_trigger = (
                    f"Przygotuj zlecenie SELL gdy wartość ≥ {t_val_eur * 0.97:.0f} EUR"
                )
            else:
                final_action = "HOLD_TARGET"
                cur_p_str = f"{position_state.get('current_price') or 0:.4f}"
                final_reason = (
                    f"Użytkownik czeka na {t_val_eur:.0f} EUR za całość. "
                    f"Teraz: {pos_val:.0f} EUR, brakuje {remaining:.1f} EUR ({dist_pct:.1f}%)"
                )
                next_trigger = (
                    f"Cena musi wzrosnąć o {dist_pct:.1f}% (z {cur_p_str} EUR)"
                    if dist_pct
                    else "Brak danych o cenie"
                )

        # Cel wartości pozycji w EUR — gdy NIE MA pozycji
        elif t_val_eur and not position_state:
            final_action = "WAIT" if no_buy else signal_type
            blocked_actions = ["BUY"] if no_buy else []
            final_reason = (
                "Brak pozycji — chcesz osiągnąć cel wartości, ale nie masz jeszcze wejścia"
                if not no_buy
                else "Zakaz nowego zakupu aktywny, nowe wejście zablokowane"
            )
            winning_priority = "user_goal" if no_buy else "symbol_signal"

        # Cel ceny
        elif t_price and position_state:
            cur_p = position_state.get("current_price") or 0
            dist_price_pct = (t_price - cur_p) / cur_p * 100 if cur_p > 0 else None
            allowed_actions = ["HOLD", "SELL_AT_TARGET", "PARTIAL_EXIT"]
            blocked_actions = ["BUY"]
            if dist_price_pct is not None and dist_price_pct <= 1:
                final_action = "SELL_AT_TARGET"
                final_reason = f"Cel cenowy osiągnięty: {cur_p:.4f} ≈ {t_price:.4f} EUR"
            elif dist_price_pct is not None and dist_price_pct <= 5:
                final_action = "PREPARE_EXIT"
                final_reason = f"Blisko celu cenowego {t_price:.4f} EUR (brakuje {dist_price_pct:.1f}%)"
            else:
                final_action = "HOLD_TARGET"
                final_reason = (
                    f"Cel cenowy: {t_price:.4f} EUR. "
                    f"Teraz: {cur_p:.4f} EUR — brakuje {dist_price_pct:.1f}%"
                    if dist_price_pct
                    else f"Czekaj na cenę {t_price:.4f} EUR"
                )
            next_trigger = f"Sprzedaj gdy cena ≥ {t_price:.4f} EUR"

        # Cel procentowy zysku
        elif t_pct and position_state:
            pnl_pct = position_state.get("pnl_pct") or 0
            dist_pct_profit = t_pct - pnl_pct
            allowed_actions = ["HOLD", "SELL_AT_TARGET", "PARTIAL_EXIT"]
            blocked_actions = ["BUY"]
            if dist_pct_profit <= 0:
                final_action = "SELL_AT_TARGET"
                final_reason = f"Cel zysku osiągnięty: {pnl_pct:+.1f}% ≥ {t_pct:+.1f}%"
            elif dist_pct_profit <= 2:
                final_action = "PREPARE_EXIT"
                final_reason = (
                    f"Blisko celu zysku {t_pct:+.1f}% (teraz: {pnl_pct:+.1f}%)"
                )
            else:
                final_action = "HOLD_TARGET"
                final_reason = f"Cel zysku: {t_pct:+.1f}%. Teraz: {pnl_pct:+.1f}%, brakuje {dist_pct_profit:.1f}%"
            next_trigger = f"Sprzedaj gdy zysk ≥ {t_pct:+.1f}%"

        # Zakaz kupna (bez określonego celu)
        elif no_buy:
            blocked_actions = ["BUY"]
            if signal_type == "BUY":
                final_action = "WAIT_FOR_SIGNAL"
                final_reason = "Sygnał techniczny: KUP — ale zakaz zakupu ustawiony przez użytkownika"
            else:
                final_action = signal_type
                final_reason = (
                    "Sygnał techniczny (zakaz kupna aktywny, ale brak sygnału KUP)"
                )
            winning_priority = "user_goal" if signal_type == "BUY" else "symbol_signal"

        # Zakaz sprzedaży
        elif no_sell:
            blocked_actions = ["SELL", "PARTIAL_EXIT", "PREPARE_EXIT"]
            if signal_type == "SELL":
                final_action = "HOLD"
                final_reason = "Sygnał techniczny: SPRZEDAJ — ale zakaz sprzedaży ustawiony przez użytkownika"
            else:
                final_action = signal_type
                final_reason = "Sygnał techniczny (zakaz sprzedaży aktywny)"
            winning_priority = "user_goal" if signal_type == "SELL" else "symbol_signal"

        else:
            # Aktywne oczekiwanie, ale bez konkretnego celu → przekaż do niższych warstw
            winning_priority = "symbol_signal"
            final_action = signal_type
            final_reason = (
                "Sygnał techniczny (aktywne oczekiwanie, brak konkretnego celu)"
            )

    # ──────────────────────────────────────────────────────────────────
    # WARSTWA 3: Reguły portfelowe / tier (hold_mode, no_new_entries)
    # ──────────────────────────────────────────────────────────────────
    if winning_priority not in ("safety", "user_goal"):
        hold_mode = tier_config.get("hold_mode", False)
        no_new_entries = tier_config.get("no_new_entries", False)
        tier_target_eur = float(tier_config.get("target_value_eur", 0) or 0)

        if hold_mode or no_new_entries:
            winning_priority = "portfolio_tier"

            if position_state is not None and tier_target_eur > 0:
                pos_val = position_state.get("position_value_eur") or 0
                remaining = tier_target_eur - pos_val
                dist_pct = (remaining / pos_val * 100) if pos_val > 0 else None

                position_state["hold_target_eur"] = tier_target_eur
                position_state["remaining_to_target_eur"] = round(remaining, 2)
                position_state["distance_to_target_pct"] = (
                    round(dist_pct, 1) if dist_pct is not None else None
                )

                if dist_pct is not None and dist_pct <= 5:
                    final_action = "PREPARE_EXIT"
                    final_reason = (
                        f"Tier TARGET — cel {tier_target_eur:.0f} EUR prawie osiągnięty "
                        f"(teraz: {pos_val:.0f} EUR, brakuje {remaining:.1f} EUR)"
                    )
                    next_trigger = f"Sprzedaj gdy wartość ≥ {tier_target_eur:.0f} EUR"
                else:
                    final_action = "HOLD_TARGET"
                    final_reason = (
                        f"Tier TARGET — trzymaj do {tier_target_eur:.0f} EUR "
                        f"(teraz: {pos_val:.0f} EUR, brakuje {remaining:.1f} EUR)"
                    )
                    next_trigger = (
                        f"Cena musi wzrosnąć o ~{dist_pct:.1f}%"
                        if dist_pct
                        else "Brak danych o cenie"
                    )
            elif position_state is None:
                final_action = "WAIT"
                final_reason = (
                    f"Symbol '{symbol}' — brak nowych wejść (konfiguracja tier)"
                )
                next_trigger = "Zmień konfigurację symbol_tiers, aby odblokować zakup"
            else:
                final_action = "HOLD_TARGET"
                final_reason = f"Tryb HOLD (tier) — trzymaj pozycję"

            blocked_actions = list(set(blocked_actions + ["BUY"]))
            if "BUY" in allowed_actions:
                allowed_actions.remove("BUY")

    # ──────────────────────────────────────────────────────────────────
    # WARSTWA 4: Logika pozycji (blisko TP/SL, realizacja zysku)
    # ──────────────────────────────────────────────────────────────────
    if (
        winning_priority not in ("safety", "user_goal", "portfolio_tier")
        and position_state is not None
    ):
        pnl_pct = position_state.get("pnl_pct", 0)
        pl_tp = position_state.get("planned_tp")
        pl_sl = position_state.get("planned_sl")
        cur_p = position_state.get("current_price") or price

        # Blisko TP — przygotuj wyjście
        if pl_tp and cur_p and pl_tp > 0:
            tp_dist_pct = (pl_tp - cur_p) / cur_p * 100
            if 0 < tp_dist_pct <= 3:
                winning_priority = "position_mgmt"
                final_action = "PREPARE_EXIT"
                final_reason = f"Cena blisko TP ({cur_p:.4f} → {pl_tp:.4f}, brakuje {tp_dist_pct:.1f}%)"
                next_trigger = f"TP osiągnięty przy {pl_tp:.4f} EUR"

        # Blisko SL — alarm
        if pl_sl and cur_p and pl_sl > 0 and winning_priority == "symbol_signal":
            sl_dist_pct = (cur_p - pl_sl) / cur_p * 100
            if 0 < sl_dist_pct <= 1.5:
                winning_priority = "position_mgmt"
                final_action = "PREPARE_EXIT"
                final_reason = f"Cena bardzo blisko SL ({cur_p:.4f} → SL {pl_sl:.4f}, margines {sl_dist_pct:.1f}%)"
                next_trigger = f"SL zostanie uderzony przy {pl_sl:.4f} EUR"

        # Duży zysk + sygnał BUY → nie dokładaj
        if (
            pnl_pct >= 8
            and winning_priority == "symbol_signal"
            and signal_type == "BUY"
        ):
            winning_priority = "position_mgmt"
            final_action = "DO_NOT_ADD"
            final_reason = f"Pozycja już zyskowna ({pnl_pct:+.1f}%) — nie dokładaj, ryzyko ekspozycji"
            next_trigger = "Rozważ częściową realizację zysku przy dalszym wzroście"
            blocked_actions = list(set(blocked_actions + ["BUY"]))

        if winning_priority == "symbol_signal":
            final_reason = (
                f"Sygnał techniczny (istniejąca pozycja, PnL {pnl_pct:+.1f}%)"
            )

    # ──────────────────────────────────────────────────────────────────
    # WARSTWA 5: Sygnał techniczny (domyślny)
    # ──────────────────────────────────────────────────────────────────
    if winning_priority == "symbol_signal":
        if signal_type == "BUY" and confidence >= 0.70:
            final_action = "BUY"
            final_reason = signal.get("reason") or "RSI/EMA dają sygnał kupna"
        elif signal_type == "SELL" and confidence >= 0.60:
            final_action = "SELL"
            final_reason = signal.get("reason") or "RSI/EMA dają sygnał sprzedaży"
        elif signal_type == "BUY" and confidence >= 0.45:
            final_action = "KANDYDAT_DO_WEJŚCIA"
            final_reason = (
                f"Kandydat do wejścia (pewność {confidence*100:.0f}%) — sygnał kupna"
            )
        else:
            final_action = "HOLD"
            final_reason = signal.get("reason") or "Brak wyraźnego sygnału"

    final_action_pl = _ACTION_PL.get(final_action, final_action)

    return {
        "symbol": symbol,
        "mode": mode,
        "final_action": final_action,
        "final_action_pl": final_action_pl,
        "priority_rule": winning_priority,
        "final_reason": final_reason,
        "next_trigger": next_trigger,
        "blocked_actions": blocked_actions,
        "allowed_actions": allowed_actions,
        "symbol_analysis": symbol_analysis,
        "position_state": position_state,
        "portfolio_state": portfolio_state,
        "goal_assessment": goal_assessment,
        "active_expectation": active_exp,
        "tier_config": {
            "tier": tier_config.get("tier"),
            "hold_mode": tier_config.get("hold_mode", False),
            "no_new_entries": tier_config.get("no_new_entries", False),
            "target_value_eur": float(tier_config.get("target_value_eur") or 0) or None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# CRUD ENDPOINTS — oczekiwania użytkownika
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/expectations")
def get_expectations(
    mode: str = Query("live"),
    symbol: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Pobierz aktywne oczekiwania użytkownika (opcjonalnie filtruj po symbolu)."""
    try:
        q = db.query(UserExpectation).filter(
            UserExpectation.mode == mode,
            UserExpectation.is_active == True,
        )
        if symbol:
            q = q.filter(UserExpectation.symbol == symbol.strip().upper())
        rows = q.order_by(UserExpectation.created_at.desc()).all()

        result = []
        for r in rows:
            result.append(
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "mode": r.mode,
                    "expectation_type": r.expectation_type,
                    "target_value_eur": r.target_value_eur,
                    "target_price": r.target_price,
                    "target_profit_pct": r.target_profit_pct,
                    "no_buy": bool(r.no_buy),
                    "no_sell": bool(r.no_sell),
                    "no_auto_exit": bool(r.no_auto_exit),
                    "preferred_horizon": r.preferred_horizon,
                    "profile_mode": r.profile_mode,
                    "notes": r.notes,
                    "is_active": bool(r.is_active),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return {"success": True, "expectations": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania oczekiwań: {str(e)}"
        )


@router.post("/expectations")
async def set_expectation(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Utwórz lub zaktualizuj oczekiwanie użytkownika dla symbolu.
    Body JSON: symbol, mode, expectation_type, target_value_eur?, target_price?,
               target_profit_pct?, no_buy?, no_sell?, no_auto_exit?,
               preferred_horizon?, profile_mode?, notes?

    expectation_type: "target_value_eur" | "target_price" | "target_profit_pct"
                    | "no_buy" | "no_sell" | "profile_mode"
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Nieprawidłowy JSON")

    symbol_raw = (data.get("symbol") or "").strip().upper()
    mode_raw = (data.get("mode") or "demo").strip().lower()
    exp_type = (data.get("expectation_type") or "").strip()

    if not exp_type:
        raise HTTPException(
            status_code=400, detail="Pole 'expectation_type' jest wymagane"
        )

    # Deaktywuj poprzednie oczekiwanie tego samego typu dla symbolu
    db.query(UserExpectation).filter(
        UserExpectation.symbol == (symbol_raw or None),
        UserExpectation.mode == mode_raw,
        UserExpectation.expectation_type == exp_type,
        UserExpectation.is_active == True,
    ).update({"is_active": False})

    exp = UserExpectation(
        symbol=symbol_raw or None,
        mode=mode_raw,
        expectation_type=exp_type,
        target_value_eur=(
            float(data["target_value_eur"])
            if data.get("target_value_eur") is not None
            else None
        ),
        target_price=(
            float(data["target_price"])
            if data.get("target_price") is not None
            else None
        ),
        target_profit_pct=(
            float(data["target_profit_pct"])
            if data.get("target_profit_pct") is not None
            else None
        ),
        no_buy=bool(data.get("no_buy", False)),
        no_sell=bool(data.get("no_sell", False)),
        no_auto_exit=bool(data.get("no_auto_exit", False)),
        preferred_horizon=data.get("preferred_horizon"),
        profile_mode=data.get("profile_mode"),
        notes=data.get("notes"),
        is_active=True,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    return {
        "success": True,
        "message": f"Oczekiwanie zapisane dla {symbol_raw or 'portfela'}",
        "id": exp.id,
    }


@router.delete("/expectations/{expectation_id}")
def delete_expectation(
    expectation_id: int,
    db: Session = Depends(get_db),
):
    """Deaktywuj oczekiwanie użytkownika (soft delete)."""
    row = db.query(UserExpectation).filter(UserExpectation.id == expectation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Oczekiwanie nie znalezione")
    row.is_active = False
    db.commit()
    return {"success": True, "message": "Oczekiwanie deaktywowane"}


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT — finalne decyzje z pełnym kontekstem (6 warstw)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/final-decisions")
def get_final_decisions(
    mode: str = Query("live", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Finalne decyzje portfelowe — 6-warstwowy resolver:
    bezpieczeństwo → cel użytkownika → tier → pozycja → sygnał techniczny.
    Każda decyzja zawiera: winning_priority, goal_assessment, blocked_actions.
    """
    try:
        from backend.runtime_settings import build_symbol_tier_map, get_runtime_config

        rs = get_runtime_config(db)
        symbol_tiers = rs.get("symbol_tiers") or {}
        tier_map = build_symbol_tier_map(symbol_tiers)

        symbols = _get_symbols_from_db_or_env(db, include_spot=False)
        if not symbols:
            return {"success": True, "decisions": [], "note": "Brak danych rynkowych"}

        positions_db = db.query(Position).filter(Position.mode == mode).all()
        positions_by_symbol = {p.symbol: p for p in positions_db}

        # Pobierz aktywne oczekiwania użytkownika
        expectations_rows = (
            db.query(UserExpectation)
            .filter(
                UserExpectation.mode == mode,
                UserExpectation.is_active == True,
            )
            .all()
        )
        user_expectations = [
            {
                "id": r.id,
                "symbol": r.symbol,
                "expectation_type": r.expectation_type,
                "target_value_eur": r.target_value_eur,
                "target_price": r.target_price,
                "target_profit_pct": r.target_profit_pct,
                "no_buy": bool(r.no_buy),
                "no_sell": bool(r.no_sell),
                "no_auto_exit": bool(r.no_auto_exit),
                "preferred_horizon": r.preferred_horizon,
                "profile_mode": r.profile_mode,
                "is_active": True,
            }
            for r in expectations_rows
        ]

        # Pobierz sygnały z DB (szybko) — fallback do live_analysis dla brakujących
        live = _load_signals_from_db_or_live(db, symbols)

        # Cache aktywnych pending orders per symbol
        active_pending_symbols = set()
        try:
            pending_rows = (
                db.query(PendingOrder.symbol)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.status.in_(_ACTIVE_PENDING_STATUSES),
                )
                .all()
            )
            for row in pending_rows:
                if row[0]:
                    active_pending_symbols.add(
                        row[0].strip().upper().replace("/", "").replace("-", "")
                    )
        except Exception:
            pass

        decisions = []
        for s in live:
            symbol = s["symbol"]
            scored = _score_opportunity(s, db)
            position = positions_by_symbol.get(symbol)
            sym_norm = symbol.strip().upper().replace("/", "").replace("-", "")
            tier_config = tier_map.get(sym_norm, {})

            decision = _final_action_resolver(
                symbol=symbol,
                signal=s,
                scored=scored,
                position=position,
                tier_config=tier_config,
                mode=mode,
                user_expectations=user_expectations,
            )

            # Nadpisz akcję na WEJŚCIE_AKTYWNE gdy istnieje aktywny pending order BUY
            if sym_norm in active_pending_symbols and decision["final_action"] in (
                "BUY",
                "KANDYDAT_DO_WEJŚCIA",
            ):
                decision["final_action"] = "WEJŚCIE_AKTYWNE"
                decision["final_action_pl"] = _ACTION_PL.get(
                    "WEJŚCIE_AKTYWNE", "WEJŚCIE AKTYWNE"
                )
                decision["final_reason"] = "Zlecenie wejścia w trakcie realizacji"

            decisions.append(decision)

        priority_order = {
            "SELL_AT_TARGET": 0,
            "PREPARE_EXIT": 1,
            "HOLD_TARGET": 2,
            "DO_NOT_ADD": 3,
            "KANDYDAT_DO_WEJŚCIA": 3,
            "BUY": 4,
            "SELL": 5,
            "PARTIAL_EXIT": 5,
            "WAIT": 6,
            "HOLD": 7,
        }
        decisions.sort(
            key=lambda x: (
                priority_order.get(x["final_action"], 9),
                -(x["symbol_analysis"].get("score") or 0),
            )
        )

        summary = {
            "sell_at_target": sum(
                1 for d in decisions if d["final_action"] == "SELL_AT_TARGET"
            ),
            "prepare_exit": sum(
                1 for d in decisions if d["final_action"] == "PREPARE_EXIT"
            ),
            "hold_target": sum(
                1 for d in decisions if d["final_action"] == "HOLD_TARGET"
            ),
            "buy_ready": sum(1 for d in decisions if d["final_action"] == "BUY"),
            "consider_buy": sum(
                1 for d in decisions if d["final_action"] == "KANDYDAT_DO_WEJŚCIA"
            ),
            "sell_ready": sum(
                1 for d in decisions if d["final_action"] in ("SELL", "PARTIAL_EXIT")
            ),
            "blocked": sum(
                1
                for d in decisions
                if d["final_action"] in ("DO_NOT_ADD", "WAIT", "WAIT_FOR_SIGNAL")
            ),
            "hold": sum(1 for d in decisions if d["final_action"] == "HOLD"),
        }

        return {
            "success": True,
            "mode": mode,
            "decisions": decisions,
            "summary": summary,
            "total": len(decisions),
            "active_expectations": len(user_expectations),
            "updated_at": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd final-decisions: {str(e)}")


# ---------------------------------------------------------------------------
# Endpoint diagnostyczny: dlaczego bot demo nie wszedł w pozycję?
# ---------------------------------------------------------------------------

_REASON_PL = {
    "all_gates_passed": "✅ Wszystkie filtry OK — zlecenie złożone",
    "pending_confirmed_execution": "✅ Zlecenie wykonane",
    "signal_confidence_too_low": "❌ Pewność sygnału poniżej progu",
    "signal_too_old": "⏳ Sygnał zbyt stary",
    "signal_filters_not_met": "❌ Filtry techniczne (EMA/RSI/zakres) niezaliczone",
    "active_pending_exists": "⏳ Mamy otwarte zlecenie dla tego symbolu",
    "buy_blocked_existing_position": "⏳ Już mamy otwartą pozycję BUY",
    "buy_rejected_inferior_to_open_positions": "⏳ Kandydat słabszy od obecnych pozycji",
    "buy_replaced_worst_position": "🔄 Rotacja: zastąpiono najsłabszą pozycję",
    "buy_deferred_insufficient_rotation_edge": "⏳ Rotacja odroczona — przewaga netto za mała",
    "portfolio_rotation_triggered": "🔄 Uruchomiono rotację portfela",
    "sell_blocked_no_position": "❌ SELL bez otwartej pozycji — pomijamy",
    "symbol_not_in_any_tier": "❌ Symbol nie jest w żadnym tierze (watchliście AI)",
    "hold_mode_no_new_entries": "🔒 Symbol w trybie HOLD — nie otwieramy nowych",
    "symbol_cooldown_active": "⏳ Cooldown po ostatniej transakcji",
    "pending_cooldown_active": "⏳ Cooldown po ostatnim zleceniu",
    "insufficient_cash_or_qty_below_min": "❌ Za mało gotówki lub ilość poniżej minimum",
    "min_notional_guard": "❌ Wartość zlecenia poniżej minimalnej (Binance wymóg)",
    "cost_gate_failed": "❌ Koszty transakcji zbyt wysokie vs oczekiwany zysk",
    "tier_daily_trade_limit": "❌ Dzienny limit transakcji dla tego tieru osiągnięty",
    "daily_loss_brake_active": "🛑 Dzienny limit strat — bot wstrzymał handel",
    "risk_evaluation_failed": "❌ Ocena ryzyka negatywna",
    "sync_pending_db_commit": "⏳ Sync: oczekiwanie na commit DB",
    "sync_ignored_fee_asset_residual": "ℹ️ Sync: pominięto residual fee asset (BNB)",
    "sync_ignored_dust_residual": "ℹ️ Sync: pominięto dust residual",
    "sync_detected_real_mismatch": "⚠️ Sync: rzeczywista niezgodność Binance↔DB",
    "no_trace": "ℹ️ Brak decyzji w tym oknie — czeka na następny cykl collectora",
}


@router.get("/execution-trace")
def get_execution_trace(
    mode: str = Query("live", description="Tryb: demo lub live"),
    limit_minutes: int = Query(
        30, ge=1, le=1440, description="Okno czasowe w minutach"
    ),
    db: Session = Depends(get_db),
):
    """
    Diagnostyczny przegląd dlaczego bot nie otworzył pozycji dla każdego symbolu.
    Zwraca ostatnią decyzję per symbol z opisem w języku polskim.
    """
    try:
        since = utc_now_naive() - timedelta(minutes=limit_minutes)
        traces: list[DecisionTrace] = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode, DecisionTrace.timestamp >= since)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(500)
            .all()
        )

        # Najnowsza decyzja per symbol
        latest_per_symbol: dict[str, DecisionTrace] = {}
        for t in traces:
            if t.symbol and t.symbol not in latest_per_symbol:
                latest_per_symbol[t.symbol] = t

        # Dodaj symbole bez trace (brak danych lub brak sygnałów)
        symbols_in_db = _get_symbols_from_db_or_env(db)

        # Odczytaj aktualne sygnały i pozycje
        signals_map: dict[str, Signal] = {}
        for sig in db.query(Signal).order_by(desc(Signal.timestamp)).limit(200).all():
            if sig.symbol and sig.symbol not in signals_map:
                signals_map[sig.symbol] = sig

        positions_map: dict[str, Position] = {}
        for pos in (
            db.query(Position)
            .filter(Position.mode == mode, Position.exit_reason_code.is_(None))
            .all()
        ):
            if pos.symbol:
                positions_map[pos.symbol] = pos

        pending_map: dict[str, PendingOrder] = {}
        for po in (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == mode,
                PendingOrder.status.in_(_ACTIVE_PENDING_STATUSES),
            )
            .order_by(desc(PendingOrder.created_at))
            .all()
        ):
            if po.symbol and po.symbol not in pending_map:
                pending_map[po.symbol] = po

        result_symbols = sorted(set(list(latest_per_symbol.keys()) + symbols_in_db))
        rows = []
        for sym in result_symbols:
            trace = latest_per_symbol.get(sym)
            sig = signals_map.get(sym)
            pos = positions_map.get(sym)
            po = pending_map.get(sym)

            reason_code = trace.reason_code if trace else "no_trace"
            reason_pl = _REASON_PL.get(reason_code, f"Nieznany powód: {reason_code}")

            trace_age_s = None
            if trace and trace.timestamp:
                trace_age_s = int((utc_now_naive() - trace.timestamp).total_seconds())

            # Szczegóły z trace (JSON fields jeśli dostępne)
            sig_details: dict = {}
            if trace:
                # Mapowanie faktycznych nazw pól DB → klucze w odpowiedzi
                field_map = {
                    "signal_summary": "signal_summary",
                    "risk_gate_result": "risk_check",
                    "cost_gate_result": "cost_check",
                    "execution_gate_result": "execution_check",
                    "payload": "details",
                }
                for db_field, resp_key in field_map.items():
                    val = getattr(trace, db_field, None)
                    if val:
                        try:
                            sig_details[resp_key] = (
                                json.loads(val) if isinstance(val, str) else val
                            )
                        except Exception:
                            pass

            # Uzupełnij reason_pl o konkretne przyczyny filtra (filter_fails)
            if reason_code == "signal_filters_not_met":
                fails = (sig_details.get("details") or {}).get("filter_fails") or []
                if fails:
                    reason_pl = "❌ Filtry niezaliczone: " + "; ".join(fails)

            rows.append(
                {
                    "symbol": sym,
                    "reason_code": reason_code,
                    "reason_pl": reason_pl,
                    "reason_code_pl": reason_pl,
                    "timestamp": (
                        trace.timestamp.isoformat()
                        if trace and trace.timestamp
                        else None
                    ),
                    "action_type": trace.action_type if trace else None,
                    "strategy_name": trace.strategy_name if trace else None,
                    "timeframe": trace.timeframe if trace else None,
                    "signal_summary": (
                        json.dumps(
                            sig_details.get("signal_summary") or {}, ensure_ascii=False
                        )
                        if sig_details.get("signal_summary")
                        else None
                    ),
                    "risk_gate_result": (
                        json.dumps(
                            sig_details.get("risk_check") or {}, ensure_ascii=False
                        )
                        if sig_details.get("risk_check")
                        else None
                    ),
                    "cost_gate_result": (
                        json.dumps(
                            sig_details.get("cost_check") or {}, ensure_ascii=False
                        )
                        if sig_details.get("cost_check")
                        else None
                    ),
                    "trace_age_seconds": trace_age_s,
                    "has_position": pos is not None,
                    "has_pending": po is not None,
                    "pending_status": po.status if po else None,
                    "signal_type": sig.signal_type if sig else None,
                    "signal_confidence": (
                        round(float(sig.confidence), 3) if sig else None
                    ),
                    "signal_age_seconds": (
                        int((utc_now_naive() - sig.timestamp).total_seconds())
                        if sig and sig.timestamp
                        else None
                    ),
                    "details": sig_details,
                }
            )

        # Podsumowanie
        summary = {
            "executed": sum(
                1
                for r in rows
                if r["reason_code"]
                in ("all_gates_passed", "pending_confirmed_execution")
            ),
            "pending": sum(1 for r in rows if r["has_pending"]),
            "blocked": sum(
                1
                for r in rows
                if r["reason_code"]
                not in ("all_gates_passed", "pending_confirmed_execution", "no_trace")
            ),
            "no_signal": sum(1 for r in rows if r["signal_type"] is None),
        }

        # Sortuj: blokowane problemy najpierw
        priority = {
            "insufficient_cash_or_qty_below_min": 0,
            "signal_filters_not_met": 1,
            "signal_confidence_too_low": 2,
        }
        rows.sort(key=lambda r: (priority.get(r["reason_code"], 5), r["symbol"]))

        return {
            "success": True,
            "mode": mode,
            "window_minutes": limit_minutes,
            "data": rows,
            "symbols": rows,
            "summary": summary,
            "updated_at": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd execution-trace: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
def _build_rich_reason_pl(code: str, base_pl: str, detail: dict) -> str:
    """
    Buduje czytelny po polsku opis odrzucenia z konkretnych wartości.
    Każdy case ma swój wzorzec komunikatu.
    """
    try:
        if code == "ENTRY_BLOCKED_SIGNAL_FILTERS":
            sub = detail.get("reason", "")
            if sub == "signal_too_old":
                age_h = round(detail.get("age_seconds", 0) / 3600, 1)
                max_h = round(detail.get("max_age_seconds", 3600) / 3600, 1)
                return (
                    f"Sygnał zbyt stary ({age_h}h, max {max_h}h) — odśwież dane rynkowe"
                )
            if sub == "soft_buy_rsi_too_high":
                rsi = detail.get("rsi")
                limit = detail.get("rsi_soft_limit", 55)
                return f"RSI {rsi} > {limit} — za drogie na wejście (soft buy gate)"
            # fails list
            fails = detail.get("fails") or []
            regime = detail.get("regime", "")
            rsi = detail.get("rsi") or "?"
            rsi_gate = detail.get("rsi_buy_gate", 65)
            in_range = detail.get("in_range")
            parts = []
            if fails:
                parts.extend(fails)
            else:
                if not detail.get("rsi_ok"):
                    parts.append(f"RSI {rsi} > {rsi_gate} (gate)")
                if regime in ("TREND_DOWN", "CHAOS"):
                    parts.append(f"reżim rynku={regime}")
                if in_range is False:
                    parts.append("cena poza strefą BUY")
            if parts:
                return "Filtry techniczne: " + " | ".join(parts)
            return base_pl

        if code == "ENTRY_BLOCKED_SIGNAL_CONFIDENCE":
            conf = detail.get("confidence", "?")
            eff = detail.get("effective", "?")
            req = detail.get("required", "?")
            return f"Confidence {eff} < {req} (sygnał za słaby)"

        if code == "ENTRY_BLOCKED_SCORE":
            score = detail.get("score", "?")
            req = detail.get("required", "?")
            return f"Score {score} < {req} (za mała okazja)"

        if code == "ENTRY_BLOCKED_NO_CASH":
            cash = detail.get("free_cash_eur", "?")
            req = detail.get("min_notional_eur", "?")
            deficit = detail.get("deficit", "?")
            return f"Za mało gotówki: {cash} EUR (wymagane {req} EUR, brakuje {deficit} EUR)"

        if code == "ENTRY_BLOCKED_MAX_POSITIONS":
            open_n = detail.get("open", "?")
            mx = detail.get("max", "?")
            return f"Limit pozycji: {open_n}/{mx} otwartych"

        if code == "ENTRY_BLOCKED_COOLDOWN":
            remaining = detail.get("remaining_seconds", 0)
            rem_m = round(remaining / 60, 1)
            return f"Cooldown aktywny — jeszcze {rem_m} min"

        if code == "ENTRY_BLOCKED_ALREADY_HAS_POSITION":
            ep = detail.get("entry_price", "?")
            return f"Pozycja już otwarta (wejście @ {ep})"

        if code == "ENTRY_BLOCKED_KILL_SWITCH":
            return "Kill switch aktywny — wszystkie wejścia zablokowane"

        if code == "ENTRY_BLOCKED_ASSET_BIAS":
            last = detail.get("last_exit_reason", "?")
            blocked_until = detail.get("reentry_blocked_until", "?")
            return f"Cross-market bias: zamknięto z powodu '{last}' — zablokowane do {blocked_until}"

        if code == "ENTRY_BLOCKED_QUOTE_MODE_MISMATCH":
            sym_q = detail.get("symbol_quote", "?")
            mode_ = detail.get("active_mode", "?")
            return f"Symbol {sym_q} ≠ tryb {mode_} — zmień quote mode lub użyj właściwego symbolu"

        if code == "NO_SIGNAL":
            return "Brak sygnału BUY w bazie dla tego symbolu"

    except Exception:
        pass
    return base_pl


# ENTRY READINESS — gotowość systemu do wejścia
# ─────────────────────────────────────────────────────────────────────────────

_ENTRY_BLOCK_PL = {
    "ENTRY_BLOCKED_NO_CASH": "Brak wystarczającej gotówki",
    "ENTRY_BLOCKED_MIN_NOTIONAL": "Nominał poniżej minimum",
    "ENTRY_BLOCKED_COOLDOWN": "Symbol w cooldown (ostatnia transakcja zbyt niedawno)",
    "ENTRY_BLOCKED_MAX_POSITIONS": "Osiągnięto limit otwartych pozycji",
    "ENTRY_BLOCKED_SIGNAL_CONFIDENCE": "Za niska pewność sygnału",
    "ENTRY_BLOCKED_SCORE": "Za niski score okazji",
    "ENTRY_BLOCKED_WATCHLIST": "Symbol poza watchlistą",
    "ENTRY_BLOCKED_TIER_HOLD": "Tier HOLD — brak nowych wejść",
    "ENTRY_BLOCKED_KILL_SWITCH": "Kill switch aktywny",
    "ENTRY_BLOCKED_RISK_GATE": "Zablokowano przez bramę ryzyka",
    "ENTRY_BLOCKED_ALREADY_HAS_POSITION": "Pozycja już otwarta na tym symbolu",
    "ENTRY_BLOCKED_PENDING_EXISTS": "Oczekujące zlecenie już istnieje",
    "ENTRY_BLOCKED_SELL_NO_POSITION": "Sygnał SELL bez otwartej pozycji (spot — brak aktywa do sprzedaży)",
    "ENTRY_BLOCKED_NOT_IN_TIER": "Symbol poza tierami handlowymi (nie w żadnym aktywnym tierze)",
    "ENTRY_BLOCKED_SIGNAL_FILTERS": "Filtry techniczne nie spełnione (trend/RSI/zakres)",
    "ENTRY_BLOCKED_COST_GATE": "Bramka kosztowa — oczekiwany zysk za mały",
    "ENTRY_BLOCKED_ASSET_BIAS": "Blokada cross-market: to samo aktywo bazowe zostało właśnie zamknięte z powodu zmiany kierunku",
    "ENTRY_BLOCKED_QUOTE_MODE_MISMATCH": "Symbol nie pasuje do aktywnego trybu quote (EUR/USDC)",
    "ENTRY_BLOCKED_DATA_TOO_OLD": "Sygnał przeterminowany — dane sprzed ponad 90 minut (wymagana re-analiza)",
    "ENTRY_ALLOWED": "Wejście dozwolone",
    "NO_SIGNAL": "Brak sygnału dla symbolu",
}


@router.get("/buy-trace/{symbol}")
def get_buy_trace(
    symbol: str,
    mode: str = Query("live"),
    db: Session = Depends(get_db),
):
    """
    Pełny deterministyczny trace decyzji BUY dla konkretnego symbolu.
    Jeden endpoint — jeden finalny reason_code.

    Śledzi cały pipeline:
    signal → confidence → score → quote_mode → funding → risk_gate
    → price_range → regime → rsi_gate → soft_buy → final decision
    """
    from backend.accounting import compute_risk_snapshot
    from backend.database import BlogPost
    from backend.risk import detect_regime, estimate_trade_costs
    from backend.runtime_settings import get_runtime_config

    sym = symbol.strip().upper()
    config = get_runtime_config(db)
    now = utc_now_naive()

    result: dict = {
        "symbol": sym,
        "mode": mode,
        "checked_at": now.isoformat(),
        "pipeline": [],
        "final_decision": None,
        "final_reason_code": None,
        "final_reason_pl": None,
    }

    def _step(name: str, passed: bool, detail: dict | None = None) -> None:
        result["pipeline"].append(
            {
                "step": name,
                "passed": passed,
                **(detail or {}),
            }
        )

    def _reject(code: str, detail: dict | None = None) -> dict:
        result["final_decision"] = "REJECT"
        result["final_reason_code"] = code
        base_pl = _ENTRY_BLOCK_PL.get(code, code)
        # Zbuduj szczegółowy reason_pl z informacjami z detail
        enriched_pl = _build_rich_reason_pl(code, base_pl, detail or {})
        result["final_reason_pl"] = enriched_pl
        _step(code, False, detail)
        # Zawsze wrapped — spójny format z ALLOW
        return {"success": True, "data": result}

    # 1. Kill switch
    _risk_snap = compute_risk_snapshot(db, mode=mode)
    kill_switch_cfg = bool(config.get("kill_switch_enabled", True)) and bool(
        config.get("kill_switch_active", False)
    )
    kill_switch_dyn = bool(config.get("kill_switch_enabled", True)) and bool(
        _risk_snap.get("kill_switch_triggered", False)
    )
    if kill_switch_cfg or kill_switch_dyn:
        return _reject(
            "ENTRY_BLOCKED_KILL_SWITCH",
            {
                "kill_switch_config": kill_switch_cfg,
                "kill_switch_dynamic": kill_switch_dyn,
            },
        )
    _step("kill_switch", True)

    # 2. Asset-level bias — cross-market conflict guard
    # Jeśli to samo aktywo bazowe (np. BTC) zostało zamknięte z powodu trend reversal
    # na BTCEUR, to BTCUSDC nie może od razu wejść.
    try:
        from backend.quote_currency import get_base_asset
        from backend.risk import get_asset_bias

        _base = get_base_asset(sym) or sym[:-3]
        _asset_cooldown = int(float(config.get("asset_reentry_cooldown_minutes", 30)))
        _bias = get_asset_bias(
            db, _base, mode=mode, reentry_cooldown_minutes=_asset_cooldown, now=now
        )
        if _bias.get("conflict_detected"):
            return _reject(
                "ENTRY_BLOCKED_ASSET_BIAS",
                {
                    "base_asset": _base,
                    "last_exit_symbol": _bias.get("last_exit_symbol"),
                    "last_exit_reason": _bias.get("last_exit_reason"),
                    "last_exit_at": _bias.get("last_exit_at"),
                    "reentry_blocked_until": _bias.get("reentry_blocked_until"),
                    "explanation": _bias.get("explanation"),
                },
            )
        _step(
            "asset_bias",
            True,
            {
                "base_asset": _base,
                "asset_bias": _bias.get("asset_bias"),
                "reentry_allowed": _bias.get("reentry_allowed"),
            },
        )
    except Exception as _bias_err:
        _step("asset_bias", True, {"error": str(_bias_err), "skipped": True})

    # 3. Quote mode zgodność
    qcm = os.getenv("QUOTE_CURRENCY_MODE", "USDC").strip().upper()
    if qcm != "BOTH":
        if not sym.endswith(qcm):
            return _reject(
                "ENTRY_BLOCKED_QUOTE_MODE_MISMATCH",
                {
                    "symbol_quote": sym[-3:] if len(sym) > 3 else "?",
                    "active_mode": qcm,
                    "reason": f"Symbol {sym} nie pasuje do quote mode {qcm}",
                },
            )
    _step("quote_mode", True, {"qcm": qcm, "symbol": sym})

    # 3. Sygnał (Signal table)
    sig = (
        db.query(Signal)
        .filter(Signal.symbol == sym)
        .order_by(Signal.timestamp.desc())
        .first()
    )
    if not sig:
        return _reject("NO_SIGNAL", {"detail": "Brak sygnału w DB dla tego symbolu"})
    sig_age_s = (now - sig.timestamp).total_seconds() if sig.timestamp else 9999
    max_signal_age = float(config.get("max_signal_age_seconds", 3600))
    _step(
        "signal_exists",
        True,
        {
            "signal_type": sig.signal_type,
            "confidence": float(sig.confidence),
            "age_seconds": round(sig_age_s),
            "max_age_seconds": max_signal_age,
        },
    )

    if sig.signal_type == "SELL":
        pos = (
            db.query(Position)
            .filter(
                Position.symbol == sym,
                Position.mode == mode,
                Position.exit_reason_code.is_(None),
            )
            .first()
        )
        if not pos:
            return _reject("ENTRY_BLOCKED_SELL_NO_POSITION", {"signal_type": "SELL"})

    if sig.signal_type == "HOLD":
        return _reject("NO_SIGNAL", {"signal_type": "HOLD"})

    if sig_age_s > max_signal_age:
        return _reject(
            "ENTRY_BLOCKED_SIGNAL_FILTERS",
            {
                "reason": "signal_too_old",
                "age_seconds": round(sig_age_s),
                "max_age_seconds": max_signal_age,
            },
        )

    # 4. Confidence
    base_min_conf = float(config.get("min_signal_confidence", 0.55))
    buy_tol = float(config.get("buy_confidence_tolerance", 0.01))
    effective_conf = float(sig.confidence) + (
        buy_tol if sig.signal_type == "BUY" else 0.0
    )
    if effective_conf < base_min_conf:
        return _reject(
            "ENTRY_BLOCKED_SIGNAL_CONFIDENCE",
            {
                "confidence": float(sig.confidence),
                "tolerance": buy_tol,
                "effective": round(effective_conf, 3),
                "required": base_min_conf,
            },
        )
    _step(
        "confidence",
        True,
        {"confidence": float(sig.confidence), "required": base_min_conf},
    )

    # 5. Score
    try:
        ind = json.loads(sig.indicators) if sig.indicators else {}
    except Exception:
        ind = {}
    score_data = _score_opportunity(
        {
            "symbol": sym,
            "signal_type": sig.signal_type,
            "confidence": float(sig.confidence),
            "price": float(sig.price or 0),
            **ind,
        },
        db,
    )
    score = float(score_data.get("score", 0.0))
    min_score = float(config.get("demo_min_entry_score", 5.5))
    if score < min_score:
        return _reject("ENTRY_BLOCKED_SCORE", {"score": score, "required": min_score})
    _step("score", True, {"score": score, "required": min_score})

    # 6. Max positions
    max_open = int(config.get("max_open_positions", 3))
    open_count = (
        db.query(Position)
        .filter(Position.mode == mode, Position.exit_reason_code.is_(None))
        .count()
    )
    if open_count >= max_open:
        return _reject(
            "ENTRY_BLOCKED_MAX_POSITIONS", {"open": open_count, "max": max_open}
        )
    _step("max_positions", True, {"open": open_count, "max": max_open})

    # 7. Czy pozycja już otwarta
    existing_pos = (
        db.query(Position)
        .filter(
            Position.symbol == sym,
            Position.mode == mode,
            Position.exit_reason_code.is_(None),
        )
        .first()
    )
    if existing_pos:
        return _reject(
            "ENTRY_BLOCKED_ALREADY_HAS_POSITION",
            {"entry_price": float(existing_pos.entry_price or 0)},
        )
    _step("no_existing_position", True)

    # 8. Pending order conflict
    from backend.database import PendingOrder as PO

    pending_count = (
        db.query(PO)
        .filter(
            PO.mode == mode, PO.symbol == sym, PO.status.in_(_ACTIVE_PENDING_STATUSES)
        )
        .count()
    )
    if pending_count > 0:
        return _reject("ENTRY_BLOCKED_PENDING_EXISTS", {"pending_count": pending_count})
    _step("no_pending_conflict", True)

    # 9. Funding / USDC dostępne
    from backend.database import AccountSnapshot

    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FTE

        from backend.routers.portfolio import _build_live_spot_portfolio

        with ThreadPoolExecutor(max_workers=1) as _pool:
            _fut = _pool.submit(_build_live_spot_portfolio, db)
            try:
                _live = _fut.result(timeout=3.0)
                cash_eur = float(_live.get("free_cash_eur", 0.0))
            except FTE:
                cash_eur = 0.0
    except Exception:
        snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(AccountSnapshot.timestamp.desc())
            .first()
        )
        cash_eur = float(snap.free_margin or 0.0) if snap else 0.0

    min_notional = float(config.get("min_order_notional", 25.0))
    min_buy_eur = float(config.get("min_buy_eur", 60.0))
    required_eur = max(min_notional, min_buy_eur)
    if cash_eur < required_eur:
        return _reject(
            "ENTRY_BLOCKED_NO_CASH",
            {
                "free_cash_eur": round(cash_eur, 2),
                "min_notional_eur": required_eur,
                "min_buy_eur": min_buy_eur,
                "deficit": round(required_eur - cash_eur, 2),
            },
        )

    # Dodatkowa kontrola dla par USDC: wolne USDC musi pokrywać nominał
    # (EUR nie może być użyte bezpośrednio do kupna par XyzUSDC na Binance)
    _free_usdc = float(_live.get("free_usdc", 0.0)) if isinstance(_live, dict) else 0.0
    _free_eur_nat = (
        float(_live.get("free_eur", 0.0)) if isinstance(_live, dict) else 0.0
    )
    _allow_conv = os.getenv(
        "ALLOW_AUTO_CONVERT_EUR_TO_USDC", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    from backend.binance_client import get_binance_client

    eur_usdc_rate, eur_usdc_rate_source = resolve_eur_usdc_rate(get_binance_client())
    required_usdc = convert_eur_amount_to_quote(
        required_eur,
        "USDC",
        eur_usdc_rate=eur_usdc_rate,
    )
    if sym.endswith("USDC") and _free_usdc < required_usdc:
        if not _allow_conv:
            return _reject(
                "ENTRY_BLOCKED_NO_CASH",
                {
                    "free_cash_eur": round(cash_eur, 2),
                    "free_usdc": round(_free_usdc, 4),
                    "free_eur": round(_free_eur_nat, 2),
                    "min_notional_usdc": round(required_usdc, 4),
                    "required_eur": required_eur,
                    "eur_usdc_rate": round(eur_usdc_rate, 8),
                    "symbol_needs": "USDC",
                    "action_needed": "Włącz ALLOW_AUTO_CONVERT_EUR_TO_USDC lub przenieś USDC na konto",
                },
            )
        if _free_eur_nat < required_eur:
            return _reject(
                "ENTRY_BLOCKED_NO_CASH",
                {
                    "free_cash_eur": round(cash_eur, 2),
                    "free_usdc": round(_free_usdc, 4),
                    "free_eur": round(_free_eur_nat, 2),
                    "min_notional_usdc": round(required_usdc, 4),
                    "required_eur": required_eur,
                    "eur_usdc_rate": round(eur_usdc_rate, 8),
                    "deficit": round(required_eur - _free_eur_nat, 2),
                    "reason_code": "cash_insufficient_after_conversion_attempt",
                },
            )
        # Auto-konwersja włączona — wejście możliwe po konwersji, dodaj ostrzeżenie w krokach
        _step(
            "funding_usdc_conversion_needed",
            True,
            {
                "free_usdc": round(_free_usdc, 4),
                "free_eur": round(_free_eur_nat, 2),
                "min_notional_usdc": round(required_usdc, 4),
                "required_eur": required_eur,
                "eur_usdc_rate": round(eur_usdc_rate, 8),
                "eur_usdc_rate_source": eur_usdc_rate_source,
                "auto_convert_enabled": True,
                "note": "EUR→USDC konwersja nastąpi automatycznie przed pierwszym wejściem",
            },
        )
    else:
        _step(
            "funding",
            True,
            {
                "free_cash_eur": round(cash_eur, 2),
                "free_usdc": round(_free_usdc, 4),
                "min_notional_eur": min_notional,
            },
        )

    # 10. Price range gate (z najnowszego bloga AI)
    price = float(sig.price or 0.0)
    if price <= 0:
        md = (
            db.query(MarketData)
            .filter(MarketData.symbol == sym)
            .order_by(MarketData.timestamp.desc())
            .first()
        )
        price = float(md.price) if md else 0.0

    range_result = {
        "buy_low": None,
        "buy_high": None,
        "in_range": None,
        "price": round(price, 8),
    }
    try:
        blog = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
        if blog and blog.market_insights:
            bdata = json.loads(blog.market_insights)
            insights = (
                bdata.get("insights", bdata) if isinstance(bdata, dict) else bdata
            )
            for ins in insights if isinstance(insights, list) else []:
                if ins.get("symbol") == sym:
                    r = ins.get("range") or {}
                    bl = r.get("buy_low")
                    bh = r.get("buy_high")
                    price_tol = float(
                        config.get(
                            "buy_zone_tolerance_pct",
                            config.get("price_tolerance", 0.02),
                        )
                    )
                    if bl is not None and bh is not None:
                        in_range = (
                            (float(bl) * (1 - price_tol))
                            <= price
                            <= (float(bh) * (1 + price_tol))
                        )
                        range_result = {
                            "buy_low": bl,
                            "buy_high": bh,
                            "price": round(price, 8),
                            "in_range": in_range,
                            "distance_pct": (
                                round((price - float(bh)) / float(bh) * 100, 2)
                                if price > float(bh)
                                else 0.0
                            ),
                            "buy_action": r.get("buy_action"),
                            "comment": r.get("comment", "")[:120],
                        }
                    break
    except Exception:
        pass

    _step("price_range_check", range_result.get("in_range") is not False, range_result)
    in_range = range_result.get("in_range")

    # 11. Regime + RSI gate
    regime_result: dict = {}
    rsi_result: dict = {}
    try:
        from backend.analysis import get_regime_indicators

        ri = get_regime_indicators(db, sym)
        if ri:
            costs_base = estimate_trade_costs(config)
            from backend.risk import detect_regime as _dr

            regime_state = _dr(
                price=price,
                ema21_15m=ri.get("ema21_15m"),
                ema50_15m=ri.get("ema50_15m"),
                ema21_1h=ri.get("ema21_1h"),
                ema50_1h=ri.get("ema50_1h"),
                ema200_1h=ri.get("ema200_1h"),
                rsi_15m=ri.get("rsi_15m"),
                macd_hist_15m=ri.get("macd_hist_15m"),
                volume_ratio_15m=ri.get("volume_ratio_15m"),
            )
            regime = regime_state.regime
            rsi = ri.get("rsi_15m") or ri.get("rsi_1h")
            rsi_buy_gate = float(config.get("rsi_buy_gate", 65))
            rsi_ok = rsi is not None and float(rsi) <= rsi_buy_gate
            trend_up = regime == "TREND_UP"
            range_buyable = regime == "RANGE"
            regime_result = {
                "regime": regime,
                "regime_confidence": regime_state.confidence,
                "reasons": regime_state.reasons,
            }
            rsi_result = {
                "rsi": round(float(rsi), 1) if rsi else None,
                "rsi_buy_gate": rsi_buy_gate,
                "rsi_ok": rsi_ok,
            }

            if sig.signal_type == "BUY":
                can_soft = bool(config.get("demo_allow_soft_buy", True))
                if in_range and (trend_up or range_buyable) and rsi_ok:
                    _step(
                        "regime_rsi_range_gate",
                        True,
                        {
                            "path": "in_range + regime + rsi",
                            **regime_result,
                            **rsi_result,
                            "in_range": in_range,
                        },
                    )
                elif can_soft and trend_up and rsi_ok and not in_range:
                    rsi_val = float(rsi) if rsi else 50.0
                    if rsi_val < 55.0:
                        _step(
                            "regime_rsi_range_gate",
                            True,
                            {
                                "path": "soft_buy (trend+rsi, poza zakresem)",
                                **regime_result,
                                **rsi_result,
                                "in_range": in_range,
                            },
                        )
                    else:
                        return _reject(
                            "ENTRY_BLOCKED_SIGNAL_FILTERS",
                            {
                                "reason": "soft_buy_rsi_too_high",
                                "rsi": round(float(rsi), 1),
                                "rsi_soft_limit": 55.0,
                                "explanation": f"RSI {round(float(rsi),1)} > 55 — nie kupuj na overextension (soft buy)",
                                **regime_result,
                            },
                        )
                else:
                    fails = []
                    if not in_range:
                        fails.append(
                            f"cena {round(price,6)} poza strefą BUY [{range_result.get('buy_low')},{range_result.get('buy_high')}]"
                        )
                    if regime in ("TREND_DOWN", "CHAOS"):
                        fails.append(f"regime={regime} blokuje nowe longi")
                    if not rsi_ok:
                        fails.append(f"RSI {rsi_result.get('rsi')} > {rsi_buy_gate}")
                    return _reject(
                        "ENTRY_BLOCKED_SIGNAL_FILTERS",
                        {
                            "fails": fails,
                            "can_soft_buy": can_soft,
                            **regime_result,
                            **rsi_result,
                            "in_range": in_range,
                        },
                    )
    except Exception as e:
        _step("regime_rsi_range_gate", False, {"error": str(e)})

    # 12. Cooldown
    from backend.database import Order as Ord

    base_cooldown = int(
        float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60
    )
    last_ord = (
        db.query(Ord)
        .filter(Ord.symbol == sym, Ord.mode == mode)
        .order_by(Ord.timestamp.desc())
        .first()
    )
    if last_ord:
        elapsed = (now - last_ord.timestamp).total_seconds()
        if elapsed < base_cooldown:
            return _reject(
                "ENTRY_BLOCKED_COOLDOWN",
                {
                    "elapsed_seconds": round(elapsed),
                    "cooldown_seconds": base_cooldown,
                    "remaining_seconds": round(base_cooldown - elapsed),
                },
            )
    _step("cooldown", True)

    # PASS — wszystkie filtry przeszły
    result["final_decision"] = "ALLOW"
    result["final_reason_code"] = "ENTRY_ALLOWED"
    result["final_reason_pl"] = "Wejście dozwolone — wszystkie filtry przeszły"
    _step(
        "final_gate",
        True,
        {
            "message": "Kandydat gotowy do złożenia zlecenia BUY",
            "confidence": float(sig.confidence),
            "score": score,
            "price": round(price, 8),
        },
    )

    return {"success": True, "data": result}  # spójny format — zawsze wrapped


@router.get("/entry-readiness")
def get_entry_readiness(
    mode: str = Query("live"),
    db: Session = Depends(get_db),
):
    """
    Gotowość systemu do wejść w bieżącym cyklu DEMO.
    Dla każdego symbolu zwraca: czy wejście możliwe, a jeśli nie — dokładny powód blokady.
    Używane przez dashboard do wyświetlenia realnego stanu zamiast ogólnikowego 'CZEKAJ'.
    """
    try:
        from backend.accounting import compute_demo_account_state
        from backend.database import Order as Ord
        from backend.database import PendingOrder as PO
        from backend.database import RuntimeSetting
        from backend.runtime_settings import build_runtime_state, get_runtime_config

        runtime_ctx = build_runtime_state(db)
        config = get_runtime_config(db)

        # Sprawdź kill switch: zarówno config.kill_switch_active JAK I risk_snapshot.kill_switch_triggered
        # (collector używa risk_snapshot, więc entry-readiness musi też to sprawdzać)
        kill_switch_config = bool(config.get("kill_switch_enabled", True)) and bool(
            config.get("kill_switch_active", False)
        )
        from backend.accounting import compute_risk_snapshot

        _risk_snap = compute_risk_snapshot(db, mode=mode)
        kill_switch_dynamic = bool(config.get("kill_switch_enabled", True)) and bool(
            _risk_snap.get("kill_switch_triggered", False)
        )
        kill_switch = kill_switch_config or kill_switch_dynamic

        # Sprawdź konfigurację
        max_open_positions = int(config.get("max_open_positions", 3))
        min_order_notional = float(config.get("min_order_notional", 25.0))
        min_buy_eur = float(config.get("min_buy_eur", 60.0))
        required_cash_eur = max(min_order_notional, min_buy_eur)  # backward compat
        demo_min_conf = float(config.get("demo_min_signal_confidence", 0.55))
        demo_min_score = float(config.get("demo_min_entry_score", 5.5))
        pending_cooldown_s = int(config.get("pending_order_cooldown_seconds", 300))
        base_cooldown_s = int(
            float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60
        )

        # Pobierz account state (cash dostępne)
        from backend.accounting import get_demo_quote_ccy

        demo_quote_ccy = get_demo_quote_ccy()
        _er_free_usdc = 0.0  # USDC natywne — używane przez USDC-first cash gate
        if mode == "live":
            try:
                from concurrent.futures import ThreadPoolExecutor
                from concurrent.futures import TimeoutError as FuturesTimeoutError

                from backend.routers.portfolio import _build_live_spot_portfolio

                with ThreadPoolExecutor(max_workers=1) as _pool:
                    _fut = _pool.submit(_build_live_spot_portfolio, db)
                    try:
                        _live_data = _fut.result(timeout=3.0)
                    except FuturesTimeoutError:
                        _live_data = {"error": "timeout"}
                if _live_data.get("error"):
                    _snap = (
                        db.query(AccountSnapshot)
                        .filter(AccountSnapshot.mode == "live")
                        .order_by(AccountSnapshot.timestamp.desc())
                        .first()
                    )
                    cash = float(_snap.free_margin or 0.0) if _snap else 0.0
                    _er_free_usdc = 0.0
                else:
                    cash = float(_live_data.get("free_cash_eur", 0.0))
                    _er_free_usdc = float(_live_data.get("free_usdc", 0.0))
            except Exception:
                cash = 0.0
                _er_free_usdc = 0.0
        else:
            account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy)
            initial_balance = float(account_state.get("initial_balance") or 10000)
            cash = float(account_state.get("cash") or initial_balance)

        # Reserved cash (pending BUY orders)
        reserved_cash = 0.0
        active_pending = (
            db.query(PO)
            .filter(
                PO.mode == mode,
                PO.side == "BUY",
                PO.status.in_(
                    [
                        "PENDING_CREATED",
                        "PENDING",
                        "CONFIRMED",
                        "PENDING_CONFIRMED",
                        "EXCHANGE_SUBMITTED",
                        "PARTIALLY_FILLED",
                    ]
                ),
            )
            .all()
        )
        for p in active_pending:
            try:
                reserved_cash += float(p.price or 0.0) * float(p.quantity or 0.0)
            except Exception:
                pass
        available_cash = max(0.0, cash - reserved_cash)

        # Otwarte pozycje — open_symbols zawiera WSZYSTKIE holdingi (blokuje re-entry)
        open_positions = (
            db.query(Position)
            .filter(Position.mode == mode, Position.exit_reason_code.is_(None))
            .all()
        )
        open_symbols = {p.symbol for p in open_positions}
        # Dla live: dodaj symbole z Binance spot TYLKO jeśli wartość >= min_order_notional
        # (pył < min_notional nie blokuje nowych wejść — nie można z niego wyjść i tak)
        if mode == "live":
            try:
                from concurrent.futures import ThreadPoolExecutor
                from concurrent.futures import TimeoutError as FuturesTimeoutError

                from backend.routers.positions import _get_live_spot_positions

                with ThreadPoolExecutor(max_workers=1) as _pool:
                    _fut = _pool.submit(_get_live_spot_positions, db)
                    try:
                        for sp in _fut.result(timeout=3.0):
                            pos_value = float(sp.get("value_eur") or 0.0)
                            if pos_value >= min_order_notional:
                                open_symbols.add(sp["symbol"])
                    except FuturesTimeoutError:
                        pass
            except Exception:
                pass

        # open_count — otwarte pozycje z DB (Position records), oba tryby spójnie
        if mode == "live":
            open_count = (
                db.query(Position)
                .filter(Position.mode == "live", Position.exit_reason_code.is_(None))
                .count()
            )
        else:
            open_count = len(open_positions)

        now = utc_now_naive()

        # Tier map — te same reguły co w collectorze
        from backend.runtime_settings import build_symbol_tier_map as _build_tier_map

        # symbol_tiers jest na top-levelu runtime_ctx (nie w "config" który jest pusty)
        tier_map = _build_tier_map(runtime_ctx.get("symbol_tiers") or {})

        # Sygnały z DB — spójne z tym co widzi collector (nie live re-analiza)
        symbols = _get_symbols_from_db_or_env(db, include_spot=False)
        db_sigs = (
            db.query(Signal)
            .filter(Signal.symbol.in_(symbols))
            .order_by(desc(Signal.timestamp))
            .all()
        )
        # Wybierz jeden (najnowszy) sygnał na symbol
        signal_map: dict = {}
        for sig in db_sigs:
            if sig.symbol not in signal_map:
                try:
                    ind = json.loads(sig.indicators) if sig.indicators else {}
                except Exception:
                    ind = {}
                signal_map[sig.symbol] = {
                    "symbol": sig.symbol,
                    "signal_type": sig.signal_type,
                    "confidence": float(sig.confidence or 0.0),
                    "price": float(sig.price or 0.0),
                    "ema_20": ind.get("ema_20"),
                    "ema_50": ind.get("ema_50"),
                    "rsi_14": ind.get("rsi_14"),
                    "atr_14": ind.get("atr_14"),
                    "signal_timestamp": sig.timestamp,
                }

        candidates = []
        blocked = []

        for sym in symbols:
            sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
            if mode == "live" and is_test_symbol(sym_norm):
                continue
            # Filtr quote-ccy tylko dla DEMO; dla LIVE: symbols są już pre-filtrowane
            # przez _get_symbols_from_db_or_env (filter_symbols_by_quote_mode).
            if mode != "live" and not sym_norm.endswith(demo_quote_ccy):
                continue

            sig = signal_map.get(sym, {})
            confidence = float(sig.get("confidence", 0.0))
            signal_type = sig.get("signal_type", "HOLD")
            score_data = _score_opportunity(sig, db) if sig else {}
            score = float(score_data.get("score", 0.0))
            price = sig.get("price") or float(
                (
                    db.query(MarketData)
                    .filter(MarketData.symbol == sym)
                    .order_by(MarketData.timestamp.desc())
                    .first()
                    or type("x", (), {"price": None})()
                ).price
                or 0
            )

            entry_reason = "NO_SIGNAL"
            entry_reason_pl = _ENTRY_BLOCK_PL["NO_SIGNAL"]
            allowed = False

            # ── USDC-first cash gate (prekalkulowane per symbol) ─────────
            # LIVE + para USDC: wymagane USDC, funding fallback EUR
            # Demo / para EUR: klasyczny gate w EUR
            _er_cash_blocked = False
            if mode == "live" and sym_norm.endswith("USDC"):
                try:
                    from backend.quote_currency import resolve_eur_usdc_rate as _rer
                    from backend.quote_currency import (
                        resolve_required_quote_usdc as _rrq,
                    )

                    _er_req_usdc, _ = _rrq(
                        min_buy_eur, exchange_min_notional=min_order_notional
                    )
                    _er_rate, _ = _rer()
                    _er_total_usdc = _er_free_usdc + available_cash * max(
                        _er_rate, 1e-9
                    )
                    _er_cash_blocked = _er_total_usdc < _er_req_usdc
                except Exception:
                    _er_cash_blocked = available_cash < required_cash_eur
            else:
                _er_cash_blocked = available_cash < required_cash_eur

            # Sprawdź stałość sygnału — stary sygnał nie powinien blokować wejść
            _max_signal_age_min = int(os.getenv("MAX_SIGNAL_AGE_MINUTES", "90"))
            _sig_ts = sig.get("signal_timestamp")
            _signal_is_stale = False
            if _sig_ts is not None:
                try:
                    _sig_ts_naive = (
                        _sig_ts
                        if isinstance(_sig_ts, datetime)
                        else datetime.fromisoformat(str(_sig_ts))
                    )
                    if _sig_ts_naive.tzinfo is not None:
                        _sig_ts_naive = _sig_ts_naive.replace(tzinfo=None)
                    _sig_age_s = (now - _sig_ts_naive).total_seconds()
                    if _sig_age_s > _max_signal_age_min * 60:
                        _signal_is_stale = True
                except Exception:
                    pass

            if kill_switch:
                entry_reason = "ENTRY_BLOCKED_KILL_SWITCH"
            elif _signal_is_stale:
                # Sygnał przeterminowany — nie można oceniać jako SELL/BUY, traktuj jako brak danych
                entry_reason = "ENTRY_BLOCKED_DATA_TOO_OLD"
            elif signal_type == "HOLD":
                entry_reason = "NO_SIGNAL"
            elif tier_map and sym_norm not in tier_map:
                entry_reason = "ENTRY_BLOCKED_NOT_IN_TIER"
            elif open_count >= max_open_positions:
                entry_reason = "ENTRY_BLOCKED_MAX_POSITIONS"
            elif sym in open_symbols:
                entry_reason = "ENTRY_BLOCKED_ALREADY_HAS_POSITION"
            elif signal_type == "SELL":
                entry_reason = "ENTRY_BLOCKED_SELL_NO_POSITION"
            elif (
                db.query(PO)
                .filter(
                    PO.mode == mode,
                    PO.symbol == sym,
                    PO.status.in_(
                        [
                            "PENDING_CREATED",
                            "PENDING",
                            "CONFIRMED",
                            "PENDING_CONFIRMED",
                            "EXCHANGE_SUBMITTED",
                            "PARTIALLY_FILLED",
                        ]
                    ),
                )
                .count()
                > 0
            ):
                entry_reason = "ENTRY_BLOCKED_PENDING_EXISTS"
            elif confidence < demo_min_conf:
                entry_reason = "ENTRY_BLOCKED_SIGNAL_CONFIDENCE"
            elif score < demo_min_score:
                entry_reason = "ENTRY_BLOCKED_SCORE"
            elif _er_cash_blocked:
                entry_reason = "ENTRY_BLOCKED_NO_CASH"
            else:
                # Cross-market conflict guard: asset-level bias
                _asset_blocked = False
                try:
                    from backend.quote_currency import get_base_asset as _gba
                    from backend.risk import get_asset_bias as _gab

                    _base = _gba(sym) or sym[:-3]
                    _cooldown_min = int(
                        float(config.get("asset_reentry_cooldown_minutes", 30))
                    )
                    _bias = _gab(
                        db,
                        _base,
                        mode=mode,
                        reentry_cooldown_minutes=_cooldown_min,
                        now=now,
                    )
                    if _bias.get("conflict_detected"):
                        entry_reason = "ENTRY_BLOCKED_ASSET_BIAS"
                        _asset_blocked = True
                except Exception:
                    pass

                if not _asset_blocked:
                    # Sprawdź cooldown ostatniego zlecenia
                    last_ord = (
                        db.query(Ord)
                        .filter(Ord.symbol == sym, Ord.mode == mode)
                        .order_by(Ord.timestamp.desc())
                        .first()
                    )
                    in_cooldown = (
                        last_ord
                        and (now - last_ord.timestamp).total_seconds() < base_cooldown_s
                    )
                    # Sprawdź cooldown pending
                    last_pend = (
                        db.query(PO)
                        .filter(PO.mode == mode, PO.symbol == sym)
                        .order_by(PO.created_at.desc())
                        .first()
                    )
                    in_pending_cooldown = (
                        last_pend
                        and last_pend.created_at
                        and (now - last_pend.created_at).total_seconds()
                        < pending_cooldown_s
                    )

                    if in_cooldown:
                        entry_reason = "ENTRY_BLOCKED_COOLDOWN"
                    elif in_pending_cooldown:
                        entry_reason = "ENTRY_BLOCKED_COOLDOWN"
                    else:
                        entry_reason = "ENTRY_ALLOWED"
                        allowed = True

            entry_reason_pl = _ENTRY_BLOCK_PL.get(entry_reason, entry_reason)

            item = {
                "symbol": sym,
                "allowed": allowed,
                "entry_reason": entry_reason,
                "entry_reason_pl": entry_reason_pl,
                "confidence": round(confidence, 3),
                "score": round(score, 2),
                "signal_type": signal_type,
                "price": price,
            }
            if allowed:
                candidates.append(item)
            else:
                blocked.append(item)

        # Sortuj kandydatów po score desc
        candidates.sort(key=lambda x: -x["score"])
        blocked.sort(key=lambda x: -x["score"])

        best_ready = candidates[0] if candidates else None
        best_blocked = blocked[0] if blocked else None

        can_enter_now = (
            len(candidates) > 0
            and open_count < max_open_positions
            # can_enter_now: candidates zawierają tylko te, które przeszły _er_cash_blocked
            # więc wystarczy sprawdzić że mamy kandydatów
        )

        if can_enter_now:
            status_pl = (
                f"WEJŚCIE MOŻLIWE TERAZ: {best_ready['symbol']}"
                if best_ready
                else "WEJŚCIE MOŻLIWE"
            )
        elif candidates:
            status_pl = (
                f"OKAZJE SĄ, ALE ZABLOKOWANE: {best_blocked['entry_reason_pl']}"
                if best_blocked
                else "OKAZJE ZABLOKOWANE"
            )
        elif blocked:
            # Tylko zablokowane (np. same SELL bez pozycji) — nie ma aktywnych okazji BUY
            top_reason_pl = best_blocked["entry_reason_pl"] if best_blocked else "brak"
            status_pl = f"BRAK OKAZJI: {top_reason_pl}"
        else:
            status_pl = "BRAK SENSOWNYCH OKAZJI"

        return {
            "success": True,
            "mode": mode,
            "can_enter_now": can_enter_now,
            "ready_count": len(candidates),
            "blocked_count": len(blocked),
            "open_positions": len(open_positions),
            "max_open_positions": max_open_positions,
            "cash_available_eur": round(available_cash, 2),
            "cash_available": round(available_cash, 2),  # backward compat
            "free_usdc": round(_er_free_usdc, 4),
            "min_notional": min_order_notional,
            "min_buy_reference_eur": min_buy_eur,
            "min_buy_eur": min_buy_eur,  # backward compat
            "required_cash_eur": required_cash_eur,  # backward compat
            "kill_switch_active": kill_switch,
            "best_ready_symbol": best_ready["symbol"] if best_ready else None,
            "best_ready_score": best_ready["score"] if best_ready else None,
            "best_blocked_symbol": best_blocked["symbol"] if best_blocked else None,
            "best_blocked_reason": (
                best_blocked["entry_reason"] if best_blocked else None
            ),
            "best_blocked_reason_pl": (
                best_blocked["entry_reason_pl"] if best_blocked else None
            ),
            "status_pl": status_pl,
            "candidates": candidates[:5],
            "blocked": blocked[:10],
            "updated_at": now.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd entry-readiness: {str(e)}")


@router.get("/full-trace/{symbol}")
def get_full_execution_trace(
    symbol: str,
    mode: str = Query("live"),
    db: Session = Depends(get_db),
):
    """
    Pełna ścieżka wykonania (signal → readiness → buy-trace → collector → pending → order → Binance).
    Odpowiada na pytanie: 'Dlaczego bot nic nie zrobił mimo sygnału?'
    """
    sym = symbol.strip().upper()
    now = utc_now_naive()
    out: dict = {
        "symbol": sym,
        "mode": mode,
        "checked_at": now.isoformat(),
        "layers": {},
        "final_execution_state": None,
        "final_reason": None,
    }

    # 1. Signal layer
    sig = (
        db.query(Signal)
        .filter(Signal.symbol == sym)
        .order_by(Signal.timestamp.desc())
        .first()
    )
    if sig:
        sig_age = (now - sig.timestamp).total_seconds() if sig.timestamp else None
        out["layers"]["signal"] = {
            "exists": True,
            "signal_type": sig.signal_type,
            "confidence": float(sig.confidence or 0),
            "price": float(sig.price or 0),
            "age_seconds": round(sig_age) if sig_age is not None else None,
            "timestamp": sig.timestamp.isoformat() if sig.timestamp else None,
        }
    else:
        out["layers"]["signal"] = {"exists": False}

    # 2. buy-trace (decision pipeline)
    try:
        from fastapi.testclient import TestClient

        from backend.app import app as _app

        _client = TestClient(_app, raise_server_exceptions=False)
        _resp = _client.get(f"/api/signals/buy-trace/{sym}", params={"mode": mode})
        if _resp.status_code == 200:
            _bt = _resp.json()
            out["layers"]["buy_trace"] = _bt.get("data") or _bt
        else:
            out["layers"]["buy_trace"] = {"error": f"HTTP {_resp.status_code}"}
    except Exception as _bt_err:
        out["layers"]["buy_trace"] = {"error": str(_bt_err)}

    # 3. Collector — ostatnia aktywność (MarketData + Position)
    md = (
        db.query(MarketData)
        .filter(MarketData.symbol == sym)
        .order_by(MarketData.timestamp.desc())
        .first()
    )
    out["layers"]["collector_market_data"] = {
        "exists": md is not None,
        "price": float(md.price) if md else None,
        "timestamp": md.timestamp.isoformat() if md else None,
        "age_seconds": round((now - md.timestamp).total_seconds()) if md else None,
    }

    # 4. Open position
    open_pos = (
        db.query(Position)
        .filter(
            Position.symbol == sym,
            Position.mode == mode,
            Position.exit_reason_code.is_(None),
        )
        .first()
    )
    out["layers"]["open_position"] = {
        "exists": open_pos is not None,
        "entry_price": float(open_pos.entry_price or 0) if open_pos else None,
        "entry_reason": open_pos.entry_reason_code if open_pos else None,
        "opened_at": (
            open_pos.created_at.isoformat()
            if open_pos and open_pos.created_at
            else None
        ),
    }

    # 5. Pending orders
    from backend.database import PendingOrder as PO2

    pending_list = (
        db.query(PO2)
        .filter(
            PO2.symbol == sym,
            PO2.mode == mode,
            PO2.status.in_(
                [
                    "PENDING_CREATED",
                    "PENDING",
                    "CONFIRMED",
                    "PENDING_CONFIRMED",
                    "EXCHANGE_SUBMITTED",
                    "PARTIALLY_FILLED",
                ]
            ),
        )
        .order_by(PO2.created_at.desc())
        .all()
    )
    out["layers"]["pending_orders"] = {
        "count": len(pending_list),
        "items": [
            {
                "id": p.id,
                "side": p.side,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in pending_list[:3]
        ],
    }

    # 6. Last closed position
    last_closed = (
        db.query(Position)
        .filter(
            Position.symbol == sym,
            Position.mode == mode,
            Position.exit_reason_code.isnot(None),
        )
        .order_by(Position.updated_at.desc())
        .first()
    )
    out["layers"]["last_closed_position"] = {
        "exists": last_closed is not None,
        "exit_reason": last_closed.exit_reason_code if last_closed else None,
        "closed_at": (
            last_closed.updated_at.isoformat()
            if last_closed and last_closed.updated_at
            else None
        ),
        "pnl": (
            float(last_closed.net_pnl or last_closed.gross_pnl or 0)
            if last_closed
            else None
        ),
    }

    # 7. Last executed order (Order table)
    from backend.database import Order as Ord2

    last_order = (
        db.query(Ord2)
        .filter(Ord2.symbol == sym, Ord2.mode == mode)
        .order_by(Ord2.timestamp.desc())
        .first()
    )
    out["layers"]["last_order"] = {
        "exists": last_order is not None,
        "side": last_order.side if last_order else None,
        "status": last_order.status if last_order else None,
        "quantity": float(last_order.quantity or 0) if last_order else None,
        "price": float(last_order.price or 0) if last_order else None,
        "timestamp": last_order.timestamp.isoformat() if last_order else None,
        "binance_order_id": (
            getattr(last_order, "binance_order_id", None) if last_order else None
        ),
    }

    # 8. Asset bias
    try:
        from backend.quote_currency import get_base_asset as _gba2
        from backend.risk import get_asset_bias as _gab2
        from backend.runtime_settings import get_runtime_config as _grc2

        _cfg2 = _grc2(db)
        _b2 = _gba2(sym) or sym[:-3]
        _cm2 = int(float(_cfg2.get("asset_reentry_cooldown_minutes", 30)))
        out["layers"]["asset_bias"] = _gab2(
            db, _b2, mode=mode, reentry_cooldown_minutes=_cm2, now=now
        )
    except Exception as _abe:
        out["layers"]["asset_bias"] = {"error": str(_abe)}

    # Finalny status
    bt = out["layers"].get("buy_trace") or {}
    if isinstance(bt, dict):
        final_decision = bt.get("final_decision")
        final_code = bt.get("final_reason_code")
        final_pl = bt.get("final_reason_pl")
    else:
        final_decision = final_code = final_pl = None

    if open_pos:
        out["final_execution_state"] = "POSITION_OPEN"
        out["final_reason"] = "Pozycja już otwarta"
    elif pending_list:
        out["final_execution_state"] = "PENDING_ORDER_WAITING"
        out["final_reason"] = "Zlecenie oczekuje na realizację"
    elif final_decision == "ALLOW":
        out["final_execution_state"] = "READY_TO_ENTER"
        out["final_reason"] = (
            "Wszystkie filtry przeszły — collector powinien złożyć zlecenie w następnym cyklu"
        )
    elif final_code:
        out["final_execution_state"] = "BLOCKED"
        out["final_reason"] = f"{final_code}: {final_pl}"
    elif not sig:
        out["final_execution_state"] = "NO_SIGNAL"
        out["final_reason"] = "Brak sygnału dla symbolu"
    else:
        out["final_execution_state"] = "UNKNOWN"
        out["final_reason"] = "Nie można określić stanu — sprawdź warstwy ręcznie"

    return {"success": True, "data": out}


# ─────────────────────────────────────────────────────────────────────────────
# KANONICZNY MODEL DECYZJI — SymbolDecisionViewModel
# Jeden endpoint, jeden spójny model, zero sprzeczności w UI
# ─────────────────────────────────────────────────────────────────────────────


def _validate_decision_view_model(
    final_signal: str,
    primary_cta: str,
    prediction_available: bool,
    final_confidence: Optional[float],
    target_evaluation_available: bool,
    target: Optional[dict],
    ai_available: bool,
    recommended_action_label: str,
) -> list[str]:
    """
    Wykrywa sprzeczności w modelu decyzji.
    Zwraca listę opisów błędów (puste = OK).
    """
    issues: list[str] = []
    sell_wait_signals = {"SELL", "WAIT", "NO_TRADE", "HOLD"}

    if final_signal in sell_wait_signals and primary_cta == "BUY":
        issues.append(
            f"CRITICAL: final_signal={final_signal} ale primary_cta=BUY — sprzeczny CTA"
        )

    if not prediction_available and final_confidence is not None and not ai_available:
        issues.append(
            "prediction_available=False i ai_available=False, ale final_confidence ustawione"
        )

    if not target_evaluation_available and target is not None:
        score = (target or {}).get("score")
        if score is not None:
            issues.append(
                f"target_evaluation_available=False ale target.score={score} — nie wolno pokazywać"
            )

    if final_signal == "SELL" and "KUP" in recommended_action_label.upper():
        issues.append(
            f"CRITICAL: final_signal=SELL ale recommended_action_label={recommended_action_label!r}"
        )

    if (
        final_signal in ("WAIT", "NO_TRADE")
        and "KUP" in recommended_action_label.upper()
    ):
        issues.append(
            f"final_signal={final_signal} ale recommended_action_label={recommended_action_label!r}"
        )

    return issues


@router.get("/{symbol}/decision-view")
def get_symbol_decision_view(
    symbol: str,
    mode: str = Query("live", description="Tryb: live lub demo"),
    db: Session = Depends(get_db),
):
    """
    Kanoniczny model decyzji dla symbolu.
    Wszystkie komponenty UI mają czytać WYŁĄCZNIE z tego modelu.
    Eliminuje sprzeczności między banerem, CTA, sekcją celu i prognozą.
    """
    import logging as _logging
    import uuid

    from backend.database import ForecastRecord
    from backend.runtime_settings import get_runtime_config

    _log = _logging.getLogger(__name__)

    snapshot_id = str(uuid.uuid4())[:8]
    generated_at = utc_now_naive().isoformat()

    # ── 1. Dane bazowe ──────────────────────────────────────────────────────
    signal = (
        db.query(Signal)
        .filter(Signal.symbol == symbol)
        .order_by(Signal.timestamp.desc())
        .first()
    )
    md = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol)
        .order_by(MarketData.timestamp.desc())
        .first()
    )
    position = (
        db.query(Position)
        .filter(
            Position.symbol == symbol,
            Position.mode == mode,
            Position.exit_reason_code.is_(None),
            Position.quantity > 0,
        )
        .first()
    )
    forecasts = (
        db.query(ForecastRecord)
        .filter(ForecastRecord.symbol == symbol)
        .order_by(ForecastRecord.forecast_ts.desc())
        .limit(6)
        .all()
    )
    last_trace = (
        db.query(DecisionTrace)
        .filter(DecisionTrace.symbol == symbol, DecisionTrace.mode == mode)
        .order_by(DecisionTrace.timestamp.desc())
        .first()
    )

    # ── 2. Jakość danych ────────────────────────────────────────────────────
    current_price: Optional[float] = float(md.price) if md else None
    data_age_s: Optional[int] = None
    data_quality = "missing"

    if md:
        age_s = (utc_now_naive() - md.timestamp).total_seconds()
        data_age_s = int(age_s)
        if age_s > 600:
            data_quality = "stale"
        elif age_s > 180:
            data_quality = "degraded"
        else:
            data_quality = "good"

    # ── 3. AI availability (mamy sygnał = AI/heurystyka działała) ──────────
    ai_available: bool = signal is not None

    # ── 4. Wskaźniki z sygnału ──────────────────────────────────────────────
    indicators_raw: dict = {}
    if signal and signal.indicators:
        try:
            indicators_raw = (
                json.loads(signal.indicators)
                if isinstance(signal.indicators, str)
                else (signal.indicators or {})
            )
        except Exception:
            pass

    rsi = indicators_raw.get("rsi_14")
    ema20 = indicators_raw.get("ema_20")
    ema50 = indicators_raw.get("ema_50")

    if ema20 is not None and ema50 is not None:
        trend = (
            "WZROSTOWY"
            if ema20 > ema50
            else ("SPADKOWY" if ema20 < ema50 else "BOCZNY")
        )
    else:
        trend = "BOCZNY"

    # ── 5. Horyzonty z ForecastRecord ───────────────────────────────────────
    horizons: dict = {}
    prediction_available = False
    for fc in forecasts:
        h = fc.horizon  # "1h", "4h", "24h"
        if h and h not in horizons:
            horizons[h] = {
                "direction": fc.direction,
                "projected_pct": fc.projected_pct,
                "forecast_price": fc.forecast_price,
            }
            prediction_available = True

    # ── 6. Finalna decyzja — sygnał jest autorytetem ────────────────────────
    cfg = get_runtime_config(db)
    min_conf = float(cfg.get("min_signal_confidence", 0.6))

    if not ai_available or data_quality == "missing":
        final_signal = "NO_TRADE"
        final_signal_reason = "Brak sygnału lub danych rynkowych"
        final_confidence = None
        blockers = ["Brak sygnału dla symbolu"]
    else:
        sig_type = signal.signal_type  # BUY / SELL / HOLD
        sig_conf = float(signal.confidence or 0)
        reason_from_trace = (last_trace.reason_code if last_trace else None) or ""
        is_blocked = bool(
            "BLOCKED" in reason_from_trace.upper()
            or reason_from_trace
            in {
                "signal_filters_not_met",
                "all_gates_not_met",
                "cooldown_active",
                "max_positions_reached",
                "insufficient_edge_after_costs",
                "ENTRY_BLOCKED_SELL_NO_POSITION",
            }
        )
        blockers = []

        if sig_type == "BUY":
            if sig_conf >= min_conf and not is_blocked:
                final_signal = "BUY"
                final_signal_reason = f"Sygnał kupna ({int(sig_conf * 100)}% pewność)"
            else:
                final_signal = "WAIT"
                reason_label = reason_from_trace or "próg pewności niespełniony"
                blockers = [f"Sygnał zablokowany: {reason_label}"]
                final_signal_reason = (
                    f"Sygnał kupna za słaby lub zablokowany: {reason_label}"
                )
        elif sig_type == "SELL":
            final_signal = "SELL"
            final_signal_reason = f"Sygnał sprzedaży ({int(sig_conf * 100)}% pewność)"
            if not position:
                final_signal = "WAIT"
                final_signal_reason = "Sygnał SELL — brak pozycji do zamknięcia (spot)"
                blockers = ["ENTRY_BLOCKED_SELL_NO_POSITION: brak pozycji"]
        else:
            final_signal = "HOLD"
            final_signal_reason = "Utrzymaj pozycję — brak nowego sygnału"

        final_confidence = sig_conf

    # ── 7. Data-quality degradation ─────────────────────────────────────────
    if data_quality == "stale":
        final_signal = "WAIT"
        final_signal_reason = f"Dane rynkowe stare ({data_age_s}s) — wstrzymano sygnał"
        blockers = blockers or [f"Dane stare: {data_age_s}s"]

    # ── 8. CTA i akcje ──────────────────────────────────────────────────────
    has_position = bool(position)

    if final_signal == "BUY" and not has_position:
        recommended_action_label = "KUP"
        primary_cta = "BUY"
        allowed_actions = ["BUY", "WATCH"]
    elif final_signal == "SELL" and has_position:
        recommended_action_label = "SPRZEDAJ"
        primary_cta = "SELL"
        allowed_actions = ["SELL", "PARTIAL_SELL"]
    elif final_signal == "HOLD" and has_position:
        recommended_action_label = "TRZYMAJ"
        primary_cta = "NONE"
        allowed_actions = ["SELL", "WATCH"]
    elif final_signal in ("WAIT", "NO_TRADE"):
        recommended_action_label = "CZEKAJ"
        primary_cta = "NONE"
        allowed_actions = ["WATCH"]
    else:
        recommended_action_label = "OBSERWUJ"
        primary_cta = "NONE"
        allowed_actions = ["WATCH"]

    # ── 9. Position data ─────────────────────────────────────────────────────
    position_data: Optional[dict] = None
    if position:
        position_data = {
            "entry_price": float(position.entry_price or 0),
            "quantity": float(position.quantity or 0),
            "unrealized_pnl": float(position.unrealized_pnl or 0),
            "pnl_pct": (
                round(
                    (
                        (float(current_price or 0) - float(position.entry_price or 0))
                        / float(position.entry_price or 1)
                    )
                    * 100,
                    2,
                )
                if current_price and position.entry_price
                else None
            ),
        }

    # ── 10. Ostrzeżenia ─────────────────────────────────────────────────────
    warnings_list: list[str] = []
    if data_quality == "stale":
        warnings_list.append(f"Dane rynkowe stare ({data_age_s}s) — sygnał wstrzymany")
    elif data_quality == "degraded":
        warnings_list.append(f"Dane częściowo stare ({data_age_s}s)")
    if not prediction_available:
        warnings_list.append("Brak prognoz AI dla symbolu")
    if not ai_available:
        warnings_list.append("Brak sygnału AI — brak danych do analizy")

    # ── 11. Walidacja spójności ──────────────────────────────────────────────
    target_evaluation_available = False
    target = None

    inconsistencies = _validate_decision_view_model(
        final_signal=final_signal,
        primary_cta=primary_cta,
        prediction_available=prediction_available,
        final_confidence=final_confidence,
        target_evaluation_available=target_evaluation_available,
        target=target,
        ai_available=ai_available,
        recommended_action_label=recommended_action_label,
    )

    if inconsistencies:
        for msg in inconsistencies:
            _log.error(f"[decision_view] symbol={symbol} INCONSISTENCY: {msg}")
        critical = any("CRITICAL" in m for m in inconsistencies)
        if critical:
            # Safe fallback — wymuś neutralny stan
            final_signal = "WAIT"
            primary_cta = "NONE"
            recommended_action_label = "CZEKAJ"
            allowed_actions = ["WATCH"]
            warnings_list.append(
                "Niespójne dane analizy — wyświetlano bezpieczny fallback"
            )
        _log.warning(
            f"[decision_view] symbol_decision_snapshot_rejected "
            f"symbol={symbol} snapshot_id={snapshot_id} issues={inconsistencies}"
        )
    else:
        _log.debug(
            f"[decision_view] symbol_decision_snapshot_validated "
            f"symbol={symbol} snapshot_id={snapshot_id} final_signal={final_signal}"
        )

    model = {
        "snapshot_id": snapshot_id,
        "generated_at": generated_at,
        "symbol": symbol,
        "mode": mode,
        "current_price": current_price,
        "data_quality": data_quality,
        "data_age_seconds": data_age_s,
        "ai_available": ai_available,
        "prediction_available": prediction_available,
        "target_evaluation_available": target_evaluation_available,
        "final_signal": final_signal,
        "final_signal_reason": final_signal_reason,
        "final_confidence": final_confidence,
        "has_position": has_position,
        "position": position_data,
        "horizons": horizons,
        "indicators": {
            "rsi": rsi,
            "ema20": ema20,
            "ema50": ema50,
            "trend": trend,
        },
        "target": target,
        "blockers": blockers,
        "recommended_action_label": recommended_action_label,
        "primary_cta": primary_cta,
        "allowed_actions": allowed_actions,
        "warnings": warnings_list,
        "inconsistencies_detected": len(inconsistencies) > 0,
    }

    _log.info(
        f"[decision_view] symbol_decision_snapshot_created "
        f"symbol={symbol} snapshot_id={snapshot_id} "
        f"final_signal={final_signal} primary_cta={primary_cta} "
        f"data_quality={data_quality}"
    )
    return {"success": True, "data": model}
