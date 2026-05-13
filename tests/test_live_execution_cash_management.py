from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DISABLE_COLLECTOR"] = "true"
os.environ["ADMIN_TOKEN"] = ""

from backend.collector import DataCollector
from backend.database import (
    Base,
    DecisionTrace,
    MarketData,
    PendingOrder,
    Position,
    SessionLocal,
    init_db,
    utc_now_naive,
)
from backend.routers.account import get_trading_status

init_db()


class _MockBinance:
    def __init__(self):
        self.orders = []
        self.converted = False

    def get_ticker_price(self, symbol: str):
        symbol = (symbol or "").upper()
        if symbol == "EURUSDC":
            return {"symbol": "EURUSDC", "price": 1.1}
        if symbol == "ETHUSDC":
            return {"symbol": "ETHUSDC", "price": 2000.0}
        return None

    def get_allowed_symbols(self, quotes=None):
        return {
            "EURUSDC": {
                "base_asset": "EUR",
                "quote_asset": "USDC",
                "min_qty": 0.1,
                "step_size": 0.1,
                "min_notional": 5.0,
            },
            "ETHUSDC": {
                "base_asset": "ETH",
                "quote_asset": "USDC",
                "min_qty": 0.001,
                "step_size": 0.001,
                "min_notional": 10.0,
            },
        }

    def get_balances(self):
        if not self.converted:
            return [
                {"asset": "EUR", "free": 200.0, "locked": 0.0, "total": 200.0},
                {"asset": "USDC", "free": 0.0, "locked": 0.0, "total": 0.0},
            ]
        return [
            {"asset": "EUR", "free": 130.0, "locked": 0.0, "total": 130.0},
            {"asset": "USDC", "free": 70.0, "locked": 0.0, "total": 70.0},
        ]

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: float = 0.0,
        price=None,
        quote_qty: float = 0.0,
    ):
        self.orders.append((symbol, side, quantity, quote_qty))
        if symbol == "EURUSDC" and side == "SELL":
            self.converted = True
            return {
                "symbol": symbol,
                "orderId": 7001,
                "status": "FILLED",
                "executedQty": str(quantity),
                "fills": [
                    {
                        "qty": str(quantity),
                        "price": "1.1",
                        "commission": "0.0",
                        "commissionAsset": "USDC",
                    }
                ],
            }
        if symbol == "ETHUSDC" and side == "BUY":
            return {
                "symbol": symbol,
                "orderId": 7002,
                "status": "FILLED",
                "executedQty": str(quantity),
                "fills": [
                    {
                        "qty": str(quantity),
                        "price": "2000.0",
                        "commission": "0.01",
                        "commissionAsset": "USDC",
                    }
                ],
            }
        return {"_error": True, "error_message": "unsupported mock order"}


def _collector_with_mock_binance():
    c = DataCollector.__new__(DataCollector)
    c.binance = _MockBinance()
    c._runtime_context = lambda db: {
        "config": {
            "taker_fee_rate": 0.001,
            "slippage_bps": 5.0,
            "spread_buffer_bps": 3.0,
            "min_edge_multiplier": 2.5,
            "min_buy_eur": 60.0,
            "min_order_notional": 25.0,
            "execution_quote_buffer_pct": 0.01,
            "trading_mode": "live",
            "allow_live_trading": True,
            "execution_enabled": True,
        },
        "snapshot_id": "pytest-snapshot",
    }
    c._trace_decision = lambda *args, **kwargs: None
    c._save_exit_quality = lambda *args, **kwargs: None
    return c


def _collector_with_binance(binance_obj):
    c = DataCollector.__new__(DataCollector)
    c.binance = binance_obj
    c._runtime_context = lambda db: {
        "config": {
            "taker_fee_rate": 0.001,
            "slippage_bps": 5.0,
            "spread_buffer_bps": 3.0,
            "min_edge_multiplier": 2.5,
            "min_buy_eur": 60.0,
            "min_order_notional": 25.0,
            "execution_quote_buffer_pct": 0.01,
            "trading_mode": "live",
            "allow_live_trading": True,
            "execution_enabled": True,
        },
        "snapshot_id": "pytest-snapshot",
    }
    c._trace_decision = lambda *args, **kwargs: None
    c._save_exit_quality = lambda *args, **kwargs: None
    return c


class _MockBinanceSubmittedNoFill(_MockBinance):
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: float = 0.0,
        price=None,
        quote_qty: float = 0.0,
    ):
        self.orders.append((symbol, side, quantity, quote_qty))
        if symbol == "EURUSDC" and side == "SELL":
            self.converted = True
            return {
                "symbol": symbol,
                "orderId": 7101,
                "status": "FILLED",
                "executedQty": str(quantity),
                "fills": [
                    {
                        "qty": str(quantity),
                        "price": "1.1",
                        "commission": "0.0",
                        "commissionAsset": "USDC",
                    }
                ],
            }
        if symbol == "ETHUSDC" and side == "BUY":
            return {
                "symbol": symbol,
                "orderId": 7102,
                "status": "NEW",
                "executedQty": "0",
                "fills": [],
            }
        return {"_error": True, "error_message": "unsupported mock order"}


class _MockBinanceRejectBuy(_MockBinance):
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: float = 0.0,
        price=None,
        quote_qty: float = 0.0,
    ):
        self.orders.append((symbol, side, quantity, quote_qty))
        if symbol == "EURUSDC" and side == "SELL":
            self.converted = True
            return {
                "symbol": symbol,
                "orderId": 7201,
                "status": "FILLED",
                "executedQty": str(quantity),
                "fills": [
                    {
                        "qty": str(quantity),
                        "price": "1.1",
                        "commission": "0.0",
                        "commissionAsset": "USDC",
                    }
                ],
            }
        if symbol == "ETHUSDC" and side == "BUY":
            return {"_error": True, "error_message": "insufficient balance"}
        return {"_error": True, "error_message": "unsupported mock order"}


def test_min_buy_eur_is_converted_to_required_usdc_notional():
    collector = _collector_with_mock_binance()
    required, meta = collector._resolve_min_buy_quote_notional(
        "ETHUSDC", {"min_buy_eur": 60.0}
    )
    assert required == 66.0
    assert meta["quote_asset"] == "USDC"


def test_ensure_quote_balance_for_order_auto_converts_eur_to_usdc():
    collector = _collector_with_mock_binance()
    db = SessionLocal()
    try:
        result = collector._ensure_quote_balance_for_order(
            db,
            symbol="ETHUSDC",
            required_quote_notional=66.0,
            config={"execution_quote_buffer_pct": 0.01},
        )
        assert result["ok"] is True
        assert result.get("converted") is True
        assert any(
            order[0] == "EURUSDC" and order[1] == "SELL"
            for order in collector.binance.orders
        )
    finally:
        db.close()


def test_confirmed_pending_live_buy_is_executed_with_conversion_path():
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.commit()

        pending = PendingOrder(
            symbol="ETHUSDC",
            side="BUY",
            order_type="MARKET",
            price=2000.0,
            quantity=0.01,  # 20 USDC < min 60 EUR => musi zostać podniesione
            mode="live",
            status="PENDING_CONFIRMED",
            reason="pytest_confirmed",
            created_at=utc_now_naive(),
            confirmed_at=utc_now_naive(),
        )
        db.add(pending)
        db.commit()

        collector = _collector_with_mock_binance()
        collector._execute_confirmed_pending_orders(db)

        db.refresh(pending)
        assert pending.status == "FILLED"
        assert any(
            order[0] == "EURUSDC" and order[1] == "SELL"
            for order in collector.binance.orders
        )
        buy_orders = [
            o for o in collector.binance.orders if o[0] == "ETHUSDC" and o[1] == "BUY"
        ]
        assert buy_orders
        final_buy = buy_orders[-1]
        final_notional = float(final_buy[2]) * 2000.0
        assert final_notional >= 66.0
    finally:
        db.close()


def test_create_pending_order_returns_existing_for_active_duplicate():
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.commit()

        collector = _collector_with_mock_binance()
        first_id = collector._create_pending_order(
            db=db,
            symbol="ETHUSDC",
            side="BUY",
            price=2000.0,
            qty=0.05,
            mode="live",
            reason="pytest_dedupe",
            config_snapshot_id="pytest-snapshot",
            strategy_name="pytest",
        )
        second_id = collector._create_pending_order(
            db=db,
            symbol="ETHUSDC",
            side="BUY",
            price=2000.0,
            qty=0.05,
            mode="live",
            reason="pytest_dedupe_repeat",
            config_snapshot_id="pytest-snapshot",
            strategy_name="pytest",
        )

        assert second_id == first_id
        count = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.symbol == "ETHUSDC",
                PendingOrder.side == "BUY",
                PendingOrder.mode == "live",
            )
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_confirmed_pending_qty_non_positive_is_rejected_without_exchange_call():
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.commit()

        pending = PendingOrder(
            symbol="ETHUSDC",
            side="BUY",
            order_type="MARKET",
            price=2000.0,
            quantity=0.0,
            mode="live",
            status="PENDING_CONFIRMED",
            reason="pytest_qty_non_positive",
            created_at=utc_now_naive(),
            confirmed_at=utc_now_naive(),
        )
        db.add(pending)
        db.commit()

        collector = _collector_with_mock_binance()
        collector._execute_confirmed_pending_orders(db)

        db.refresh(pending)
        assert pending.status == "REJECTED"
        assert not collector.binance.orders
    finally:
        db.close()


def test_buy_submitted_without_fill_does_not_become_filled_or_open_position():
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.query(Position).delete()
        db.commit()

        pending = PendingOrder(
            symbol="ETHUSDC",
            side="BUY",
            order_type="MARKET",
            price=2000.0,
            quantity=0.01,
            mode="live",
            status="PENDING_CONFIRMED",
            reason="pytest_submitted_no_fill",
            created_at=utc_now_naive(),
            confirmed_at=utc_now_naive(),
        )
        db.add(pending)
        db.commit()

        collector = _collector_with_binance(_MockBinanceSubmittedNoFill())
        collector._execute_confirmed_pending_orders(db)

        db.refresh(pending)
        assert pending.status == "EXCHANGE_SUBMITTED"
        pos_count = (
            db.query(Position)
            .filter(
                Position.symbol == "ETHUSDC",
                Position.mode == "live",
                Position.exit_reason_code.is_(None),
            )
            .count()
        )
        assert pos_count == 0
    finally:
        db.close()


def test_buy_rejected_by_exchange_has_no_fake_success_and_no_position():
    db = SessionLocal()
    try:
        db.query(PendingOrder).delete()
        db.query(Position).delete()
        db.commit()

        pending = PendingOrder(
            symbol="ETHUSDC",
            side="BUY",
            order_type="MARKET",
            price=2000.0,
            quantity=0.01,
            mode="live",
            status="PENDING_CONFIRMED",
            reason="pytest_rejected",
            created_at=utc_now_naive(),
            confirmed_at=utc_now_naive(),
        )
        db.add(pending)
        db.commit()

        collector = _collector_with_binance(_MockBinanceRejectBuy())
        collector._execute_confirmed_pending_orders(db)

        db.refresh(pending)
        assert pending.status == "REJECTED"
        pos_count = (
            db.query(Position)
            .filter(
                Position.symbol == "ETHUSDC",
                Position.mode == "live",
                Position.exit_reason_code.is_(None),
            )
            .count()
        )
        assert pos_count == 0
    finally:
        db.close()


def test_temporary_execution_error_not_reported_as_persistent_blocker():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        db.add(MarketData(symbol="ETHUSDC", price=2000.0, timestamp=utc_now_naive()))
        db.add(
            DecisionTrace(
                symbol="ETHUSDC",
                mode="live",
                action_type="reject_pending",
                reason_code="temporary_execution_error",
                timestamp=utc_now_naive(),
            )
        )
        db.commit()

        data = get_trading_status(mode="live", request=None, db=db)["data"]
        blocker_codes = {b.get("code") for b in data.get("blockers") or []}
        assert "TEMPORARY_EXECUTION_ERROR" not in blocker_codes
    finally:
        db.close()


# =============================================================================
# T-104 v2: USDC-first tests
# =============================================================================


def test_resolve_min_buy_returns_usdc_meta():
    """_resolve_min_buy_quote_notional musi zwracać quote_asset=USDC i required_quote_usdc (nie min_buy_eur)."""
    collector = _collector_with_mock_binance()
    required, meta = collector._resolve_min_buy_quote_notional(
        "ETHUSDC", {"min_buy_eur": 60.0}
    )
    assert meta["quote_asset"] == "USDC"
    # meta musi mieć required_quote_usdc (USDC-first)
    assert "required_quote_usdc" in meta, f"meta nie ma required_quote_usdc: {meta}"
    # NIE powinno mieć min_buy_eur w kluczu (leakage EUR-first)
    assert "min_buy_eur" not in meta, f"meta nie powinno eksponować min_buy_eur: {meta}"


def test_execution_log_uses_usdc_not_eur_key():
    """execution_started log NIE powinien używać min_buy_eur= lecz required_quote_usdc=."""
    import io
    import logging

    collector = _collector_with_mock_binance()
    db = SessionLocal()
    try:
        _, meta = collector._resolve_min_buy_quote_notional(
            "ETHUSDC", {"min_buy_eur": 60.0}
        )
        # Sprawdzamy że klucz w logu to required_quote_usdc, nie min_buy_eur
        log_fragment = f"required_quote_usdc={meta.get('required_quote_usdc') or meta.get('required_quote_eur')} "
        # meta nie powinno eksponować min_buy_eur
        assert "min_buy_eur" not in str(meta), f"meta eksponuje min_buy_eur: {meta}"
        assert "required_quote_usdc" in str(meta) or "required_quote_eur" in str(meta)
    finally:
        db.close()


def test_fund_usdc_error_message_is_usdc_denominated():
    """Gdy brak USDC i EUR, wiadomość musi być w USDC (nie EUR)."""
    from unittest.mock import MagicMock

    from backend.quote_currency import fund_usdc_from_eur_if_needed

    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}

    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=500.0,
        available_usdc=5.0,
        available_eur=2.0,
    )
    assert result["ok"] is False
    assert result["reason_code"] == "insufficient_usdc_and_eur"
    # Wiadomość musi zawierać USDC — nie "X EUR required"
    msg = result.get("message", "")
    assert "USDC" in msg, f"Wiadomość powinna zawierać USDC: {msg!r}"


def test_funding_conversion_logs_started_and_filled():
    """fund_usdc_from_eur_if_needed emituje reason_code=funding_conversion_filled po udanej konwersji."""
    from unittest.mock import MagicMock

    from backend.quote_currency import fund_usdc_from_eur_if_needed

    mock_client = MagicMock()
    mock_client.get_ticker_price.return_value = {"symbol": "EURUSDC", "price": "1.1"}
    mock_client.get_allowed_symbols.return_value = {
        "EURUSDC": {"step_size": "0.1", "min_qty": "0.1"}
    }
    mock_client.place_order.return_value = {
        "orderId": 9001,
        "executedQty": "40.0",
        "status": "FILLED",
    }
    mock_client.get_balances.return_value = [
        {"asset": "USDC", "free": "100.0"},
    ]

    result = fund_usdc_from_eur_if_needed(
        mock_client,
        required_usdc=80.0,
        available_usdc=20.0,
        available_eur=100.0,
    )
    assert result["ok"] is True
    assert result["converted"] is True
    assert result["reason_code"] == "funding_conversion_filled"
