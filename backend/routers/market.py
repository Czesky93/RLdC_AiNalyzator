"""
Market API Router - endpoints dla danych rynkowych
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta
import os
import json

from backend.database import get_db, MarketData, Kline, SystemLog
from backend.binance_client import get_binance_client

router = APIRouter()


@router.get("/summary")
async def get_market_summary(request: Request, db: Session = Depends(get_db)):
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

            def _candidates(asset: str):
                a = (asset or "").strip().upper()
                if not a:
                    return []
                # LD* (Simple Earn / Savings) -> underlying dla par rynkowych
                if a.startswith("LD") and len(a) > 2:
                    return [a[2:], a]
                return [a]

            for asset in assets:
                if not asset:
                    continue
                for base in _candidates(asset):
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
                day_ago = datetime.utcnow() - timedelta(hours=24)
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
                        "timestamp": datetime.utcnow().isoformat(),
                        "last_update": datetime.utcnow().isoformat()
                    })
        
        return {
            "success": True,
            "data": summary,
            "count": len(summary),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting market summary: {str(e)}")


@router.get("/kline")
async def get_kline_data(
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
async def get_ticker(symbol: str, db: Session = Depends(get_db)):
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
                "timestamp": datetime.utcnow().isoformat(),
                "source": "binance"
            }
        
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting ticker: {str(e)}")


@router.get("/orderbook/{symbol}")
async def get_orderbook(
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
                "timestamp": datetime.utcnow().isoformat()
            }
        
        raise HTTPException(status_code=404, detail=f"Orderbook for {symbol} not found")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting orderbook: {str(e)}")


@router.get("/ranges")
async def get_price_ranges(
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
async def get_quantum_analysis(
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
async def analyze_now(
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

        def _candidates(asset: str):
            a = (asset or "").strip().upper()
            if not a:
                return []
            if a.startswith("LD") and len(a) > 2:
                return [a[2:], a]
            return [a]

        for asset in assets:
            if not asset:
                continue
            for base in _candidates(asset):
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
