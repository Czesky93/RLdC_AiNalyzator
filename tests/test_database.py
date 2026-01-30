"""Tests for database models."""
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Trade, PortfolioSnapshot, TradeSide


@pytest.fixture
def db_session():
    """Create a test database session."""
    # Use in-memory SQLite for testing
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def test_trade_creation(db_session):
    """Test creating a trade record."""
    trade = Trade(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        amount=0.5,
        price=50000.0,
        profit_loss=None
    )
    db_session.add(trade)
    db_session.commit()
    
    # Query back
    saved_trade = db_session.query(Trade).first()
    assert saved_trade is not None
    assert saved_trade.symbol == "BTCUSDT"
    assert saved_trade.side == TradeSide.BUY
    assert saved_trade.amount == 0.5
    assert saved_trade.price == 50000.0
    assert saved_trade.profit_loss is None


def test_trade_with_profit_loss(db_session):
    """Test creating a trade with profit/loss."""
    trade = Trade(
        symbol="ETHUSDT",
        side=TradeSide.SELL,
        amount=2.0,
        price=3000.0,
        profit_loss=150.75
    )
    db_session.add(trade)
    db_session.commit()
    
    saved_trade = db_session.query(Trade).first()
    assert saved_trade.profit_loss == 150.75


def test_portfolio_snapshot_creation(db_session):
    """Test creating a portfolio snapshot."""
    snapshot = PortfolioSnapshot(
        total_equity_usdt=15000.0,
        cash_balance=10000.0
    )
    db_session.add(snapshot)
    db_session.commit()
    
    saved_snapshot = db_session.query(PortfolioSnapshot).first()
    assert saved_snapshot is not None
    assert saved_snapshot.total_equity_usdt == 15000.0
    assert saved_snapshot.cash_balance == 10000.0
    assert saved_snapshot.timestamp is not None


def test_multiple_trades(db_session):
    """Test creating multiple trades."""
    trades = [
        Trade(symbol="BTCUSDT", side=TradeSide.BUY, amount=0.1, price=50000.0),
        Trade(symbol="ETHUSDT", side=TradeSide.BUY, amount=1.0, price=3000.0),
        Trade(symbol="BTCUSDT", side=TradeSide.SELL, amount=0.1, price=51000.0, profit_loss=100.0),
    ]
    
    for trade in trades:
        db_session.add(trade)
    db_session.commit()
    
    saved_trades = db_session.query(Trade).all()
    assert len(saved_trades) == 3
