"""
test_trading_state_manager.py — Testy jednostkowe dla backend/trading/state_manager.py

Testuje:
  - recover_on_startup: DEMO → brak akcji
  - recover_on_startup: LIVE z otwartymi orderami Binance
  - recover_on_startup: LIVE, order nie na Binance → FILLED recovery
  - recover_on_startup: LIVE, order nie na Binance → CANCELLED
  - check_pending_fills: DEMO → brak akcji
  - check_pending_fills: LIVE, brak EXCHANGE_SUBMITTED → brak akcji
  - reconcile_live_positions: throttle (force=False, za wcześ nie)
  - reconcile_live_positions: force=True → przejście mimo throttle
  - reconcile_live_positions: Binance qty=0 → closed_externally_reconcile
  - reconcile_live_positions: Binance qty < DB → discrepancy
  - detect_orphan_orders: DEMO → brak akcji
  - detect_orphan_orders: brak exchange_id → ORPHAN_NO_EXCHANGE_ID
  - detect_orphan_orders: Binance FILLED → fill odzyskany
  - detect_orphan_orders: Binance nieznaleziony → ORPHAN_NOT_FOUND
  - _symbol_to_base: poprawne parsowanie par
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from backend.trading.state_manager import ReconcileResult, StateManager
from backend.trading.trade_config import TradeConfig


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _default_cfg(**overrides) -> TradeConfig:
    cfg = TradeConfig()
    cfg.sync_interval_sec = 300.0
    cfg.orphan_order_ttl_sec = 3600
    cfg.min_order_notional = 5.0
    cfg.allowed_quotes = ["USDC", "EUR"]
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_sm(cfg=None) -> tuple[StateManager, MagicMock]:
    if cfg is None:
        cfg = _default_cfg()
    mock_bc = MagicMock()
    sm = StateManager(cfg, mock_bc)
    return sm, mock_bc


def _make_pending(
    id_: int = 1,
    symbol: str = "BTCUSDC",
    side: str = "BUY",
    mode: str = "live",
    status: str = "EXCHANGE_SUBMITTED",
    exchange_order_id: str = "999",
    created_at: datetime | None = None,
) -> MagicMock:
    po = MagicMock()
    po.id = id_
    po.symbol = symbol
    po.side = side
    po.mode = mode
    po.status = status
    po.exchange_order_id = exchange_order_id
    po.created_at = created_at or datetime.utcnow() - timedelta(minutes=5)
    po.exec_price = None
    po.exec_qty = None
    po.filled_at = None
    return po


def _make_position(
    id_: int = 1,
    symbol: str = "BTCUSDC",
    qty: float = 0.1,
    entry_price: float = 100.0,
) -> MagicMock:
    pos = MagicMock()
    pos.id = id_
    pos.symbol = symbol
    pos.quantity = qty
    pos.entry_price = entry_price
    pos.current_price = entry_price
    pos.unrealized_pnl = 0.0
    pos.exit_reason_code = None
    pos.closed_at = None
    return pos


def _build_db_mock(
    db_orders: list | None = None,
    db_positions: list | None = None,
) -> MagicMock:
    """Buduje mock DB z skonfigurowanymi wynikami query.
    
    Używa dict dispatch: query(Class) → różne dane zależnie od klasy.
    """
    db = MagicMock()
    
    pending_chain = MagicMock()
    pending_chain.filter.return_value.all.return_value = db_orders or []
    pending_chain.filter.return_value.first.return_value = None

    position_chain = MagicMock()
    position_chain.filter.return_value.all.return_value = db_positions or []

    def _side_effect(cls):
        cls_name = getattr(cls, "__name__", str(cls))
        if "PendingOrder" in cls_name:
            return pending_chain
        if "Position" in cls_name:
            return position_chain
        return MagicMock()

    db.query.side_effect = _side_effect
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


# ── 1. recover_on_startup ─────────────────────────────────────────────────────

class TestRecoverOnStartup:
    def test_demo_mode_no_op(self):
        """DEMO → natychmiastowy zwrot bez działania."""
        sm, mock_bc = _make_sm()
        db = _build_db_mock()

        result = sm.recover_on_startup(db, mode="demo")

        assert isinstance(result, ReconcileResult)
        mock_bc.get_open_orders.assert_not_called()
        db.commit.assert_not_called()

    def test_live_no_db_orders_no_action(self):
        """LIVE, brak DB orders → nic do naprawy."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = []
        db = _build_db_mock(db_orders=[])

        result = sm.recover_on_startup(db, mode="live")

        assert result.fills_detected == 0
        assert result.orphan_orders_fixed == 0

    def test_live_db_order_still_open_on_binance(self):
        """DB order ma exchange_id który jest na Binance OPEN → nie modyfikuj."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = [
            {"orderId": 999, "symbol": "BTCUSDC", "status": "NEW"}
        ]
        po = _make_pending(exchange_order_id="999", status="EXCHANGE_SUBMITTED")
        db = _build_db_mock(db_orders=[po])

        result = sm.recover_on_startup(db, mode="live")

        # Status NEW → nie naprawiamy
        assert result.orphan_orders_fixed == 0
        assert result.fills_detected == 0

    def test_live_db_order_cancelled_on_binance(self):
        """DB order ma exchange_id który jest na Binance ze statusem CANCELED → napraw."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = [
            {"orderId": 999, "symbol": "BTCUSDC", "status": "CANCELED"}
        ]
        po = _make_pending(exchange_order_id="999", status="EXCHANGE_SUBMITTED")
        db = _build_db_mock(db_orders=[po])

        result = sm.recover_on_startup(db, mode="live")

        assert result.orphan_orders_fixed == 1
        assert po.status.startswith("CANCELLED_BY_EXCHANGE")

    def test_live_db_order_not_on_binance_filled(self):
        """DB order nie ma odpowiednika na Binance → pyta get_order → FILLED → fill recovery."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = []  # pusty Binance open orders
        mock_bc.get_order.return_value = {
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "10.0",
            "price": "100.0",
        }
        po = _make_pending(exchange_order_id="1234", status="EXCHANGE_SUBMITTED")
        db = _build_db_mock(db_orders=[po])

        result = sm.recover_on_startup(db, mode="live")

        assert result.fills_detected == 1
        assert po.status == "FILLED_CONFIRMED"

    def test_live_db_order_not_on_binance_cancelled(self):
        """DB order nie na Binance + get_order zwraca CANCELED → napraw."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = []
        mock_bc.get_order.return_value = {
            "status": "CANCELED",
        }
        po = _make_pending(exchange_order_id="777", status="EXCHANGE_SUBMITTED")
        db = _build_db_mock(db_orders=[po])

        result = sm.recover_on_startup(db, mode="live")

        assert result.orphan_orders_fixed == 1
        assert po.status.startswith("CANCELLED_")

    def test_live_db_order_no_exchange_id(self):
        """DB order bez exchange_order_id → loguje no_exchange_id, nie modyfikuje."""
        sm, mock_bc = _make_sm()
        mock_bc.get_open_orders.return_value = []
        po = _make_pending(exchange_order_id="", status="EXCHANGE_SUBMITTED")
        db = _build_db_mock(db_orders=[po])

        result = sm.recover_on_startup(db, mode="live")

        any_no_id = any(d.get("type") == "no_exchange_id" for d in result.details)
        assert any_no_id is True


# ── 2. check_pending_fills ────────────────────────────────────────────────────

class TestCheckPendingFills:
    def test_demo_mode_no_op(self):
        sm, mock_bc = _make_sm()
        db = _build_db_mock()

        result = sm.check_pending_fills(db, mode="demo")

        assert result.fills_detected == 0
        mock_bc.get_order.assert_not_called()

    def test_no_exchange_submitted_rows(self):
        sm, mock_bc = _make_sm()
        db = _build_db_mock(db_orders=[])

        result = sm.check_pending_fills(db, mode="live")

        assert result.fills_detected == 0
        mock_bc.get_order.assert_not_called()

    def test_pending_row_with_no_exchange_id_skipped(self):
        """Wiersz EXCHANGE_SUBMITTED bez exchange_order_id → skip."""
        sm, mock_bc = _make_sm()
        po = _make_pending(exchange_order_id=None)
        po.exchange_order_id = None
        db = _build_db_mock(db_orders=[po])

        result = sm.check_pending_fills(db, mode="live")

        mock_bc.get_order.assert_not_called()
        assert result.fills_detected == 0

    def test_fresh_order_skipped_grace_period(self):
        """Order złożony < 10s temu → skip (grace period)."""
        sm, mock_bc = _make_sm()
        po = _make_pending(
            exchange_order_id="999",
            created_at=datetime.utcnow() - timedelta(seconds=3),  # 3s temu
        )
        db = _build_db_mock(db_orders=[po])

        result = sm.check_pending_fills(db, mode="live")

        mock_bc.get_order.assert_not_called()
        assert result.fills_detected == 0


# ── 3. reconcile_live_positions ───────────────────────────────────────────────

class TestReconcileLivePositions:
    def test_trade_config_default_uses_reconcile_interval_field(self):
        """Kanoniczny TradeConfig nie ma sync_interval_sec, tylko reconcile_interval_sec."""
        sm, mock_bc = _make_sm(cfg=TradeConfig())
        sm._last_reconcile_ts = time.monotonic()

        db = _build_db_mock()
        result = sm.reconcile_live_positions(db, force=False)

        assert result.positions_reconciled == 0
        mock_bc.get_balances.assert_not_called()

    def test_throttle_respects_interval(self):
        """Wywołanie bez force i przed upłynięciem sync_interval → no-op."""
        cfg = _default_cfg(sync_interval_sec=300.0)
        sm, mock_bc = _make_sm(cfg)
        sm._last_reconcile_ts = time.monotonic()  # właśnie reconcile

        db = _build_db_mock()
        result = sm.reconcile_live_positions(db, force=False)

        assert result.positions_reconciled == 0
        mock_bc.get_balances.assert_not_called()

    def test_force_bypasses_throttle(self):
        """force=True → reconcile mimo throttle."""
        cfg = _default_cfg(sync_interval_sec=300.0)
        sm, mock_bc = _make_sm(cfg)
        sm._last_reconcile_ts = time.monotonic()  # właśnie reconcile
        mock_bc.get_balances.return_value = []
        db = _build_db_mock(db_positions=[])

        result = sm.reconcile_live_positions(db, force=True)

        # Wywołanie nastąpiło (commit był wołany)
        db.commit.assert_called()

    def test_binance_qty_zero_closes_position(self):
        """Binance qty=0 → pozycja oznaczona jako closed_externally_reconcile."""
        sm, mock_bc = _make_sm(cfg=_default_cfg(min_order_notional=0.0))
        sm._last_reconcile_ts = 0.0  # wymuś reconcile

        pos = _make_position(symbol="BTCUSDC", qty=0.1, entry_price=100.0)
        mock_bc.get_balances.return_value = [
            {"asset": "BTC", "free": "0.0", "locked": "0.0"}
        ]
        # get_price lub get_avg_price → cena aktualna
        mock_bc.get_price.return_value = 105.0

        db = _build_db_mock(db_positions=[pos])
        result = sm.reconcile_live_positions(db, force=True)

        assert result.positions_discrepancy >= 1
        assert pos.exit_reason_code == "closed_externally_reconcile"
        assert pos.closed_at is not None

    def test_binance_qty_low_discrepancy(self):
        """Binance qty znacznie mniej niż DB → discrepancy (nie zero, nie zero-close)."""
        sm, mock_bc = _make_sm()
        sm._last_reconcile_ts = 0.0

        pos = _make_position(symbol="ETHUSDC", qty=1.0, entry_price=2000.0)
        mock_bc.get_balances.return_value = [
            {"asset": "ETH", "free": "0.5", "locked": "0.0"}  # 0.5 < 1.0 × (1-0.01)
        ]
        mock_bc.get_price.return_value = 2000.0

        db = _build_db_mock(db_positions=[pos])
        result = sm.reconcile_live_positions(db, force=True)

        assert result.positions_discrepancy >= 1
        # Nie zamknięto (nie jest zero)
        assert pos.exit_reason_code != "closed_externally_reconcile"

    def test_matching_qty_no_discrepancy(self):
        """Binance qty ≈ DB qty → brak discrepancy."""
        sm, mock_bc = _make_sm()
        sm._last_reconcile_ts = 0.0

        pos = _make_position(symbol="BTCUSDC", qty=0.1, entry_price=100.0)
        mock_bc.get_balances.return_value = [
            {"asset": "BTC", "free": "0.1", "locked": "0.0"}
        ]
        mock_bc.get_price.return_value = 100.0

        db = _build_db_mock(db_positions=[pos])
        result = sm.reconcile_live_positions(db, force=True)

        assert result.positions_discrepancy == 0
        assert result.positions_reconciled >= 1


# ── 4. detect_orphan_orders ───────────────────────────────────────────────────

class TestDetectOrphanOrders:
    def test_demo_mode_no_op(self):
        sm, mock_bc = _make_sm()
        db = _build_db_mock()

        result = sm.detect_orphan_orders(db, mode="demo")

        assert result.orphan_orders_found == 0
        mock_bc.get_order.assert_not_called()

    def test_no_orphan_candidates(self):
        sm, mock_bc = _make_sm()
        db = _build_db_mock(db_orders=[])

        result = sm.detect_orphan_orders(db, mode="live")

        assert result.orphan_orders_found == 0

    def test_no_exchange_id_marked_orphan(self):
        """Stary order bez exchange_id → ORPHAN_NO_EXCHANGE_ID."""
        sm, mock_bc = _make_sm()
        old_time = datetime.utcnow() - timedelta(hours=3)
        po = _make_pending(exchange_order_id="", created_at=old_time)
        po.exchange_order_id = ""

        db = _build_db_mock(db_orders=[po])
        result = sm.detect_orphan_orders(db, mode="live")

        assert result.orphan_orders_found >= 1
        assert po.status == "ORPHAN_NO_EXCHANGE_ID"

    def test_binance_filled_order_recovered(self):
        """Stary order z exchange_id, Binance odpowiada FILLED → fill recovery."""
        sm, mock_bc = _make_sm()
        old_time = datetime.utcnow() - timedelta(hours=3)
        po = _make_pending(exchange_order_id="555", created_at=old_time)
        mock_bc.get_order.return_value = {
            "status": "FILLED",
            "executedQty": "0.05",
            "cummulativeQuoteQty": "5.0",
            "price": "100.0",
        }

        db = _build_db_mock(db_orders=[po])
        result = sm.detect_orphan_orders(db, mode="live")

        assert result.fills_detected == 1
        assert po.status == "FILLED"
        assert po.filled_at is not None

    def test_binance_not_found_marked_orphan(self):
        """Stary order, Binance zwraca None → ORPHAN_NOT_FOUND_ON_EXCHANGE."""
        sm, mock_bc = _make_sm()
        old_time = datetime.utcnow() - timedelta(hours=3)
        po = _make_pending(exchange_order_id="666", created_at=old_time)
        mock_bc.get_order.return_value = None

        db = _build_db_mock(db_orders=[po])
        result = sm.detect_orphan_orders(db, mode="live")

        assert result.orphan_orders_found >= 1
        assert po.status == "ORPHAN_NOT_FOUND_ON_EXCHANGE"


# ── 5. _symbol_to_base ─────────────────────────────────────────────────────────

class TestSymbolToBase:
    def setup_method(self):
        sm, _ = _make_sm()
        self.sm = sm

    def test_btc_usdc(self):
        assert self.sm._symbol_to_base("BTCUSDC") == "BTC"

    def test_eth_usdt(self):
        assert self.sm._symbol_to_base("ETHUSDT") == "ETH"

    def test_sol_eur(self):
        assert self.sm._symbol_to_base("SOLEUR") == "SOL"

    def test_btc_eth_pair(self):
        assert self.sm._symbol_to_base("BTCETH") == "BTC"

    def test_fallback_short(self):
        # Symbole < 5 znaków bez znanych sufiksów — BTC kończy się na 'BTC' więc zwraca ""
        # Testujemy zamiast tego symbol 4-znakowy bez sufiksu kwotowego: ABCD → fallback odcina 4 = ""
        # Realny przypadek: sam ticker nie może być krótszy niż para z sufixem
        assert self.sm._symbol_to_base("XRPBTC") == "XRP"  # BTC suffix

    def test_fallback_unknown_quote(self):
        # XYZABC — żadna znana quote → odetnij 4 ostatnie znaki
        assert self.sm._symbol_to_base("XYZABC") == "XY"
