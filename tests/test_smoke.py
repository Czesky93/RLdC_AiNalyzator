import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root is on sys.path so `import backend` works when running pytest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ["DEMO_INITIAL_BALANCE"] = "10000"
os.environ["DEMO_TRADING_ENABLED"] = "true"
os.environ["WS_ENABLED"] = "true"
os.environ["MAX_CERTAINTY_MODE"] = "false"

# Isolated DB per test run
_tmp_db = tempfile.NamedTemporaryFile(prefix="rldc_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from fastapi.testclient import TestClient
from backend.app import app
from backend.database import PendingOrder, SessionLocal, Position, MarketData


import pytest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"


def test_market_summary(client):
    resp = client.get("/api/market/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_positions(client):
    resp = client.get("/api/positions?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_signals_top5(client):
    resp = client.get("/api/signals/top5")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_account_summary_demo(client):
    resp = client.get("/api/account/summary?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("mode") == "demo"
    assert abs(float(data.get("equity") or 0.0) - 10000.0) < 1e-6


def test_pending_confirm_reject_demo(client):
    # create pending order
    db = SessionLocal()
    try:
        p = PendingOrder(
            symbol="BTCEUR",
            side="BUY",
            order_type="MARKET",
            price=100.0,
            quantity=0.1,
            mode="demo",
            status="PENDING",
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = int(p.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid}/confirm")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "CONFIRMED"

    # reject needs a fresh PENDING record
    db = SessionLocal()
    try:
        p2 = PendingOrder(
            symbol="ETHEUR",
            side="SELL",
            order_type="MARKET",
            price=50.0,
            quantity=1.0,
            mode="demo",
            status="PENDING",
        )
        db.add(p2)
        db.commit()
        db.refresh(p2)
        pid2 = int(p2.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid2}/reject")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "REJECTED"

    # cancel needs a fresh PENDING record
    db = SessionLocal()
    try:
        p3 = PendingOrder(
            symbol="XRPEUR",
            side="BUY",
            order_type="MARKET",
            price=1.0,
            quantity=10.0,
            mode="demo",
            status="PENDING",
        )
        db.add(p3)
        db.commit()
        db.refresh(p3)
        pid3 = int(p3.id)
    finally:
        db.close()

    resp = client.post(f"/api/orders/pending/{pid3}/cancel")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("status") == "REJECTED"


def test_pending_create_demo(client):
    resp = client.post(
        "/api/orders/pending?mode=demo",
        json={"symbol": "BTC/EUR", "side": "BUY", "quantity": 0.01, "price": 100.0, "reason": "manual"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("status") == "PENDING"
    assert data.get("symbol") == "BTCEUR"


def test_control_state_no_admin_token(client):
    resp = client.get("/api/control/state")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert "demo_trading_enabled" in data


def test_control_state_setters(client):
    resp = client.post("/api/control/state", json={"demo_trading_enabled": False})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    assert (payload.get("data") or {}).get("demo_trading_enabled") is False

    resp = client.post("/api/control/state", json={"watchlist": ["BTC/EUR", "WLFI/EUR"]})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert data.get("watchlist_source") == "override"
    assert isinstance(data.get("watchlist_override"), list)
    # normalized: strip "/" and "-" and upper
    assert "BTCEUR" in data.get("watchlist_override")


def test_close_position_creates_pending_sell(client):
    db = SessionLocal()
    try:
        md = MarketData(symbol="CLOSE1EUR", price=123.45)
        pos = Position(
            symbol="CLOSE1EUR",
            side="LONG",
            entry_price=120.0,
            quantity=0.5,
            current_price=123.45,
            unrealized_pnl=1.72,
            mode="demo",
        )
        db.add(md)
        db.add(pos)
        db.commit()
        db.refresh(pos)
        pid = int(pos.id)
    finally:
        db.close()

    resp = client.post(f"/api/positions/{pid}/close?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True

    db = SessionLocal()
    try:
        p = (
            db.query(PendingOrder)
            .filter(PendingOrder.symbol == "CLOSE1EUR", PendingOrder.mode == "demo")
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        assert p is not None
        assert p.status == "PENDING"
        assert p.side == "SELL"
        assert abs(float(p.quantity) - 0.5) < 1e-9
    finally:
        db.close()


def test_partial_close_position_creates_pending_sell_qty(client):
    db = SessionLocal()
    try:
        db.add(MarketData(symbol="CLOSE4EUR", price=50.0))
        pos = Position(
            symbol="CLOSE4EUR",
            side="LONG",
            entry_price=40.0,
            quantity=1.0,
            current_price=50.0,
            unrealized_pnl=10.0,
            mode="demo",
        )
        db.add(pos)
        db.commit()
        db.refresh(pos)
        pid = int(pos.id)
    finally:
        db.close()

    resp = client.post(f"/api/positions/{pid}/close?mode=demo&quantity=0.25")
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        p = (
            db.query(PendingOrder)
            .filter(PendingOrder.symbol == "CLOSE4EUR", PendingOrder.mode == "demo")
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        assert p is not None
        assert p.side == "SELL"
        assert abs(float(p.quantity) - 0.25) < 1e-9
    finally:
        db.close()


def test_close_all_positions_creates_multiple_pending(client):
    db = SessionLocal()
    try:
        db.add(MarketData(symbol="CLOSE2EUR", price=10.0))
        db.add(MarketData(symbol="CLOSE3EUR", price=20.0))
        db.add(
            Position(
                symbol="CLOSE2EUR",
                side="LONG",
                entry_price=9.0,
                quantity=1.0,
                current_price=10.0,
                unrealized_pnl=1.0,
                mode="demo",
            )
        )
        db.add(
            Position(
                symbol="CLOSE3EUR",
                side="LONG",
                entry_price=19.0,
                quantity=2.0,
                current_price=20.0,
                unrealized_pnl=2.0,
                mode="demo",
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/positions/close-all?mode=demo")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert int(data.get("created") or 0) >= 2

    db = SessionLocal()
    try:
        syms = {p.symbol for p in db.query(PendingOrder).filter(PendingOrder.mode == "demo").all()}
        assert "CLOSE2EUR" in syms
        assert "CLOSE3EUR" in syms
    finally:
        db.close()
