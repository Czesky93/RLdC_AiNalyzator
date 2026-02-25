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

from backend.database import get_db, Order, Alert, PendingOrder, MarketData
from backend.auth import require_admin

router = APIRouter()


class OrderCreate(BaseModel):
    """Model do tworzenia zlecenia"""
    symbol: str
    side: str  # BUY, SELL
    order_type: str = "MARKET"  # MARKET, LIMIT
    price: Optional[float] = None
    quantity: float


class PendingOrderCreate(BaseModel):
    symbol: str
    side: str  # BUY, SELL
    quantity: float
    price: Optional[float] = None
    reason: Optional[str] = None


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
        
        # Bez generatora demo - tylko realne dane
        
        # Formatuj dane
        result = []
        for order in orders:
            # Spróbuj znaleźć powiązany alert z powodem
            reason = None
            alert = db.query(Alert).filter(
                Alert.symbol == order.symbol,
                Alert.alert_type == "SIGNAL",
                Alert.timestamp <= order.timestamp + timedelta(minutes=2),
                Alert.timestamp >= order.timestamp - timedelta(minutes=2)
            ).order_by(Alert.timestamp.desc()).first()
            if alert and alert.message:
                reason = alert.message
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
                "timestamp": order.timestamp.isoformat(),
                "reason": reason
            })
        
        return {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting orders: {str(e)}")


@router.get("/pending")
async def get_pending_orders(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    status: Optional[str] = Query(None, description="PENDING/CONFIRMED/REJECTED/EXECUTED"),
    limit: int = Query(100, ge=1, le=500, description="Limit"),
    db: Session = Depends(get_db)
):
    try:
        query = db.query(PendingOrder).filter(PendingOrder.mode == mode)
        if status:
            query = query.filter(PendingOrder.status == status)
        items = query.order_by(desc(PendingOrder.created_at)).limit(limit).all()
        data = []
        for p in items:
            data.append({
                "id": p.id,
                "symbol": p.symbol,
                "side": p.side,
                "order_type": p.order_type,
                "price": p.price,
                "quantity": p.quantity,
                "status": p.status,
                "reason": p.reason,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
            })
        return {"success": True, "mode": mode, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pending orders: {str(e)}")


@router.post("/pending")
async def create_pending_order(
    payload: PendingOrderCreate,
    mode: str = Query("demo", description="Tryb: demo lub live (na start: tylko demo)"),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Utwórz pending order (web/manual). Na start: tylko DEMO.
    """
    if mode != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be created")

    symbol = (payload.symbol or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    symbol = symbol.replace(" ", "").replace("/", "").replace("-", "").upper()

    side = (payload.side or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="Invalid side. Use BUY or SELL")

    try:
        qty = float(payload.quantity or 0.0)
    except Exception:
        qty = 0.0
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    price = payload.price
    if price is None:
        latest = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(desc(MarketData.timestamp))
            .first()
        )
        if latest and latest.price is not None:
            try:
                price = float(latest.price)
            except Exception:
                price = None
    if price is None:
        raise HTTPException(status_code=400, detail="Price is required (no market data available)")
    try:
        price_f = float(price)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid price")
    if price_f <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")

    p = PendingOrder(
        symbol=symbol,
        side=side,
        order_type="MARKET",
        price=price_f,
        quantity=qty,
        mode="demo",
        status="PENDING",
        reason=(payload.reason or None),
        created_at=datetime.utcnow(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {
        "success": True,
        "data": {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side,
            "quantity": p.quantity,
            "price": p.price,
            "status": p.status,
            "reason": p.reason,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        },
    }


@router.post("/pending/{pending_id}/confirm")
async def confirm_pending_order(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Potwierdź pending order (web/admin). Na start: tylko DEMO.
    """
    p = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pending order not found")
    if (p.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be confirmed")
    if (p.status or "").upper() != "PENDING":
        raise HTTPException(status_code=409, detail="Pending order is not in PENDING status")

    p.status = "CONFIRMED"
    p.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return {"success": True, "data": {"id": p.id, "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}}


@router.post("/pending/{pending_id}/reject")
async def reject_pending_order(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Odrzuć pending order (web/admin). Na start: tylko DEMO.
    """
    p = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pending order not found")
    if (p.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be rejected")
    if (p.status or "").upper() != "PENDING":
        raise HTTPException(status_code=409, detail="Pending order is not in PENDING status")

    p.status = "REJECTED"
    p.confirmed_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return {"success": True, "data": {"id": p.id, "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}}


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
