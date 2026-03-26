"""
Correlation / incident intelligence — powiązanie zdarzeń w łańcuchy przyczynowe.

Warstwa read-only agregująca istniejące rekordy:
  - monitoring verdict → policy action → incident → blocked op → notification
  - promotion chain / rollback chain / incident timeline
  - "dlaczego to jest zablokowane?" (why-blocked bundle)

NIE tworzy nowych źródeł prawdy.
NIE wykonuje akcji technicznych.
Konsumuje wyłącznie istniejące tabele.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import (
    ConfigPromotion,
    ConfigRollback,
    Incident,
    PolicyAction,
    PromotionMonitoring,
    RollbackMonitoring,
    SystemLog,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stałe — mapowanie source_type → model / tabela
# ---------------------------------------------------------------------------

_SOURCE_TYPE_INFO = {
    "promotion_monitoring": {
        "label": "Monitoring post-promotion",
        "model": PromotionMonitoring,
        "parent_key": "promotion_id",
        "parent_model": ConfigPromotion,
    },
    "rollback_decision": {
        "label": "Decyzja o rollbacku",
        "model": ConfigRollback,
        "parent_key": "promotion_id",
        "parent_model": ConfigPromotion,
    },
    "rollback_monitoring": {
        "label": "Monitoring post-rollback",
        "model": RollbackMonitoring,
        "parent_key": "rollback_id",
        "parent_model": ConfigRollback,
    },
}


# ---------------------------------------------------------------------------
# Serializacja pomocnicza (wyciąg kluczowych pól z rekordów)
# ---------------------------------------------------------------------------

def _slim_policy_action(row: PolicyAction) -> Dict[str, Any]:
    return {
        "entity": "policy_action",
        "id": int(row.id),
        "policy_action": row.policy_action,
        "priority": row.priority,
        "source_type": row.source_type,
        "source_id": int(row.source_id),
        "status": row.status,
        "requires_human_review": bool(row.requires_human_review),
        "promotion_allowed": bool(row.promotion_allowed),
        "summary": row.summary,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def _slim_incident(row: Incident) -> Dict[str, Any]:
    return {
        "entity": "incident",
        "id": int(row.id),
        "policy_action_id": int(row.policy_action_id),
        "status": row.status,
        "priority": row.priority,
        "sla_deadline": row.sla_deadline.isoformat() if row.sla_deadline else None,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "escalated_at": row.escalated_at.isoformat() if row.escalated_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _slim_promotion(row: ConfigPromotion) -> Dict[str, Any]:
    return {
        "entity": "promotion",
        "id": int(row.id),
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "status": row.status,
        "post_promotion_monitoring_status": row.post_promotion_monitoring_status,
        "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _slim_rollback(row: ConfigRollback) -> Dict[str, Any]:
    return {
        "entity": "rollback",
        "id": int(row.id),
        "promotion_id": int(row.promotion_id),
        "decision_status": row.decision_status,
        "execution_status": row.execution_status,
        "urgency": row.urgency,
        "post_rollback_monitoring_status": row.post_rollback_monitoring_status,
        "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
        "executed_at": row.executed_at.isoformat() if row.executed_at else None,
    }


def _slim_promo_monitoring(row: PromotionMonitoring) -> Dict[str, Any]:
    return {
        "entity": "promotion_monitoring",
        "id": int(row.id),
        "promotion_id": int(row.promotion_id),
        "status": row.status,
        "rollback_recommended": bool(row.rollback_recommended),
        "confidence": float(row.confidence) if row.confidence else 0.0,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
    }


def _slim_rb_monitoring(row: RollbackMonitoring) -> Dict[str, Any]:
    return {
        "entity": "rollback_monitoring",
        "id": int(row.id),
        "rollback_id": int(row.rollback_id),
        "promotion_id": int(row.promotion_id),
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
    }


def _slim_log(row: SystemLog) -> Dict[str, Any]:
    return {
        "entity": "system_log",
        "id": int(row.id),
        "level": row.level,
        "module": row.module,
        "message": row.message,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


# ---------------------------------------------------------------------------
# I. Incident timeline
# ---------------------------------------------------------------------------

def get_incident_timeline(db: Session, incident_id: int) -> Dict[str, Any]:
    """
    Pełna oś czasu incydentu: od źródłowego monitoringu przez policy action
    do blokad i notyfikacji.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if incident is None:
        raise ValueError(f"Incydent nie znaleziono: {incident_id}")

    events: List[Dict[str, Any]] = []

    # --- Incident sam ---
    events.append({
        **_slim_incident(incident),
        "event_type": "incident_created",
        "event_at": incident.created_at.isoformat() if incident.created_at else None,
    })
    if incident.acknowledged_at:
        events.append({
            "entity": "incident_transition",
            "incident_id": int(incident.id),
            "event_type": "incident_acknowledged",
            "event_at": incident.acknowledged_at.isoformat(),
            "operator": incident.acknowledged_by,
        })
    if incident.escalated_at:
        events.append({
            "entity": "incident_transition",
            "incident_id": int(incident.id),
            "event_type": "incident_escalated",
            "event_at": incident.escalated_at.isoformat(),
        })
    if incident.resolved_at:
        events.append({
            "entity": "incident_transition",
            "incident_id": int(incident.id),
            "event_type": "incident_resolved",
            "event_at": incident.resolved_at.isoformat(),
            "operator": incident.resolved_by,
            "notes": incident.resolution_notes,
        })

    # --- Powiązana policy action ---
    pa = db.query(PolicyAction).filter(PolicyAction.id == incident.policy_action_id).first()
    if pa:
        events.append({
            **_slim_policy_action(pa),
            "event_type": "policy_action_created",
            "event_at": pa.created_at.isoformat() if pa.created_at else None,
        })
        # --- Upstream: źródłowy rekord monitoringu/decyzji ---
        _add_source_events(db, pa.source_type, pa.source_id, events)

    # --- Related system logs (notifications, blocked ops) ---
    _add_related_logs(db, incident_id=incident_id, policy_action_id=incident.policy_action_id, events=events)

    # Posortuj chronologicznie
    events.sort(key=lambda e: e.get("event_at") or "")

    return {
        "incident_id": int(incident.id),
        "timeline": events,
        "event_count": len(events),
    }


# ---------------------------------------------------------------------------
# II. Policy action chain
# ---------------------------------------------------------------------------

def get_policy_action_chain(db: Session, policy_action_id: int) -> Dict[str, Any]:
    """
    Łańcuch powiązany z policy action:
    źródło → policy action → incydent(y) → blokady → notyfikacje.
    """
    pa = db.query(PolicyAction).filter(PolicyAction.id == policy_action_id).first()
    if pa is None:
        raise ValueError(f"PolicyAction nie znaleziono: {policy_action_id}")

    events: List[Dict[str, Any]] = []

    # Policy action
    events.append({
        **_slim_policy_action(pa),
        "event_type": "policy_action_created",
        "event_at": pa.created_at.isoformat() if pa.created_at else None,
    })

    # Source (monitoring/decision)
    _add_source_events(db, pa.source_type, pa.source_id, events)

    # Incidents created from this PA
    incidents = db.query(Incident).filter(Incident.policy_action_id == policy_action_id).all()
    for inc in incidents:
        events.append({
            **_slim_incident(inc),
            "event_type": "incident_created",
            "event_at": inc.created_at.isoformat() if inc.created_at else None,
        })

    # Related logs
    _add_related_logs(db, policy_action_id=policy_action_id, events=events)

    events.sort(key=lambda e: e.get("event_at") or "")

    return {
        "policy_action_id": int(pa.id),
        "source_type": pa.source_type,
        "source_id": int(pa.source_id),
        "chain": events,
        "event_count": len(events),
    }


# ---------------------------------------------------------------------------
# III. Promotion chain (full lifecycle)
# ---------------------------------------------------------------------------

def get_promotion_chain(db: Session, promotion_id: int) -> Dict[str, Any]:
    """
    Pełny łańcuch lifecycle promocji:
    promotion → monitoring → policy actions → incidents → rollback decision →
    rollback execution → post-rollback monitoring → policy actions → incidents.
    """
    promo = db.query(ConfigPromotion).filter(ConfigPromotion.id == promotion_id).first()
    if promo is None:
        raise ValueError(f"ConfigPromotion nie znaleziono: {promotion_id}")

    events: List[Dict[str, Any]] = []

    # Promotion
    events.append({
        **_slim_promotion(promo),
        "event_type": "promotion_initiated",
        "event_at": promo.initiated_at.isoformat() if promo.initiated_at else None,
    })
    if promo.applied_at:
        events.append({
            "entity": "promotion",
            "id": int(promo.id),
            "event_type": "promotion_applied",
            "event_at": promo.applied_at.isoformat(),
        })

    # Promotion monitoring records
    pm_rows = db.query(PromotionMonitoring).filter(
        PromotionMonitoring.promotion_id == promotion_id
    ).order_by(PromotionMonitoring.started_at).all()
    for pm in pm_rows:
        events.append({
            **_slim_promo_monitoring(pm),
            "event_type": "promotion_monitoring_created",
            "event_at": pm.started_at.isoformat() if pm.started_at else None,
        })
        # Policy actions sourced from this monitoring
        _add_policy_actions_for_source(db, "promotion_monitoring", pm.id, events)

    # Rollback decisions / executions linked to this promotion
    rb_rows = db.query(ConfigRollback).filter(
        ConfigRollback.promotion_id == promotion_id
    ).order_by(ConfigRollback.initiated_at).all()
    for rb in rb_rows:
        events.append({
            **_slim_rollback(rb),
            "event_type": "rollback_initiated",
            "event_at": rb.initiated_at.isoformat() if rb.initiated_at else None,
        })
        if rb.executed_at:
            events.append({
                "entity": "rollback",
                "id": int(rb.id),
                "event_type": "rollback_executed",
                "event_at": rb.executed_at.isoformat(),
            })
        # Policy actions sourced from rollback decision
        _add_policy_actions_for_source(db, "rollback_decision", rb.id, events)

        # Post-rollback monitoring
        rbm_rows = db.query(RollbackMonitoring).filter(
            RollbackMonitoring.rollback_id == rb.id
        ).order_by(RollbackMonitoring.started_at).all()
        for rbm in rbm_rows:
            events.append({
                **_slim_rb_monitoring(rbm),
                "event_type": "rollback_monitoring_created",
                "event_at": rbm.started_at.isoformat() if rbm.started_at else None,
            })
            _add_policy_actions_for_source(db, "rollback_monitoring", rbm.id, events)

    events.sort(key=lambda e: e.get("event_at") or "")

    return {
        "promotion_id": int(promo.id),
        "chain": events,
        "event_count": len(events),
    }


# ---------------------------------------------------------------------------
# IV. "Why is this blocked?" bundle
# ---------------------------------------------------------------------------

def get_why_blocked(db: Session, operation: str) -> Dict[str, Any]:
    """
    Wyjaśnij dlaczego operacja jest zablokowana — pełny łańcuch
    od blocking policy actions w górę do źródłowych monitoringów.
    """
    valid_ops = {"promotion", "rollback", "experiment", "recommendation"}
    if operation not in valid_ops:
        raise ValueError(f"Nieznana operacja: {operation}. Dozwolone: {valid_ops}")

    # Znajdź blokujące policy actions
    open_actions = db.query(PolicyAction).filter(PolicyAction.status == "open").all()

    blocking = []
    for pa in open_actions:
        blocked = False
        if operation == "promotion" and not pa.promotion_allowed:
            blocked = True
        elif operation == "rollback" and not pa.rollback_allowed:
            blocked = True
        elif operation == "experiment" and not pa.experiments_allowed:
            blocked = True
        elif operation == "recommendation" and pa.freeze_recommendations:
            blocked = True

        if blocked:
            blocking.append(pa)

    if not blocking:
        return {
            "operation": operation,
            "blocked": False,
            "message": f"Operacja '{operation}' jest dozwolona — brak blokujących policy actions.",
            "blockers": [],
        }

    blockers = []
    for pa in blocking:
        chain = {
            "policy_action": _slim_policy_action(pa),
            "source": _get_source_summary(db, pa.source_type, pa.source_id),
            "incidents": [],
        }
        incidents = db.query(Incident).filter(
            Incident.policy_action_id == pa.id,
            Incident.status.notin_(["resolved"]),
        ).all()
        chain["incidents"] = [_slim_incident(inc) for inc in incidents]
        blockers.append(chain)

    return {
        "operation": operation,
        "blocked": True,
        "blockers_count": len(blockers),
        "message": f"Operacja '{operation}' zablokowana przez {len(blockers)} policy action(s).",
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# V. Incident → related entities (cross-reference)
# ---------------------------------------------------------------------------

def get_incident_correlations(db: Session, incident_id: int) -> Dict[str, Any]:
    """
    Wszystkie skorelowane encje dla danego incydentu — w płaskiej strukturze.
    """
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if incident is None:
        raise ValueError(f"Incydent nie znaleziono: {incident_id}")

    result: Dict[str, Any] = {
        "incident": _slim_incident(incident),
        "policy_action": None,
        "source_record": None,
        "promotion": None,
        "rollback": None,
        "related_incidents": [],
        "related_logs_count": 0,
    }

    # Policy action
    pa = db.query(PolicyAction).filter(PolicyAction.id == incident.policy_action_id).first()
    if pa:
        result["policy_action"] = _slim_policy_action(pa)

        # Source record
        result["source_record"] = _get_source_summary(db, pa.source_type, pa.source_id)

        # Promotion powiązana ze źródłem
        promo_id = _find_promotion_id(db, pa.source_type, pa.source_id)
        if promo_id:
            promo = db.query(ConfigPromotion).filter(ConfigPromotion.id == promo_id).first()
            if promo:
                result["promotion"] = _slim_promotion(promo)

            # Rollback(i) powiązane z tą promocją
            rb = db.query(ConfigRollback).filter(ConfigRollback.promotion_id == promo_id).first()
            if rb:
                result["rollback"] = _slim_rollback(rb)

        # Inne incydenty dla tej samej promocji (sibling incidents)
        if promo_id:
            _add_sibling_incidents(db, promo_id, incident_id, result)

    # Count related logs
    log_count = (
        db.query(SystemLog)
        .filter(
            SystemLog.module == "notification_hooks",
            SystemLog.message.like(f"%#{incident_id}%"),
        )
        .count()
    )
    result["related_logs_count"] = log_count

    return result


# ---------------------------------------------------------------------------
# Helpers (wewnętrzne)
# ---------------------------------------------------------------------------

def _add_source_events(
    db: Session,
    source_type: str,
    source_id: int,
    events: List[Dict[str, Any]],
) -> None:
    """Dodaj zdarzenia ze źródłowego rekordu (monitoring / rollback decision)."""
    info = _SOURCE_TYPE_INFO.get(source_type)
    if not info:
        return

    model = info["model"]
    row = db.query(model).filter(model.id == source_id).first()
    if row is None:
        return

    if source_type == "promotion_monitoring":
        events.append({
            **_slim_promo_monitoring(row),
            "event_type": "monitoring_verdict",
            "event_at": row.started_at.isoformat() if row.started_at else None,
        })
        # Upstream promotion
        promo = db.query(ConfigPromotion).filter(ConfigPromotion.id == row.promotion_id).first()
        if promo:
            events.append({
                **_slim_promotion(promo),
                "event_type": "promotion_initiated",
                "event_at": promo.initiated_at.isoformat() if promo.initiated_at else None,
            })

    elif source_type == "rollback_decision":
        events.append({
            **_slim_rollback(row),
            "event_type": "rollback_decision",
            "event_at": row.initiated_at.isoformat() if row.initiated_at else None,
        })
        # Upstream promotion
        promo = db.query(ConfigPromotion).filter(ConfigPromotion.id == row.promotion_id).first()
        if promo:
            events.append({
                **_slim_promotion(promo),
                "event_type": "promotion_initiated",
                "event_at": promo.initiated_at.isoformat() if promo.initiated_at else None,
            })

    elif source_type == "rollback_monitoring":
        events.append({
            **_slim_rb_monitoring(row),
            "event_type": "rollback_monitoring_verdict",
            "event_at": row.started_at.isoformat() if row.started_at else None,
        })
        # Upstream rollback
        rb = db.query(ConfigRollback).filter(ConfigRollback.id == row.rollback_id).first()
        if rb:
            events.append({
                **_slim_rollback(rb),
                "event_type": "rollback_decision",
                "event_at": rb.initiated_at.isoformat() if rb.initiated_at else None,
            })


def _add_policy_actions_for_source(
    db: Session,
    source_type: str,
    source_id: int,
    events: List[Dict[str, Any]],
) -> None:
    """Dodaj policy actions i ich incydenty dla danego źródła."""
    pas = (
        db.query(PolicyAction)
        .filter(PolicyAction.source_type == source_type, PolicyAction.source_id == source_id)
        .all()
    )
    for pa in pas:
        events.append({
            **_slim_policy_action(pa),
            "event_type": "policy_action_created",
            "event_at": pa.created_at.isoformat() if pa.created_at else None,
        })
        # Incidents for this PA
        incidents = db.query(Incident).filter(Incident.policy_action_id == pa.id).all()
        for inc in incidents:
            events.append({
                **_slim_incident(inc),
                "event_type": "incident_created",
                "event_at": inc.created_at.isoformat() if inc.created_at else None,
            })


def _add_related_logs(
    db: Session,
    *,
    incident_id: int | None = None,
    policy_action_id: int | None = None,
    events: List[Dict[str, Any]],
    limit: int = 20,
) -> None:
    """Dodaj powiązane logi systemowe do listy zdarzeń."""
    query = db.query(SystemLog).filter(SystemLog.module == "notification_hooks")

    # Szukaj logów zawierających ID incydentu lub policy action
    conditions = []
    if incident_id is not None:
        conditions.append(SystemLog.message.like(f"%#{incident_id}%"))
    if policy_action_id is not None:
        conditions.append(SystemLog.message.like(f"%#{policy_action_id}%"))

    if not conditions:
        return

    from sqlalchemy import or_
    query = query.filter(or_(*conditions))
    rows = query.order_by(SystemLog.timestamp.desc()).limit(limit).all()

    for row in rows:
        events.append({
            **_slim_log(row),
            "event_type": "notification",
            "event_at": row.timestamp.isoformat() if row.timestamp else None,
        })


def _get_source_summary(db: Session, source_type: str, source_id: int) -> Dict[str, Any] | None:
    """Zwróć podsumowanie źródłowego rekordu."""
    info = _SOURCE_TYPE_INFO.get(source_type)
    if not info:
        return {"source_type": source_type, "source_id": source_id, "label": "nieznane źródło"}

    model = info["model"]
    row = db.query(model).filter(model.id == source_id).first()
    if row is None:
        return {"source_type": source_type, "source_id": source_id, "label": "rekord nie znaleziony"}

    if source_type == "promotion_monitoring":
        return _slim_promo_monitoring(row)
    elif source_type == "rollback_decision":
        return _slim_rollback(row)
    elif source_type == "rollback_monitoring":
        return _slim_rb_monitoring(row)

    return {"source_type": source_type, "source_id": source_id}


def _find_promotion_id(db: Session, source_type: str, source_id: int) -> int | None:
    """Znajdź promotion_id powiązaną ze źródłem (upstream traversal)."""
    if source_type == "promotion_monitoring":
        row = db.query(PromotionMonitoring).filter(PromotionMonitoring.id == source_id).first()
        return int(row.promotion_id) if row else None
    elif source_type == "rollback_decision":
        row = db.query(ConfigRollback).filter(ConfigRollback.id == source_id).first()
        return int(row.promotion_id) if row else None
    elif source_type == "rollback_monitoring":
        row = db.query(RollbackMonitoring).filter(RollbackMonitoring.id == source_id).first()
        if row:
            rb = db.query(ConfigRollback).filter(ConfigRollback.id == row.rollback_id).first()
            return int(rb.promotion_id) if rb else None
    return None


def _add_sibling_incidents(
    db: Session,
    promotion_id: int,
    exclude_incident_id: int,
    result: Dict[str, Any],
) -> None:
    """Znajdź inne incydenty powiązane z tą samą promocją (sibling incidents)."""
    # Znajdź wszystkie policy actions z tym samym promotion chain
    pm_rows = db.query(PromotionMonitoring).filter(
        PromotionMonitoring.promotion_id == promotion_id
    ).all()
    pm_ids = [pm.id for pm in pm_rows]

    rb_rows = db.query(ConfigRollback).filter(
        ConfigRollback.promotion_id == promotion_id
    ).all()
    rb_ids = [rb.id for rb in rb_rows]

    rbm_ids = []
    for rb in rb_rows:
        rbm_rows = db.query(RollbackMonitoring).filter(
            RollbackMonitoring.rollback_id == rb.id
        ).all()
        rbm_ids.extend([rbm.id for rbm in rbm_rows])

    # Znajdź policy actions powiązane z tymi źródłami
    from sqlalchemy import or_
    conditions = []
    if pm_ids:
        conditions.append(
            (PolicyAction.source_type == "promotion_monitoring") & (PolicyAction.source_id.in_(pm_ids))
        )
    if rb_ids:
        conditions.append(
            (PolicyAction.source_type == "rollback_decision") & (PolicyAction.source_id.in_(rb_ids))
        )
    if rbm_ids:
        conditions.append(
            (PolicyAction.source_type == "rollback_monitoring") & (PolicyAction.source_id.in_(rbm_ids))
        )

    if not conditions:
        return

    related_pas = db.query(PolicyAction).filter(or_(*conditions)).all()
    pa_ids = [pa.id for pa in related_pas]

    if not pa_ids:
        return

    siblings = (
        db.query(Incident)
        .filter(
            Incident.policy_action_id.in_(pa_ids),
            Incident.id != exclude_incident_id,
        )
        .all()
    )
    result["related_incidents"] = [_slim_incident(s) for s in siblings]
