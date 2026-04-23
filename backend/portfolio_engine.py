"""Portfolio-level ranking and replacement decision helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class OpenPositionScore:
    symbol: str
    hold_score: float
    hold_expected_value_net: float
    position_rank_score: float
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl_pct: float
    distance_to_tp_pct: float
    distance_to_sl_pct: float
    age_minutes: float


@dataclass
class EntryCandidateScore:
    symbol: str
    entry_score: float
    expected_value_gross: float
    expected_value_net: float
    confidence: float
    risk_adjusted_return: float
    position_size_suggestion: float
    priority_rank: float


@dataclass
class ReplacementDecision:
    should_replace: bool
    reason_code: str
    replacement_net_advantage: float
    gross_advantage: float
    total_replacement_cost: float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def compute_hold_score(
    position: Any, now: datetime, cfg: Dict[str, Any]
) -> OpenPositionScore:
    entry_price = max(1e-9, _safe_float(getattr(position, "entry_price", 0.0)))
    current_price = _safe_float(
        getattr(position, "current_price", entry_price), entry_price
    )
    quantity = max(0.0, _safe_float(getattr(position, "quantity", 0.0)))
    unrealized_pnl = _safe_float(getattr(position, "unrealized_pnl", 0.0))
    planned_tp = _safe_float(getattr(position, "planned_tp", 0.0))
    planned_sl = _safe_float(getattr(position, "planned_sl", 0.0))
    opened_at = getattr(position, "opened_at", None)

    unrealized_pnl_pct = (
        unrealized_pnl / max(entry_price * max(quantity, 1e-9), 1e-9)
    ) * 100.0

    if planned_tp > 0:
        distance_to_tp_pct = (
            max(0.0, (planned_tp - current_price) / max(current_price, 1e-9)) * 100.0
        )
    else:
        distance_to_tp_pct = 999.0

    if planned_sl > 0:
        distance_to_sl_pct = (
            max(0.0, (current_price - planned_sl) / max(current_price, 1e-9)) * 100.0
        )
    else:
        distance_to_sl_pct = 999.0

    if isinstance(opened_at, datetime):
        age_minutes = max(0.0, (now - opened_at).total_seconds() / 60.0)
    else:
        age_minutes = 999.0

    pnl_component = _clamp01((unrealized_pnl_pct + 2.0) / 6.0)
    tp_component = _clamp01(1.0 - min(distance_to_tp_pct, 10.0) / 10.0)
    sl_component = _clamp01(min(distance_to_sl_pct, 10.0) / 10.0)
    maturity_component = _clamp01(min(age_minutes, 120.0) / 120.0)

    hold_score = (
        0.45 * pnl_component
        + 0.20 * tp_component
        + 0.20 * sl_component
        + 0.15 * maturity_component
    )

    hold_expected_value_net = hold_score - _safe_float(
        getattr(position, "total_cost", 0.0)
    ) / max(entry_price * max(quantity, 1e-9), 1e-9)

    return OpenPositionScore(
        symbol=str(getattr(position, "symbol", "")),
        hold_score=hold_score,
        hold_expected_value_net=hold_expected_value_net,
        position_rank_score=hold_score,
        quantity=quantity,
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl_pct=unrealized_pnl_pct,
        distance_to_tp_pct=distance_to_tp_pct,
        distance_to_sl_pct=distance_to_sl_pct,
        age_minutes=age_minutes,
    )


def rank_open_positions(
    positions: List[Any], now: datetime, cfg: Dict[str, Any]
) -> List[OpenPositionScore]:
    scored = [
        compute_hold_score(p, now, cfg)
        for p in positions
        if _safe_float(getattr(p, "quantity", 0.0)) > 0
    ]
    scored.sort(key=lambda x: x.position_rank_score)
    return scored


def compute_entry_score(
    candidate: Dict[str, Any], cfg: Dict[str, Any]
) -> EntryCandidateScore:
    confidence = _safe_float(candidate.get("confidence", 0.0))
    expected_move_ratio = _safe_float(candidate.get("expected_move_ratio", 0.0))
    total_cost_ratio = _safe_float(candidate.get("total_cost_ratio", 0.0))
    risk_reward = max(0.0, _safe_float(candidate.get("risk_reward", 0.0)))
    qty = max(0.0, _safe_float(candidate.get("qty", 0.0)))
    price = max(1e-9, _safe_float(candidate.get("price", 0.0)))

    expected_value_gross = expected_move_ratio
    expected_value_net = expected_move_ratio - total_cost_ratio
    risk_adjusted_return = expected_value_net * min(2.0, max(0.5, risk_reward))

    entry_score = (
        0.50 * confidence
        + 0.30 * max(0.0, min(1.0, expected_value_net * 10.0))
        + 0.20 * max(0.0, min(1.0, risk_adjusted_return * 5.0))
    )

    return EntryCandidateScore(
        symbol=str(candidate.get("symbol", "")),
        entry_score=entry_score,
        expected_value_gross=expected_value_gross,
        expected_value_net=expected_value_net,
        confidence=confidence,
        risk_adjusted_return=risk_adjusted_return,
        position_size_suggestion=qty,
        priority_rank=entry_score,
    )


def rank_entry_candidates(
    candidates: List[Dict[str, Any]], cfg: Dict[str, Any]
) -> List[EntryCandidateScore]:
    scored = [compute_entry_score(c, cfg) for c in candidates]
    scored.sort(key=lambda x: x.priority_rank, reverse=True)
    return scored


def compute_replacement_decision(
    best_new: EntryCandidateScore,
    worst_open: OpenPositionScore,
    cfg: Dict[str, Any],
) -> ReplacementDecision:
    replacement_threshold = _safe_float(cfg.get("min_replacement_edge", 0.015))
    min_conf_delta = _safe_float(cfg.get("min_confidence_delta_for_replacement", 0.03))

    close_fee = _safe_float(cfg.get("taker_fee_rate", 0.001))
    open_fee = _safe_float(cfg.get("taker_fee_rate", 0.001))
    spread_cost = _safe_float(cfg.get("spread_buffer_bps", 8.0)) / 10000.0
    slippage_cost = _safe_float(cfg.get("slippage_bps", 12.0)) / 10000.0
    total_replacement_cost = close_fee + open_fee + spread_cost + slippage_cost

    # Używamy hybrydowej przewagi: różnica jakości (score) + różnica EV netto.
    # Sama EV bywa niestabilna między symbolami o różnych skalach ATR.
    score_advantage = best_new.entry_score - worst_open.hold_score
    ev_advantage = best_new.expected_value_net - worst_open.hold_expected_value_net
    gross_advantage = (0.7 * score_advantage) + (0.3 * ev_advantage)
    replacement_net_advantage = gross_advantage - total_replacement_cost

    if best_new.entry_score <= worst_open.hold_score:
        return ReplacementDecision(
            should_replace=False,
            reason_code="buy_rejected_inferior_to_open_positions",
            replacement_net_advantage=replacement_net_advantage,
            gross_advantage=gross_advantage,
            total_replacement_cost=total_replacement_cost,
        )

    if (best_new.confidence - worst_open.hold_score) < min_conf_delta:
        return ReplacementDecision(
            should_replace=False,
            reason_code="buy_deferred_insufficient_rotation_edge",
            replacement_net_advantage=replacement_net_advantage,
            gross_advantage=gross_advantage,
            total_replacement_cost=total_replacement_cost,
        )

    if replacement_net_advantage <= replacement_threshold:
        return ReplacementDecision(
            should_replace=False,
            reason_code="buy_deferred_insufficient_rotation_edge",
            replacement_net_advantage=replacement_net_advantage,
            gross_advantage=gross_advantage,
            total_replacement_cost=total_replacement_cost,
        )

    return ReplacementDecision(
        should_replace=True,
        reason_code="buy_replaced_worst_position",
        replacement_net_advantage=replacement_net_advantage,
        gross_advantage=gross_advantage,
        total_replacement_cost=total_replacement_cost,
    )
