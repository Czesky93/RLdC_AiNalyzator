from backend.database import Base, Position, SessionLocal, engine, init_db
from backend.portfolio_reconcile import fetch_my_trades_paginated
from backend.routers import portfolio as portfolio_router
from backend.runtime_settings import get_symbol_tier_or_default


Base.metadata.create_all(bind=engine)


def _reset_positions(db):
    db.query(Position).delete()
    db.commit()


def test_live_portfolio_classifies_cash_orphan_and_dust(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        _reset_positions(db)

        def fake_live_portfolio(_db):
            return {
                "error": None,
                "total_equity_eur": 1165.90,
                "free_cash_eur": 691.40,
                "spot_positions": [
                    {
                        "asset": "EUR",
                        "total": 560.50,
                        "free": 560.50,
                        "locked": 0,
                        "price_eur": 1,
                        "price_source": "stable_eur",
                        "value_eur": 560.50,
                        "free_value_eur": 560.50,
                        "weight_pct": 45.7,
                    },
                    {
                        "asset": "USDC",
                        "total": 153.60,
                        "free": 153.60,
                        "locked": 0,
                        "price_eur": 0.852,
                        "price_source": "usdt_conv",
                        "value_eur": 130.90,
                        "free_value_eur": 130.90,
                        "weight_pct": 10.7,
                    },
                    {
                        "asset": "APE",
                        "total": 314.560883,
                        "free": 314.560883,
                        "locked": 0,
                        "price_eur": 1.508,
                        "price_source": "market_data",
                        "value_eur": 474.36,
                        "free_value_eur": 474.36,
                        "weight_pct": 38.7,
                    },
                    {
                        "asset": "ETH",
                        "total": 0.00007207,
                        "free": 0.00007207,
                        "locked": 0,
                        "price_eur": 1927.0,
                        "price_source": "market_data",
                        "value_eur": 0.1389,
                        "free_value_eur": 0.1389,
                        "weight_pct": 0,
                    },
                ],
                "unpriced_assets": [],
                "assets_count": 4,
                "unpriced_count": 0,
                "eur_per_usdt": 0.852,
            }

        monkeypatch.setattr(
            portfolio_router, "_build_live_spot_portfolio", fake_live_portfolio
        )
        data = portfolio_router.get_portfolio_wealth(mode="live", db=db)

        assert data["total_equity"] == 1165.90
        assert data["free_cash"] == 691.40
        assert data["positions_value"] == 474.50
        assert data["positions_value"] == round(474.36 + 0.1389, 2)
        assert data["total_equity"] == round(data["free_cash"] + data["positions_value"], 2)
        assert data["positions_count"] == 0
        assert data["orphan_holdings_count"] == 1
        assert data["dust_positions_count"] == 1
        assert data["cash_assets_count"] == 2
        assert {i["display_symbol"] for i in data["cash"]} == {"EUR", "USDC"}
        assert not any(i["display_symbol"] in {"/EUR", "/USDC"} for i in data["items"])

        ape = next(i for i in data["items"] if i["asset"] == "APE")
        eth = next(i for i in data["items"] if i["asset"] == "ETH")
        assert ape["classification"] == "ORPHAN_HOLDING"
        assert ape["pnl_eur"] is None
        assert ape["requires_backfill"] is True
        assert eth["classification"] == "DUST_RESIDUAL"
    finally:
        db.close()


def test_symbol_without_manual_tier_gets_default_market():
    tier = get_symbol_tier_or_default("PEPEUSDC", {})
    assert tier["tier"] == "DEFAULT_MARKET"
    assert tier["risk_scale"] == 1.0


def test_backfill_fetches_more_than_1000_trades_by_from_id():
    class DummyClient:
        def __init__(self):
            self.calls = []

        def get_my_trades(self, symbol, limit=1000, from_id=None):
            self.calls.append(from_id)
            start = int(from_id or 1)
            size = 1000 if start == 1 else 5
            return [
                {
                    "id": i,
                    "time": 1710000000000 + i,
                    "isBuyer": True,
                    "qty": "1",
                    "price": "1",
                }
                for i in range(start, start + size)
            ]

    client = DummyClient()
    trades = fetch_my_trades_paginated(client, "TESTUSDC", limit=1000, max_pages=3)
    assert len(trades) == 1005
    assert client.calls == [None, 1001]
