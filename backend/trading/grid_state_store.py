"""Persistence helpers for dynamic grid runtime state."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from backend.database import RuntimeSetting, utc_now_naive

ACTIVE_GRID_PLANS_KEY = "active_grid_plans"


def load_active_grid_plans(db: Session) -> dict[str, dict[str, Any]]:
    """Load the active grid plan map from RuntimeSetting."""
    row = (
        db.query(RuntimeSetting)
        .filter(RuntimeSetting.key == ACTIVE_GRID_PLANS_KEY)
        .first()
    )
    if not row or not row.value:
        return {}

    try:
        data = json.loads(row.value)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    return {
        str(symbol).strip().upper(): dict(plan)
        for symbol, plan in data.items()
        if symbol and isinstance(plan, dict)
    }


def save_active_grid_plans(db: Session, plans: dict[str, dict[str, Any]]) -> None:
    """Save the full active grid plan map as one atomic RuntimeSetting payload."""
    normalized = {
        str(symbol).strip().upper(): dict(plan)
        for symbol, plan in (plans or {}).items()
        if symbol and isinstance(plan, dict)
    }
    payload = json.dumps(normalized, ensure_ascii=True, sort_keys=True)

    row = (
        db.query(RuntimeSetting)
        .filter(RuntimeSetting.key == ACTIVE_GRID_PLANS_KEY)
        .first()
    )
    now = utc_now_naive()
    if row is None:
        db.add(RuntimeSetting(key=ACTIVE_GRID_PLANS_KEY, value=payload, updated_at=now))
    else:
        row.value = payload
        row.updated_at = now
