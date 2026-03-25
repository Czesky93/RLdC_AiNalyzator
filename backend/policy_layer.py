"""
Policy layer: verdict → operational action mapping.

Konsumuje istniejące verdicty z:
  - promotion_monitoring
  - config_rollbacks (rollback decision)
  - rollback_monitoring (post-rollback monitoring)

Mapuje je deterministycznie na akcje operacyjne i zapisuje audit trail.
NIE wykonuje żadnych technicznych akcji (rollback, promotion, apply).
NIE liczy ekonomiki po swojemu.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.database import (
    ConfigRollback,
    PolicyAction,
    PromotionMonitoring,
    RollbackMonitoring,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stałe
# ---------------------------------------------------------------------------

POLICY_ACTIONS = {
    "NO_ACTION",
    "CONTINUE_MONITORING",
    "REQUIRE_MANUAL_REVIEW",
    "PREPARE_ROLLBACK",
    "FREEZE_PROMOTIONS",
    "FREEZE_EXPERIMENTS",
    "ESCALATE_TO_OPERATOR",
    "CLOSE_INCIDENT",
}

_PRIORITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ---------------------------------------------------------------------------
# Helpery JSON
# ---------------------------------------------------------------------------

def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


# ---------------------------------------------------------------------------
# Serializacja rekordu
# ---------------------------------------------------------------------------

def _policy_action_dict(row: PolicyAction) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "source_type": row.source_type,
        "source_id": int(row.source_id),
        "policy_action": row.policy_action,
        "priority": row.priority,
        "requires_human_review": bool(row.requires_human_review),
        "promotion_allowed": bool(row.promotion_allowed),
        "rollback_allowed": bool(row.rollback_allowed),
        "experiments_allowed": bool(row.experiments_allowed),
        "freeze_recommendations": bool(row.freeze_recommendations),
        "summary": row.summary,
        "reason_codes": _json_load(row.reason_codes_json) or [],
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "superseded_by": row.superseded_by,
        "notes": row.notes,
    }


# ---------------------------------------------------------------------------
# Mapowania verdict → action (deterministyczne)
# ---------------------------------------------------------------------------

def _map_promotion_monitoring_verdict(status: str, reason_codes: List[str]) -> Dict[str, Any]:
    """Mapuj verdict z promotion_monitoring na policy action."""
    status = (status or "").lower()

    if status == "healthy":
        return {
            "policy_action": "NO_ACTION",
            "priority": "low",
            "requires_human_review": False,
            "promotion_allowed": True,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if status in {"pending", "collecting"}:
        return {
            "policy_action": "CONTINUE_MONITORING",
            "priority": "low",
            "requires_human_review": False,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if status == "watch":
        return {
            "policy_action": "CONTINUE_MONITORING",
            "priority": "medium",
            "requires_human_review": False,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if status == "warning":
        return {
            "policy_action": "REQUIRE_MANUAL_REVIEW",
            "priority": "high",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": True,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }
    if status == "rollback_candidate":
        return {
            "policy_action": "PREPARE_ROLLBACK",
            "priority": "critical",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": True,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }

    # Nieznany status — bezpieczna domyślna
    return {
        "policy_action": "CONTINUE_MONITORING",
        "priority": "medium",
        "requires_human_review": False,
        "promotion_allowed": False,
        "rollback_allowed": False,
        "experiments_allowed": True,
        "freeze_recommendations": False,
    }


def _map_rollback_decision_verdict(decision_status: str, urgency: str, reason_codes: List[str]) -> Dict[str, Any]:
    """Mapuj verdict z rollback_decision na policy action."""
    decision_status = (decision_status or "").lower()
    urgency = (urgency or "low").lower()

    if decision_status == "no_action":
        return {
            "policy_action": "NO_ACTION",
            "priority": "low",
            "requires_human_review": False,
            "promotion_allowed": True,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if decision_status == "continue_monitoring":
        return {
            "policy_action": "CONTINUE_MONITORING",
            "priority": urgency if urgency in _PRIORITY_ORDER else "medium",
            "requires_human_review": False,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if decision_status == "rollback_recommended":
        return {
            "policy_action": "PREPARE_ROLLBACK",
            "priority": "high",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": True,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }
    if decision_status == "rollback_required":
        return {
            "policy_action": "ESCALATE_TO_OPERATOR",
            "priority": "critical",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": True,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }

    return {
        "policy_action": "CONTINUE_MONITORING",
        "priority": "medium",
        "requires_human_review": False,
        "promotion_allowed": False,
        "rollback_allowed": False,
        "experiments_allowed": True,
        "freeze_recommendations": False,
    }


def _map_post_rollback_monitoring_verdict(status: str, reason_codes: List[str]) -> Dict[str, Any]:
    """Mapuj verdict z post_rollback_monitoring na policy action."""
    status = (status or "").lower()

    if status == "stabilized":
        return {
            "policy_action": "CLOSE_INCIDENT",
            "priority": "low",
            "requires_human_review": False,
            "promotion_allowed": True,
            "rollback_allowed": False,
            "experiments_allowed": True,
            "freeze_recommendations": False,
        }
    if status in {"pending", "collecting"}:
        return {
            "policy_action": "CONTINUE_MONITORING",
            "priority": "low",
            "requires_human_review": False,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }
    if status == "watch":
        return {
            "policy_action": "CONTINUE_MONITORING",
            "priority": "medium",
            "requires_human_review": False,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }
    if status == "warning":
        return {
            "policy_action": "REQUIRE_MANUAL_REVIEW",
            "priority": "high",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }
    if status == "escalate":
        return {
            "policy_action": "ESCALATE_TO_OPERATOR",
            "priority": "critical",
            "requires_human_review": True,
            "promotion_allowed": False,
            "rollback_allowed": False,
            "experiments_allowed": False,
            "freeze_recommendations": True,
        }

    return {
        "policy_action": "CONTINUE_MONITORING",
        "priority": "medium",
        "requires_human_review": False,
        "promotion_allowed": False,
        "rollback_allowed": False,
        "experiments_allowed": True,
        "freeze_recommendations": False,
    }


# ---------------------------------------------------------------------------
# Publiczne API engine
# ---------------------------------------------------------------------------

_SOURCE_MAPPERS = {
    "promotion_monitoring": _map_promotion_monitoring_verdict,
    "rollback_decision": _map_rollback_decision_verdict,
    "rollback_monitoring": _map_post_rollback_monitoring_verdict,
}


def evaluate_policy(
    *,
    source_type: str,
    verdict_status: str,
    reason_codes: List[str] | None = None,
    urgency: str | None = None,
) -> Dict[str, Any]:
    """
    Czysta funkcja: verdict → policy action mapping.
    Nie dotyka DB, nie wykonuje side-effectów.
    """
    reason_codes = list(reason_codes or [])
    mapper = _SOURCE_MAPPERS.get(source_type)
    if mapper is None:
        raise ValueError(f"Nieznany source_type: {source_type}")

    if source_type == "rollback_decision":
        result = mapper(verdict_status, urgency or "low", reason_codes)
    else:
        result = mapper(verdict_status, reason_codes)

    summary = (
        f"policy={result['policy_action']}: source={source_type}, "
        f"verdict={verdict_status}, priority={result['priority']}, "
        f"reasons={','.join(reason_codes) or 'none'}"
    )
    result["summary"] = summary
    result["reason_codes"] = reason_codes
    return result


def create_policy_action(
    db: Session,
    *,
    source_type: str,
    source_id: int,
    verdict_status: str,
    reason_codes: List[str] | None = None,
    urgency: str | None = None,
    notes: str | None = None,
) -> Dict[str, Any]:
    """
    Ewaluuj verdict i zapisz policy action do DB.
    Superseduje poprzednie otwarte akcje dla tego samego źródła.
    """
    evaluation = evaluate_policy(
        source_type=source_type,
        verdict_status=verdict_status,
        reason_codes=reason_codes,
        urgency=urgency,
    )

    # Superseduj istniejące otwarte akcje z tego samego source
    open_actions = (
        db.query(PolicyAction)
        .filter(
            PolicyAction.source_type == source_type,
            PolicyAction.source_id == source_id,
            PolicyAction.status == "open",
        )
        .all()
    )

    new_row = PolicyAction(
        source_type=source_type,
        source_id=source_id,
        policy_action=evaluation["policy_action"],
        priority=evaluation["priority"],
        requires_human_review=evaluation["requires_human_review"],
        promotion_allowed=evaluation["promotion_allowed"],
        rollback_allowed=evaluation["rollback_allowed"],
        experiments_allowed=evaluation["experiments_allowed"],
        freeze_recommendations=evaluation["freeze_recommendations"],
        summary=evaluation["summary"],
        reason_codes_json=_json_text(evaluation["reason_codes"]),
        status="open",
        notes=notes,
    )
    db.add(new_row)
    db.flush()

    for old_action in open_actions:
        old_action.status = "superseded"
        old_action.superseded_by = new_row.id
        old_action.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(new_row)

    logger.info(
        "Policy action created: id=%s, source=%s/%s, action=%s, priority=%s",
        new_row.id, source_type, source_id, evaluation["policy_action"], evaluation["priority"],
    )
    return _policy_action_dict(new_row)


def resolve_policy_action(
    db: Session,
    policy_action_id: int,
    *,
    notes: str | None = None,
) -> Dict[str, Any]:
    """Ręczne zamknięcie akcji policy (resolved)."""
    row = db.query(PolicyAction).filter(PolicyAction.id == policy_action_id).first()
    if row is None:
        raise ValueError(f"PolicyAction nie znaleziono: {policy_action_id}")
    if row.status != "open":
        raise ValueError(f"PolicyAction nie jest open: {row.status}")

    row.status = "resolved"
    row.resolved_at = datetime.utcnow()
    if notes:
        row.notes = (row.notes or "") + f"\n[resolved] {notes}" if row.notes else f"[resolved] {notes}"
    db.commit()
    db.refresh(row)
    return _policy_action_dict(row)


# ---------------------------------------------------------------------------
# Odczyt
# ---------------------------------------------------------------------------

def get_policy_action(db: Session, policy_action_id: int) -> Dict[str, Any]:
    row = db.query(PolicyAction).filter(PolicyAction.id == policy_action_id).first()
    if row is None:
        raise ValueError(f"PolicyAction nie znaleziono: {policy_action_id}")
    return _policy_action_dict(row)


def list_policy_actions(
    db: Session,
    *,
    status: str | None = None,
    source_type: str | None = None,
) -> List[Dict[str, Any]]:
    query = db.query(PolicyAction)
    if status:
        query = query.filter(PolicyAction.status == status)
    if source_type:
        query = query.filter(PolicyAction.source_type == source_type)
    rows = query.order_by(PolicyAction.created_at.desc(), PolicyAction.id.desc()).all()
    return [_policy_action_dict(r) for r in rows]


def list_active_policy_actions(db: Session) -> List[Dict[str, Any]]:
    """Zwróć wszystkie otwarte policy actions posortowane wg priorytetu (critical first)."""
    rows = (
        db.query(PolicyAction)
        .filter(PolicyAction.status == "open")
        .all()
    )
    rows.sort(key=lambda r: (-_PRIORITY_ORDER.get(r.priority or "low", 0), -(r.id or 0)))
    return [_policy_action_dict(r) for r in rows]


def policy_actions_summary(db: Session) -> Dict[str, Any]:
    """Podsumowanie stanu policy actions do dashboardu."""
    open_actions = db.query(PolicyAction).filter(PolicyAction.status == "open").all()
    total = db.query(PolicyAction).count()

    by_action = {}
    by_priority = {}
    any_freeze_promotions = False
    any_freeze_experiments = False
    any_freeze_recommendations = False
    any_requires_review = False

    for row in open_actions:
        action = row.policy_action or "UNKNOWN"
        by_action[action] = by_action.get(action, 0) + 1
        prio = row.priority or "low"
        by_priority[prio] = by_priority.get(prio, 0) + 1
        if not row.promotion_allowed:
            any_freeze_promotions = True
        if not row.experiments_allowed:
            any_freeze_experiments = True
        if row.freeze_recommendations:
            any_freeze_recommendations = True
        if row.requires_human_review:
            any_requires_review = True

    return {
        "total_policy_actions": total,
        "open_count": len(open_actions),
        "by_action": by_action,
        "by_priority": by_priority,
        "any_freeze_promotions": any_freeze_promotions,
        "any_freeze_experiments": any_freeze_experiments,
        "any_freeze_recommendations": any_freeze_recommendations,
        "any_requires_human_review": any_requires_review,
    }
