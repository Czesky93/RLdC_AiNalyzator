from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp_db = tempfile.NamedTemporaryFile(
    prefix="rldc_reconcile_", suffix=".db", delete=False
)
_tmp_db.close()
_TEST_DB_URL = f"sqlite:///{_tmp_db.name}"

from backend import portfolio_reconcile as pr
from backend.database import (
    Base,
    ManualTradeDetection,
    PendingOrder,
    Position,
    ReconciliationEvent,
    ReconciliationRun,
    utc_now_naive,
)

engine = create_engine(_TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _run_reconcile(monkeypatch, *, balances, prices, mode="live"):
    monkeypatch.setattr(pr, "_last_reconcile_ts", None)
    monkeypatch.setattr(pr, "_get_binance_balances", lambda: balances)
    monkeypatch.setattr(pr, "_get_ticker_price", lambda symbol: prices.get(symbol, 0.0))
    monkeypatch.setattr(pr, "_notify_telegram_reconcile", lambda summary, events: None)

    db = TestingSessionLocal()
    try:
        return pr.reconcile_with_binance(
            db, mode=mode, trigger="pytest", notify_telegram=False, force=True
        )
    finally:
        db.close()


def test_reconcile_cancels_stale_pending(monkeypatch):
    db = TestingSessionLocal()
    try:
        stale = PendingOrder(
            symbol="BTCUSDC",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
            mode="live",
            status="PENDING",
        )
        stale.created_at = utc_now_naive().replace(year=utc_now_naive().year - 1)
        db.add(stale)
        db.commit()
        pid = stale.id
    finally:
        db.close()

    summary = _run_reconcile(
        monkeypatch,
        balances={"USDC": 100.0},
        prices={"EURUSDC": 1.1},
        mode="live",
    )

    db = TestingSessionLocal()
    try:
        refreshed = db.query(PendingOrder).filter(PendingOrder.id == pid).first()
        assert refreshed is not None
        assert refreshed.status == "CANCELLED"
        run = (
            db.query(ReconciliationRun)
            .filter(ReconciliationRun.id == summary["run_id"])
            .first()
        )
        assert run is not None
        assert run.status == "completed"
    finally:
        db.close()


def test_reconcile_fixes_orphan_and_qty_mismatch(monkeypatch):
    db = TestingSessionLocal()
    try:
        orphan = Position(
            symbol="ADAUSDC",
            side="LONG",
            entry_price=1.0,
            quantity=10.0,
            current_price=1.0,
            mode="live",
        )
        mismatch = Position(
            symbol="ETHUSDC",
            side="LONG",
            entry_price=2000.0,
            quantity=1.0,
            current_price=2000.0,
            mode="live",
        )
        db.add(orphan)
        db.add(mismatch)
        db.commit()
        orphan_id = orphan.id
        mismatch_id = mismatch.id
    finally:
        db.close()

    _run_reconcile(
        monkeypatch,
        balances={"ETH": 1.5, "USDC": 50.0},
        prices={"EURUSDC": 1.1, "ETHUSDC": 2000.0},
        mode="live",
    )

    db = TestingSessionLocal()
    try:
        orphan_after = db.query(Position).filter(Position.id == orphan_id).first()
        mismatch_after = db.query(Position).filter(Position.id == mismatch_id).first()
        assert orphan_after is not None
        assert mismatch_after is not None
        assert orphan_after.exit_reason_code == "reconcile_closed_missing_on_binance"
        assert orphan_after.quantity == 0.0
        assert abs(float(mismatch_after.quantity) - 1.5) < 1e-9

        ev_types = [
            e.event_type
            for e in db.query(ReconciliationEvent)
            .order_by(ReconciliationEvent.id.desc())
            .limit(10)
            .all()
        ]
        assert "orphan_position" in ev_types
        assert "qty_mismatch" in ev_types
    finally:
        db.close()


def test_reconcile_detects_manual_trade_and_creates_position(monkeypatch):
    summary = _run_reconcile(
        monkeypatch,
        balances={"BTC": 0.01, "USDC": 10.0},
        prices={"EURUSDC": 1.1, "BTCUSDC": 50000.0},
        mode="live",
    )

    assert summary["manual_trades_detected"] >= 1
    assert summary["detected_manual_live"] >= 1
    assert "repaired_positions" in summary
    assert "repaired_pending" in summary

    db = TestingSessionLocal()
    try:
        pos = (
            db.query(Position)
            .filter(Position.symbol == "BTCUSDC", Position.mode == "live")
            .first()
        )
        det = (
            db.query(ManualTradeDetection)
            .filter(ManualTradeDetection.symbol == "BTCUSDC")
            .first()
        )
        assert pos is not None
        assert pos.entry_reason_code == "manual_trade_reconcile_synced"
        assert det is not None
        assert det.db_synced is True
    finally:
        db.close()
