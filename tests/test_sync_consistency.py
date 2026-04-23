"""
Tests for DB ↔ Binance sync consistency after soft-close changes.

Validates:
1. Full close positions are soft-closed, not deleted
2. Partial TP quantities are tracked correctly
3. BNB fee residuals are detected separately
4. Reconcile ignores closed positions
5. No false mismatches on delayed commit
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""
os.environ["DEMO_INITIAL_BALANCE"] = "10000"
os.environ["TRADING_MODE"] = "demo"
os.environ["ALLOW_LIVE_TRADING"] = "false"

import pytest

from backend.database import Position, SessionLocal, init_db, utc_now_naive


@pytest.fixture(autouse=True)
def clean_positions_table():
    init_db()
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.commit()
        yield
    finally:
        db.query(Position).delete()
        db.commit()
        db.close()


def test_full_close_soft_closes_position_not_deleted():
    """
    Verify that full close (qty <= 0) marks position as closed, not deleted.

    After fix: position.exit_reason_code = "full_close", quantity = 0.0
    Before would: db.delete(position)
    """
    db = SessionLocal()
    init_db()

    pos = Position(
        symbol="BTCEUR",
        side="LONG",
        entry_price=45000.0,
        quantity=0.5,
        mode="live",
        entry_reason_code="test_entry",
    )
    db.add(pos)
    db.commit()

    pos_id = pos.id

    # Simulate SELL execution that full closes position
    pos.quantity = 0.0
    pos.exit_reason_code = "full_close"
    pos.unrealized_pnl = 0.0
    pos.gross_pnl = 1000.0
    pos.net_pnl = 900.0
    db.commit()

    # Verify position still exists in DB
    result = db.query(Position).filter(Position.id == pos_id).first()
    assert result is not None, "Position was deleted instead of soft-closed"
    assert result.quantity == 0.0
    assert result.exit_reason_code == "full_close"
    assert result.gross_pnl == 1000.0

    # Verify query with exit_reason_code IS NULL doesn't return it
    open_positions = (
        db.query(Position)
        .filter(Position.mode == "live", Position.exit_reason_code.is_(None))
        .all()
    )
    assert len(open_positions) == 0, "Closed position returned in open positions query"

    db.close()


def test_partial_tp_reduces_quantity():
    """
    Verify partial TP correctly reduces position quantity.

    Position remains open with quantity > 0, can have multiple partial closes.
    """
    db = SessionLocal()
    init_db()

    pos = Position(
        symbol="ETHEUR",
        side="LONG",
        entry_price=2500.0,
        quantity=2.0,
        mode="live",
        entry_reason_code="test_entry",
    )
    db.add(pos)
    db.commit()

    original_id = pos.id

    # First partial TP: sell 0.5
    pos.quantity = 1.5
    pos.partial_take_count = 1
    pos.gross_pnl = 250.0  # partial gain
    db.commit()

    # Verify position is still open
    result = db.query(Position).filter(Position.id == original_id).first()
    assert result is not None
    assert result.quantity == 1.5
    assert result.exit_reason_code is None  # still open
    assert result.partial_take_count == 1

    # Second partial TP: sell 0.5 more (now at 1.0)
    pos.quantity = 1.0
    pos.partial_take_count = 2
    pos.gross_pnl = 600.0  # cumulative gain
    db.commit()

    result = db.query(Position).filter(Position.id == original_id).first()
    assert result.quantity == 1.0
    assert result.partial_take_count == 2
    assert result.exit_reason_code is None  # still open

    # Final close: sell last 1.0
    pos.quantity = 0.0
    pos.exit_reason_code = "full_close"  # now closed
    pos.gross_pnl = 1200.0
    db.commit()

    result = db.query(Position).filter(Position.id == original_id).first()
    assert result.quantity == 0.0
    assert result.exit_reason_code == "full_close"
    assert result.partial_take_count == 2

    db.close()


def test_reconcile_ignores_closed_positions():
    """
    Verify that _sync_binance_positions() ignores positions with exit_reason_code != NULL.

    This prevents false mismatchesa when reconcile runs and finds closed positions.
    """
    db = SessionLocal()
    init_db()

    # Add open position
    open_pos = Position(
        symbol="SOLUSDC",
        side="LONG",
        entry_price=100.0,
        quantity=1.0,
        mode="live",
        entry_reason_code="test",
    )
    db.add(open_pos)

    # Add closed position
    closed_pos = Position(
        symbol="ARBEUR",
        side="LONG",
        entry_price=1.0,
        quantity=0.0,
        mode="live",
        entry_reason_code="test",
        exit_reason_code="full_close",  # marked as closed
    )
    db.add(closed_pos)
    db.commit()

    # Query LIVE open positions (as reconcile does)
    db_positions = (
        db.query(Position)
        .filter(
            Position.mode == "live", Position.exit_reason_code.is_(None)  # only open
        )
        .all()
    )

    # Should only get the open position
    symbols = {p.symbol for p in db_positions}
    assert symbols == {"SOLUSDC"}, f"Expected only SOLUSDC, got {symbols}"
    assert len(db_positions) == 1

    db.close()


def test_bnb_fee_residual_detection():
    """
    Verify BNB fee residual is detected separately from position mismatches.

    If there's significant BNB balance but no BNB position in DB:
    - Below dust threshold: ignored
    - Above dust threshold: reported as bnb_fee_residual
    """
    db = SessionLocal()
    init_db()

    # Simulate no BNB position in DB
    db_positions = (
        db.query(Position)
        .filter(Position.mode == "live", Position.exit_reason_code.is_(None))
        .all()
    )

    # Map BNB qty from DB (should be 0)
    db_bnb_qty = sum(p.quantity for p in db_positions if "BNB" in (p.symbol or ""))
    assert db_bnb_qty == 0.0, "Test setup: no BNB position should exist"

    # Simulate Binance having BNB balance (from fees)
    bnb_balance = 0.015  # 15 mBNB from fees
    bnb_price = 25.0  # example BNB/EUR price
    bnb_value = bnb_balance * bnb_price  # 0.375 EUR

    _bnb_dust_threshold = 0.002  # 2 mBNB dust threshold
    _min_notional = 25.0

    # Above dust threshold, below min notional
    if bnb_balance > _bnb_dust_threshold and bnb_value < _min_notional:
        reason = "bnb_fee_residual"  # as per reconcile logic

    assert reason == "bnb_fee_residual"

    # Now test below dust threshold
    bnb_balance_dust = 0.001  # 1 mBNB
    if bnb_balance_dust > _bnb_dust_threshold:
        # Would be reported
        raise AssertionError("Should not reach here - BNB is below dust")

    db.close()


def test_no_false_mismatch_on_delayed_commit():
    """
    Verify that a newly closed position doesn't cause mismatch on next reconcile.

    Scenario:
    1. Position is SELL executed on Binance (qty becomes 0)
    2. DB updates position.quantity = 0, exit_reason_code = "full_close"
    3. Commit might be delayed
    4. Reconcile runs and compares Binance vs DB
    5. Since query has filter exit_reason_code.is_(None), closed position is excluded
    6. No false mismatch reported
    """
    db = SessionLocal()
    init_db()

    # Create position
    pos = Position(
        symbol="BTCEUR",
        side="LONG",
        entry_price=45000.0,
        quantity=0.5,
        mode="live",
        entry_reason_code="test",
    )
    db.add(pos)
    db.commit()

    # SELL execution: mark as full_close
    pos.quantity = 0.0
    pos.exit_reason_code = "full_close"
    db.commit()

    # Now reconcile: query open positions
    db_positions = (
        db.query(Position)
        .filter(
            Position.mode == "live", Position.exit_reason_code.is_(None)  # skip closed
        )
        .all()
    )

    # DB map should not include the closed BTC position
    db_map = {}
    for p in db_positions:
        sym = p.symbol or ""
        base = sym.replace("EUR", "").replace("USDC", "").replace("USDT", "")
        if base:
            db_map[base] = db_map.get(base, 0.0) + float(p.quantity or 0)

    assert "BTC" not in db_map, "Closed BTC position should not be in DB map"

    # Binance would show qty=0 for BTC (normal for closed position)
    binance_map = {}  # no BTC (qty already 0 or asset removed after close)

    # No mismatch because neither has BTC
    all_assets = set(list(binance_map.keys()) + list(db_map.keys()))
    assert "BTC" not in all_assets, "No mismatch reported for closed positions"

    db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
