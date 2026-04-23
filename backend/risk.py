"""
Risk layer that consumes accounting snapshots and runtime settings.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.accounting import (
    compute_activity_snapshot,
    compute_risk_snapshot,
    compute_strategy_performance,
    compute_symbol_performance,
)
from backend.database import Order, utc_now_naive
from backend.runtime_settings import get_runtime_config


@dataclass
class RiskContext:
    symbol: str
    mode: str
    side: str
    notional: float
    strategy_name: str
    runtime_config: Dict[str, Any]
    risk_snapshot: Dict[str, Any]
    activity_snapshot: Dict[str, Any]
    symbol_performance: Dict[str, Any]
    strategy_performance: Dict[str, Any]
    config_snapshot_id: Optional[str] = None
    open_positions_count: int = 0
    signal_summary: Optional[Dict[str, Any]] = None
    symbol_loss_streak: int = 0
    symbol_cooldown_active: bool = False
    symbol_cooldown_until: Optional[str] = None


@dataclass
class RiskDecision:
    allowed: bool
    action: str
    reason_codes: List[str]
    risk_score: float
    cooldown_active: bool
    kill_switch_active: bool
    position_size_multiplier: float
    limit_breaches: List[str]
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


@dataclass
class TradeCostEstimate:
    fee_entry_pct: float
    fee_exit_pct: float
    spread_pct: float
    slippage_pct: float
    safety_buffer_pct: float = 0.0

    @property
    def total_cost_pct(self) -> float:
        return (
            float(self.fee_entry_pct)
            + float(self.fee_exit_pct)
            + float(self.spread_pct)
            + float(self.slippage_pct)
            + float(self.safety_buffer_pct)
        )


@dataclass
class RegimeState:
    regime: str
    confidence: float
    reasons: List[str]


@dataclass
class EntryDecision:
    allowed: bool
    score: float
    reasons: List[str]
    regime: str
    expected_move_pct: float
    total_cost_pct: float
    risk_reward: float


@dataclass
class PositionPlan:
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    trailing_activation_price: float
    break_even_after_tp1: bool = True
    break_even_price: float = 0.0


@dataclass
class PositionManagerDecision:
    action: str
    reason_code: str
    reasons: List[str]
    stop_loss: float
    trailing_active: bool
    trailing_stop_price: Optional[float]
    partial_take_fraction: float = 0.0
    move_stop_to_break_even: bool = False


def estimate_trade_costs(
    runtime_config: Dict[str, Any],
    *,
    spread_pct: float = 0.0,
    slippage_pct: Optional[float] = None,
    fee_entry_pct: Optional[float] = None,
    fee_exit_pct: Optional[float] = None,
    safety_buffer_pct: float = 0.0,
) -> TradeCostEstimate:
    taker_fee = _safe_float(runtime_config.get("taker_fee_rate"), 0.001) * 100.0
    slip = _safe_float(runtime_config.get("slippage_bps"), 5.0) / 100.0
    spread = _safe_float(runtime_config.get("spread_buffer_bps"), 3.0) / 100.0
    return TradeCostEstimate(
        fee_entry_pct=_safe_float(fee_entry_pct, taker_fee),
        fee_exit_pct=_safe_float(fee_exit_pct, taker_fee),
        spread_pct=_safe_float(spread_pct, spread),
        slippage_pct=_safe_float(slippage_pct, slip),
        safety_buffer_pct=_safe_float(safety_buffer_pct, safety_buffer_pct),
    )


def detect_regime(
    *,
    price: float,
    ema21_15m: Optional[float],
    ema50_15m: Optional[float],
    ema21_1h: Optional[float],
    ema50_1h: Optional[float],
    ema200_1h: Optional[float],
    rsi_15m: Optional[float],
    macd_hist_15m: Optional[float],
    volume_ratio_15m: Optional[float],
) -> RegimeState:
    reasons: List[str] = []
    volume_ratio = 1.0 if volume_ratio_15m is None else float(volume_ratio_15m)
    macd_hist = 0.0 if macd_hist_15m is None else float(macd_hist_15m)
    ema200 = float(ema200_1h) if ema200_1h is not None else float(ema50_1h or 0.0)

    trend_up = (
        price > _safe_float(ema50_15m)
        and _safe_float(ema21_15m) > _safe_float(ema50_15m)
        and _safe_float(ema21_1h) > _safe_float(ema50_1h) > ema200
        and rsi_15m is not None
        and 52 <= float(rsi_15m) <= 72
        and macd_hist >= 0
        and volume_ratio >= 1.05
    )
    trend_down = (
        price < _safe_float(ema50_15m)
        and _safe_float(ema21_15m) < _safe_float(ema50_15m)
        and _safe_float(ema21_1h) < _safe_float(ema50_1h) < max(ema200, 1e-12)
        and rsi_15m is not None
        and float(rsi_15m) <= 48
        and macd_hist <= 0
    )

    if trend_up:
        reasons.append("Aligned uptrend on 15m and 1h")
        return RegimeState("TREND_UP", 0.82, reasons)
    if trend_down:
        reasons.append("Aligned downtrend on 15m and 1h")
        return RegimeState("TREND_DOWN", 0.82, reasons)
    if (
        rsi_15m is None
        or ema21_15m is None
        or ema50_15m is None
        or ema21_1h is None
        or ema50_1h is None
    ):
        reasons.append("Missing confirmation data across timeframes")
        return RegimeState("CHAOS", 0.25, reasons)
    reasons.append("Mixed signals or range-like conditions")
    return RegimeState("RANGE", 0.45, reasons)


def validate_long_entry(
    *,
    regime: str,
    signal_score: float,
    expected_move_pct: float,
    risk_reward: float,
    costs: TradeCostEstimate,
    min_score: float = 72.0,
    min_rr: float = 2.0,
    min_profit_buffer_pct: float = 0.0,
    allow_range: bool = False,
) -> EntryDecision:
    reasons: List[str] = []
    total_cost_pct = costs.total_cost_pct
    # Dla mocnych sygnałów w TREND_UP dopuszczamy nieco ciaśniejszy bufor,
    # bez globalnego luzowania dla słabych setupów.
    required_move_mult = 1.3
    if regime == "TREND_UP" and signal_score >= max(min_score + 10.0, 65.0):
        required_move_mult = 1.2
    required_move = max(
        total_cost_pct * required_move_mult,
        total_cost_pct + min_profit_buffer_pct,
    )

    if regime not in {"TREND_UP", "RANGE"}:
        reasons.append(f"Regime {regime} blocks spot long entries")
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    if regime == "RANGE" and not allow_range:
        reasons.append("Range regime requires a stronger edge; default is NO_TRADE")
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    if signal_score < min_score:
        reasons.append("Signal score below threshold")
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    if risk_reward < min_rr:
        reasons.append("Risk-reward below minimum")
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    max_cost_share = 0.50
    if regime == "TREND_UP" and signal_score >= max(min_score + 5.0, 60.0):
        max_cost_share = 0.55
    if total_cost_pct > (expected_move_pct * max_cost_share):
        reasons.append(
            f"Total costs exceed {int(max_cost_share * 100)}% of expected move"
        )
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    if expected_move_pct <= required_move:
        reasons.append("Expected move too small after costs")
        return EntryDecision(
            False,
            signal_score,
            reasons,
            regime,
            expected_move_pct,
            total_cost_pct,
            risk_reward,
        )
    reasons.append("Entry validated")
    return EntryDecision(
        True,
        signal_score,
        reasons,
        regime,
        expected_move_pct,
        total_cost_pct,
        risk_reward,
    )


def can_sell(position_qty: float) -> tuple[bool, str]:
    if _safe_float(position_qty) <= 0:
        return False, "Cannot SELL without an open position"
    return True, "OK"


def build_long_plan(
    *,
    entry: float,
    atr: float,
    costs: TradeCostEstimate,
    rr1: float = 2.0,
    rr2: float = 3.2,
) -> PositionPlan:
    stop_distance = max(float(atr) * 1.2, float(entry) * 0.008)
    stop_loss = float(entry) - stop_distance
    risk_per_unit = float(entry) - stop_loss
    break_even_price = float(entry) * (1 + (costs.total_cost_pct / 100.0))
    return PositionPlan(
        entry=float(entry),
        stop_loss=stop_loss,
        take_profit_1=float(entry) + risk_per_unit * rr1,
        take_profit_2=float(entry) + risk_per_unit * rr2,
        trailing_activation_price=float(entry) + risk_per_unit * 1.5,
        break_even_price=break_even_price,
    )


def manage_long_position(
    *,
    plan: PositionPlan,
    current_price: float,
    atr: float,
    highest_price_seen: Optional[float] = None,
    trailing_active: bool = False,
    trailing_stop_price: Optional[float] = None,
    partial_take_count: int = 0,
    regime: str = "TREND_UP",
    macd_hist_15m: Optional[float] = None,
    volume_ratio_15m: Optional[float] = None,
    close_below_ema50_15m: bool = False,
    min_net_profit_pct: float = 0.8,
    risk_kill_switch: bool = False,
    trail_atr_mult: float = 1.0,
) -> PositionManagerDecision:
    reasons: List[str] = []
    highest = max(_safe_float(highest_price_seen, plan.entry), float(current_price))
    active_trail = bool(trailing_active)
    trail_price = trailing_stop_price
    pnl_pct = (
        ((float(current_price) - plan.entry) / plan.entry * 100.0)
        if plan.entry > 0
        else 0.0
    )

    if risk_kill_switch:
        reasons.append("Risk kill switch triggered")
        return PositionManagerDecision(
            "SELL",
            "risk_kill_switch",
            reasons,
            plan.stop_loss,
            active_trail,
            trail_price,
        )
    if float(current_price) <= float(plan.stop_loss):
        reasons.append("Hard stop loss hit")
        return PositionManagerDecision(
            "SELL", "stop_loss_hit", reasons, plan.stop_loss, active_trail, trail_price
        )
    if (
        active_trail
        and trail_price is not None
        and float(current_price) <= float(trail_price)
    ):
        reasons.append("Trailing stop hit after profit protection")
        return PositionManagerDecision(
            "SELL",
            "trailing_stop_hit",
            reasons,
            plan.stop_loss,
            active_trail,
            trail_price,
        )
    if partial_take_count < 1 and float(current_price) >= float(plan.take_profit_1):
        reasons.append("TP1 hit")
        return PositionManagerDecision(
            "REDUCE",
            "take_profit_1_hit",
            reasons,
            max(plan.stop_loss, plan.break_even_price),
            True,
            max(
                plan.break_even_price,
                float(current_price) - float(atr) * float(trail_atr_mult),
            ),
            partial_take_fraction=0.3,
            move_stop_to_break_even=True,
        )
    if float(current_price) >= float(plan.trailing_activation_price):
        active_trail = True
        candidate_trail = highest - float(atr) * float(trail_atr_mult)
        trail_price = max(plan.break_even_price, candidate_trail)
        reasons.append("Trailing activated after profit threshold")
    invalidation = (
        close_below_ema50_15m
        and (macd_hist_15m is not None and float(macd_hist_15m) < 0)
        and (volume_ratio_15m is not None and float(volume_ratio_15m) >= 1.05)
        and regime in {"TREND_DOWN", "RANGE", "CHAOS"}
    )
    if invalidation and pnl_pct >= float(min_net_profit_pct):
        reasons.append("Trend invalidation confirmed")
        return PositionManagerDecision(
            "SELL",
            "trend_invalidation",
            reasons,
            plan.stop_loss,
            active_trail,
            trail_price,
        )
    reasons.append("Plan remains valid; ignore minor pullback")
    return PositionManagerDecision(
        "HOLD", "hold_plan_valid", reasons, plan.stop_loss, active_trail, trail_price
    )


def get_symbol_loss_streak(db: Session, *, symbol: str, mode: str = "demo") -> int:
    rows = (
        db.query(Order)
        .filter(
            Order.symbol == symbol,
            Order.mode == mode,
            Order.status == "FILLED",
            Order.side == "SELL",
        )
        .order_by(Order.timestamp.desc(), Order.id.desc())
        .all()
    )
    streak = 0
    for order in rows:
        if _safe_float(order.net_pnl, _safe_float(order.gross_pnl)) < 0:
            streak += 1
        else:
            break
    return streak


def get_symbol_cooldown_status(
    db: Session,
    *,
    symbol: str,
    mode: str = "demo",
    runtime_config: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    cfg = runtime_config or {}
    now = now or utc_now_naive()
    cooldown_minutes = int(cfg.get("cooldown_after_loss_streak_minutes", 15))
    loss_streak = get_symbol_loss_streak(db, symbol=symbol, mode=mode)
    last_sell = (
        db.query(Order)
        .filter(
            Order.symbol == symbol,
            Order.mode == mode,
            Order.status == "FILLED",
            Order.side == "SELL",
        )
        .order_by(Order.timestamp.desc(), Order.id.desc())
        .first()
    )
    if not last_sell or last_sell.timestamp is None:
        return {"active": False, "loss_streak": loss_streak, "until": None}
    last_net = _safe_float(last_sell.net_pnl, _safe_float(last_sell.gross_pnl))
    if last_net >= 0:
        return {"active": False, "loss_streak": loss_streak, "until": None}
    multiplier = min(max(loss_streak, 1), 3)
    cooldown_until = last_sell.timestamp + timedelta(
        minutes=cooldown_minutes * multiplier
    )
    return {
        "active": now < cooldown_until,
        "loss_streak": loss_streak,
        "until": cooldown_until.isoformat(),
    }


def _find_summary(items: List[Dict[str, Any]], key: str, value: str) -> Dict[str, Any]:
    target = (value or "").lower()
    for item in items:
        if str(item.get(key) or "").lower() == target:
            return item
    return {}


def build_risk_context(
    db: Session,
    *,
    symbol: str,
    side: str,
    notional: float,
    strategy_name: str = "default",
    mode: str = "demo",
    runtime_config: Optional[Dict[str, Any]] = None,
    config_snapshot_id: Optional[str] = None,
    signal_summary: Optional[Dict[str, Any]] = None,
) -> RiskContext:
    runtime_config = runtime_config or get_runtime_config(db)
    risk_snapshot = compute_risk_snapshot(db, mode=mode)
    activity_snapshot = compute_activity_snapshot(db, mode=mode)
    symbol_performance = _find_summary(
        compute_symbol_performance(db, mode=mode), "symbol", symbol
    )
    strategy_performance = _find_summary(
        compute_strategy_performance(db, mode=mode), "strategy_name", strategy_name
    )
    symbol_cooldown = get_symbol_cooldown_status(
        db,
        symbol=symbol,
        mode=mode,
        runtime_config=runtime_config,
    )
    return RiskContext(
        symbol=symbol,
        mode=mode,
        side=side,
        notional=float(notional or 0.0),
        strategy_name=strategy_name,
        runtime_config=runtime_config,
        risk_snapshot=risk_snapshot,
        activity_snapshot=activity_snapshot,
        symbol_performance=symbol_performance,
        strategy_performance=strategy_performance,
        config_snapshot_id=config_snapshot_id,
        open_positions_count=int(risk_snapshot.get("open_positions_count") or 0),
        signal_summary=signal_summary or {},
        symbol_loss_streak=int(symbol_cooldown.get("loss_streak") or 0),
        symbol_cooldown_active=bool(symbol_cooldown.get("active")),
        symbol_cooldown_until=symbol_cooldown.get("until"),
    )


def evaluate_risk(context: RiskContext) -> RiskDecision:
    cfg = context.runtime_config
    rs = context.risk_snapshot
    activity = context.activity_snapshot
    symbol_perf = context.symbol_performance or {}
    strategy_perf = context.strategy_performance or {}

    reason_codes: List[str] = []
    limit_breaches: List[str] = []
    action = "allow"
    allowed = True
    position_size_multiplier = 1.0
    cooldown_active = False

    # Debug override (tylko testy/manual debug): pozwala sprawdzić pełny flow BUY
    # bez blokad risk engine. Domyślnie wyłączone.
    force_allow_debug = (
        str(os.getenv("RISK_FORCE_ALLOW_ENTRY_DEBUG", "false")).strip().lower()
        == "true"
    )
    if force_allow_debug and context.side.upper() == "BUY":
        return RiskDecision(
            allowed=True,
            action="force_allow_debug",
            reason_codes=["forced_entry_debug_override"],
            risk_score=0.0,
            cooldown_active=False,
            kill_switch_active=False,
            position_size_multiplier=1.0,
            limit_breaches=[],
            payload={
                "symbol": context.symbol,
                "strategy_name": context.strategy_name,
                "config_snapshot_id": context.config_snapshot_id,
                "debug_override": True,
                "debug_env": "RISK_FORCE_ALLOW_ENTRY_DEBUG",
                "risk_snapshot": rs,
                "activity_snapshot": activity,
                "symbol_performance": symbol_perf,
                "strategy_performance": strategy_perf,
            },
        )

    kill_switch_active = bool(cfg.get("kill_switch_enabled")) and bool(
        rs.get("kill_switch_triggered")
    )
    if kill_switch_active:
        allowed = False
        action = "trigger_kill_switch"
        reason_codes.append("kill_switch_gate")
        limit_breaches.append("kill_switch_gate")

    max_daily_drawdown = float(cfg.get("max_daily_drawdown", 0.03))
    if context.mode == "demo":
        _initial_balance = max(
            1.0, float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
        )
        daily_drawdown_ratio = (
            abs(float(rs.get("daily_net_drawdown") or 0.0)) / _initial_balance
        )
    else:
        # LIVE: używamy całkowitego zaangażowania (exposure) lub fallback na live_balance_eur
        _exposure = float(rs.get("total_exposure") or 0.0)
        _live_balance = float(
            cfg.get("live_balance_eur") or os.getenv("LIVE_INITIAL_BALANCE", "0") or 0.0
        )
        _base = max(1.0, _exposure if _exposure > 0 else _live_balance)
        daily_drawdown_ratio = abs(float(rs.get("daily_net_drawdown") or 0.0)) / _base
    if allowed and daily_drawdown_ratio >= max_daily_drawdown:
        allowed = False
        action = "block_temporarily"
        reason_codes.append("daily_net_drawdown_gate")
        limit_breaches.append("daily_net_drawdown_gate")

    loss_streak_limit = int(cfg.get("loss_streak_limit", 3))
    loss_streak = int(rs.get("loss_streak_net") or 0)
    symbol_loss_streak_limit = min(3, max(1, loss_streak_limit))
    if allowed and loss_streak >= loss_streak_limit:
        allowed = False
        action = "block_temporarily"
        cooldown_active = True
        reason_codes.append("loss_streak_gate")
        limit_breaches.append("loss_streak_gate")

    if allowed and context.side.upper() == "BUY" and context.symbol_cooldown_active:
        allowed = False
        action = "block_symbol"
        cooldown_active = True
        reason_codes.append("symbol_cooldown_gate")
        limit_breaches.append("symbol_cooldown_gate")

    if (
        allowed
        and context.side.upper() == "BUY"
        and context.symbol_loss_streak >= symbol_loss_streak_limit
    ):
        allowed = False
        action = "block_symbol"
        cooldown_active = True
        reason_codes.append("symbol_loss_streak_gate")
        limit_breaches.append("symbol_loss_streak_gate")

    max_open_positions = int(cfg.get("max_open_positions", 3))
    signal_summary = context.signal_summary or {}
    position_action = str(signal_summary.get("position_action") or "").lower()
    allow_rotation_override = bool(signal_summary.get("portfolio_rotation_candidate"))
    allow_add_or_rebalance = position_action in {"add_to_position", "rebalance"}
    legacy_slot_block = bool(cfg.get("legacy_max_open_positions_block", False))
    if (
        legacy_slot_block
        and allowed
        and context.side.upper() == "BUY"
        and context.open_positions_count >= max_open_positions
        and not allow_rotation_override
        and not allow_add_or_rebalance
    ):
        allowed = False
        action = "block_temporarily"
        reason_codes.append("max_open_positions_gate")
        limit_breaches.append("max_open_positions_gate")

    trades_24h = int(activity.get("trades_24h") or 0)
    if allowed and trades_24h >= int(cfg.get("max_trades_per_day", 20)):
        allowed = False
        action = "block_temporarily"
        reason_codes.append("activity_gate_day")
        limit_breaches.append("activity_gate_day")

    symbol_trades_1h = int((activity.get("by_symbol_1h") or {}).get(context.symbol, 0))
    if allowed and symbol_trades_1h >= int(
        cfg.get("max_trades_per_hour_per_symbol", 2)
    ):
        allowed = False
        action = "block_symbol"
        reason_codes.append("activity_gate_symbol_hour")
        limit_breaches.append("activity_gate_symbol_hour")

    initial_balance = (
        float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
        if context.mode == "demo"
        else 0.0
    )
    total_exposure_ratio = (
        (float(rs.get("total_exposure") or 0.0) / initial_balance)
        if initial_balance > 0
        else 0.0
    )
    if allowed and total_exposure_ratio >= float(
        cfg.get("max_total_exposure_ratio", 0.8)
    ):
        allowed = False
        action = "block_temporarily"
        reason_codes.append("exposure_gate_total")
        limit_breaches.append("exposure_gate_total")

    symbol_exposure_ratio = (
        (
            float((rs.get("exposure_per_symbol") or {}).get(context.symbol, 0.0))
            / initial_balance
        )
        if initial_balance > 0
        else 0.0
    )
    if allowed and symbol_exposure_ratio >= float(
        cfg.get("max_symbol_exposure_ratio", 0.35)
    ):
        allowed = False
        action = "block_symbol"
        reason_codes.append("exposure_gate_symbol")
        limit_breaches.append("exposure_gate_symbol")

    max_cost_leakage_ratio = float(cfg.get("max_cost_leakage_ratio", 0.5))
    leakage_min_trades = int(cfg.get("leakage_gate_min_trades", 5))
    sym_closed_trades = int(symbol_perf.get("closed_trades") or 0)
    if (
        allowed
        and sym_closed_trades >= leakage_min_trades
        and float(symbol_perf.get("cost_leakage_ratio") or 0.0) > max_cost_leakage_ratio
    ):
        allowed = False
        action = "block_symbol"
        reason_codes.append("leakage_gate_symbol")
        limit_breaches.append("leakage_gate_symbol")

    min_symbol_net_expectancy = float(cfg.get("min_symbol_net_expectancy", 0.0))
    expectancy_min_trades = int(cfg.get("expectancy_gate_min_trades", 5))
    if (
        allowed
        and sym_closed_trades >= expectancy_min_trades
        and float(symbol_perf.get("net_expectancy") or 0.0) < min_symbol_net_expectancy
    ):
        allowed = False
        action = "block_symbol"
        reason_codes.append("expectancy_gate_symbol")
        limit_breaches.append("expectancy_gate_symbol")

    strat_closed_trades = (
        int(strategy_perf.get("closed_trades") or 0) if strategy_perf else 0
    )
    if (
        allowed
        and strategy_perf
        and strat_closed_trades >= expectancy_min_trades
        and float(strategy_perf.get("net_expectancy") or 0.0)
        < min_symbol_net_expectancy
    ):
        allowed = False
        action = "block_strategy"
        reason_codes.append("expectancy_gate_strategy")
        limit_breaches.append("expectancy_gate_strategy")

    if (
        allowed
        and total_exposure_ratio
        >= float(cfg.get("max_total_exposure_ratio", 0.8)) * 0.85
    ):
        position_size_multiplier = min(position_size_multiplier, 0.5)
        action = "allow_with_reduced_size"
        reason_codes.append("exposure_size_reduction")

    if allowed and loss_streak == max(0, loss_streak_limit - 1):
        position_size_multiplier = min(position_size_multiplier, 0.5)
        action = "allow_with_reduced_size"
        reason_codes.append("loss_streak_size_reduction")

    if (
        allowed
        and context.side.upper() == "BUY"
        and context.symbol_loss_streak == max(0, symbol_loss_streak_limit - 1)
    ):
        position_size_multiplier = min(position_size_multiplier, 0.5)
        action = "allow_with_reduced_size"
        reason_codes.append("symbol_loss_streak_size_reduction")

    risk_score = min(
        1.0,
        max(
            daily_drawdown_ratio / max(max_daily_drawdown, 1e-9),
            total_exposure_ratio
            / max(float(cfg.get("max_total_exposure_ratio", 0.8)), 1e-9),
            symbol_exposure_ratio
            / max(float(cfg.get("max_symbol_exposure_ratio", 0.35)), 1e-9),
            float(symbol_perf.get("cost_leakage_ratio") or 0.0)
            / max(max_cost_leakage_ratio, 1e-9),
        ),
    )

    if not reason_codes:
        reason_codes.append("risk_ok")

    return RiskDecision(
        allowed=allowed,
        action=action,
        reason_codes=reason_codes,
        risk_score=float(risk_score),
        cooldown_active=cooldown_active,
        kill_switch_active=kill_switch_active,
        position_size_multiplier=float(position_size_multiplier),
        limit_breaches=limit_breaches,
        payload={
            "symbol": context.symbol,
            "strategy_name": context.strategy_name,
            "config_snapshot_id": context.config_snapshot_id,
            "symbol_loss_streak": context.symbol_loss_streak,
            "symbol_cooldown_active": context.symbol_cooldown_active,
            "symbol_cooldown_until": context.symbol_cooldown_until,
            "risk_snapshot": rs,
            "activity_snapshot": activity,
            "symbol_performance": symbol_perf,
            "strategy_performance": strategy_perf,
        },
    )


# ---------------------------------------------------------------------------
# Asset-level bias — spójna ocena dla aktywa bazowego (np. BTC niezależnie
# od quote: EUR lub USDC).
# Zapobiega sytuacji gdy BTCEUR jest zamknięte z "direction_change",
# a system natychmiast poleca BTCUSDC jako BUY.
# ---------------------------------------------------------------------------

# Kody exit powodów, które blokują reentry na poziomie asset-level
_BEARISH_EXIT_CODES: frozenset[str] = frozenset(
    {
        "direction_change",
        "trend_reversal",
        "trend_reversal_exit",
        "signal_flip_sell",
        "momentum_exhaustion",  # mocny bearish signal
        "emergency_exit",
        "kill_switch_exit",
    }
)

# Kody exit powodów, które NIE blokują reentry (normalne zysk/SL)
_NEUTRAL_EXIT_CODES: frozenset[str] = frozenset(
    {
        "tp_hit",
        "trailing_sl_hit",
        "sl_hit",
        "partial_take_profit",
        "time_stop",
        "full_close",
        "manual_close",
        "break_even_exit",
        "pending_confirmed_execution",
        "sync_ignored_dust_residual",
    }
)


def get_asset_bias(
    db: Session,
    base_asset: str,
    mode: str = "live",
    reentry_cooldown_minutes: int = 30,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Zwraca ocenę na poziomie aktywa bazowego (np. "BTC"):
    - asset_bias: NEUTRAL | BEARISH | BLOCKED
    - reentry_allowed: bool
    - reentry_blocked_until: ISO str lub None
    - last_exit_symbol: symbol który wygenerował blokadę
    - last_exit_reason: kod powodu
    - last_exit_at: timestamp
    - conflict_detected: True jeśli próbujemy wejść mimo bearish exit innego rynku
    - explanation: czytelny opis

    Przeszukuje ostatnie zamknięte pozycje dla WSZYSTKICH symboli tego aktywa
    (BTCEUR, BTCUSDC, itp.) i ocenia czy asset ma bearish bias.
    """
    from backend.database import Position
    from backend.quote_currency import get_base_asset, get_markets_for_asset

    asset = base_asset.upper()
    now_ = now or utc_now_naive()
    cutoff_minutes = max(1, reentry_cooldown_minutes)
    cutoff_time = now_ - timedelta(minutes=cutoff_minutes)

    # Znajdź wszystkie symbole tego aktywa (BTCEUR, BTCUSDC...)
    all_markets = get_markets_for_asset(asset)
    all_symbols = (
        list(all_markets.values())
        if isinstance(all_markets, dict)
        else list(all_markets)
    )

    if not all_symbols:
        # fallback: szukaj po prefixie
        all_symbols = [asset + "EUR", asset + "USDC", asset + "USDT", asset + "BTC"]

    # Najnowsza zamknięta pozycja z bearish exit w oknie cooldown
    blocking_exit: Optional[Any] = None
    blocking_symbol: Optional[str] = None

    for sym in all_symbols:
        try:
            pos = (
                db.query(Position)
                .filter(
                    Position.symbol == sym,
                    Position.mode == mode,
                    Position.exit_reason_code.isnot(None),
                    Position.exit_reason_code.in_(list(_BEARISH_EXIT_CODES)),
                    Position.updated_at >= cutoff_time,
                )
                .order_by(Position.updated_at.desc())
                .first()
            )
            if pos:
                if blocking_exit is None or pos.updated_at > blocking_exit.updated_at:
                    blocking_exit = pos
                    blocking_symbol = sym
        except Exception:
            continue

    if blocking_exit is not None:
        blocked_until = blocking_exit.updated_at + timedelta(minutes=cutoff_minutes)
        reentry_allowed = now_ >= blocked_until
        return {
            "asset": asset,
            "asset_bias": "BEARISH" if reentry_allowed else "BLOCKED",
            "reentry_allowed": reentry_allowed,
            "reentry_blocked_until": blocked_until.isoformat(),
            "last_exit_symbol": blocking_symbol,
            "last_exit_reason": blocking_exit.exit_reason_code,
            "last_exit_at": blocking_exit.updated_at.isoformat(),
            "conflict_detected": not reentry_allowed,
            "explanation": (
                f"Aktywo {asset} zostało zamknięte z powodu '{blocking_exit.exit_reason_code}' "
                f"na {blocking_symbol}. Reentry zablokowane do {blocked_until.strftime('%H:%M:%S')}."
                if not reentry_allowed
                else (
                    f"Aktywo {asset} miało bearish exit ({blocking_exit.exit_reason_code}) "
                    f"ale cooldown {cutoff_minutes}min już minął — reentry dozwolone."
                )
            ),
        }

    return {
        "asset": asset,
        "asset_bias": "NEUTRAL",
        "reentry_allowed": True,
        "reentry_blocked_until": None,
        "last_exit_symbol": None,
        "last_exit_reason": None,
        "last_exit_at": None,
        "conflict_detected": False,
        "explanation": f"Brak bearish exit dla {asset} w ostatnich {cutoff_minutes} min — wejście dozwolone.",
    }
