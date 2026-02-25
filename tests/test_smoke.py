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
from backend.database import PendingOrder, SessionLocal


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


def test_control_state_no_admin_token(client):
    resp = client.get("/api/control/state")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("success") is True
    data = payload.get("data") or {}
    assert "demo_trading_enabled" in data
