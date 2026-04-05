"""
Rollback execution flow using the same runtime apply path as promotions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import ConfigRollback, get_config_snapshot, utc_now_naive
from backend.governance import enforce_pipeline_permission
from backend.promotion_flow import _active_position_count, _current_runtime_snapshot_id, _snapshot_to_updates
from backend.rollback_decision import get_rollback_decision
from backend.runtime_settings import RuntimeSettingsError, apply_runtime_updates


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _rollback_execution_dict(row: ConfigRollback) -> Dict[str, Any]:
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


def _get_rollback_row(db: Session, rollback_id: int) -> ConfigRollback:
    row = db.query(ConfigRollback).filter(ConfigRollback.id == rollback_id).first()
    if row is None:
        raise ValueError(f"Rollback decision not found: {rollback_id}")
    return row


def _post_rollback_hook(row: ConfigRollback, apply_result: Dict[str, Any]) -> Dict[str, Any]:
    state = (apply_result or {}).get("state") or {}
    return {
        "status": "pending",
        "expected_snapshot_id": state.get("config_snapshot_id") or row.rollback_snapshot_id,
        "source": "rollback_execution",
    }


def execute_rollback(
    db: Session,
    *,
    rollback_id: int,
    initiated_by: str,
    notes: str | None = None,
) -> Dict[str, Any]:
    enforce_pipeline_permission(db, "rollback")
    row = _get_rollback_row(db, rollback_id)
    if row.decision_status not in {"rollback_recommended", "rollback_required"}:
        raise ValueError(f"Rollback decision is not executable: {row.decision_status}")
    if (row.execution_status or "pending") != "pending":
        raise ValueError(f"Rollback execution already processed: {row.execution_status}")
    if not row.rollback_snapshot_id:
        raise ValueError("Rollback target is missing")

    target_snapshot = get_config_snapshot(db, row.rollback_snapshot_id)
    if target_snapshot is None:
        raise ValueError(f"Rollback target snapshot not found: {row.rollback_snapshot_id}")
    source_snapshot = get_config_snapshot(db, row.from_snapshot_id)
    if source_snapshot is None:
        raise ValueError(f"Rollback source snapshot not found: {row.from_snapshot_id}")

    current_snapshot_id = _current_runtime_snapshot_id(db)
    validation_summary = {
        "current_snapshot_id": current_snapshot_id,
        "expected_from_snapshot_id": row.from_snapshot_id,
        "rollback_snapshot_id": row.rollback_snapshot_id,
        "current_matches_expected": current_snapshot_id == row.from_snapshot_id,
        "decision_status": row.decision_status,
        "same_apply_path_as_promotion": True,
    }
    row.validation_summary_json = _json_text(validation_summary)
    if current_snapshot_id != row.from_snapshot_id:
        row.execution_status = "failed"
        row.failed_at = utc_now_naive()
        row.failure_reason = f"ROLLBACK_RUNTIME_DRIFT: active runtime snapshot {current_snapshot_id} does not match expected {row.from_snapshot_id}"
        db.commit()
        db.refresh(row)
        raise ValueError(row.failure_reason)

    updates = _snapshot_to_updates(target_snapshot, source_snapshot)
    try:
        apply_result = apply_runtime_updates(
            db,
            updates,
            actor=f"rollback:{initiated_by}",
            active_position_count=_active_position_count(db),
        )
        row.execution_status = "executed"
        row.executed_at = utc_now_naive()
        row.runtime_apply_result_json = _json_text(
            {
                **(apply_result or {}),
                "post_rollback_hook": _post_rollback_hook(row, apply_result),
            }
        )
        row.post_rollback_monitoring_status = "pending"
        row.notes = notes or row.notes
        db.commit()
        from backend.post_rollback_monitoring import initialize_post_rollback_monitoring
        initialize_post_rollback_monitoring(db, int(row.id), notes="initialized after successful rollback")
    except (RuntimeSettingsError, ValueError) as exc:
        db.rollback()
        row = _get_rollback_row(db, rollback_id)
        row.execution_status = "failed"
        row.failed_at = utc_now_naive()
        row.failure_reason = str(exc)
        row.notes = notes or row.notes
        db.commit()
        db.refresh(row)
        return get_rollback_execution(db, rollback_id)

    db.refresh(row)
    return get_rollback_execution(db, rollback_id)


def get_rollback_execution(db: Session, rollback_id: int) -> Dict[str, Any]:
    row = _get_rollback_row(db, rollback_id)
    return {
        **_rollback_execution_dict(row),
        "rollback": get_rollback_decision(db, rollback_id),
    }


def list_rollback_executions(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(ConfigRollback).order_by(ConfigRollback.initiated_at.desc(), ConfigRollback.id.desc()).all()
    return [get_rollback_execution(db, int(row.id)) for row in rows if row.id is not None]
