"""
Controlled promotion flow for approved recommendations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.database import ConfigPromotion, Position, Recommendation, RecommendationReview, get_config_snapshot, utc_now_naive
from backend.governance import enforce_pipeline_permission
from backend.recommendations import get_recommendation
from backend.runtime_settings import RuntimeSettingsError, apply_runtime_updates, build_runtime_state


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _promotion_dict(row: ConfigPromotion) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "recommendation_id": int(row.recommendation_id),
        "review_id": int(row.review_id),
        "from_snapshot_id": row.from_snapshot_id,
        "to_snapshot_id": row.to_snapshot_id,
        "status": row.status,
        "initiated_at": row.initiated_at.isoformat() if row.initiated_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        "failed_at": row.failed_at.isoformat() if row.failed_at else None,
        "initiated_by": row.initiated_by,
        "failure_reason": row.failure_reason,
        "rollback_available": bool(row.rollback_available),
        "rollback_snapshot_id": row.rollback_snapshot_id,
        "post_promotion_monitoring_status": row.post_promotion_monitoring_status,
        "validation_summary": _json_load(row.validation_summary_json) or {},
        "runtime_apply_result": _json_load(row.runtime_apply_result_json) or {},
        "notes": row.notes,
    }


def _latest_approved_review(db: Session, recommendation_id: int) -> RecommendationReview | None:
    return (
        db.query(RecommendationReview)
        .filter(
            RecommendationReview.recommendation_id == recommendation_id,
            RecommendationReview.review_status == "approved",
            RecommendationReview.promotion_ready.is_(True),
        )
        .order_by(RecommendationReview.reviewed_at.desc(), RecommendationReview.id.desc())
        .first()
    )


def _snapshot_to_updates(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    payload = snapshot.get("payload") or {}
    sections = payload.get("sections") or {}
    updates: Dict[str, Any] = {}
    for section_values in sections.values():
        if isinstance(section_values, dict):
            updates.update(section_values)
    watchlist = payload.get("watchlist")
    if isinstance(watchlist, list):
        updates["watchlist"] = watchlist
    return updates


def _active_position_count(db: Session) -> int:
    return int(db.query(Position).count())


def _current_runtime_snapshot_id(db: Session) -> str:
    state = build_runtime_state(db, active_position_count=_active_position_count(db))
    snapshot_id = state.get("config_snapshot_id")
    if not snapshot_id:
        raise ValueError("Unable to resolve current active runtime snapshot")
    return str(snapshot_id)


def _validate_promotion_ready(db: Session, recommendation_id: int) -> Dict[str, Any]:
    recommendation = get_recommendation(db, recommendation_id)
    row = db.query(Recommendation).filter(Recommendation.id == recommendation_id).first()
    if row is None:
        raise ValueError(f"Recommendation not found: {recommendation_id}")
    if (row.status or "").lower() != "approved":
        raise ValueError(f"Recommendation is not approved: {row.status}")
    review = _latest_approved_review(db, recommendation_id)
    if review is None:
        raise ValueError("Approved review with promotion_ready=true is required")
    target_snapshot = get_config_snapshot(db, recommendation["candidate_snapshot_id"])
    if target_snapshot is None:
        raise ValueError(f"Missing target snapshot: {recommendation['candidate_snapshot_id']}")
    source_snapshot = get_config_snapshot(db, recommendation["baseline_snapshot_id"])
    if source_snapshot is None:
        raise ValueError(f"Missing source snapshot: {recommendation['baseline_snapshot_id']}")
    existing = (
        db.query(ConfigPromotion)
        .filter(
            ConfigPromotion.recommendation_id == recommendation_id,
            ConfigPromotion.status.in_(["pending", "applied"]),
        )
        .first()
    )
    if existing is not None:
        raise ValueError(f"Promotion already exists for recommendation {recommendation_id}: {existing.status}")
    current_snapshot_id = _current_runtime_snapshot_id(db)
    validation_summary = {
        "current_snapshot_id": current_snapshot_id,
        "approved_review_id": int(review.id),
        "baseline_snapshot_id": recommendation["baseline_snapshot_id"],
        "candidate_snapshot_id": recommendation["candidate_snapshot_id"],
        "current_matches_baseline": current_snapshot_id == recommendation["baseline_snapshot_id"],
    }
    if current_snapshot_id != recommendation["baseline_snapshot_id"]:
        raise ValueError(
            f"Active runtime snapshot {current_snapshot_id} does not match approved baseline {recommendation['baseline_snapshot_id']}"
        )
    return {
        "recommendation": recommendation,
        "review": review,
        "source_snapshot": source_snapshot,
        "target_snapshot": target_snapshot,
        "current_snapshot_id": current_snapshot_id,
        "validation_summary": validation_summary,
    }


def promote_recommendation(
    db: Session,
    *,
    recommendation_id: int,
    initiated_by: str,
    notes: str | None = None,
) -> Dict[str, Any]:
    enforce_pipeline_permission(db, "promotion")
    ctx = _validate_promotion_ready(db, recommendation_id)
    promotion = ConfigPromotion(
        recommendation_id=recommendation_id,
        review_id=int(ctx["review"].id),
        from_snapshot_id=ctx["current_snapshot_id"],
        to_snapshot_id=ctx["recommendation"]["candidate_snapshot_id"],
        status="pending",
        initiated_at=utc_now_naive(),
        initiated_by=initiated_by,
        rollback_available=True,
        rollback_snapshot_id=ctx["current_snapshot_id"],
        post_promotion_monitoring_status="pending",
        validation_summary_json=_json_text(ctx["validation_summary"]),
        notes=notes,
    )
    db.add(promotion)
    db.flush()

    updates = _snapshot_to_updates(ctx["target_snapshot"])
    try:
        apply_result = apply_runtime_updates(
            db,
            updates,
            actor=f"promotion:{initiated_by}",
            active_position_count=_active_position_count(db),
        )
        promotion.status = "applied"
        promotion.applied_at = utc_now_naive()
        promotion.runtime_apply_result_json = _json_text(apply_result)
        promotion.post_promotion_monitoring_status = "pending"
        db.commit()
        from backend.post_promotion_monitoring import initialize_monitoring_record
        initialize_monitoring_record(db, int(promotion.id), notes="initialized after successful promotion")
    except (RuntimeSettingsError, ValueError) as exc:
        db.rollback()
        db.add(promotion)
        promotion.status = "failed"
        promotion.failed_at = utc_now_naive()
        promotion.failure_reason = str(exc)
        promotion.post_promotion_monitoring_status = "blocked"
        db.commit()
        db.refresh(promotion)
        return get_promotion(db, int(promotion.id))
    db.refresh(promotion)
    return get_promotion(db, int(promotion.id))


def get_promotion(db: Session, promotion_id: int) -> Dict[str, Any]:
    row = db.query(ConfigPromotion).filter(ConfigPromotion.id == promotion_id).first()
    if row is None:
        raise ValueError(f"Promotion not found: {promotion_id}")
    return {
        **_promotion_dict(row),
        "recommendation": get_recommendation(db, int(row.recommendation_id)),
        "from_snapshot": get_config_snapshot(db, row.from_snapshot_id),
        "to_snapshot": get_config_snapshot(db, row.to_snapshot_id),
    }


def list_promotions(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(ConfigPromotion).order_by(ConfigPromotion.initiated_at.desc(), ConfigPromotion.id.desc()).all()
    return [get_promotion(db, int(row.id)) for row in rows if row.id is not None]
