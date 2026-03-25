"""
Control Plane API - thin HTTP layer over runtime settings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.accounting import get_demo_quote_ccy
from backend.auth import require_admin
from backend.database import Position, get_db
from backend.runtime_settings import RuntimeSettingsError, apply_runtime_updates, build_runtime_state


router = APIRouter()


class ControlStateUpdate(BaseModel):
    trading_mode: Optional[str] = None
    allow_live_trading: Optional[bool] = None
    demo_trading_enabled: Optional[bool] = None
    ws_enabled: Optional[bool] = None
    max_certainty_mode: Optional[bool] = None
    watchlist: Optional[List[str]] = None
    enabled_strategies: Optional[List[str]] = None
    max_open_positions: Optional[int] = None
    max_trades_per_day: Optional[int] = None
    max_trades_per_hour_per_symbol: Optional[int] = None
    loss_streak_limit: Optional[int] = None
    cooldown_after_loss_streak_minutes: Optional[int] = None
    risk_per_trade: Optional[float] = None
    max_daily_drawdown: Optional[float] = None
    max_weekly_drawdown: Optional[float] = None
    kill_switch_enabled: Optional[bool] = None
    maker_fee_rate: Optional[float] = None
    taker_fee_rate: Optional[float] = None
    slippage_bps: Optional[float] = None
    spread_buffer_bps: Optional[float] = None
    min_edge_multiplier: Optional[float] = None
    min_expected_rr: Optional[float] = None
    min_order_notional: Optional[float] = None
    ai_enabled: Optional[bool] = None
    market_data_timeout_seconds: Optional[int] = None
    log_level: Optional[str] = None


def _active_position_count(db: Session) -> int:
    return int(db.query(Position).count())


def _collector_watchlist(request: Request) -> Optional[list[str]]:
    collector = getattr(request.app.state, "collector", None)
    watchlist = getattr(collector, "watchlist", None) if collector is not None else None
    if isinstance(watchlist, list) and watchlist:
        return [str(item) for item in watchlist if item]
    return None


def _build_response_state(request: Request, db: Session) -> Dict[str, Any]:
    state = build_runtime_state(
        db,
        collector_watchlist=_collector_watchlist(request),
        active_position_count=_active_position_count(db),
    )
    state["demo_quote_ccy"] = get_demo_quote_ccy()
    return state


def _actor_from_request(request: Request) -> str:
    client_host = request.client.host if request.client else "unknown"
    return f"control_api:{client_host}"


def _update_payload(update: ControlStateUpdate) -> Dict[str, Any]:
    return update.model_dump(exclude_none=True)


@router.get("/state")
async def get_control_state(request: Request, db: Session = Depends(get_db)):
    try:
        return {"success": True, "data": _build_response_state(request, db)}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error getting control state: {str(exc)}") from exc


@router.post("/state")
async def set_control_state(
    request: Request,
    update: ControlStateUpdate,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        payload = _update_payload(update)
        result = apply_runtime_updates(
            db,
            payload,
            actor=_actor_from_request(request),
            active_position_count=_active_position_count(db),
        )
        state = _build_response_state(request, db)
        return {
            "success": True,
            "data": state,
            "changes": result.get("changed", []),
        }
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error setting control state: {str(exc)}") from exc
