"""
Signals API Router - endpoints dla sygnałów AI
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List
from datetime import datetime, timedelta, timezone
import os
import json

from backend.database import get_db, Signal, MarketData, Kline, Position, UserExpectation, DecisionAudit, DecisionTrace, PendingOrder, utc_now_naive
from backend.analysis import persist_insights_as_signals

router = APIRouter()


def _build_live_signals(db: Session, symbols: List[str], limit: int = 20) -> List[dict]:
    """
    Wygeneruj sygnały oparte o prawdziwą analizę techniczną (RSI, EMA, MACD).
    Nie używa random ani OpenAI — czyste wskaźniki z historii klines.
    """
    from backend.analysis import get_live_context

    results = []
    for symbol in symbols:
        ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
        if not ctx:
            continue

        rsi = ctx.get("rsi")
        ema_20 = ctx.get("ema_20")
        ema_50 = ctx.get("ema_50")
        close = ctx.get("close")
        rsi_buy = ctx.get("rsi_buy", 35)
        rsi_sell = ctx.get("rsi_sell", 65)

        if not close or close <= 0:
            continue

        signal_type = "HOLD"
        confidence = 0.50
        reasons: list = []

        if rsi is not None:
            if rsi < rsi_buy:
                signal_type = "BUY"
                confidence += min(0.20, (rsi_buy - rsi) / rsi_buy * 0.25)
                reasons.append(f"RSI {rsi:.0f} — wyprzedanie")
            elif rsi > rsi_sell:
                signal_type = "SELL"
                confidence += min(0.20, (rsi - rsi_sell) / (100 - rsi_sell) * 0.25)
                reasons.append(f"RSI {rsi:.0f} — wykupienie")
            else:
                reasons.append(f"RSI {rsi:.0f} — neutralny")

        if ema_20 and ema_50:
            if ema_20 > ema_50:
                reasons.append("EMA20 > EMA50 — trend wzrostowy")
                if signal_type == "BUY":
                    confidence += 0.10
                elif signal_type == "HOLD":
                    signal_type = "BUY"
                    confidence += 0.05
            else:
                reasons.append("EMA20 < EMA50 — trend spadkowy")
                if signal_type == "SELL":
                    confidence += 0.10
                elif signal_type == "HOLD":
                    signal_type = "SELL"
                    confidence += 0.05

        confidence = round(max(0.45, min(confidence, 0.97)), 2)

        # Pobierz aktualną cenę z bazy (może być nowsza niż kline)
        md = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(desc(MarketData.timestamp))
            .first()
        )
        price = md.price if md else close

        results.append({
            "id": None,
            "symbol": symbol,
            "signal_type": signal_type,
            "confidence": confidence,
            "price": price,
            "indicators": {
                "rsi": round(rsi, 1) if rsi else None,
                "ema_20": round(ema_20, 6) if ema_20 else None,
                "ema_50": round(ema_50, 6) if ema_50 else None,
            },
            "reason": "; ".join(reasons) if reasons else "Brak wystarczających danych",
            "timestamp": utc_now_naive().isoformat(),
            "source": "live_analysis",
        })

    results.sort(key=lambda x: (-x["confidence"], x["signal_type"] == "HOLD"))
    return results[:limit]


def _get_symbols_from_db_or_env(db: Session, include_spot: bool = True) -> List[str]:
    """
    Buduje effective universe symboli do analizy.
    Priorytet:
    1. Watchlista użytkownika (runtime_settings)
    2. Symbole z MarketData (zbierane przez collector)
    3. ENV WATCHLIST (fallback)
    4. Symbole z Binance spot (realne aktywa użytkownika)
    Deduplikuje i zwraca unikalną listę.
    """
    seen: set[str] = set()
    result: List[str] = []

    def _add(sym: str) -> None:
        s = sym.strip().upper()
        if s and s not in seen:
            seen.add(s)
            result.append(s)

    # 1. Watchlist z runtime_settings
    try:
        from backend.runtime_settings import get_runtime_config
        rs = get_runtime_config(db)
        wl = rs.get("watchlist_override") or ""
        if isinstance(wl, str):
            for s in wl.split(","):
                _add(s)
        elif isinstance(wl, list):
            for s in wl:
                _add(str(s))
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
        for s in raw.split(","):
            _add(s)

    # 4. Symbole z Binance spot (żeby analizować to co użytkownik posiada)
    if include_spot:
        try:
            from backend.routers.positions import _get_live_spot_positions
            for sp in _get_live_spot_positions(db):
                _add(sp["symbol"])
        except Exception:
            pass

    return result


@router.get("/latest")
def get_latest_signals(
    limit: int = Query(10, ge=1, le=100, description="Liczba sygnałów"),
    signal_type: Optional[str] = Query(None, description="Filtr: BUY, SELL, HOLD"),
    db: Session = Depends(get_db),
):
    """
    Najnowsze sygnały — najpierw z bazy (zapisanych przez collector), potem live analiza.
    """
    try:
        # Sygnały z bazy (zapisane przez collector)
        query = db.query(Signal)
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
                result.append({
                    "id": sig.id,
                    "symbol": sig.symbol,
                    "signal_type": sig.signal_type,
                    "confidence": sig.confidence,
                    "price": sig.price,
                    "indicators": ind,
                    "reason": sig.reason,
                    "timestamp": sig.timestamp.isoformat(),
                    "source": "database",
                })
            return {"success": True, "data": result, "count": len(result)}

        # Fallback: live analiza — zapisz do DB żeby collector mógł korzystać
        symbols = _get_symbols_from_db_or_env(db)
        live = _build_live_signals(db, symbols, limit=limit)
        if live:
            persist_insights_as_signals(db, live)
        if signal_type:
            live = [s for s in live if s["signal_type"] == signal_type.upper()]
        return {"success": True, "data": live, "count": len(live), "source": "live_analysis"}

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
        raise HTTPException(status_code=500, detail=f"Error getting top10 signals: {str(e)}")


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
        filtered = [s for s in live if s["signal_type"] != "HOLD" and s["confidence"] > 0.55][:5]
        return {
            "success": True,
            "data": filtered,
            "count": len(filtered),
            "description": "Top 5 sygnałów BUY/SELL — live analiza",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting top5 signals: {str(e)}")


def _score_opportunity(signal: dict, db: Session) -> dict:
    """
    Oblicz score okazji tradingowej dla jednego sygnału.
    Zwraca wzbogacony słownik z polami: score, expected_profit_pct, risk_pct, score_breakdown.
    """
    from backend.analysis import get_live_context

    symbol = signal.get("symbol", "")
    signal_type = signal.get("signal_type", "HOLD")
    confidence = float(signal.get("confidence") or 0.5)
    ind = signal.get("indicators") or {}
    rsi = ind.get("rsi")
    ema_20 = ind.get("ema_20")
    ema_50 = ind.get("ema_50")
    price = float(signal.get("price") or 0)

    # Pobierz ATR z pełnego kontekstu
    ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
    atr = ctx.get("atr") if ctx else None

    # --- Scoring ---
    score = round(confidence * 10, 2)
    breakdown = [f"confidence {confidence:.2f} → {score:.1f}pkt"]

    # Trend alignment
    trend_up = (ema_20 and ema_50 and float(ema_20) > float(ema_50))
    if signal_type == "BUY" and trend_up:
        score += 1.5
        breakdown.append("+1.5 trend wzrostowy (EMA20>EMA50)")
    elif signal_type == "SELL" and not trend_up and ema_20 and ema_50:
        score += 1.5
        breakdown.append("+1.5 trend spadkowy (EMA20<EMA50)")
    elif signal_type == "BUY" and not trend_up and ema_20 and ema_50:
        score -= 1.0
        breakdown.append("-1.0 BUY pod prąd trendu")

    # RSI bonus
    if rsi is not None:
        rsi_f = float(rsi)
        if signal_type == "BUY" and rsi_f < 40:
            score += 1.5
            breakdown.append(f"+1.5 RSI {rsi_f:.0f} (wyprzedanie)")
        elif signal_type == "SELL" and rsi_f > 60:
            score += 1.5
            breakdown.append(f"+1.5 RSI {rsi_f:.0f} (wykupienie)")
        elif signal_type == "BUY" and rsi_f > 65:
            score -= 1.0
            breakdown.append(f"-1.0 RSI {rsi_f:.0f} (wykupienie przy BUY)")

    # ATR-based profit/risk estimation
    atr_stop_mult = float(os.getenv("ATR_STOP_MULT", "1.3"))
    atr_take_mult = float(os.getenv("ATR_TAKE_MULT", "2.2"))
    if atr and price and price > 0:
        expected_profit_pct = round((atr * atr_take_mult / price) * 100, 2)
        risk_pct = round((atr * atr_stop_mult / price) * 100, 2)
        if expected_profit_pct > 0 and risk_pct > 0:
            rr_ratio = expected_profit_pct / risk_pct
            if rr_ratio >= 1.5:
                score += 1.0
                breakdown.append(f"+1.0 R/R={rr_ratio:.1f} (korzystny)")
    else:
        expected_profit_pct = None
        risk_pct = None

    # HOLD penalty
    if signal_type == "HOLD":
        score -= 3.0
        breakdown.append("-3.0 sygnał HOLD")

    score = round(max(0.0, score), 2)

    result = dict(signal)
    result["score"] = score
    result["expected_profit_pct"] = expected_profit_pct
    result["risk_pct"] = risk_pct
    result["score_breakdown"] = breakdown
    return result


@router.get("/best-opportunity")
def get_best_opportunity(
    mode: str = Query("demo", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Najlepsza okazja tradingowa — iteruje kandydatów od najwyższego score
    i zwraca PIERWSZEGO, który przechodzi bramki wejścia.
    CZEKAJ tylko gdy ŻADEN kandydat nie przeszedł.
    """
    try:
        from backend.database import RuntimeSetting, PendingOrder as PO, Order as Ord
        from backend.accounting import compute_demo_account_state
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
        kill_switch = bool(config.get("kill_switch_enabled", True)) and bool(config.get("kill_switch_active", False))
        max_open_positions = int(config.get("max_open_positions", 3))
        min_order_notional = float(config.get("min_order_notional", 25.0))
        demo_min_conf = float(config.get("demo_min_signal_confidence", 0.55))
        base_cooldown_s = int(float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60)

        # Profil agresywności — dynamiczne progi
        from backend.runtime_settings import AGGRESSIVENESS_PROFILES
        aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
        aggr_profile = AGGRESSIVENESS_PROFILES.get(aggressiveness, AGGRESSIVENESS_PROFILES["balanced"])

        # Stan konta
        demo_quote_ccy = os.getenv("DEMO_QUOTE_CCY", "EUR")
        if mode == "demo":
            account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy)
            cash = float(account_state.get("cash") or 0.0)
        else:
            from backend.routers.portfolio import _build_live_spot_portfolio
            live_data = _build_live_spot_portfolio(db)
            cash = float(live_data.get("free_cash_eur", 0.0))

        open_positions = db.query(Position).filter(Position.mode == mode).all()
        open_count = len(open_positions)
        open_symbols = {p.symbol for p in open_positions}
        # Dla LIVE: dodaj symbole z Binance spot
        if mode == "live":
            from backend.routers.positions import _get_live_spot_positions
            for sp in _get_live_spot_positions(db):
                open_symbols.add(sp["symbol"])

        now = utc_now_naive()

        live = _build_live_signals(db, symbols, limit=len(symbols))
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

        MIN_SCORE = float(config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"]))
        MIN_CONFIDENCE = float(config.get("demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]))

        allowed_candidates = []
        blocked_candidates = []

        for cand in scored:
            sym = cand["symbol"]
            score = float(cand.get("score", 0))
            confidence = float(cand.get("confidence", 0))
            block_reason = None

            if kill_switch:
                block_reason = "Kill switch aktywny"
            elif score < MIN_SCORE:
                block_reason = f"Score {score:.1f} < {MIN_SCORE}"
            elif confidence < MIN_CONFIDENCE:
                block_reason = f"Pewność {confidence:.0%} < {MIN_CONFIDENCE:.0%}"
            elif open_count >= max_open_positions:
                block_reason = f"Osiągnięto limit {max_open_positions} pozycji"
            elif sym in open_symbols:
                block_reason = f"Pozycja już otwarta na {sym}"
            elif cash < min_order_notional:
                block_reason = f"Brak gotówki ({cash:.2f} < {min_order_notional})"
            else:
                # Cooldown
                last_ord = db.query(Ord).filter(
                    Ord.symbol == sym, Ord.mode == mode
                ).order_by(Ord.timestamp.desc()).first()
                if last_ord and (now - last_ord.timestamp).total_seconds() < base_cooldown_s:
                    block_reason = f"Cooldown (ostatnia transakcja {int((now - last_ord.timestamp).total_seconds())}s temu)"

            if block_reason:
                blocked_candidates.append({
                    "symbol": sym,
                    "action": cand["signal_type"],
                    "score": score,
                    "confidence": confidence,
                    "block_reason": block_reason,
                })
            else:
                allowed_candidates.append(cand)

        if not allowed_candidates:
            top_blocked = blocked_candidates[0] if blocked_candidates else None
            return {
                "success": True,
                "opportunity": None,
                "action": "CZEKAJ",
                "reason": (
                    f"Najlepszy kandydat ({top_blocked['symbol']} {top_blocked['action']}) "
                    f"zablokowany: {top_blocked['block_reason']}"
                ) if top_blocked else "Brak kandydatów powyżej progu",
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
            "runner_up": {
                "symbol": allowed_candidates[1]["symbol"],
                "action": allowed_candidates[1]["signal_type"],
                "score": allowed_candidates[1]["score"],
                "confidence": allowed_candidates[1]["confidence"],
            } if len(allowed_candidates) > 1 else None,
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
        from backend.runtime_settings import build_runtime_state, get_runtime_config, AGGRESSIVENESS_PROFILES
        runtime_ctx = build_runtime_state(db)
        config = runtime_ctx.get("config", {})
        aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
        aggr_profile = AGGRESSIVENESS_PROFILES.get(aggressiveness, AGGRESSIVENESS_PROFILES["balanced"])
        MIN_SCORE = float(config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"]))
        MIN_CONFIDENCE = float(config.get("demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]))

        symbols = _get_symbols_from_db_or_env(db)
        if not symbols:
            return {
                "success": True,
                "items": [],
                "note": "Brak danych rynkowych — kolektor nie zebrał jeszcze danych",
            }

        live = _build_live_signals(db, symbols, limit=len(symbols))

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

            # Oblicz brakujące warunki
            missing_conditions = []
            status = "WAIT"

            if signal_type == "HOLD":
                trend_up = ema_20 and ema_50 and float(ema_20) > float(ema_50)
                missing_conditions.append({
                    "condition": "Kierunek trendu",
                    "current": "Wzrostowy (EMA20>EMA50)" if trend_up else "Boczny/Spadkowy (EMA20<EMA50)",
                    "required": "Wyraźny kierunek BUY lub SELL",
                    "met": False,
                })
                status = "HOLD"
            else:
                # Sprawdź confidence
                if confidence < MIN_CONFIDENCE:
                    missing_conditions.append({
                        "condition": "Pewność sygnału",
                        "current": f"{confidence:.0%}",
                        "required": f"{MIN_CONFIDENCE:.0%}",
                        "met": False,
                    })

                # Sprawdź score
                if score < MIN_SCORE:
                    missing_conditions.append({
                        "condition": "Score okazji",
                        "current": f"{score:.1f}/10",
                        "required": f"{MIN_SCORE:.1f}/10",
                        "met": False,
                    })

                # Trend
                trend_up = ema_20 and ema_50 and float(ema_20) > float(ema_50)
                if signal_type == "BUY" and not trend_up and ema_20 and ema_50:
                    missing_conditions.append({
                        "condition": "Trend wzrostowy (EMA20>EMA50)",
                        "current": f"EMA20={float(ema_20):.4f} < EMA50={float(ema_50):.4f}",
                        "required": "EMA20 > EMA50",
                        "met": False,
                    })

                # RSI
                if rsi is not None:
                    rsi_f = float(rsi)
                    if signal_type == "BUY" and rsi_f > 65:
                        missing_conditions.append({
                            "condition": "RSI < 65 (nie wykupiony)",
                            "current": f"RSI={rsi_f:.0f}",
                            "required": "RSI < 65",
                            "met": False,
                        })
                    elif signal_type == "SELL" and rsi_f < 35:
                        missing_conditions.append({
                            "condition": "RSI > 35 (nie wyprzedany)",
                            "current": f"RSI={rsi_f:.0f}",
                            "required": "RSI > 35",
                            "met": False,
                        })

                # Jeśli nie brakuje warunków — okazja jest aktywna
                if not missing_conditions:
                    status = "READY"
                else:
                    status = "WAIT"

            # Typ akcji po polsku
            action_pl = {"BUY": "KUP", "SELL": "SPRZEDAJ", "HOLD": "TRZYMAJ"}.get(signal_type, signal_type)
            status_pl = {"READY": "Gotowy do wejścia", "WAIT": "Czeka na warunki", "HOLD": "W trzymaniu"}.get(status, status)

            items.append({
                "symbol": s["symbol"],
                "signal_type": signal_type,
                "action_pl": action_pl,
                "status": status,
                "status_pl": status_pl,
                "confidence": round(confidence, 3),
                "confidence_min": MIN_CONFIDENCE,
                "score": round(score, 2),
                "score_min": MIN_SCORE,
                "price": round(price, 6) if price else None,
                "rsi": round(float(rsi), 1) if rsi is not None else None,
                "ema_20": round(float(ema_20), 6) if ema_20 else None,
                "ema_50": round(float(ema_50), 6) if ema_50 else None,
                "trend": "WZROSTOWY" if (ema_20 and ema_50 and float(ema_20) > float(ema_50)) else "SPADKOWY" if (ema_20 and ema_50) else "BRAK DANYCH",
                "missing_conditions": missing_conditions,
                "expected_profit_pct": s.get("expected_profit_pct"),
                "risk_pct": s.get("risk_pct"),
                "score_breakdown": s.get("score_breakdown", []),
            })

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
        required_move_pct = (target_value_eur - current_value_eur) / current_value_eur * 100
    elif target_price and current_price > 0:
        target_type = "price"
        target_val = target_price
        required_move_pct = (target_price - current_price) / current_price * 100
    elif target_profit_pct and entry_price > 0:
        target_type = "pct"
        target_val = target_profit_pct
        current_pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
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
    fast_rate = max(0.1, 3.5)   # % dziennie, optymistycznie
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
        blockers.append(f"RSI {rsi:.0f} — symbol wykupiony, możliwa korekta przed wzrostem")
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
    "BUY":              "KUP",
    "SELL":             "SPRZEDAJ",
    "HOLD":             "TRZYMAJ",
    "HOLD_TARGET":      "TRZYMAJ (CEL)",
    "PREPARE_EXIT":     "PRZYGOTUJ SPRZEDAŻ",
    "PARTIAL_EXIT":     "SPRZEDAJ CZĘŚĆ",
    "SELL_AT_TARGET":   "SPRZEDAJ NA CELU",
    "DO_NOT_ADD":       "NIE DOKŁADAJ",
    "NO_NEW_ENTRIES":   "BRAK NOWYCH WEJŚĆ",
    "WAIT":             "CZEKAJ",
    "WAIT_FOR_SIGNAL":  "CZEKAJ NA SYGNAŁ",
    "KANDYDAT_DO_WEJŚCIA": "KANDYDAT DO WEJŚCIA",
    "WEJŚCIE_AKTYWNE":  "WEJŚCIE AKTYWNE",
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
    trend = "WZROSTOWY" if (ema_20 and ema_50 and float(ema_20) > float(ema_50)) else \
            "SPADKOWY" if (ema_20 and ema_50) else "BRAK DANYCH"
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
            position_state["distance_to_target_pct"] = round(dist_pct, 1) if dist_pct is not None else None

            allowed_actions = ["HOLD", "PARTIAL_EXIT", "SELL_AT_TARGET"]
            blocked_actions = ["BUY"]  # nie dokładaj do pozycji z celem

            if dist_pct is not None and dist_pct <= 2:
                final_action = "SELL_AT_TARGET"
                final_reason = (
                    f"Cel osiągnięty — wartość pozycji {pos_val:.0f} EUR ≥ {t_val_eur:.0f} EUR"
                )
                next_trigger = f"Sprzedaj całość (cel: {t_val_eur:.0f} EUR)"
            elif dist_pct is not None and dist_pct <= 8:
                final_action = "PREPARE_EXIT"
                final_reason = (
                    f"Blisko celu {t_val_eur:.0f} EUR — "
                    f"brakuje {remaining:.1f} EUR ({dist_pct:.1f}%)"
                )
                next_trigger = f"Przygotuj zlecenie SELL gdy wartość ≥ {t_val_eur * 0.97:.0f} EUR"
            else:
                final_action = "HOLD_TARGET"
                cur_p_str = f"{position_state.get('current_price') or 0:.4f}"
                final_reason = (
                    f"Użytkownik czeka na {t_val_eur:.0f} EUR za całość. "
                    f"Teraz: {pos_val:.0f} EUR, brakuje {remaining:.1f} EUR ({dist_pct:.1f}%)"
                )
                next_trigger = (
                    f"Cena musi wzrosnąć o {dist_pct:.1f}% (z {cur_p_str} EUR)"
                    if dist_pct else "Brak danych o cenie"
                )

        # Cel wartości pozycji w EUR — gdy NIE MA pozycji
        elif t_val_eur and not position_state:
            final_action = "WAIT" if no_buy else signal_type
            blocked_actions = ["BUY"] if no_buy else []
            final_reason = (
                "Brak pozycji — chcesz osiągnąć cel wartości, ale nie masz jeszcze wejścia"
                if not no_buy else
                "Zakaz nowego zakupu aktywny, nowe wejście zablokowane"
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
                    if dist_price_pct else f"Czekaj na cenę {t_price:.4f} EUR"
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
                final_reason = f"Blisko celu zysku {t_pct:+.1f}% (teraz: {pnl_pct:+.1f}%)"
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
                final_reason = "Sygnał techniczny (zakaz kupna aktywny, ale brak sygnału KUP)"
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
            final_reason = "Sygnał techniczny (aktywne oczekiwanie, brak konkretnego celu)"

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
                position_state["distance_to_target_pct"] = round(dist_pct, 1) if dist_pct is not None else None

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
                        if dist_pct else "Brak danych o cenie"
                    )
            elif position_state is None:
                final_action = "WAIT"
                final_reason = f"Symbol '{symbol}' — brak nowych wejść (konfiguracja tier)"
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
    if winning_priority not in ("safety", "user_goal", "portfolio_tier") and position_state is not None:
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
        if pnl_pct >= 8 and winning_priority == "symbol_signal" and signal_type == "BUY":
            winning_priority = "position_mgmt"
            final_action = "DO_NOT_ADD"
            final_reason = f"Pozycja już zyskowna ({pnl_pct:+.1f}%) — nie dokładaj, ryzyko ekspozycji"
            next_trigger = "Rozważ częściową realizację zysku przy dalszym wzroście"
            blocked_actions = list(set(blocked_actions + ["BUY"]))

        if winning_priority == "symbol_signal":
            final_reason = f"Sygnał techniczny (istniejąca pozycja, PnL {pnl_pct:+.1f}%)"

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
            final_reason = f"Kandydat do wejścia (pewność {confidence*100:.0f}%) — sygnał kupna"
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
    mode: str = Query("demo"),
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
            result.append({
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
            })
        return {"success": True, "expectations": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania oczekiwań: {str(e)}")


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
        raise HTTPException(status_code=400, detail="Pole 'expectation_type' jest wymagane")

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
        target_value_eur=float(data["target_value_eur"]) if data.get("target_value_eur") is not None else None,
        target_price=float(data["target_price"]) if data.get("target_price") is not None else None,
        target_profit_pct=float(data["target_profit_pct"]) if data.get("target_profit_pct") is not None else None,
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
    mode: str = Query("demo", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Finalne decyzje portfelowe — 6-warstwowy resolver:
    bezpieczeństwo → cel użytkownika → tier → pozycja → sygnał techniczny.
    Każda decyzja zawiera: winning_priority, goal_assessment, blocked_actions.
    """
    try:
        from backend.runtime_settings import get_runtime_config, build_symbol_tier_map

        rs = get_runtime_config(db)
        symbol_tiers = rs.get("symbol_tiers") or {}
        tier_map = build_symbol_tier_map(symbol_tiers)

        symbols = _get_symbols_from_db_or_env(db)
        if not symbols:
            return {"success": True, "decisions": [], "note": "Brak danych rynkowych"}

        positions_db = db.query(Position).filter(Position.mode == mode).all()
        positions_by_symbol = {p.symbol: p for p in positions_db}

        # Pobierz aktywne oczekiwania użytkownika
        expectations_rows = db.query(UserExpectation).filter(
            UserExpectation.mode == mode,
            UserExpectation.is_active == True,
        ).all()
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

        live = _build_live_signals(db, symbols, limit=len(symbols))

        # Cache aktywnych pending orders per symbol
        active_pending_symbols = set()
        try:
            pending_rows = db.query(PendingOrder.symbol).filter(
                PendingOrder.mode == mode,
                PendingOrder.status.in_(["PENDING", "CONFIRMED"]),
            ).all()
            for row in pending_rows:
                if row[0]:
                    active_pending_symbols.add(row[0].strip().upper().replace("/", "").replace("-", ""))
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
            if sym_norm in active_pending_symbols and decision["final_action"] in ("BUY", "KANDYDAT_DO_WEJŚCIA"):
                decision["final_action"] = "WEJŚCIE_AKTYWNE"
                decision["final_action_pl"] = _ACTION_PL.get("WEJŚCIE_AKTYWNE", "WEJŚCIE AKTYWNE")
                decision["final_reason"] = "Zlecenie wejścia w trakcie realizacji"

            decisions.append(decision)

        priority_order = {
            "SELL_AT_TARGET": 0, "PREPARE_EXIT": 1, "HOLD_TARGET": 2,
            "DO_NOT_ADD": 3, "KANDYDAT_DO_WEJŚCIA": 3, "BUY": 4,
            "SELL": 5, "PARTIAL_EXIT": 5, "WAIT": 6, "HOLD": 7,
        }
        decisions.sort(key=lambda x: (
            priority_order.get(x["final_action"], 9),
            -(x["symbol_analysis"].get("score") or 0),
        ))

        summary = {
            "sell_at_target": sum(1 for d in decisions if d["final_action"] == "SELL_AT_TARGET"),
            "prepare_exit":   sum(1 for d in decisions if d["final_action"] == "PREPARE_EXIT"),
            "hold_target":    sum(1 for d in decisions if d["final_action"] == "HOLD_TARGET"),
            "buy_ready":      sum(1 for d in decisions if d["final_action"] == "BUY"),
            "consider_buy":   sum(1 for d in decisions if d["final_action"] == "KANDYDAT_DO_WEJŚCIA"),
            "sell_ready":     sum(1 for d in decisions if d["final_action"] in ("SELL", "PARTIAL_EXIT")),
            "blocked":        sum(1 for d in decisions if d["final_action"] in ("DO_NOT_ADD", "WAIT", "WAIT_FOR_SIGNAL")),
            "hold":           sum(1 for d in decisions if d["final_action"] == "HOLD"),
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
    "all_gates_passed":                  "✅ Wszystkie filtry OK — zlecenie złożone",
    "pending_confirmed_execution":       "✅ Zlecenie wykonane",
    "signal_confidence_too_low":         "❌ Pewność sygnału poniżej progu",
    "signal_too_old":                    "⏳ Sygnał zbyt stary",
    "signal_filters_not_met":            "❌ Filtry techniczne (EMA/RSI/zakres) niezaliczone",
    "active_pending_exists":             "⏳ Mamy otwarte zlecenie dla tego symbolu",
    "buy_blocked_existing_position":     "⏳ Już mamy otwartą pozycję BUY",
    "sell_blocked_no_position":          "❌ SELL bez otwartej pozycji — pomijamy",
    "symbol_not_in_any_tier":            "❌ Symbol nie jest w żadnym tierze (watchliście AI)",
    "hold_mode_no_new_entries":          "🔒 Symbol w trybie HOLD — nie otwieramy nowych",
    "symbol_cooldown_active":            "⏳ Cooldown po ostatniej transakcji",
    "pending_cooldown_active":           "⏳ Cooldown po ostatnim zleceniu",
    "insufficient_cash_or_qty_below_min":"❌ Za mało gotówki lub ilość poniżej minimum",
    "min_notional_guard":                "❌ Wartość zlecenia poniżej minimalnej (Binance wymóg)",
    "cost_gate_failed":                  "❌ Koszty transakcji zbyt wysokie vs oczekiwany zysk",
    "tier_daily_trade_limit":            "❌ Dzienny limit transakcji dla tego tieru osiągnięty",
    "daily_loss_brake_active":           "🛑 Dzienny limit strat — bot wstrzymał handel",
    "risk_evaluation_failed":            "❌ Ocena ryzyka negatywna",
    "no_trace":                          "ℹ️ Brak decyzji w tym oknie — czeka na następny cykl collectora",
}


@router.get("/execution-trace")
def get_execution_trace(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    limit_minutes: int = Query(30, ge=1, le=1440, description="Okno czasowe w minutach"),
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
        for pos in db.query(Position).filter(Position.mode == mode).all():
            if pos.symbol:
                positions_map[pos.symbol] = pos

        pending_map: dict[str, PendingOrder] = {}
        for po in (
            db.query(PendingOrder)
            .filter(PendingOrder.mode == mode, PendingOrder.status.in_(["PENDING", "CONFIRMED"]))
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
                            sig_details[resp_key] = json.loads(val) if isinstance(val, str) else val
                        except Exception:
                            pass

            # Uzupełnij reason_pl o konkretne przyczyny filtra (filter_fails)
            if reason_code == "signal_filters_not_met":
                fails = (sig_details.get("details") or {}).get("filter_fails") or []
                if fails:
                    reason_pl = "❌ Filtry niezaliczone: " + "; ".join(fails)

            rows.append({
                "symbol": sym,
                "reason_code": reason_code,
                "reason_pl": reason_pl,
                "trace_age_seconds": trace_age_s,
                "has_position": pos is not None,
                "has_pending": po is not None,
                "pending_status": po.status if po else None,
                "signal_type": sig.signal_type if sig else None,
                "signal_confidence": round(float(sig.confidence), 3) if sig else None,
                "signal_age_seconds": int((utc_now_naive() - sig.timestamp).total_seconds()) if sig and sig.timestamp else None,
                "details": sig_details,
            })

        # Podsumowanie
        summary = {
            "executed":   sum(1 for r in rows if r["reason_code"] in ("all_gates_passed", "pending_confirmed_execution")),
            "pending":    sum(1 for r in rows if r["has_pending"]),
            "blocked":    sum(1 for r in rows if r["reason_code"] not in ("all_gates_passed", "pending_confirmed_execution", "no_trace")),
            "no_signal":  sum(1 for r in rows if r["signal_type"] is None),
        }

        # Sortuj: blokowane problemy najpierw
        priority = {"insufficient_cash_or_qty_below_min": 0, "signal_filters_not_met": 1, "signal_confidence_too_low": 2}
        rows.sort(key=lambda r: (priority.get(r["reason_code"], 5), r["symbol"]))

        return {
            "success": True,
            "mode": mode,
            "window_minutes": limit_minutes,
            "symbols": rows,
            "summary": summary,
            "updated_at": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd execution-trace: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY READINESS — gotowość systemu do wejścia
# ─────────────────────────────────────────────────────────────────────────────

_ENTRY_BLOCK_PL = {
    "ENTRY_BLOCKED_NO_CASH":              "Brak wystarczającej gotówki",
    "ENTRY_BLOCKED_MIN_NOTIONAL":         "Nominał poniżej minimum",
    "ENTRY_BLOCKED_COOLDOWN":             "Symbol w cooldown (ostatnia transakcja zbyt niedawno)",
    "ENTRY_BLOCKED_MAX_POSITIONS":        "Osiągnięto limit otwartych pozycji",
    "ENTRY_BLOCKED_SIGNAL_CONFIDENCE":    "Za niska pewność sygnału",
    "ENTRY_BLOCKED_SCORE":                "Za niski score okazji",
    "ENTRY_BLOCKED_WATCHLIST":            "Symbol poza watchlistą",
    "ENTRY_BLOCKED_TIER_HOLD":            "Tier HOLD — brak nowych wejść",
    "ENTRY_BLOCKED_KILL_SWITCH":          "Kill switch aktywny",
    "ENTRY_BLOCKED_RISK_GATE":            "Zablokowano przez bramę ryzyka",
    "ENTRY_BLOCKED_ALREADY_HAS_POSITION": "Pozycja już otwarta na tym symbolu",
    "ENTRY_BLOCKED_PENDING_EXISTS":       "Oczekujące zlecenie już istnieje",
    "ENTRY_BLOCKED_SIGNAL_FILTERS":       "Filtry techniczne nie spełnione (trend/RSI/zakres)",
    "ENTRY_BLOCKED_COST_GATE":            "Bramka kosztowa — oczekiwany zysk za mały",
    "ENTRY_ALLOWED":                      "Wejście dozwolone",
    "NO_SIGNAL":                          "Brak sygnału dla symbolu",
}


@router.get("/entry-readiness")
def get_entry_readiness(
    mode: str = Query("demo"),
    db: Session = Depends(get_db),
):
    """
    Gotowość systemu do wejść w bieżącym cyklu DEMO.
    Dla każdego symbolu zwraca: czy wejście możliwe, a jeśli nie — dokładny powód blokady.
    Używane przez dashboard do wyświetlenia realnego stanu zamiast ogólnikowego 'CZEKAJ'.
    """
    try:
        from backend.database import RuntimeSetting, PendingOrder as PO, Order as Ord
        from backend.accounting import compute_demo_account_state
        from backend.runtime_settings import build_runtime_state

        runtime_ctx = build_runtime_state(db)
        config = runtime_ctx.get("config", {})

        # Sprawdź kill switch
        kill_switch = bool(config.get("kill_switch_enabled", True)) and bool(config.get("kill_switch_active", False))

        # Sprawdź konfigurację
        max_open_positions = int(config.get("max_open_positions", 3))
        min_order_notional = float(config.get("min_order_notional", 25.0))
        demo_min_conf = float(config.get("demo_min_signal_confidence", 0.55))
        pending_cooldown_s = int(config.get("pending_order_cooldown_seconds", 300))
        base_cooldown_s = int(float(config.get("cooldown_after_loss_streak_minutes", 15)) * 60)

        # Pobierz account state
        from backend.accounting import get_demo_quote_ccy
        demo_quote_ccy = get_demo_quote_ccy()
        account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy)
        initial_balance = float(account_state.get("initial_balance") or 10000)
        cash = float(account_state.get("cash") or initial_balance)

        # Reserved cash (pending BUY orders)
        reserved_cash = 0.0
        active_pending = db.query(PO).filter(
            PO.mode == mode,
            PO.side == "BUY",
            PO.status.in_(["PENDING", "CONFIRMED"]),
        ).all()
        for p in active_pending:
            try:
                reserved_cash += float(p.price or 0.0) * float(p.quantity or 0.0)
            except Exception:
                pass
        available_cash = max(0.0, cash - reserved_cash)

        # Otwarte pozycje
        open_positions = db.query(Position).filter(Position.mode == mode).all()
        open_count = len(open_positions)
        open_symbols = {p.symbol for p in open_positions}

        now = utc_now_naive()

        # Zbierz sygnały
        symbols = _get_symbols_from_db_or_env(db)
        live_signals = _build_live_signals(db, symbols, limit=len(symbols)) if symbols else []
        signal_map = {s["symbol"]: s for s in live_signals}

        candidates = []
        blocked = []

        for sym in symbols:
            sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
            if not sym_norm.endswith(demo_quote_ccy):
                continue

            sig = signal_map.get(sym, {})
            confidence = float(sig.get("confidence", 0.0))
            signal_type = sig.get("signal_type", "HOLD")
            score_data = _score_opportunity(sig, db) if sig else {}
            score = float(score_data.get("score", 0.0))
            price = sig.get("price") or float(
                (db.query(MarketData).filter(MarketData.symbol == sym)
                 .order_by(MarketData.timestamp.desc()).first() or type("x", (), {"price": None})()).price or 0
            )

            entry_reason = "NO_SIGNAL"
            entry_reason_pl = _ENTRY_BLOCK_PL["NO_SIGNAL"]
            allowed = False

            if kill_switch:
                entry_reason = "ENTRY_BLOCKED_KILL_SWITCH"
            elif signal_type == "HOLD":
                entry_reason = "NO_SIGNAL"
            elif open_count >= max_open_positions:
                entry_reason = "ENTRY_BLOCKED_MAX_POSITIONS"
            elif sym in open_symbols:
                entry_reason = "ENTRY_BLOCKED_ALREADY_HAS_POSITION"
            elif db.query(PO).filter(
                PO.mode == mode, PO.symbol == sym,
                PO.status.in_(["PENDING", "CONFIRMED"])
            ).count() > 0:
                entry_reason = "ENTRY_BLOCKED_PENDING_EXISTS"
            elif confidence < demo_min_conf:
                entry_reason = "ENTRY_BLOCKED_SIGNAL_CONFIDENCE"
            elif available_cash < min_order_notional:
                entry_reason = "ENTRY_BLOCKED_NO_CASH"
            else:
                # Sprawdź cooldown ostatniego zlecenia
                last_ord = db.query(Ord).filter(
                    Ord.symbol == sym, Ord.mode == mode
                ).order_by(Ord.timestamp.desc()).first()
                in_cooldown = last_ord and (now - last_ord.timestamp).total_seconds() < base_cooldown_s
                # Sprawdź cooldown pending
                last_pend = db.query(PO).filter(
                    PO.mode == mode, PO.symbol == sym
                ).order_by(PO.created_at.desc()).first()
                in_pending_cooldown = last_pend and last_pend.created_at and (
                    now - last_pend.created_at
                ).total_seconds() < pending_cooldown_s

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

        can_enter_now = len(candidates) > 0 and open_count < max_open_positions and available_cash >= min_order_notional

        if can_enter_now:
            status_pl = f"WEJŚCIE MOŻLIWE TERAZ: {best_ready['symbol']}" if best_ready else "WEJŚCIE MOŻLIWE"
        elif candidates:
            status_pl = f"OKAZJE SĄ, ALE ZABLOKOWANE: {best_blocked['entry_reason_pl']}" if best_blocked else "OKAZJE ZABLOKOWANE"
        elif blocked:
            status_pl = f"OKAZJE SĄ, ALE ZABLOKOWANE: {best_blocked['entry_reason_pl']}" if best_blocked else "OKAZJE ZABLOKOWANE"
        else:
            status_pl = "BRAK SENSOWNYCH OKAZJI"

        return {
            "success": True,
            "mode": mode,
            "can_enter_now": can_enter_now,
            "ready_count": len(candidates),
            "blocked_count": len(blocked),
            "open_positions": open_count,
            "max_open_positions": max_open_positions,
            "cash_available": round(available_cash, 2),
            "min_notional": min_order_notional,
            "kill_switch_active": kill_switch,
            "best_ready_symbol": best_ready["symbol"] if best_ready else None,
            "best_ready_score": best_ready["score"] if best_ready else None,
            "best_blocked_symbol": best_blocked["symbol"] if best_blocked else None,
            "best_blocked_reason": best_blocked["entry_reason"] if best_blocked else None,
            "best_blocked_reason_pl": best_blocked["entry_reason_pl"] if best_blocked else None,
            "status_pl": status_pl,
            "candidates": candidates[:5],
            "blocked": blocked[:10],
            "updated_at": now.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd entry-readiness: {str(e)}")

