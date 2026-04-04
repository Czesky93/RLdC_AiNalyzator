"""
Post-promotion monitoring for promoted configuration snapshots.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import ConfigPromotion, PromotionMonitoring, utc_now_naive
from backend.experiments import snapshot_performance_report
from backend.recommendations import get_recommendation


_EVALUATION_VERSION = "v1"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _monitoring_dict(row: PromotionMonitoring) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "promotion_id": int(row.promotion_id),
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
        "evaluation_window_start": row.evaluation_window_start.isoformat() if row.evaluation_window_start else None,
        "evaluation_window_end": row.evaluation_window_end.isoformat() if row.evaluation_window_end else None,
        "baseline_reference_summary": _json_load(row.baseline_reference_summary_json) or {},
        "observed_summary": _json_load(row.observed_summary_json) or {},
        "deviation_summary": _json_load(row.deviation_summary_json) or {},
        "reason_codes": _json_load(row.reason_codes_json) or [],
        "rollback_recommended": bool(row.rollback_recommended),
        "min_trade_count_gate_passed": bool(row.min_trade_count_gate_passed),
        "min_time_window_gate_passed": bool(row.min_time_window_gate_passed),
        "confidence": float(row.confidence or 0.0),
        "evaluation_version": row.evaluation_version,
        "notes": row.notes,
    }


def _get_promotion_row(db: Session, promotion_id: int) -> ConfigPromotion:
    row = db.query(ConfigPromotion).filter(ConfigPromotion.id == promotion_id).first()
    if row is None:
        raise ValueError(f"Promotion not found: {promotion_id}")
    return row


def _observed_snapshot_id(row: ConfigPromotion) -> str:
    payload = _json_load(row.runtime_apply_result_json) or {}
    state = payload.get("state") or {}
    return str(state.get("config_snapshot_id") or row.to_snapshot_id)


def initialize_monitoring_record(db: Session, promotion_id: int, notes: str | None = None) -> Dict[str, Any]:
    promotion = _get_promotion_row(db, promotion_id)
    existing = db.query(PromotionMonitoring).filter(PromotionMonitoring.promotion_id == promotion_id).first()
    if existing is not None:
        return get_monitoring_record(db, int(existing.id))
    row = PromotionMonitoring(
        promotion_id=promotion_id,
        from_snapshot_id=promotion.from_snapshot_id,
        to_snapshot_id=_observed_snapshot_id(promotion),
        status="pending",
        started_at=promotion.applied_at or promotion.initiated_at or utc_now_naive(),
        evaluation_window_start=promotion.applied_at or promotion.initiated_at or utc_now_naive(),
        evaluation_version=_EVALUATION_VERSION,
        notes=notes,
    )
    db.add(row)
    promotion.post_promotion_monitoring_status = "pending"
    db.commit()
    db.refresh(row)
    return get_monitoring_record(db, int(row.id))


def _min_trade_count() -> int:
    try:
        return max(1, int(os.getenv("POST_PROMOTION_MIN_TRADE_COUNT", "20") or 20))
    except Exception:
        return 20


def _min_window_seconds() -> int:
    try:
        return max(0, int(os.getenv("POST_PROMOTION_MIN_WINDOW_SECONDS", "7200") or 7200))
    except Exception:
        return 7200


def evaluate_monitoring(db: Session, promotion_id: int, notes: str | None = None) -> Dict[str, Any]:
    promotion = _get_promotion_row(db, promotion_id)
    if (promotion.status or "").lower() != "applied":
        raise ValueError(f"Promotion is not applied: {promotion.status}")
    record = db.query(PromotionMonitoring).filter(PromotionMonitoring.promotion_id == promotion_id).first()
    if record is None:
        initialize_monitoring_record(db, promotion_id, notes=notes)
        record = db.query(PromotionMonitoring).filter(PromotionMonitoring.promotion_id == promotion_id).first()
        if record is None:
            raise ValueError("Unable to initialize monitoring record")

    recommendation = get_recommendation(db, int(promotion.recommendation_id))
    baseline_reference = ((recommendation.get("experiment") or {}).get("baseline") or {}).get("metrics") or {}

    start_at = record.evaluation_window_start or promotion.applied_at or promotion.initiated_at or utc_now_naive()
    now = utc_now_naive()
    observed = snapshot_performance_report(
        db,
        snapshot_id=_observed_snapshot_id(promotion),
        mode=((recommendation.get("experiment") or {}).get("mode") or "demo"),
        start_at=start_at,
        end_at=now,
    )

    baseline_net = float(baseline_reference.get("net_pnl") or 0.0)
    observed_net = float(observed.get("net_pnl") or 0.0)
    baseline_leak = float(baseline_reference.get("cost_leakage_ratio") or 0.0)
    observed_leak = float(observed.get("cost_leakage_ratio") or 0.0)
    baseline_dd = abs(float(baseline_reference.get("drawdown_net") or 0.0))
    observed_dd = abs(float(observed.get("drawdown_net") or 0.0))
    baseline_expectancy = float(baseline_reference.get("net_expectancy") or 0.0)
    observed_expectancy = float(observed.get("net_expectancy") or 0.0)
    baseline_risk = int(baseline_reference.get("risk_actions_count") or 0)
    observed_risk = int(observed.get("risk_actions_count") or 0)
    baseline_win_rate = float(baseline_reference.get("win_rate_net") or 0.0)
    observed_win_rate = float(observed.get("win_rate_net") or 0.0)
    baseline_pf = float(baseline_reference.get("profit_factor_net") or 0.0)
    observed_pf = float(observed.get("profit_factor_net") or 0.0)
    observed_trades = int(observed.get("trade_count") or 0)
    elapsed_seconds = max(0.0, (now - start_at).total_seconds())

    min_trade_gate = observed_trades >= _min_trade_count()
    min_time_gate = elapsed_seconds >= _min_window_seconds()
    reason_codes: List[str] = []
    status = "collecting"
    rollback_recommended = False

    if not min_trade_gate:
        reason_codes.append("POST_PROMOTION_SAMPLE_TOO_SMALL")
    if not min_time_gate:
        reason_codes.append("POST_PROMOTION_TIME_WINDOW_TOO_SHORT")

    if min_trade_gate and min_time_gate:
        degraded = 0
        if observed_net < baseline_net:
            degraded += 1
            reason_codes.append("POST_PROMOTION_NET_PNL_DEGRADATION")
        if observed_dd > baseline_dd * 1.15 + 1e-9:
            degraded += 1
            reason_codes.append("POST_PROMOTION_DRAWDOWN_WORSE")
        if observed_leak > baseline_leak * 1.20 + 1e-9:
            degraded += 1
            reason_codes.append("POST_PROMOTION_COST_LEAKAGE_HIGH")
        if observed_risk > baseline_risk:
            degraded += 1
            reason_codes.append("POST_PROMOTION_RISK_ACTIONS_INCREASED")
        if observed_expectancy < baseline_expectancy:
            degraded += 1
            reason_codes.append("POST_PROMOTION_EXPECTANCY_DOWN")
        # win_rate i profit_factor — dodatkowe sygnały ostrzegawcze (nie wchodzą do rollback_candidate logiki)
        if baseline_win_rate > 0.01 and observed_win_rate < baseline_win_rate * 0.80 - 0.01:
            reason_codes.append("POST_PROMOTION_WIN_RATE_DOWN")
        if baseline_pf > 0.1 and observed_pf < baseline_pf * 0.75 - 0.01:
            reason_codes.append("POST_PROMOTION_PROFIT_FACTOR_DOWN")

        if degraded == 0:
            status = "healthy"
        elif degraded == 1:
            status = "watch"
        elif degraded == 2:
            status = "warning"
        else:
            status = "rollback_candidate"
            rollback_recommended = True

    confidence = 0.25 + min(0.30, observed_trades / 20.0) + min(0.20, elapsed_seconds / max(1, _min_window_seconds() or 1) * 0.1)
    if status in {"collecting", "watch"}:
        confidence -= 0.10
    if status == "rollback_candidate":
        confidence += 0.10
    confidence = max(0.05, min(0.99, confidence))

    # Composite strategy score = weighted sum of kluczowych metryk (info dla operatora)
    _score_baseline = (
        0.35 * baseline_net
        + 0.20 * baseline_expectancy
        + 0.20 * baseline_win_rate
        - 0.15 * baseline_dd
        - 0.10 * (baseline_leak * 100)
    )
    _score_observed = (
        0.35 * observed_net
        + 0.20 * observed_expectancy
        + 0.20 * observed_win_rate
        - 0.15 * observed_dd
        - 0.10 * (observed_leak * 100)
    )
    deviation_summary = {
        "net_pnl_delta": observed_net - baseline_net,
        "cost_leakage_delta": observed_leak - baseline_leak,
        "drawdown_delta": observed_dd - baseline_dd,
        "net_expectancy_delta": observed_expectancy - baseline_expectancy,
        "risk_actions_delta": observed_risk - baseline_risk,
        "win_rate_delta": observed_win_rate - baseline_win_rate,
        "profit_factor_delta": observed_pf - baseline_pf,
        "strategy_score_baseline": round(_score_baseline, 4),
        "strategy_score_observed": round(_score_observed, 4),
        "strategy_score_delta": round(_score_observed - _score_baseline, 4),
        "trade_count": observed_trades,
        "elapsed_seconds": elapsed_seconds,
    }

    record.status = status
    record.last_evaluated_at = now
    record.evaluation_window_end = now
    record.baseline_reference_summary_json = _json_text(baseline_reference)
    record.observed_summary_json = _json_text(observed)
    record.deviation_summary_json = _json_text(deviation_summary)
    record.reason_codes_json = _json_text(sorted(set(reason_codes)))
    record.rollback_recommended = rollback_recommended
    record.min_trade_count_gate_passed = min_trade_gate
    record.min_time_window_gate_passed = min_time_gate
    record.confidence = confidence
    record.evaluation_version = _EVALUATION_VERSION
    record.notes = notes or record.notes

    promotion.post_promotion_monitoring_status = status
    db.commit()
    db.refresh(record)
    return get_monitoring_record(db, int(record.id))


def get_monitoring_record(db: Session, monitoring_id: int) -> Dict[str, Any]:
    row = db.query(PromotionMonitoring).filter(PromotionMonitoring.id == monitoring_id).first()
    if row is None:
        raise ValueError(f"Promotion monitoring record not found: {monitoring_id}")
    promotion = _get_promotion_row(db, int(row.promotion_id))
    return {
        **_monitoring_dict(row),
        "promotion": {
            "id": int(promotion.id),
            "status": promotion.status,
            "from_snapshot_id": promotion.from_snapshot_id,
            "to_snapshot_id": promotion.to_snapshot_id,
            "rollback_snapshot_id": promotion.rollback_snapshot_id,
            "post_promotion_monitoring_status": promotion.post_promotion_monitoring_status,
        },
    }


def get_monitoring_by_promotion(db: Session, promotion_id: int) -> Dict[str, Any]:
    row = db.query(PromotionMonitoring).filter(PromotionMonitoring.promotion_id == promotion_id).first()
    if row is None:
        raise ValueError(f"Promotion monitoring record not found for promotion: {promotion_id}")
    return get_monitoring_record(db, int(row.id))


def list_monitoring_records(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(PromotionMonitoring).order_by(PromotionMonitoring.started_at.desc(), PromotionMonitoring.id.desc()).all()
    return [get_monitoring_record(db, int(row.id)) for row in rows if row.id is not None]
