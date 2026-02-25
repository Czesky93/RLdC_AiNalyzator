"""
Portfolio API Router - endpoints dla portfolio
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime
import random

from backend.database import get_db, Position
from backend.binance_client import get_binance_client

router = APIRouter()


@router.get("/")
async def get_portfolio(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz portfolio (otwarte pozycje)
    """
    try:
        positions = db.query(Position).filter(
            Position.mode == mode
        ).all()
        
        # Jeśli brak pozycji w demo, zwracamy pusty wynik
        
        # Formatuj dane
        result = []
        total_unrealized_pnl = 0.0
        
        for pos in positions:
            # Aktualizuj current_price (w prawdziwym systemie z market data)
            # current_price = get_current_price(pos.symbol)
            unrealized_pnl = pos.unrealized_pnl or 0.0
            total_unrealized_pnl += unrealized_pnl
            
            result.append({
                "id": pos.id,
                "symbol": pos.symbol,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "quantity": pos.quantity,
                "unrealized_pnl": unrealized_pnl,
                "pnl_percent": round((unrealized_pnl / (pos.entry_price * pos.quantity) * 100) if pos.entry_price > 0 else 0, 2),
                "opened_at": pos.opened_at.isoformat(),
                "updated_at": pos.updated_at.isoformat() if pos.updated_at else pos.opened_at.isoformat()
            })
        
        response = {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2)
        }
        
        # Jeśli LIVE, dołącz salda z Binance
        if mode == "live":
            binance = get_binance_client()
            spot_balances = binance.get_balances()
            simple_earn_account = binance.get_simple_earn_account() or {}
            simple_earn_flexible = binance.get_simple_earn_flexible_positions() or {}
            simple_earn_locked = binance.get_simple_earn_locked_positions() or {}
            futures_balance = binance.get_futures_balance() or []
            futures_account = binance.get_futures_account() or {}
            response["spot_balances"] = spot_balances
            response["simple_earn_account"] = simple_earn_account
            response["simple_earn_flexible"] = simple_earn_flexible
            response["simple_earn_locked"] = simple_earn_locked
            response["futures_balance"] = futures_balance
            response["futures_account"] = futures_account
        
        return response
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio: {str(e)}")


@router.get("/summary")
async def get_portfolio_summary(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Podsumowanie portfolio
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()
        
        if not positions:
            return {
                "success": True,
                "mode": mode,
                "data": {
                    "total_positions": 0,
                    "total_value": 0.0,
                    "total_unrealized_pnl": 0.0,
                    "winning_positions": 0,
                    "losing_positions": 0
                }
            }
        
        total_value = 0.0
        total_unrealized_pnl = 0.0
        winning = 0
        losing = 0
        
        for pos in positions:
            value = pos.entry_price * pos.quantity
            total_value += value
            
            pnl = pos.unrealized_pnl or 0.0
            total_unrealized_pnl += pnl
            
            if pnl > 0:
                winning += 1
            elif pnl < 0:
                losing += 1
        
        return {
            "success": True,
            "mode": mode,
            "data": {
                "total_positions": len(positions),
                "total_value": round(total_value, 2),
                "total_unrealized_pnl": round(total_unrealized_pnl, 2),
                "winning_positions": winning,
                "losing_positions": losing,
                "win_rate": round((winning / len(positions) * 100) if len(positions) > 0 else 0, 2)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting portfolio summary: {str(e)}")
