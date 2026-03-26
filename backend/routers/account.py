"""
Account API Router - endpoints dla danych konta (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import os
import re
import requests
import hashlib

from backend.database import get_db, AccountSnapshot, Position, SystemLog, reset_database
from backend.binance_client import get_binance_client
from backend.accounting import compute_demo_account_state, compute_risk_snapshot, get_demo_quote_ccy
from backend.auth import require_admin
from backend.experiments import compare_snapshots_for_experiment, create_experiment, get_experiment, list_experiments
from backend.recommendations import (
    generate_recommendation,
    get_recommendation,
    list_recommendations,
    pending_recommendation_candidates,
    recommendation_overview,
)
from backend.review_flow import apply_review_decision, list_review_queue, review_bundle
from backend.promotion_flow import get_promotion, list_promotions, promote_recommendation
from backend.post_promotion_monitoring import (
    evaluate_monitoring,
    get_monitoring_by_promotion,
    get_monitoring_record,
    list_monitoring_records,
)
from backend.rollback_decision import (
    create_rollback_decision,
    get_rollback_decision,
    latest_rollback_decision_for_promotion,
    list_rollback_decisions,
)
from backend.rollback_flow import execute_rollback, get_rollback_execution, list_rollback_executions
from backend.post_rollback_monitoring import (
    evaluate_post_rollback_monitoring,
    get_post_rollback_monitoring_by_rollback,
    get_post_rollback_monitoring_record,
    list_post_rollback_monitoring_records,
)
from backend.reporting import (
    analytics_bundle,
    config_snapshot_compare_report,
    config_snapshot_payload_report,
    performance_overview,
    risk_effectiveness_report,
)
from backend.policy_layer import (
    create_policy_action,
    get_policy_action,
    list_active_policy_actions,
    list_policy_actions,
    policy_actions_summary,
    resolve_policy_action,
)
from backend.governance import (
    PipelineFreezeError,
    check_pipeline_permission,
    create_incident,
    escalate_overdue_incidents,
    get_incident,
    get_operator_queue,
    get_pipeline_status,
    list_incidents,
    transition_incident,
)
from backend.notification_hooks import (
    dispatch_notification,
    send_telegram_message,
    _get_config as _get_notification_config,
)
from backend.reevaluation_worker import (
    get_worker_status,
    run_worker_cycle,
)
from backend.runtime_settings import RuntimeSettingsError

router = APIRouter()

_openai_status_cache: dict = {"ts": None, "data": None}
_demo_state_cache: dict = {"ts": None, "data": None}


class ExperimentCreateRequest(BaseModel):
    name: str
    baseline_snapshot_id: str
    candidate_snapshot_id: str
    description: Optional[str] = None
    mode: str = "demo"
    scope: str = "global"
    symbol: Optional[str] = None
    strategy_name: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    notes: Optional[str] = None


class RecommendationCreateRequest(BaseModel):
    experiment_id: int
    notes: Optional[str] = None


class RecommendationReviewRequest(BaseModel):
    reviewed_by: str
    decision_reason: Optional[str] = None
    notes: Optional[str] = None
    supersede_open_others: bool = False


class PromotionCreateRequest(BaseModel):
    recommendation_id: int
    initiated_by: str
    notes: Optional[str] = None


class PromotionMonitoringRequest(BaseModel):
    notes: Optional[str] = None


class RollbackDecisionRequest(BaseModel):
    initiated_by: Optional[str] = None
    monitoring_id: Optional[int] = None
    notes: Optional[str] = None


class RollbackExecutionRequest(BaseModel):
    initiated_by: str
    notes: Optional[str] = None


class PolicyActionCreateRequest(BaseModel):
    source_type: str
    source_id: int
    verdict_status: str
    reason_codes: Optional[list] = None
    urgency: Optional[str] = None
    notes: Optional[str] = None


class PolicyActionResolveRequest(BaseModel):
    notes: Optional[str] = None


class IncidentCreateRequest(BaseModel):
    policy_action_id: int


class IncidentTransitionRequest(BaseModel):
    new_status: str
    operator: Optional[str] = None
    notes: Optional[str] = None


def _sanitize_openai_message(msg: str) -> str:
    # Never leak secret-like strings (API keys) to clients/logs.
    return re.sub(r"sk-[^\s]+", "sk-[REDACTED]", msg or "")


def _cached_demo_state(db: Session, force: bool = False) -> dict:
    """
    Cache DEMO state na krótki TTL, żeby nie mielić DB w UI (odświeżanie co 60s).
    """
    now = datetime.utcnow()
    ttl_seconds = int(os.getenv("ACCOUNT_STATE_CACHE_SECONDS", "5"))
    if not force and _demo_state_cache.get("ts") and _demo_state_cache.get("data"):
        age = (now - _demo_state_cache["ts"]).total_seconds()
        if age < ttl_seconds:
            return _demo_state_cache["data"]

    state = compute_demo_account_state(db, quote_ccy=get_demo_quote_ccy(), now=now)
    _demo_state_cache["ts"] = now
    _demo_state_cache["data"] = state
    return state


def _persist_demo_snapshot(db: Session, state: dict) -> AccountSnapshot:
    snap = AccountSnapshot(
        mode="demo",
        equity=float(state.get("equity") or 0.0),
        free_margin=float(state.get("cash") or 0.0),
        used_margin=0.0,
        margin_level=0.0,
        balance=float(state.get("cash") or 0.0),
        unrealized_pnl=float(state.get("unrealized_pnl") or 0.0),
        timestamp=datetime.utcnow(),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


@router.get("/summary")
async def get_account_summary(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz podsumowanie konta (Account Summary)
    - DEMO: symulowane dane
    - LIVE: rzeczywiste dane z Binance (read-only)
    """
    try:
        if mode == "demo":
            state = _cached_demo_state(db)
            cash = float(state.get("cash") or 0.0)
            data = {
                "mode": "demo",
                "quote_ccy": state.get("quote_ccy"),
                "equity": round(float(state.get("equity") or 0.0), 2),
                "free_margin": round(cash, 2),
                "used_margin": 0.0,
                "margin_level": 0.0,
                "balance": round(cash, 2),
                "unrealized_pnl": round(float(state.get("unrealized_pnl") or 0.0), 2),
                "cash": round(cash, 2),
                "positions_value": round(float(state.get("positions_value") or 0.0), 2),
                "realized_pnl_total": round(float(state.get("realized_pnl_total") or 0.0), 2),
                "realized_pnl_24h": round(float(state.get("realized_pnl_24h") or 0.0), 2),
                "roi": float(state.get("roi") or 0.0),
                "timestamp": state.get("timestamp") or datetime.utcnow().isoformat(),
                "positions": state.get("positions") or [],
            }
            return {"success": True, "data": data}
        
        elif mode == "live":
            # LIVE mode - pobierz z Binance (read-only)
            binance = get_binance_client()
            account = binance.get_account_info()
            if not account:
                raise HTTPException(
                    status_code=401,
                    detail="Brak kluczy API Binance lub błąd autoryzacji"
                )

            spot_balances = account.get("balances", [])
            stable_assets = {"USDT", "USDC", "BUSD"}
            spot_stable_total = sum(b["total"] for b in spot_balances if b["asset"] in stable_assets)

            simple_earn_account = binance.get_simple_earn_account() or {}
            simple_earn_flexible = binance.get_simple_earn_flexible_positions() or {}
            simple_earn_locked = binance.get_simple_earn_locked_positions() or {}
            earn_total = 0.0
            try:
                earn_total = float(simple_earn_account.get("totalAmount", 0) or 0)
            except Exception:
                earn_total = 0.0

            futures_balance = binance.get_futures_balance() or []
            futures_account = binance.get_futures_account() or {}
            futures_wallet_balance = 0.0
            try:
                for b in futures_balance:
                    if b.get("asset") == "USDT":
                        futures_wallet_balance = float(b.get("balance", 0))
                        break
            except Exception:
                futures_wallet_balance = 0.0

            total_equity = spot_stable_total + earn_total + futures_wallet_balance

            data = {
                "mode": "live",
                "equity": round(total_equity, 2),
                "free_margin": round(total_equity * 0.5, 2),
                "used_margin": round(total_equity * 0.5, 2),
                "margin_level": 200.0,
                "balance": round(spot_stable_total, 2),
                "unrealized_pnl": 0.0,
                "timestamp": datetime.utcnow().isoformat(),
                "balances": spot_balances[:10],
                "spot_stable_total": round(spot_stable_total, 2),
                "simple_earn_total": round(earn_total, 2),
                "futures_wallet_balance": round(futures_wallet_balance, 2),
                "futures_account": futures_account,
            }
            
            # Zapisz snapshot do bazy
            snapshot = AccountSnapshot(
                mode="live",
                equity=data["equity"],
                free_margin=data["free_margin"],
                used_margin=data["used_margin"],
                margin_level=data["margin_level"],
                balance=data["balance"],
                unrealized_pnl=data["unrealized_pnl"],
                timestamp=datetime.utcnow()
            )
            db.add(snapshot)
            db.commit()
            
            return {
                "success": True,
                "data": data
            }
        
        else:
            raise HTTPException(status_code=400, detail="Invalid mode. Use 'demo' or 'live'")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting account summary: {str(e)}")


@router.post("/reset")
async def reset_account_data(
    request: Request,
    scope: str = Query("full", description="full lub demo"),
    admin: None = Depends(require_admin),
):
    try:
        reset_database(scope=scope)
        collector = getattr(request.app.state, "collector", None)
        if collector is not None:
            try:
                collector.reset_demo_state()
            except Exception:
                pass
        return {"success": True, "scope": scope}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resetting database: {str(e)}")


@router.get("/openai-status")
async def get_openai_status(
    force: bool = Query(False, description="Jeśli true, pomija cache i wykonuje realny test"),
):
    """
    Sprawdza czy klucz OpenAI z `.env` działa (bez ujawniania klucza).
    Używane do szybkiej diagnostyki w UI.
    """
    # Key from env (dotenv loaded at app/collector startup). Trim for safety.
    api_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if (api_key.startswith('"') and api_key.endswith('"')) or (api_key.startswith("'") and api_key.endswith("'")):
        api_key = api_key[1:-1].strip()
    if not api_key:
        return {
            "success": True,
            "data": {
                "status": "missing",
                "http_status": None,
                "code": "missing_api_key",
                "message": "Brak OPENAI_API_KEY w `.env`.",
                "key_len": 0,
                "key_fingerprint": None,
            },
        }

    now = datetime.utcnow()
    ttl_seconds = int(os.getenv("OPENAI_STATUS_CACHE_SECONDS", "120"))
    if not force and _openai_status_cache.get("ts") and _openai_status_cache.get("data"):
        age = (now - _openai_status_cache["ts"]).total_seconds()
        if age < ttl_seconds:
            return {"success": True, "data": _openai_status_cache["data"]}

    try:
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        key_fp = hashlib.sha256(api_key.encode("utf-8", errors="ignore")).hexdigest()[:12]
        if resp.status_code < 400:
            data = {
                "status": "ok",
                "http_status": resp.status_code,
                "code": None,
                "message": "OK",
                "checked_at": now.isoformat(),
                "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
                "key_len": len(api_key),
                "key_fingerprint": key_fp,
            }
        else:
            code = "openai_error"
            msg = resp.text or ""
            try:
                payload = resp.json()
                err = (payload or {}).get("error") or {}
                code = err.get("code") or err.get("type") or code
                msg = str(err.get("message") or msg)
            except Exception:
                pass
            data = {
                "status": "error",
                "http_status": resp.status_code,
                "code": code,
                "message": _sanitize_openai_message(msg)[:240],
                "checked_at": now.isoformat(),
                "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
                "key_len": len(api_key),
                "key_fingerprint": key_fp,
            }

        _openai_status_cache["ts"] = now
        _openai_status_cache["data"] = data
        return {"success": True, "data": data}
    except Exception as exc:
        key_fp = hashlib.sha256(api_key.encode("utf-8", errors="ignore")).hexdigest()[:12]
        data = {
            "status": "error",
            "http_status": None,
            "code": "exception",
            "message": _sanitize_openai_message(str(exc))[:240],
            "checked_at": now.isoformat(),
            "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            "key_len": len(api_key),
            "key_fingerprint": key_fp,
        }
        _openai_status_cache["ts"] = now
        _openai_status_cache["data"] = data
        return {"success": True, "data": data}


@router.get("/history")
async def get_account_history(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    hours: int = Query(24, ge=1, le=168, description="Ile godzin wstecz (max 168 = tydzień)"),
    db: Session = Depends(get_db)
):
    """
    Pobierz historię equity/margin z ostatnich N godzin
    Do wykresów KPI
    """
    try:
        # Oblicz czas początkowy
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Pobierz snapshoty
        snapshots = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode,
            AccountSnapshot.timestamp >= since
        ).order_by(AccountSnapshot.timestamp).all()
        
        if not snapshots:
            if mode == "demo":
                state = _cached_demo_state(db)
                _persist_demo_snapshot(db, state)
                snapshots = db.query(AccountSnapshot).filter(
                    AccountSnapshot.mode == mode,
                    AccountSnapshot.timestamp >= since
                ).order_by(AccountSnapshot.timestamp).all()
            else:
                return {"success": True, "mode": mode, "data": [], "count": 0}
        
        # Formatuj dane
        history = []
        for snap in snapshots:
            history.append({
                "timestamp": snap.timestamp.isoformat(),
                "equity": snap.equity,
                "free_margin": snap.free_margin,
                "used_margin": snap.used_margin,
                "margin_level": snap.margin_level,
                "unrealized_pnl": snap.unrealized_pnl
            })
        
        return {
            "success": True,
            "mode": mode,
            "data": history,
            "count": len(history),
            "period_hours": hours
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting account history: {str(e)}")


@router.get("/kpi")
async def get_account_kpi(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Pobierz KPI konta (do dashboard)
    """
    try:
        # Pobierz aktualny snapshot
        latest = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode
        ).order_by(desc(AccountSnapshot.timestamp)).first()
        
        if not latest:
            if mode == "demo":
                state = _cached_demo_state(db)
                latest = _persist_demo_snapshot(db, state)
            else:
                raise HTTPException(status_code=404, detail="No account data found")
        
        # Pobierz snapshot sprzed 24h
        day_ago = datetime.utcnow() - timedelta(hours=24)
        prev = db.query(AccountSnapshot).filter(
            AccountSnapshot.mode == mode,
            AccountSnapshot.timestamp <= day_ago
        ).order_by(desc(AccountSnapshot.timestamp)).first()
        
        # Oblicz zmiany
        equity_change = 0
        equity_change_percent = 0
        if prev:
            equity_change = latest.equity - prev.equity
            equity_change_percent = (equity_change / prev.equity * 100) if prev.equity > 0 else 0
        
        kpi = {
            "equity": round(latest.equity, 2),
            "equity_change": round(equity_change, 2),
            "equity_change_percent": round(equity_change_percent, 2),
            "free_margin": round(latest.free_margin, 2),
            "used_margin": round(latest.used_margin, 2),
            "margin_level": round(latest.margin_level, 2),
            "unrealized_pnl": round(latest.unrealized_pnl, 2),
            "balance": round(latest.balance, 2),
            "timestamp": latest.timestamp.isoformat()
        }
        
        return {
            "success": True,
            "mode": mode,
            "data": kpi
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting KPI: {str(e)}")


@router.get("/risk")
async def get_risk_summary(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Podsumowanie ryzyka dla demo/live
    """
    try:
        risk = compute_risk_snapshot(db, mode=mode)
        return {
            "success": True,
            "mode": mode,
            "data": risk,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting risk summary: {str(e)}")


@router.get("/analytics/overview")
async def get_analytics_overview(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Cost-aware performance overview built on accounting/reporting source-of-truth.
    """
    try:
        return {
            "success": True,
            "mode": mode,
            "data": performance_overview(db, mode=mode),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting analytics overview: {str(e)}")


@router.get("/analytics/risk-effectiveness")
async def get_risk_effectiveness(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Reporting view of risk gate effectiveness and protective actions.
    """
    try:
        return {
            "success": True,
            "mode": mode,
            "data": risk_effectiveness_report(db, mode=mode),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting risk effectiveness analytics: {str(e)}")


@router.get("/analytics")
async def get_analytics_bundle(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Unified analytics payload for dashboards and audit tooling.
    """
    try:
        return {
            "success": True,
            "mode": mode,
            "data": analytics_bundle(db, mode=mode),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting analytics bundle: {str(e)}")


@router.get("/analytics/config-snapshots/compare")
async def compare_config_snapshot_payloads(
    snapshot_a: str,
    snapshot_b: str,
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "mode": mode,
            "data": config_snapshot_compare_report(db, snapshot_a, snapshot_b, mode=mode),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing config snapshots: {str(e)}")


@router.get("/analytics/config-snapshots/{snapshot_id}")
async def get_config_snapshot_payload(
    snapshot_id: str,
    db: Session = Depends(get_db),
):
    try:
        payload = config_snapshot_payload_report(db, snapshot_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Config snapshot not found")
        return {
            "success": True,
            "data": payload,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting config snapshot payload: {str(e)}")


@router.get("/analytics/experiments/compare")
async def compare_experiment_variants(
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    mode: str = Query("demo", description="Tryb: demo lub live"),
    symbol: Optional[str] = Query(None),
    strategy_name: Optional[str] = Query(None),
    start_at: Optional[str] = Query(None),
    end_at: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": compare_snapshots_for_experiment(
                db,
                baseline_snapshot_id=baseline_snapshot_id,
                candidate_snapshot_id=candidate_snapshot_id,
                mode=mode,
                symbol=symbol,
                strategy_name=strategy_name,
                start_at=datetime.fromisoformat(start_at) if start_at else None,
                end_at=datetime.fromisoformat(end_at) if end_at else None,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error comparing experiment variants: {str(e)}")


@router.get("/analytics/experiments")
async def get_experiments(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_experiments(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing experiments: {str(e)}")


@router.get("/analytics/experiments/{experiment_id}")
async def get_experiment_by_id(
    experiment_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_experiment(db, experiment_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting experiment: {str(e)}")


@router.post("/analytics/experiments")
async def create_experiment_endpoint(
    payload: ExperimentCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        result = create_experiment(
            db,
            name=payload.name,
            description=payload.description,
            baseline_snapshot_id=payload.baseline_snapshot_id,
            candidate_snapshot_id=payload.candidate_snapshot_id,
            mode=payload.mode,
            scope=payload.scope,
            symbol=payload.symbol,
            strategy_name=payload.strategy_name,
            start_at=payload.start_at,
            end_at=payload.end_at,
            notes=payload.notes,
        )
        return {"success": True, "data": result}
    except PipelineFreezeError as exc:
        raise HTTPException(status_code=403, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating experiment: {str(e)}")


@router.get("/analytics/recommendations")
async def get_recommendations(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_recommendations(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing recommendations: {str(e)}")


@router.get("/analytics/recommendations/overview")
async def get_recommendations_overview(
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": {
                "overview": recommendation_overview(db),
                "pending_experiments": pending_recommendation_candidates(db),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendation overview: {str(e)}")


@router.get("/analytics/recommendations/review-queue")
async def get_recommendation_review_queue(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_review_queue(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendation review queue: {str(e)}")


@router.post("/analytics/recommendations")
async def create_recommendation_endpoint(
    payload: RecommendationCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": generate_recommendation(db, payload.experiment_id, notes=payload.notes),
        }
    except PipelineFreezeError as exc:
        raise HTTPException(status_code=403, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating recommendation: {str(e)}")


@router.get("/analytics/recommendations/{recommendation_id}")
async def get_recommendation_by_id(
    recommendation_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_recommendation(db, recommendation_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendation: {str(e)}")


@router.get("/analytics/recommendations/{recommendation_id}/review")
async def get_recommendation_review_bundle(
    recommendation_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": review_bundle(db, recommendation_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendation review bundle: {str(e)}")


def _apply_review_http(
    db: Session,
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    action: str,
) -> Dict[str, Any]:
    return apply_review_decision(
        db,
        recommendation_id=recommendation_id,
        action=action,
        reviewed_by=payload.reviewed_by,
        decision_reason=payload.decision_reason,
        notes=payload.notes,
        supersede_open_others=payload.supersede_open_others,
    )


@router.post("/analytics/recommendations/{recommendation_id}/start-review")
async def start_recommendation_review(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": _apply_review_http(db, recommendation_id, payload, "start_review")}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting recommendation review: {str(e)}")


@router.post("/analytics/recommendations/{recommendation_id}/approve")
async def approve_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": _apply_review_http(db, recommendation_id, payload, "approve")}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving recommendation: {str(e)}")


@router.post("/analytics/recommendations/{recommendation_id}/reject")
async def reject_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": _apply_review_http(db, recommendation_id, payload, "reject")}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting recommendation: {str(e)}")


@router.post("/analytics/recommendations/{recommendation_id}/defer")
async def defer_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": _apply_review_http(db, recommendation_id, payload, "defer")}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deferring recommendation: {str(e)}")


@router.get("/analytics/promotions")
async def get_config_promotions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_promotions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing promotions: {str(e)}")


@router.get("/analytics/promotions/{promotion_id}")
async def get_config_promotion_by_id(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_promotion(db, promotion_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting promotion: {str(e)}")


@router.post("/analytics/promotions")
async def create_config_promotion(
    payload: PromotionCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": promote_recommendation(
                db,
                recommendation_id=payload.recommendation_id,
                initiated_by=payload.initiated_by,
                notes=payload.notes,
            ),
        }
    except PipelineFreezeError as exc:
        raise HTTPException(status_code=403, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating promotion: {str(e)}")


@router.get("/analytics/promotion-monitoring")
async def get_promotion_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing promotion monitoring records: {str(e)}")


@router.get("/analytics/promotion-monitoring/{monitoring_id}")
async def get_promotion_monitoring_record(
    monitoring_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_monitoring_record(db, monitoring_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting promotion monitoring record: {str(e)}")


@router.get("/analytics/promotions/{promotion_id}/monitoring")
async def get_monitoring_verdict_for_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_monitoring_by_promotion(db, promotion_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting promotion monitoring verdict: {str(e)}")


@router.post("/analytics/promotions/{promotion_id}/monitoring/evaluate")
async def evaluate_promotion_monitoring(
    promotion_id: int,
    payload: PromotionMonitoringRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": evaluate_monitoring(db, promotion_id, notes=payload.notes)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating promotion monitoring: {str(e)}")


@router.get("/analytics/rollbacks")
async def get_rollback_decisions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_decisions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing rollback decisions: {str(e)}")


@router.get("/analytics/rollbacks/{rollback_id}")
async def get_rollback_decision_by_id(
    rollback_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_rollback_decision(db, rollback_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting rollback decision: {str(e)}")


@router.get("/analytics/promotions/{promotion_id}/rollback-decision")
async def get_latest_rollback_decision_for_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": latest_rollback_decision_for_promotion(db, promotion_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting rollback decision for promotion: {str(e)}")


@router.post("/analytics/promotions/{promotion_id}/rollback-decision")
async def create_promotion_rollback_decision(
    promotion_id: int,
    payload: RollbackDecisionRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": create_rollback_decision(
                db,
                promotion_id=promotion_id,
                initiated_by=payload.initiated_by,
                monitoring_id=payload.monitoring_id,
                notes=payload.notes,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating rollback decision: {str(e)}")


@router.get("/analytics/rollback-executions")
async def get_rollback_execution_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_executions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing rollback executions: {str(e)}")


@router.get("/analytics/rollback-executions/{rollback_id}")
async def get_rollback_execution_record(
    rollback_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_rollback_execution(db, rollback_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting rollback execution: {str(e)}")


@router.post("/analytics/rollbacks/{rollback_id}/execute")
async def execute_rollback_decision(
    rollback_id: int,
    payload: RollbackExecutionRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": execute_rollback(
                db,
                rollback_id=rollback_id,
                initiated_by=payload.initiated_by,
                notes=payload.notes,
            ),
        }
    except PipelineFreezeError as exc:
        raise HTTPException(status_code=403, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error executing rollback: {str(e)}")


@router.get("/analytics/post-rollback-monitoring")
async def get_post_rollback_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_post_rollback_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing post-rollback monitoring records: {str(e)}")


@router.get("/analytics/post-rollback-monitoring/{monitoring_id}")
async def get_post_rollback_monitoring_record_by_id(
    monitoring_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_post_rollback_monitoring_record(db, monitoring_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting post-rollback monitoring record: {str(e)}")


@router.get("/analytics/rollbacks/{rollback_id}/post-monitoring")
async def get_post_rollback_monitoring_for_rollback(
    rollback_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_post_rollback_monitoring_by_rollback(db, rollback_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting post-rollback monitoring verdict: {str(e)}")


@router.post("/analytics/rollbacks/{rollback_id}/post-monitoring/evaluate")
async def evaluate_rollback_post_monitoring(
    rollback_id: int,
    payload: PromotionMonitoringRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": evaluate_post_rollback_monitoring(db, rollback_id, notes=payload.notes)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error evaluating post-rollback monitoring: {str(e)}")


@router.get("/system-logs")
async def get_system_logs(
    limit: int = Query(50, ge=1, le=200, description="Ile wpisów (max 200)"),
    level: Optional[str] = Query(None, description="Filtr poziomu: INFO/WARNING/ERROR"),
    module: Optional[str] = Query(None, description="Filtr modułu (np. analysis, collector)"),
    db: Session = Depends(get_db),
):
    """
    Pobierz ostatnie logi systemowe z bazy (SystemLog).
    Pomaga diagnozować np. problemy z OpenAI/Binance.
    """
    try:
        query = db.query(SystemLog)
        if level:
            query = query.filter(SystemLog.level == level.upper())
        if module:
            query = query.filter(SystemLog.module == module)

        logs = query.order_by(desc(SystemLog.timestamp)).limit(limit).all()
        data = [
            {
                "id": l.id,
                "level": l.level,
                "module": l.module,
                "message": l.message,
                "exception": l.exception,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            }
            for l in logs
        ]
        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting system logs: {str(e)}")


# ---------------------------------------------------------------------------
# Policy Actions
# ---------------------------------------------------------------------------


@router.get("/analytics/policy-actions")
async def get_policy_actions_list(
    status: Optional[str] = Query(None, description="Filtr statusu: open, resolved, superseded"),
    source_type: Optional[str] = Query(None, description="Filtr źródła: promotion_monitoring, rollback_decision, rollback_monitoring"),
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_policy_actions(db, status=status, source_type=source_type)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania policy actions: {str(e)}")


@router.get("/analytics/policy-actions/active")
async def get_active_policy_actions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_active_policy_actions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania aktywnych policy actions: {str(e)}")


@router.get("/analytics/policy-actions/summary")
async def get_policy_actions_summary(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": policy_actions_summary(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania podsumowania policy actions: {str(e)}")


@router.get("/analytics/policy-actions/{policy_action_id}")
async def get_policy_action_by_id(
    policy_action_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_policy_action(db, policy_action_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania policy action: {str(e)}")


@router.post("/analytics/policy-actions")
async def create_policy_action_endpoint(
    payload: PolicyActionCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": create_policy_action(
                db,
                source_type=payload.source_type,
                source_id=payload.source_id,
                verdict_status=payload.verdict_status,
                reason_codes=payload.reason_codes,
                urgency=payload.urgency,
                notes=payload.notes,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd tworzenia policy action: {str(e)}")


@router.post("/analytics/policy-actions/{policy_action_id}/resolve")
async def resolve_policy_action_endpoint(
    policy_action_id: int,
    payload: PolicyActionResolveRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": resolve_policy_action(db, policy_action_id, notes=payload.notes),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd rozwiązywania policy action: {str(e)}")


# ---------------------------------------------------------------------------
# Governance / Operator Workflow
# ---------------------------------------------------------------------------


@router.get("/analytics/pipeline-status")
async def get_pipeline_status_endpoint(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_pipeline_status(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania pipeline status: {str(e)}")


@router.get("/analytics/pipeline-permission/{operation}")
async def check_pipeline_permission_endpoint(
    operation: str,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": check_pipeline_permission(db, operation)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd sprawdzania uprawnień: {str(e)}")


@router.get("/analytics/operator-queue")
async def get_operator_queue_endpoint(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_operator_queue(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania kolejki operatora: {str(e)}")


@router.get("/analytics/incidents")
async def list_incidents_endpoint(
    status: Optional[str] = Query(None, description="Filtr statusu: open, acknowledged, in_progress, escalated, resolved"),
    priority: Optional[str] = Query(None, description="Filtr priorytetu: critical, high, medium, low"),
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_incidents(db, status=status, priority=priority)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania incydentów: {str(e)}")


@router.get("/analytics/incidents/{incident_id}")
async def get_incident_endpoint(
    incident_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_incident(db, incident_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania incydentu: {str(e)}")


@router.post("/analytics/incidents")
async def create_incident_endpoint(
    payload: IncidentCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {"success": True, "data": create_incident(db, policy_action_id=payload.policy_action_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd tworzenia incydentu: {str(e)}")


@router.post("/analytics/incidents/{incident_id}/transition")
async def transition_incident_endpoint(
    incident_id: int,
    payload: IncidentTransitionRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": transition_incident(
                db,
                incident_id,
                new_status=payload.new_status,
                operator=payload.operator,
                notes=payload.notes,
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd przejścia incydentu: {str(e)}")


@router.post("/analytics/incidents/escalate-overdue")
async def escalate_overdue_endpoint(
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        escalated = escalate_overdue_incidents(db)
        return {"success": True, "escalated_count": len(escalated), "data": escalated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd eskalacji: {str(e)}")


# =====================================================================
# Notification hooks
# =====================================================================

@router.get("/analytics/notifications/config")
async def get_notification_config():
    """Aktualny stan konfiguracji powiadomień (bez wrażliwych danych)."""
    cfg = _get_notification_config()
    return {
        "success": True,
        "data": {
            "enabled": cfg["enabled"],
            "telegram_configured": bool(cfg["telegram_bot_token"] and cfg["telegram_chat_id"]),
            "telegram_min_priority": cfg["telegram_min_priority"],
        },
    }


class TestNotificationRequest(BaseModel):
    message: str = "Test powiadomienia z RLdC Trading Bot"


@router.post("/analytics/notifications/test")
async def test_notification(
    payload: TestNotificationRequest,
    admin: None = Depends(require_admin),
):
    """Wyślij testowe powiadomienie (do weryfikacji konfiguracji Telegram)."""
    result = dispatch_notification("test", payload.message, priority="high")
    return {"success": True, "data": result}


# =====================================================================
# ============ REEVALUATION WORKER ====================================
# =====================================================================

@router.get("/analytics/worker/status")
async def worker_status():
    """Aktualny stan reevaluation workera."""
    return {"success": True, "data": get_worker_status()}


@router.post("/analytics/worker/cycle")
async def worker_manual_cycle(
    admin: None = Depends(require_admin),
):
    """Ręcznie uruchom jeden cykl reewaluacji (debug / test)."""
    summary = run_worker_cycle()
    return {"success": True, "data": summary}
