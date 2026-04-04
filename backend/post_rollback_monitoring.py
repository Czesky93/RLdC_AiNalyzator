"""
Post-rollback monitoring for executed rollbacks.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import ConfigRollback, RollbackMonitoring, utc_now_naive
from backend.experiments import snapshot_performance_report


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


def _monitoring_dict(row: RollbackMonitoring) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "rollback_id": int(row.rollback_id),
        "promotion_id": int(row.promotion_id),
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
        "evaluation_window_start": row.evaluation_window_start.isoformat() if row.evaluation_window_start else None,
        "evaluation_window_end": row.evaluation_window_end.isoformat() if row.evaluation_window_end else None,
        "pre_rollback_summary": _json_load(row.pre_rollback_summary_json) or {},
        "observed_summary": _json_load(row.observed_summary_json) or {},
        "deviation_summary": _json_load(row.deviation_summary_json) or {},
        "reason_codes": _json_load(row.reason_codes_json) or [],
        "min_trade_count_gate_passed": bool(row.min_trade_count_gate_passed),
        "min_time_window_gate_passed": bool(row.min_time_window_gate_passed),
        "confidence": float(row.confidence or 0.0),
        "evaluation_version": row.evaluation_version,
        "notes": row.notes,
    }


def _get_rollback_row(db: Session, rollback_id: int) -> ConfigRollback:
    row = db.query(ConfigRollback).filter(ConfigRollback.id == rollback_id).first()
    if row is None:
        raise ValueError(f"Rollback not found: {rollback_id}")
    return row


def _post_apply_snapshot_id(row: ConfigRollback) -> str:
    payload = _json_load(row.runtime_apply_result_json) or {}
    state = payload.get("state") or {}
    return str(state.get("config_snapshot_id") or row.rollback_snapshot_id or row.to_snapshot_id)


def _min_trade_count() -> int:
    try:
        return max(1, int(os.getenv("POST_ROLLBACK_MIN_TRADE_COUNT", "20") or 20))
    except Exception:
        return 20


def _min_window_seconds() -> int:
    try:
        return max(0, int(os.getenv("POST_ROLLBACK_MIN_WINDOW_SECONDS", "7200") or 7200))
    except Exception:
        return 7200


def initialize_post_rollback_monitoring(db: Session, rollback_id: int, notes: str | None = None) -> Dict[str, Any]:
    rollback = _get_rollback_row(db, rollback_id)
    existing = db.query(RollbackMonitoring).filter(RollbackMonitoring.rollback_id == rollback_id).first()
    if existing is not None:
        return get_post_rollback_monitoring_record(db, int(existing.id))
    start_at = rollback.executed_at or rollback.initiated_at or utc_now_naive()
    row = RollbackMonitoring(
        rollback_id=rollback_id,
        promotion_id=rollback.promotion_id,
        from_snapshot_id=rollback.from_snapshot_id,
        to_snapshot_id=_post_apply_snapshot_id(rollback),
        status="pending",
        started_at=start_at,
        evaluation_window_start=start_at,
        evaluation_version=_EVALUATION_VERSION,
        notes=notes,
    )
    db.add(row)
    rollback.post_rollback_monitoring_status = "pending"
    db.commit()
    db.refresh(row)
    return get_post_rollback_monitoring_record(db, int(row.id))


def evaluate_post_rollback_monitoring(db: Session, rollback_id: int, notes: str | None = None) -> Dict[str, Any]:
    rollback = _get_rollback_row(db, rollback_id)
    if (rollback.execution_status or "").lower() != "executed":
        raise ValueError(f"Rollback is not executed: {rollback.execution_status}")

    record = db.query(RollbackMonitoring).filter(RollbackMonitoring.rollback_id == rollback_id).first()
    if record is None:
        initialize_post_rollback_monitoring(db, rollback_id, notes=notes)
        record = db.query(RollbackMonitoring).filter(RollbackMonitoring.rollback_id == rollback_id).first()
        if record is None:
            raise ValueError("Unable to initialize rollback monitoring record")

    apply_result = _json_load(rollback.runtime_apply_result_json) or {}
    state = apply_result.get("state") or {}
    mode = str(state.get("trading_mode") or "demo")

    pre_start = rollback.initiated_at
    pre_end = rollback.executed_at or rollback.initiated_at or utc_now_naive()
    pre_summary = snapshot_performance_report(
        db,
        snapshot_id=rollback.from_snapshot_id,
        mode=mode,
        start_at=pre_start,
        end_at=pre_end,
    )

    start_at = record.evaluation_window_start or rollback.executed_at or rollback.initiated_at or utc_now_naive()
    now = utc_now_naive()
    observed = snapshot_performance_report(
        db,
        snapshot_id=_post_apply_snapshot_id(rollback),
        mode=mode,
        start_at=start_at,
        end_at=now,
    )

    pre_net = float(pre_summary.get("net_pnl") or 0.0)
    obs_net = float(observed.get("net_pnl") or 0.0)
    pre_leak = float(pre_summary.get("cost_leakage_ratio") or 0.0)
    obs_leak = float(observed.get("cost_leakage_ratio") or 0.0)
    pre_dd = abs(float(pre_summary.get("drawdown_net") or 0.0))
    obs_dd = abs(float(observed.get("drawdown_net") or 0.0))
    pre_risk = int(pre_summary.get("risk_actions_count") or 0)
    obs_risk = int(observed.get("risk_actions_count") or 0)
    pre_blocked = int(pre_summary.get("blocked_decisions") or 0)
    obs_blocked = int(observed.get("blocked_decisions") or 0)
    obs_trades = int(observed.get("trade_count") or 0)
    elapsed_seconds = max(0.0, (now - start_at).total_seconds())

    min_trade_gate = obs_trades >= _min_trade_count()
    min_time_gate = elapsed_seconds >= _min_window_seconds()
    reason_codes: List[str] = []
    status = "collecting"

    if not min_trade_gate:
        reason_codes.append("POST_ROLLBACK_SAMPLE_TOO_SMALL")
    if not min_time_gate:
        reason_codes.append("POST_ROLLBACK_TIME_WINDOW_TOO_SHORT")

    if min_trade_gate and min_time_gate:
        improved = 0
        degraded = 0
        if obs_net >= pre_net:
            improved += 1
            reason_codes.append("POST_ROLLBACK_NET_PNL_RECOVERED")
        else:
            degraded += 1
            reason_codes.append("POST_ROLLBACK_NET_PNL_STILL_WEAK")
        if obs_dd <= pre_dd * 0.95 + 1e-9:
            improved += 1
            reason_codes.append("POST_ROLLBACK_DRAWDOWN_IMPROVED")
        elif pre_dd > 0 and obs_dd > pre_dd * 1.10 + 1e-9:
            degraded += 1
            reason_codes.append("POST_ROLLBACK_DRAWDOWN_STILL_HIGH")
        if obs_leak <= pre_leak * 0.95 + 1e-9:
            improved += 1
            reason_codes.append("POST_ROLLBACK_LEAKAGE_IMPROVED")
        elif pre_leak > 0 and obs_leak > pre_leak * 1.10 + 1e-9:
            degraded += 1
            reason_codes.append("POST_ROLLBACK_LEAKAGE_STILL_HIGH")
        if obs_risk <= pre_risk and obs_blocked <= pre_blocked:
            improved += 1
            reason_codes.append("POST_ROLLBACK_RISK_PRESSURE_REDUCED")
        elif obs_risk > pre_risk or obs_blocked > pre_blocked:
            degraded += 1
            reason_codes.append("POST_ROLLBACK_RISK_PRESSURE_PERSISTENT")

        critical_persistence = (
            obs_net < pre_net
            and (obs_risk > pre_risk or obs_blocked > pre_blocked)
            and (obs_dd > pre_dd * 1.10 + 1e-9 or degraded >= 2)
        )

        if critical_persistence:
            status = "escalate"
        elif degraded == 0 and improved >= 2:
            status = "stabilized"
        elif degraded == 0:
            status = "watch"
        elif degraded <= 2:
            status = "warning"
        else:
            status = "escalate"

    confidence = 0.25 + min(0.30, obs_trades / 20.0) + min(0.20, elapsed_seconds / max(1, _min_window_seconds() or 1) * 0.1)
    if status in {"collecting", "watch"}:
        confidence -= 0.10
    if status == "escalate":
        confidence += 0.10
    confidence = max(0.05, min(0.99, confidence))

    deviation_summary = {
        "net_pnl_delta": obs_net - pre_net,
        "cost_leakage_delta": obs_leak - pre_leak,
        "drawdown_delta": obs_dd - pre_dd,
        "risk_actions_delta": obs_risk - pre_risk,
        "blocked_decisions_delta": obs_blocked - pre_blocked,
        "trade_count": obs_trades,
        "elapsed_seconds": elapsed_seconds,
    }

    record.status = status
    record.last_evaluated_at = now
    record.evaluation_window_end = now
    record.pre_rollback_summary_json = _json_text(pre_summary)
    record.observed_summary_json = _json_text(observed)
    record.deviation_summary_json = _json_text(deviation_summary)
    record.reason_codes_json = _json_text(sorted(set(reason_codes)))
    record.min_trade_count_gate_passed = min_trade_gate
    record.min_time_window_gate_passed = min_time_gate
    record.confidence = confidence
    record.evaluation_version = _EVALUATION_VERSION
    record.notes = notes or record.notes

    rollback.post_rollback_monitoring_status = status
    db.commit()
    db.refresh(record)
    return get_post_rollback_monitoring_record(db, int(record.id))


def get_post_rollback_monitoring_record(db: Session, monitoring_id: int) -> Dict[str, Any]:
    row = db.query(RollbackMonitoring).filter(RollbackMonitoring.id == monitoring_id).first()
    if row is None:
        raise ValueError(f"Rollback monitoring record not found: {monitoring_id}")
    rollback = _get_rollback_row(db, int(row.rollback_id))
    return {
        **_monitoring_dict(row),
        "rollback": {
            "id": int(rollback.id),
            "promotion_id": int(rollback.promotion_id),
            "decision_status": rollback.decision_status,
            "execution_status": rollback.execution_status,
            "from_snapshot_id": rollback.from_snapshot_id,
            "to_snapshot_id": rollback.to_snapshot_id,
            "rollback_snapshot_id": rollback.rollback_snapshot_id,
            "post_rollback_monitoring_status": rollback.post_rollback_monitoring_status,
        },
    }


def get_post_rollback_monitoring_by_rollback(db: Session, rollback_id: int) -> Dict[str, Any]:
    row = db.query(RollbackMonitoring).filter(RollbackMonitoring.rollback_id == rollback_id).first()
    if row is None:
        raise ValueError(f"Rollback monitoring record not found for rollback: {rollback_id}")
    return get_post_rollback_monitoring_record(db, int(row.id))


def list_post_rollback_monitoring_records(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(RollbackMonitoring).order_by(RollbackMonitoring.started_at.desc(), RollbackMonitoring.id.desc()).all()
    return [get_post_rollback_monitoring_record(db, int(row.id)) for row in rows if row.id is not None]
