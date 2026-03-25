"""
Recommendation layer built on top of experiment outputs.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import Recommendation, compare_config_snapshots
from backend.experiments import get_experiment, list_experiments


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def evaluate_recommendation(experiment: Dict[str, Any], comparison: Dict[str, Any]) -> Dict[str, Any]:
    verdict = ((experiment.get("verdict") or {}).get("winner") or "inconclusive").lower()
    baseline = ((experiment.get("baseline") or {}).get("metrics") or {})
    candidate = ((experiment.get("candidate") or {}).get("metrics") or {})
    diff = comparison.get("diff") or []

    baseline_net = float(baseline.get("net_pnl") or 0.0)
    candidate_net = float(candidate.get("net_pnl") or 0.0)
    baseline_leak = float(baseline.get("cost_leakage_ratio") or 0.0)
    candidate_leak = float(candidate.get("cost_leakage_ratio") or 0.0)
    baseline_dd = abs(float(baseline.get("drawdown_net") or 0.0))
    candidate_dd = abs(float(candidate.get("drawdown_net") or 0.0))
    baseline_expectancy = float(baseline.get("net_expectancy") or 0.0)
    candidate_expectancy = float(candidate.get("net_expectancy") or 0.0)
    baseline_trades = int(baseline.get("trade_count") or 0)
    candidate_trades = int(candidate.get("trade_count") or 0)
    candidate_risk_actions = int(candidate.get("risk_actions_count") or 0)
    baseline_risk_actions = int(baseline.get("risk_actions_count") or 0)

    reason_codes: List[str] = list((experiment.get("verdict") or {}).get("reason_codes") or [])
    recommendation = "needs_more_data"

    if min(baseline_trades, candidate_trades) < 1:
        reason_codes.append("insufficient_trade_sample")
        recommendation = "needs_more_data"
    elif verdict == "candidate":
        if candidate_net > baseline_net and candidate_leak <= baseline_leak * 1.05 and candidate_dd <= baseline_dd * 1.15 + 1e-9:
            recommendation = "promote"
            reason_codes.append("candidate_outperformed_net")
        else:
            recommendation = "watch"
            reason_codes.append("candidate_win_but_side_effects_need_review")
    elif verdict == "baseline":
        if candidate_dd > baseline_dd * 1.10 or candidate_leak > baseline_leak * 1.10 or candidate_net < baseline_net:
            recommendation = "rollback_candidate"
            reason_codes.append("candidate_degraded_risk_or_cost")
        else:
            recommendation = "reject"
            reason_codes.append("candidate_underperformed")
    else:
        net_edge = candidate_net - baseline_net
        expectancy_edge = candidate_expectancy - baseline_expectancy
        if net_edge > 0 and expectancy_edge >= 0 and candidate_trades >= 3:
            recommendation = "watch"
            reason_codes.append("promising_but_inconclusive")
        else:
            recommendation = "needs_more_data"
            reason_codes.append("inconclusive_experiment")

    if candidate_trades > baseline_trades and candidate_net <= baseline_net:
        reason_codes.append("turnover_up_without_net_gain")
        if recommendation == "promote":
            recommendation = "watch"
    if candidate_risk_actions > baseline_risk_actions and candidate_net <= baseline_net:
        reason_codes.append("risk_actions_up_without_net_gain")
        if recommendation in {"promote", "watch"}:
            recommendation = "reject"
    if candidate_expectancy < baseline_expectancy and candidate_net <= baseline_net:
        reason_codes.append("expectancy_deteriorated")
        if recommendation == "watch":
            recommendation = "reject"

    confidence = 0.35
    confidence += min(0.20, abs(candidate_net - baseline_net) / 20.0)
    confidence += min(0.15, abs(candidate_expectancy - baseline_expectancy) / 5.0)
    confidence += min(0.10, min(baseline_trades, candidate_trades) / 20.0)
    if verdict == "candidate":
        confidence += 0.10
    elif verdict == "baseline":
        confidence += 0.08
    if recommendation in {"needs_more_data", "watch"}:
        confidence -= 0.10
    confidence = max(0.05, min(0.99, confidence))

    changed_fields = [item.get("field") for item in diff if item.get("field")]
    summary = (
        f"{recommendation}: baseline net={baseline_net:.2f}, candidate net={candidate_net:.2f}, "
        f"baseline leakage={baseline_leak:.4f}, candidate leakage={candidate_leak:.4f}, "
        f"baseline dd={baseline_dd:.2f}, candidate dd={candidate_dd:.2f}"
    )
    return {
        "recommendation": recommendation,
        "confidence": round(confidence, 4),
        "reason_codes": sorted(set(reason_codes)),
        "summary": summary,
        "parameter_changes": changed_fields,
        "net_effect_summary": {
            "baseline_net_pnl": baseline_net,
            "candidate_net_pnl": candidate_net,
            "baseline_expectancy": baseline_expectancy,
            "candidate_expectancy": candidate_expectancy,
            "baseline_trade_count": baseline_trades,
            "candidate_trade_count": candidate_trades,
        },
        "risk_effect_summary": {
            "baseline_drawdown_net": baseline_dd,
            "candidate_drawdown_net": candidate_dd,
            "baseline_risk_actions_count": baseline_risk_actions,
            "candidate_risk_actions_count": candidate_risk_actions,
            "baseline_leakage": baseline_leak,
            "candidate_leakage": candidate_leak,
        },
    }


def generate_recommendation(db: Session, experiment_id: int, notes: str | None = None) -> Dict[str, Any]:
    experiment = get_experiment(db, experiment_id)
    comparison = compare_config_snapshots(
        db,
        experiment["baseline_snapshot_id"],
        experiment["candidate_snapshot_id"],
    )
    evaluation = evaluate_recommendation(experiment, comparison)
    row = Recommendation(
        experiment_id=experiment_id,
        baseline_snapshot_id=experiment["baseline_snapshot_id"],
        candidate_snapshot_id=experiment["candidate_snapshot_id"],
        recommendation=evaluation["recommendation"],
        confidence=float(evaluation["confidence"]),
        reason_codes_json=_json_text(evaluation["reason_codes"]),
        summary=evaluation["summary"],
        parameter_changes_json=_json_text(evaluation["parameter_changes"]),
        net_effect_summary_json=_json_text(evaluation["net_effect_summary"]),
        risk_effect_summary_json=_json_text(evaluation["risk_effect_summary"]),
        status="open",
        created_at=datetime.utcnow(),
        notes=notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return get_recommendation(db, int(row.id))


def get_recommendation(db: Session, recommendation_id: int) -> Dict[str, Any]:
    row = db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
    if row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")
    experiment = get_experiment(db, int(row.experiment_id))
    comparison = compare_config_snapshots(db, row.baseline_snapshot_id, row.candidate_snapshot_id)
    return {
        "id": int(row.id),
        "experiment_id": int(row.experiment_id),
        "baseline_snapshot_id": row.baseline_snapshot_id,
        "candidate_snapshot_id": row.candidate_snapshot_id,
        "recommendation": row.recommendation,
        "confidence": float(row.confidence or 0.0),
        "reason_codes": _json_load(row.reason_codes_json) or [],
        "summary": row.summary,
        "parameter_changes": _json_load(row.parameter_changes_json) or [],
        "net_effect_summary": _json_load(row.net_effect_summary_json) or {},
        "risk_effect_summary": _json_load(row.risk_effect_summary_json) or {},
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "notes": row.notes,
        "experiment": experiment,
        "config_diff": comparison,
    }


def list_recommendations(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(Recommendation).order_by(Recommendation.created_at.desc(), Recommendation.id.desc()).all()
    return [get_recommendation(db, int(row.id)) for row in rows if row.id is not None]


def recommendation_overview(db: Session) -> Dict[str, Any]:
    items = list_recommendations(db)
    counts: Dict[str, int] = {}
    for item in items:
        key = item.get("recommendation") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return {
        "total": len(items),
        "by_type": counts,
        "recent": items[:10],
    }


def pending_recommendation_candidates(db: Session) -> List[Dict[str, Any]]:
    experiments = list_experiments(db)
    existing = {
        int(row.experiment_id)
        for row in db.query(Recommendation.experiment_id).all()
        if row and row[0] is not None
    }
    return [item for item in experiments if int(item["id"]) not in existing]
