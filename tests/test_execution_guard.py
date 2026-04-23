from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp_db = tempfile.NamedTemporaryFile(
    prefix="rldc_exec_guard_", suffix=".db", delete=False
)
_tmp_db.close()
_TEST_DB_URL = f"sqlite:///{_tmp_db.name}"

from backend.collector import DataCollector
from backend.database import Base, PendingOrder, RuntimeSetting, utc_now_naive

engine = create_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def test_execution_enabled_false_blocks_all_modes_with_reason_code():
    db = TestingSessionLocal()
    try:
        db.add(
            PendingOrder(
                symbol="ETHUSDC",
                side="BUY",
                order_type="MARKET",
                quantity=0.02,
                mode="live",
                status="PENDING_CONFIRMED",
            )
        )
        db.add(
            PendingOrder(
                symbol="BTCUSDC",
                side="SELL",
                order_type="MARKET",
                quantity=0.01,
                mode="demo",
                status="CONFIRMED",
            )
        )
        db.commit()

        reasons = []

        collector = DataCollector.__new__(DataCollector)
        collector.binance = None
        collector._runtime_context = lambda _db: {
            "config": {
                "allow_live_trading": True,
                "trading_mode": "live",
                "execution_enabled": False,
            },
            "snapshot_id": "pytest",
        }
        collector._trace_decision = lambda _db, **kwargs: reasons.append(
            kwargs.get("reason_code")
        )
        collector._acquire_inflight_slot = lambda *args, **kwargs: True
        collector._release_inflight_slot = lambda *args, **kwargs: None

        collector._execute_confirmed_pending_orders(db)

        assert reasons
        assert all(r == "execution_globally_disabled" for r in reasons)

        live_pending = (
            db.query(PendingOrder).filter(PendingOrder.symbol == "ETHUSDC").first()
        )
        demo_pending = (
            db.query(PendingOrder).filter(PendingOrder.symbol == "BTCUSDC").first()
        )
        assert live_pending is not None
        assert demo_pending is not None
        assert live_pending.status in ("PENDING_CONFIRMED", "CONFIRMED")
        assert demo_pending.status in ("PENDING_CONFIRMED", "CONFIRMED")
    finally:
        db.close()


def test_pending_timeout_cleanup_marks_expired():
    db = TestingSessionLocal()
    try:
        db.add(
            PendingOrder(
                symbol="ETHUSDC",
                side="BUY",
                order_type="MARKET",
                quantity=0.02,
                mode="demo",
                status="PENDING_CREATED",
                expires_at=utc_now_naive().replace(year=utc_now_naive().year - 1),
            )
        )
        db.commit()

        collector = DataCollector.__new__(DataCollector)
        collector.binance = None
        collector._runtime_context = lambda _db: {
            "config": {
                "allow_live_trading": False,
                "trading_mode": "demo",
                "execution_enabled": True,
            },
            "snapshot_id": "pytest",
        }
        collector._trace_decision = lambda *args, **kwargs: None
        collector._acquire_inflight_slot = lambda *args, **kwargs: True
        collector._release_inflight_slot = lambda *args, **kwargs: None

        collector._execute_confirmed_pending_orders(db)

        pending = db.query(PendingOrder).filter(PendingOrder.symbol == "ETHUSDC").first()
        assert pending is not None
        assert pending.status == "EXPIRED"
    finally:
        db.close()


def test_create_pending_order_respects_manual_confirmation():
    db = TestingSessionLocal()
    try:
        db.query(RuntimeSetting).filter(
            RuntimeSetting.key.in_(["enable_auto_execute", "require_manual_confirmation"])
        ).delete(synchronize_session=False)
        db.add(RuntimeSetting(key="enable_auto_execute", value="true"))
        db.add(RuntimeSetting(key="require_manual_confirmation", value="true"))
        db.commit()

        collector = DataCollector.__new__(DataCollector)
        collector.binance = None
        collector._active_mode = "demo"

        pending_id = collector._create_pending_order(
            db,
            symbol="ETHUSDC",
            side="BUY",
            price=2000.0,
            qty=0.01,
            mode="demo",
            reason="pytest_manual_confirmation",
            source="manual_telegram",
        )

        pending = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
        assert pending is not None
        assert pending.status == "PENDING_CREATED"
        assert pending.pending_type == "manual_demo"
    finally:
        db.close()
