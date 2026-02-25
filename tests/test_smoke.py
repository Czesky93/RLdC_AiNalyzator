import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `import backend` works when running pytest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"

from fastapi.testclient import TestClient
from backend.app import app


client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "healthy"


def test_market_summary():
    resp = client.get("/api/market/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_positions():
    resp = client.get("/api/positions?mode=demo")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True


def test_signals_top5():
    resp = client.get("/api/signals/top5")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
