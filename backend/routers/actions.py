"""
Actions API — szybkie akcje operatorskie i czat AI.

Endpointy:
  POST /api/actions/analyze-now        — wymuś analizę rynku teraz
  POST /api/actions/scan-opportunities — skanuj okazje
  POST /api/actions/recompute-signals  — przelicz sygnały
  POST /api/actions/check-errors       — sprawdź błędy systemu
  POST /api/actions/restart-collector  — restart collectora
  POST /api/actions/generate-report    — generuj raport
  POST /api/actions/check-binance      — test połączenia z Binance
  POST /api/actions/check-telegram     — test połączenia z Telegramem
  POST /api/actions/check-ai           — test połączenia z AI
  POST /api/actions/force-sync         — wymuszony sync portfela
  POST /api/actions/check-positions    — aktywne pozycje z PnL/SL/TP
  POST /api/actions/check-sl-tp        — ostrzeżenia SL (pozycje blisko SL)
  POST /api/actions/save-snapshot      — zapisz snapshot equity
  POST /api/ai/chat                    — czat AI dla operatora
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import require_admin
from backend.database import Order, Position, Signal, SystemLog, get_db, utc_now_naive
from backend.system_logger import log_to_db

router = APIRouter()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _log_action(actor: str, action: str, result: str, db: Session):
    log_to_db(
        level="INFO",
        module=f"operator_action:{action}",
        message=f"[{actor}] {action} → {result}",
        db=db,
    )


def _actor(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"operator:{host}"


# ─────────────────────────────────────────────
# Modele
# ─────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None  # "signals" | "errors" | "positions" | "all"


class ActionResult(BaseModel):
    success: bool
    action: str
    message: str
    data: Optional[Any] = None
    timestamp: str = ""

    def __init__(self, **data):
        if not data.get("timestamp"):
            data["timestamp"] = datetime.now(timezone.utc).isoformat()
        super().__init__(**data)


# ─────────────────────────────────────────────
# Akcje
# ─────────────────────────────────────────────

@router.post("/analyze-now")
def analyze_now(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Wymusza uruchomienie pełnego cyklu kolektora."""
    actor = _actor(request)
    collector = getattr(request.app.state, "collector", None)
    if collector is None:
        _log_action(actor, "analyze-now", "collector_not_running", db)
        return ActionResult(
            success=False,
            action="analyze-now",
            message="Kolektor nie jest uruchomiony.",
        )
    try:
        import threading
        result_holder: dict = {}

        def _run():
            from backend.database import SessionLocal
            sess = SessionLocal()
            try:
                collector.run_once()
                result_holder["ok"] = True
            except Exception as exc:
                result_holder["error"] = str(exc)
            finally:
                sess.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=15)

        if result_holder.get("ok"):
            _log_action(actor, "analyze-now", "ok", db)
            return ActionResult(
                success=True,
                action="analyze-now",
                message="Cykl analizy uruchomiony i zakończony.",
            )
        elif "error" in result_holder:
            _log_action(actor, "analyze-now", f"error: {result_holder['error'][:80]}", db)
            return ActionResult(
                success=False,
                action="analyze-now",
                message=f"Błąd cyklu: {result_holder['error'][:200]}",
            )
        else:
            _log_action(actor, "analyze-now", "timeout", db)
            return ActionResult(
                success=True,
                action="analyze-now",
                message="Cykl analizy uruchomiony (timeout — działa w tle).",
            )
    except Exception as exc:
        _log_action(actor, "analyze-now", f"exception: {str(exc)[:80]}", db)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/scan-opportunities")
def scan_opportunities(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Skanuje rynek i zwraca top okazji z aktualnych sygnałów."""
    actor = _actor(request)
    try:
        signals = (
            db.query(Signal)
            .filter(Signal.signal_type.in_(["BUY", "SELL"]))
            .order_by(Signal.confidence.desc())
            .limit(20)
            .all()
        )
        top = [
            {
                "symbol": s.symbol,
                "type": s.signal_type,
                "confidence": round(float(s.confidence or 0), 4),
                "price": float(s.price or 0),
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            }
            for s in signals
        ]
        _log_action(actor, "scan-opportunities", f"found {len(top)} signals", db)
        return ActionResult(
            success=True,
            action="scan-opportunities",
            message=f"Znaleziono {len(top)} sygnałów.",
            data={"signals": top, "count": len(top)},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/recompute-signals")
def recompute_signals(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Przelicza sygnały dla wszystkich symboli z watchlisty."""
    actor = _actor(request)
    collector = getattr(request.app.state, "collector", None)
    watchlist = getattr(collector, "watchlist", []) if collector else []

    try:
        from backend.analysis import maybe_generate_insights_and_blog

        insights_data = maybe_generate_insights_and_blog(db, force=True)
        _log_action(actor, "recompute-signals", "ok", db)
        return ActionResult(
            success=True,
            action="recompute-signals",
            message=f"Sygnały przeliczone dla {len(watchlist)} symboli watchlisty.",
            data={"watchlist": list(watchlist)[:20], "insights": bool(insights_data)},
        )
    except Exception as exc:
        _log_action(actor, "recompute-signals", f"error: {str(exc)[:80]}", db)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/check-errors")
def check_errors(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Zwraca ostatnie błędy z systemu."""
    actor = _actor(request)
    errors = (
        db.query(SystemLog)
        .filter(SystemLog.level.in_(["ERROR", "WARNING"]))
        .order_by(SystemLog.id.desc())
        .limit(30)
        .all()
    )
    result = [
        {
            "id": e.id,
            "level": e.level,
            "module": e.module,
            "message": (e.message or "")[:300],
            "exception": (e.exception or "")[:200] if e.exception else None,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in errors
    ]
    _log_action(actor, "check-errors", f"found {len(result)} issues", db)
    return ActionResult(
        success=True,
        action="check-errors",
        message=f"Znaleziono {len(result)} błędów/ostrzeżeń (ostatnie 30).",
        data={"errors": result, "count": len(result)},
    )


@router.post("/restart-collector")
def restart_collector(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Zatrzymuje i uruchamia ponownie kolektor danych."""
    actor = _actor(request)
    collector = getattr(request.app.state, "collector", None)
    if collector is None:
        return ActionResult(
            success=False,
            action="restart-collector",
            message="Kolektor nie jest zarejestrowany w stanie aplikacji.",
        )
    try:
        import threading

        collector.stop()
        time.sleep(1)
        t = threading.Thread(target=collector.start, daemon=True)
        t.start()
        _log_action(actor, "restart-collector", "restarted", db)
        return ActionResult(
            success=True,
            action="restart-collector",
            message="Kolektor zrestartowany pomyślnie.",
        )
    except Exception as exc:
        _log_action(actor, "restart-collector", f"error: {str(exc)[:80]}", db)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/generate-report")
def generate_report(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Generuje snapshot stanu systemu do logu."""
    actor = _actor(request)
    try:
        from backend.accounting import take_snapshot

        mode = os.getenv("TRADING_MODE", "demo")
        snap = take_snapshot(db, mode=mode)
        _log_action(actor, "generate-report", f"snapshot_id={getattr(snap, 'id', '?')}", db)
        return ActionResult(
            success=True,
            action="generate-report",
            message=f"Snapshot konta zapisany (tryb: {mode}).",
            data={"snapshot_id": getattr(snap, "id", None)},
        )
    except Exception as exc:
        _log_action(actor, "generate-report", f"error: {str(exc)[:80]}", db)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/check-binance")
def check_binance(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Testuje połączenie z Binance API."""
    actor = _actor(request)
    try:
        from backend.binance_client import BinanceClient

        b = BinanceClient()
        ticker = b.get_ticker_price("BTCUSDT")
        price = float(ticker.get("price", 0)) if ticker else None
        if price:
            _log_action(actor, "check-binance", f"ok BTC={price}", db)
            return ActionResult(
                success=True,
                action="check-binance",
                message=f"Binance API działa. BTC/USDT = {price:,.2f}",
                data={"btc_price": price, "status": "online"},
            )
        else:
            return ActionResult(
                success=False,
                action="check-binance",
                message="Binance API: brak ceny (prawdopodobny błąd klucza API lub limitów).",
                data={"status": "error"},
            )
    except Exception as exc:
        _log_action(actor, "check-binance", f"error: {str(exc)[:80]}", db)
        return ActionResult(
            success=False,
            action="check-binance",
            message=f"Błąd połączenia z Binance: {str(exc)[:200]}",
            data={"status": "error"},
        )


@router.post("/check-telegram")
def check_telegram(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Testuje konfigurację Telegram."""
    actor = _actor(request)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        return ActionResult(
            success=False,
            action="check-telegram",
            message="TELEGRAM_BOT_TOKEN nie jest ustawiony w .env.",
        )
    if not chat_id:
        return ActionResult(
            success=False,
            action="check-telegram",
            message="TELEGRAM_CHAT_ID nie jest ustawiony w .env.",
        )
    try:
        import requests as req_lib

        resp = req_lib.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=5,
        )
        if resp.status_code == 200:
            bot_name = resp.json().get("result", {}).get("username", "?")
            _log_action(actor, "check-telegram", f"ok bot=@{bot_name}", db)
            return ActionResult(
                success=True,
                action="check-telegram",
                message=f"Telegram API działa. Bot: @{bot_name}",
                data={"bot_username": bot_name, "chat_id": chat_id, "status": "online"},
            )
        else:
            return ActionResult(
                success=False,
                action="check-telegram",
                message=f"Telegram API zwrócił status {resp.status_code}.",
            )
    except Exception as exc:
        return ActionResult(
            success=False,
            action="check-telegram",
            message=f"Błąd połączenia z Telegram: {str(exc)[:200]}",
        )


@router.post("/check-ai")
def check_ai(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Sprawdza konfigurację AI — wszystkich providerów (OpenAI, Gemini, Groq, heurystyka)."""
    actor = _actor(request)
    import requests as req_lib

    provider_cfg = os.getenv("AI_PROVIDER", "auto").strip().lower()
    results: dict = {}

    # --- OpenAI ---
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            r = req_lib.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {openai_key}"},
                timeout=5,
            )
            results["openai"] = "online" if r.status_code == 200 else f"error_{r.status_code}"
        except Exception:
            results["openai"] = "unreachable"
    else:
        results["openai"] = "no_key"

    # --- Gemini ---
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            r = req_lib.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={gemini_key}",
                timeout=5,
            )
            results["gemini"] = "online" if r.status_code == 200 else f"error_{r.status_code}"
        except Exception:
            results["gemini"] = "unreachable"
    else:
        results["gemini"] = "no_key"

    # --- Groq ---
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            r = req_lib.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {groq_key}"},
                timeout=5,
            )
            results["groq"] = "online" if r.status_code == 200 else f"error_{r.status_code}"
        except Exception:
            results["groq"] = "unreachable"
    else:
        results["groq"] = "no_key"

    # Ustal aktywny provider i ogólny sukces
    active = [p for p, s in results.items() if s == "online"]
    heuristic_fallback = len(active) == 0
    overall_ok = True  # heurystyka zawsze działa

    if heuristic_fallback:
        msg = "Brak działających providerów AI — aktywna heurystyka ATR/Bollinger."
        active_provider = "heuristic"
    else:
        active_provider = active[0]
        msg = f"AI działa. Aktywny provider: {', '.join(active)} (konfiguracja: {provider_cfg})"

    _log_action(actor, "check-ai", f"active={active_provider}", db)
    return ActionResult(
        success=overall_ok,
        action="check-ai",
        message=msg,
        data={
            "provider": active_provider,
            "provider_config": provider_cfg,
            "providers": results,
            "active": active,
            "status": "online" if active else "heuristic",
        },
    )


@router.post("/force-sync")
def force_sync(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Wymusza synchronizację pozycji z Binance (tylko tryb LIVE)."""
    actor = _actor(request)
    mode = os.getenv("TRADING_MODE", "demo").lower()
    if mode != "live":
        return ActionResult(
            success=False,
            action="force-sync",
            message=f"Synchronizacja dostępna tylko w trybie LIVE. Aktualny tryb: {mode}.",
        )
    try:
        from backend.routers.positions import _sync_live_positions_from_binance

        synced = _sync_live_positions_from_binance(db)
        _log_action(actor, "force-sync", f"synced={synced}", db)
        return ActionResult(
            success=True,
            action="force-sync",
            message=f"Synchronizacja zakończona. Zsynchronizowano {synced} pozycji.",
            data={"synced_count": synced},
        )
    except Exception as exc:
        _log_action(actor, "force-sync", f"error: {str(exc)[:80]}", db)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/check-positions")
def check_positions(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Sprawdza aktywne pozycje: PnL, SL, TP, odległości procentowe."""
    actor = _actor(request)
    mode = os.getenv("TRADING_MODE", "demo").lower()
    positions = (
        db.query(Position)
        .filter(Position.mode == mode, Position.quantity > 0)
        .order_by(Position.opened_at.desc())  # type: ignore[arg-type]
        .all()
    )
    summary = []
    for p in positions:
        price = float(p.current_price or p.entry_price or 0)
        entry = float(p.entry_price or 0)
        sl = float(p.planned_sl) if p.planned_sl else None
        tp = float(p.planned_tp) if p.planned_tp else None
        pnl = float(p.unrealized_pnl or 0)
        pnl_pct = round((price - entry) / entry * 100, 2) if entry > 0 and price > 0 else 0.0
        sl_dist = round((price - sl) / price * 100, 2) if sl and price > 0 else None
        tp_dist = round((tp - price) / price * 100, 2) if tp and price > 0 else None
        summary.append({
            "symbol": p.symbol,
            "quantity": round(float(p.quantity), 8),
            "entry_price": round(entry, 6),
            "current_price": round(price, 6),
            "unrealized_pnl": round(pnl, 4),
            "pnl_pct": pnl_pct,
            "take_profit": round(tp, 6) if tp else None,
            "stop_loss": round(sl, 6) if sl else None,
            "tp_distance_pct": tp_dist,
            "sl_distance_pct": sl_dist,
            "sl_alert": sl_dist is not None and sl_dist < 2.0,
        })
    total_pnl = round(sum(s["unrealized_pnl"] for s in summary), 4)
    _log_action(actor, "check-positions", f"count={len(summary)} pnl={total_pnl:+.4f}", db)
    return ActionResult(
        success=True,
        action="check-positions",
        message=f"Aktywne pozycje ({mode.upper()}): {len(summary)} | Unrealized PnL: {total_pnl:+.4f} EUR",
        data={"positions": summary, "total_unrealized_pnl": total_pnl, "count": len(summary), "mode": mode},
    )


@router.post("/check-sl-tp")
def check_sl_tp(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Sprawdza odległości SL/TP — alarmuje gdy pozycja jest < 2% od SL."""
    actor = _actor(request)
    mode = os.getenv("TRADING_MODE", "demo").lower()
    positions = (
        db.query(Position)
        .filter(Position.mode == mode, Position.quantity > 0)
        .all()
    )
    report = []
    alerts = []
    for p in positions:
        price = float(p.current_price or p.entry_price or 0)
        if price <= 0:
            continue
        sl = float(p.planned_sl) if p.planned_sl else None
        tp = float(p.planned_tp) if p.planned_tp else None
        sl_dist = round((price - sl) / price * 100, 2) if sl else None
        tp_dist = round((tp - price) / price * 100, 2) if tp else None
        is_alert = sl_dist is not None and sl_dist < 2.0
        entry = {
            "symbol": p.symbol,
            "price": round(price, 6),
            "stop_loss": round(sl, 6) if sl else None,
            "take_profit": round(tp, 6) if tp else None,
            "sl_distance_pct": sl_dist,
            "tp_distance_pct": tp_dist,
            "alert": is_alert,
        }
        report.append(entry)
        if is_alert:
            alerts.append(f"{p.symbol}: SL za {sl_dist}% (SL={sl:.4f}, cena={price:.4f})")
    if not report:
        msg = f"Brak otwartych pozycji w trybie {mode.upper()}."
    elif alerts:
        msg = f"⚠ {len(alerts)} pozycji blisko SL: {' | '.join(alerts)}"
    else:
        msg = f"Sprawdzono {len(report)} pozycji — wszystkie SL/TP w bezpiecznej odległości."
    _log_action(actor, "check-sl-tp", f"positions={len(report)} alerts={len(alerts)}", db)
    return ActionResult(
        success=True,
        action="check-sl-tp",
        message=msg,
        data={"positions": report, "alerts": alerts, "alert_count": len(alerts)},
    )


@router.post("/save-snapshot")
def save_snapshot(
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """Zapisuje snapshot equity i stanu portfela."""
    actor = _actor(request)
    try:
        from backend.accounting import compute_demo_account_state, compute_risk_snapshot
        mode = os.getenv("TRADING_MODE", "demo").lower()
        state = compute_demo_account_state(db)
        equity = float(state.get("equity", 0)) if state else 0.0
        positions_count = db.query(Position).filter(
            Position.mode == mode, Position.quantity > 0
        ).count()
        snap_ts = datetime.now(timezone.utc).isoformat()
        log_to_db(
            level="INFO",
            module="operator_action:save-snapshot",
            message=f"[{actor}] Snapshot zapisany: equity={equity:.2f} EUR, pozycje={positions_count}, tryb={mode}",
            db=db,
        )
        return ActionResult(
            success=True,
            action="save-snapshot",
            message=f"Snapshot zapisany — equity: {equity:.2f} EUR | pozycje: {positions_count} ({mode.upper()})",
            data={"equity": equity, "positions_count": positions_count, "mode": mode, "timestamp": snap_ts},
        )
    except Exception as exc:
        _log_action(actor, "save-snapshot", f"error: {str(exc)[:80]}", db)
        return ActionResult(
            success=False,
            action="save-snapshot",
            message=f"Błąd snapshota: {str(exc)[:200]}",
        )


# ─────────────────────────────────────────────
# AI Chat operatorski
# ─────────────────────────────────────────────

def _build_system_context(db: Session, request: Request) -> str:
    """Buduje kontekst systemowy dla AI — pozycje, sygnały, błędy, blokady wejścia."""
    lines = ["=== KONTEKST SYSTEMU RLdC Trading Bot ==="]

    # Status
    mode = os.getenv("TRADING_MODE", "demo")
    lines.append(f"Tryb handlu: {mode.upper()}")

    # Otwarte pozycje
    positions = db.query(Position).filter(Position.mode == mode, Position.quantity > 0).all()
    lines.append(f"Otwarte pozycje ({mode}): {len(positions)}")
    for p in positions[:5]:
        pnl = float(p.unrealized_pnl or 0)
        sl = float(p.trailing_stop_price or p.planned_sl or 0) or None
        price = float(p.current_price or p.entry_price or 0)
        sl_dist = round((price - sl) / price * 100, 2) if sl and price > 0 else None
        alert = f" ⚠SL za {sl_dist}%" if sl_dist is not None and sl_dist < 2.0 else ""
        lines.append(f"  - {p.symbol}: qty={round(float(p.quantity),6)}, entry={p.entry_price}, pnl={pnl:+.4f}{alert}")

    # Ostatnie sygnały
    signals = (
        db.query(Signal)
        .filter(Signal.signal_type.in_(["BUY", "SELL"]))
        .order_by(Signal.id.desc())
        .limit(8)
        .all()
    )
    lines.append(f"Ostatnie sygnały: {len(signals)}")
    for s in signals:
        lines.append(f"  - {s.symbol} {s.signal_type} conf={s.confidence:.2f}")

    # Decision trace — dlaczego bot nie wchodzi
    try:
        from backend.routers.signals import get_execution_trace  # type: ignore[import]
        # Pobierz bezpośrednio z DB zamiast przez HTTP
        from backend.database import DecisionTrace
        traces = (
            db.query(DecisionTrace)  # type: ignore[attr-defined]
            .filter(DecisionTrace.mode == mode)  # type: ignore[attr-defined]
            .order_by(DecisionTrace.id.desc())  # type: ignore[attr-defined]
            .limit(10)
            .all()
        )
        if traces:
            lines.append(f"Ostatnie blokady wejścia (decision trace, {len(traces)}):")
            for t in traces[:8]:
                rc = getattr(t, "reason_code", "?")
                sym = getattr(t, "symbol", "?")
                rpl = getattr(t, "reason_pl", "")
                lines.append(f"  - {sym}: {rc} | {str(rpl)[:80]}")
    except Exception:
        pass

    # Ostatnie błędy
    errors = (
        db.query(SystemLog)
        .filter(SystemLog.level == "ERROR")
        .order_by(SystemLog.id.desc())
        .limit(5)
        .all()
    )
    if errors:
        lines.append(f"Ostatnie błędy ({len(errors)}):")
        for e in errors:
            lines.append(f"  - [{e.module}] {str(e.message or '')[:100]}")

    # Ostrzeżenia z ostatnich 30 min
    warnings = (
        db.query(SystemLog)
        .filter(SystemLog.level == "WARNING")
        .order_by(SystemLog.id.desc())
        .limit(5)
        .all()
    )
    if warnings:
        lines.append(f"Ostatnie ostrzeżenia ({len(warnings)}):")
        for w in warnings:
            lines.append(f"  - [{w.module}] {str(w.message or '')[:80]}")

    # Collector
    collector = getattr(request.app.state, "collector", None)
    if collector:
        running = getattr(collector, "_running", False)
        watchlist = getattr(collector, "watchlist", []) or []
        lines.append(f"Kolektor: {'aktywny' if running else 'zatrzymany'}, watchlist={len(watchlist)} symboli")

    # Ostatnie akcje operatora
    op_logs = (
        db.query(SystemLog)
        .filter(SystemLog.module.like("operator_action:%"))
        .order_by(SystemLog.id.desc())
        .limit(5)
        .all()
    )
    if op_logs:
        lines.append(f"Ostatnie akcje operatora ({len(op_logs)}):")
        for ol in op_logs:
            lines.append(f"  - {str(ol.message or '')[:80]}")

    return "\n".join(lines)


def _heuristic_chat_response(message: str, context: str) -> str:
    """Heurystyczna odpowiedź czatu gdy brak OpenAI."""
    m = message.lower()
    lines = []

    if any(w in m for w in ["błąd", "error", "problem", "nie działa", "sprawdź błędy"]):
        lines = [
            "🔍 Diagnoza błędów:",
            "Sprawdź zakładkę Logi → filtruj ERROR/WARNING.",
            "Użyj akcji 'Sprawdź błędy' → ostatnie 30 błędów systemu.",
            "Jeśli collector nie działa: użyj 'Restart collectora'.",
            "",
        ]
    elif any(w in m for w in ["nie kupił", "nie wszedł", "blokad", "dlaczego nie"]):
        lines = [
            "🚧 Analiza blokad wejścia:",
            "Sprawdź zakładkę 'Decyzje' → decision trace dla każdego symbolu.",
            "Najczęstsze przyczyny blokad:",
            "  • market_regime_buy_blocked — CRASH/BEAR, za niska confidence",
            "  • cost_gate_failed — edge < 4× koszty transakcji",
            "  • cooldown_active — za krótki czas od ostatniej transakcji",
            "  • max_positions_reached — osiągnięto limit otwartych pozycji",
            "  • confidence_below_threshold — za słaby sygnał",
            "Użyj akcji 'Szukaj okazji' → aktywne sygnały BUY z konfidencją.",
            "",
        ]
    elif any(w in m for w in ["sprzedał", "zamknął", "dlaczego sprzedał", "exit"]):
        lines = [
            "📤 Analiza zamknięcia pozycji:",
            "Sprawdź zakładkę 'Decyzje' → reason_code dla symbolu z pozycją.",
            "Powody wyjścia bota:",
            "  • stop_loss_hit — cena uderzyła Stop Loss",
            "  • tp_partial_keep_trend — częściowy TP, bot trzyma resztę",
            "  • trailing_lock_profit — trailing stop aktywowany",
            "  • trend_reversal — odwrócenie trendu",
            "  • tp_full_reversal — pełny TP + odwrócenie",
            "Użyj akcji 'Sprawdź SL/TP' → odległości do SL dla pozycji.",
            "",
        ]
    elif any(w in m for w in ["kupi", "sygnał", "okazj", "wejś", "skanuj"]):
        lines = [
            "📊 Analiza sygnałów:",
            "Użyj akcji 'Skanuj okazje' → top 20 aktywnych sygnałów BUY/SELL.",
            "Sprawdź widok 'AI Sygnały' w menu bocznym.",
            "Zakładka 'Decyzje' pokaże execution-trace dla każdego symbolu.",
            "Status rynku (CRASH/BEAR/BULL) blokuje BUY gdy confidence < min_threshold.",
            "",
        ]
    elif any(w in m for w in ["portfel", "pozycj", "balans", "equity", "sl", "tp", "stop"]):
        lines = [
            "💼 Portfel i pozycje:",
            "Użyj akcji 'Sprawdź pozycje' → wszystkie pozycje z PnL i SL/TP.",
            "Użyj akcji 'Sprawdź SL/TP' → alerty gdy pozycja < 2% od SL.",
            "Sprawdź widok 'Portfel' w menu bocznym.",
        ]
    elif any(w in m for w in ["restart", "zatrzym", "uruchom", "reset", "kolektor"]):
        lines = [
            "🔄 Restart / kontrola:",
            "Użyj akcji 'Restart collectora' w panelu Akcje.",
            "Użyj akcji 'Wymuś synchronizację' w trybie LIVE.",
            "Status systemu → Kolektor pokaże czy jest aktywny.",
        ]
    elif any(w in m for w in ["config", "ustaw", "parametr", "próg", "risk", "ryzyko"]):
        lines = [
            "⚙️ Konfiguracja i ryzyko:",
            "Runtime settings w widoku 'Ustawienia' (menu boczne).",
            "Kluczowe parametry: min_edge_multiplier, max_open_positions, bear_regime_min_conf.",
            "Zmiany działają bez restartu aplikacji.",
        ]
    elif any(w in m for w in ["ai", "gemini", "groq", "openai", "heurystyk"]):
        lines = [
            "🤖 Status AI:",
            "Użyj akcji 'Test AI' → sprawdź wszystkich providerów (OpenAI/Gemini/Groq/heurystyka).",
            "Kolejność fallback: Gemini → Groq → OpenAI → Ollama → heurystyka ATR.",
            "Bez klucza API → heurystyczne zakresy ATR/Bollinger.",
        ]
    elif any(w in m for w in ["snapshot", "zapis", "raport", "eksport"]):
        lines = [
            "📸 Snapshot i raporty:",
            "Użyj akcji 'Zapisz snapshot' → equity + pozycje → log systemowy.",
            "Użyj akcji 'Generuj raport' → pełny raport systemowy.",
        ]
    else:
        lines = [
            f"Odpowiadam na: '{message[:80]}'",
            "",
            "Dostępne komendy (kliknij akcję lub wpisz):",
            "• dlaczego nie kupił → analiza blokad wejścia",
            "• dlaczego sprzedał → analiza powodu exit",
            "• sprawdź błędy → błędy systemu",
            "• skanuj okazje → sygnały BUY/SELL teraz",
            "• sprawdź pozycje → aktywne pozycje z PnL",
            "• sprawdź SL/TP → odległości do stop loss",
            "• status systemu → pełny przegląd modułów",
            "• test AI → sprawdź providery AI",
            "",
            "Dla pełnej analizy AI: ustaw OPENAI_API_KEY lub GEMINI_API_KEY w .env",
        ]

    lines.append("─────────────────────")
    ctx_lines = context.split("\n")[:8]
    lines.extend(ctx_lines)
    return "\n".join(lines)


@router.post("/ai/chat")
def operator_chat(
    chat: ChatMessage,
    request: Request,
    db: Session = Depends(get_db),
    _admin: None = Depends(require_admin),
):
    """
    Czat AI dla operatora — próbuje kolejno: OpenAI → Gemini → Groq → heurystyka.
    """
    import requests as req_lib

    actor = _actor(request)
    context = _build_system_context(db, request)

    system_prompt = (
        "Jesteś asystentem AI dla systemu tradingowego RLdC AiNalyzator (Binance spot). "
        "Rozmawiasz z operatorem/traderem po polsku. "
        "Odpowiadaj zwięźle, technicznie i praktycznie. "
        "Wskazuj konkretne działania naprawcze. "
        "Nie podawaj nierealistycznych obietnic zysku.\n\n"
        f"{context}"
    )

    # --- OpenAI ---
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            resp = req_lib.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": chat.message},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.3,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                answer = resp.json()["choices"][0]["message"]["content"].strip()
                _log_action(actor, "ai-chat", f"openai_ok msg_len={len(chat.message)}", db)
                return {"success": True, "response": answer, "provider": "openai",
                        "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception:
            pass

    # --- Gemini ---
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    if gemini_key:
        try:
            resp = req_lib.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={gemini_key}",
                json={
                    "contents": [{"parts": [{"text": system_prompt + "\n\nOperator pyta: " + chat.message}]}],
                    "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
                },
                timeout=20,
            )
            if resp.status_code == 200:
                candidates = resp.json().get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    answer = "".join(p.get("text", "") for p in parts).strip()
                    if answer:
                        _log_action(actor, "ai-chat", f"gemini_ok msg_len={len(chat.message)}", db)
                        return {"success": True, "response": answer, "provider": "gemini",
                                "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception:
            pass

    # --- Groq ---
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    if groq_key:
        try:
            resp = req_lib.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": groq_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": chat.message},
                    ],
                    "max_tokens": 600,
                    "temperature": 0.3,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                answer = resp.json()["choices"][0]["message"]["content"].strip()
                _log_action(actor, "ai-chat", f"groq_ok msg_len={len(chat.message)}", db)
                return {"success": True, "response": answer, "provider": "groq",
                        "timestamp": datetime.now(timezone.utc).isoformat()}
        except Exception:
            pass

    # --- Heurystyka ---
    answer = _heuristic_chat_response(chat.message, context)
    _log_action(actor, "ai-chat", "heuristic", db)
    return {"success": True, "response": answer, "provider": "heuristic",
            "timestamp": datetime.now(timezone.utc).isoformat()}
