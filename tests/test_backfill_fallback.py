from backend.database import engine, Base
Base.metadata.create_all(bind=engine)
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

def test_backfill_no_fake_avg_price_for_orphan(monkeypatch):
    monkeypatch.setattr("backend.binance_client.get_binance_client", lambda: DummyClient())
    db = next(get_db())
    # Pozycja bez entry_price i brak trade'ów pozostaje ORPHAN_HOLDING:
    # nie wolno podstawiać aktualnej ceny jako fałszywego entry.
    pos = Position(
        symbol="BTCUSDC",
        side="LONG",
        entry_price=0.0,
        quantity=0.5,
        current_price=40000,
        mode="live"
    )
    db.add(pos)
    db.commit()
    result = backfill_trade_history_from_binance(db, mode="live", limit=10)
    assert result["ok"]
    db.refresh(pos)
    assert pos.entry_price == 0.0
    assert any(s["symbol"] == "BTCUSDC" for s in result["skipped"])
