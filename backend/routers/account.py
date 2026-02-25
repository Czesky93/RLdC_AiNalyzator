"""
Account API Router - endpoints dla danych konta (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional
from datetime import datetime, timedelta
import os
import re
import requests
import hashlib

from backend.database import get_db, AccountSnapshot, Position, SystemLog, reset_database
from backend.binance_client import get_binance_client
from backend.accounting import compute_demo_account_state, get_demo_quote_ccy
from backend.auth import require_admin

router = APIRouter()

_openai_status_cache: dict = {"ts": None, "data": None}
_demo_state_cache: dict = {"ts": None, "data": None}


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
        max_daily_loss_pct = float(os.getenv("MAX_DAILY_LOSS_PERCENT", "5.0"))
        max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PERCENT", "10.0"))
        if mode != "demo":
            # LIVE: zachowaj dotychczasowe zachowanie (pozycje są read-only).
            initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000"))
            positions = db.query(Position).filter(Position.mode == mode).all()
            unrealized_pnl = sum((p.unrealized_pnl or 0.0) for p in positions)
            worst_dd = 0.0
            for p in positions:
                if p.entry_price and p.current_price and p.entry_price > 0:
                    dd = ((p.current_price - p.entry_price) / p.entry_price) * 100
                    if dd < worst_dd:
                        worst_dd = dd
            daily_loss_limit = -(initial_balance * max_daily_loss_pct / 100)
            daily_loss_triggered = unrealized_pnl <= daily_loss_limit
            drawdown_triggered = worst_dd <= -max_drawdown_pct
            return {
                "success": True,
                "mode": mode,
                "data": {
                    "initial_balance": initial_balance,
                    "max_daily_loss_pct": max_daily_loss_pct,
                    "max_drawdown_pct": max_drawdown_pct,
                    "unrealized_pnl": round(unrealized_pnl, 2),
                    "daily_loss_limit": round(daily_loss_limit, 2),
                    "worst_drawdown_pct": round(worst_dd, 2),
                    "daily_loss_triggered": daily_loss_triggered,
                    "drawdown_triggered": drawdown_triggered,
                    "positions_count": len(positions),
                },
            }

        state = _cached_demo_state(db)
        initial_balance = float(state.get("initial_balance") or float(os.getenv("DEMO_INITIAL_BALANCE", "10000")))
        unrealized_pnl = float(state.get("unrealized_pnl") or 0.0)
        realized_pnl_24h = float(state.get("realized_pnl_24h") or 0.0)
        realized_pnl_total = float(state.get("realized_pnl_total") or 0.0)

        worst_dd = 0.0
        for p in (state.get("positions") or []):
            try:
                entry = float(p.get("avg_entry") or 0.0)
                cur = float(p.get("current_price") or 0.0)
                if entry > 0:
                    dd = ((cur - entry) / entry) * 100
                    if dd < worst_dd:
                        worst_dd = dd
            except Exception:
                continue

        daily_loss_limit = -(initial_balance * max_daily_loss_pct / 100)
        pnl_24h = realized_pnl_24h + unrealized_pnl
        daily_loss_triggered = pnl_24h <= daily_loss_limit
        drawdown_triggered = worst_dd <= -max_drawdown_pct

        return {
            "success": True,
            "mode": mode,
            "data": {
                "initial_balance": initial_balance,
                "max_daily_loss_pct": max_daily_loss_pct,
                "max_drawdown_pct": max_drawdown_pct,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "realized_pnl_24h": round(realized_pnl_24h, 2),
                "realized_pnl_total": round(realized_pnl_total, 2),
                "pnl_24h": round(pnl_24h, 2),
                "daily_loss_limit": round(daily_loss_limit, 2),
                "worst_drawdown_pct": round(worst_dd, 2),
                "daily_loss_triggered": daily_loss_triggered,
                "drawdown_triggered": drawdown_triggered,
                "positions_count": len(state.get("positions") or []),
                "quote_ccy": state.get("quote_ccy"),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting risk summary: {str(e)}")


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
