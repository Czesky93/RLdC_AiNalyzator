"""
Router: Telegram Intelligence Layer
Endpointy diagnostyczne i ocena celu użytkownika.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.database import get_db
from backend.telegram_intelligence import (
    build_telegram_intelligence_state,
    evaluate_goal,
    get_messages_page,
    log_telegram_event,
    CAT_SIGNAL, CAT_EXECUTION, CAT_BLOCKER, CAT_RISK, CAT_STATUS, CAT_OPERATOR, CAT_TARGET,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/telegram-intel/state
# ---------------------------------------------------------------------------

@router.get("/state")
async def get_intelligence_state(
    mode: str = Query("demo", enum=["demo", "live"]),
    db=Depends(get_db),
):
    """
    Zwraca aktualny stan interpretacyjny Telegram Intelligence:
    - ostatni sygnał, egzekucja, blokery
    - system health
    - bias decyzyjny (BUY/SELL/WAIT/NO_TRADING)
    - statystyki z ostatnich 2h
    """
    try:
        state = build_telegram_intelligence_state(db, mode=mode)
        return {"ok": True, "data": state}
    except Exception as exc:
        logger.error("telegram-intel/state error: %s", exc)
        return {"ok": False, "data": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# GET /api/telegram-intel/messages
# ---------------------------------------------------------------------------

@router.get("/messages")
async def get_messages(
    limit: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None),
    since_minutes: int = Query(120, ge=5, le=1440),
    db=Depends(get_db),
):
    """
    Zwraca archiwum wiadomości Telegram z parsowanymi metadanymi.
    Opcjonalnie filtruj po kategorii: SIGNAL_MESSAGE, EXECUTION_MESSAGE, BLOCKER_MESSAGE, itd.
    """
    try:
        msgs = get_messages_page(db, limit=limit, category=category, since_minutes=since_minutes)
        return {
            "ok": True,
            "count": len(msgs),
            "categories": [
                CAT_SIGNAL, CAT_EXECUTION, CAT_BLOCKER,
                CAT_RISK, CAT_STATUS, CAT_OPERATOR, CAT_TARGET,
            ],
            "messages": msgs,
        }
    except Exception as exc:
        logger.error("telegram-intel/messages error: %s", exc)
        return {"ok": False, "messages": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# POST /api/telegram-intel/evaluate-goal
# ---------------------------------------------------------------------------

class GoalRequest(BaseModel):
    target_type: str = "position_value"      # position_value | portfolio_value | profit_pct | price_target
    current_value: float
    target_value: float
    symbol: Optional[str] = None
    entry_price: Optional[float] = None
    quantity: Optional[float] = None
    atr: Optional[float] = None
    daily_volatility_pct: Optional[float] = None


@router.post("/evaluate-goal")
async def evaluate_goal_endpoint(payload: GoalRequest):
    """
    Ocenia realność celu użytkownika.

    Przykład: current_value=500, target_value=650, target_type="portfolio_value"
    → ocena: „realny" + co zrobić, żeby to osiągnąć + horyzont czasowy.
    """
    try:
        result = evaluate_goal(
            target_type=payload.target_type,
            current_value=payload.current_value,
            target_value=payload.target_value,
            symbol=payload.symbol,
            entry_price=payload.entry_price,
            quantity=payload.quantity,
            atr=payload.atr,
            daily_volatility_pct=payload.daily_volatility_pct,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.error("telegram-intel/evaluate-goal error: %s", exc)
        return {"ok": False, "result": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# POST /api/telegram-intel/log-event  (wewnętrzny, do testów i UI)
# ---------------------------------------------------------------------------

class LogEventRequest(BaseModel):
    text: str
    source_module: str = "ui"
    direction: str = "incoming"


@router.post("/log-event")
async def log_event_endpoint(payload: LogEventRequest, db=Depends(get_db)):
    """Ręczny zapis wiadomości do archiwum Telegram (do testów z UI)."""
    try:
        log_telegram_event(
            raw_text=payload.text,
            source_module=payload.source_module,
            direction=payload.direction,
            message_type="manual",
            db=db,
        )
        return {"ok": True}
    except Exception as exc:
        logger.error("telegram-intel/log-event error: %s", exc)
        return {"ok": False, "error": str(exc)}
