"""
Scheduled reevaluation worker — cykliczny mózg systemu.

Okresowo (co X minut) odświeża stan governance i pipeline:
  1. Eskalacja przeterminowanych incydentów (SLA breach)
  2. Re-ewaluacja aktywnych monitoringów post-promotion
  3. Re-ewaluacja aktywnych monitoringów post-rollback
  4. Odświeżenie operator queue snapshot
  5. Powiadomienia przy zmianach statusu

Worker NIE:
  - nie zmienia configu
  - nie wykonuje rollback ani promotion
  - nie liczy ekonomiki
  - nie podejmuje automatycznych decyzji

Korzysta wyłącznie z istniejących warstw.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.database import (
    ConfigPromotion,
    ConfigRollback,
    SessionLocal,
    utc_now_naive
)
from backend.governance import escalate_overdue_incidents, get_operator_queue, get_pipeline_status
from backend.notification_hooks import dispatch_notification
from backend.post_promotion_monitoring import evaluate_monitoring
from backend.post_rollback_monitoring import evaluate_post_rollback_monitoring

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stałe
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL_SECONDS = int(os.getenv("WORKER_INTERVAL_SECONDS", "300"))
WORKER_ENABLED = os.getenv("WORKER_ENABLED", "true").lower() in ("1", "true", "yes")

# Stan poprzedniego cyklu dla delta-based alertów kolejki operatora
# -1 oznacza "pierwsza iteracja" — alert nie zostanie wysłany dopóki nie wzrośnie
_QUEUE_LAST_CRITICAL_COUNT: int = -1
_QUEUE_LAST_SLA_BREACHED: int = -1


# ---------------------------------------------------------------------------
# Pojedynczy cykl workera
# ---------------------------------------------------------------------------

def run_worker_cycle() -> Dict[str, Any]:
    """
    Jeden pełny cykl reewaluacji. Może być wywołany:
      - automatycznie przez scheduler,
      - ręcznie z endpointu debug/test.

    Zwraca podsumowanie cyklu.
    """
    cycle_start = utc_now_naive()
    summary: Dict[str, Any] = {
        "cycle_start": cycle_start.isoformat(),
        "steps": {},
        "errors": [],
    }

    db = SessionLocal()
    try:
        # --- 1. Eskalacja przeterminowanych incydentów ---
        summary["steps"]["escalate_overdue"] = _step_escalate_overdue(db)

        # --- 2. Re-ewaluacja aktywnych monitoringów post-promotion ---
        summary["steps"]["reevaluate_promotion_monitoring"] = _step_reevaluate_promotion_monitoring(db)

        # --- 3. Re-ewaluacja aktywnych monitoringów post-rollback ---
        summary["steps"]["reevaluate_rollback_monitoring"] = _step_reevaluate_rollback_monitoring(db)

        # --- 4. Odświeżenie operator queue snapshot ---
        summary["steps"]["operator_queue"] = _step_refresh_operator_queue(db)

        # --- 5. Pipeline status ---
        summary["steps"]["pipeline_status"] = _step_refresh_pipeline_status(db)

    except Exception as exc:
        logger.error("Krytyczny błąd cyklu workera: %s", exc)
        summary["errors"].append(str(exc))
    finally:
        db.close()

    cycle_end = utc_now_naive()
    summary["cycle_end"] = cycle_end.isoformat()
    summary["duration_seconds"] = round((cycle_end - cycle_start).total_seconds(), 2)

    # Log podsumowanie cyklu
    _log_cycle_summary(summary)

    return summary


# ---------------------------------------------------------------------------
# Kroki cyklu
# ---------------------------------------------------------------------------

def _step_escalate_overdue(db) -> Dict[str, Any]:
    """Krok 1: eskalacja przeterminowanych incydentów."""
    try:
        escalated = escalate_overdue_incidents(db)
        return {
            "status": "ok",
            "escalated_count": len(escalated),
            "escalated_ids": [e.get("id") for e in escalated],
        }
    except Exception as exc:
        logger.error("Błąd eskalacji SLA: %s", exc)
        return {"status": "error", "error": str(exc)}


def _step_reevaluate_promotion_monitoring(db) -> Dict[str, Any]:
    """Krok 2: re-ewaluacja aktywnych monitoringów post-promotion."""
    try:
        # Znajdź promocje z aktywnym monitoringiem (status applied, monitoring pending/collecting)
        active_promotions = (
            db.query(ConfigPromotion)
            .filter(
                ConfigPromotion.status == "applied",
                ConfigPromotion.post_promotion_monitoring_status.in_(["pending", "collecting"]),
            )
            .all()
        )

        results = []
        for promo in active_promotions:
            try:
                verdict = evaluate_monitoring(db, int(promo.id), notes="worker: cykliczna re-ewaluacja")
                results.append({
                    "promotion_id": int(promo.id),
                    "verdict": verdict.get("status", "?"),
                    "rollback_recommended": verdict.get("rollback_recommended", False),
                })
            except Exception as exc:
                logger.warning("Błąd re-ewaluacji monitoringu promotion #%s: %s", promo.id, exc)
                results.append({
                    "promotion_id": int(promo.id),
                    "error": str(exc),
                })

        return {
            "status": "ok",
            "active_count": len(active_promotions),
            "evaluated": results,
        }
    except Exception as exc:
        logger.error("Błąd re-ewaluacji promotion monitoring: %s", exc)
        return {"status": "error", "error": str(exc)}


def _step_reevaluate_rollback_monitoring(db) -> Dict[str, Any]:
    """Krok 3: re-ewaluacja aktywnych monitoringów post-rollback."""
    try:
        active_rollbacks = (
            db.query(ConfigRollback)
            .filter(
                ConfigRollback.execution_status == "executed",  # BUG FIX: było "applied"
                ConfigRollback.post_rollback_monitoring_status.in_(["pending", "collecting"]),
            )
            .all()
        )

        results = []
        for rb in active_rollbacks:
            try:
                verdict = evaluate_post_rollback_monitoring(
                    db, int(rb.id), notes="worker: cykliczna re-ewaluacja"
                )
                results.append({
                    "rollback_id": int(rb.id),
                    "verdict": verdict.get("status", "?"),
                })
            except Exception as exc:
                logger.warning("Błąd re-ewaluacji monitoringu rollback #%s: %s", rb.id, exc)
                results.append({
                    "rollback_id": int(rb.id),
                    "error": str(exc),
                })

        return {
            "status": "ok",
            "active_count": len(active_rollbacks),
            "evaluated": results,
        }
    except Exception as exc:
        logger.error("Błąd re-ewaluacji rollback monitoring: %s", exc)
        return {"status": "error", "error": str(exc)}


def _step_refresh_operator_queue(db) -> Dict[str, Any]:
    """Krok 4: odświeżenie operator queue i raport."""
    global _QUEUE_LAST_CRITICAL_COUNT, _QUEUE_LAST_SLA_BREACHED
    try:
        queue = get_operator_queue(db)
        critical_count = sum(1 for q in queue if q.get("priority") == "critical")
        sla_breached = sum(1 for q in queue if q.get("sla_breached"))

        result = {
            "status": "ok",
            "queue_size": len(queue),
            "critical_count": critical_count,
            "sla_breached_count": sla_breached,
        }

        # Powiadom TYLKO gdy sytuacja się POGORSZYŁA (delta > 0) względem poprzedniego cyklu.
        # Nie spamuj co 5 minut jeśli stan jest stały.
        state_worsened = (
            critical_count > _QUEUE_LAST_CRITICAL_COUNT
            or sla_breached > _QUEUE_LAST_SLA_BREACHED
        )
        if (critical_count > 0 or sla_breached > 0) and state_worsened:
            try:
                dispatch_notification(
                    "worker_queue_alert",
                    f"⚙️ WORKER: Operator queue — {len(queue)} elementów, "
                    f"critical: {critical_count}, SLA breached: {sla_breached}",
                    priority="high",
                )
            except Exception as exc:
                logger.error("Błąd wysyłki powiadomienia queue: %s", exc)

        # Aktualizuj zapamiętany stan (zawsze, nie tylko gdy gorszy)
        _QUEUE_LAST_CRITICAL_COUNT = critical_count
        _QUEUE_LAST_SLA_BREACHED = sla_breached

        return result
    except Exception as exc:
        logger.error("Błąd odświeżania operator queue: %s", exc)
        return {"status": "error", "error": str(exc)}


def _step_refresh_pipeline_status(db) -> Dict[str, Any]:
    """Krok 5: odświeżenie zagregowanego stanu pipeline."""
    try:
        status = get_pipeline_status(db)
        return {
            "status": "ok",
            **status,
        }
    except Exception as exc:
        logger.error("Błąd odświeżania pipeline status: %s", exc)
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Logowanie cyklu
# ---------------------------------------------------------------------------

def _log_cycle_summary(summary: Dict[str, Any]) -> None:
    """Zapisz podsumowanie cyklu do system log."""
    errors = summary.get("errors", [])
    duration = summary.get("duration_seconds", 0)

    steps = summary.get("steps", {})
    escalated = steps.get("escalate_overdue", {}).get("escalated_count", 0)
    promo_active = steps.get("reevaluate_promotion_monitoring", {}).get("active_count", 0)
    rb_active = steps.get("reevaluate_rollback_monitoring", {}).get("active_count", 0)
    queue_size = steps.get("operator_queue", {}).get("queue_size", 0)

    msg = (
        f"Worker cycle: {duration}s, "
        f"escalated={escalated}, promo_monitoring={promo_active}, "
        f"rollback_monitoring={rb_active}, queue={queue_size}"
    )

    if errors:
        msg += f", errors={len(errors)}"
        logger.warning("Worker cycle zakończony z błędami: %s", msg)
    else:
        logger.info("Worker cycle: %s", msg)

    try:
        from backend.system_logger import log_to_db
        log_to_db(
            level="WARNING" if errors else "INFO",
            module="reevaluation_worker",
            message=msg,
        )
    except Exception as exc:
        logger.error("Błąd logowania cyklu do DB: %s", exc)


# ---------------------------------------------------------------------------
# Background scheduler (daemon thread)
# ---------------------------------------------------------------------------

_worker_thread: threading.Thread | None = None
_worker_stop_event = threading.Event()


def start_worker(interval_seconds: int | None = None) -> bool:
    """
    Uruchom worker jako daemon thread.
    Zwraca True jeśli uruchomiono, False jeśli już działa lub wyłączony.
    """
    global _worker_thread

    if not WORKER_ENABLED:
        logger.info("Worker wyłączony (WORKER_ENABLED=false)")
        return False

    if _worker_thread is not None and _worker_thread.is_alive():
        logger.info("Worker już działa")
        return False

    interval = interval_seconds or DEFAULT_INTERVAL_SECONDS
    _worker_stop_event.clear()

    def _loop():
        logger.info("Worker started: interval=%ds", interval)
        while not _worker_stop_event.is_set():
            try:
                run_worker_cycle()
            except Exception as exc:
                logger.error("Worker cycle exception: %s", exc)
            _worker_stop_event.wait(timeout=interval)
        logger.info("Worker stopped")

    _worker_thread = threading.Thread(target=_loop, name="reevaluation-worker", daemon=True)
    _worker_thread.start()
    return True


def stop_worker() -> bool:
    """Zatrzymaj worker thread. Zwraca True jeśli zatrzymano."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        return False
    _worker_stop_event.set()
    _worker_thread.join(timeout=10)
    _worker_thread = None
    return True


def get_worker_status() -> Dict[str, Any]:
    """Aktualny stan workera."""
    return {
        "enabled": WORKER_ENABLED,
        "running": _worker_thread is not None and _worker_thread.is_alive(),
        "interval_seconds": DEFAULT_INTERVAL_SECONDS,
    }
