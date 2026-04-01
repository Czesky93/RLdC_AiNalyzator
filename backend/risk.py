"""
Risk layer that consumes accounting snapshots and runtime settings.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import os
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.accounting import compute_activity_snapshot, compute_risk_snapshot, compute_strategy_performance, compute_symbol_performance
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
    symbol_performance = _find_summary(compute_symbol_performance(db, mode=mode), "symbol", symbol)
    strategy_performance = _find_summary(compute_strategy_performance(db, mode=mode), "strategy_name", strategy_name)
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

    kill_switch_active = bool(cfg.get("kill_switch_enabled")) and bool(rs.get("kill_switch_triggered"))
    if kill_switch_active:
        allowed = False
        action = "trigger_kill_switch"
        reason_codes.append("kill_switch_gate")
        limit_breaches.append("kill_switch_gate")

    max_daily_drawdown = float(cfg.get("max_daily_drawdown", 0.03))
    if context.mode == "demo":
        _initial_balance = max(1.0, float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000))
        daily_drawdown_ratio = abs(float(rs.get("daily_net_drawdown") or 0.0)) / _initial_balance
    else:
        # LIVE: używamy całkowitego zaangażowania (exposure) lub fallback na live_balance_eur
        _exposure = float(rs.get("total_exposure") or 0.0)
        _live_balance = float(cfg.get("live_balance_eur") or os.getenv("LIVE_INITIAL_BALANCE", "0") or 0.0)
        _base = max(1.0, _exposure if _exposure > 0 else _live_balance)
        daily_drawdown_ratio = abs(float(rs.get("daily_net_drawdown") or 0.0)) / _base
    if allowed and daily_drawdown_ratio >= max_daily_drawdown:
        allowed = False
        action = "block_temporarily"
        reason_codes.append("daily_net_drawdown_gate")
        limit_breaches.append("daily_net_drawdown_gate")

    loss_streak_limit = int(cfg.get("loss_streak_limit", 3))
    loss_streak = int(rs.get("loss_streak_net") or 0)
    if allowed and loss_streak >= loss_streak_limit:
        allowed = False
        action = "block_temporarily"
        cooldown_active = True
        reason_codes.append("loss_streak_gate")
        limit_breaches.append("loss_streak_gate")

    max_open_positions = int(cfg.get("max_open_positions", 3))
    if allowed and context.side.upper() == "BUY" and context.open_positions_count >= max_open_positions:
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
    if allowed and symbol_trades_1h >= int(cfg.get("max_trades_per_hour_per_symbol", 2)):
        allowed = False
        action = "block_symbol"
        reason_codes.append("activity_gate_symbol_hour")
        limit_breaches.append("activity_gate_symbol_hour")

    initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000) if context.mode == "demo" else 0.0
    total_exposure_ratio = (float(rs.get("total_exposure") or 0.0) / initial_balance) if initial_balance > 0 else 0.0
    if allowed and total_exposure_ratio >= float(cfg.get("max_total_exposure_ratio", 0.8)):
        allowed = False
        action = "block_temporarily"
        reason_codes.append("exposure_gate_total")
        limit_breaches.append("exposure_gate_total")

    symbol_exposure_ratio = (float((rs.get("exposure_per_symbol") or {}).get(context.symbol, 0.0)) / initial_balance) if initial_balance > 0 else 0.0
    if allowed and symbol_exposure_ratio >= float(cfg.get("max_symbol_exposure_ratio", 0.35)):
        allowed = False
        action = "block_symbol"
        reason_codes.append("exposure_gate_symbol")
        limit_breaches.append("exposure_gate_symbol")

    max_cost_leakage_ratio = float(cfg.get("max_cost_leakage_ratio", 0.5))
    leakage_min_trades = int(cfg.get("leakage_gate_min_trades", 5))
    sym_closed_trades = int(symbol_perf.get("closed_trades") or 0)
    if (allowed
        and sym_closed_trades >= leakage_min_trades
        and float(symbol_perf.get("cost_leakage_ratio") or 0.0) > max_cost_leakage_ratio):
        allowed = False
        action = "block_symbol"
        reason_codes.append("leakage_gate_symbol")
        limit_breaches.append("leakage_gate_symbol")

    min_symbol_net_expectancy = float(cfg.get("min_symbol_net_expectancy", 0.0))
    expectancy_min_trades = int(cfg.get("expectancy_gate_min_trades", 5))
    if (allowed
        and sym_closed_trades >= expectancy_min_trades
        and float(symbol_perf.get("net_expectancy") or 0.0) < min_symbol_net_expectancy):
        allowed = False
        action = "block_symbol"
        reason_codes.append("expectancy_gate_symbol")
        limit_breaches.append("expectancy_gate_symbol")

    strat_closed_trades = int(strategy_perf.get("closed_trades") or 0) if strategy_perf else 0
    if (allowed and strategy_perf
        and strat_closed_trades >= expectancy_min_trades
        and float(strategy_perf.get("net_expectancy") or 0.0) < min_symbol_net_expectancy):
        allowed = False
        action = "block_strategy"
        reason_codes.append("expectancy_gate_strategy")
        limit_breaches.append("expectancy_gate_strategy")

    if allowed and total_exposure_ratio >= float(cfg.get("max_total_exposure_ratio", 0.8)) * 0.85:
        position_size_multiplier = min(position_size_multiplier, 0.5)
        action = "allow_with_reduced_size"
        reason_codes.append("exposure_size_reduction")

    if allowed and loss_streak == max(0, loss_streak_limit - 1):
        position_size_multiplier = min(position_size_multiplier, 0.5)
        action = "allow_with_reduced_size"
        reason_codes.append("loss_streak_size_reduction")

    risk_score = min(
        1.0,
        max(
            daily_drawdown_ratio / max(max_daily_drawdown, 1e-9),
            total_exposure_ratio / max(float(cfg.get("max_total_exposure_ratio", 0.8)), 1e-9),
            symbol_exposure_ratio / max(float(cfg.get("max_symbol_exposure_ratio", 0.35)), 1e-9),
            float(symbol_perf.get("cost_leakage_ratio") or 0.0) / max(max_cost_leakage_ratio, 1e-9),
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
            "risk_snapshot": rs,
            "activity_snapshot": activity,
            "symbol_performance": symbol_perf,
            "strategy_performance": strategy_perf,
        },
    )
