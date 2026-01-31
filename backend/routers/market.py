"""
Market API Router - endpoints dla danych rynkowych
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from datetime import datetime, timedelta

from backend.database import get_db, MarketData, Kline
from backend.binance_client import get_binance_client

router = APIRouter()


@router.get("/summary")
async def get_market_summary(db: Session = Depends(get_db)):
    """
    Pobierz podsumowanie rynku - ostatnie dane dla watchlist
    """
    try:
        # Pobierz ostatnie dane dla każdego symbolu
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MATICUSDT", "BNBUSDT"]
        
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
                binance = get_binance_client()
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
