"""
test_trading_execution_engine.py — Testy jednostkowe dla backend/trading/execution_engine.py

Testuje:
  - IDLE → PENDING_BUY po queue_buy
  - PENDING_BUY → LONG_OPEN po on_buy_filled
  - LONG_OPEN → PENDING_SELL po queue_sell
  - PENDING_SELL → COOLDOWN po on_sell_filled
  - Blokada duplicate BUY (pending już istnieje)
  - Blokada SELL bez pozycji (IDLE)
  - Cooldown wraca do IDLE (tick_cooldowns)
  - Cooldown check w state machine
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest

from backend.trading.execution_engine import (
    CycleResult,
    ExecutionEngine,
    SymbolExecState,
    SymbolState,
    _StateRegistry,
    get_state_registry,
)
from backend.trading.trade_config import TradeConfig


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _default_cfg(**overrides) -> TradeConfig:
    cfg = TradeConfig()
    cfg.execution_enabled = True
    cfg.min_order_notional = 1.0
    cfg.min_buy_notional = 1.0
    cfg.use_oco_for_protection = False
    cfg.oco_fallback_to_two_orders = False
    cfg.allowed_quotes = ["USDC", "EUR"]
    cfg.max_losing_streak = 3
    cfg.cooldown_after_loss_streak_min = 1
    cfg.pending_order_cooldown_sec = 5
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_engine(cfg=None) -> tuple[ExecutionEngine, MagicMock, _StateRegistry]:
    """Zwraca (engine, mock_binance, fresh_registry)."""
    if cfg is None:
        cfg = _default_cfg()

    mock_bc = MagicMock()
    # get_exchange_info: minimalny zwrot
    mock_bc.get_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDC",
                "baseAsset": "BTC",
                "quoteAsset": "USDC",
                "status": "TRADING",
                "ocoAllowed": True,
                "permissions": ["SPOT"],
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.00001", "maxQty": "9000.0", "stepSize": "0.00001"},
                    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "9999999.0", "tickSize": "0.01"},
                    {"filterType": "NOTIONAL", "minNotional": "1.0", "maxNotional": "0.0", "applyMinToMarket": True},
                ],
            },
            {
                "symbol": "ETHUSDC",
                "baseAsset": "ETH",
                "quoteAsset": "USDC",
                "status": "TRADING",
                "ocoAllowed": True,
                "permissions": ["SPOT"],
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.0001", "maxQty": "9000.0", "stepSize": "0.0001"},
                    {"filterType": "PRICE_FILTER", "minPrice": "0.01", "maxPrice": "9999999.0", "tickSize": "0.01"},
                    {"filterType": "NOTIONAL", "minNotional": "1.0", "maxNotional": "0.0", "applyMinToMarket": True},
                ],
            },
        ]
    }

    # Resetuj symbol_filter cache aby uniknąć contamination między testami
    from backend.trading.symbol_filter import invalidate_cache
    invalidate_cache()

    registry = _StateRegistry()
    engine = ExecutionEngine(cfg, mock_bc)
    engine._registry = registry
    return engine, mock_bc, registry


def _db_mock_for_buy(pending_exists=False) -> MagicMock:
    """Mock DB dla queue_buy — zwraca None dla dedup check (brak istniejącego pending)."""
    db = MagicMock()
    from backend.database import PendingOrder

    # query(...).filter(...).first() dla dedup check
    first_mock = MagicMock()
    first_mock.return_value = None if not pending_exists else _make_pending_mock(1, "BTCUSDC", "BUY")
    db.query.return_value.filter.return_value.first.return_value = (
        None if not pending_exists else _make_pending_mock(1, "BTCUSDC", "BUY")
    )
    # query(...).filter(...).order_by(...).first() dla _create_pending_order dedup
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    # PendingOrder add/commit
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()

    # Fake ID po add (symuluje auto-increment)
    created_pending = _make_pending_mock(42, "BTCUSDC", "BUY")
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    return db


def _make_pending_mock(id_: int, symbol: str, side: str) -> MagicMock:
    po = MagicMock()
    po.id = id_
    po.symbol = symbol
    po.side = side
    po.status = "PENDING_CREATED"
    po.mode = "demo"
    return po


def _db_mock_for_sell(pending_sell_exists=False, pending_buy_exists=False) -> MagicMock:
    db = MagicMock()
    # dedup check SELL
    db.query.return_value.filter.return_value.first.return_value = (
        _make_pending_mock(5, "BTCUSDC", "SELL") if pending_sell_exists else None
    )
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


# ── 1. IDLE → PENDING_BUY ─────────────────────────────────────────────────────

class TestQueueBuy:
    def test_idle_to_pending_buy(self):
        """IDLE → PENDING_BUY po poprawnym queue_buy."""
        engine, mock_bc, registry = _make_engine()

        db = _db_mock_for_buy()
        # Symuluj że _create_pending_order zwróci id=42
        with patch.object(engine, "_create_pending_order", return_value=42):
            with patch.object(engine, "_get_avg_price", return_value=0.0):
                result = engine.queue_buy(
                db=db,
                symbol="BTCUSDC",
                qty=0.1,
                entry_price=100.0,
                stop_loss=96.0,
                take_profit=107.0,
                take_profit_2=110.0,
                trailing_activation=103.0,
                atr=2.0,
                mode="demo",
            )

        assert result.new_state == SymbolState.PENDING_BUY
        assert result.action_taken == "BUY_QUEUED"
        assert result.pending_order_id == 42
        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.PENDING_BUY
        assert state.pending_order_id == 42

    def test_non_idle_blocks_buy(self):
        """Jeśli symbol nie jest IDLE/CANDIDATE → blokada buy."""
        engine, mock_bc, registry = _make_engine()

        # Ręcznie ustaw stan na LONG_OPEN
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.LONG_OPEN, "test")
        registry.set(sym_state)

        db = _db_mock_for_buy()
        result = engine.queue_buy(
            db=db, symbol="BTCUSDC", qty=0.1, entry_price=100.0,
            stop_loss=96.0, take_profit=107.0, take_profit_2=110.0,
            trailing_activation=103.0, atr=2.0, mode="demo",
        )
        assert result.reason_code == "invalid_state_for_buy"
        assert result.new_state == SymbolState.LONG_OPEN  # stan nie zmienił się

    def test_cooldown_blocks_buy(self):
        """Symbol w cooldown → blokada buy."""
        engine, mock_bc, registry = _make_engine()
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.cooldown_until = time.monotonic() + 3600  # cooldown na 1h
        registry.set(sym_state)

        db = _db_mock_for_buy()
        result = engine.queue_buy(
            db=db, symbol="BTCUSDC", qty=0.1, entry_price=100.0,
            stop_loss=96.0, take_profit=107.0, take_profit_2=110.0,
            trailing_activation=103.0, atr=2.0, mode="demo",
        )
        assert result.reason_code == "cooldown_active"


# ── 2. PENDING_BUY → LONG_OPEN po fill ───────────────────────────────────────

class TestOnBuyFilled:
    def test_pending_buy_to_long_open(self):
        engine, mock_bc, registry = _make_engine()

        # Ustaw stan na PENDING_BUY
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_BUY, "test")
        sym_state.stop_loss = 96.0
        sym_state.take_profit = 107.0
        registry.set(sym_state)

        db = MagicMock()
        engine.on_buy_filled(
            db=db,
            symbol="BTCUSDC",
            mode="demo",
            position_id=7,
            exec_price=100.0,
            exec_qty=0.1,
            stop_loss=96.0,
            take_profit=107.0,
        )

        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.LONG_OPEN
        assert state.position_id == 7
        assert state.entry_price == 100.0
        assert state.quantity == 0.1
        assert state.stop_loss == 96.0
        assert state.take_profit == 107.0
        assert state.pending_order_id is None

    def test_on_buy_filled_mode_demo_no_oco(self):
        """W trybie DEMO on_buy_filled nie składa OCO na Binance."""
        cfg = _default_cfg(use_oco_for_protection=True)
        engine, mock_bc, registry = _make_engine(cfg)

        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_BUY, "test")
        registry.set(sym_state)

        db = MagicMock()
        engine.on_buy_filled(db, "BTCUSDC", "demo", 1, 100.0, 0.1, 96.0, 107.0)

        # DEMO → nie powinien wywoływać place_oco_order
        mock_bc.place_oco_order.assert_not_called()


# ── 3. LONG_OPEN → PENDING_SELL ──────────────────────────────────────────────

class TestQueueSell:
    def test_long_open_to_pending_sell(self):
        engine, mock_bc, registry = _make_engine()

        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.LONG_OPEN, "test")
        sym_state.quantity = 0.1
        sym_state.entry_price = 100.0
        registry.set(sym_state)

        db = _db_mock_for_sell()
        with patch.object(engine, "_create_pending_order", return_value=99):
            with patch.object(engine, "_get_avg_price", return_value=0.0):
                result = engine.queue_sell(
                db=db,
                symbol="BTCUSDC",
                qty=0.1,
                price=105.0,
                mode="demo",
                reason_code="take_profit_hit",
            )

        assert result.new_state == SymbolState.PENDING_SELL
        assert result.action_taken == "SELL_QUEUED"
        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.PENDING_SELL

    def test_idle_state_blocks_sell(self):
        """SELL z IDLE → blokada (nie mamy pozycji)."""
        engine, mock_bc, registry = _make_engine()
        # Stan domyślny = IDLE

        db = _db_mock_for_sell()
        result = engine.queue_sell(
            db=db, symbol="BTCUSDC", qty=0.1, price=105.0, mode="demo",
        )
        assert result.reason_code == "invalid_state_for_sell"

    def test_pending_buy_state_blocks_sell(self):
        """SELL z PENDING_BUY → blokada (zlecenie nie wypełnione)."""
        engine, mock_bc, registry = _make_engine()
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_BUY, "test")
        registry.set(sym_state)

        db = _db_mock_for_sell()
        result = engine.queue_sell(
            db=db, symbol="BTCUSDC", qty=0.1, price=105.0, mode="demo",
        )
        assert result.reason_code == "invalid_state_for_sell"

    def test_duplicate_sell_blocked(self):
        """Drugi SELL gdy pending SELL już istnieje → blokada."""
        engine, mock_bc, registry = _make_engine()
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.LONG_OPEN, "test")
        registry.set(sym_state)

        db = _db_mock_for_sell(pending_sell_exists=True)
        result = engine.queue_sell(
            db=db, symbol="BTCUSDC", qty=0.1, price=105.0, mode="demo",
        )
        assert result.reason_code == "duplicate_pending_sell"


# ── 4. PENDING_SELL → COOLDOWN po on_sell_filled ─────────────────────────────

class TestOnSellFilled:
    def test_sell_filled_to_cooldown(self):
        engine, mock_bc, registry = _make_engine()

        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_SELL, "test")
        sym_state.quantity = 0.1
        sym_state.entry_price = 100.0
        registry.set(sym_state)

        db = MagicMock()
        engine.on_sell_filled(db, "BTCUSDC", "demo", net_pnl=5.0, cooldown_sec=5)

        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.COOLDOWN
        assert state.quantity == 0.0
        assert state.position_id is None

    def test_loss_sets_risk_engine_cooldown(self):
        """Strata → risk_engine _cooldown_tracker dostaje on_loss."""
        from backend.trading.risk_engine import _cooldown_tracker

        engine, mock_bc, registry = _make_engine()
        sym_state = registry.get("SOLUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_SELL, "test")
        registry.set(sym_state)

        _cooldown_tracker.reset("SOLUSDC")

        db = MagicMock()
        engine.on_sell_filled(db, "SOLUSDC", "demo", net_pnl=-10.0, cooldown_sec=0)

        state_cd = _cooldown_tracker.get("SOLUSDC")
        assert state_cd["loss_streak"] >= 1

    def test_win_resets_risk_engine_cooldown(self):
        from backend.trading.risk_engine import _cooldown_tracker

        engine, mock_bc, registry = _make_engine()
        sym_state = registry.get("ETHUSDC", "demo")
        sym_state.transition(SymbolState.PENDING_SELL, "test")
        registry.set(sym_state)

        # Najpierw ustaw cooldown po stratach
        _cooldown_tracker.on_loss("ETHUSDC", max_streak=3, cooldown_sec=3600)
        in_cd_before, _ = _cooldown_tracker.is_in_cooldown("ETHUSDC")
        assert in_cd_before is True

        db = MagicMock()
        engine.on_sell_filled(db, "ETHUSDC", "demo", net_pnl=+5.0, cooldown_sec=0)

        in_cd_after, _ = _cooldown_tracker.is_in_cooldown("ETHUSDC")
        assert in_cd_after is False


# ── 5. Cooldown wraca do IDLE ─────────────────────────────────────────────────

class TestTickCooldowns:
    def test_expired_cooldown_returns_to_idle(self):
        engine, mock_bc, registry = _make_engine()

        # Ustaw cooldown już wygasły (0.01s temu)
        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.COOLDOWN, "test")
        sym_state.cooldown_until = time.monotonic() - 0.01
        registry.set(sym_state)

        transitioned = engine.tick_cooldowns()

        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.IDLE
        assert "BTCUSDC" in transitioned

    def test_active_cooldown_stays_in_cooldown(self):
        engine, mock_bc, registry = _make_engine()

        sym_state = registry.get("BTCUSDC", "demo")
        sym_state.transition(SymbolState.COOLDOWN, "test")
        sym_state.cooldown_until = time.monotonic() + 3600
        registry.set(sym_state)

        transitioned = engine.tick_cooldowns()

        state = registry.get("BTCUSDC", "demo")
        assert state.state == SymbolState.COOLDOWN
        assert "BTCUSDC" not in transitioned

    def test_only_cooldown_state_affected(self):
        """tick_cooldowns nie zmienia stanów innych niż COOLDOWN."""
        engine, mock_bc, registry = _make_engine()

        sym_state_long = registry.get("ETHUSDC", "demo")
        sym_state_long.transition(SymbolState.LONG_OPEN, "test")
        sym_state_long.cooldown_until = time.monotonic() - 1.0  # wygasły, ale stan to LONG_OPEN
        registry.set(sym_state_long)

        engine.tick_cooldowns()
        state = registry.get("ETHUSDC", "demo")
        assert state.state == SymbolState.LONG_OPEN  # nie zmienił


# ── 6. State registry unit tests ──────────────────────────────────────────────

class TestStateRegistry:
    def test_get_returns_idle_by_default(self):
        reg = _StateRegistry()
        state = reg.get("BTCUSDC", "demo")
        assert state.state == SymbolState.IDLE
        assert state.symbol == "BTCUSDC"

    def test_set_and_get_persist(self):
        reg = _StateRegistry()
        state = reg.get("ETHUSDC", "live")
        state.transition(SymbolState.LONG_OPEN, "test")
        reg.set(state)

        retrieved = reg.get("ETHUSDC", "live")
        assert retrieved.state == SymbolState.LONG_OPEN

    def test_mode_isolation(self):
        """DEMO i LIVE są izolowanymi stanami."""
        reg = _StateRegistry()
        demo_state = reg.get("BTCUSDC", "demo")
        demo_state.transition(SymbolState.LONG_OPEN, "test")
        reg.set(demo_state)

        live_state = reg.get("BTCUSDC", "live")
        assert live_state.state == SymbolState.IDLE

    def test_all_states_returns_all(self):
        reg = _StateRegistry()
        reg.get("BTCUSDC", "demo")
        reg.get("ETHUSDC", "demo")
        all_states = reg.all_states()
        symbols = [s.symbol for s in all_states]
        assert "BTCUSDC" in symbols
        assert "ETHUSDC" in symbols


# ── 7. SymbolExecState helpers ────────────────────────────────────────────────

class TestSymbolExecState:
    def test_is_in_cooldown_false_by_default(self):
        s = SymbolExecState(symbol="BTCUSDC")
        assert s.is_in_cooldown() is False
        assert s.cooldown_remaining_sec() == 0

    def test_is_in_cooldown_true(self):
        s = SymbolExecState(symbol="BTCUSDC")
        s.cooldown_until = time.monotonic() + 3600
        assert s.is_in_cooldown() is True
        assert s.cooldown_remaining_sec() > 0

    def test_transition_changes_state(self):
        s = SymbolExecState(symbol="BTCUSDC")
        assert s.state == SymbolState.IDLE
        s.transition(SymbolState.PENDING_BUY, "test reason")
        assert s.state == SymbolState.PENDING_BUY
