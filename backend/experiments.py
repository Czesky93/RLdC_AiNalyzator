"""
Controlled experiment layer for comparing configuration snapshots.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from backend.accounting import summarize_orders
from backend.database import DecisionTrace, Experiment, ExperimentResult, Order, get_config_snapshot, utc_now_naive
from backend.governance import enforce_pipeline_permission


_RISK_ACTION_REASONS = {
    "loss_streak_gate",
    "activity_gate_day",
    "activity_gate_symbol_hour",
    "kill_switch_gate",
    "daily_net_drawdown_gate",
    "max_open_positions_gate",
    "exposure_gate_total",
    "exposure_gate_symbol",
    "leakage_gate_symbol",
    "expectancy_gate_symbol",
    "expectancy_gate_strategy",
}


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _order_strategy_map(db: Session, mode: str) -> Dict[int, str]:
    rows = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()
    result: Dict[int, str] = {}
    for row in rows:
        if row.order_id and row.strategy_name:
            result[int(row.order_id)] = row.strategy_name
    return result


def _filter_orders(
    db: Session,
    *,
    mode: str,
    snapshot_id: str,
    symbol: Optional[str] = None,
    strategy_name: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
) -> List[Order]:
    query = db.query(Order).filter(
        Order.mode == mode,
        Order.status == "FILLED",
        Order.config_snapshot_id == snapshot_id,
    )
    if symbol:
        query = query.filter(Order.symbol == symbol.upper())
    if start_at:
        query = query.filter(Order.timestamp >= start_at)
    if end_at:
        query = query.filter(Order.timestamp <= end_at)
    orders = query.all()
    if not strategy_name:
        return orders
    strategy_map = _order_strategy_map(db, mode)
    return [order for order in orders if strategy_map.get(int(order.id or 0), "unknown") == strategy_name]


def _filter_traces(
    db: Session,
    *,
    mode: str,
    snapshot_id: str,
    symbol: Optional[str] = None,
    strategy_name: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
) -> List[DecisionTrace]:
    query = db.query(DecisionTrace).filter(
        DecisionTrace.mode == mode,
        DecisionTrace.config_snapshot_id == snapshot_id,
    )
    if symbol:
        query = query.filter(DecisionTrace.symbol == symbol.upper())
    if strategy_name:
        query = query.filter(DecisionTrace.strategy_name == strategy_name)
    if start_at:
        query = query.filter(DecisionTrace.timestamp >= start_at)
    if end_at:
        query = query.filter(DecisionTrace.timestamp <= end_at)
    return query.all()


def _blocked_by_reason(traces: Iterable[DecisionTrace]) -> Dict[str, int]:
    blocked: Dict[str, int] = {}
    for trace in traces:
        action = (trace.action_type or "").upper()
        if "SKIP" in action or "BLOCK" in action or "REJECT" in action:
            key = trace.reason_code or "unknown"
            blocked[key] = blocked.get(key, 0) + 1
    return dict(sorted(blocked.items(), key=lambda item: item[1], reverse=True))


def _breakdown_by_symbol(db: Session, orders: Iterable[Order]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Order]] = defaultdict(list)
    for order in orders:
        grouped[(order.symbol or "").upper()].append(order)
    result = []
    for symbol, items in grouped.items():
        if not symbol:
            continue
        summary = summarize_orders(items, db=db, label=symbol)
        summary["symbol"] = symbol
        result.append(summary)
    result.sort(key=lambda item: float(item.get("net_pnl") or 0.0), reverse=True)
    return result


def _breakdown_by_strategy(db: Session, mode: str, orders: Iterable[Order]) -> List[Dict[str, Any]]:
    strategy_map = _order_strategy_map(db, mode)
    grouped: Dict[str, List[Order]] = defaultdict(list)
    for order in orders:
        strategy = strategy_map.get(int(order.id or 0), "unknown")
        grouped[strategy].append(order)
    result = []
    for strategy, items in grouped.items():
        summary = summarize_orders(items, db=db, label=strategy)
        summary["strategy_name"] = strategy
        result.append(summary)
    result.sort(key=lambda item: float(item.get("net_pnl") or 0.0), reverse=True)
    return result


def snapshot_performance_report(
    db: Session,
    *,
    snapshot_id: str,
    mode: str = "demo",
    symbol: Optional[str] = None,
    strategy_name: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    snapshot = get_config_snapshot(db, snapshot_id)
    if snapshot is None:
        raise ValueError(f"Missing config snapshot: {snapshot_id}")
    orders = _filter_orders(
        db,
        mode=mode,
        snapshot_id=snapshot_id,
        symbol=symbol,
        strategy_name=strategy_name,
        start_at=start_at,
        end_at=end_at,
    )
    traces = _filter_traces(
        db,
        mode=mode,
        snapshot_id=snapshot_id,
        symbol=symbol,
        strategy_name=strategy_name,
        start_at=start_at,
        end_at=end_at,
    )
    summary = summarize_orders(orders, db=db, label=snapshot_id)
    blocked = _blocked_by_reason(traces)
    risk_actions_count = sum(count for reason, count in blocked.items() if reason in _RISK_ACTION_REASONS)
    return {
        "snapshot_id": snapshot_id,
        "mode": mode,
        "scope_symbol": symbol.upper() if symbol else None,
        "scope_strategy": strategy_name,
        "start_at": start_at.isoformat() if start_at else None,
        "end_at": end_at.isoformat() if end_at else None,
        "trade_count": int(summary["closed_orders"]),
        "gross_pnl": summary["gross_pnl"],
        "net_pnl": summary["net_pnl"],
        "total_cost": summary["total_cost"],
        "cost_leakage_ratio": summary["cost_leakage_ratio"],
        "profit_factor_net": summary["profit_factor_net"],
        "net_expectancy": summary["net_expectancy"],
        "drawdown_net": min(0.0, float(summary["net_pnl"] or 0.0)),
        "win_rate_net": summary["win_rate_net"],
        "blocked_decisions": int(sum(blocked.values())),
        "blocked_by_reason": blocked,
        "risk_actions_count": int(risk_actions_count),
        "symbol_breakdown": _breakdown_by_symbol(db, orders),
        "strategy_breakdown": _breakdown_by_strategy(db, mode, orders),
        "snapshot": snapshot,
    }


def evaluate_experiment_result(baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    reason_codes: List[str] = []
    baseline_net = float(baseline.get("net_pnl") or 0.0)
    candidate_net = float(candidate.get("net_pnl") or 0.0)
    baseline_dd = abs(float(baseline.get("drawdown_net") or 0.0))
    candidate_dd = abs(float(candidate.get("drawdown_net") or 0.0))
    baseline_leak = float(baseline.get("cost_leakage_ratio") or 0.0)
    candidate_leak = float(candidate.get("cost_leakage_ratio") or 0.0)
    baseline_expectancy = float(baseline.get("net_expectancy") or 0.0)
    candidate_expectancy = float(candidate.get("net_expectancy") or 0.0)
    baseline_trades = int(baseline.get("trade_count") or 0)
    candidate_trades = int(candidate.get("trade_count") or 0)

    winner = "inconclusive"
    if candidate_net > baseline_net:
        reason_codes.append("candidate_net_pnl_up")
    elif candidate_net < baseline_net:
        reason_codes.append("candidate_net_pnl_down")

    if candidate_dd < baseline_dd:
        reason_codes.append("candidate_drawdown_improved")
    elif candidate_dd > baseline_dd:
        reason_codes.append("candidate_drawdown_worse")

    if candidate_leak < baseline_leak:
        reason_codes.append("candidate_leakage_improved")
    elif candidate_leak > baseline_leak:
        reason_codes.append("candidate_leakage_worse")

    if candidate_expectancy > baseline_expectancy:
        reason_codes.append("candidate_expectancy_up")
    elif candidate_expectancy < baseline_expectancy:
        reason_codes.append("candidate_expectancy_down")

    if candidate_trades > baseline_trades and candidate_net <= baseline_net:
        reason_codes.append("turnover_up_without_net_gain")

    if (
        candidate_net > baseline_net
        and candidate_expectancy >= baseline_expectancy
        and candidate_dd <= (baseline_dd * 1.10 + 1e-9)
    ):
        winner = "candidate"
    elif (
        candidate_net < baseline_net
        and candidate_dd >= baseline_dd
        and candidate_expectancy <= baseline_expectancy
    ):
        winner = "baseline"

    explanation = {
        "baseline_net_pnl": baseline_net,
        "candidate_net_pnl": candidate_net,
        "baseline_drawdown_net": baseline_dd,
        "candidate_drawdown_net": candidate_dd,
        "baseline_leakage": baseline_leak,
        "candidate_leakage": candidate_leak,
        "baseline_expectancy": baseline_expectancy,
        "candidate_expectancy": candidate_expectancy,
    }
    return {
        "winner": winner,
        "reason_codes": reason_codes or ["insufficient_edge"],
        "explanation": explanation,
    }


def compare_snapshots_for_experiment(
    db: Session,
    *,
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    mode: str = "demo",
    symbol: Optional[str] = None,
    strategy_name: Optional[str] = None,
    start_at: Optional[datetime] = None,
    end_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    baseline = snapshot_performance_report(
        db,
        snapshot_id=baseline_snapshot_id,
        mode=mode,
        symbol=symbol,
        strategy_name=strategy_name,
        start_at=start_at,
        end_at=end_at,
    )
    candidate = snapshot_performance_report(
        db,
        snapshot_id=candidate_snapshot_id,
        mode=mode,
        symbol=symbol,
        strategy_name=strategy_name,
        start_at=start_at,
        end_at=end_at,
    )
    verdict = evaluate_experiment_result(baseline, candidate)
    return {
        "mode": mode,
        "scope": {
            "symbol": symbol.upper() if symbol else None,
            "strategy_name": strategy_name,
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
        },
        "baseline": baseline,
        "candidate": candidate,
        "verdict": verdict,
    }


def create_experiment(
    db: Session,
    *,
    name: str,
    description: Optional[str],
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    mode: str = "demo",
    scope: str = "global",
    symbol: Optional[str] = None,
    strategy_name: Optional[str] = None,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    enforce_pipeline_permission(db, "experiment")
    start_dt = _parse_date(start_at)
    end_dt = _parse_date(end_at)
    comparison = compare_snapshots_for_experiment(
        db,
        baseline_snapshot_id=baseline_snapshot_id,
        candidate_snapshot_id=candidate_snapshot_id,
        mode=mode,
        symbol=symbol,
        strategy_name=strategy_name,
        start_at=start_dt,
        end_at=end_dt,
    )
    now = utc_now_naive()
    experiment = Experiment(
        name=name,
        description=description,
        status="completed",
        mode=mode,
        baseline_snapshot_id=baseline_snapshot_id,
        candidate_snapshot_id=candidate_snapshot_id,
        scope=scope,
        symbol=symbol.upper() if symbol else None,
        strategy_name=strategy_name,
        start_at=start_dt,
        end_at=end_dt,
        created_at=now,
        started_at=now,
        ended_at=now,
        notes=notes,
    )
    db.add(experiment)
    db.flush()
    verdict = comparison["verdict"]["winner"]
    db.add(
        ExperimentResult(
            experiment_id=int(experiment.id),
            variant="baseline",
            snapshot_id=baseline_snapshot_id,
            metrics_json=_json_text(comparison["baseline"]),
            breakdown_json=_json_text(
                {
                    "symbol_breakdown": comparison["baseline"]["symbol_breakdown"],
                    "strategy_breakdown": comparison["baseline"]["strategy_breakdown"],
                }
            ),
            verdict=verdict,
            reason_codes_json=_json_text(comparison["verdict"]["reason_codes"]),
        )
    )
    db.add(
        ExperimentResult(
            experiment_id=int(experiment.id),
            variant="candidate",
            snapshot_id=candidate_snapshot_id,
            metrics_json=_json_text(comparison["candidate"]),
            breakdown_json=_json_text(
                {
                    "symbol_breakdown": comparison["candidate"]["symbol_breakdown"],
                    "strategy_breakdown": comparison["candidate"]["strategy_breakdown"],
                }
            ),
            verdict=verdict,
            reason_codes_json=_json_text(comparison["verdict"]["reason_codes"]),
        )
    )
    db.commit()
    db.refresh(experiment)
    return get_experiment(db, int(experiment.id))


def get_experiment(db: Session, experiment_id: int) -> Dict[str, Any]:
    experiment = db.query(Experiment).filter(Experiment.id == experiment_id).first()
    if experiment is None:
        raise ValueError(f"Experiment not found: {experiment_id}")
    results = db.query(ExperimentResult).filter(ExperimentResult.experiment_id == experiment_id).all()
    result_map = {
        row.variant: {
            "snapshot_id": row.snapshot_id,
            "metrics": _json_load(row.metrics_json),
            "breakdown": _json_load(row.breakdown_json),
            "verdict": row.verdict,
            "reason_codes": _json_load(row.reason_codes_json) or [],
        }
        for row in results
    }
    return {
        "id": int(experiment.id),
        "name": experiment.name,
        "description": experiment.description,
        "status": experiment.status,
        "mode": experiment.mode,
        "baseline_snapshot_id": experiment.baseline_snapshot_id,
        "candidate_snapshot_id": experiment.candidate_snapshot_id,
        "scope": experiment.scope,
        "symbol": experiment.symbol,
        "strategy_name": experiment.strategy_name,
        "start_at": experiment.start_at.isoformat() if experiment.start_at else None,
        "end_at": experiment.end_at.isoformat() if experiment.end_at else None,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "started_at": experiment.started_at.isoformat() if experiment.started_at else None,
        "ended_at": experiment.ended_at.isoformat() if experiment.ended_at else None,
        "notes": experiment.notes,
        "baseline": result_map.get("baseline"),
        "candidate": result_map.get("candidate"),
        "verdict": {
            "winner": (result_map.get("baseline") or {}).get("verdict") or (result_map.get("candidate") or {}).get("verdict"),
            "reason_codes": (result_map.get("baseline") or {}).get("reason_codes") or (result_map.get("candidate") or {}).get("reason_codes") or [],
        },
    }


def list_experiments(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(Experiment).order_by(Experiment.created_at.desc(), Experiment.id.desc()).all()
    return [get_experiment(db, int(row.id)) for row in rows if row.id is not None]
