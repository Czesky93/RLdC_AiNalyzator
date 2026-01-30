"""SQLAlchemy models for trading data."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()


class TradeSide(enum.Enum):
    """Enum for trade side."""
    BUY = "BUY"
    SELL = "SELL"


class Trade(Base):
    """Model for individual trades."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(Enum(TradeSide), nullable=False)
    amount = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    profit_loss = Column(Float, nullable=True)

    def __repr__(self):
        return f"<Trade(id={self.id}, symbol={self.symbol}, side={self.side.value}, amount={self.amount}, price={self.price})>"


class PortfolioSnapshot(Base):
    """Model for portfolio snapshots over time."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    total_equity_usdt = Column(Float, nullable=False)
    cash_balance = Column(Float, nullable=False)

    def __repr__(self):
        return f"<PortfolioSnapshot(id={self.id}, timestamp={self.timestamp}, total_equity_usdt={self.total_equity_usdt})>"
