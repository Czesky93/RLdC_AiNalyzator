from __future__ import annotations

import os
from typing import Any, Dict

from sqlalchemy.orm import Session

from backend.database import PendingOrder
from backend.governance import get_operator_queue
from backend.runtime_settings import get_runtime_config

ACTIVE_PENDING_STATUSES = {
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
    "EXCHANGE_SUBMITTED",
    "PARTIALLY_FILLED",
}


def get_queue_pressure_state(db: Session) -> Dict[str, Any]:
    config = get_runtime_config(db)
    threshold = int(
        config.get(
            "queue_backpressure_threshold",
            os.getenv("QUEUE_BACKPRESSURE_THRESHOLD", "10"),
        )
        or 10
    )
    pending_total = int(
        db.query(PendingOrder)
        .filter(PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)))
        .count()
    )
    try:
        operator_queue = get_operator_queue(db)
    except Exception:
        operator_queue = []
    operator_total = len(operator_queue or [])
    pressure = max(pending_total, operator_total)
    level = "normal"
    if pressure >= threshold * 2:
        level = "high"
    elif pressure >= threshold:
        level = "elevated"
    local_only = bool(config.get("force_local_only_on_queue_pressure")) and level != "normal"
    return {
        "pressure": pressure,
        "level": level,
        "pending_total": pending_total,
        "operator_queue_total": operator_total,
        "threshold": threshold,
        "local_only": local_only,
        "drop_non_critical": level != "normal",
        "limit_external_ai": level != "normal",
    }


def should_force_local_only(db: Session) -> bool:
    return bool(get_queue_pressure_state(db).get("local_only"))
