"""Trading API routes for querying trade history and portfolio data."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from database.session import get_db
from database.models import Trade, PortfolioSnapshot, TradeSide

router = APIRouter(prefix="/trading", tags=["trading"])


# Pydantic models for API responses
class TradeResponse(BaseModel):
    """Response model for trade data."""
    id: int
    symbol: str
    side: str
    amount: float
    price: float
    timestamp: datetime
    profit_loss: Optional[float]

    class Config:
        from_attributes = True


class PortfolioSnapshotResponse(BaseModel):
    """Response model for portfolio snapshot data."""
    id: int
    timestamp: datetime
    total_equity_usdt: float
    cash_balance: float

    class Config:
        from_attributes = True


class TradingStatsResponse(BaseModel):
    """Response model for trading statistics."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    average_pnl: float


@router.get("/history", response_model=List[TradeResponse])
def get_trade_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of trades to return"),
    offset: int = Query(default=0, ge=0, description="Number of trades to skip"),
    symbol: Optional[str] = Query(default=None, description="Filter by trading symbol"),
    db: Session = Depends(get_db)
):
    """
    Get trade history with pagination.
    
    Args:
        limit: Maximum number of trades to return (1-1000)
        offset: Number of trades to skip for pagination
        symbol: Optional symbol filter
        db: Database session
        
    Returns:
        List of trades ordered by timestamp (newest first)
    """
    query = db.query(Trade)
    
    if symbol:
        query = query.filter(Trade.symbol == symbol)
    
    trades = query.order_by(Trade.timestamp.desc()).offset(offset).limit(limit).all()
    
    # Convert to response format
    return [
        TradeResponse(
            id=trade.id,
            symbol=trade.symbol,
            side=trade.side.value,
            amount=trade.amount,
            price=trade.price,
            timestamp=trade.timestamp,
            profit_loss=trade.profit_loss
        )
        for trade in trades
    ]


@router.get("/equity", response_model=List[PortfolioSnapshotResponse])
def get_equity_curve(
    limit: int = Query(default=1000, ge=1, le=10000, description="Maximum number of snapshots to return"),
    offset: int = Query(default=0, ge=0, description="Number of snapshots to skip"),
    db: Session = Depends(get_db)
):
    """
    Get portfolio equity curve data for charting.
    
    Args:
        limit: Maximum number of snapshots to return (1-10000)
        offset: Number of snapshots to skip for pagination
        db: Database session
        
    Returns:
        List of portfolio snapshots ordered by timestamp (oldest first)
    """
    snapshots = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.timestamp.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    return [
        PortfolioSnapshotResponse(
            id=snapshot.id,
            timestamp=snapshot.timestamp,
            total_equity_usdt=snapshot.total_equity_usdt,
            cash_balance=snapshot.cash_balance
        )
        for snapshot in snapshots
    ]


@router.get("/stats", response_model=TradingStatsResponse)
def get_trading_stats(db: Session = Depends(get_db)):
    """
    Calculate trading statistics including win rate and PnL.
    
    Args:
        db: Database session
        
    Returns:
        Trading statistics
    """
    # Get total trades count
    total_trades = db.query(func.count(Trade.id)).scalar() or 0
    
    # Get winning and losing trades (only count trades with profit_loss data)
    winning_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.profit_loss > 0)
        .scalar() or 0
    )
    
    losing_trades = (
        db.query(func.count(Trade.id))
        .filter(Trade.profit_loss < 0)
        .scalar() or 0
    )
    
    # Calculate win rate
    trades_with_pnl = winning_trades + losing_trades
    win_rate = (winning_trades / trades_with_pnl * 100) if trades_with_pnl > 0 else 0.0
    
    # Get total and average PnL
    total_pnl = db.query(func.sum(Trade.profit_loss)).scalar() or 0.0
    average_pnl = (total_pnl / trades_with_pnl) if trades_with_pnl > 0 else 0.0
    
    return TradingStatsResponse(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=round(win_rate, 2),
        total_pnl=round(total_pnl, 2),
        average_pnl=round(average_pnl, 2)
    )
