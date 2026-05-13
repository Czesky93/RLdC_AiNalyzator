"""
Reporting and analytics layer built on top of accounting and risk.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from sqlalchemy.orm import Session

from backend.accounting import (
    blocked_decisions_summary,
    compute_demo_account_state,
    compute_risk_snapshot,
    compute_strategy_performance,
    compute_symbol_performance,
    cost_breakdown_by_symbol,
    summarize_orders,
    summarize_positions,
)
from backend.database import (
    AccountSnapshot,
    CostLedger,
    DecisionTrace,
    Order,
    Position,
    compare_config_snapshots,
    get_config_snapshot,
    list_config_snapshots,
    utc_now_naive,
)


def _compute_overtrading_score(activity_gate_blocks: int, closed_orders: int) -> float:
    """
    Ratio 0..1: im więcej blokad aktywności względem zamkniętych transakcji,
    tym większe ryzyko overtradingu.
    """
    if activity_gate_blocks <= 0:
        return 0.0
    base = max(int(closed_orders), 1)
    return float(min(float(activity_gate_blocks) / float(base), 1.0))


def _compute_gross_to_net_retention(gross_pnl: float, net_pnl: float) -> float:
    """
    Retencja 0..1: jaka część PnL brutto zostaje po kosztach.
    Dla braku dodatniego brutto zwracamy 0, aby uniknąć mylących wartości.
    """
    if gross_pnl <= 0:
        return 0.0
    ratio = net_pnl / gross_pnl
    return float(max(0.0, min(ratio, 1.0)))


def performance_overview(db: Session, mode: str = "demo") -> Dict[str, object]:
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    closed_orders = [o for o in orders if (o.side or "").upper() == "SELL"]
    summary = summarize_orders(closed_orders, db=db, label="overview")
    risk = compute_risk_snapshot(db, mode=mode)
    blocked = blocked_decisions_summary(db, mode=mode)
    if mode == "demo":
        state = compute_demo_account_state(db)
    else:
        snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(AccountSnapshot.timestamp.desc())
            .first()
        )
        positions = (
            db.query(Position)
            .filter(Position.mode == mode, Position.exit_reason_code.is_(None))
            .all()
        )
        positions_value = sum(
            float(p.quantity or 0.0) * float(p.current_price or p.entry_price or 0.0)
            for p in positions
        )
        equity = float(snap.equity or 0.0) if snap else positions_value
        cash = float(snap.free_margin or 0.0) if snap else 0.0
        state = {
            "equity": equity,
            "cash": cash,
            "positions_value": positions_value,
        }

    cooldown_count = (
        db.query(DecisionTrace)
        .filter(
            DecisionTrace.mode == mode,
            DecisionTrace.reason_code.in_(
                ["loss_streak_gate", "activity_gate_day", "activity_gate_symbol_hour"]
            ),
        )
        .count()
    )
    kill_switch_count = (
        db.query(DecisionTrace)
        .filter(
            DecisionTrace.mode == mode, DecisionTrace.reason_code == "kill_switch_gate"
        )
        .count()
    )
    activity_gate_blocks = (
        db.query(DecisionTrace)
        .filter(
            DecisionTrace.mode == mode,
            DecisionTrace.reason_code.in_(
                ["activity_gate_day", "activity_gate_symbol_hour"]
            ),
        )
        .count()
    )
    closed_orders = int(summary.get("closed_orders") or 0)
    overtrading_score = _compute_overtrading_score(activity_gate_blocks, closed_orders)
    gross_to_net_retention_ratio = _compute_gross_to_net_retention(
        float(summary["gross_pnl"]),
        float(summary["net_pnl"]),
    )
    gross_net_gap = float(summary["gross_pnl"]) - float(summary["net_pnl"])

    return {
        "mode": mode,
        "gross_pnl": summary["gross_pnl"],
        "net_pnl": summary["net_pnl"],
        "gross_net_gap": gross_net_gap,
        "total_cost": summary["total_cost"],
        "fee_cost": summary["fee_cost"],
        "slippage_cost": summary["slippage_cost"],
        "spread_cost": summary["spread_cost"],
        "closed_orders": closed_orders,
        "net_win_rate": summary["win_rate_net"],
        "net_expectancy": summary["net_expectancy"],
        "profit_factor_net": summary["profit_factor_net"],
        "drawdown_net": risk["daily_net_drawdown"],
        "blocked_decisions_count": int(sum(blocked.values())),
        "cooldown_activations": cooldown_count,
        "kill_switch_activations": kill_switch_count,
        "overtrading_activity_blocks": activity_gate_blocks,
        "overtrading_score": overtrading_score,
        "gross_to_net_retention_ratio": gross_to_net_retention_ratio,
        "cost_leakage_ratio": summary["cost_leakage_ratio"],
        "risk_snapshot": risk,
        "account_state": state,
    }


def daily_performance_report(
    db: Session, mode: str = "demo"
) -> List[Dict[str, object]]:
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    grouped: Dict[str, List[Order]] = defaultdict(list)
    for order in orders:
        ts = order.timestamp or utc_now_naive()
        grouped[ts.date().isoformat()].append(order)

    blocked_by_day: Dict[str, int] = defaultdict(int)
    traces = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()
    for trace in traces:
        if (
            "SKIP" in (trace.action_type or "").upper()
            or "BLOCK" in (trace.action_type or "").upper()
            or "REJECT" in (trace.action_type or "").upper()
        ):
            ts = trace.timestamp or utc_now_naive()
            blocked_by_day[ts.date().isoformat()] += 1

    cost_by_day: Dict[str, float] = defaultdict(float)
    for ledger in db.query(CostLedger).all():
        ts = ledger.timestamp or utc_now_naive()
        cost_by_day[ts.date().isoformat()] += float(
            ledger.actual_value or ledger.expected_value or 0.0
        )

    result = []
    for day, items in sorted(grouped.items()):
        summary = summarize_orders(items, db=db, label=day)
        result.append(
            {
                "day": day,
                "gross_pnl": summary["gross_pnl"],
                "net_pnl": summary["net_pnl"],
                "total_cost": summary["total_cost"],
                "blocked_decisions": blocked_by_day.get(day, 0),
                "cost_for_day": cost_by_day.get(day, 0.0),
            }
        )
    return result


def reason_code_breakdown(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    blocked = blocked_decisions_summary(db, mode=mode)
    return [{"reason_code": code, "count": count} for code, count in blocked.items()]


def cost_breakdown_by_type(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    orders = {
        int(o.id)
        for o in db.query(Order)
        .filter(Order.mode == mode, Order.status == "FILLED")
        .all()
        if o.id is not None
    }
    totals: Dict[str, float] = defaultdict(float)
    for row in db.query(CostLedger).all():
        if row.order_id is not None and int(row.order_id) not in orders:
            continue
        totals[row.cost_type] += float(
            row.actual_value
            if row.actual_value is not None
            else row.expected_value or 0.0
        )
    return [
        {"cost_type": key, "total_cost": value}
        for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)
    ]


def risk_effectiveness_report(db: Session, mode: str = "demo") -> Dict[str, object]:
    blocked = blocked_decisions_summary(db, mode=mode)
    overview = performance_overview(db, mode=mode)
    risk = compute_risk_snapshot(db, mode=mode)
    return {
        "mode": mode,
        "blocked_by_reason": blocked,
        "blocked_total": int(sum(blocked.values())),
        "cooldown_activations": overview["cooldown_activations"],
        "kill_switch_activations": overview["kill_switch_activations"],
        "daily_net_drawdown": risk["daily_net_drawdown"],
        "loss_streak_net": risk["loss_streak_net"],
        "net_pnl": overview["net_pnl"],
    }


def config_snapshot_report(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    grouped: Dict[str, List[Order]] = defaultdict(list)
    for order in orders:
        key = (order.config_snapshot_id or "unknown").strip() or "unknown"
        grouped[key].append(order)
    result = []
    for snapshot_id, items in grouped.items():
        summary = summarize_orders(items, db=db, label=snapshot_id)
        summary["config_snapshot_id"] = snapshot_id
        snapshot = get_config_snapshot(db, snapshot_id)
        if snapshot is not None:
            summary["config_hash"] = snapshot.get("config_hash")
            summary["created_at"] = snapshot.get("created_at")
            summary["source"] = snapshot.get("source")
            summary["changed_fields"] = snapshot.get("changed_fields")
            summary["previous_snapshot_id"] = snapshot.get("previous_snapshot_id")
        result.append(summary)
    result.sort(key=lambda item: float(item.get("net_pnl") or 0.0), reverse=True)
    return result


def config_snapshot_payload_report(
    db: Session, snapshot_id: str
) -> Dict[str, object] | None:
    return get_config_snapshot(db, snapshot_id)


def config_snapshot_compare_report(
    db: Session, snapshot_a: str, snapshot_b: str, mode: str = "demo"
) -> Dict[str, object]:
    comparison = compare_config_snapshots(db, snapshot_a, snapshot_b)
    grouped = {
        item.get("config_snapshot_id"): item
        for item in config_snapshot_report(db, mode=mode)
    }
    comparison["performance_a"] = grouped.get(snapshot_a)
    comparison["performance_b"] = grouped.get(snapshot_b)
    comparison["mode"] = mode
    return comparison


def analytics_bundle(db: Session, mode: str = "demo") -> Dict[str, object]:
    positions = db.query(Position).filter(Position.mode == mode).all()
    return {
        "overview": performance_overview(db, mode=mode),
        "by_symbol": compute_symbol_performance(db, mode=mode),
        "by_strategy": compute_strategy_performance(db, mode=mode),
        "by_day": daily_performance_report(db, mode=mode),
        "blocked_by_reason": reason_code_breakdown(db, mode=mode),
        "cost_by_symbol": cost_breakdown_by_symbol(db, mode=mode),
        "cost_by_type": cost_breakdown_by_type(db, mode=mode),
        "risk_effectiveness": risk_effectiveness_report(db, mode=mode),
        "config_snapshots": config_snapshot_report(db, mode=mode),
        "config_snapshot_catalog": list_config_snapshots(db),
        "positions_summary": summarize_positions(positions, db=db, label="positions"),
    }
