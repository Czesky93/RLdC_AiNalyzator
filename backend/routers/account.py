"""
Account API Router - endpoints dla danych konta (demo i live)
"""

import hashlib
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend import tunnel_manager as _tunnel_mgr
from backend.accounting import (
    compute_demo_account_state,
    compute_risk_snapshot,
    get_demo_quote_ccy,
)
from backend.ai_orchestrator import get_ai_orchestrator_status
from backend.auth import require_admin
from backend.binance_client import get_binance_client
from backend.candidate_validation import (
    experiment_feed_summary,
    generate_experiment_feed,
)
from backend.correlation import (
    get_incident_correlations,
    get_incident_timeline,
    get_policy_action_chain,
    get_promotion_chain,
    get_why_blocked,
)
from backend.database import (
    AccountSnapshot,
    CostLedger,
    DecisionTrace,
    MarketData,
    Order,
    PendingOrder,
    Position,
    RuntimeSetting,
    SystemLog,
    get_db,
    reset_database,
    utc_now_naive,
)
from backend.experiments import (
    compare_snapshots_for_experiment,
    create_experiment,
    get_experiment,
    list_experiments,
)
from backend.governance import (
    PipelineFreezeError,
    check_pipeline_permission,
    create_incident,
    escalate_overdue_incidents,
    get_incident,
    get_operator_queue_with_summary,
    get_pipeline_status,
    list_incidents,
    transition_incident,
)
from backend.notification_hooks import _get_config as _get_notification_config
from backend.notification_hooks import dispatch_notification, send_telegram_message
from backend.operator_console import get_console_section, get_operator_console
from backend.policy_layer import (
    create_policy_action,
    get_policy_action,
    list_active_policy_actions,
    list_policy_actions,
    policy_actions_summary,
    resolve_policy_action,
)
from backend.post_promotion_monitoring import (
    evaluate_monitoring,
    get_monitoring_by_promotion,
    get_monitoring_record,
    list_monitoring_records,
)
from backend.post_rollback_monitoring import (
    evaluate_post_rollback_monitoring,
    get_post_rollback_monitoring_by_rollback,
    get_post_rollback_monitoring_record,
    list_post_rollback_monitoring_records,
)
from backend.promotion_flow import (
    get_promotion,
    list_promotions,
    promote_recommendation,
)
from backend.recommendations import (
    generate_recommendation,
    get_recommendation,
    list_recommendations,
    pending_recommendation_candidates,
    recommendation_overview,
)
from backend.reevaluation_worker import get_worker_status, run_worker_cycle
from backend.reporting import (
    analytics_bundle,
    config_snapshot_compare_report,
    config_snapshot_payload_report,
    performance_overview,
    risk_effectiveness_report,
)
from backend.review_flow import apply_review_decision, list_review_queue, review_bundle
from backend.rollback_decision import (
    create_rollback_decision,
    get_rollback_decision,
    latest_rollback_decision_for_promotion,
    list_rollback_decisions,
)
from backend.rollback_flow import (
    execute_rollback,
    get_rollback_execution,
    list_rollback_executions,
)
from backend.routers.portfolio import _build_live_spot_portfolio
from backend.runtime_settings import (
    RuntimeSettingsError,
    build_runtime_state,
    get_runtime_config,
)
from backend.trading_effectiveness import (
    effectiveness_bundle,
    exit_quality_report,
    reason_code_effectiveness,
    strategy_effectiveness,
    symbol_effectiveness,
)
from backend.tuning_insights import generate_tuning_candidates, tuning_summary

router = APIRouter()

_openai_status_cache: dict = {"ts": None, "data": None}
_demo_state_cache: dict = {"ts": None, "data": None}


def _resolve_local_ip() -> Dict[str, Any]:
    hostname = socket.gethostname()
    local_candidates = []
    try:
        _, _, host_ips = socket.gethostbyname_ex(hostname)
        local_candidates = [ip for ip in host_ips if ip and not ip.startswith("127.")]
    except Exception:
        local_candidates = []

    primary_local_ip = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary_local_ip = sock.getsockname()[0]
        sock.close()
    except Exception:
        primary_local_ip = local_candidates[0] if local_candidates else None

    return {
        "hostname": hostname,
        "local_ip": primary_local_ip,
        "local_ips": local_candidates,
    }


def _resolve_public_egress_ip() -> Dict[str, Any]:
    sources = [
        ("ipify", "https://api.ipify.org?format=json"),
        ("ifconfig", "https://ifconfig.me/ip"),
        ("icanhazip", "https://icanhazip.com"),
    ]
    for name, url in sources:
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code != 200:
                continue
            ip = ""
            if "json" in (resp.headers.get("content-type", "") or ""):
                ip = str((resp.json() or {}).get("ip") or "").strip()
            else:
                ip = (resp.text or "").strip()
            if ip:
                return {"public_egress_ip": ip, "source": name}
        except Exception:
            continue
    return {"public_egress_ip": None, "source": None}


def _dns_resolve_records(domain: str, record_type: str) -> list[str]:
    try:
        resp = requests.get(
            "https://dns.google/resolve",
            params={"name": domain, "type": record_type},
            timeout=4,
        )
        if resp.status_code != 200:
            return []
        payload = resp.json() if resp.text else {}
        answers = (payload or {}).get("Answer") or []
        result = []
        for ans in answers:
            data = str((ans or {}).get("data") or "").strip().rstrip(".")
            if data:
                result.append(data)
        return result
    except Exception:
        return []


def _resolve_domain_proxy_info(domain: Optional[str]) -> Dict[str, Any]:
    if not domain:
        return {
            "configured_domain": None,
            "dns": {"a": [], "aaaa": [], "cname": [], "ns": []},
            "classification": "unknown",
            "cloudflare_detected": False,
            "proxied": None,
            "tunnel_detected": False,
            "notes": [
                "No configured domain in env (APP_DOMAIN/PUBLIC_DOMAIN/API_DOMAIN)."
            ],
        }

    a_records = _dns_resolve_records(domain, "A")
    aaaa_records = _dns_resolve_records(domain, "AAAA")
    cname_records = _dns_resolve_records(domain, "CNAME")
    ns_records = _dns_resolve_records(domain, "NS")

    cname_l = [x.lower() for x in cname_records]
    ns_l = [x.lower() for x in ns_records]

    tunnel_detected = any("cfargotunnel.com" in x for x in cname_l)
    cloudflare_ns = any("cloudflare" in x for x in ns_l)
    cloudflare_cname = any("cloudflare" in x for x in cname_l)
    cloudflare_detected = bool(cloudflare_ns or cloudflare_cname or tunnel_detected)

    if tunnel_detected:
        classification = "tunnel"
    elif cloudflare_detected:
        classification = "proxied"
    elif a_records or aaaa_records:
        classification = "direct"
    else:
        classification = "unknown"

    notes = []
    if classification in {"proxied", "tunnel"}:
        notes.append("Cloudflare/proxy detected: DNS may not expose origin server IP.")
    if classification == "tunnel":
        notes.append("Cloudflare Tunnel detected: origin IP is intentionally hidden.")

    return {
        "configured_domain": domain,
        "dns": {
            "a": a_records,
            "aaaa": aaaa_records,
            "cname": cname_records,
            "ns": ns_records,
        },
        "classification": classification,
        "cloudflare_detected": cloudflare_detected,
        "proxied": classification in {"proxied", "tunnel"},
        "tunnel_detected": tunnel_detected,
        "notes": notes,
    }


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


@router.get("/runtime-settings")
def get_runtime_settings_alias(db: Session = Depends(get_db)):
    """
    Alias kompatybilnosci dla starszych klientow: /api/account/runtime-settings.
    """
    try:
        data = get_runtime_config(db)
        return {"success": True, "data": data}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting runtime settings: {str(exc)}"
        ) from exc


@router.get("/runtime-config")
def get_runtime_config_alias(db: Session = Depends(get_db)):
    """
    Alias kompatybilnosci dla starszych klientow: /api/account/runtime-config.
    """
    try:
        data = build_runtime_state(db)
        return {"success": True, "data": data}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting runtime config: {str(exc)}"
        ) from exc


@router.get("/config")
def get_account_config_alias(db: Session = Depends(get_db)):
    """
    Alias kompatybilnosci dla starszych klientow: /api/account/config.
    """
    try:
        data = {
            "runtime": get_runtime_config(db),
            "state": build_runtime_state(db),
        }
        return {"success": True, "data": data}
    except RuntimeSettingsError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting account config: {str(exc)}"
        ) from exc


def _sanitize_openai_message(msg: str) -> str:
    # Never leak secret-like strings (API keys) to clients/logs.
    return re.sub(r"sk-[^\s]+", "sk-[REDACTED]", msg or "")


def _resolve_openai_status(force: bool = False) -> dict:
    """Jedno źródło prawdy dla statusu OpenAI (używane przez dwa endpointy)."""
    api_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    if (api_key.startswith('"') and api_key.endswith('"')) or (
        api_key.startswith("'") and api_key.endswith("'")
    ):
        api_key = api_key[1:-1].strip()

    if not api_key:
        return {
            "status": "missing",
            "http_status": None,
            "code": "missing_api_key",
            "message": "Brak OPENAI_API_KEY w `.env`.",
            "key_len": 0,
            "key_fingerprint": None,
            "checked_at": utc_now_naive().isoformat(),
            "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        }

    now = utc_now_naive()
    ttl_seconds = int(os.getenv("OPENAI_STATUS_CACHE_SECONDS", "120"))
    if (
        not force
        and _openai_status_cache.get("ts")
        and _openai_status_cache.get("data")
    ):
        age = (now - _openai_status_cache["ts"]).total_seconds()
        if age < ttl_seconds:
            return _openai_status_cache["data"]

    key_fp = hashlib.sha256(api_key.encode("utf-8", errors="ignore")).hexdigest()[:12]
    try:
        resp = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
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
        return data
    except Exception as exc:
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
        return data


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
    mode: str = Query("live", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
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
                "realized_pnl_total": round(
                    float(state.get("realized_pnl_total") or 0.0), 2
                ),
                "realized_pnl_24h": round(
                    float(state.get("realized_pnl_24h") or 0.0), 2
                ),
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
                            if _binance_err
                            else "Binance API niedostępne. "
                        )
                        + "Ustaw BINANCE_API_KEY i BINANCE_SECRET_KEY w .env",
                    },
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
                timestamp=utc_now_naive(),
            )
            db.add(snapshot)
            db.commit()

            return {"success": True, "data": data}

        else:
            raise HTTPException(
                status_code=400, detail="Invalid mode. Use 'demo' or 'live'"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting account summary: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error resetting database: {str(e)}"
        )


@router.get("/openai-status")
def get_openai_status(
    force: bool = Query(
        False, description="Jeśli true, pomija cache i wykonuje realny test"
    ),
):
    """
    Sprawdza czy klucz OpenAI z `.env` działa (bez ujawniania klucza).
    Używane do szybkiej diagnostyki w UI.
    """
    return {"success": True, "data": _resolve_openai_status(force=force)}


@router.get("/ai-status")
def get_ai_status():
    """
    Status wszystkich skonfigurowanych providerów AI.
    Szybka diagnostyka w UI — który provider jest aktywny, czy jest w backoff.
    """
    from backend.analysis import get_ai_providers_status

    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()

    def _check_key(env_name: str) -> dict:
        key = (os.getenv(env_name, "") or "").strip()
        return {"configured": bool(key), "key_len": len(key) if key else 0}

    openai_diag = _resolve_openai_status(force=False)

    providers_static = {
        "ollama": {
            "configured": bool(
                (
                    os.getenv("OLLAMA_BASE_URL", "") or os.getenv("OLLAMA_URL", "")
                ).strip()
            ),
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
            "diagnostic": {
                "status": openai_diag.get("status"),
                "code": openai_diag.get("code"),
                "message": openai_diag.get("message"),
            },
        },
    }

    # Backoff / runtime status z modułu analysis
    runtime_statuses = {s["name"]: s for s in get_ai_providers_status()}

    # OpenAI: jeśli status diagnostyczny zwraca błąd (np. invalid_api_key),
    # nie pokazuj go jako aktywnego providera.
    if openai_diag.get("status") == "error":
        runtime_statuses["openai"] = {
            "name": "openai",
            "status": "backoff",
            "label": "błąd klucza/API",
            "code": openai_diag.get("code"),
        }
    elif openai_diag.get("status") == "missing":
        runtime_statuses["openai"] = {
            "name": "openai",
            "status": "unconfigured",
            "label": "brak klucza",
            "code": openai_diag.get("code"),
        }

    for name, pdata in providers_static.items():
        pdata["runtime"] = runtime_statuses.get(name, {})

    # configured dla OpenAI oznacza poprawny status testu, a nie samą obecność stringa klucza
    providers_static["openai"]["configured"] = openai_diag.get("status") == "ok"
    providers_static["openai"]["key_len"] = int(openai_diag.get("key_len") or 0)

    # W trybie auto, kolejność prób
    if provider == "auto":
        chain = ["ollama", "gemini", "groq", "openai", "heuristic"]
    elif provider in ("heuristic", "offline"):
        chain = ["heuristic"]
    else:
        chain = [provider, "heuristic"]

    active = "heuristic"
    for p in chain:
        if p != "heuristic" and providers_static.get(p, {}).get("configured"):
            rt = runtime_statuses.get(p, {})
            if rt.get("status") not in ("backoff", "unconfigured"):
                active = p
                break

    return {
        "success": True,
        "data": {
            "ai_provider_setting": provider,
            "active_provider": active,
            "fallback_chain": chain,
            "providers": providers_static,
            "heuristic": "ATR + Bollinger (zawsze dostępna)",
        },
    }


@router.get("/ai-orchestrator-status")
def get_ai_orchestrator_diagnostics(
    force: bool = Query(False, description="Wymusza pelny check providerow"),
):
    """
    Rozszerzona diagnostyka multi-provider AI.
    """
    try:
        data = get_ai_orchestrator_status(force=force)
        return {"success": True, "data": data}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting AI orchestrator status: {str(exc)}"
        )


@router.get("/system-health")
def get_system_health():
    """
    Stan wszystkich serwisów systemd + tunnel + HTTP health.
    Wymaganie autonomii: po restarcie systemu pokazuje co działa, a co nie.
    """
    import subprocess

    SERVICES = [
        ("rldc-backend", "Backend FastAPI"),
        ("rldc-frontend", "Frontend Next.js"),
        ("rldc-telegram", "Telegram Bot"),
        ("rldc-cloudflared", "Named Tunnel"),
        ("rldc-quicktunnel", "Quick Tunnel (fallback)"),
        ("rldc-watchdog.timer", "Watchdog Timer"),
    ]
    HEALTHCHECKS = [
        ("http://127.0.0.1:8000/health", "backend_http"),
        ("http://127.0.0.1:3000", "frontend_http"),
    ]

    import requests as _req

    services_status = []
    for svc, label in SERVICES:
        try:
            _is_active = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True,
                text=True,
                timeout=3,
            )
            _is_enabled = subprocess.run(
                ["systemctl", "--user", "is-enabled", svc],
                capture_output=True,
                text=True,
                timeout=3,
            )
            active = _is_active.stdout.strip()
            enabled = _is_enabled.stdout.strip()
            services_status.append(
                {
                    "service": svc,
                    "label": label,
                    "active": active,
                    "enabled": enabled,
                    "ok": active == "active",
                }
            )
        except Exception as _e:
            services_status.append(
                {
                    "service": svc,
                    "label": label,
                    "active": "error",
                    "enabled": "error",
                    "ok": False,
                    "error": str(_e),
                }
            )

    http_checks = []
    for url, name in HEALTHCHECKS:
        try:
            r = _req.get(url, timeout=3)
            http_checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_code": r.status_code,
                    "ok": r.status_code < 500,
                }
            )
        except Exception as _he:
            http_checks.append(
                {
                    "name": name,
                    "url": url,
                    "status_code": None,
                    "ok": False,
                    "error": str(_he),
                }
            )

    # Quick tunnel runtime file
    qt_runtime: dict = {}
    try:
        import json as _json

        with open("/tmp/rldc_tunnel_runtime.json") as _f:
            qt_runtime = _json.load(_f)
    except Exception:
        qt_runtime = {"running": False, "frontend_url": None}

    all_ok = all(
        s["ok"]
        for s in services_status
        if s["service"] in {"rldc-backend", "rldc-frontend", "rldc-telegram"}
    ) and all(h["ok"] for h in http_checks)

    return {
        "success": True,
        "data": {
            "overall_ok": all_ok,
            "services": services_status,
            "http_checks": http_checks,
            "quicktunnel_runtime": qt_runtime,
            "checked_at": utc_now_naive().isoformat(),
            "autonomy_note": (
                "Backend/frontend/telegram: systemd enabled + linger=yes → auto-start po restarcie. "
                "Watchdog timer: co 60s restartuje padnięte usług. "
                "Quick tunnel: auto-start po restarcie (nowy URL zapisywany do /tmp/rldc_tunnel_runtime.json). "
                "Named tunnel: wymaga jednorazowego setup (bash scripts/setup_tunnel.sh DOMENA)."
            ),
        },
    }


@router.get("/ip-diagnostics")
def get_ip_diagnostics():
    """
    Rozdziela local IP, public egress IP oraz info domena/proxy/tunnel.
    Dodatkowa weryfikacja: HTTP probe każdego candidate URL (2s timeout).
    Wykrywa martwe quick tunnel, sprawdza czy cloudflared działa.
    """
    import subprocess

    import requests as _req

    try:
        local_info = _resolve_local_ip()
        public_info = _resolve_public_egress_ip()

        domain = (
            os.getenv("APP_DOMAIN", "")
            or os.getenv("PUBLIC_DOMAIN", "")
            or os.getenv("API_DOMAIN", "")
        ).strip() or None
        app_domain = (
            os.getenv("APP_DOMAIN", "") or os.getenv("PUBLIC_DOMAIN", "")
        ).strip()
        api_domain = (os.getenv("API_DOMAIN", "") or "").strip()
        tunnel_url = (os.getenv("CLOUDFLARE_TUNNEL_URL", "") or "").strip()

        # Zbierz kandydatów URL — preferuj aktywny runtime tunnel URL.
        candidate_urls: list[dict] = []
        seen_urls: set[str] = set()

        def _add_candidate(url: str, label: str, is_api: bool = False) -> None:
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            tunnel_type = "quick" if "trycloudflare.com" in url else "named"
            candidate_urls.append(
                {
                    "url": url,
                    "label": label,
                    "tunnel_type": tunnel_type,
                    "is_api": is_api,
                }
            )

        runtime_active_url: str | None = None
        try:
            _tm_status = _tunnel_mgr.get_tunnel_status()
            runtime_active_url = (_tm_status or {}).get("active_url")
        except Exception:
            runtime_active_url = None

        if runtime_active_url:
            _add_candidate(runtime_active_url, "tunnel_runtime_active")

        # Czytaj żywy URL z runtime pliku quick tunnel (run_quicktunnel.sh)
        _qt_runtime_file = "/tmp/rldc_tunnel_runtime.json"
        _qt_runtime_data: dict = {}
        try:
            import json as _json

            with open(_qt_runtime_file) as _f:
                _qt_runtime_data = _json.load(_f)
            if _qt_runtime_data.get("running") and _qt_runtime_data.get("frontend_url"):
                _add_candidate(_qt_runtime_data["frontend_url"], "quicktunnel_runtime")
        except Exception:
            pass

        # Legacy env URLs traktujemy jako fallback diagnostyczny tylko gdy runtime nie daje aktywnego URL.
        if not candidate_urls:
            if app_domain:
                _add_candidate(f"https://{app_domain}", "frontend")
            if api_domain:
                _add_candidate(f"https://{api_domain}", "api", is_api=True)
            if tunnel_url and tunnel_url not in seen_urls:
                _add_candidate(tunnel_url, "tunnel_env")

        # Sprawdź czy cloudflared działa jako proces
        tunnel_process_running = False
        try:
            result = subprocess.run(
                ["pgrep", "-x", "cloudflared"], capture_output=True, timeout=2
            )
            tunnel_process_running = result.returncode == 0
        except Exception:
            tunnel_process_running = False

        # HTTP probe każdego URL — prawdziwy test (GET + analiza treści)
        import re as _re

        # Znaczniki strony błędu Cloudflare (case-insensitive search w body)
        _CF_ERROR_PATTERNS = [
            r"error\s+1\d{3}",  # Error 1016, Error 1012, ...
            r"\"cf-error-details\"",
            r"<title>[^<]{0,60}1\d{3}[^<]{0,60}</title>",
            r"cloudflare ray id",
            r"host not found",
            r"this page can.t be reached",
        ]

        def _probe_url(url: str) -> dict:
            """
            Prawdziwy test dostępności URL-a (GET + analiza treści).
            URL jest uznany za DZIAŁAJĄCY tylko gdy:
            - HTTP 200 (lub redirect → 200)
            - Treść ma ≥100 bajtów
            - Brak markerów strony błędu Cloudflare / pustej odpowiedzi
            """
            result: dict = {
                "status_code": None,
                "final_url": url,
                "reachable": False,
                "cf_error": False,
                "cf_error_code": None,
                "content_len": 0,
                "status": "unreachable",
                "debug": None,
            }
            try:
                r = _req.get(
                    url,
                    timeout=5,
                    allow_redirects=True,
                    verify=False,
                    headers={"User-Agent": "RLdC-Probe/1.0"},
                )
                result["status_code"] = r.status_code
                result["final_url"] = str(r.url)
                body = (r.text or "")[:5000]
                result["content_len"] = len(r.content)

                # 4xx/5xx = niedziałający
                if r.status_code >= 400:
                    result["status"] = f"http_{r.status_code}"
                    result["debug"] = f"HTTP {r.status_code}"
                    return result

                # Sprawdź markery CF error page
                body_lower = body.lower()
                for _pat in _CF_ERROR_PATTERNS:
                    _m = _re.search(_pat, body_lower)
                    if _m:
                        result["cf_error"] = True
                        result["cf_error_code"] = _m.group(0)[:60]
                        result["status"] = "cf_error_page"
                        result["debug"] = f"Strona błędu CF: {_m.group(0)[:60]}"
                        return result

                # Pusta odpowiedź po 200 = tunnel żyje, origin nie odpowiada
                if len(r.content) < 100:
                    result["status"] = "empty_response"
                    result["debug"] = (
                        f"HTTP {r.status_code}, pusta odpowiedź ({len(r.content)} B)"
                    )
                    return result

                # Wygląda jak działająca strona
                result["reachable"] = True
                result["status"] = "reachable"
                result["debug"] = f"HTTP {r.status_code}, {len(r.content)} B"
                return result

            except _req.exceptions.Timeout:
                result["status"] = "timeout"
                result["debug"] = "Timeout (5s)"
                return result
            except Exception as _exc:
                result["status"] = "error"
                result["debug"] = str(_exc)[:120]
                return result

        url_status: list[dict] = []
        active_frontend_url: str | None = None
        active_api_url: str | None = None
        any_reachable = False

        for cand in candidate_urls:
            probe = _probe_url(cand["url"])
            reachable = probe["reachable"]
            is_quick = cand["tunnel_type"] == "quick"
            # Ostrzeżenie dla quick tunneli
            if is_quick and reachable:
                warn = "Quick tunnel URL jest tymczasowy i wygasa. Użyj named tunnel dla stabilności."
            elif is_quick and not reachable:
                warn = f"Quick tunnel nieosiągalny ({probe['status']}). Zrestartuj tunel lub sprawdź logi."
            else:
                warn = None
            entry = {
                "url": cand["url"],
                "label": cand["label"],
                "tunnel_type": cand["tunnel_type"],
                "status": probe["status"],
                "reachable": reachable,
                "status_code": probe.get("status_code"),
                "final_url": probe.get("final_url"),
                "cf_error": probe.get("cf_error", False),
                "cf_error_code": probe.get("cf_error_code"),
                "content_len": probe.get("content_len", 0),
                "debug": probe.get("debug"),
                "is_quick_tunnel": is_quick,
                "warning": warn,
            }
            url_status.append(entry)
            if reachable:
                any_reachable = True
                if cand.get("is_api") and not active_api_url:
                    active_api_url = cand["url"]
                elif not cand.get("is_api") and not active_frontend_url:
                    active_frontend_url = cand["url"]

        domain_info = _resolve_domain_proxy_info(domain)
        tunnel_detected = bool(domain_info.get("tunnel_detected") or tunnel_url)
        cloudflare_detected = bool(domain_info.get("cloudflare_detected") or tunnel_url)

        notes = list(domain_info.get("notes") or [])
        if tunnel_url and not tunnel_process_running and not any_reachable:
            notes.append(
                "UWAGA: Zmienna CLOUDFLARE_TUNNEL_URL jest ustawiona, ale cloudflared NIE jest uruchomiony!"
            )
        if not any_reachable and candidate_urls:
            notes.append(
                "Brak działającego publicznego adresu — żaden URL nie zwraca prawidłowej odpowiedzi."
            )
        if not candidate_urls:
            notes.append(
                "Brak skonfigurowanych publicznych URL-i. Ustaw APP_DOMAIN lub CLOUDFLARE_TUNNEL_URL."
            )
        # Ogranicz alerty: ostrzeżenia tylko gdy NIE ma żadnego działającego URL.
        for _us in url_status:
            if (
                _us.get("label") == "quicktunnel_runtime"
                and not _us.get("reachable")
                and not any_reachable
            ):
                notes.append(
                    f"Quick tunnel runtime nieosiągalny ({_us['status']}): {_us['url']} — "
                    "zrestartuj serwis rldc-quicktunnel lub sprawdź logi (port 3000)."
                )

        return {
            "success": True,
            "data": {
                "hostname": local_info.get("hostname"),
                "local_ip": local_info.get("local_ip"),
                "local_ips": local_info.get("local_ips") or [],
                "public_egress_ip": public_info.get("public_egress_ip"),
                "public_lookup_source": public_info.get("source"),
                "configured_domain": domain_info.get("configured_domain"),
                "dns_result": domain_info.get("dns") or {},
                "classification": domain_info.get("classification"),
                "cloudflare_detected": cloudflare_detected,
                "proxied": domain_info.get("proxied"),
                "tunnel_detected": tunnel_detected,
                "tunnel_process_running": tunnel_process_running,
                "public_urls": [c["url"] for c in url_status],
                "url_status": url_status,
                "active_frontend_url": active_frontend_url,
                "active_api_url": active_api_url,
                "any_url_reachable": any_reachable,
                "notes": notes,
                "explanation": (
                    "url_status: GET probe (5s timeout). "
                    "reachable=True: HTTP 200 + treść ≥100B + brak CF error page. "
                    "status: reachable|http_NNN|cf_error_page|empty_response|timeout|error. "
                    "active_frontend_url: jedyny prawidłowo działający adres frontendu."
                ),
                "checked_at": utc_now_naive().isoformat(),
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Error getting IP diagnostics: {str(exc)}"
        )


@router.get("/tunnel-status")
def get_tunnel_status():
    """
    Aktualny stan tunelu cloudflared + wynik ostatniego probe.
    Nie triggeruje self-healing — tylko raportuje stan.
    """
    try:
        status = _tunnel_mgr.get_tunnel_status()
        return {"success": True, "data": status}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tunnel status error: {str(exc)}")


@router.post("/tunnel-heal")
def trigger_tunnel_heal(force: bool = False):
    """
    Uruchom self-healing tunelu:
    1. Sprawdź lokalny port frontendu
    2. Jeśli runtime/env URL nie działa → restartuj cloudflared
    3. Czekaj na nowy URL → probe → zapisz do .env

    force=true → ignoruj cooldown (dla operatora).
    """
    try:
        result = _tunnel_mgr.ensure_public_url(force_recovery=force)
        status_code = 200 if result.get("success") else 503
        if status_code != 200:
            raise HTTPException(
                status_code=503,
                detail={
                    "success": False,
                    "error_step": result.get("error_step"),
                    "local_frontend_ok": result.get("local_frontend_ok"),
                    "recovery_attempted": result.get("recovery_attempted"),
                },
            )
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Tunnel heal error: {str(exc)}")


@router.get("/history")
def get_account_history(
    mode: str = Query("live", description="Tryb: demo lub live"),
    hours: int = Query(
        24, ge=1, le=168, description="Ile godzin wstecz (max 168 = tydzień)"
    ),
    db: Session = Depends(get_db),
):
    """
    Pobierz historię equity/margin z ostatnich N godzin
    Do wykresów KPI
    """
    try:
        # Oblicz czas początkowy
        since = utc_now_naive() - timedelta(hours=hours)

        # Pobierz snapshoty
        snapshots = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode, AccountSnapshot.timestamp >= since)
            .order_by(AccountSnapshot.timestamp)
            .all()
        )

        if not snapshots:
            if mode == "demo":
                state = _cached_demo_state(db)
                _persist_demo_snapshot(db, state)
                snapshots = (
                    db.query(AccountSnapshot)
                    .filter(
                        AccountSnapshot.mode == mode, AccountSnapshot.timestamp >= since
                    )
                    .order_by(AccountSnapshot.timestamp)
                    .all()
                )
            else:
                return {"success": True, "mode": mode, "data": [], "count": 0}

        # Formatuj dane
        history = []
        for snap in snapshots:
            history.append(
                {
                    "timestamp": snap.timestamp.isoformat(),
                    "equity": snap.equity,
                    "free_margin": snap.free_margin,
                    "used_margin": snap.used_margin,
                    "margin_level": snap.margin_level,
                    "unrealized_pnl": snap.unrealized_pnl,
                }
            )

        return {
            "success": True,
            "mode": mode,
            "data": history,
            "count": len(history),
            "period_hours": hours,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting account history: {str(e)}"
        )


@router.get("/kpi")
def get_account_kpi(
    mode: str = Query("live", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Pobierz KPI konta (do dashboard)
    """
    try:
        # Pobierz aktualny snapshot
        latest = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(desc(AccountSnapshot.timestamp))
            .first()
        )

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
                        "timestamp": utc_now_naive().isoformat(),
                    },
                    "_info": "Brak danych live z Binance. Synchronizacja konta nieaktywna.",
                    "source": "fallback",
                    "stale": True,
                }

        # Pobierz snapshot sprzed 24h
        day_ago = utc_now_naive() - timedelta(hours=24)
        prev = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode, AccountSnapshot.timestamp <= day_ago)
            .order_by(desc(AccountSnapshot.timestamp))
            .first()
        )

        # Oblicz zmiany
        equity_change = 0
        equity_change_percent = 0
        if prev:
            equity_change = latest.equity - prev.equity
            equity_change_percent = (
                (equity_change / prev.equity * 100) if prev.equity > 0 else 0
            )

        kpi = {
            "equity": round(latest.equity, 2),
            "equity_change": round(equity_change, 2),
            "equity_change_percent": round(equity_change_percent, 2),
            "free_margin": round(latest.free_margin, 2),
            "used_margin": round(latest.used_margin, 2),
            "margin_level": round(latest.margin_level, 2),
            "unrealized_pnl": round(latest.unrealized_pnl, 2),
            "balance": round(latest.balance, 2),
            "timestamp": latest.timestamp.isoformat(),
        }

        return {"success": True, "mode": mode, "data": kpi}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting KPI: {str(e)}")


@router.get("/risk")
def get_risk_summary(
    mode: str = Query("live", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
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
        raise HTTPException(
            status_code=500, detail=f"Error getting risk summary: {str(e)}"
        )


@router.get("/analytics/overview")
def get_analytics_overview(
    mode: str = Query("live", description="Tryb: demo lub live"),
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
        raise HTTPException(
            status_code=500, detail=f"Error getting analytics overview: {str(e)}"
        )


@router.get("/analytics/risk-effectiveness")
def get_risk_effectiveness(
    mode: str = Query("live", description="Tryb: demo lub live"),
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
        raise HTTPException(
            status_code=500,
            detail=f"Error getting risk effectiveness analytics: {str(e)}",
        )


@router.get("/analytics")
def get_analytics_bundle(
    mode: str = Query("live", description="Tryb: demo lub live"),
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
        raise HTTPException(
            status_code=500, detail=f"Error getting analytics bundle: {str(e)}"
        )


@router.get("/analytics/config-snapshots/compare")
def compare_config_snapshot_payloads(
    snapshot_a: str,
    snapshot_b: str,
    mode: str = Query("live", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "mode": mode,
            "data": config_snapshot_compare_report(
                db, snapshot_a, snapshot_b, mode=mode
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error comparing config snapshots: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting config snapshot payload: {str(e)}"
        )


@router.get("/analytics/experiments/compare")
def compare_experiment_variants(
    baseline_snapshot_id: str,
    candidate_snapshot_id: str,
    mode: str = Query("live", description="Tryb: demo lub live"),
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
        raise HTTPException(
            status_code=500, detail=f"Error comparing experiment variants: {str(e)}"
        )


@router.get("/analytics/experiments")
def get_experiments(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_experiments(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing experiments: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting experiment: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error creating experiment: {str(e)}"
        )


@router.get("/analytics/recommendations")
def get_recommendations(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_recommendations(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing recommendations: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting recommendation overview: {str(e)}"
        )


@router.get("/analytics/recommendations/review-queue")
def get_recommendation_review_queue(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_review_queue(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting recommendation review queue: {str(e)}",
        )


@router.post("/analytics/recommendations")
def create_recommendation_endpoint(
    payload: RecommendationCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": generate_recommendation(
                db, payload.experiment_id, notes=payload.notes
            ),
        }
    except PipelineFreezeError as exc:
        raise HTTPException(status_code=403, detail=exc.to_dict()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating recommendation: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting recommendation: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500,
            detail=f"Error getting recommendation review bundle: {str(e)}",
        )


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
        return {
            "success": True,
            "data": _apply_review_http(db, recommendation_id, payload, "start_review"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error starting recommendation review: {str(e)}"
        )


@router.post("/analytics/recommendations/{recommendation_id}/approve")
def approve_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": _apply_review_http(db, recommendation_id, payload, "approve"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error approving recommendation: {str(e)}"
        )


@router.post("/analytics/recommendations/{recommendation_id}/reject")
def reject_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": _apply_review_http(db, recommendation_id, payload, "reject"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error rejecting recommendation: {str(e)}"
        )


@router.post("/analytics/recommendations/{recommendation_id}/defer")
def defer_recommendation(
    recommendation_id: int,
    payload: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": _apply_review_http(db, recommendation_id, payload, "defer"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error deferring recommendation: {str(e)}"
        )


@router.get("/analytics/promotions")
def get_config_promotions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_promotions(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing promotions: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting promotion: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error creating promotion: {str(e)}"
        )


@router.get("/analytics/promotion-monitoring")
def get_promotion_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing promotion monitoring records: {str(e)}",
        )


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
        raise HTTPException(
            status_code=500,
            detail=f"Error getting promotion monitoring record: {str(e)}",
        )


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
        raise HTTPException(
            status_code=500,
            detail=f"Error getting promotion monitoring verdict: {str(e)}",
        )


@router.post("/analytics/promotions/{promotion_id}/monitoring/evaluate")
def evaluate_promotion_monitoring(
    promotion_id: int,
    payload: PromotionMonitoringRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": evaluate_monitoring(db, promotion_id, notes=payload.notes),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error evaluating promotion monitoring: {str(e)}"
        )


@router.get("/analytics/rollbacks")
def get_rollback_decisions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_decisions(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing rollback decisions: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting rollback decision: {str(e)}"
        )


@router.get("/analytics/promotions/{promotion_id}/rollback-decision")
def get_latest_rollback_decision_for_promotion(
    promotion_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": latest_rollback_decision_for_promotion(db, promotion_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting rollback decision for promotion: {str(e)}",
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error creating rollback decision: {str(e)}"
        )


@router.get("/analytics/rollback-executions")
def get_rollback_execution_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_rollback_executions(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing rollback executions: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error getting rollback execution: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Error executing rollback: {str(e)}"
        )


@router.get("/analytics/post-rollback-monitoring")
def get_post_rollback_monitoring_records(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_post_rollback_monitoring_records(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error listing post-rollback monitoring records: {str(e)}",
        )


@router.get("/analytics/post-rollback-monitoring/{monitoring_id}")
def get_post_rollback_monitoring_record_by_id(
    monitoring_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": get_post_rollback_monitoring_record(db, monitoring_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting post-rollback monitoring record: {str(e)}",
        )


@router.get("/analytics/rollbacks/{rollback_id}/post-monitoring")
def get_post_rollback_monitoring_for_rollback(
    rollback_id: int,
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": get_post_rollback_monitoring_by_rollback(db, rollback_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting post-rollback monitoring verdict: {str(e)}",
        )


@router.post("/analytics/rollbacks/{rollback_id}/post-monitoring/evaluate")
def evaluate_rollback_post_monitoring(
    rollback_id: int,
    payload: PromotionMonitoringRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": evaluate_post_rollback_monitoring(
                db, rollback_id, notes=payload.notes
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error evaluating post-rollback monitoring: {str(e)}",
        )


@router.get("/system-logs")
def get_system_logs(
    limit: int = Query(50, ge=1, le=200, description="Ile wpisów (max 200)"),
    level: Optional[str] = Query(None, description="Filtr poziomu: INFO/WARNING/ERROR"),
    module: Optional[str] = Query(
        None, description="Filtr modułu (np. analysis, collector)"
    ),
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
        raise HTTPException(
            status_code=500, detail=f"Error getting system logs: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Policy Actions
# ---------------------------------------------------------------------------


@router.get("/analytics/policy-actions")
def get_policy_actions_list(
    status: Optional[str] = Query(
        None, description="Filtr statusu: open, resolved, superseded"
    ),
    source_type: Optional[str] = Query(
        None,
        description="Filtr źródła: promotion_monitoring, rollback_decision, rollback_monitoring",
    ),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": list_policy_actions(db, status=status, source_type=source_type),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania policy actions: {str(e)}"
        )


@router.get("/analytics/policy-actions/active")
def get_active_policy_actions(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": list_active_policy_actions(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Błąd pobierania aktywnych policy actions: {str(e)}",
        )


@router.get("/analytics/policy-actions/summary")
def get_policy_actions_summary(
    db: Session = Depends(get_db),
):
    try:
        return {"success": True, "data": policy_actions_summary(db)}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Błąd pobierania podsumowania policy actions: {str(e)}",
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania policy action: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd tworzenia policy action: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd rozwiązywania policy action: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania pipeline status: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd sprawdzania uprawnień: {str(e)}"
        )


@router.get("/analytics/operator-queue")
def get_operator_queue_endpoint(
    db: Session = Depends(get_db),
):
    try:
        payload = get_operator_queue_with_summary(db)
        return {
            "success": True,
            "data": payload.get("items", []),
            "summary": payload.get("summary", {}),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania kolejki operatora: {str(e)}"
        )


@router.get("/analytics/incidents")
def list_incidents_endpoint(
    status: Optional[str] = Query(
        None,
        description="Filtr statusu: open, acknowledged, in_progress, escalated, resolved",
    ),
    priority: Optional[str] = Query(
        None, description="Filtr priorytetu: critical, high, medium, low"
    ),
    db: Session = Depends(get_db),
):
    try:
        return {
            "success": True,
            "data": list_incidents(db, status=status, priority=priority),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania incydentów: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd pobierania incydentu: {str(e)}"
        )


@router.post("/analytics/incidents")
def create_incident_endpoint(
    payload: IncidentCreateRequest,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    try:
        return {
            "success": True,
            "data": create_incident(db, policy_action_id=payload.policy_action_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd tworzenia incydentu: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Błąd przejścia incydentu: {str(e)}"
        )


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
            "telegram_configured": bool(
                cfg["telegram_bot_token"] and cfg["telegram_chat_id"]
            ),
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

        last_md = db.query(MarketData).order_by(desc(MarketData.timestamp)).first()
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

        # Tylko błędy z ostatniej godziny — stare błędy nie są już aktywne
        _error_since = utc_now_naive() - timedelta(hours=1)
        last_error = (
            db.query(SystemLog)
            .filter(
                SystemLog.level == "ERROR",
                SystemLog.timestamp >= _error_since,
            )
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
        raise HTTPException(
            status_code=500, detail=f"Error getting system status: {str(e)}"
        )


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
            raise HTTPException(
                status_code=400,
                detail="Kapitał startowy musi być między 1 a 100 000 EUR",
            )

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
        ib_row = (
            db.query(RuntimeSetting)
            .filter(RuntimeSetting.key == "demo_initial_balance")
            .first()
        )
        if ib_row is None:
            db.add(
                RuntimeSetting(
                    key="demo_initial_balance",
                    value=str(body.starting_balance),
                    updated_at=utc_now_naive(),
                )
            )
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
    "all_gates_passed": "Wszystkie filtry OK — zlecenie złożone",
    "pending_confirmed_execution": "Zlecenie wykonane",
    "signal_confidence_too_low": "Pewność sygnału poniżej progu",
    "signal_filters_not_met": "Filtry techniczne (EMA/RSI) niezaliczone",
    "active_pending_exists": "Mamy otwarte zlecenie dla tego symbolu",
    "buy_blocked_existing_position": "Już mamy otwartą pozycję BUY",
    "buy_rejected_inferior_to_open_positions": "Kandydat słabszy od aktualnych pozycji portfela",
    "buy_replaced_worst_position": "Rotacja portfela: zastąpiono najsłabszą pozycję",
    "buy_deferred_insufficient_rotation_edge": "Rotacja odroczona: przewaga netto po kosztach za mała",
    "portfolio_rotation_triggered": "Uruchomiono rotację portfela",
    "symbol_not_in_any_tier": "Symbol nie jest w żadnym tierze",
    "hold_mode_no_new_entries": "Symbol w trybie HOLD — nie otwieramy nowych",
    "symbol_cooldown_active": "Cooldown po ostatniej transakcji",
    "insufficient_cash_or_qty_below_min": "Za mało gotówki lub ilość poniżej minimum",
    "cost_gate_failed": "Koszty transakcji zbyt wysokie vs oczekiwany zysk",
    "max_open_positions_gate": "Osiągnięto limit otwartych pozycji",
    "pending_cooldown_active": "Aktywny cooldown zlecenia oczekującego",
    "sell_blocked_no_position": "Brak pozycji do sprzedaży",
    "tp_sl_exit_triggered": "TP/SL osiągnięty — pozycja zamknięta",
    "sync_pending_db_commit": "Synchronizacja oczekuje na commit DB",
    "sync_ignored_fee_asset_residual": "Pominięto residual fee asset (BNB)",
    "sync_ignored_dust_residual": "Pominięto residual pyłu poniżej progu",
    "sync_detected_real_mismatch": "Wykryto rzeczywistą niezgodność Binance↔DB",
    "min_notional_guard": "Wartość zlecenia poniżej minimum giełdowego",
    "tp_hit": "Take Profit osiągnięty — pozycja zamknięta",
    "sl_hit": "Stop Loss osiągnięty — pozycja zamknięta",
    "trailing_stop_hit": "Trailing Stop — pozycja zamknięta",
    "manual_close": "Ręczne zamknięcie pozycji",
    "partial_close": "Częściowe zamknięcie pozycji",
    "hold_target_reached": "Cel portfelowy HOLD osiągnięty",
    "no_trace": "Brak decyzji w tym oknie",
}

_EXIT_REASON_CODES = {
    "tp_hit",
    "sl_hit",
    "trailing_stop_hit",
    "manual_close",
    "partial_close",
    "hold_target_reached",
    "tp_sl_exit_triggered",
}
_BUY_REASON_CODES = {"all_gates_passed", "pending_confirmed_execution"}


@router.get("/bot-activity")
def get_bot_activity(
    mode: str = Query("live"),
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
            icon = (
                "✅"
                if t.reason_code in _BUY_REASON_CODES
                else ("🔴" if t.reason_code in _EXIT_REASON_CODES else "⏳")
            )
            last_actions.append(
                {
                    "symbol": t.symbol,
                    "reason_code": t.reason_code,
                    "description": f"{icon} {t.symbol}: {desc_pl}",
                    "action_type": t.action_type,
                    "ts": t.timestamp.isoformat() if t.timestamp else None,
                }
            )
            if len(last_actions) >= 3:
                break

        # Otwarte pozycje z bieżącym kursem
        positions_raw = db.query(Position).filter(Position.mode == mode).all()
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
            open_positions.append(
                {
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
                }
            )

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
        raise HTTPException(
            status_code=500, detail=f"Error getting bot activity: {str(e)}"
        )


@router.get("/runtime-activity")
def get_runtime_activity(
    mode: str = Query("live"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Runtime heartbeat bota: co robi teraz, kiedy była ostatnia decyzja,
    ostatni order, świeżość danych i status workerów.
    """
    try:
        now = utc_now_naive()
        since_15m = now - timedelta(minutes=15)

        collector_running = False
        ws_running = False
        watchlist_count = 0
        collector_last_snapshot_ts = None
        collector_last_learning_ts = None
        collector_last_binance_sync_ts = None

        if request is not None:
            state = getattr(getattr(request, "app", None), "state", None)
            coll_obj = getattr(state, "collector", None) if state is not None else None
            if coll_obj is not None:
                collector_running = bool(getattr(coll_obj, "running", False))
                ws_running = bool(getattr(coll_obj, "ws_running", False))
                watchlist = getattr(coll_obj, "watchlist", []) or []
                watchlist_count = len(watchlist) if isinstance(watchlist, list) else 0

                last_snapshot_ts = getattr(coll_obj, "last_snapshot_ts", None)
                if isinstance(last_snapshot_ts, datetime):
                    collector_last_snapshot_ts = last_snapshot_ts.isoformat()

                last_learning_ts = getattr(coll_obj, "last_learning_ts", None)
                if isinstance(last_learning_ts, datetime):
                    collector_last_learning_ts = last_learning_ts.isoformat()

                last_sync_ts = getattr(coll_obj, "_last_binance_sync_ts", None)
                if isinstance(last_sync_ts, datetime):
                    collector_last_binance_sync_ts = last_sync_ts.isoformat()

        worker_status = get_worker_status() or {}

        last_md = db.query(MarketData).order_by(desc(MarketData.timestamp)).first()
        symbols_with_data = db.query(MarketData.symbol).distinct().count()
        last_tick_ts = last_md.timestamp.isoformat() if last_md else None
        last_tick_age_s = None
        data_stale = True
        if last_md and last_md.timestamp:
            age = (now - last_md.timestamp).total_seconds()
            last_tick_age_s = int(age)
            data_stale = age > 180

        traces_15m = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode, DecisionTrace.timestamp >= since_15m)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(300)
            .all()
        )
        considered_15m = len({t.symbol for t in traces_15m})
        bought_15m = sum(1 for t in traces_15m if t.reason_code in _BUY_REASON_CODES)
        closed_15m = sum(1 for t in traces_15m if t.reason_code in _EXIT_REASON_CODES)
        skipped_15m = len(traces_15m) - bought_15m - closed_15m

        last_trace = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode)
            .order_by(desc(DecisionTrace.timestamp))
            .first()
        )
        last_trace_data = None
        if last_trace is not None:
            last_trace_data = {
                "id": last_trace.id,
                "symbol": last_trace.symbol,
                "action_type": last_trace.action_type,
                "reason_code": last_trace.reason_code,
                "reason_pl": _REASON_PL.get(
                    last_trace.reason_code or "", last_trace.reason_code
                ),
                "timestamp": (
                    last_trace.timestamp.isoformat() if last_trace.timestamp else None
                ),
            }

        recent_traces_rows = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(5)
            .all()
        )
        recent_traces = [
            {
                "symbol": t.symbol,
                "action_type": t.action_type,
                "reason_code": t.reason_code,
                "reason_pl": _REASON_PL.get(t.reason_code or "", t.reason_code),
                "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            }
            for t in recent_traces_rows
        ]

        last_order = (
            db.query(Order)
            .filter(Order.mode == mode)
            .order_by(desc(Order.timestamp))
            .first()
        )
        last_order_data = None
        if last_order is not None:
            last_order_data = {
                "id": last_order.id,
                "symbol": last_order.symbol,
                "side": last_order.side,
                "status": last_order.status,
                "quantity": float(last_order.quantity or 0.0),
                "executed_price": float(last_order.executed_price or 0.0),
                "timestamp": (
                    last_order.timestamp.isoformat() if last_order.timestamp else None
                ),
            }

        last_pending = (
            db.query(PendingOrder)
            .filter(PendingOrder.mode == mode)
            .order_by(desc(PendingOrder.created_at))
            .first()
        )
        last_pending_data = None
        if last_pending is not None:
            last_pending_data = {
                "id": last_pending.id,
                "symbol": last_pending.symbol,
                "side": last_pending.side,
                "status": last_pending.status,
                "quantity": float(last_pending.quantity or 0.0),
                "price": float(last_pending.price or 0.0),
                "created_at": (
                    last_pending.created_at.isoformat()
                    if last_pending.created_at
                    else None
                ),
            }

        last_error = (
            db.query(SystemLog)
            .filter(SystemLog.level == "ERROR")
            .order_by(desc(SystemLog.timestamp))
            .first()
        )
        last_error_data = None
        if last_error is not None:
            last_error_data = {
                "timestamp": (
                    last_error.timestamp.isoformat() if last_error.timestamp else None
                ),
                "message": str(last_error.message or "")[:240],
            }

        alive = bool(collector_running and ws_running and not data_stale)

        return {
            "success": True,
            "data": {
                "mode": mode,
                "alive": alive,
                "collector": {
                    "running": collector_running,
                    "ws_running": ws_running,
                    "watchlist_count": watchlist_count,
                    "last_snapshot_ts": collector_last_snapshot_ts,
                    "last_learning_ts": collector_last_learning_ts,
                    "last_binance_sync_ts": collector_last_binance_sync_ts,
                },
                "worker": worker_status,
                "market_data": {
                    "symbols_with_data": symbols_with_data,
                    "last_tick_ts": last_tick_ts,
                    "last_tick_age_s": last_tick_age_s,
                    "data_stale": data_stale,
                },
                "decision_pipeline_15m": {
                    "considered": considered_15m,
                    "bought": bought_15m,
                    "closed": closed_15m,
                    "skipped": skipped_15m,
                },
                "last_decision": last_trace_data,
                "last_order": last_order_data,
                "last_pending": last_pending_data,
                "last_error": last_error_data,
                "recent_decisions": recent_traces,
                "updated_at": now.isoformat(),
            },
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting runtime activity: {str(e)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# CAPITAL SNAPSHOT — jedyne źródło prawdy dla salda w całym UI
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/capital-snapshot")
def get_capital_snapshot(
    mode: str = Query("live"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Unified capital snapshot — jedno źródło prawdy dla całego UI.

    Zawiera: saldo, wolne środki, pozycje aktywne, dust, cash_assets,
    klasyfikację holdings, freshness, source_of_truth, sync_status.
    """
    try:
        from backend.routers.portfolio import get_portfolio_wealth as _build_wealth

        # Wewnętrznie korzystamy z portfolio endpoint (już ma logikę live/demo)
        # Tworzymy mockowy request jeśli brak
        if request is None:

            class _MockRequest:
                class app:
                    class state:
                        pass

            request = _MockRequest()  # type: ignore

        wealth = (
            _build_wealth.__wrapped__(mode=mode, request=request, db=db)
            if hasattr(_build_wealth, "__wrapped__")
            else None
        )

        # Fallback: bezpośrednie wywołanie przez handler
        if wealth is None:
            from fastapi.testclient import (
                TestClient as _TC,
            )  # noqa: E501 – import only for fallback

            from backend.accounting import compute_demo_account_state

            # Prosta implementacja bezpośrednia zamiast nested call
            from backend.routers.portfolio import _build_live_spot_portfolio

            _DUST = 0.50
            _CASH = {"EUR", "USDT", "USDC", "BUSD", "DAI", "USDP", "TUSD"}

            if mode == "live":
                live_data = _build_live_spot_portfolio(db)
                if live_data and not live_data.get("error"):
                    items = live_data.get("items", live_data.get("spot_positions", []))
                    total_equity = float(
                        live_data.get("total_equity")
                        or live_data.get("total_equity_eur")
                        or 0
                    )
                    free_cash = float(
                        live_data.get("free_cash")
                        or live_data.get("free_cash_eur")
                        or 0
                    )
                    source_of_truth = "binance_live"
                    sync_status = "ok"
                    sync_warning = None
                else:
                    items = []
                    total_equity = 0.0
                    free_cash = 0.0
                    source_of_truth = "local_db"
                    sync_status = "binance_unavailable"
                    sync_warning = (live_data or {}).get(
                        "error"
                    ) or "Brak połączenia z Binance"
            else:
                demo_state = compute_demo_account_state(
                    db, quote_ccy=get_demo_quote_ccy()
                )
                items = []
                total_equity = float(demo_state.get("equity", 0))
                free_cash = float(
                    demo_state.get("free_cash", demo_state.get("free_margin", 0))
                )
                source_of_truth = "demo_local"
                sync_status = "demo"
                sync_warning = None

            def _is_dust(it: dict) -> bool:
                return float(it.get("value_eur") or 0) < _DUST

            def _is_cash(it: dict) -> bool:
                return str(it.get("asset") or it.get("symbol") or "").upper() in _CASH

            active_items = [i for i in items if not _is_dust(i) and not _is_cash(i)]
            dust_items = [i for i in items if _is_dust(i) and not _is_cash(i)]
            cash_items = [i for i in items if _is_cash(i)]

            active_value = sum(float(i.get("value_eur") or 0) for i in active_items)
            dust_value = sum(float(i.get("value_eur") or 0) for i in dust_items)

            now = utc_now_naive()
            updated_at = now.isoformat()
            age_seconds = 0

            holdings = []
            for it in items:
                asset = str(it.get("asset") or it.get("symbol") or "")
                val = float(it.get("value_eur") or 0)
                if _is_cash(it):
                    cls = "cash"
                elif _is_dust(it):
                    cls = "dust"
                elif val > 0:
                    cls = "active_position"
                else:
                    cls = "other"
                holdings.append(
                    {
                        "asset": asset,
                        "free": float(it.get("free") or it.get("quantity") or 0),
                        "locked": float(it.get("locked") or 0),
                        "total": float(it.get("total") or it.get("quantity") or 0),
                        "value_in_base": round(val, 4),
                        "classification": cls,
                    }
                )

            wealth = {
                "mode": mode,
                "base_currency": "EUR",
                "free_cash": round(free_cash, 4),
                "locked_cash": 0.0,
                "total_account_value": round(total_equity, 4),
                "active_positions_value": round(active_value, 4),
                "dust_value": round(dust_value, 4),
                "available_to_trade": round(free_cash, 4),
                "open_orders_reserved": 0.0,
                "active_positions_count": len(active_items),
                "dust_positions_count": len(dust_items),
                "cash_assets_count": len(cash_items),
                "all_assets_count": len(items),
                "sync_status": sync_status,
                "sync_warning": sync_warning,
                "updated_at": updated_at,
                "source_of_truth": source_of_truth,
                "age_seconds": age_seconds,
                "stale": False,
                "holdings_breakdown": holdings,
            }
        else:
            # Wzbogacamy odpowiedź portfolio o pola capital_snapshot
            _DUST = 0.50
            _CASH = {"EUR", "USDT", "USDC", "BUSD", "DAI", "USDP", "TUSD"}
            items = wealth.get("items", [])

            def _is_dust(it: dict) -> bool:
                return float(it.get("value_eur") or 0) < _DUST

            def _is_cash(it: dict) -> bool:
                return str(it.get("asset") or it.get("symbol") or "").upper() in _CASH

            active_items = [i for i in items if not _is_dust(i) and not _is_cash(i)]
            dust_items = [i for i in items if _is_dust(i) and not _is_cash(i)]
            cash_items = [i for i in items if _is_cash(i)]
            active_value = sum(float(i.get("value_eur") or 0) for i in active_items)
            dust_value = sum(float(i.get("value_eur") or 0) for i in dust_items)
            free_cash = float(wealth.get("free_cash") or 0)
            total_equity = float(wealth.get("total_equity") or 0)
            now = utc_now_naive()
            holdings = [
                {
                    "asset": str(i.get("asset") or i.get("symbol") or ""),
                    "free": float(i.get("free") or i.get("quantity") or 0),
                    "locked": float(i.get("locked") or 0),
                    "total": float(i.get("total") or i.get("quantity") or 0),
                    "value_in_base": round(float(i.get("value_eur") or 0), 4),
                    "classification": (
                        "cash"
                        if _is_cash(i)
                        else (
                            "dust"
                            if _is_dust(i)
                            else (
                                "active_position"
                                if float(i.get("value_eur") or 0) > 0
                                else "other"
                            )
                        )
                    ),
                }
                for i in items
            ]
            wealth = {
                "mode": mode,
                "base_currency": "EUR",
                "free_cash": round(free_cash, 4),
                "locked_cash": 0.0,
                "total_account_value": round(total_equity, 4),
                "active_positions_value": round(active_value, 4),
                "dust_value": round(dust_value, 4),
                "available_to_trade": round(free_cash, 4),
                "open_orders_reserved": 0.0,
                "active_positions_count": len(active_items),
                "dust_positions_count": len(dust_items),
                "cash_assets_count": len(cash_items),
                "all_assets_count": len(items),
                "sync_status": "ok",
                "sync_warning": None,
                "updated_at": now.isoformat(),
                "source_of_truth": "portfolio_router",
                "age_seconds": 0,
                "stale": False,
                "holdings_breakdown": holdings,
            }

        return {"success": True, "data": wealth}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd capital-snapshot: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# TRADING STATUS — unified execution pipeline state + blockers
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/trading-status")
def get_trading_status(
    mode: str = Query("live"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    """
    Pełny status pipeline handlowego: co jest włączone, co jest zablokowane,
    ile kandydatów przeszło przez kolejne etapy, ostatnia decyzja, lista blokad.

    Używany do panelu diagnostycznego 'Dlaczego bot nie handluje?'.
    """
    try:
        from backend.runtime_settings import build_runtime_state, get_runtime_config

        # --- Konfiguracja runtime ---
        cfg = get_runtime_config(db)
        trading_mode_cfg = cfg.get("trading_mode", "demo")
        allow_live = bool(cfg.get("allow_live_trading", False))
        demo_enabled = bool(cfg.get("demo_trading_enabled", True))
        max_cert = bool(cfg.get("max_certainty_mode", False))
        hold_only = bool(cfg.get("hold_mode", False))
        ws_enabled = bool(os.getenv("WS_ENABLED", "true").lower() in ("true", "1"))

        trading_enabled = demo_enabled if mode == "demo" else allow_live
        live_trading_enabled = allow_live

        # --- Collector / WS status ---
        collector_running = False
        ws_running = False
        if request is not None:
            coll = getattr(getattr(request, "app", None), "state", None)
            if coll:
                coll_obj = getattr(coll, "collector", None)
                if coll_obj:
                    collector_running = bool(getattr(coll_obj, "running", False))
                    ws_running = bool(getattr(coll_obj, "ws_running", False))

        # --- Binance połączenie ---
        bc = get_binance_client()
        exchange_connected = bc is not None

        # --- Dane rynkowe ---
        last_md = db.query(MarketData).order_by(desc(MarketData.timestamp)).first()
        last_tick_age_s = None
        data_stale = True
        if last_md:
            age = (utc_now_naive() - last_md.timestamp).total_seconds()
            last_tick_age_s = int(age)
            data_stale = age > 300

        # --- Ostatnie decyzje ---
        since_15m = utc_now_naive() - timedelta(minutes=15)
        recent_traces = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.mode == mode, DecisionTrace.timestamp >= since_15m)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(200)
            .all()
        )

        considered = len({t.symbol for t in recent_traces})
        bought = sum(1 for t in recent_traces if t.reason_code in _BUY_REASON_CODES)
        closed = sum(1 for t in recent_traces if t.reason_code in _EXIT_REASON_CODES)
        skipped = sum(
            1
            for t in recent_traces
            if t.reason_code not in _BUY_REASON_CODES | _EXIT_REASON_CODES
        )

        last_trace = recent_traces[0] if recent_traces else None
        last_decision_time = last_trace.timestamp.isoformat() if last_trace else None
        last_attempted_symbol = last_trace.symbol if last_trace else None
        last_attempted_action = last_trace.action_type if last_trace else None
        last_rejection_reason = last_trace.reason_code if last_trace else None

        # --- Ostatni błąd ---
        last_err = (
            db.query(SystemLog)
            .filter(
                SystemLog.level == "ERROR",
                SystemLog.module.in_(["live_trading", "orders", "positions"]),
            )
            .order_by(desc(SystemLog.timestamp))
            .first()
        )
        last_order_error = last_err.message[:200] if last_err else None

        # --- Wolne środki ---
        snap = (
            db.query(AccountSnapshot)
            .filter(AccountSnapshot.mode == mode)
            .order_by(desc(AccountSnapshot.timestamp))
            .first()
        )
        equity = float(snap.equity) if snap else None
        free_cash_snap = (
            float(snap.free_margin) if snap and snap.free_margin is not None else None
        )

        # --- Zbieranie blokad ---
        blockers = []
        now = utc_now_naive().isoformat()

        if not trading_enabled:
            blockers.append(
                {
                    "code": (
                        "TRADING_DISABLED"
                        if mode == "demo"
                        else "LIVE_TRADING_DISABLED"
                    ),
                    "stage": "config",
                    "severity": "critical",
                    "symbol": None,
                    "message": f"Handel {'demo' if mode == 'demo' else 'live'} jest wyłączony w konfiguracji",
                    "timestamp": now,
                }
            )

        if mode == "live" and not allow_live:
            blockers.append(
                {
                    "code": "LIVE_TRADING_DISABLED",
                    "stage": "config",
                    "severity": "critical",
                    "symbol": None,
                    "message": "allow_live_trading=false — handel live zablokowany",
                    "timestamp": now,
                }
            )

        if mode == "live" and not exchange_connected:
            blockers.append(
                {
                    "code": "EXCHANGE_UNAVAILABLE",
                    "stage": "exchange",
                    "severity": "critical",
                    "symbol": None,
                    "message": "Brak klienta Binance — brak kluczy API lub błąd połączenia",
                    "timestamp": now,
                }
            )

        if not ws_enabled:
            blockers.append(
                {
                    "code": "WEBSOCKET_DISABLED",
                    "stage": "data",
                    "severity": "warning",
                    "symbol": None,
                    "message": "WebSocket wyłączony w konfiguracji (WS_ENABLED=false)",
                    "timestamp": now,
                }
            )

        if data_stale:
            age_str = (
                f"{last_tick_age_s}s" if last_tick_age_s is not None else "unknown"
            )
            blockers.append(
                {
                    "code": (
                        "NO_MARKET_DATA" if last_md is None else "MARKET_DATA_STALE"
                    ),
                    "stage": "data",
                    "severity": "warning" if last_md else "critical",
                    "symbol": None,
                    "message": f"Dane rynkowe są stare lub brakujące (wiek: {age_str})",
                    "timestamp": now,
                }
            )

        if max_cert:
            blockers.append(
                {
                    "code": "MAX_CERTAINTY_MODE",
                    "stage": "signal",
                    "severity": "warning",
                    "symbol": None,
                    "message": "Tryb MAX_CERTAINTY aktywny — wymagany bardzo wysoki poziom pewności",
                    "timestamp": now,
                }
            )

        if hold_only:
            blockers.append(
                {
                    "code": "HOLD_MODE_ACTIVE",
                    "stage": "signal",
                    "severity": "warning",
                    "symbol": None,
                    "message": "Tryb HOLD aktywny — nowe wejścia wstrzymane",
                    "timestamp": now,
                }
            )

        # Kody non-blocker — to są informacyjne trace'y, nie blokady handlu
        _NON_BLOCKER_REASONS = {
            "sync_ignored_dust_residual",
            "sync_ignored_fee_asset_residual",
            "sync_pending_db_commit",
            "waiting_next_collector_cycle",
            "temporary_execution_error",
            "cash_convert_failed",
            "cash_insufficient_after_conversion_attempt",
            "governance_freeze_critical_only",
        }
        # Sprawdź ostatnie rejection_reason z traces
        if (
            last_rejection_reason
            and last_rejection_reason not in _BUY_REASON_CODES | _EXIT_REASON_CODES
            and last_rejection_reason not in _NON_BLOCKER_REASONS
        ):
            _REJECTION_LABELS = {
                "signal_filters_not_met": "Filtry sygnału nie spełnione",
                "signal_confidence_too_low": "Zbyt niska pewność sygnału",
                "regime_blocked": "Blokada reżimu rynkowego (CHAOS/nieznany)",
                "cooldown_active": "Cooldown aktywny dla symbolu",
                "max_positions_reached": "Osiągnięto maksymalną liczbę pozycji",
                "cost_gate_blocked": "Koszt transakcji zbyt wysoki względem zysku",
                "risk_gate_blocked": "Bramka ryzyka zablokowana",
                "min_notional_not_met": "Zbyt mały rozmiar zlecenia (minNotional)",
                "missing_binance_price": "Brak ceny z Binance dla symbolu",
                "no_trend_confirmation": "Brak potwierdzenia trendu",
                "sell_blocked_no_position": "SELL niemożliwy — brak otwartej pozycji",
                "insufficient_edge_after_costs": "Niewystarczający edge netto po kosztach",
                "cash_convert_failed": "Automatyczna konwersja EUR→USDC nie powiodła się",
                "cash_insufficient_after_conversion_attempt": "Brak środków po próbie konwersji EUR→USDC",
                "execution_rejected_by_exchange": "Giełda odrzuciła zlecenie wykonania",
                "temporary_execution_error": "Tymczasowy błąd wykonania (bez trwałego freeze)",
            }
            label = _REJECTION_LABELS.get(
                last_rejection_reason, f"Ostatnia blokada: {last_rejection_reason}"
            )
            blockers.append(
                {
                    "code": last_rejection_reason.upper(),
                    "stage": "execution",
                    "severity": "info",
                    "symbol": last_attempted_symbol,
                    "message": label,
                    "timestamp": last_decision_time or now,
                }
            )

        available_to_trade = trading_enabled and not data_stale and exchange_connected
        status_color = (
            "green"
            if (available_to_trade and not blockers)
            else (
                "yellow"
                if blockers and all(b["severity"] != "critical" for b in blockers)
                else "red"
            )
        )

        return {
            "success": True,
            "data": {
                "mode": mode,
                "trading_enabled": trading_enabled,
                "live_trading_enabled": live_trading_enabled,
                "exchange_connected": exchange_connected,
                "websocket_enabled": ws_enabled,
                "collector_running": collector_running,
                "data_stale": data_stale,
                "last_tick_age_s": last_tick_age_s,
                "available_to_trade": available_to_trade,
                "status_color": status_color,
                "max_certainty_mode": max_cert,
                "hold_mode": hold_only,
                "candidate_count": considered,
                "bought_count_15m": bought,
                "closed_count_15m": closed,
                "skipped_count_15m": skipped,
                "last_decision_time": last_decision_time,
                "last_attempted_symbol": last_attempted_symbol,
                "last_attempted_action": last_attempted_action,
                "last_rejection_reason": last_rejection_reason,
                "last_order_error": last_order_error,
                "equity": equity,
                "free_cash_snap": free_cash_snap,
                "blockers": blockers,
                "blockers_count": len(blockers),
                "updated_at": utc_now_naive().isoformat(),
                "age_seconds": 0,
                "stale": False,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd trading-status: {str(e)}")


@router.get("/funding-diagnostics")
def get_funding_diagnostics(db: Session = Depends(get_db)):
    """
    Diagnostyka finansowania: saldo EUR vs USDC, status auto-konwersji,
    watchlista, świeżość sygnałów.
    """
    import time as _time

    from backend.binance_client import get_binance_client
    from backend.database import Signal
    from backend.quote_currency import should_convert_eur_to_usdc

    result: Dict[str, Any] = {
        "timestamp": utc_now_naive().isoformat(),
        "balances": {},
        "conversion": {},
        "watchlist": [],
        "signal_freshness": {},
        "diagnosis": [],
    }

    # Salda
    binance = get_binance_client()
    free_eur = 0.0
    free_usdc = 0.0
    try:
        balances = binance.get_balances() or []
        for b in balances:
            asset = str(b.get("asset", "")).upper()
            free_v = float(b.get("free", 0) or 0)
            if asset == "EUR":
                free_eur = free_v
            elif asset == "USDC":
                free_usdc = free_v
        result["balances"] = {
            "free_eur": round(free_eur, 4),
            "free_usdc": round(free_usdc, 4),
            "raw": [
                {"asset": b.get("asset"), "free": float(b.get("free", 0) or 0)}
                for b in balances
                if float(b.get("free", 0) or 0) > 0.00001
            ],
        }
    except Exception as exc:
        result["balances"]["error"] = str(exc)

    # Konfiguracja konwersji
    allow_conv = os.getenv(
        "ALLOW_AUTO_CONVERT_EUR_TO_USDC", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    min_eur_reserve = float(os.getenv("MIN_EUR_RESERVE", "50") or 50)
    target_usdc = float(os.getenv("TARGET_USDC_BUFFER", "150") or 150)
    min_conv_notional = float(os.getenv("MIN_CONVERSION_NOTIONAL", "20") or 20)
    cooldown_m = int(os.getenv("CONVERSION_COOLDOWN_MINUTES", "30") or 30)
    max_per_hour = int(os.getenv("MAX_CONVERSION_PER_HOUR", "3") or 3)
    should_conv, conv_reason, conv_amount = should_convert_eur_to_usdc(
        free_eur=free_eur,
        free_usdc=free_usdc,
        target_usdc_buffer=target_usdc,
        min_eur_reserve=min_eur_reserve,
        min_conversion_notional=min_conv_notional,
        conversion_cooldown_minutes=cooldown_m,
        max_conversion_per_hour=max_per_hour,
    )
    result["conversion"] = {
        "allow_auto_convert": allow_conv,
        "should_convert_now": should_conv,
        "reason_code": conv_reason,
        "amount_eur": conv_amount,
        "min_eur_reserve": min_eur_reserve,
        "target_usdc_buffer": target_usdc,
        "mode": os.getenv("QUOTE_CURRENCY_MODE", "BOTH"),
        "primary_quote": os.getenv("PRIMARY_QUOTE", "EUR"),
    }

    # Watchlista i świeżość sygnałów
    watchlist_raw = os.getenv("WATCHLIST", "")
    watchlist = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()]
    result["watchlist"] = watchlist
    now_ts = _time.time()
    max_signal_age = 3600
    sig_freshness = {}
    from backend.database import Signal

    for base_sym in watchlist:
        sym = f"{base_sym}USDC"
        sig = (
            db.query(Signal)
            .filter(Signal.symbol == sym)
            .order_by(Signal.timestamp.desc())
            .first()
        )
        if sig and sig.timestamp:
            import datetime as _dt

            sig_ts = (
                sig.timestamp.replace(tzinfo=_dt.timezone.utc).timestamp()
                if sig.timestamp.tzinfo is None
                else sig.timestamp.timestamp()
            )
            age_s = round(now_ts - sig_ts)
            sig_freshness[sym] = {
                "age_seconds": age_s,
                "fresh": age_s <= max_signal_age,
                "signal_type": sig.signal_type,
                "confidence": round(float(sig.confidence or 0), 3),
            }
        else:
            sig_freshness[sym] = {
                "age_seconds": None,
                "fresh": False,
                "signal_type": None,
            }
    result["signal_freshness"] = sig_freshness

    # Diagnoza — co blokuje
    diags = []
    if free_usdc < 25 and free_eur > 25:
        if allow_conv:
            diags.append(
                {
                    "level": "WARN",
                    "msg": f"USDC={free_usdc:.4f} — zbyt mało, konwersja EUR→USDC automatyczna (ALLOW=true). Nastąpi przy następnym cyklu kolekcji.",
                }
            )
        else:
            diags.append(
                {
                    "level": "ERROR",
                    "msg": f"USDC={free_usdc:.4f} ale ALLOW_AUTO_CONVERT_EUR_TO_USDC=false. "
                    "Pary USDC będą zablokowane. Włącz konwersję lub przenieś USDC ręcznie.",
                }
            )
    if free_usdc >= 25:
        diags.append(
            {
                "level": "OK",
                "msg": f"USDC={free_usdc:.2f} — wystarczy na handel USDC pairs",
            }
        )
    stale_syms = [s for s, v in sig_freshness.items() if not v["fresh"]]
    if stale_syms:
        diags.append(
            {"level": "WARN", "msg": f"Stare/brak sygnałów: {', '.join(stale_syms)}"}
        )
    result["diagnosis"] = diags
    return result
