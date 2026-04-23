"""
System diagnostics router — /api/system/...
Endpointy diagnostyczne dla execution, reconciliation, universe, AI, DB health.
"""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import (
    PendingOrder,
    Position,
    ReconciliationRun,
    SessionLocal,
    get_db,
    utc_now_naive,
)

router = APIRouter()

ACTIVE_PENDING_STATUSES = [
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
]


def _canonical_open_positions_count(db: Session, mode: str) -> int:
    """Zwraca kanoniczną liczbę otwartych pozycji.

    LIVE: źródło prawdy = Binance snapshot przez router positions.
    DEMO: źródło prawdy = lokalna tabela Position.
    """
    mode_norm = (mode or "demo").lower()
    if mode_norm == "live":
        try:
            from backend.routers.positions import _get_live_spot_positions

            live_positions = _get_live_spot_positions(db)
            return sum(
                1
                for p in (live_positions or [])
                if str(p.get("source") or "") == "binance_spot"
                and float(p.get("quantity") or 0.0) > 0.0
            )
        except Exception:
            # Fallback awaryjny: DB (bez pyłu i zamkniętych)
            return (
                db.query(Position)
                .filter(
                    Position.mode == "live",
                    Position.exit_reason_code.is_(None),
                    Position.quantity > 0,
                )
                .count()
            )

    return (
        db.query(Position)
        .filter(
            Position.mode == mode_norm,
            Position.exit_reason_code.is_(None),
            Position.quantity > 0,
        )
        .count()
    )


# ---------------------------------------------------------------------------
# /api/system/execution-status
# ---------------------------------------------------------------------------
@router.get("/execution-status")
def get_execution_status(db: Session = Depends(get_db)):
    """Status execution layer — flagi, tryb, pending counts."""
    try:
        from backend.runtime_settings import build_runtime_state
        from backend.ai_orchestrator import get_ai_orchestrator_status

        rt = build_runtime_state(db)
        ai = get_ai_orchestrator_status(force=False)
        trading_mode = str(rt.get("trading_mode") or "demo").lower()
        allow_live = bool(rt.get("allow_live_trading"))
        execution_enabled = bool(rt.get("execution_enabled", True))

        live_mode = trading_mode == "live"
        live_execution_ok = live_mode and allow_live and execution_enabled

        pending_active = (
            db.query(PendingOrder)
            .filter(PendingOrder.status.in_(ACTIVE_PENDING_STATUSES))
            .count()
        )
        pending_confirmed = (
            db.query(PendingOrder)
            .filter(PendingOrder.status == "PENDING_CONFIRMED")
            .count()
        )
        pending_live = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "live",
                PendingOrder.status.in_(ACTIVE_PENDING_STATUSES),
            )
            .count()
        )
        pending_demo = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "demo",
                PendingOrder.status.in_(ACTIVE_PENDING_STATUSES),
            )
            .count()
        )
        open_positions = _canonical_open_positions_count(db, trading_mode)

        blockers = []
        if not allow_live:
            blockers.append("ALLOW_LIVE_TRADING=false")
        if not execution_enabled:
            blockers.append("EXECUTION_ENABLED=false")
        if trading_mode != "live":
            blockers.append(f"TRADING_MODE={trading_mode} (not live)")

        return {
            "success": True,
            "data": {
                "trading_mode": trading_mode,
                "allow_live_trading": allow_live,
                "execution_enabled": execution_enabled,
                "live_execution_ok": live_execution_ok,
                "pending_active_total": pending_active,
                "pending_confirmed_awaiting": pending_confirmed,
                "pending_live": pending_live,
                "pending_demo": pending_demo,
                "open_positions": open_positions,
                "execution_blockers": blockers,
                "local_only_mode": bool(ai.get("local_only_mode")),
                "external_ai_limited": any(
                    bool(item.get("fallback_active"))
                    for item in (ai.get("ai_budget", {}).get("providers") or {}).values()
                ),
                "require_manual_confirmation": bool(
                    rt.get("require_manual_confirmation")
                ),
                "enable_auto_execute": bool(rt.get("enable_auto_execute", True)),
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/reconciliation-status
# ---------------------------------------------------------------------------
@router.get("/reconciliation-status")
def get_reconciliation_status(db: Session = Depends(get_db)):
    """Status reconcylacji DB ↔ Binance."""
    try:
        from backend.portfolio_reconcile import get_reconcile_status

        status = get_reconcile_status(db)
        return {"success": True, "data": status}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.post("/reconcile")
def trigger_reconcile(
    mode: str = "live",
    trigger: str = "manual",
    force: bool = False,
    db: Session = Depends(get_db),
):
    """Ręczne uruchomienie reconcylacji DB ↔ Binance."""
    try:
        from backend.portfolio_reconcile import reconcile_with_binance

        result = reconcile_with_binance(
            db, mode=mode, trigger=trigger, notify_telegram=True, force=force
        )
        return {"success": True, "data": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/universe-status
# ---------------------------------------------------------------------------
@router.get("/universe-status")
def get_universe_status(db: Session = Depends(get_db)):
    """Status symbol universe (watchlista, skaner, tryb quote)."""
    try:
        from backend.runtime_settings import build_runtime_state

        rt = build_runtime_state(db)
        watchlist = rt.get("watchlist") or []
        quote_mode = rt.get("config_sections", {}).get("trading", {}).get(
            "quote_currency_mode"
        ) or os.getenv("QUOTE_CURRENCY_MODE", "USDC")

        universe_info: dict = {
            "watchlist_count": len(watchlist),
            "watchlist_symbols": watchlist[:20],
            "quote_mode": quote_mode,
            "trading_mode": rt.get("trading_mode"),
        }

        # Jeśli symbol_universe.py istnieje
        try:
            from backend.symbol_universe import (
                get_symbol_universe_stats,
            )  # type: ignore

            stats = get_symbol_universe_stats()
            universe_info.update(stats)
        except ImportError:
            universe_info["symbol_universe_module"] = "not_loaded"

        # Kolektor live stats jeśli dostępne
        try:
            from backend.market_scanner import (
                get_scanner_universe_stats,
            )  # type: ignore

            scanner_stats = get_scanner_universe_stats(db)
            universe_info["scanner"] = scanner_stats
        except (ImportError, Exception):
            pass

        return {"success": True, "data": universe_info}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/universe-stats")
def get_universe_stats(db: Session = Depends(get_db)):
    try:
        from backend.market_scanner import get_scanner_universe_stats

        return {"success": True, "data": get_scanner_universe_stats(db)}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@router.get("/ai-budget")
def get_ai_budget():
    try:
        from backend.ai_orchestrator import get_ai_budget_status

        return {"success": True, "data": get_ai_budget_status()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/ai-consensus-status
# ---------------------------------------------------------------------------
@router.get("/ai-consensus-status")
def get_ai_consensus_status():
    """Status multi-AI consensus layer."""
    try:
        from backend.ai_orchestrator import AIOrchestrator

        orch = AIOrchestrator()
        status = orch.get_provider_status()
        return {"success": True, "data": status}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/telegram-status
# ---------------------------------------------------------------------------
@router.get("/telegram-status")
def get_telegram_status(db: Session = Depends(get_db)):
    """Status bota Telegram — konfiguracja, ostatnie wiadomości."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        from backend.database import TelegramMessage

        last_msg = (
            db.query(TelegramMessage).order_by(TelegramMessage.timestamp.desc()).first()
        )
        return {
            "success": True,
            "data": {
                "bot_configured": bool(token),
                "chat_configured": bool(chat_id),
                "last_message_at": str(last_msg.timestamp) if last_msg else None,
                "last_message_type": last_msg.message_type if last_msg else None,
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/db-health
# ---------------------------------------------------------------------------
@router.get("/db-health")
def get_db_health(db: Session = Depends(get_db)):
    """Zdrowie bazy danych — liczby rekordów w kluczowych tabelach."""
    try:
        from backend.database import Alert, Incident, Order, Signal, SystemLog

        counts = {
            "signals": db.query(Signal).count(),
            "orders": db.query(Order).count(),
            "positions": db.query(Position)
            .filter(Position.exit_reason_code.is_(None), Position.quantity > 0)
            .count(),
            "pending_active": db.query(PendingOrder)
            .filter(PendingOrder.status.in_(ACTIVE_PENDING_STATUSES))
            .count(),
            "incidents_open": db.query(Incident)
            .filter(Incident.status != "resolved")
            .count(),
            "alerts_unsent": db.query(Alert).filter(Alert.is_sent.is_(False)).count(),
            "system_logs": db.query(SystemLog).count(),
            "reconciliation_runs": db.query(ReconciliationRun).count(),
        }
        return {"success": True, "data": counts}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# /api/system/full-status — agregat wszystkich
# ---------------------------------------------------------------------------
@router.get("/full-status")
def get_full_status(db: Session = Depends(get_db)):
    """Pełny status systemu — agregat wszystkich diagnostyk."""
    try:
        from backend.runtime_settings import build_runtime_state

        rt = build_runtime_state(db)
        from backend.portfolio_reconcile import get_reconcile_status

        reconcile = get_reconcile_status(db)
        from backend.database import Alert, Incident, Signal

        trading_mode = str(rt.get("trading_mode") or "demo").lower()
        allow_live = bool(rt.get("allow_live_trading"))
        execution_enabled = bool(rt.get("execution_enabled", True))

        pending_active = (
            db.query(PendingOrder)
            .filter(PendingOrder.status.in_(ACTIVE_PENDING_STATUSES))
            .count()
        )
        open_positions = _canonical_open_positions_count(db, trading_mode)
        incidents_open = (
            db.query(Incident).filter(Incident.status != "resolved").count()
        )

        return {
            "success": True,
            "data": {
                "trading_mode": trading_mode,
                "allow_live_trading": allow_live,
                "execution_enabled": execution_enabled,
                "live_execution_ok": trading_mode == "live"
                and allow_live
                and execution_enabled,
                "pending_active": pending_active,
                "open_positions": open_positions,
                "incidents_open": incidents_open,
                "last_reconcile": reconcile.get("last_live_reconcile"),
                "reconcile_running": reconcile.get("currently_running"),
                "manual_trades_synced": reconcile.get("total_manual_trades_synced"),
            },
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
