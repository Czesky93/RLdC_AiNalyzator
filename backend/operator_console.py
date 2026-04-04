"""
Operator Console — zagregowany widok stanu systemu dla operatora.

Konsumuje istniejące warstwy:
  - governance (incidents, operator queue, pipeline status)
  - policy_layer (active policy actions, summary)
  - reevaluation_worker (worker status)
  - system_logger / SystemLog (ostatnie notyfikacje, zablokowane operacje)
  - post_promotion_monitoring / post_rollback_monitoring (aktywne monitoringi)

NIE tworzy nowych źródeł prawdy.
NIE wykonuje akcji technicznych.
Warstwa czysto prezentacyjna / read-only.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import (
    ConfigPromotion,
    ConfigRollback,
    DecisionTrace,
    Incident,
    PolicyAction,
    PromotionMonitoring,
    RollbackMonitoring,
    SystemLog,
    utc_now_naive
)
from backend.governance import (
    get_operator_queue,
    get_pipeline_status,
    list_incidents,
)
from backend.policy_layer import (
    list_active_policy_actions,
    policy_actions_summary,
)
from backend.reevaluation_worker import get_worker_status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sekcje składowe konsoli
# ---------------------------------------------------------------------------

def _load_json_blob(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _section_active_incidents(db: Session, limit: int = 50) -> Dict[str, Any]:
    """Aktywne incydenty (niefinalne)."""
    active = list_incidents(db)
    non_resolved = [i for i in active if i.get("status") != "resolved"]
    return {
        "total_active": len(non_resolved),
        "items": non_resolved[:limit],
        "by_status": _count_by(non_resolved, "status"),
        "by_priority": _count_by(non_resolved, "priority"),
    }


def _section_active_policy_actions(db: Session, limit: int = 50) -> Dict[str, Any]:
    """Otwarte policy actions wymagające uwagi."""
    actions = list_active_policy_actions(db)
    review_required = [a for a in actions if a.get("requires_human_review")]
    return {
        "total_open": len(actions),
        "requiring_review": len(review_required),
        "items": actions[:limit],
        "summary": policy_actions_summary(db),
    }


def _section_pipeline_status(db: Session) -> Dict[str, Any]:
    """Zagregowany stan blokad pipeline."""
    status = get_pipeline_status(db)
    frozen = not all([
        status.get("promotion_allowed", True),
        status.get("experiment_allowed", True),
        status.get("recommendation_allowed", True),
    ])
    return {
        **status,
        "any_freeze_active": frozen,
    }


def _section_operator_queue(db: Session, limit: int = 30) -> Dict[str, Any]:
    """Priorytetowa kolejka operatora."""
    queue = get_operator_queue(db)
    critical_count = sum(1 for q in queue if q.get("priority") == "critical")
    sla_breached = sum(1 for q in queue if q.get("sla_breached"))
    return {
        "queue_size": len(queue),
        "critical_count": critical_count,
        "sla_breached_count": sla_breached,
        "items": queue[:limit],
    }


def _section_worker_status() -> Dict[str, Any]:
    """Stan reevaluation workera."""
    return get_worker_status()


def _section_recent_notifications(db: Session, limit: int = 30) -> Dict[str, Any]:
    """Ostatnie powiadomienia (z system_logs modułu notification_hooks)."""
    rows = (
        db.query(SystemLog)
        .filter(SystemLog.module == "notification_hooks")
        .order_by(SystemLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": int(r.id),
            "level": r.level,
            "message": r.message,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]
    return {
        "count": len(items),
        "items": items,
    }


def _section_recent_blocked_operations(db: Session, limit: int = 20) -> Dict[str, Any]:
    """Ostatnie zablokowane operacje pipeline (z system_logs)."""
    rows = (
        db.query(SystemLog)
        .filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like("%pipeline_blocked%"),
        )
        .order_by(SystemLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": int(r.id),
            "level": r.level,
            "message": r.message,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]
    return {
        "count": len(items),
        "items": items,
    }


def _section_monitoring_summary(db: Session) -> Dict[str, Any]:
    """Podsumowanie aktywnych monitoringów post-promotion i post-rollback."""
    # Aktywne promotion monitoringi
    promo_active = (
        db.query(PromotionMonitoring)
        .filter(PromotionMonitoring.status.in_(["pending", "collecting", "watch", "warning"]))
        .all()
    )
    promo_items = [
        {
            "id": int(r.id),
            "promotion_id": int(r.promotion_id),
            "status": r.status,
            "rollback_recommended": bool(r.rollback_recommended),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "last_evaluated_at": r.last_evaluated_at.isoformat() if r.last_evaluated_at else None,
        }
        for r in promo_active
    ]

    # Aktywne rollback monitoringi
    rb_active = (
        db.query(RollbackMonitoring)
        .filter(RollbackMonitoring.status.in_(["pending", "collecting", "watch", "warning"]))
        .all()
    )
    rb_items = [
        {
            "id": int(r.id),
            "rollback_id": int(r.rollback_id),
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "last_evaluated_at": r.last_evaluated_at.isoformat() if r.last_evaluated_at else None,
        }
        for r in rb_active
    ]

    return {
        "promotion_monitoring": {
            "active_count": len(promo_items),
            "items": promo_items,
            "by_status": _count_by(promo_items, "status"),
        },
        "rollback_monitoring": {
            "active_count": len(rb_items),
            "items": rb_items,
            "by_status": _count_by(rb_items, "status"),
        },
    }


def _section_recent_system_events(db: Session, limit: int = 30) -> Dict[str, Any]:
    """Ostatnie zdarzenia systemowe (WARNING+) z system_logs."""
    rows = (
        db.query(SystemLog)
        .filter(SystemLog.level.in_(["WARNING", "ERROR", "CRITICAL"]))
        .order_by(SystemLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": int(r.id),
            "level": r.level,
            "module": r.module,
            "message": r.message,
            "exception": r.exception,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in rows
    ]
    return {
        "count": len(items),
        "items": items,
    }


def _section_decision_intelligence(db: Session, limit: int = 30) -> Dict[str, Any]:
    """Najnowsze decyzje tradingowe z planem, rewizją i economics."""
    rows = (
        db.query(DecisionTrace)
        .order_by(DecisionTrace.timestamp.desc())
        .limit(limit)
        .all()
    )

    items: List[Dict[str, Any]] = []
    blocked_count = 0
    revision_required_count = 0
    negative_net_count = 0

    for row in rows:
        plan = _load_json_blob(row.plan_json)
        snapshot = _load_json_blob(row.snapshot_json)
        risk_gate = _load_json_blob(row.risk_gate_result)
        cost_gate = _load_json_blob(row.cost_gate_result)
        execution_gate = _load_json_blob(row.execution_gate_result)
        payload = _load_json_blob(row.payload)

        expected_net = plan.get("expected_net_profit")
        requires_revision = bool(plan.get("requires_revision"))
        action = plan.get("action")
        plan_status = plan.get("plan_status")

        if str(row.action_type).lower() == "skip":
            blocked_count += 1
        if requires_revision:
            revision_required_count += 1
        try:
            if expected_net is not None and float(expected_net) < 0:
                negative_net_count += 1
        except Exception:
            pass

        items.append({
            "id": int(row.id),
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "symbol": row.symbol,
            "mode": row.mode,
            "action_type": row.action_type,
            "reason_code": row.reason_code,
            "strategy_name": row.strategy_name,
            "signal_summary": row.signal_summary,
            "position_id": row.position_id,
            "order_id": row.order_id,
            "plan_status": plan_status,
            "action": action,
            "break_even_price": plan.get("break_even_price"),
            "expected_net_profit": expected_net,
            "expected_net_profit_pct": plan.get("expected_net_profit_pct"),
            "take_profit_price": plan.get("take_profit_price"),
            "stop_loss_price": plan.get("stop_loss_price"),
            "confidence_score": plan.get("confidence_score"),
            "risk_score": plan.get("risk_score"),
            "trade_quality_score": plan.get("trade_quality_score"),
            "cost_efficiency_score": plan.get("cost_efficiency_score"),
            "requires_revision": requires_revision,
            "invalidation_reason": plan.get("invalidation_reason"),
            "market_price": ((snapshot.get("market") or {}).get("price")),
            "market_stale": ((snapshot.get("source_freshness") or {}).get("is_stale")),
            "risk_allowed": risk_gate.get("allowed"),
            "cost_eligible": cost_gate.get("eligible"),
            "execution_allowed": execution_gate.get("allowed"),
            "payload": payload,
        })

    return {
        "count": len(items),
        "blocked_count": blocked_count,
        "revision_required_count": revision_required_count,
        "negative_expected_net_count": negative_net_count,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _count_by(items: List[Dict], key: str) -> Dict[str, int]:
    """Zlicz elementy wg klucza."""
    counts: Dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Główny bundle konsoli
# ---------------------------------------------------------------------------

def get_operator_console(db: Session) -> Dict[str, Any]:
    """
    Pełny zagregowany widok konsoli operatora.
    Jeden endpoint — pełny obraz systemu.
    """
    console: Dict[str, Any] = {
        "generated_at": utc_now_naive().isoformat(),
        "sections": {},
    }

    section_builders = {
        "incidents": lambda: _section_active_incidents(db),
        "policy_actions": lambda: _section_active_policy_actions(db),
        "pipeline_status": lambda: _section_pipeline_status(db),
        "operator_queue": lambda: _section_operator_queue(db),
        "worker_status": lambda: _section_worker_status(),
        "monitoring_summary": lambda: _section_monitoring_summary(db),
        "decision_intelligence": lambda: _section_decision_intelligence(db),
        "recent_notifications": lambda: _section_recent_notifications(db),
        "recent_blocked_operations": lambda: _section_recent_blocked_operations(db),
        "recent_system_events": lambda: _section_recent_system_events(db),
    }

    for name, builder in section_builders.items():
        try:
            console["sections"][name] = builder()
        except Exception as exc:
            logger.error("Operator console: błąd sekcji '%s': %s", name, exc)
            console["sections"][name] = {"error": str(exc)}

    return console


def get_console_section(db: Session, section: str) -> Dict[str, Any]:
    """
    Pobierz pojedynczą sekcję konsoli.
    Przydatne gdy frontend odświeża jedną kartę.
    """
    section_builders = {
        "incidents": lambda: _section_active_incidents(db),
        "policy_actions": lambda: _section_active_policy_actions(db),
        "pipeline_status": lambda: _section_pipeline_status(db),
        "operator_queue": lambda: _section_operator_queue(db),
        "worker_status": lambda: _section_worker_status(),
        "monitoring_summary": lambda: _section_monitoring_summary(db),
        "decision_intelligence": lambda: _section_decision_intelligence(db),
        "recent_notifications": lambda: _section_recent_notifications(db),
        "recent_blocked_operations": lambda: _section_recent_blocked_operations(db),
        "recent_system_events": lambda: _section_recent_system_events(db),
    }

    builder = section_builders.get(section)
    if builder is None:
        raise ValueError(
            f"Nieznana sekcja: '{section}'. "
            f"Dostępne: {', '.join(sorted(section_builders.keys()))}"
        )

    return builder()
