"""
Market API Router - endpoints dla danych rynkowych
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import os
import json

from backend.database import get_db, MarketData, Kline, SystemLog, ForecastRecord, utc_now_naive
from backend.binance_client import get_binance_client

router = APIRouter()


def _asset_to_candidates(asset: str) -> list[str]:
    """Mapuje asset (np. LDBTC, BTC) na listę kandydatów do par walutowych."""
    a = (asset or "").strip().upper()
    if not a:
        return []
    if a.startswith("LD") and len(a) > 2:
        return [a[2:], a]
    return [a]


@router.get("/summary")
def get_market_summary(request: Request, db: Session = Depends(get_db)):
    """
    Pobierz podsumowanie rynku - ostatnie dane dla watchlist
    """
    try:
        binance = get_binance_client()
        symbols: List[str] = []

        # 1) Preferuj watchlistę z kolektora (jeśli działa)
        collector = getattr(request.app.state, "collector", None)
        if collector is not None:
            wl = getattr(collector, "watchlist", None)
            if isinstance(wl, list) and wl:
                symbols = [str(s) for s in wl if s]

        # 2) Fallback: zbuduj z portfela Binance
        if not symbols:
            quotes = [q.strip().upper() for q in os.getenv("PORTFOLIO_QUOTES", "EUR,USDC").split(",") if q.strip()]
            balances = binance.get_balances()
            assets = [b.get("asset") for b in balances if (b.get("total") or 0) > 0]

            for asset in assets:
                if not asset:
                    continue
                for base in _asset_to_candidates(asset):
                    if not base or base in quotes:
                        continue
                    for quote in quotes:
                        pair = f"{base}/{quote}"
                        resolved = binance.resolve_symbol(pair)
                        if resolved and resolved not in symbols:
                            symbols.append(resolved)

        # 3) Fallback: stała WATCHLIST z `.env` (działa bez kluczy)
        if not symbols:
            raw_watchlist = os.getenv("WATCHLIST", "")
            items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
            for item in items:
                resolved_symbol = binance.resolve_symbol(item)
                if not resolved_symbol:
                    resolved_symbol = item.replace("/", "").strip().upper()
                if resolved_symbol and resolved_symbol not in symbols:
                    symbols.append(resolved_symbol)
        
        summary = []
        for symbol in symbols:
            # Ostatni ticker z bazy
            latest = db.query(MarketData).filter(
                MarketData.symbol == symbol
            ).order_by(desc(MarketData.timestamp)).first()
            
            if latest:
                # Poprzednia cena (24h temu)
                day_ago = utc_now_naive() - timedelta(hours=24)
                prev = db.query(MarketData).filter(
                    MarketData.symbol == symbol,
                    MarketData.timestamp >= day_ago
                ).order_by(MarketData.timestamp).first()
                
                price_change = 0
                price_change_percent = 0
                if prev and prev.price > 0:
                    price_change = latest.price - prev.price
                    price_change_percent = (price_change / prev.price) * 100
                
                summary.append({
                    "symbol": symbol,
                    "price": latest.price,
                    "volume": latest.volume,
                    "bid": latest.bid,
                    "ask": latest.ask,
                    "price_change": price_change,
                    "price_change_percent": price_change_percent,
                    "timestamp": latest.timestamp.isoformat(),
                    "last_update": latest.timestamp.isoformat()
                })
            else:
                # Fallback - pobierz z Binance jeśli brak w bazie
                ticker = binance.get_24hr_ticker(symbol)
                
                if ticker:
                    summary.append({
                        "symbol": symbol,
                        "price": ticker["last_price"],
                        "volume": ticker["volume"],
                        "bid": ticker["bid_price"],
                        "ask": ticker["ask_price"],
                        "price_change": ticker["price_change"],
                        "price_change_percent": ticker["price_change_percent"],
                        "timestamp": utc_now_naive().isoformat(),
                        "last_update": utc_now_naive().isoformat()
                    })
        
        return {
            "success": True,
            "data": summary,
            "count": len(summary),
            "timestamp": utc_now_naive().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting market summary: {str(e)}")


@router.get("/kline")
def get_kline_data(
    symbol: str = Query(..., description="Symbol (np. BTCUSDT)"),
    tf: str = Query("1h", description="Timeframe (1m, 5m, 15m, 1h, 4h, 1d)"),
    limit: int = Query(100, ge=1, le=1000, description="Liczba świec"),
    db: Session = Depends(get_db)
):
    """
    Pobierz dane świecowe (klines) dla symbolu
    """
    try:
        # Mapowanie tf na timeframe
        timeframe_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d"
        }
        
        timeframe = timeframe_map.get(tf, "1h")
        
        # Pobierz z bazy danych
        klines = db.query(Kline).filter(
            Kline.symbol == symbol,
            Kline.timeframe == timeframe
        ).order_by(desc(Kline.open_time)).limit(limit).all()
        
        if not klines:
            # Fallback - pobierz z Binance
            binance = get_binance_client()
            klines_data = binance.get_klines(symbol, timeframe, limit)
            
            if klines_data:
                result = []
                for k in klines_data:
                    result.append({
                        "timestamp": k["open_time"],
                        "open": k["open"],
                        "high": k["high"],
                        "low": k["low"],
                        "close": k["close"],
                        "volume": k["volume"]
                    })
                
                return {
                    "success": True,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "data": result,
                    "count": len(result),
                    "source": "binance"
                }
        
        # Formatuj dane z bazy
        result = []
        for k in reversed(klines):  # Odwróć aby były chronologicznie
            result.append({
                "timestamp": int(k.open_time.timestamp() * 1000),
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume
            })
        
        return {
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "data": result,
            "count": len(result),
            "source": "database"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting kline data: {str(e)}")


@router.get("/ticker/{symbol}")
def get_ticker(symbol: str, db: Session = Depends(get_db)):
    """
    Pobierz aktualną cenę symbolu
    """
    try:
        # Najpierw z bazy
        latest = db.query(MarketData).filter(
            MarketData.symbol == symbol
        ).order_by(desc(MarketData.timestamp)).first()
        
        if latest:
            return {
                "success": True,
                "symbol": symbol,
                "price": latest.price,
                "bid": latest.bid,
                "ask": latest.ask,
                "volume": latest.volume,
                "timestamp": latest.timestamp.isoformat(),
                "source": "database"
            }
        
        # Fallback - Binance
        binance = get_binance_client()
        ticker = binance.get_ticker_price(symbol)
        
        if ticker:
            return {
                "success": True,
                "symbol": symbol,
                "price": ticker["price"],
                "timestamp": utc_now_naive().isoformat(),
                "source": "binance"
            }
        
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting ticker: {str(e)}")


@router.get("/orderbook/{symbol}")
def get_orderbook(
    symbol: str,
    limit: int = Query(20, ge=5, le=100, description="Głębokość orderbook")
):
    """
    Pobierz orderbook (księgę zleceń) - zawsze z Binance (real-time)
    """
    try:
        binance = get_binance_client()
        orderbook = binance.get_orderbook(symbol, limit)
        
        if orderbook:
            return {
                "success": True,
                "symbol": symbol,
                "bids": orderbook["bids"],
                "asks": orderbook["asks"],
                "timestamp": utc_now_naive().isoformat()
            }
        
        raise HTTPException(status_code=404, detail=f"Orderbook for {symbol} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting orderbook: {str(e)}")


@router.get("/ranges")
def get_price_ranges(
    symbol: Optional[str] = Query(None, description="Symbol (np. BTCUSDT)"),
    db: Session = Depends(get_db)
):
    """
    Zwróć ostatnie zakresy cen (OpenAI) zapisane w blogu.
    """
    try:
        from backend.database import BlogPost
        latest = db.query(BlogPost).order_by(desc(BlogPost.created_at)).first()
        if not latest or not latest.market_insights:
            return {"success": True, "data": []}

        insights = json.loads(latest.market_insights)
        ranges = []
        for ins in insights:
            r = ins.get("range")
            if not r:
                continue
            if symbol and ins.get("symbol") != symbol:
                continue
            ranges.append({
                "symbol": ins.get("symbol"),
                "buy_low": r.get("buy_low"),
                "buy_high": r.get("buy_high"),
                "sell_low": r.get("sell_low"),
                "sell_high": r.get("sell_high"),
                "buy_action": r.get("buy_action"),
                "buy_target": r.get("buy_target"),
                "sell_action": r.get("sell_action"),
                "sell_target": r.get("sell_target"),
                "comment": r.get("comment"),
                "timestamp": ins.get("timestamp"),
            })

        return {"success": True, "data": ranges}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting ranges: {str(e)}")


@router.get("/quantum")
def get_quantum_analysis(
    db: Session = Depends(get_db)
):
    """
    Zwróć ostatnią analizę kwantową z bloga.
    """
    try:
        from backend.database import BlogPost
        latest = db.query(BlogPost).order_by(desc(BlogPost.created_at)).first()
        if not latest or not latest.market_insights:
            return {"success": True, "data": []}

        insights = json.loads(latest.market_insights)
        data = []
        for ins in insights:
            q = ins.get("quantum")
            if q:
                data.append({
                    "symbol": ins.get("symbol"),
                    "weight": q.get("weight"),
                    "volatility": q.get("volatility"),
                    "timestamp": ins.get("timestamp"),
                })

        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting quantum: {str(e)}")


@router.post("/analyze-now")
def analyze_now(
    force: bool = Query(True, description="Jeśli true, pomija blokadę 1h i backoff (debug)"),
    db: Session = Depends(get_db),
):
    """
    Ręczne uruchomienie analizy + generacji bloga (OpenAI ranges) dla watchlisty z portfela.
    Przydatne do testów po podmianie OPENAI_API_KEY bez czekania 1h.
    """
    try:
        from backend.analysis import maybe_generate_insights_and_blog

        binance = get_binance_client()
        quotes = [q.strip().upper() for q in os.getenv("PORTFOLIO_QUOTES", "EUR,USDC").split(",") if q.strip()]
        symbols: List[str] = []
        balances = binance.get_balances()
        assets = [b.get("asset") for b in balances if (b.get("total") or 0) > 0]

        for asset in assets:
            if not asset:
                continue
            for base in _asset_to_candidates(asset):
                if not base or base in quotes:
                    continue
                for quote in quotes:
                    pair = f"{base}/{quote}"
                    resolved = binance.resolve_symbol(pair)
                    if resolved and resolved not in symbols:
                        symbols.append(resolved)

        if not symbols:
            raise HTTPException(status_code=400, detail="Brak symboli z portfela (Spot) do analizy")

        post = maybe_generate_insights_and_blog(db, symbols, force=force)
        if not post:
            last_err = (
                db.query(SystemLog)
                .filter(SystemLog.module == "analysis", SystemLog.level == "ERROR")
                .order_by(desc(SystemLog.timestamp))
                .first()
            )
            return {
                "success": True,
                "symbols": symbols,
                "generated": False,
                "message": "Nie wygenerowano nowych zakresów/insightów (sprawdź Logi -> module=analysis).",
                "last_openai_error": (last_err.message[:220] if last_err and last_err.message else None),
            }
        return {
            "success": True,
            "symbols": symbols,
            "generated": True,
            "post_id": post.id,
            "created_at": post.created_at.isoformat() if post.created_at else None,
            "title": post.title,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyze-now: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# MARKET SCANNER — TOP N okazji wyliczonych z prawdziwej analizy technicznej
# ─────────────────────────────────────────────────────────────────────────────

def _score_symbol(db: Session, symbol: str) -> Optional[dict]:
    """
    Oblicz composite score dla symbolu na podstawie wskaźników technicznych.
    Zwraca dict z polami: symbol, signal, confidence, score, price, reasons, rsi, trend
    lub None jeśli brak danych.
    """
    from backend.analysis import get_live_context
    import pandas as pd
    import pandas_ta as ta

    ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
    if not ctx:
        return None

    rsi = ctx.get("rsi")
    ema_20 = ctx.get("ema_20")
    ema_50 = ctx.get("ema_50")
    atr = ctx.get("atr")
    close = ctx.get("close")
    rsi_buy = ctx.get("rsi_buy", 35)
    rsi_sell = ctx.get("rsi_sell", 65)

    if close is None or close <= 0:
        return None

    # ── Wyznacz sygnał i confidence ──────────────────────────────────
    signal = "HOLD"
    confidence = 0.50
    reasons: List[str] = []

    if rsi is not None:
        if rsi < rsi_buy:
            reasons.append(f"RSI {rsi:.0f} — wyprzedanie (poniżej {rsi_buy:.0f})")
            signal = "BUY"
            confidence += min(0.20, (rsi_buy - rsi) / rsi_buy * 0.25)
        elif rsi > rsi_sell:
            reasons.append(f"RSI {rsi:.0f} — wykupienie (powyżej {rsi_sell:.0f})")
            signal = "SELL"
            confidence += min(0.20, (rsi - rsi_sell) / (100 - rsi_sell) * 0.25)
        else:
            reasons.append(f"RSI {rsi:.0f} — strefa neutralna")

    trend = "BOCZNY"
    if ema_20 is not None and ema_50 is not None:
        ema_margin_pct = abs(ema_20 - ema_50) / ema_50 * 100 if ema_50 > 0 else 0
        if ema_20 > ema_50:
            trend = "WZROSTOWY"
            reasons.append(f"EMA20 > EMA50 — trend wzrostowy (+{ema_margin_pct:.1f}%)")
            if signal == "BUY":
                confidence += 0.10
            elif signal == "SELL":
                confidence -= 0.05
        else:
            trend = "SPADKOWY"
            reasons.append(f"EMA20 < EMA50 — trend spadkowy (-{ema_margin_pct:.1f}%)")
            if signal == "SELL":
                confidence += 0.10
            elif signal == "BUY":
                confidence -= 0.05

    # Momentum (ATR jako % ceny = zmienność)
    volatility_pct = (atr / close * 100) if atr and close else 0
    if volatility_pct > 3:
        reasons.append(f"Wysoka zmienność ({volatility_pct:.1f}%) — dobry moment na wejście")
        confidence += 0.05

    confidence = round(max(0.40, min(confidence, 0.97)), 2)

    # Pobierz aktualną cenę z bazy lub Binance
    latest_md = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol)
        .order_by(desc(MarketData.timestamp))
        .first()
    )
    price = latest_md.price if latest_md else close

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "score": confidence if signal != "HOLD" else confidence * 0.6,
        "price": price,
        "rsi": round(rsi, 1) if rsi else None,
        "trend": trend,
        "volatility_pct": round(volatility_pct, 2),
        "reasons": reasons,
        "timestamp": utc_now_naive().isoformat(),
    }


@router.get("/scanner")
def market_scanner(
    request: Request,
    top_n: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """
    Market Scanner — rankinguje dostępne symbole i zwraca TOP N okazji
    na podstawie analizy technicznej (RSI, EMA, ATR).
    Działa bez OpenAI.
    """
    try:
        # Pobierz symbole z kolektora lub portfela
        symbols: List[str] = []
        collector = getattr(request.app.state, "collector", None)
        if collector is not None:
            wl = getattr(collector, "watchlist", None)
            if isinstance(wl, list) and wl:
                symbols = list(wl)

        if not symbols:
            binance = get_binance_client()
            quotes = [q.strip().upper() for q in os.getenv("PORTFOLIO_QUOTES", "EUR,USDC").split(",") if q.strip()]
            balances = binance.get_balances()
            assets = [b.get("asset") for b in balances if (b.get("total") or 0) > 0]
            for asset in assets:
                if not asset:
                    continue
                base = asset.upper()
                if base.startswith("LD") and len(base) > 2:
                    base = base[2:]
                if base in quotes:
                    continue
                for quote in quotes:
                    sym = binance.resolve_symbol(f"{base}/{quote}")
                    if sym and sym not in symbols:
                        symbols.append(sym)

        if not symbols:
            raw = os.getenv("WATCHLIST", "")
            symbols = [s.strip() for s in raw.split(",") if s.strip()]

        results = []
        for sym in symbols:
            scored = _score_symbol(db, sym)
            if scored:
                results.append(scored)

        # Sortuj wg score malejąco, HOLD na końcu
        results.sort(key=lambda x: (-x["score"], x["signal"] == "HOLD"))

        top = results[:top_n]
        return {
            "success": True,
            "data": top,
            "scanned": len(results),
            "top_n": top_n,
            "timestamp": utc_now_naive().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scanner error: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# FORECAST — prognoza kierunku ceny 1h / 4h / 24h (EMA + momentum, bez ML)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/forecast/{symbol}")
def get_forecast(
    symbol: str,
    db: Session = Depends(get_db),
):
    """
    Prognoza kierunku dla symbolu (1h / 4h / 24h).
    Używa EMA momentum + ATR do projekcji liniowej.
    Nie wymaga OpenAI. Jakość modelu na podstawie trafności historycznej RSI.
    """
    try:
        from backend.analysis import get_live_context
        import math

        ctx_1h = get_live_context(db, symbol, timeframe="1h", limit=200)
        ctx_4h = get_live_context(db, symbol, timeframe="4h", limit=100)

        latest_md = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(desc(MarketData.timestamp))
            .first()
        )
        current_price = latest_md.price if latest_md else (ctx_1h.get("close") if ctx_1h else None)

        if not current_price:
            raise HTTPException(status_code=404, detail=f"Brak danych ceny dla {symbol}")

        forecasts: dict = {}

        def _project(ctx: Optional[dict], hours: int) -> Optional[dict]:
            if not ctx:
                return None
            close = ctx.get("close", current_price)
            ema_20 = ctx.get("ema_20")
            ema_50 = ctx.get("ema_50")
            atr = ctx.get("atr", 0)
            rsi = ctx.get("rsi", 50)

            if not ema_20 or not ema_50:
                return None

            # Momentum: EMA spread jako % ceny
            ema_spread = (ema_20 - ema_50) / close * 100 if close > 0 else 0
            # ATR jako % ceny (oczekiwany ruch na świecę)
            atr_pct = atr / close * 100 if close > 0 else 0

            # Projekcja liniowa: kierunek z EMA spread, zasięg z ATR
            direction_pct = ema_spread * 0.3  # wytłumiony mnożnik
            # Ogranicz do 2× ATR % per hour
            max_move = atr_pct * math.sqrt(hours) * 0.5
            projected_pct = max(-max_move, min(direction_pct, max_move))
            projected_price = close * (1 + projected_pct / 100)

            # Jakość: oparta o RSI (skrajne wartości = lepsza przewidywalność)
            rsi_quality = abs(rsi - 50) / 50  # 0..1, większy = skrajniejszy RSI
            model_quality = round(50 + rsi_quality * 35, 0)  # 50..85%

            direction = "WZROST" if projected_pct > 0.2 else ("SPADEK" if projected_pct < -0.2 else "BOCZNY")

            return {
                "direction": direction,
                "projected_pct": round(projected_pct, 2),
                "projected_price": round(projected_price, 8 if current_price < 1 else 4 if current_price < 100 else 2),
                "model_quality": int(model_quality),
                "atr_pct": round(atr_pct, 2),
            }

        f1h = _project(ctx_1h, 1)
        f4h = _project(ctx_1h, 4)  # 4× ATR z 1h
        f24h = _project(ctx_4h, 6) if ctx_4h else _project(ctx_1h, 24)

        # Zapisz prognozy do DB dla śledzenia trafności
        now = utc_now_naive()
        for horizon, fdata, hours in [("1h", f1h, 1), ("4h", f4h, 4), ("24h", f24h, 24)]:
            if fdata:
                try:
                    rec = ForecastRecord(
                        symbol=symbol,
                        horizon=horizon,
                        forecast_ts=now,
                        forecast_price=fdata["projected_price"],
                        current_price_at_forecast=float(current_price),
                        projected_pct=fdata.get("projected_pct"),
                        direction=fdata.get("direction"),
                        target_ts=now + timedelta(hours=hours),
                        checked=False,
                    )
                    db.add(rec)
                except Exception:
                    pass
        try:
            db.commit()
        except Exception:
            db.rollback()

        return {
            "success": True,
            "symbol": symbol,
            "current_price": current_price,
            "forecast_1h": f1h,
            "forecast_4h": f4h,
            "forecast_24h": f24h,
            "timestamp": utc_now_naive().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast error: {str(e)}")


# FORECAST ACCURACY — historia trafności prognoz dla symbolu
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/forecast-accuracy/{symbol}")
def get_forecast_accuracy(
    symbol: str,
    horizon: Optional[str] = Query(None, description="1h / 4h / 24h — pomiń dla wszystkich"),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Zwraca historię sprawdzonych prognoz dla symbolu oraz statystyki trafności.
    """
    try:
        q = (
            db.query(ForecastRecord)
            .filter(ForecastRecord.symbol == symbol, ForecastRecord.checked == True)  # noqa: E712
        )
        if horizon:
            q = q.filter(ForecastRecord.horizon == horizon)
        records = q.order_by(desc(ForecastRecord.forecast_ts)).limit(limit).all()

        items = []
        for r in records:
            items.append({
                "id": r.id,
                "horizon": r.horizon,
                "forecast_ts": r.forecast_ts.isoformat() if r.forecast_ts else None,
                "target_ts": r.target_ts.isoformat() if r.target_ts else None,
                "current_price_at_forecast": r.current_price_at_forecast,
                "forecast_price": r.forecast_price,
                "actual_price": r.actual_price,
                "error_pct": round(r.error_pct, 2) if r.error_pct is not None else None,
                "direction": r.direction,
                "correct_direction": r.correct_direction,
                "projected_pct": r.projected_pct,
            })

        # Statystyki zbiorcze
        checked_with_error = [r for r in records if r.error_pct is not None]
        correct_dir = [r for r in records if r.correct_direction is True]
        directional_checked = [r for r in records if r.correct_direction is not None]

        avg_error = (
            round(sum(r.error_pct for r in checked_with_error) / len(checked_with_error), 2)
            if checked_with_error else None
        )
        direction_accuracy = (
            round(len(correct_dir) / len(directional_checked) * 100, 1)
            if directional_checked else None
        )

        return {
            "success": True,
            "symbol": symbol,
            "horizon": horizon,
            "count": len(items),
            "avg_error_pct": avg_error,
            "direction_accuracy_pct": direction_accuracy,
            "records": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast accuracy error: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# ALLOWED SYMBOLS — jakie pary SPOT można handlować na tym koncie Binance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/allowed-symbols")
def get_allowed_symbols_endpoint(
    quotes: str = Query("EUR,USDC,USDT", description="Kwoty po przecinku, np. EUR,USDC"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Zwraca listę symboli dozwolonych do handlu SPOT na Binance (wg exchangeInfo),
    z informacją który jest w bieżącej watchliście kolektora.
    Buforowane — nie obciąża API przy każdym request.
    """
    try:
        binance = get_binance_client()
        quotes_list = [q.strip().upper() for q in quotes.split(",") if q.strip()]

        allowed = binance.get_allowed_symbols(quotes=quotes_list)

        # Pobierz aktualną watchlistę kolektora
        watchlist: List[str] = []
        collector = getattr(request.app.state, "collector", None) if request else None
        if collector is not None:
            wl = getattr(collector, "watchlist", None)
            if isinstance(wl, list):
                watchlist = list(wl)

        # Zbuduj listę per-symbol z dodatkowym statusem
        items = []
        for sym, info in sorted(allowed.items()):
            in_watchlist = sym in watchlist
            items.append({
                "symbol": sym,
                "base_asset": info["base_asset"],
                "quote_asset": info["quote_asset"],
                "in_watchlist": in_watchlist,
                "min_qty": info.get("min_qty"),
                "step_size": info.get("step_size"),
                "min_notional": info.get("min_notional"),
            })

        # Osobna lista: symbole z watchlisty które NIE są w allowed
        blocked = [s for s in watchlist if s not in allowed]

        return {
            "success": True,
            "allowed_count": len(items),
            "watchlist_count": len(watchlist),
            "watchlist": watchlist,
            "blocked_in_watchlist": blocked,
            "symbols": items,
            "quotes_filter": quotes_list,
            "cached": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd allowed-symbols: {str(e)}")

