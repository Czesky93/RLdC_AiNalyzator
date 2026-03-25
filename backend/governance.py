"""
Governance / operator workflow layer.

Warstwa nad policy_layer — definiuje:
  - freeze enforcement (blokady pipeline'u na podstawie aktywnych policy actions),
  - incident lifecycle (open → acknowledged → in_progress → escalated → resolved),
  - operator queue (kolejka akcji wymagających interwencji),
  - pipeline status (zagregowany stan blokad).

NIE wykonuje technicznych akcji (rollback, promotion, apply).
NIE liczy ekonomiki po swojemu.
NIE rusza istniejących warstw backendowych.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import Incident, PolicyAction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wyjątek freeze
# ---------------------------------------------------------------------------

class PipelineFreezeError(Exception):
    """Operacja zablokowana przez aktywne policy actions (governance freeze)."""

    def __init__(self, operation: str, blocking_actions: list):
        self.operation = operation
        self.blocking_actions = blocking_actions
        blockers_desc = "; ".join(
            f"[PA#{b['policy_action_id']}] {b['policy_action']} ({b['priority']})"
            for b in blocking_actions
        )
        super().__init__(
            f"Operacja '{operation}' zablokowana przez governance freeze. "
            f"Aktywne blokery: {blockers_desc}"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": "pipeline_freeze",
            "operation": self.operation,
            "message": str(self),
            "blocking_actions": self.blocking_actions,
            "blockers_count": len(self.blocking_actions),
        }

# ---------------------------------------------------------------------------
# Stałe
# ---------------------------------------------------------------------------

INCIDENT_STATUSES = {"open", "acknowledged", "in_progress", "escalated", "resolved"}

# SLA — czas na acknowledge (minuty) w zależności od priorytetu
SLA_MINUTES = {
    "critical": 15,
    "high": 60,
    "medium": 0,   # brak auto-eskalacji
    "low": 0,       # brak auto-eskalacji
}

# Dozwolone przejścia stanu incydentu
_TRANSITIONS = {
    "open": {"acknowledged", "resolved"},
    "acknowledged": {"in_progress", "escalated", "resolved"},
    "in_progress": {"resolved"},
    "escalated": {"in_progress", "resolved"},
}


# ---------------------------------------------------------------------------
# Serializacja rekordu
# ---------------------------------------------------------------------------

def _incident_dict(row: Incident) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "policy_action_id": int(row.policy_action_id),
        "status": row.status,
        "priority": row.priority,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "acknowledged_by": row.acknowledged_by,
        "escalated_at": row.escalated_at.isoformat() if row.escalated_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "resolved_by": row.resolved_by,
        "resolution_notes": row.resolution_notes,
        "sla_deadline": row.sla_deadline.isoformat() if row.sla_deadline else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# I. Freeze Enforcement
# ---------------------------------------------------------------------------

def check_pipeline_permission(
    db: Session,
    operation: str,
) -> Dict[str, Any]:
    """
    Sprawdź, czy operacja jest dozwolona na podstawie aktywnych (open) policy actions.

    operation: 'promotion' | 'rollback' | 'experiment' | 'recommendation'

    Zwraca:
        {"allowed": True/False, "blocking_actions": [...]}
    """
    valid_ops = {"promotion", "rollback", "experiment", "recommendation"}
    if operation not in valid_ops:
        raise ValueError(f"Nieznana operacja: {operation}. Dozwolone: {valid_ops}")

    open_actions = (
        db.query(PolicyAction)
        .filter(PolicyAction.status == "open")
        .all()
    )

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
            blocking.append({
                "policy_action_id": int(pa.id),
                "policy_action": pa.policy_action,
                "priority": pa.priority,
                "source_type": pa.source_type,
                "source_id": int(pa.source_id),
                "summary": pa.summary,
            })

    return {
        "allowed": len(blocking) == 0,
        "blocking_actions": blocking,
    }


def enforce_pipeline_permission(db: Session, operation: str) -> None:
    """
    Sprawdza uprawnienia pipeline i rzuca PipelineFreezeError jeśli operacja
    jest zablokowana. Służy jako one-liner guard w flow functions.
    """
    result = check_pipeline_permission(db, operation)
    if not result["allowed"]:
        logger.warning(
            "Pipeline freeze: operacja '%s' zablokowana przez %d policy actions",
            operation, len(result["blocking_actions"]),
        )
        raise PipelineFreezeError(operation, result["blocking_actions"])


def get_pipeline_status(db: Session) -> Dict[str, Any]:
    """
    Zagregowany stan blokad pipeline'u.
    Zwraca jedno spojrzenie na to, co jest dozwolone a co zablokowane.
    """
    promotions = check_pipeline_permission(db, "promotion")
    rollbacks = check_pipeline_permission(db, "rollback")
    experiments = check_pipeline_permission(db, "experiment")
    recommendations = check_pipeline_permission(db, "recommendation")

    return {
        "promotion_allowed": promotions["allowed"],
        "promotion_blockers_count": len(promotions["blocking_actions"]),
        "rollback_allowed": rollbacks["allowed"],
        "rollback_blockers_count": len(rollbacks["blocking_actions"]),
        "experiment_allowed": experiments["allowed"],
        "experiment_blockers_count": len(experiments["blocking_actions"]),
        "recommendation_allowed": recommendations["allowed"],
        "recommendation_blockers_count": len(recommendations["blocking_actions"]),
    }


# ---------------------------------------------------------------------------
# II. Incident Lifecycle
# ---------------------------------------------------------------------------

def create_incident(
    db: Session,
    *,
    policy_action_id: int,
    operator: str | None = None,
) -> Dict[str, Any]:
    """
    Utwórz incydent powiązany z policy action.
    Nie tworzy duplikatu, jeśli otwarty incydent dla tej policy action już istnieje.
    """
    pa = db.query(PolicyAction).filter(PolicyAction.id == policy_action_id).first()
    if pa is None:
        raise ValueError(f"PolicyAction nie znaleziono: {policy_action_id}")

    existing = (
        db.query(Incident)
        .filter(
            Incident.policy_action_id == policy_action_id,
            Incident.status.notin_(["resolved"]),
        )
        .first()
    )
    if existing is not None:
        raise ValueError(f"Otwarty incydent dla policy_action_id={policy_action_id} już istnieje (id={existing.id})")

    priority = pa.priority or "low"
    sla_mins = SLA_MINUTES.get(priority, 0)
    now = datetime.utcnow()
    sla_deadline = (now + timedelta(minutes=sla_mins)) if sla_mins > 0 else None

    incident = Incident(
        policy_action_id=policy_action_id,
        status="open",
        priority=priority,
        sla_deadline=sla_deadline,
        created_at=now,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    logger.info(
        "Incident created: id=%s, policy_action_id=%s, priority=%s, sla_deadline=%s",
        incident.id, policy_action_id, priority, sla_deadline,
    )
    return _incident_dict(incident)


def transition_incident(
    db: Session,
    incident_id: int,
    *,
    new_status: str,
    operator: str | None = None,
    notes: str | None = None,
) -> Dict[str, Any]:
    """
    Przejście stanu incydentu z walidacją.
    """
    if new_status not in INCIDENT_STATUSES:
        raise ValueError(f"Nieznany status: {new_status}. Dozwolone: {INCIDENT_STATUSES}")

    row = db.query(Incident).filter(Incident.id == incident_id).first()
    if row is None:
        raise ValueError(f"Incydent nie znaleziono: {incident_id}")

    allowed = _TRANSITIONS.get(row.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Niedozwolone przejście: {row.status} → {new_status}. "
            f"Dozwolone z '{row.status}': {allowed}"
        )

    now = datetime.utcnow()
    row.status = new_status

    if new_status == "acknowledged":
        row.acknowledged_at = now
        row.acknowledged_by = operator or "operator"
    elif new_status == "escalated":
        row.escalated_at = now
    elif new_status == "resolved":
        row.resolved_at = now
        row.resolved_by = operator or "operator"
        if notes:
            row.resolution_notes = notes

    db.commit()
    db.refresh(row)

    logger.info(
        "Incident transition: id=%s, %s → %s, operator=%s",
        incident_id, row.status, new_status, operator,
    )
    return _incident_dict(row)


def get_incident(db: Session, incident_id: int) -> Dict[str, Any]:
    row = db.query(Incident).filter(Incident.id == incident_id).first()
    if row is None:
        raise ValueError(f"Incydent nie znaleziono: {incident_id}")
    return _incident_dict(row)


def list_incidents(
    db: Session,
    *,
    status: str | None = None,
    priority: str | None = None,
) -> List[Dict[str, Any]]:
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    if priority:
        query = query.filter(Incident.priority == priority)
    rows = query.order_by(Incident.created_at.desc()).all()
    return [_incident_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# III. Operator Queue
# ---------------------------------------------------------------------------

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def get_operator_queue(db: Session) -> List[Dict[str, Any]]:
    """
    Kolejka operatora: otwarte incydenty + niezaksjęte policy actions wymagające review.
    Posortowane wg priorytetu (critical first), potem wg czasu utworzenia (najstarsze first).
    """
    # Incydenty niefinalne
    active_incidents = (
        db.query(Incident)
        .filter(Incident.status.notin_(["resolved"]))
        .all()
    )

    # Policy actions wymagające review, które nie mają jeszcze incydentu
    incident_pa_ids = {inc.policy_action_id for inc in active_incidents}

    review_actions = (
        db.query(PolicyAction)
        .filter(
            PolicyAction.status == "open",
            PolicyAction.requires_human_review == True,
        )
        .all()
    )

    queue_items = []

    for inc in active_incidents:
        pa = db.query(PolicyAction).filter(PolicyAction.id == inc.policy_action_id).first()
        now = datetime.utcnow()
        sla_remaining = None
        sla_breached = False
        if inc.sla_deadline:
            delta = (inc.sla_deadline - now).total_seconds()
            sla_remaining = max(0, int(delta))
            sla_breached = delta < 0

        queue_items.append({
            "type": "incident",
            "incident_id": int(inc.id),
            "policy_action_id": int(inc.policy_action_id),
            "incident_status": inc.status,
            "priority": inc.priority,
            "policy_action": pa.policy_action if pa else None,
            "source_type": pa.source_type if pa else None,
            "source_id": int(pa.source_id) if pa else None,
            "summary": pa.summary if pa else None,
            "created_at": inc.created_at.isoformat() if inc.created_at else None,
            "sla_deadline": inc.sla_deadline.isoformat() if inc.sla_deadline else None,
            "sla_remaining_seconds": sla_remaining,
            "sla_breached": sla_breached,
        })

    for pa in review_actions:
        if pa.id in incident_pa_ids:
            continue
        queue_items.append({
            "type": "policy_action",
            "incident_id": None,
            "policy_action_id": int(pa.id),
            "incident_status": None,
            "priority": pa.priority,
            "policy_action": pa.policy_action,
            "source_type": pa.source_type,
            "source_id": int(pa.source_id),
            "summary": pa.summary,
            "created_at": pa.created_at.isoformat() if pa.created_at else None,
            "sla_deadline": None,
            "sla_remaining_seconds": None,
            "sla_breached": False,
        })

    queue_items.sort(key=lambda x: (
        _PRIORITY_ORDER.get(x.get("priority", "low"), 3),
        x.get("created_at", ""),
    ))

    return queue_items


# ---------------------------------------------------------------------------
# IV. Auto-eskalacja SLA
# ---------------------------------------------------------------------------

def escalate_overdue_incidents(db: Session) -> List[Dict[str, Any]]:
    """
    Eskaluj incydenty, które przekroczyły SLA deadline bez acknowledge.
    Wywołuj okresowo (np. co 5 min z workera).
    Zwraca listę eskalowanych incydentów.
    """
    now = datetime.utcnow()
    overdue = (
        db.query(Incident)
        .filter(
            Incident.status == "open",
            Incident.sla_deadline != None,
            Incident.sla_deadline < now,
        )
        .all()
    )

    escalated = []
    for inc in overdue:
        inc.status = "escalated"
        inc.escalated_at = now
        escalated.append(_incident_dict(inc))
        logger.warning(
            "Incident auto-escalated: id=%s, policy_action_id=%s, sla_deadline=%s",
            inc.id, inc.policy_action_id, inc.sla_deadline,
        )

    if escalated:
        db.commit()

    return escalated
