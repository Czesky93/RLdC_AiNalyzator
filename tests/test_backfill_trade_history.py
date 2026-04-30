import pytest
from backend.portfolio_reconcile import backfill_trade_history_from_binance
from backend.database import get_db, Position

class DummyClient:
    def get_balances(self):
        return [
            {"asset": "BTC", "total": 0.5},
            {"asset": "ETH", "total": 1.0},
        ]
    def get_my_trades(self, symbol, limit=1000):
        if symbol == "BTCUSDC":
            return [
                {"isBuyer": True, "qty": "0.5", "price": "40000", "time": 1710000000000},
            ]
        if symbol == "ETHUSDC":
            return []
        return []

def test_backfill_trade_history(monkeypatch):
    # Patch binance_client
    monkeypatch.setattr("backend.binance_client.get_binance_client", lambda: DummyClient())
    db = next(get_db())
    # Dodaj pozycję bez entry_price
    pos = Position(symbol="BTCUSDC", mode="live", quantity=0.5, current_price=40000, entry_price=None)
    db.add(pos)
    db.commit()
    # Backfill
    result = backfill_trade_history_from_binance(db, mode="live", limit=10)
    assert result["ok"]
    assert any(u["symbol"] == "BTCUSDC" for u in result["updated"])
    # Fallback: ETHUSDC nie ma trade'ów, entry_price nie powinno być ustawione
    pos2 = Position(symbol="ETHUSDC", mode="live", quantity=1.0, current_price=2000, entry_price=None)
    db.add(pos2)
    db.commit()
    result2 = backfill_trade_history_from_binance(db, mode="live", limit=10)
    assert result2["ok"]
    assert any(s["symbol"] == "ETHUSDC" for s in result2["skipped"])
