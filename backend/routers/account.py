"""
Account API Router - endpoints dla danych konta (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone
import os
import re
import requests
import hashlib

from backend.database import get_db, AccountSnapshot, Position, SystemLog, MarketData, Order, CostLedger, PendingOrder, RuntimeSetting, DecisionTrace, reset_database, utc_now_naive
from backend.binance_client import get_binance_client
from backend.accounting import compute_demo_account_state, compute_risk_snapshot, get_demo_quote_ccy
from backend.routers.portfolio import _build_live_spot_portfolio
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
from backend.operator_console import (
    get_console_section,
    get_operator_console,
)
from backend.correlation import (
    get_incident_correlations,
    get_incident_timeline,
    get_policy_action_chain,
    get_promotion_chain,
    get_why_blocked,
)
from backend.trading_effectiveness import (
    effectiveness_bundle,
    exit_quality_report,
    symbol_effectiveness,
    reason_code_effectiveness,
    strategy_effectiveness,
)
from backend.tuning_insights import generate_tuning_candidates, tuning_summary
from backend.candidate_validation import generate_experiment_feed, experiment_feed_summary
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
    now = utc_now_naive()
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
        timestamp=utc_now_naive(),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


@router.get("/summary")
def get_account_summary(
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
                "timestamp": state.get("timestamp") or utc_now_naive().isoformat(),
                "positions": state.get("positions") or [],
            }
            return {"success": True, "data": data}
        
        elif mode == "live":
            # LIVE mode - pobierz z Binance (read-only)
            _binance_err: Optional[str] = None
            try:
                binance = get_binance_client()
                account = binance.get_account_info()
            except Exception as _be:
                account = None
                _binance_err = str(_be)
            if not account:
                return {
                    "success": True,
                    "data": {
                        "mode": "live",
                        "equity": 0.0,
                        "balance": 0.0,
                        "free_margin": 0.0,
                        "used_margin": 0.0,
                        "margin_level": 0.0,
                        "unrealized_pnl": 0.0,
                        "cash": 0.0,
                        "positions_value": 0.0,
                        "realized_pnl_total": 0.0,
                        "realized_pnl_24h": 0.0,
                        "roi": 0.0,
                        "positions": [],
                        "timestamp": utc_now_naive().isoformat(),
                        "_info": (
                            f"Binance API niedostępne ({_binance_err}). "
                            if _binance_err else
                            "Binance API niedostępne. "
                        ) + "Ustaw BINANCE_API_KEY i BINANCE_SECRET_KEY w .env",
                    }
                }

            spot_balances = account.get("balances", [])

            # ── przelicz wszystkie aktywa spot na EUR ──────────────────────
            spot_data = _build_live_spot_portfolio(db)
            total_equity = spot_data.get("total_equity_eur", 0.0)
            free_cash_eur = spot_data.get("free_cash_eur", 0.0)
            spot_positions = spot_data.get("spot_positions", [])
            unpriced = spot_data.get("unpriced_assets", [])

            # earn + futures (opcjonalne, dokładają do equity)
            simple_earn_account = binance.get_simple_earn_account() or {}
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
            eur_per_usdt = spot_data.get("eur_per_usdt") or 1.0
            total_equity += round(
                (earn_total + futures_wallet_balance) * eur_per_usdt, 2
            )

            data = {
                "mode": "live",
                "equity": round(total_equity, 2),
                "free_margin": round(free_cash_eur, 2),
                "used_margin": round(total_equity - free_cash_eur, 2),
                "margin_level": 200.0,
                "balance": round(total_equity, 2),
                "unrealized_pnl": 0.0,
                "timestamp": utc_now_naive().isoformat(),
                "balances": spot_balances[:15],
                "spot_positions": spot_positions,
                "unpriced_assets": unpriced,
                "spot_equity_eur": round(spot_data.get("total_equity_eur", 0.0), 2),
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
                timestamp=utc_now_naive()
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
def reset_account_data(
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
def get_openai_status(
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

    now = utc_now_naive()
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


@router.get("/ai-status")
def get_ai_status():
    """
    Status wszystkich skonfigurowanych providerów AI.
    Szybka diagnostyka w UI — który provider jest aktywny.
    """
    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()

    def _check_key(env_name: str) -> dict:
        key = (os.getenv(env_name, "") or "").strip()
        return {"configured": bool(key), "key_len": len(key) if key else 0}

    providers = {
        "ollama": {
            "configured": bool((os.getenv("OLLAMA_BASE_URL", "") or "").strip()),
            "key_len": 0,
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
            "docs": "https://ollama.com/download (lokalne, bez klucza)",
        },
        "gemini": {
            **_check_key("GEMINI_API_KEY"),
            "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            "docs": "https://aistudio.google.com/apikey",
        },
        "groq": {
            **_check_key("GROQ_API_KEY"),
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "docs": "https://console.groq.com/keys",
        },
        "openai": {
            **_check_key("OPENAI_API_KEY"),
            "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            "docs": "https://platform.openai.com/api-keys",
        },
    }

    # W trybie auto, kolejność prób
    if provider == "auto":
        chain = ["ollama", "gemini", "groq", "openai", "heuristic"]
    elif provider in ("heuristic", "offline"):
        chain = ["heuristic"]
    else:
        chain = [provider, "heuristic"]

    active = "heuristic"
    for p in chain:
        if p != "heuristic" and providers.get(p, {}).get("configured"):
            active = p
            break

    return {
        "success": True,
        "data": {
            "ai_provider_setting": provider,
            "active_provider": active,
            "fallback_chain": chain,
            "providers": providers,
            "heuristic": "ATR + Bollinger (zawsze dostępna)",
        },
    }


@router.get("/history")
def get_account_history(
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
        since = utc_now_naive() - timedelta(hours=hours)
        
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
def get_account_kpi(
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
                # Tryb LIVE bez danych — zwracamy HTTP 200 z bezpiecznym fallbackiem
                return {
                    "success": True,
                    "mode": mode,
                    "data": {
                        "equity": 0.0,
                        "equity_change": 0.0,
                        "equity_change_percent": 0.0,
                        "free_margin": 0.0,
                        "used_margin": 0.0,
                        "margin_level": 0.0,
                        "unrealized_pnl": 0.0,
                        "balance": 0.0,
                        "timestamp": utc_now_naive().isoformat()
                    },
                    "_info": "Brak danych live z Binance. Synchronizacja konta nieaktywna.",
                    "source": "fallback",
                    "stale": True
                }
        
        # Pobierz snapshot sprzed 24h
        day_ago = utc_now_naive() - timedelta(hours=24)
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
def get_risk_summary(
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
def get_analytics_overview(
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
def get_risk_effectiveness(
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
def get_analytics_bundle(
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
def compare_config_snapshot_payloads(
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
def get_config_snapshot_payload(
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
def compare_experiment_variants(
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
def get_experiments(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_experiments(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing experiments: {str(e)}")


@router.get("/analytics/experiments/{experiment_id}")
def get_experiment_by_id(
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
def create_experiment_endpoint(
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
def get_recommendations(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_recommendations(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing recommendations: {str(e)}")


@router.get("/analytics/recommendations/overview")
def get_recommendations_overview(
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
def get_recommendation_review_queue(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_review_queue(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting recommendation review queue: {str(e)}")


@router.post("/analytics/recommendations")
def create_recommendation_endpoint(
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
def get_recommendation_by_id(
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
def get_recommendation_review_bundle(
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
def start_recommendation_review(
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
def approve_recommendation(
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
def reject_recommendation(
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
def defer_recommendation(
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
def get_config_promotions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_promotions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing promotions: {str(e)}")


@router.get("/analytics/promotions/{promotion_id}")
def get_config_promotion_by_id(
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
def create_config_promotion(
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
def get_promotion_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing promotion monitoring records: {str(e)}")


@router.get("/analytics/promotion-monitoring/{monitoring_id}")
def get_promotion_monitoring_record(
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
def get_monitoring_verdict_for_promotion(
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
def evaluate_promotion_monitoring(
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
def get_rollback_decisions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_decisions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing rollback decisions: {str(e)}")


@router.get("/analytics/rollbacks/{rollback_id}")
def get_rollback_decision_by_id(
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
def get_latest_rollback_decision_for_promotion(
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
def create_promotion_rollback_decision(
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
def get_rollback_execution_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_executions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing rollback executions: {str(e)}")


@router.get("/analytics/rollback-executions/{rollback_id}")
def get_rollback_execution_record(
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
def execute_rollback_decision(
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
def get_post_rollback_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_post_rollback_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing post-rollback monitoring records: {str(e)}")


@router.get("/analytics/post-rollback-monitoring/{monitoring_id}")
def get_post_rollback_monitoring_record_by_id(
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
def get_post_rollback_monitoring_for_rollback(
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
def evaluate_rollback_post_monitoring(
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
def get_system_logs(
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
def get_policy_actions_list(
    status: Optional[str] = Query(None, description="Filtr statusu: open, resolved, superseded"),
    source_type: Optional[str] = Query(None, description="Filtr źródła: promotion_monitoring, rollback_decision, rollback_monitoring"),
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_policy_actions(db, status=status, source_type=source_type)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania policy actions: {str(e)}")


@router.get("/analytics/policy-actions/active")
def get_active_policy_actions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_active_policy_actions(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania aktywnych policy actions: {str(e)}")


@router.get("/analytics/policy-actions/summary")
def get_policy_actions_summary(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": policy_actions_summary(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania podsumowania policy actions: {str(e)}")


@router.get("/analytics/policy-actions/{policy_action_id}")
def get_policy_action_by_id(
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
def create_policy_action_endpoint(
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
def resolve_policy_action_endpoint(
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
def get_pipeline_status_endpoint(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_pipeline_status(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania pipeline status: {str(e)}")


@router.get("/analytics/pipeline-permission/{operation}")
def check_pipeline_permission_endpoint(
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
def get_operator_queue_endpoint(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": get_operator_queue(db)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania kolejki operatora: {str(e)}")


@router.get("/analytics/incidents")
def list_incidents_endpoint(
    status: Optional[str] = Query(None, description="Filtr statusu: open, acknowledged, in_progress, escalated, resolved"),
    priority: Optional[str] = Query(None, description="Filtr priorytetu: critical, high, medium, low"),
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_incidents(db, status=status, priority=priority)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd pobierania incydentów: {str(e)}")


@router.get("/analytics/incidents/{incident_id}")
def get_incident_endpoint(
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
def create_incident_endpoint(
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
def transition_incident_endpoint(
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
def escalate_overdue_endpoint(
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
def get_notification_config():
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
def test_notification(
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
def worker_status():
    """Aktualny stan reevaluation workera."""
    return {"success": True, "data": get_worker_status()}


@router.post("/analytics/worker/cycle")
def worker_manual_cycle(
    admin: None = Depends(require_admin),
):
    """Ręcznie uruchom jeden cykl reewaluacji (debug / test)."""
    summary = run_worker_cycle()
    return {"success": True, "data": summary}


# =====================================================================
# ============ OPERATOR CONSOLE =======================================
# =====================================================================

@router.get("/analytics/console")
def operator_console_bundle(db: Session = Depends(get_db)):
    """Pełny zagregowany widok konsoli operatora — jeden endpoint, pełny obraz."""
    data = get_operator_console(db)
    return {"success": True, "data": data}


@router.get("/analytics/console/{section}")
def operator_console_section(
    section: str,
    db: Session = Depends(get_db),
):
    """Pojedyncza sekcja konsoli operatora (np. incidents, pipeline_status)."""
    try:
        data = get_console_section(db, section)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "section": section, "data": data}


# =====================================================================
# ============ CORRELATION / INCIDENT INTELLIGENCE ====================
# =====================================================================

@router.get("/analytics/incidents/{incident_id}/timeline")
def incident_timeline(
    incident_id: int,
    db: Session = Depends(get_db),
):
    """Oś czasu incydentu — pełny łańcuch przyczynowy od monitoringu do notyfikacji."""
    try:
        data = get_incident_timeline(db, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "data": data}


@router.get("/analytics/incidents/{incident_id}/correlations")
def incident_correlations(
    incident_id: int,
    db: Session = Depends(get_db),
):
    """Skorelowane encje dla incydentu (policy action, monitoring, promotion, rollback)."""
    try:
        data = get_incident_correlations(db, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "data": data}


@router.get("/analytics/policy-actions/{pa_id}/chain")
def policy_action_chain(
    pa_id: int,
    db: Session = Depends(get_db),
):
    """\u0141a\u0144cuch zdarze\u0144 powi\u0105zanych z policy action."""
    try:
        data = get_policy_action_chain(db, pa_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "data": data}


@router.get("/analytics/promotions/{promotion_id}/chain")
def promotion_chain(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    """Pełny lifecycle promocji — od inicjacji przez monitoring do rollbacku."""
    try:
        data = get_promotion_chain(db, promotion_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "data": data}


@router.get("/analytics/why-blocked/{operation}")
def why_blocked(
    operation: str,
    db: Session = Depends(get_db),
):
    """Wyja\u015bnij dlaczego operacja jest zablokowana (pe\u0142ny \u0142a\u0144cuch przyczynowy)."""
    try:
        data = get_why_blocked(db, operation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "data": data}


# =====================================================================
# ============ TRADING EFFECTIVENESS REVIEW ===========================
# =====================================================================

@router.get("/analytics/trading-effectiveness")
def trading_effectiveness(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Pełny raport skuteczności tradingu — summary, symbole, strategie, koszty, sugestie."""
    data = effectiveness_bundle(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/trading-effectiveness/symbols")
def trading_effectiveness_symbols(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Skuteczność per symbol — które zarabiają netto, które przepalają."""
    data = symbol_effectiveness(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/trading-effectiveness/reasons")
def trading_effectiveness_reasons(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Skuteczność per entry reason code — które wejścia tracą po kosztach."""
    data = reason_code_effectiveness(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/trading-effectiveness/strategies")
def trading_effectiveness_strategies(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Skuteczność per strategia — expectancy, edge gap, cost leakage."""
    data = strategy_effectiveness(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/exit-quality")
def get_exit_quality(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Jakość wyjść z pozycji — gave_back, TP/SL hit rate, RR, edge vs cost."""
    data = exit_quality_report(db, mode=mode)
    return {"success": True, "data": data}


# ============ TUNING INSIGHTS (ETAP Y) ============


@router.get("/analytics/tuning-insights")
def tuning_insights_candidates(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Pełna lista kandydatów zmian parametrów — pomost diagnostyka → tuning."""
    data = generate_tuning_candidates(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/tuning-insights/summary")
def tuning_insights_summary(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Skrócone podsumowanie + top 5 akcji do podjęcia."""
    data = tuning_summary(db, mode=mode)
    return {"success": True, "data": data}


# ============ CANDIDATE VALIDATION / EXPERIMENT FEED (ETAP Z) ============


@router.get("/analytics/experiment-feed")
def experiment_feed(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Pełny pipeline: kandydaci → klasyfikacja → konflikty → paczki eksperymentalne."""
    data = generate_experiment_feed(db, mode=mode)
    return {"success": True, "data": data}


@router.get("/analytics/experiment-feed/summary")
def experiment_feed_summary_endpoint(
    mode: str = "demo",
    db: Session = Depends(get_db),
):
    """Skrót: ile paczek gotowych, ile konfliktów, ile czeka na dane."""
    data = experiment_feed_summary(db, mode=mode)
    return {"success": True, "data": data}


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM STATUS — stan kolektora, danych, połączeń
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/system-status")
def get_system_status(request: Request, db: Session = Depends(get_db)):
    """
    Diagnostyka systemu: czy collector działa, kiedy ostatni tick, ile symboli,
    czy WS aktywny, czy Binance dostępny.
    """
    try:
        collector = getattr(request.app.state, "collector", None)

        collector_running = False
        ws_running = False
        watchlist: list = []
        if collector is not None:
            collector_running = getattr(collector, "running", False)
            ws_running = getattr(collector, "ws_running", False)
            watchlist = getattr(collector, "watchlist", []) or []

        last_md = (
            db.query(MarketData)
            .order_by(desc(MarketData.timestamp))
            .first()
        )
        last_tick_ts = last_md.timestamp.isoformat() if last_md else None
        last_tick_age_s = None
        data_stale = True
        if last_md:
            age = (utc_now_naive() - last_md.timestamp).total_seconds()
            last_tick_age_s = int(age)
            data_stale = age > 180

        symbols_with_data = db.query(MarketData.symbol).distinct().count()

        last_snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == "demo")
            .order_by(desc(AccountSnapshot.timestamp))
            .first()
        )
        last_snapshot_ts = last_snap.timestamp.isoformat() if last_snap else None

        last_error = (
            db.query(SystemLog)
            .filter(SystemLog.level == "ERROR")
            .order_by(desc(SystemLog.timestamp))
            .first()
        )
        last_error_msg = last_error.message[:120] if last_error else None
        last_error_ts = last_error.timestamp.isoformat() if last_error else None

        return {
            "success": True,
            "data": {
                "collector_running": collector_running,
                "ws_running": ws_running,
                "watchlist": watchlist,
                "watchlist_count": len(watchlist),
                "symbols_with_data": symbols_with_data,
                "last_tick_ts": last_tick_ts,
                "last_tick_age_s": last_tick_age_s,
                "data_stale": data_stale,
                "last_snapshot_ts": last_snapshot_ts,
                "last_error_msg": last_error_msg,
                "last_error_ts": last_error_ts,
                "timestamp": utc_now_naive().isoformat(),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting system status: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# DEMO RESET — zeruje demo i ustawia nowy kapitał startowy
# ─────────────────────────────────────────────────────────────────────────────

class DemoResetRequest(BaseModel):
    starting_balance: float = 500.0


@router.post("/demo/reset-balance")
def reset_demo_balance(
    request: Request,
    body: DemoResetRequest,
    db: Session = Depends(get_db),
):
    """
    Resetuje konto demo: zamyka pozycje demo, usuwa snapshoty i tworzy nowy
    snapshot startowy z zadanym kapitałem (domyślnie 500 EUR).
    """
    try:
        if body.starting_balance <= 0 or body.starting_balance > 100_000:
            raise HTTPException(status_code=400, detail="Kapitał startowy musi być między 1 a 100 000 EUR")

        # 1) Usuń pozycje demo
        demo_positions = db.query(Position).filter(Position.mode == "demo").all()
        positions_count = len(demo_positions)
        for pos in demo_positions:
            db.delete(pos)

        # 2) Usuń WSZYSTKIE zlecenia demo (replay historii dawał stary stan)
        demo_orders = db.query(Order).filter(Order.mode == "demo").all()
        orders_count = len(demo_orders)
        for order in demo_orders:
            db.query(CostLedger).filter(CostLedger.order_id == order.id).delete()
        for order in demo_orders:
            db.delete(order)

        # 3) Usuń oczekujące zlecenia demo
        db.query(PendingOrder).filter(PendingOrder.mode == "demo").delete()

        # 4) Usuń stare snapshoty demo
        db.query(AccountSnapshot).filter(AccountSnapshot.mode == "demo").delete()

        # 5) Zapisz nową wartość początkową jako override w DB
        ib_row = db.query(RuntimeSetting).filter(RuntimeSetting.key == "demo_initial_balance").first()
        if ib_row is None:
            db.add(RuntimeSetting(key="demo_initial_balance", value=str(body.starting_balance), updated_at=utc_now_naive()))
        else:
            ib_row.value = str(body.starting_balance)
            ib_row.updated_at = utc_now_naive()

        snap = AccountSnapshot(
            mode="demo",
            equity=body.starting_balance,
            balance=body.starting_balance,
            free_margin=body.starting_balance,
            used_margin=0.0,
            margin_level=100.0,
            unrealized_pnl=0.0,
            timestamp=utc_now_naive(),
        )
        db.add(snap)
        db.commit()

        collector = getattr(request.app.state, "collector", None)
        if collector is not None:
            try:
                collector.reset_demo_state()
            except Exception:
                pass

        return {
            "success": True,
            "message": f"Demo zresetowane. Kapitał startowy: {body.starting_balance} EUR",
            "starting_balance": body.starting_balance,
            "positions_closed": positions_count,
            "orders_deleted": orders_count,
            "timestamp": utc_now_naive().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resetting demo: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# BOT ACTIVITY — aktywność bota w ostatnich N minutach
# ─────────────────────────────────────────────────────────────────────────────

_REASON_PL: dict[str, str] = {
    "all_gates_passed":                   "Wszystkie filtry OK — zlecenie złożone",
    "pending_confirmed_execution":         "Zlecenie wykonane",
    "signal_confidence_too_low":           "Pewność sygnału poniżej progu",
    "signal_filters_not_met":              "Filtry techniczne (EMA/RSI) niezaliczone",
    "active_pending_exists":               "Mamy otwarte zlecenie dla tego symbolu",
    "buy_blocked_existing_position":       "Już mamy otwartą pozycję BUY",
    "symbol_not_in_any_tier":              "Symbol nie jest w żadnym tierze",
    "hold_mode_no_new_entries":            "Symbol w trybie HOLD — nie otwieramy nowych",
    "symbol_cooldown_active":              "Cooldown po ostatniej transakcji",
    "insufficient_cash_or_qty_below_min": "Za mało gotówki lub ilość poniżej minimum",
    "cost_gate_failed":                    "Koszty transakcji zbyt wysokie vs oczekiwany zysk",
    "max_open_positions_gate":             "Osiągnięto limit otwartych pozycji",
    "pending_cooldown_active":             "Aktywny cooldown zlecenia oczekującego",
    "sell_blocked_no_position":            "Brak pozycji do sprzedaży",
    "tp_sl_exit_triggered":                "TP/SL osiągnięty — pozycja zamknięta",
    "min_notional_guard":                  "Wartość zlecenia poniżej minimum giełdowego",
    "tp_hit":                              "Take Profit osiągnięty — pozycja zamknięta",
    "sl_hit":                              "Stop Loss osiągnięty — pozycja zamknięta",
    "trailing_stop_hit":                   "Trailing Stop — pozycja zamknięta",
    "manual_close":                        "Ręczne zamknięcie pozycji",
    "partial_close":                       "Częściowe zamknięcie pozycji",
    "hold_target_reached":                 "Cel portfelowy HOLD osiągnięty",
    "no_trace":                            "Brak decyzji w tym oknie",
}

_EXIT_REASON_CODES = {"tp_hit", "sl_hit", "trailing_stop_hit", "manual_close", "partial_close", "hold_target_reached", "tp_sl_exit_triggered"}
_BUY_REASON_CODES = {"all_gates_passed", "pending_confirmed_execution"}


@router.get("/bot-activity")
def get_bot_activity(
    mode: str = Query("demo"),
    minutes: int = Query(15, ge=1, le=120),
    db: Session = Depends(get_db),
):
    """
    Aktywność bota: ile symboli rozważył, ile odrzucił, ile kupił, ile zamknął
    w ostatnich N minutach. Zwraca też 3 ostatnie akcje po polsku i otwarte pozycje.
    """
    try:
        since = utc_now_naive() - timedelta(minutes=minutes)

        traces = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode, DecisionTrace.timestamp >= since)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(500)
            .all()
        )

        considered = len({t.symbol for t in traces})
        bought = sum(1 for t in traces if t.reason_code in _BUY_REASON_CODES)
        closed = sum(1 for t in traces if t.reason_code in _EXIT_REASON_CODES)
        rejected = len(traces) - bought - closed

        last_actions = []
        seen_ids: set = set()
        for t in traces:
            if t.id in seen_ids:
                continue
            seen_ids.add(t.id)
            desc_pl = _REASON_PL.get(t.reason_code or "", t.reason_code or "—")
            icon = "✅" if t.reason_code in _BUY_REASON_CODES else ("🔴" if t.reason_code in _EXIT_REASON_CODES else "⏳")
            last_actions.append({
                "symbol": t.symbol,
                "reason_code": t.reason_code,
                "description": f"{icon} {t.symbol}: {desc_pl}",
                "action_type": t.action_type,
                "ts": t.timestamp.isoformat() if t.timestamp else None,
            })
            if len(last_actions) >= 3:
                break

        # Otwarte pozycje z bieżącym kursem
        positions_raw = (
            db.query(Position)
            .filter(Position.mode == mode)
            .all()
        )
        open_positions = []
        for p in positions_raw:
            entry = float(p.entry_price or 0)
            curr = float(p.current_price or entry)
            qty = float(p.quantity or 0)
            pnl_eur = float(p.unrealized_pnl or 0)
            pnl_pct = ((curr - entry) / entry * 100) if entry > 0 else 0.0
            tp = float(p.planned_tp) if p.planned_tp else None
            sl = float(p.planned_sl) if p.planned_sl else None
            if tp and curr >= tp:
                hold_reason = f"Blisko TP ({tp:.2f})"
            elif sl and curr <= sl:
                hold_reason = f"Zagrożony SL ({sl:.2f})"
            else:
                hold_reason = f"Trzymamy — TP: {tp:.2f}" if tp else "Brak TP/SL"
            open_positions.append({
                "symbol": p.symbol,
                "side": p.side,
                "quantity": qty,
                "entry_price": entry,
                "current_price": curr,
                "pnl_eur": round(pnl_eur, 4),
                "pnl_pct": round(pnl_pct, 3),
                "planned_tp": tp,
                "planned_sl": sl,
                "hold_reason": hold_reason,
                "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            })

        # Equity z ostatniego snapshot
        snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(desc(AccountSnapshot.timestamp))
            .first()
        )
        equity = float(snap.equity) if snap else None

        return {
            "data": {
                "mode": mode,
                "window_minutes": minutes,
                "considered": considered,
                "rejected": rejected,
                "bought": bought,
                "closed": closed,
                "last_actions": last_actions,
                "open_positions": open_positions,
                "equity": equity,
                "timestamp": utc_now_naive().isoformat(),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting bot activity: {str(e)}")
