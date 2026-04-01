"""
Rollback decision layer consuming post-promotion monitoring verdicts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import ConfigPromotion, ConfigRollback, PromotionMonitoring, utc_now_naive
from backend.post_promotion_monitoring import get_monitoring_by_promotion, get_monitoring_record


_SEVERE_MONITORING_CODES = {
    "POST_PROMOTION_NET_PNL_DEGRADATION": "ROLLBACK_NET_PNL_DEGRADATION",
    "POST_PROMOTION_DRAWDOWN_WORSE": "ROLLBACK_DRAWDOWN_BREACH",
    "POST_PROMOTION_COST_LEAKAGE_HIGH": "ROLLBACK_COST_LEAKAGE_BREACH",
    "POST_PROMOTION_RISK_ACTIONS_INCREASED": "ROLLBACK_RISK_ACTIONS_SURGE",
    "POST_PROMOTION_EXPECTANCY_DOWN": "ROLLBACK_EXPECTANCY_DETERIORATION",
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


def _rollback_dict(row: ConfigRollback) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "promotion_id": int(row.promotion_id),
        "monitoring_id": int(row.monitoring_id),
        "decision_source": row.decision_source,
        "decision_status": row.decision_status,
        "execution_status": row.execution_status,
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "rollback_snapshot_id": row.rollback_snapshot_id,
        "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
        "failed_at": row.failed_at.isoformat() if row.failed_at else None,
        "initiated_by": row.initiated_by,
        "failure_reason": row.failure_reason,
        "validation_summary": _json_load(row.validation_summary_json) or {},
        "runtime_apply_result": _json_load(row.runtime_apply_result_json) or {},
        "reason_codes": _json_load(row.rollback_reason_codes_json) or [],
        "urgency": row.urgency,
        "notes": row.notes,
        "post_rollback_monitoring_status": row.post_rollback_monitoring_status,
    }


def _get_promotion(db: Session, promotion_id: int) -> ConfigPromotion:
    row = db.query(ConfigPromotion).filter(ConfigPromotion.id == promotion_id).first()
    if row is None:
        raise ValueError(f"Promotion not found: {promotion_id}")
    return row


def _get_monitoring(db: Session, promotion_id: int, monitoring_id: int | None = None) -> Dict[str, Any]:
    if monitoring_id is not None:
        monitoring = get_monitoring_record(db, monitoring_id)
        if int(monitoring["promotion_id"]) != promotion_id:
            raise ValueError(f"Monitoring {monitoring_id} does not belong to promotion {promotion_id}")
        return monitoring
    return get_monitoring_by_promotion(db, promotion_id)


def evaluate_rollback_decision(monitoring: Dict[str, Any]) -> Dict[str, Any]:
    status = (monitoring.get("status") or "pending").lower()
    reason_codes = list(monitoring.get("reason_codes") or [])
    deviation = monitoring.get("deviation_summary") or {}
    sample_ok = bool(monitoring.get("min_trade_count_gate_passed"))
    time_ok = bool(monitoring.get("min_time_window_gate_passed"))
    severe_codes = [code for code in reason_codes if code in _SEVERE_MONITORING_CODES]

    decision_status = "continue_monitoring"
    urgency = "low"
    rollback_reason_codes: List[str] = []

    if status == "healthy":
        decision_status = "no_action"
        urgency = "low"
        rollback_reason_codes.append("ROLLBACK_NO_ACTION_HEALTHY")
    elif status in {"pending", "collecting"}:
        decision_status = "continue_monitoring"
        urgency = "low"
        rollback_reason_codes.append("ROLLBACK_CONTINUE_MONITORING")
        if not sample_ok:
            rollback_reason_codes.append("ROLLBACK_SAMPLE_TOO_SMALL")
        if not time_ok:
            rollback_reason_codes.append("ROLLBACK_TIME_WINDOW_TOO_SHORT")
    elif status == "watch":
        decision_status = "continue_monitoring"
        urgency = "medium"
        rollback_reason_codes.append("ROLLBACK_CONTINUE_MONITORING")
        rollback_reason_codes.append("ROLLBACK_MONITORING_WARNING_PERSISTENT")
    elif status == "warning":
        if len(severe_codes) >= 2:
            decision_status = "rollback_recommended"
            urgency = "high"
        else:
            decision_status = "continue_monitoring"
            urgency = "medium"
            rollback_reason_codes.append("ROLLBACK_CONTINUE_MONITORING")
        rollback_reason_codes.append("ROLLBACK_MONITORING_WARNING_PERSISTENT")
    elif status == "rollback_candidate":
        net_delta = float(deviation.get("net_pnl_delta") or 0.0)
        drawdown_delta = float(deviation.get("drawdown_delta") or 0.0)
        leak_delta = float(deviation.get("cost_leakage_delta") or 0.0)
        critical_breach = (
            "POST_PROMOTION_DRAWDOWN_WORSE" in reason_codes
            or ("POST_PROMOTION_COST_LEAKAGE_HIGH" in reason_codes and "POST_PROMOTION_NET_PNL_DEGRADATION" in reason_codes)
            or (net_delta < 0 and drawdown_delta > 0 and leak_delta > 0)
        )
        decision_status = "rollback_required" if critical_breach else "rollback_recommended"
        urgency = "critical" if critical_breach else "high"
    else:
        decision_status = "continue_monitoring"
        urgency = "medium"
        rollback_reason_codes.append("ROLLBACK_CONTINUE_MONITORING")

    rollback_reason_codes.extend(_SEVERE_MONITORING_CODES[code] for code in severe_codes)
    rollback_reason_codes = sorted(set(rollback_reason_codes))
    summary = (
        f"{decision_status}: monitoring={status}, sample_ok={sample_ok}, time_ok={time_ok}, "
        f"reasons={','.join(rollback_reason_codes) or 'none'}"
    )
    return {
        "decision_status": decision_status,
        "reason_codes": rollback_reason_codes,
        "summary": summary,
        "urgency": urgency,
    }


def create_rollback_decision(
    db: Session,
    *,
    promotion_id: int,
    initiated_by: str | None = None,
    monitoring_id: int | None = None,
    notes: str | None = None,
    decision_source: str = "monitoring",
) -> Dict[str, Any]:
    promotion = _get_promotion(db, promotion_id)
    monitoring = _get_monitoring(db, promotion_id, monitoring_id=monitoring_id)
    if (promotion.status or "").lower() != "applied":
        raise ValueError(f"Promotion is not applied: {promotion.status}")
    if not promotion.rollback_available or not promotion.rollback_snapshot_id:
        raise ValueError("Promotion does not have a rollback target")

    existing = (
        db.query(ConfigRollback)
        .filter(
            ConfigRollback.promotion_id == promotion_id,
            ConfigRollback.monitoring_id == int(monitoring["id"]),
        )
        .order_by(ConfigRollback.initiated_at.desc(), ConfigRollback.id.desc())
        .first()
    )
    if existing is not None:
        return get_rollback_decision(db, int(existing.id))

    decision = evaluate_rollback_decision(monitoring)
    validation_summary = {
        "promotion_status": promotion.status,
        "monitoring_status": monitoring.get("status"),
        "rollback_available": bool(promotion.rollback_available),
        "rollback_snapshot_id": promotion.rollback_snapshot_id,
        "sample_ok": bool(monitoring.get("min_trade_count_gate_passed")),
        "time_window_ok": bool(monitoring.get("min_time_window_gate_passed")),
    }

    row = ConfigRollback(
        promotion_id=promotion_id,
        monitoring_id=int(monitoring["id"]),
        decision_source=decision_source,
        decision_status=decision["decision_status"],
        from_snapshot_id=promotion.to_snapshot_id,
        to_snapshot_id=promotion.rollback_snapshot_id,
        rollback_snapshot_id=promotion.rollback_snapshot_id,
        initiated_at=utc_now_naive(),
        initiated_by=initiated_by,
        validation_summary_json=_json_text(validation_summary),
        rollback_reason_codes_json=_json_text(decision["reason_codes"]),
        urgency=decision["urgency"],
        notes=notes or decision["summary"],
        post_rollback_monitoring_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return get_rollback_decision(db, int(row.id))


def get_rollback_decision(db: Session, rollback_id: int) -> Dict[str, Any]:
    row = db.query(ConfigRollback).filter(ConfigRollback.id == rollback_id).first()
    if row is None:
        raise ValueError(f"Rollback decision not found: {rollback_id}")
    return {
        **_rollback_dict(row),
        "promotion": _promotion_summary(db, int(row.promotion_id)),
        "monitoring": get_monitoring_record(db, int(row.monitoring_id)),
    }


def _promotion_summary(db: Session, promotion_id: int) -> Dict[str, Any]:
    row = _get_promotion(db, promotion_id)
    return {
        "id": int(row.id),
        "status": row.status,
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "rollback_available": bool(row.rollback_available),
        "rollback_snapshot_id": row.rollback_snapshot_id,
        "post_promotion_monitoring_status": row.post_promotion_monitoring_status,
    }


def list_rollback_decisions(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(ConfigRollback).order_by(ConfigRollback.initiated_at.desc(), ConfigRollback.id.desc()).all()
    return [get_rollback_decision(db, int(row.id)) for row in rows if row.id is not None]


def latest_rollback_decision_for_promotion(db: Session, promotion_id: int) -> Dict[str, Any]:
    row = (
        db.query(ConfigRollback)
        .filter(ConfigRollback.promotion_id == promotion_id)
        .order_by(ConfigRollback.initiated_at.desc(), ConfigRollback.id.desc())
        .first()
    )
    if row is None:
        raise ValueError(f"Rollback decision not found for promotion: {promotion_id}")
    return get_rollback_decision(db, int(row.id))
