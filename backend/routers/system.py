"""
System Status & Logs API — thin HTTP layer.
Endpointy:
  GET  /api/system/status        — pełny status systemu
  GET  /api/system/public-url    — aktywny publiczny adres panelu
  GET  /api/system/logs/stream   — SSE stream logów z bazy
  GET  /api/system/events        — ostatnie 100 eventów systemowych
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database import SessionLocal, SystemLog, get_db, utc_now_naive
from backend.public_url import get_public_url_info

router = APIRouter()

_START_TIME = time.time()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _uptime_str(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m}m {s}s"


def _collector_info(request: Request) -> dict:
    collector = getattr(request.app.state, "collector", None)
    if collector is None:
        return {"running": False, "status": "not_started"}
    status = getattr(collector, "running", False) or getattr(collector, "_running", False)
    watchlist = getattr(collector, "watchlist", []) or []
    last_tick = getattr(collector, "last_tick_ts", None)
    return {
        "running": bool(status),
        "status": "active" if status else "stopped",
        "watchlist_size": len(watchlist),
        "watchlist": list(watchlist)[:10],
        "last_tick_ts": (
            datetime.fromtimestamp(last_tick, tz=timezone.utc).isoformat()
            if last_tick else None
        ),
    }


def _db_info(db: Session) -> dict:
    try:
        count = db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM system_logs")).scalar()
        return {"connected": True, "log_count": count}
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def _ai_info() -> dict:
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    return {
        "openai_enabled": bool(openai_key),
        "provider": "openai" if openai_key else "heuristic",
    }


def _binance_info() -> dict:
    from backend.binance_client import BinanceClient
    try:
        b = BinanceClient()
        ticker = b.get_ticker_price("BTCUSDT")
        price = float(ticker.get("price", 0)) if ticker else None
        return {"connected": bool(price), "status": "online" if price else "error"}
    except Exception as exc:
        return {"connected": False, "status": "error", "detail": str(exc)[:120]}


def _telegram_info() -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return {
        "configured": bool(token and chat_id),
        "status": "configured" if (token and chat_id) else "not_configured",
    }


# ─────────────────────────────────────────────
# Endpointy
# ─────────────────────────────────────────────

@router.get("/status")
def get_system_status(request: Request, db: Session = Depends(get_db)):
    """Pełny status systemu — collector, DB, AI, Binance, Telegram, uptime."""
    uptime_sec = time.time() - _START_TIME
    collector = _collector_info(request)
    db_info = _db_info(db)
    ai_info = _ai_info()
    telegram_info = _telegram_info()
    trading_mode = os.getenv("TRADING_MODE", "demo").lower()

    # ostatni log
    last_log = (
        db.query(SystemLog)
        .order_by(SystemLog.id.desc())
        .first()
    )
    last_log_info = None
    if last_log:
        last_log_info = {
            "level": last_log.level,
            "module": last_log.module,
            "message": (last_log.message or "")[:120],
            "timestamp": last_log.timestamp.isoformat() if last_log.timestamp else None,
        }

    # Binance sprawdzamy lekko — bez blokowania całej odpowiedzi
    binance_info: dict[str, Any] = {"status": "skipped"}
    try:
        binance_info = _binance_info()
    except Exception:
        binance_info = {"connected": False, "status": "error"}

    # Market regime — z cache analysis.py (30 min TTL)
    regime_info: dict[str, Any] = {}
    try:
        from backend.analysis import get_market_regime
        r = get_market_regime()
        regime_info = {
            "regime": r.get("regime", "?"),
            "buy_blocked": r.get("buy_blocked", False),
            "buy_confidence_adj": r.get("buy_confidence_adj", 0.0),
            "reason": (r.get("reason") or "")[:120],
        }
    except Exception:
        pass

    return {
        "uptime": _uptime_str(uptime_sec),
        "uptime_seconds": int(uptime_sec),
        "trading_mode": trading_mode,
        "regime": regime_info,
        "collector": collector,
        "database": db_info,
        "ai": ai_info,
        "binance": binance_info,
        "telegram": telegram_info,
        "last_log": last_log_info,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/public-url")
def get_public_url(db: Session = Depends(get_db)):
    """Zwraca aktywny publiczny adres panelu i backendu."""
    info = get_public_url_info()
    return {"success": True, "data": info}


@router.get("/events")
def get_recent_events(
    limit: int = Query(100, ge=1, le=500),
    level: str = Query("", description="Filtr: INFO|WARNING|ERROR|DEBUG (pusty = wszystkie)"),
    module: str = Query("", description="Filtr po nazwie modułu"),
    db: Session = Depends(get_db),
):
    """Ostatnie eventy systemowe z tabeli system_logs."""
    q = db.query(SystemLog)
    if level.strip():
        q = q.filter(SystemLog.level == level.upper().strip())
    if module.strip():
        q = q.filter(SystemLog.module.ilike(f"%{module.strip()}%"))
    logs = q.order_by(SystemLog.id.desc()).limit(limit).all()
    return {
        "total": len(logs),
        "events": [
            {
                "id": lg.id,
                "level": lg.level,
                "module": lg.module,
                "message": (lg.message or "")[:500],
                "exception": (lg.exception or "")[:300] if lg.exception else None,
                "timestamp": lg.timestamp.isoformat() if lg.timestamp else None,
            }
            for lg in reversed(logs)
        ],
    }


# ─────────────────────────────────────────────
# SSE — live log stream
# ─────────────────────────────────────────────

async def _sse_log_generator(
    level_filter: str,
    module_filter: str,
) -> AsyncGenerator[str, None]:
    """
    Generuje SSE stream z tabeli system_logs.
    Polluje bazę co 2s po nowych rekordach (id > last_id).
    """
    last_id: int = 0

    # Inicjalizuj last_id od TERAZ (bez backlogu historii)
    db = SessionLocal()
    try:
        newest = db.query(SystemLog).order_by(SystemLog.id.desc()).first()
        if newest:
            last_id = newest.id
    finally:
        db.close()

    # Wyślij ping żeby SSE się podłączyło
    yield f"data: {json.dumps({'type': 'connected', 'message': 'Stream logów połączony'})}\n\n"

    while True:
        db = SessionLocal()
        try:
            q = db.query(SystemLog).filter(SystemLog.id > last_id)
            if level_filter:
                q = q.filter(SystemLog.level == level_filter.upper())
            if module_filter:
                q = q.filter(SystemLog.module.ilike(f"%{module_filter}%"))
            logs = q.order_by(SystemLog.id.asc()).limit(50).all()

            for lg in logs:
                last_id = lg.id
                event_data = {
                    "type": "log",
                    "id": lg.id,
                    "level": lg.level,
                    "module": lg.module,
                    "message": (lg.message or "")[:500],
                    "exception": (lg.exception or "")[:200] if lg.exception else None,
                    "timestamp": lg.timestamp.isoformat() if lg.timestamp else None,
                }
                yield f"data: {json.dumps(event_data)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)[:200]})}\n\n"
        finally:
            db.close()

        await asyncio.sleep(2)


@router.get("/logs/stream")
async def stream_logs(
    level: str = Query("", description="Filtr poziomu: INFO|WARNING|ERROR"),
    module: str = Query("", description="Filtr modułu"),
):
    """
    SSE stream logów systemowych — odświeża co 2s.
    Content-Type: text/event-stream

    Użycie w JS:
      const es = new EventSource('/api/system/logs/stream');
      es.onmessage = (e) => { const log = JSON.parse(e.data); ... };
    """
    return StreamingResponse(
        _sse_log_generator(level.strip(), module.strip()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # wyłącza buforowanie w Nginx
        },
    )
