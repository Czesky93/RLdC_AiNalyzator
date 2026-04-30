import pytest
from backend.portfolio_reconcile import backfill_trade_history_from_binance
from backend.database import get_db, Position

class DummyClient:
    def get_balances(self):
        return [
            {"asset": "BTC", "total": 0.5},
        ]
    def get_my_trades(self, symbol, limit=1000):
        return []

def test_backfill_fallback_avg_price(monkeypatch):
    monkeypatch.setattr("backend.binance_client.get_binance_client", lambda: DummyClient())
    db = next(get_db())
    # Pozycja bez entry_price, brak trade'ów, fallback na avg_price
    pos = Position(symbol="BTCUSDC", mode="live", quantity=0.5, current_price=40000, entry_price=None)
    db.add(pos)
    db.commit()
    result = backfill_trade_history_from_binance(db, mode="live", limit=10)
    assert result["ok"]
    assert any(u.get("fallback") for u in result["updated"])
