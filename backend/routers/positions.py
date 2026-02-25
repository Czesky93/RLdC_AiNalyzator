"""
Positions API Router - endpoints dla pozycji (otwarte pozycje)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime

from backend.database import get_db, Position, PendingOrder, MarketData
from backend.auth import require_admin

router = APIRouter()


@router.get("/")
async def get_positions(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    symbol: Optional[str] = Query(None, description="Filtr po symbolu"),
    db: Session = Depends(get_db)
):
    """
    Pobierz listę otwartych pozycji
    """
    try:
        query = db.query(Position).filter(Position.mode == mode)
        if symbol:
            query = query.filter(Position.symbol == symbol)

        positions = query.order_by(desc(Position.opened_at)).all()

        # Bez generatora demo - tylko realne dane

        result = []
        for pos in positions:
            unrealized_pnl = pos.unrealized_pnl or 0.0
            denom = (pos.entry_price * pos.quantity) if pos.entry_price and pos.quantity else 0
            pnl_percent = round((unrealized_pnl / denom * 100) if denom > 0 else 0, 2)

            result.append(
                {
                    "id": pos.id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "quantity": pos.quantity,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_percent": pnl_percent,
                    "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
                    "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
                }
            )

        return {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting positions: {str(e)}")


def _latest_price_for_symbol(db: Session, symbol: str) -> Optional[float]:
    latest = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol)
        .order_by(desc(MarketData.timestamp))
        .first()
    )
    if latest and latest.price is not None:
        try:
            return float(latest.price)
        except Exception:
            return None
    return None


@router.post("/{position_id}/close")
async def close_position(
    position_id: int,
    mode: str = Query("demo", description="Tryb: demo lub live (na start: tylko demo)"),
    quantity: Optional[float] = Query(None, gt=0, description="Ile zamknąć (domyślnie: całość)"),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Utwórz PENDING order do zamknięcia pozycji (DEMO): SELL qty=position.quantity (lub częściowo).
    """
    if mode != "demo":
        raise HTTPException(status_code=403, detail="Only demo positions can be closed")

    pos = db.query(Position).filter(Position.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    if (pos.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo positions can be closed")

    if (pos.side or "").upper() == "SHORT":
        raise HTTPException(status_code=409, detail="Closing SHORT positions is not supported")

    sym = (pos.symbol or "").strip().replace(" ", "").replace("/", "").replace("-", "").upper()
    if not sym:
        raise HTTPException(status_code=400, detail="Invalid position symbol")

    pos_qty = float(pos.quantity or 0.0)
    if pos_qty <= 0:
        raise HTTPException(status_code=409, detail="Position quantity is not positive")

    qty = pos_qty
    if quantity is not None:
        try:
            qty = float(quantity)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid quantity")
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        if qty > pos_qty:
            raise HTTPException(status_code=409, detail="Quantity exceeds position quantity")

    existing = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.mode == "demo",
            PendingOrder.symbol == sym,
            PendingOrder.status.in_(["PENDING", "CONFIRMED"]),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="There is already an active pending order for this symbol")

    price = _latest_price_for_symbol(db, sym)
    if price is None and pos.current_price is not None:
        try:
            price = float(pos.current_price)
        except Exception:
            price = None
    if price is None or price <= 0:
        raise HTTPException(status_code=400, detail="No price available to create close order")

    p = PendingOrder(
        symbol=sym,
        side="SELL",
        order_type="MARKET",
        price=price,
        quantity=qty,
        mode="demo",
        status="PENDING",
        reason=f"Close position #{pos.id}" if qty == pos_qty else f"Partial close position #{pos.id} qty={qty}",
        created_at=datetime.utcnow(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {
        "success": True,
        "data": {
            "pending_id": p.id,
            "position_id": pos.id,
            "symbol": p.symbol,
            "side": p.side,
            "quantity": p.quantity,
            "price": p.price,
            "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        },
    }


@router.post("/close-all")
async def close_all_positions(
    mode: str = Query("demo", description="Tryb: demo lub live (na start: tylko demo)"),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Utwórz PENDING ordery do zamknięcia wszystkich pozycji (DEMO).
    """
    if mode != "demo":
        raise HTTPException(status_code=403, detail="Only demo positions can be closed")

    positions = db.query(Position).filter(Position.mode == "demo").order_by(desc(Position.opened_at)).all()
    if not positions:
        return {"success": True, "data": {"created": 0, "skipped_existing": 0, "skipped_short": 0, "skipped_invalid": 0}}

    created: list[PendingOrder] = []
    skipped_existing = 0
    skipped_short = 0
    skipped_invalid = 0

    for pos in positions:
        if (pos.side or "").upper() == "SHORT":
            skipped_short += 1
            continue

        sym = (pos.symbol or "").strip().replace(" ", "").replace("/", "").replace("-", "").upper()
        if not sym:
            skipped_invalid += 1
            continue

        qty = float(pos.quantity or 0.0)
        if qty <= 0:
            skipped_invalid += 1
            continue

        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "demo",
                PendingOrder.symbol == sym,
                PendingOrder.status.in_(["PENDING", "CONFIRMED"]),
            )
            .first()
        )
        if existing:
            skipped_existing += 1
            continue

        price = _latest_price_for_symbol(db, sym)
        if price is None and pos.current_price is not None:
            try:
                price = float(pos.current_price)
            except Exception:
                price = None
        if price is None or price <= 0:
            skipped_invalid += 1
            continue

        p = PendingOrder(
            symbol=sym,
            side="SELL",
            order_type="MARKET",
            price=price,
            quantity=qty,
            mode="demo",
            status="PENDING",
            reason=f"Close all (position #{pos.id})",
            created_at=datetime.utcnow(),
        )
        db.add(p)
        created.append(p)

    db.commit()
    for p in created:
        db.refresh(p)

    return {
        "success": True,
        "data": {
            "created": len(created),
            "skipped_existing": skipped_existing,
            "skipped_short": skipped_short,
            "skipped_invalid": skipped_invalid,
        },
    }
