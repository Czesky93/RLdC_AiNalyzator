"""
Positions API Router - endpoints dla pozycji (otwarte pozycje)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime
import random

from backend.database import get_db, Position

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
