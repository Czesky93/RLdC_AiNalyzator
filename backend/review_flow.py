"""
Review / approval flow for recommendations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import Recommendation, RecommendationReview
from backend.recommendations import get_recommendation, list_recommendations


_REVIEWABLE_STATUSES = {"open", "under_review", "deferred"}
_TERMINAL_STATUSES = {"approved", "rejected", "expired", "superseded"}
_ALLOWED_ACTIONS = {"approve", "reject", "defer", "start_review"}


def _review_dict(row: RecommendationReview) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "recommendation_id": int(row.recommendation_id),
        "review_status": row.review_status,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reviewed_by": row.reviewed_by,
        "decision_reason": row.decision_reason,
        "notes": row.notes,
        "promotion_ready": bool(row.promotion_ready),
        "previous_review_id": row.previous_review_id,
        "superseded_by": row.superseded_by,
    }


def _latest_review(db: Session, recommendation_id: int) -> RecommendationReview | None:
    return (
        db.query(RecommendationReview)
        .filter(RecommendationReview.recommendation_id == recommendation_id)
        .order_by(RecommendationReview.reviewed_at.desc(), RecommendationReview.id.desc())
        .first()
    )


def review_bundle(db: Session, recommendation_id: int) -> Dict[str, Any]:
    recommendation = get_recommendation(db, recommendation_id)
    reviews = (
        db.query(RecommendationReview)
        .filter(RecommendationReview.recommendation_id == recommendation_id)
        .order_by(RecommendationReview.reviewed_at.desc(), RecommendationReview.id.desc())
        .all()
    )
    latest = _latest_review(db, recommendation_id)
    return {
        "recommendation": recommendation,
        "current_status": recommendation.get("status"),
        "latest_review": _review_dict(latest) if latest else None,
        "review_history": [_review_dict(item) for item in reviews],
        "promotion_ready": bool(latest.promotion_ready) if latest else False,
    }


def list_review_queue(db: Session) -> List[Dict[str, Any]]:
    items = list_recommendations(db)
    return [item for item in items if (item.get("status") or "").lower() in {"open", "under_review", "deferred"}]


def _transition_status(current_status: str, action: str) -> str:
    current = (current_status or "open").lower()
    if action not in _ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported review action: {action}")
    if current in _TERMINAL_STATUSES:
        raise ValueError(f"Recommendation is already in terminal state: {current}")
    if current not in _REVIEWABLE_STATUSES and current != "open":
        raise ValueError(f"Recommendation is not reviewable from state: {current}")

    mapping = {
        "start_review": "under_review",
        "approve": "approved",
        "reject": "rejected",
        "defer": "deferred",
    }
    return mapping[action]


def apply_review_decision(
    db: Session,
    *,
    recommendation_id: int,
    action: str,
    reviewed_by: str,
    decision_reason: str | None = None,
    notes: str | None = None,
    supersede_open_others: bool = False,
) -> Dict[str, Any]:
    recommendation_row = db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
    if recommendation_row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")

    # Ensure bundle can be resolved before status transition.
    recommendation = get_recommendation(db, recommendation_id)
    if not recommendation.get("experiment") or not recommendation.get("config_diff"):
        raise ValueError("Recommendation is missing experiment or snapshot context")

    current_status = (recommendation_row.status or "open").lower()
    new_status = _transition_status(current_status, action)
    latest = _latest_review(db, recommendation_id)

    review = RecommendationReview(
        recommendation_id=recommendation_id,
        review_status=new_status,
        reviewed_at=datetime.utcnow(),
        reviewed_by=reviewed_by,
        decision_reason=decision_reason,
        notes=notes,
        promotion_ready=new_status == "approved",
        previous_review_id=int(latest.id) if latest and latest.id is not None else None,
    )
    db.add(review)
    db.flush()

    if latest is not None:
        latest.superseded_by = int(review.id)

    recommendation_row.status = new_status

    if supersede_open_others:
        siblings = (
            db.query(Recommendation)
            .filter(
                Recommendation.id != recommendation_id,
                Recommendation.baseline_snapshot_id == recommendation_row.baseline_snapshot_id,
                Recommendation.candidate_snapshot_id == recommendation_row.candidate_snapshot_id,
                Recommendation.status.in_(list(_REVIEWABLE_STATUSES)),
            )
            .all()
        )
        for sibling in siblings:
            sibling.status = "superseded"

    db.commit()
    db.refresh(review)
    return review_bundle(db, recommendation_id)
