"""
Signals API Router - endpoints dla sygnałów AI
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta
import random
import json

from backend.database import get_db, Signal

router = APIRouter()


class DemoSignalGenerator:
    """Generator demo sygnałów"""
    
    @staticmethod
    def generate_demo_signals(db: Session, count: int = 20):
        """Wygeneruj przykładowe sygnały AI"""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MATICUSDT", "BNBUSDT"]
        signal_types = ["BUY", "SELL", "HOLD"]
        
        signals = []
        for i in range(count):
            timestamp = datetime.utcnow() - timedelta(hours=random.randint(1, 48))
            signal_type = random.choice(signal_types)
            confidence = round(random.uniform(0.6, 0.95), 2)
            
            # Przykładowe wskaźniki
            indicators = {
                "ema_20": round(random.uniform(100, 50000), 2),
                "ema_50": round(random.uniform(100, 50000), 2),
                "rsi": round(random.uniform(20, 80), 2),
                "macd": round(random.uniform(-100, 100), 2),
                "volume": round(random.uniform(1000, 100000), 2)
            }
            
            # Uzasadnienie po polsku
            reasons = [
                "RSI wskazuje na wykupienie - spodziewana korekta",
                "EMA 20 przecięła EMA 50 od dołu - sygnał kupna",
                "Wolumen znacząco wzrósł - potencjalne wybicie",
                "MACD pokazuje dywergencję niedźwiedzią",
                "Formacja świecowa młot - możliwe odbicie",
                "Trend wzrostowy zachowany - kontynuacja",
                "Przekroczono opór - możliwe dalsze wzrosty",
                "Spadek poniżej wsparcia - ryzyko dalszych spadków"
            ]
            
            signal = Signal(
                symbol=random.choice(symbols),
                signal_type=signal_type,
                confidence=confidence,
                price=round(random.uniform(100, 50000), 2),
                indicators=json.dumps(indicators),
                reason=random.choice(reasons),
                timestamp=timestamp
            )
            signals.append(signal)
        
        db.bulk_save_objects(signals)
        db.commit()
        return count


@router.get("/latest")
async def get_latest_signals(
    limit: int = Query(10, ge=1, le=100, description="Liczba sygnałów"),
    signal_type: Optional[str] = Query(None, description="Filtr: BUY, SELL, HOLD"),
    db: Session = Depends(get_db)
):
    """
    Pobierz najnowsze sygnały AI
    """
    try:
        query = db.query(Signal)
        
        if signal_type:
            query = query.filter(Signal.signal_type == signal_type)
        
        signals = query.order_by(desc(Signal.timestamp)).limit(limit).all()
        
        # Jeśli brak, wygeneruj demo
        if not signals:
            DemoSignalGenerator.generate_demo_signals(db, 20)
            return await get_latest_signals(limit, signal_type, db)
        
        # Formatuj dane
        result = []
        for sig in signals:
            indicators = {}
            try:
                indicators = json.loads(sig.indicators) if sig.indicators else {}
            except:
                pass
            
            result.append({
                "id": sig.id,
                "symbol": sig.symbol,
                "signal_type": sig.signal_type,
                "confidence": sig.confidence,
                "price": sig.price,
                "indicators": indicators,
                "reason": sig.reason,
                "timestamp": sig.timestamp.isoformat()
            })
        
        return {
            "success": True,
            "data": result,
            "count": len(result)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting signals: {str(e)}")


@router.get("/top10")
async def get_top10_signals(db: Session = Depends(get_db)):
    """
    Top 10 sygnałów (najwyższy confidence, BUY i SELL)
    """
    try:
        # Pobierz top 10 z ostatnich 48h
        since = datetime.utcnow() - timedelta(hours=48)
        
        signals = db.query(Signal).filter(
            Signal.timestamp >= since,
            Signal.signal_type.in_(["BUY", "SELL"])
        ).order_by(desc(Signal.confidence)).limit(10).all()
        
        if not signals:
            DemoSignalGenerator.generate_demo_signals(db, 20)
            return await get_top10_signals(db)
        
        # Formatuj dane
        result = []
        for sig in signals:
            indicators = {}
            try:
                indicators = json.loads(sig.indicators) if sig.indicators else {}
            except:
                pass
            
            result.append({
                "id": sig.id,
                "symbol": sig.symbol,
                "signal_type": sig.signal_type,
                "confidence": sig.confidence,
                "price": sig.price,
                "indicators": indicators,
                "reason": sig.reason,
                "timestamp": sig.timestamp.isoformat()
            })
        
        return {
            "success": True,
            "data": result,
            "count": len(result),
            "description": "Top 10 sygnałów z ostatnich 48h"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting top10 signals: {str(e)}")


@router.get("/top5")
async def get_top5_signals(db: Session = Depends(get_db)):
    """
    Top 5 sygnałów (najwyższy confidence, BUY i SELL)
    """
    try:
        since = datetime.utcnow() - timedelta(hours=24)
        
        signals = db.query(Signal).filter(
            Signal.timestamp >= since,
            Signal.signal_type.in_(["BUY", "SELL"])
        ).order_by(desc(Signal.confidence)).limit(5).all()
        
        if not signals:
            DemoSignalGenerator.generate_demo_signals(db, 20)
            return await get_top5_signals(db)
        
        # Formatuj dane
        result = []
        for sig in signals:
            indicators = {}
            try:
                indicators = json.loads(sig.indicators) if sig.indicators else {}
            except:
                pass
            
            result.append({
                "id": sig.id,
                "symbol": sig.symbol,
                "signal_type": sig.signal_type,
                "confidence": sig.confidence,
                "price": sig.price,
                "indicators": indicators,
                "reason": sig.reason,
                "timestamp": sig.timestamp.isoformat()
            })
        
        return {
            "success": True,
            "data": result,
            "count": len(result),
            "description": "Top 5 sygnałów z ostatnich 24h"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting top5 signals: {str(e)}")
