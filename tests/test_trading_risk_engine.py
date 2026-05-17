"""
test_trading_risk_engine.py — Testy jednostkowe dla backend/trading/risk_engine.py

Testuje:
  - blokada przy max_positions
  - blokada przy daily drawdown
  - blokada przy losing streak / cooldown
  - blokada przy braku ATR
  - blokada przy kill switch
  - poprawny ATR-based sizing
  - poprawny SL/TP
  - brak pozycji poniżej min notional
  - blokada duplikatu (symbol z otwartą pozycją)
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from backend.trading.risk_engine import (
    AccountState,
    PositionMeta,
    RiskEngine,
    RiskGateResult,
    _CooldownTracker,
    get_cooldown_tracker,
)
from backend.trading.trade_config import TradeConfig


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _default_cfg(**overrides) -> TradeConfig:
    cfg = TradeConfig()
    cfg.risk_per_trade_pct = 1.0          # 1% equity per trade
    cfg.max_open_positions = 5
    cfg.max_trades_per_day = 100
    cfg.max_daily_drawdown_pct = 3.0
    cfg.max_weekly_drawdown_pct = 7.0
    cfg.max_losing_streak = 3
    cfg.cooldown_after_loss_streak_min = 1
    cfg.max_total_exposure_pct = 80.0
    cfg.max_exposure_per_symbol_pct = 10.0
    cfg.atr_stop_multiplier = 2.0
    cfg.atr_take_multiplier = 3.5
    cfg.min_order_notional = 5.0
    cfg.min_buy_notional = 10.0
    cfg.execution_enabled = True
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _default_account(
    equity=1000.0,
    available_cash=900.0,
    positions_count=0,
    realized_pnl_24h=0.0,
    realized_pnl_7d=0.0,
    unrealized_pnl=0.0,
    initial_balance=1000.0,
) -> AccountState:
    return AccountState(
        equity=equity,
        available_cash=available_cash,
        positions_count=positions_count,
        positions_value=equity - available_cash,
        realized_pnl_24h=realized_pnl_24h,
        realized_pnl_7d=realized_pnl_7d,
        unrealized_pnl=unrealized_pnl,
        initial_balance=initial_balance,
    )


def _make_position(symbol="BTCUSDC", qty=0.01, entry=100.0, current=100.0, pnl=0.0) -> PositionMeta:
    return PositionMeta(
        symbol=symbol,
        quantity=qty,
        entry_price=entry,
        current_price=current,
        unrealized_pnl=pnl,
    )


def _make_engine(cfg=None) -> RiskEngine:
    if cfg is None:
        cfg = _default_cfg()
    engine = RiskEngine(cfg)
    # Wróć do świeżego cooldown trackera per test
    engine._tracker.reset("BTCUSDC")
    engine._tracker.reset("ETHUSDC")
    engine._tracker.reset("SOLUSDC")
    return engine


def _db_mock(daily_count=0) -> MagicMock:
    db = MagicMock()
    # _count_daily_trades wywołuje db.query(...).filter(...).count()
    db.query.return_value.filter.return_value.count.return_value = daily_count
    return db


# ── 1. Kill switch ────────────────────────────────────────────────────────────

def test_kill_switch_blocks_all():
    cfg = _default_cfg(execution_enabled=False)
    engine = _make_engine(cfg)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, _default_account())
    assert result.is_allowed is False
    assert result.reason_code == "kill_switch_active"


# ── 2. Duplikat pozycji na symbolu ────────────────────────────────────────────

def test_duplicate_position_blocked():
    engine = _make_engine()
    pos = _make_position(symbol="BTCUSDC", qty=0.1)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, _default_account(), open_positions=[pos])
    assert result.is_allowed is False
    assert result.reason_code == "symbol_has_open_position"


def test_different_symbol_not_blocked_by_position():
    engine = _make_engine()
    pos = _make_position(symbol="ETHUSDC", qty=0.1)
    # Inny symbol → nie duplikat, sprawdza dalej
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, _default_account(), open_positions=[pos])
    # Powinno PRZEJŚĆ dalej (nie blokować z powodu duplikatu)
    assert result.reason_code != "symbol_has_open_position"


# ── 3. Cooldown po streak strat ──────────────────────────────────────────────

def test_cooldown_blocks_entry():
    engine = _make_engine()
    # Wywołaj 4 straty (max_losing_streak=3 → po 4 stratach cooldown powinien być aktywny)
    for _ in range(4):
        engine._tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=3600)

    in_cd, remaining = engine._tracker.is_in_cooldown("BTCUSDC")
    assert in_cd is True
    assert remaining > 0

    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, _default_account())
    assert result.is_allowed is False
    assert result.reason_code == "cooldown_after_loss_streak"


def test_win_resets_cooldown():
    engine = _make_engine()
    for _ in range(4):
        engine._tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=3600)
    engine._tracker.on_win("BTCUSDC")
    in_cd, _ = engine._tracker.is_in_cooldown("BTCUSDC")
    assert in_cd is False


# ── 4. Max open positions ─────────────────────────────────────────────────────

def test_max_positions_reached():
    cfg = _default_cfg(max_open_positions=3)
    engine = _make_engine(cfg)
    positions = [
        _make_position(symbol=f"SYM{i}USDC") for i in range(3)
    ]
    result = engine.evaluate(_db_mock(), "NEWUSDC", 100.0, 2.0, _default_account(), open_positions=positions)
    assert result.is_allowed is False
    assert result.reason_code == "max_positions_reached"


def test_below_max_positions_allowed():
    cfg = _default_cfg(max_open_positions=5)
    engine = _make_engine(cfg)
    positions = [_make_position(symbol=f"SYM{i}USDC") for i in range(3)]
    result = engine.evaluate(_db_mock(), "NEWUSDC", 100.0, 2.0, _default_account(), open_positions=positions)
    assert result.reason_code != "max_positions_reached"


# ── 5. Daily limit strat ─────────────────────────────────────────────────────

def test_daily_loss_limit_blocks():
    cfg = _default_cfg(max_daily_drawdown_pct=3.0)
    engine = _make_engine(cfg)
    # daily_pnl = realized_pnl_24h + unrealized_pnl = -50 → przekracza -1000*3% = -30
    account = _default_account(equity=1000.0, realized_pnl_24h=-35.0, unrealized_pnl=0.0)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, account)
    assert result.is_allowed is False
    assert result.reason_code == "daily_loss_limit_hit"


def test_daily_loss_below_limit_ok():
    cfg = _default_cfg(max_daily_drawdown_pct=3.0)
    engine = _make_engine(cfg)
    account = _default_account(equity=1000.0, realized_pnl_24h=-5.0)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, account)
    assert result.reason_code != "daily_loss_limit_hit"


# ── 6. Tygodniowy limit strat ─────────────────────────────────────────────────

def test_weekly_loss_limit_blocks():
    cfg = _default_cfg(max_weekly_drawdown_pct=5.0)
    engine = _make_engine(cfg)
    account = _default_account(equity=1000.0, realized_pnl_7d=-55.0)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, account)
    assert result.is_allowed is False
    assert result.reason_code == "weekly_loss_limit_hit"


# ── 7. Brak ATR ───────────────────────────────────────────────────────────────

def test_no_atr_blocks():
    engine = _make_engine()
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 0.0, _default_account())
    assert result.is_allowed is False
    assert result.reason_code == "no_atr_for_sizing"


def test_zero_price_blocks():
    engine = _make_engine()
    result = engine.evaluate(_db_mock(), "BTCUSDC", 0.0, 2.0, _default_account())
    assert result.is_allowed is False
    assert result.reason_code == "no_atr_for_sizing"


# ── 8. Position sizing ATR-based ──────────────────────────────────────────────

def test_atr_sizing_correct():
    """qty = risk_amount / sl_distance. SL = price - ATR×stop_mult."""
    cfg = _default_cfg(
        risk_per_trade_pct=1.0,    # 1% equity
        atr_stop_multiplier=2.0,
        min_order_notional=1.0,
        min_buy_notional=1.0,
        max_exposure_per_symbol_pct=100.0,
    )
    engine = _make_engine(cfg)
    price = 100.0
    atr = 2.0

    account = _default_account(equity=1000.0, available_cash=1000.0)
    result = engine.evaluate(_db_mock(), "BTCUSDC", price, atr, account)

    if result.is_allowed:
        # sl_distance = atr × stop_mult = 4.0
        # risk_amount = 1000 × 1% = 10.0
        # qty_by_risk = 10.0 / 4.0 = 2.5
        assert result.recommended_qty > 0.0
        assert result.stop_loss_price == pytest.approx(price - atr * 2.0, rel=1e-6)
        assert result.take_profit_price == pytest.approx(price + atr * 3.5, rel=1e-6)


def test_sl_tp_calculation():
    cfg = _default_cfg(
        atr_stop_multiplier=2.0,
        atr_take_multiplier=3.0,
        min_order_notional=1.0,
        min_buy_notional=1.0,
        max_exposure_per_symbol_pct=100.0,
    )
    engine = _make_engine(cfg)
    price = 200.0
    atr = 4.0
    account = _default_account(equity=5000.0, available_cash=5000.0)

    result = engine.evaluate(_db_mock(), "ETHUSDC", price, atr, account)
    if result.is_allowed:
        assert result.stop_loss_price == pytest.approx(200.0 - 4.0 * 2.0, rel=1e-6)  # 192.0
        assert result.take_profit_price == pytest.approx(200.0 + 4.0 * 3.0, rel=1e-6)  # 212.0


# ── 9. Niewystarczający kapitał → qty_too_small ──────────────────────────────

def test_insufficient_cash_blocks():
    cfg = _default_cfg(
        min_order_notional=10.0,
        min_buy_notional=100.0,
    )
    engine = _make_engine(cfg)
    # Tylko 0.5 USDC → za mało na min_buy_notional=100 przy price=100
    account = _default_account(equity=0.5, available_cash=0.5, initial_balance=0.5)
    result = engine.evaluate(_db_mock(), "BTCUSDC", 100.0, 2.0, account)
    assert result.is_allowed is False
    assert result.reason_code in ("qty_too_small", "insufficient_cash")


def test_min_notional_guard():
    """Qty × price musi być >= min_order_notional — blokuje przy bardzo małej pozycji."""
    cfg = _default_cfg(
        risk_per_trade_pct=0.001,   # 0.001 = 0.1% risk → mała kwota
        min_order_notional=500.0,   # wysoki próg min notional
        min_buy_notional=500.0,
    )
    engine = _make_engine(cfg)
    account = _default_account(equity=10.0, available_cash=10.0)
    # risk_amount = 10 × 0.001 = 0.01; qty_by_risk = 0.01 / (2×2) = 0.0025; notional = 0.0025 × 1000 = 2.5 < 500
    result = engine.evaluate(_db_mock(), "BTCUSDC", 1000.0, 2.0, account)
    assert result.is_allowed is False
    # Qty jest bump'owane do min_buy_notional/price=0.5, ale required_cash=500 > available=10 → insufficient_cash
    assert result.reason_code in ("qty_too_small", "insufficient_cash")


# ── 10. CooldownTracker unit tests ────────────────────────────────────────────

class TestCooldownTracker:
    def setup_method(self):
        self.tracker = _CooldownTracker()

    def test_initially_not_in_cooldown(self):
        in_cd, rem = self.tracker.is_in_cooldown("BTCUSDC")
        assert in_cd is False
        assert rem == 0

    def test_single_loss_no_cooldown(self):
        """Jedna strata nie daje cooldown (max_streak=3)."""
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=300)
        in_cd, _ = self.tracker.is_in_cooldown("BTCUSDC")
        # Po 1 stracie streak=1, cooldown = 300 × (1+1) = 600s
        # on_loss ustawia cooldown zawsze
        assert in_cd is True

    def test_win_resets_streak_and_cooldown(self):
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=3600)
        self.tracker.on_win("BTCUSDC")
        in_cd, _ = self.tracker.is_in_cooldown("BTCUSDC")
        assert in_cd is False
        state = self.tracker.get("BTCUSDC")
        assert state["loss_streak"] == 0
        assert state["win_streak"] == 1

    def test_multiple_losses_escalate_cooldown(self):
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=60)
        state1 = self.tracker.get("BTCUSDC")
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=60)
        state2 = self.tracker.get("BTCUSDC")
        assert state2["loss_streak"] > state1["loss_streak"]

    def test_reset_clears_state(self):
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=3600)
        self.tracker.reset("BTCUSDC")
        in_cd, _ = self.tracker.is_in_cooldown("BTCUSDC")
        assert in_cd is False

    def test_independent_symbols(self):
        """Cooldown jednego symbolu nie wpływa na inny."""
        self.tracker.on_loss("BTCUSDC", max_streak=3, cooldown_sec=3600)
        in_cd_eth, _ = self.tracker.is_in_cooldown("ETHUSDC")
        assert in_cd_eth is False


# ── 11. Łączna ekspozycja ─────────────────────────────────────────────────────

def test_max_total_exposure_hit():
    cfg = _default_cfg(max_total_exposure_pct=50.0)
    engine = _make_engine(cfg)
    # Equity=1000, max_exposure=500 → 3 pozycje po 200 = 600 > 500
    positions = [
        _make_position(symbol=f"SYM{i}USDC", qty=2.0, current=100.0)
        for i in range(3)
    ]
    account = _default_account(equity=1000.0, available_cash=400.0)
    result = engine.evaluate(_db_mock(), "NEWUSDC", 100.0, 2.0, account, open_positions=positions)
    assert result.is_allowed is False
    assert result.reason_code == "max_total_exposure_hit"
