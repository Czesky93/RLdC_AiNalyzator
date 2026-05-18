"""Factories that keep dynamic-grid orders aligned with the DB model."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from backend.database import PendingOrder, utc_now_naive


def _pending_order_columns() -> set[str]:
    return {column.name for column in PendingOrder.__table__.columns}


def create_pending_order_from_grid(
    *,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    mode: str,
    reason: str,
    plan_payload: dict[str, Any],
    auto_confirm: bool = True,
) -> PendingOrder:
    """Create a market-on-touch PendingOrder using only real PendingOrder fields."""
    now = utc_now_naive()
    side_norm = str(side or "").strip().upper()
    mode_norm = str(mode or "demo").strip().lower()
    status = "PENDING_CONFIRMED" if auto_confirm else "PENDING_CREATED"
    plan_json = json.dumps(plan_payload or {}, ensure_ascii=True, sort_keys=True)
    reason_full = f"{reason} | RLDC_GRID_PLAN={plan_json}".strip(" |")

    payload: dict[str, Any] = {
        "symbol": str(symbol or "").strip().upper().replace("/", "").replace("-", ""),
        "side": side_norm,
        "order_type": "MARKET",
        "price": float(price),
        "quantity": float(quantity),
        "mode": mode_norm,
        "status": status,
        "reason": reason_full,
        "strategy_name": "dynamic_grid",
        "source": "dynamic_grid",
        "pending_type": f"auto_{mode_norm}",
        "created_at": now,
        "confirmed_at": now if auto_confirm else None,
        "expires_at": now + timedelta(hours=24),
    }

    columns = _pending_order_columns()
    clean_payload = {key: value for key, value in payload.items() if key in columns}
    return PendingOrder(**clean_payload)
