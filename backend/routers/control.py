"""
Control Plane API - runtime overrides (stop trading / ws / modes).
"""

from __future__ import annotations

from datetime import datetime
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.accounting import get_demo_quote_ccy
from backend.auth import require_admin
from backend.database import get_db
from backend.runtime_settings import effective_bool, get_overrides, upsert_overrides


router = APIRouter()


def _parse_watchlist(raw: str) -> List[str]:
    items = [s.strip() for s in (raw or "").split(",") if s.strip()]
    wl: List[str] = []
    for item in items:
        sym = (item or "").strip()
        if not sym:
            continue
        sym = sym.replace(" ", "").replace("/", "").replace("-", "").upper()
        if sym and sym not in wl:
            wl.append(sym)
    return wl


def _effective_watchlist(request: Request, overrides: dict) -> List[str]:
    if overrides.get("watchlist") is not None:
        return _parse_watchlist(overrides.get("watchlist") or "")

    collector = getattr(request.app.state, "collector", None)
    if collector is not None:
        wl = getattr(collector, "watchlist", None)
        if isinstance(wl, list) and wl:
            return [str(s) for s in wl if s]

    raw = os.getenv("WATCHLIST", "")
    return _parse_watchlist(raw)


def _build_state(request: Request, db: Session) -> dict:
    overrides = get_overrides(db, ["demo_trading_enabled", "ws_enabled", "max_certainty_mode", "watchlist"])
    data = {
        "demo_trading_enabled": effective_bool(db, "demo_trading_enabled", "DEMO_TRADING_ENABLED", True),
        "ws_enabled": effective_bool(db, "ws_enabled", "WS_ENABLED", True),
        "max_certainty_mode": effective_bool(db, "max_certainty_mode", "MAX_CERTAINTY_MODE", False),
        "watchlist": _effective_watchlist(request, overrides),
        "demo_quote_ccy": get_demo_quote_ccy(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    return data


class ControlStateUpdate(BaseModel):
    demo_trading_enabled: Optional[bool] = None
    ws_enabled: Optional[bool] = None
    max_certainty_mode: Optional[bool] = None
    watchlist: Optional[List[str]] = None


@router.get("/state")
async def get_control_state(request: Request, db: Session = Depends(get_db)):
    try:
        return {"success": True, "data": _build_state(request, db)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error getting control state: {str(exc)}")


@router.post("/state")
async def set_control_state(
    request: Request,
    update: ControlStateUpdate,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        changes = {}
        if update.demo_trading_enabled is not None:
            changes["demo_trading_enabled"] = "true" if update.demo_trading_enabled else "false"
        if update.ws_enabled is not None:
            changes["ws_enabled"] = "true" if update.ws_enabled else "false"
        if update.max_certainty_mode is not None:
            changes["max_certainty_mode"] = "true" if update.max_certainty_mode else "false"
        if update.watchlist is not None:
            if not update.watchlist:
                changes["watchlist"] = None
            else:
                normalized = _parse_watchlist(",".join(update.watchlist))
                changes["watchlist"] = ",".join(normalized)

        upsert_overrides(db, changes)
        return {"success": True, "data": _build_state(request, db)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error setting control state: {str(exc)}")

