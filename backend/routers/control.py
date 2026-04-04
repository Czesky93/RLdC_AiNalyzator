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
from backend.database import MarketData, Position, get_db
from backend.runtime_settings import RuntimeSettingsError, apply_runtime_updates, build_runtime_state, build_symbol_tier_map, get_runtime_config


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
    min_atr_pct: Optional[float] = None
    min_order_notional: Optional[float] = None
    trading_aggressiveness: Optional[str] = None
    atr_stop_mult: Optional[float] = None
    atr_take_mult: Optional[float] = None
    atr_trail_mult: Optional[float] = None
    bear_regime_min_conf: Optional[float] = None
    bear_oversold_bypass_conf: Optional[float] = None
    extreme_oversold_rsi_threshold: Optional[float] = None
    bear_rsi_sell_gate: Optional[float] = None
    extreme_min_confidence: Optional[float] = None
    extreme_min_rating: Optional[int] = None
    rsi_buy_gate_max: Optional[float] = None
    rsi_sell_gate_min: Optional[float] = None
    min_volume_ratio: Optional[float] = None
    min_adx_for_entry: Optional[float] = None
    demo_min_signal_confidence: Optional[float] = None
    demo_min_entry_score: Optional[float] = None
    demo_allow_soft_buy_entries: Optional[bool] = None
    demo_require_manual_confirm: Optional[bool] = None
    demo_use_heuristic_ranges_fallback: Optional[bool] = None
    live_entry_order_type: Optional[str] = None
    limit_order_timeout: Optional[int] = None
    ai_enabled: Optional[bool] = None
    market_data_timeout_seconds: Optional[int] = None
    log_level: Optional[str] = None
    symbol_tiers: Optional[Dict[str, Any]] = None


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
def get_control_state(request: Request, db: Session = Depends(get_db)):
    try:
        return {"success": True, "data": _build_response_state(request, db)}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error getting control state: {str(exc)}") from exc


@router.post("/state")
def set_control_state(
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


@router.get("/hold-status")
def get_hold_status(db: Session = Depends(get_db)):
    """
    Zwraca status pozycji HOLD (np. WLFI) — aktualną wartość vs. cel.
    Używane do wyświetlania paska postępu WLFI w UI.
    """
    try:
        cfg = get_runtime_config(db)
        tiers_cfg = cfg.get("symbol_tiers") or {}
        tier_map = build_symbol_tier_map(tiers_cfg)

        hold_symbols = [
            sym for sym, overrides in tier_map.items()
            if overrides.get("hold_mode")
        ]

        items = []
        for sym in hold_symbols:
            overrides = tier_map[sym]
            target_eur = float(overrides.get("target_value_eur") or 0)

            # szukamy aktualnej ceny z MarketData
            from sqlalchemy import desc as _desc
            md = (
                db.query(MarketData)
                .filter(MarketData.symbol == sym)
                .order_by(_desc(MarketData.timestamp))
                .first()
            )
            current_price = float(md.price) if md and md.price else None

            # szukamy pozycji w DB (demo lub live)
            pos = (
                db.query(Position)
                .filter(Position.symbol == sym)
                .order_by(_desc(Position.opened_at))
                .first()
            )
            quantity = float(pos.quantity) if pos and pos.quantity else None
            if current_price and quantity:
                position_value = round(current_price * quantity, 2)
            elif pos and pos.current_price and quantity:
                position_value = round(float(pos.current_price) * quantity, 2)
            else:
                position_value = None

            progress_pct = None
            if position_value is not None and target_eur > 0:
                progress_pct = round(min(100.0, position_value / target_eur * 100), 1)

            items.append({
                "symbol": sym,
                "quantity": quantity,
                "current_price": current_price,
                "position_value": position_value,
                "target_eur": target_eur,
                "progress_pct": progress_pct,
                "reached": (position_value or 0) >= target_eur if target_eur > 0 else False,
            })

        return {"success": True, "data": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error getting hold status: {str(exc)}") from exc

