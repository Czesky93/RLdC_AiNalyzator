"""
Orders API Router - endpoints dla zleceń (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import random
import io
import csv

from backend.database import get_db, Order

router = APIRouter()


class OrderCreate(BaseModel):
    """Model do tworzenia zlecenia"""
    symbol: str
    side: str  # BUY, SELL
    order_type: str = "MARKET"  # MARKET, LIMIT
    price: Optional[float] = None
    quantity: float


class DemoOrderGenerator:
    """Generator demo orders"""
    
    @staticmethod
    def generate_demo_orders(db: Session, count: int = 50):
        """Wygeneruj przykładowe zlecenia demo"""
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "MATICUSDT", "BNBUSDT"]
        sides = ["BUY", "SELL"]
        types = ["MARKET", "LIMIT"]
        statuses = ["FILLED", "FILLED", "FILLED", "CANCELLED", "REJECTED"]  # Więcej FILLED
        
        orders = []
        for i in range(count):
            timestamp = datetime.utcnow() - timedelta(hours=random.randint(1, 168))
            
            order = Order(
                symbol=random.choice(symbols),
                side=random.choice(sides),
                order_type=random.choice(types),
                price=round(random.uniform(50, 50000), 2),
                quantity=round(random.uniform(0.01, 10), 4),
                status=random.choice(statuses),
                mode="demo",
                executed_price=round(random.uniform(50, 50000), 2),
                executed_quantity=round(random.uniform(0.01, 10), 4),
                timestamp=timestamp
            )
            orders.append(order)
        
        db.bulk_save_objects(orders)
        db.commit()
        return count


@router.get("/")
async def get_orders(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    status: Optional[str] = Query(None, description="Filtr po statusie (FILLED, CANCELLED, etc.)"),
    symbol: Optional[str] = Query(None, description="Filtr po symbolu"),
    limit: int = Query(100, ge=1, le=500, description="Limit zleceń"),
    db: Session = Depends(get_db)
):
    """
    Pobierz listę zleceń
    """
    try:
        # Query builder
        query = db.query(Order).filter(Order.mode == mode)
        
        if status:
            query = query.filter(Order.status == status)
        
        if symbol:
            query = query.filter(Order.symbol == symbol)
        
        # Pobierz zlecenia
        orders = query.order_by(desc(Order.timestamp)).limit(limit).all()
        
        # Jeśli brak zleceń w demo, wygeneruj
        if not orders and mode == "demo":
            DemoOrderGenerator.generate_demo_orders(db, 50)
            return await get_orders(mode, status, symbol, limit, db)
        
        # Formatuj dane
        result = []
        for order in orders:
            result.append({
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "type": order.order_type,
                "price": order.price,
                "quantity": order.quantity,
                "status": order.status,
                "executed_price": order.executed_price,
                "executed_quantity": order.executed_quantity,
                "timestamp": order.timestamp.isoformat()
            })
        
        return {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting orders: {str(e)}")


@router.post("/")
async def create_order(
    order: OrderCreate,
    mode: str = Query("demo", description="Tryb: demo (live nie jest dostępny - read-only)"),
    db: Session = Depends(get_db)
):
    """
    Utwórz nowe zlecenie (tylko DEMO)
    LIVE mode jest read-only - nie wykonujemy zleceń
    """
    try:
        if mode != "demo":
            raise HTTPException(
                status_code=403,
                detail="Trading in LIVE mode is disabled (read-only). Use DEMO mode."
            )
        
        # Walidacja
        if order.side not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="Invalid side. Use BUY or SELL")
        
        if order.order_type not in ["MARKET", "LIMIT"]:
            raise HTTPException(status_code=400, detail="Invalid type. Use MARKET or LIMIT")
        
        if order.quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        
        # Symulacja wykonania zlecenia
        # W prawdziwym systemie tutaj byłaby logika matchingu z orderbook
        executed_price = order.price if order.order_type == "LIMIT" else round(random.uniform(50, 50000), 2)
        
        # Utwórz zlecenie
        new_order = Order(
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            price=order.price,
            quantity=order.quantity,
            status="FILLED",  # Demo: od razu FILLED
            mode="demo",
            executed_price=executed_price,
            executed_quantity=order.quantity,
            timestamp=datetime.utcnow()
        )
        
        db.add(new_order)
        db.commit()
        db.refresh(new_order)
        
        return {
            "success": True,
            "message": "Zlecenie utworzone (DEMO)",
            "data": {
                "id": new_order.id,
                "symbol": new_order.symbol,
                "side": new_order.side,
                "type": new_order.order_type,
                "price": new_order.price,
                "quantity": new_order.quantity,
                "status": new_order.status,
                "executed_price": new_order.executed_price,
                "executed_quantity": new_order.executed_quantity,
                "timestamp": new_order.timestamp.isoformat()
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating order: {str(e)}")


@router.get("/export.csv")
async def export_orders_csv(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    days: int = Query(7, ge=1, le=90, description="Ile dni wstecz (max 90)"),
    db: Session = Depends(get_db)
):
    """
    Eksportuj zlecenia do CSV
    """
    try:
        # Pobierz zlecenia z ostatnich N dni
        since = datetime.utcnow() - timedelta(days=days)
        
        orders = db.query(Order).filter(
            Order.mode == mode,
            Order.timestamp >= since
        ).order_by(desc(Order.timestamp)).all()
        
        # Jeśli brak, wygeneruj demo
        if not orders and mode == "demo":
            DemoOrderGenerator.generate_demo_orders(db, 50)
            orders = db.query(Order).filter(
                Order.mode == mode,
                Order.timestamp >= since
            ).order_by(desc(Order.timestamp)).all()
        
        # Utwórz CSV w pamięci
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "ID",
            "Symbol",
            "Side",
            "Type",
            "Price",
            "Quantity",
            "Status",
            "Executed Price",
            "Executed Quantity",
            "Timestamp"
        ])
        
        # Dane
        for order in orders:
            writer.writerow([
                order.id,
                order.symbol,
                order.side,
                order.order_type,
                order.price or "",
                order.quantity,
                order.status,
                order.executed_price or "",
                order.executed_quantity or "",
                order.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            ])
        
        # Przygotuj odpowiedź
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=orders_{mode}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting CSV: {str(e)}")


@router.get("/stats")
async def get_order_stats(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    days: int = Query(7, ge=1, le=90, description="Period statystyk"),
    db: Session = Depends(get_db)
):
    """
    Statystyki zleceń
    """
    try:
        since = datetime.utcnow() - timedelta(days=days)
        
        orders = db.query(Order).filter(
            Order.mode == mode,
            Order.timestamp >= since
        ).all()
        
        if not orders:
            return {
                "success": True,
                "mode": mode,
                "data": {
                    "total": 0,
                    "filled": 0,
                    "cancelled": 0,
                    "rejected": 0,
                    "buy_count": 0,
                    "sell_count": 0
                }
            }
        
        # Oblicz statystyki
        total = len(orders)
        filled = sum(1 for o in orders if o.status == "FILLED")
        cancelled = sum(1 for o in orders if o.status == "CANCELLED")
        rejected = sum(1 for o in orders if o.status == "REJECTED")
        buy_count = sum(1 for o in orders if o.side == "BUY")
        sell_count = sum(1 for o in orders if o.side == "SELL")
        
        return {
            "success": True,
            "mode": mode,
            "period_days": days,
            "data": {
                "total": total,
                "filled": filled,
                "cancelled": cancelled,
                "rejected": rejected,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "fill_rate": round((filled / total * 100) if total > 0 else 0, 2)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")
