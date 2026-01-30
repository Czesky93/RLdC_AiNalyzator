"""Tests for paper trader."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Trade, PortfolioSnapshot, TradeSide
from decision_engine.paper_trader import PaperTrader


@pytest.fixture
def db_session():
    """Create a test database session."""
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


@pytest.fixture
def paper_trader(db_session):
    """Create a paper trader instance."""
    return PaperTrader(db_session, initial_balance=10000.0)


def test_paper_trader_initialization(paper_trader, db_session):
    """Test paper trader initializes correctly."""
    assert paper_trader.cash_balance == 10000.0
    assert len(paper_trader.positions) == 0
    
    # Should have created initial snapshot
    snapshots = db_session.query(PortfolioSnapshot).all()
    assert len(snapshots) == 1
    assert snapshots[0].total_equity_usdt == 10000.0


def test_execute_buy_order(paper_trader, db_session):
    """Test executing a buy order."""
    trade = paper_trader.execute_order(
        symbol="BTCUSDT",
        side="BUY",
        amount=0.1,
        price=50000.0
    )
    
    assert trade.symbol == "BTCUSDT"
    assert trade.side == TradeSide.BUY
    assert trade.amount == 0.1
    assert trade.price == 50000.0
    
    # Check internal state
    assert paper_trader.cash_balance == 5000.0  # 10000 - (0.1 * 50000)
    assert paper_trader.positions["BTCUSDT"] == 0.1
    
    # Check database
    trades = db_session.query(Trade).all()
    assert len(trades) == 1


def test_execute_sell_order(paper_trader, db_session):
    """Test executing a sell order."""
    # First buy
    paper_trader.execute_order("BTCUSDT", "BUY", 0.1, 50000.0)
    
    # Then sell
    trade = paper_trader.execute_order(
        symbol="BTCUSDT",
        side="SELL",
        amount=0.1,
        price=51000.0,
        profit_loss=100.0
    )
    
    assert trade.side == TradeSide.SELL
    assert trade.profit_loss == 100.0
    
    # Check internal state
    assert paper_trader.cash_balance == 10100.0  # 5000 + (0.1 * 51000)
    assert "BTCUSDT" not in paper_trader.positions
    
    # Check database
    trades = db_session.query(Trade).all()
    assert len(trades) == 2


def test_insufficient_funds(paper_trader):
    """Test that insufficient funds raises error."""
    with pytest.raises(ValueError, match="Insufficient funds"):
        paper_trader.execute_order("BTCUSDT", "BUY", 1.0, 50000.0)


def test_insufficient_position(paper_trader):
    """Test that insufficient position raises error."""
    with pytest.raises(ValueError, match="Insufficient"):
        paper_trader.execute_order("BTCUSDT", "SELL", 0.1, 50000.0)


def test_invalid_side(paper_trader):
    """Test that invalid side raises error."""
    with pytest.raises(ValueError, match="Invalid side"):
        paper_trader.execute_order("BTCUSDT", "HOLD", 0.1, 50000.0)


def test_step_saves_snapshot(paper_trader, db_session):
    """Test that step saves portfolio snapshots."""
    initial_snapshots = db_session.query(PortfolioSnapshot).count()
    
    paper_trader.step()
    
    snapshots = db_session.query(PortfolioSnapshot).count()
    assert snapshots == initial_snapshots + 1


def test_get_portfolio_value(paper_trader):
    """Test calculating portfolio value."""
    paper_trader.execute_order("BTCUSDT", "BUY", 0.1, 50000.0)
    paper_trader.execute_order("ETHUSDT", "BUY", 1.0, 3000.0)
    
    current_prices = {
        "BTCUSDT": 52000.0,
        "ETHUSDT": 3100.0
    }
    
    value = paper_trader.get_portfolio_value(current_prices)
    # cash: 2000, BTC: 0.1 * 52000 = 5200, ETH: 1.0 * 3100 = 3100
    assert value == 10300.0
