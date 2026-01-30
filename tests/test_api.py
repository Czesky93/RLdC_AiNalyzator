"""Tests for trading API endpoints."""
import pytest
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base, Trade, PortfolioSnapshot, TradeSide
from database.session import get_db
from datetime import datetime, timedelta

# Set testing mode before importing app
os.environ["TESTING"] = "1"
from web_portal.api.main import app


@pytest.fixture
def sample_trades(db_session):
    """Create sample trades in database."""
    trades = [
        Trade(
            symbol="BTCUSDT",
            side=TradeSide.BUY,
            amount=0.1,
            price=50000.0,
            timestamp=datetime.utcnow() - timedelta(hours=2),
            profit_loss=None
        ),
        Trade(
            symbol="BTCUSDT",
            side=TradeSide.SELL,
            amount=0.1,
            price=51000.0,
            timestamp=datetime.utcnow() - timedelta(hours=1),
            profit_loss=100.0
        ),
        Trade(
            symbol="ETHUSDT",
            side=TradeSide.BUY,
            amount=1.0,
            price=3000.0,
            timestamp=datetime.utcnow(),
            profit_loss=None
        ),
    ]
    for trade in trades:
        db_session.add(trade)
    db_session.commit()
    return trades


@pytest.fixture
def sample_snapshots(db_session):
    """Create sample portfolio snapshots."""
    snapshots = [
        PortfolioSnapshot(
            timestamp=datetime.utcnow() - timedelta(hours=3),
            total_equity_usdt=10000.0,
            cash_balance=10000.0
        ),
        PortfolioSnapshot(
            timestamp=datetime.utcnow() - timedelta(hours=2),
            total_equity_usdt=10500.0,
            cash_balance=5000.0
        ),
        PortfolioSnapshot(
            timestamp=datetime.utcnow() - timedelta(hours=1),
            total_equity_usdt=10100.0,
            cash_balance=10100.0
        ),
    ]
    for snapshot in snapshots:
        db_session.add(snapshot)
    db_session.commit()
    return snapshots


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "endpoints" in data


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_get_trade_history(client, sample_trades):
    """Test getting trade history."""
    response = client.get("/trading/history")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 3
    
    # Should be ordered by timestamp descending (newest first)
    assert data[0]["symbol"] == "ETHUSDT"
    assert data[1]["symbol"] == "BTCUSDT"
    assert data[1]["side"] == "SELL"


def test_get_trade_history_with_limit(client, sample_trades):
    """Test trade history with limit."""
    response = client.get("/trading/history?limit=2")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2


def test_get_trade_history_with_offset(client, sample_trades):
    """Test trade history with offset."""
    response = client.get("/trading/history?offset=1")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2


def test_get_trade_history_with_symbol_filter(client, sample_trades):
    """Test trade history with symbol filter."""
    response = client.get("/trading/history?symbol=BTCUSDT")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2
    assert all(trade["symbol"] == "BTCUSDT" for trade in data)


def test_get_equity_curve(client, sample_snapshots):
    """Test getting equity curve data."""
    response = client.get("/trading/equity")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 3
    
    # Should be ordered by timestamp ascending (oldest first)
    assert data[0]["total_equity_usdt"] == 10000.0
    assert data[1]["total_equity_usdt"] == 10500.0
    assert data[2]["total_equity_usdt"] == 10100.0


def test_get_equity_curve_with_limit(client, sample_snapshots):
    """Test equity curve with limit."""
    response = client.get("/trading/equity?limit=2")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2


def test_get_trading_stats_with_trades(client, sample_trades):
    """Test getting trading statistics."""
    response = client.get("/trading/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total_trades"] == 3
    assert data["winning_trades"] == 1
    assert data["losing_trades"] == 0
    assert data["win_rate"] == 100.0
    assert data["total_pnl"] == 100.0
    assert data["average_pnl"] == 100.0


def test_get_trading_stats_empty_db(client):
    """Test trading stats with empty database."""
    response = client.get("/trading/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total_trades"] == 0
    assert data["winning_trades"] == 0
    assert data["losing_trades"] == 0
    assert data["win_rate"] == 0.0
    assert data["total_pnl"] == 0.0
    assert data["average_pnl"] == 0.0


def test_get_trading_stats_with_losses(client, db_session):
    """Test trading stats with winning and losing trades."""
    trades = [
        Trade(symbol="BTCUSDT", side=TradeSide.SELL, amount=0.1, price=51000.0, profit_loss=100.0),
        Trade(symbol="ETHUSDT", side=TradeSide.SELL, amount=1.0, price=2900.0, profit_loss=-100.0),
        Trade(symbol="BTCUSDT", side=TradeSide.SELL, amount=0.1, price=52000.0, profit_loss=200.0),
    ]
    for trade in trades:
        db_session.add(trade)
    db_session.commit()
    
    response = client.get("/trading/stats")
    assert response.status_code == 200
    
    data = response.json()
    assert data["total_trades"] == 3
    assert data["winning_trades"] == 2
    assert data["losing_trades"] == 1
    assert data["win_rate"] == 66.67
    assert data["total_pnl"] == 200.0
    assert data["average_pnl"] == 66.67
