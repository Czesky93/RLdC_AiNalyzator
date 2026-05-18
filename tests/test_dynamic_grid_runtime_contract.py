"""Contract tests for dynamic_grid runtime integration."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_db():
    from backend.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_cls = sessionmaker(bind=engine)
    return session_cls()


def test_grid_state_store_roundtrip():
    from backend.trading.grid_state_store import (
        load_active_grid_plans,
        save_active_grid_plans,
    )

    db = _make_db()
    try:
        plans = {
            "BTCUSDC": {
                "symbol": "BTCUSDC",
                "lower": 76000.0,
                "upper": 79000.0,
                "grid_count": 12,
            }
        }

        save_active_grid_plans(db, plans)
        db.commit()

        loaded = load_active_grid_plans(db)
        assert loaded["BTCUSDC"]["grid_count"] == 12
        assert loaded["BTCUSDC"]["lower"] == 76000.0
    finally:
        db.close()


def test_grid_pending_order_uses_real_model_fields():
    from backend.database import PendingOrder
    from backend.trading.pending_order_factory import create_pending_order_from_grid

    order = create_pending_order_from_grid(
        symbol="BTCUSDC",
        side="BUY",
        quantity=0.001,
        price=76000.0,
        mode="demo",
        reason="grid level buy",
        plan_payload={"grid_id": "test"},
    )

    assert isinstance(order, PendingOrder)
    assert order.symbol == "BTCUSDC"
    assert order.side == "BUY"
    assert order.order_type == "MARKET"
    assert order.status == "PENDING_CONFIRMED"
    assert order.strategy_name == "dynamic_grid"


def test_runtime_config_contains_dynamic_grid_keys():
    from backend.runtime_settings import get_runtime_config

    db = _make_db()
    try:
        cfg = get_runtime_config(db)

        assert "trading_system" in cfg
        assert "dynamic_grid_enabled" in cfg
        assert "dynamic_grid_top_n" in cfg
        assert "dynamic_grid_quote_asset" in cfg
    finally:
        db.close()


def test_build_dynamic_grid_plans_does_not_fail_on_import():
    from backend.collector import DataCollector
    from backend.runtime_settings import upsert_overrides

    db = _make_db()
    try:
        upsert_overrides(
            db,
            {
                "trading_system": "dynamic_grid",
                "dynamic_grid_enabled": "true",
            },
        )

        collector = object.__new__(DataCollector)
        collector.watchlist = ["BTCUSDC"]
        collector.binance = None

        result = collector._build_dynamic_grid_plans(db)
        assert result == 0
    finally:
        db.close()


def test_dynamic_grid_runtime_skips_legacy_entry(monkeypatch):
    from backend.collector import DataCollector

    collector = object.__new__(DataCollector)
    called = {"entries": 0}

    def fake_screen(*args, **kwargs):
        called["entries"] += 1
        return 1

    monkeypatch.setattr(collector, "_screen_entry_candidates", fake_screen)

    assert collector._is_dynamic_grid_selected(
        {"trading_system": "dynamic_grid", "dynamic_grid_enabled": False}
    )
    assert not collector._is_dynamic_grid_runtime(
        {"trading_system": "dynamic_grid", "dynamic_grid_enabled": False}
    )
    assert collector._is_dynamic_grid_runtime(
        {"trading_system": "dynamic_grid", "dynamic_grid_enabled": True}
    )
    assert not collector._is_dynamic_grid_runtime(
        {"trading_system": "legacy", "dynamic_grid_enabled": True}
    )
    assert called["entries"] == 0
