#!/usr/bin/env python
"""
End-to-end integration test for the entire system.
This validates the complete workflow from paper trading to API querying.
"""
import sys
import os
import time
import requests
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.session import init_db, SessionLocal
from database.models import Trade, PortfolioSnapshot
from decision_engine.paper_trader import PaperTrader


def test_database_layer():
    """Test 1: Database layer works."""
    print("✓ Test 1: Database layer initialization")
    init_db()
    db = SessionLocal()
    
    # Clear existing data
    db.query(Trade).delete()
    db.query(PortfolioSnapshot).delete()
    db.commit()
    
    assert db.query(Trade).count() == 0
    assert db.query(PortfolioSnapshot).count() == 0
    db.close()
    print("  ✓ Database tables created and empty")


def test_paper_trader():
    """Test 2: Paper trader with DB persistence."""
    print("\n✓ Test 2: Paper trader execution")
    db = SessionLocal()
    trader = PaperTrader(db, initial_balance=10000.0)
    
    # Execute trades
    trader.execute_order("BTCUSDT", "BUY", 0.1, 50000.0)
    trader.step({"BTCUSDT": 51000.0})
    trader.execute_order("BTCUSDT", "SELL", 0.1, 52000.0, profit_loss=200.0)
    trader.step({})
    
    # Verify trades persisted
    trade_count = db.query(Trade).count()
    snapshot_count = db.query(PortfolioSnapshot).count()
    
    assert trade_count == 2, f"Expected 2 trades, got {trade_count}"
    assert snapshot_count == 3, f"Expected 3 snapshots, got {snapshot_count}"
    assert trader.cash_balance == 10200.0, f"Expected $10200, got ${trader.cash_balance}"
    
    db.close()
    print(f"  ✓ Executed 2 trades, saved 3 snapshots")
    print(f"  ✓ Final balance: ${trader.cash_balance:.2f}")


def test_api_server():
    """Test 3: API server endpoints."""
    print("\n✓ Test 3: API server endpoints")
    
    # Give server time to start (should already be running)
    time.sleep(1)
    
    base_url = "http://localhost:8000"
    
    # Test root endpoint
    response = requests.get(f"{base_url}/", timeout=5)
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    print("  ✓ Root endpoint works")
    
    # Test health check
    response = requests.get(f"{base_url}/health", timeout=5)
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    print("  ✓ Health check works")
    
    # Test trading history
    response = requests.get(f"{base_url}/trading/history", timeout=5)
    assert response.status_code == 200
    trades = response.json()
    assert isinstance(trades, list)
    assert len(trades) >= 2  # At least our test trades
    print(f"  ✓ Trading history endpoint (returned {len(trades)} trades)")
    
    # Test equity curve
    response = requests.get(f"{base_url}/trading/equity", timeout=5)
    assert response.status_code == 200
    snapshots = response.json()
    assert isinstance(snapshots, list)
    assert len(snapshots) >= 3  # At least our test snapshots
    print(f"  ✓ Equity curve endpoint (returned {len(snapshots)} snapshots)")
    
    # Test trading stats
    response = requests.get(f"{base_url}/trading/stats", timeout=5)
    assert response.status_code == 200
    stats = response.json()
    assert "total_trades" in stats
    assert "win_rate" in stats
    assert "total_pnl" in stats
    assert stats["total_trades"] >= 2
    print(f"  ✓ Trading stats endpoint")
    print(f"    - Total trades: {stats['total_trades']}")
    print(f"    - Win rate: {stats['win_rate']}%")
    print(f"    - Total P/L: ${stats['total_pnl']:.2f}")


def main():
    """Run all integration tests."""
    print("=" * 60)
    print("End-to-End Integration Test")
    print("=" * 60)
    
    try:
        test_database_layer()
        test_paper_trader()
        test_api_server()
        
        print("\n" + "=" * 60)
        print("✅ ALL INTEGRATION TESTS PASSED!")
        print("=" * 60)
        print("\nThe complete system is working:")
        print("  • Database layer: Persistent storage with SQLAlchemy")
        print("  • Paper trader: Trade execution with DB persistence")
        print("  • REST API: All endpoints functioning correctly")
        print("\nReady for production deployment! 🚀")
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\n❌ API SERVER NOT RUNNING: {e}")
        print("Please start the server first: python -m web_portal.api.main")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
