"""
Telegram Bot for RLdC Trading Bot
"""
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from backend.database import SessionLocal, Signal, Order, Position, BlogPost, SystemLog, AccountSnapshot, PendingOrder, Alert, utc_now_naive
from backend.system_logger import log_exception
from backend.telegram_intelligence import log_telegram_event

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TRADING_MODE = os.getenv("TRADING_MODE", "demo")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def _api(method: str, path: str, data: dict = None, params: dict = None, timeout: int = 12) -> dict:
    """Wywołuje backend API. Zwraca słownik lub {'error': ...} przy problemie."""
    url = f"{API_BASE_URL}{path}"
    hdrs = {"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"}
    try:
        if method == "GET":
            r = requests.get(url, headers=hdrs, params=params, timeout=timeout)
        else:
            r = requests.post(url, headers=hdrs, json=data or {}, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
    except requests.exceptions.Timeout:
        return {"error": "timeout"}
    except Exception as exc:
        return {"error": str(exc)}


def _fval(val, decimals: int = 2) -> str:
    """Formatuje wartość liczbową z myślnikiem gdy brak."""
    if val is None:
        return "—"
    return f"{float(val):.{decimals}f}"


def _fpnl(val, suffix: str = " EUR") -> str:
    """Formatuje PnL ze znakiem +/-."""
    if val is None:
        return "—"
    v = float(val)
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}{suffix}"


def _pnl_icon(val) -> str:
    if val is None:
        return "➖"
    return "📈" if float(val) >= 0 else "📉"


def _fmt_price(val) -> str:
    if val is None:
        return "—"
    num = float(val)
    return f"{num:.6f}".rstrip("0").rstrip(".")


def _plan_lines(item: dict) -> list[str]:
    lines: list[str] = []
    action = item.get("action")
    status = item.get("plan_status")
    confidence = item.get("confidence_score")
    risk = item.get("risk_score")
    entry = item.get("entry_price")
    tp = item.get("take_profit_price") or item.get("planned_tp")
    sl = item.get("stop_loss_price") or item.get("planned_sl")
    be = item.get("break_even_price")
    exp_net = item.get("expected_net_profit")
    needs_revision = item.get("requires_revision")
    invalidation = item.get("invalidation_reason")
    last_consulted = item.get("last_consulted_at")

    if action or status:
        lines.append(f"   Plan: {action or '—'} [{status or 'brak'}]")
    if entry is not None or tp is not None or sl is not None:
        lines.append(f"   Entry: {_fmt_price(entry)}  |  TP: {_fmt_price(tp)}  |  SL: {_fmt_price(sl)}")
    if be is not None or exp_net is not None:
        lines.append(f"   Break-even: {_fmt_price(be)}  |  Net: {_fpnl(exp_net)}")
    if confidence is not None or risk is not None:
        conf_txt = f"{round(float(confidence) * 100)}%" if confidence is not None else "—"
        risk_txt = f"{round(float(risk) * 100)}%" if risk is not None else "—"
        lines.append(f"   Pewność: {conf_txt}  |  Ryzyko: {risk_txt}")
    if needs_revision:
        lines.append(f"   Rewizja: wymagana ({invalidation or 'brak powodu'})")
    if last_consulted:
        lines.append(f"   Ostatnia konsultacja: {str(last_consulted)[:16].replace('T', ' ')}")
    return lines


def _mode() -> str:
    """Aktualny tryb z .env (może zmienić się runtime)."""
    return os.getenv("TRADING_MODE", TRADING_MODE)


def _is_authorized(update: Update) -> bool:
    """Sprawdza czy wiadomość pochodzi z dozwolonego chatu."""
    if not TELEGRAM_CHAT_ID:
        return False  # brak konfiguracji = blokuj wszystkich
    return str(update.effective_chat.id) == str(TELEGRAM_CHAT_ID)


async def _send_reply(update: Update, text: str, command: Optional[str] = None):
    chat_id = str(update.effective_chat.id)
    try:
        await update.message.reply_text(text)
        log_telegram_event(
            chat_id=chat_id,
            direction="outgoing",
            raw_text=text,
            source_module="telegram_bot",
            message_type="command" if command else "alert",
        )
    except Exception as exc:
        log_telegram_event(
            chat_id=chat_id,
            direction="outgoing",
            raw_text=f"{text} [BŁĄD: {exc}]",
            source_module="telegram_bot",
            message_type="error",
        )


async def _check_auth(update: Update) -> bool:
    """Zwraca True jeśli autoryzowany, False + odpowiedź jeśli nie."""
    if not _is_authorized(update):
        await update.message.reply_text("⛔ Brak dostępu.")
        return False
    return True


async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zwraca aktualny publiczny adres panelu."""
    if not await _check_auth(update):
        return
    try:
        from backend.public_url import get_public_url_info

        info = get_public_url_info()
        public_url = info.get("public_url")
        lan_url = info.get("lan_url", "brak")
        source = info.get("source", "?")
        mode = info.get("mode", "?")
        status = info.get("status", "?")
        warning = info.get("warning", "")
        updated_at = info.get("updated_at", "?")

        mode_icons = {
            "configured": "🌐",
            "tunnel": "🔗",
            "direct_ip": "📡",
            "local": "🏠",
        }
        icon = mode_icons.get(mode, "🌐")

        if public_url:
            lines = [
                f"🖥️ RLdC AiNalyzer — adres panelu",
                f"",
                f"{icon} Publiczny URL: {public_url}",
                f"🏠 LAN: {lan_url}",
                f"📋 Źródło: {source}",
                f"🔧 Tryb: {mode}",
                f"✅ Status: {status}",
            ]
        else:
            lines = [
                f"🖥️ RLdC AiNalyzer — adres panelu",
                f"",
                f"⚠️ Brak publicznego adresu",
                f"🏠 LAN: {lan_url}",
                f"📋 Źródło: {source}",
            ]

        if warning:
            lines.append(f"")
            lines.append(f"⚠️ {warning}")

        lines.append(f"")
        lines.append(f"🕐 {updated_at[:19].replace('T', ' ')}")
        text = "\n".join(lines)
    except Exception as exc:
        text = f"❌ Błąd pobierania adresu: {exc}"
    await _send_reply(update, text, "/ip")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode().upper()
    text = (
        f"🤖 RLdC Trading Bot — gotowy! [{mode}]\n\n"
        "Możesz pisać do mnie jak na czacie — odpowiem po polsku używając AI (Gemini/Groq).\n\n"
        "Najważniejsze komendy:\n"
        "/status — pełny status systemu\n"
        "/portfolio — otwarte pozycje z PnL\n"
        "/top5 — top 5 sygnałów z powodami blokad\n"
        "/analyze — uruchom analizę teraz\n"
        "/help — pełna lista komend"
    )
    await _send_reply(update, text, "/start")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 Dostępne komendy:\n\n"
        "📊 Dane rynkowe:\n"
        "/status — pełny status: portfel, PnL, kolektor, blokady\n"
        "/portfolio — otwarte pozycje z PnL%, SL, TP\n"
        "/positions — to samo co /portfolio\n"
        "/top5 — top 5 sygnałów z powodami blokad\n"
        "/top10 — top 10 sygnałów\n"
        "/orders — ostatnie zlecenia\n"
        "/lastsignal — ostatni sygnał AI\n"
        "/risk — ryzyko: cash, ekspozycja, blokady\n"
        "/blog — ostatni raport AI\n"
        "/logs — ostatnie błędy systemu\n\n"
        "⚙️ Akcje:\n"
        "/analyze — uruchom analizę teraz\n"
        "/scan — skanuj okazje\n"
        "/mode — aktualny tryb trading\n"
        "/stop — zatrzymaj trading demo\n"
        "/confirm <ID> — potwierdź transakcję\n"
        "/reject <ID> — odrzuć transakcję\n\n"
        "🌐 Sieć:\n"
        "/ip — adres panelu WWW\n\n"
        "🔒 Governance:\n"
        "/governance — status pipeline\n"
        "/freeze — aktywne blokady\n"
        "/incidents — aktywne incydenty\n\n"
        "💬 Chat AI:\n"
        "Napisz dowolne pytanie — odpowiem przez Gemini/Groq AI."
    )
    await _send_reply(update, text, "/help")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    mode_upper = mode.upper()
    mode_icon = "🔴" if mode == "live" else "🟡"

    summary = _api("GET", "/api/portfolio/summary", params={"mode": mode})
    readiness = _api("GET", "/api/signals/entry-readiness", params={"mode": mode})

    lines = [f"{mode_icon} Status RLdC Bot — {mode_upper}", "─" * 22]

    # Portfel
    sdata = summary.get("data", {})
    n_pos = sdata.get("total_positions", "?")
    total_val = sdata.get("total_value")
    pnl = sdata.get("total_unrealized_pnl")
    win = sdata.get("winning_positions", 0)
    lose = sdata.get("losing_positions", 0)
    net_pnl = sdata.get("net_pnl")
    lines.append(f"{_pnl_icon(pnl)} Pozycje: {n_pos}  ({win}↑ / {lose}↓)")
    if total_val is not None:
        lines.append(f"💰 Wartość: {_fval(total_val)} EUR")
    if pnl is not None:
        lines.append(f"📊 PnL niezrealizowany: {_fpnl(pnl)}")
    if net_pnl is not None:
        lines.append(f"💵 PnL netto (closed): {_fpnl(net_pnl)}")

    # Cash i gotowość
    cash = readiness.get("cash_available")
    if cash is not None:
        lines.append(f"💵 Wolna gotówka: {_fval(cash)} EUR")

    lines.append("")
    # Wejście
    can_enter = readiness.get("can_enter_now")
    if can_enter is True:
        best = readiness.get("best_ready_symbol", "?")
        lines.append(f"✅ WEJŚCIE: MOŻLIWE → {best}")
    elif can_enter is False:
        status_pl = readiness.get("status_pl", "")
        best_blocked = readiness.get("best_blocked_symbol", "")
        best_reason = readiness.get("best_blocked_reason_pl", "")
        ready = readiness.get("ready_count", 0)
        blocked = readiness.get("blocked_count", 0)
        kill = readiness.get("kill_switch_active", False)
        if kill:
            lines.append("🚨 KILL SWITCH AKTYWNY — trading zatrzymany!")
        else:
            lines.append(f"🔒 WEJŚCIE: ZABLOKOWANE ({ready} gotowych / {blocked} zablokowanych)")
        if best_blocked and best_reason:
            lines.append(f"   ↳ {best_blocked}: {best_reason[:60]}")
    elif "error" in readiness:
        lines.append(f"⚠️ Błąd odczytu gotowości: {readiness['error']}")

    # Collector state z DB
    lines.append("")
    db = SessionLocal()
    try:
        last_log = db.query(SystemLog).filter(SystemLog.module == "collector").order_by(SystemLog.id.desc()).first()
        if last_log:
            age_s = max(0, int((utc_now_naive() - last_log.timestamp).total_seconds()))
            age_str = f"{age_s}s temu" if age_s < 120 else f"{age_s//60} min temu"
            icon = "✅" if age_s < 120 else "⚠️"
            lines.append(f"{icon} Kolektor: aktywny ({age_str})")
        else:
            lines.append("❓ Kolektor: brak danych")
        # Ostatni błąd
        last_err = db.query(SystemLog).filter(SystemLog.level == "ERROR").order_by(SystemLog.id.desc()).first()
        if last_err:
            err_age = int((utc_now_naive() - last_err.timestamp).total_seconds())
            if err_age < 3600:
                lines.append(f"⚠️ Ostatni błąd ({err_age//60}min): {str(last_err.message or '')[:60]}")
    finally:
        db.close()

    lines.append("")
    lines.append(f"🕐 {utc_now_naive().strftime('%Y-%m-%d %H:%M UTC')}")
    await _send_reply(update, "\n".join(lines), "/status")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/control/state",
            json={"demo_trading_enabled": False},
            headers={"X-Admin-Token": ADMIN_TOKEN},
            timeout=5,
        )
        if resp.status_code == 200:
            text = "🛑 Demo trading zatrzymany. Kolektor nadal śledzi dane."
        elif resp.status_code == 401:
            text = "⛔ Brak autoryzacji API — sprawdź ADMIN_TOKEN w .env."
        else:
            text = f"⚠️ Nie udało się zatrzymać (status {resp.status_code}). Sprawdź API."
    except Exception as exc:
        text = f"❌ Błąd wywołania API: {exc}"
    await _send_reply(update, text, "/stop")


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    readiness = _api("GET", "/api/signals/entry-readiness", params={"mode": mode})
    summary = _api("GET", "/api/portfolio/summary", params={"mode": mode})
    sdata = summary.get("data", {})

    lines = ["⚠️ Ryzyko i gotowość", "─" * 22]

    # Gotówka i limity
    cash = readiness.get("cash_available")
    min_notional = readiness.get("min_notional")
    max_pos = readiness.get("max_open_positions")
    open_pos = readiness.get("open_positions")
    kill = readiness.get("kill_switch_active", False)

    if kill:
        lines.append("🚨 KILL SWITCH AKTYWNY")
    else:
        lines.append("✅ Kill switch: wyłączony")

    if cash is not None:
        lines.append(f"💵 Wolna gotówka: {_fval(cash)} EUR")
    if min_notional is not None:
        lines.append(f"📐 Min. notional: {_fval(min_notional)} EUR")
    if max_pos is not None and open_pos is not None:
        pct = int(open_pos / max_pos * 100) if max_pos > 0 else 0
        lines.append(f"📊 Pozycje: {open_pos}/{max_pos} ({pct}% limitu)")

    # PnL
    pnl = sdata.get("total_unrealized_pnl")
    total_val = sdata.get("total_value")
    total_cost = sdata.get("total_cost")
    lines.append("")
    if pnl is not None:
        lines.append(f"📉 Niezrealizowany PnL: {_fpnl(pnl)}")
    if total_val is not None:
        lines.append(f"💰 Wartość portfela: {_fval(total_val)} EUR")
    if total_cost is not None and total_cost > 0:
        lines.append(f"💸 Koszty (fee+poślizg): {_fval(total_cost)} EUR")

    # Env limity
    max_daily_loss = os.getenv("MAX_DAILY_LOSS_PERCENT", "5.0")
    max_drawdown = os.getenv("MAX_DRAWDOWN_PERCENT", "10.0")
    lines.append("")
    lines.append(f"⚙️ Limit dzienny: {max_daily_loss}%")
    lines.append(f"⚙️ Max drawdown: {max_drawdown}%")

    # Blokady wejścia
    blocked = readiness.get("blocked_count", 0)
    ready = readiness.get("ready_count", 0)
    if blocked > 0 or ready > 0:
        lines.append("")
        lines.append(f"🔒 Sygnały: {ready} gotowych, {blocked} zablokowanych")
        best_blocked = readiness.get("best_blocked_symbol", "")
        best_reason = readiness.get("best_blocked_reason_pl", "")
        if best_blocked:
            lines.append(f"   ↳ Główna blokada: {best_blocked} — {best_reason[:50]}")

    await _send_reply(update, "\n".join(lines), "/risk")


def _format_signals_list(signals_data: list, title: str) -> str:
    """Formatuje listę sygnałów z powodami blokad."""
    if not signals_data:
        return "Brak sygnałów."
    lines = [title, "─" * 22]
    for i, s in enumerate(signals_data, 1):
        sym = s.get("symbol", "?")
        stype = s.get("signal_type", "?")
        conf = s.get("confidence", 0)
        allowed = s.get("allowed", s.get("can_enter"))
        reason_pl = s.get("entry_reason_pl", s.get("reason_pl", ""))
        blocking = s.get("entry_reason", s.get("blocking_reason", ""))
        score = s.get("score")

        stype_icon = "🟢" if stype == "BUY" else "🔴" if stype == "SELL" else "⚪"
        if allowed is True:
            status_icon = "✅"
        elif allowed is False:
            status_icon = "🔒"
        else:
            status_icon = "➖"

        score_str = f" score={score:.1f}" if score is not None else ""
        line = f"{i}. {stype_icon} {sym} {stype} {int(conf*100)}%{score_str} {status_icon}"
        lines.append(line)
        if reason_pl:
            lines.append(f"   ↳ {reason_pl[:65]}")
        elif blocking and allowed is False:
            lines.append(f"   ↳ {blocking[:65]}")
        lines.extend(_plan_lines(s))
    return "\n".join(lines)


async def top10_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    readiness = _api("GET", "/api/signals/entry-readiness", params={"mode": mode})
    candidates = readiness.get("candidates", [])
    blocked = readiness.get("blocked", [])
    # Łącz: najpierw gotowe (candidates), potem zablokowane
    combined = candidates + blocked
    combined = combined[:10]
    if not combined:
        # fallback: surowe sygnały z DB
        db = SessionLocal()
        try:
            rows = db.query(Signal).filter(Signal.signal_type.in_(["BUY", "SELL"])).order_by(Signal.confidence.desc()).limit(10).all()
            combined = [{"symbol": s.symbol, "signal_type": s.signal_type, "confidence": s.confidence} for s in rows]
        finally:
            db.close()
    text = _format_signals_list(combined, f"📊 Top 10 sygnałów [{mode.upper()}]")
    await _send_reply(update, text, "/top10")


async def top5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    readiness = _api("GET", "/api/signals/entry-readiness", params={"mode": mode})
    candidates = readiness.get("candidates", [])
    blocked = readiness.get("blocked", [])
    combined = candidates + blocked
    combined = combined[:5]
    if not combined:
        db = SessionLocal()
        try:
            rows = db.query(Signal).filter(Signal.signal_type.in_(["BUY", "SELL"])).order_by(Signal.confidence.desc()).limit(5).all()
            combined = [{"symbol": s.symbol, "signal_type": s.signal_type, "confidence": s.confidence} for s in rows]
        finally:
            db.close()
    text = _format_signals_list(combined, f"📈 Top 5 sygnałów [{mode.upper()}]")
    await _send_reply(update, text, "/top5")


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    data = _api("GET", "/api/positions", params={"mode": mode})
    positions = data if isinstance(data, list) else data.get("positions", data.get("data", []))

    if "error" in data and not positions:
        await _send_reply(update, f"❌ Błąd pobierania pozycji: {data.get('error')}", "/portfolio")
        return

    if not positions:
        await _send_reply(update, f"📭 Brak otwartych pozycji [{mode.upper()}].", "/portfolio")
        return

    lines = [f"💼 Otwarte pozycje — {mode.upper()} ({len(positions)})", "─" * 22]
    total_pnl = 0.0
    total_val = 0.0

    for p in positions:
        sym = p.get("symbol", "?")
        side = p.get("side", "?")
        qty = p.get("quantity", 0)
        entry = p.get("entry_price")
        cur = p.get("current_price")
        pnl = p.get("unrealized_pnl")
        pnl_pct = p.get("pnl_percent")
        val = p.get("value_eur")
        sl = p.get("planned_sl")
        tp = p.get("planned_tp")
        trailing_sl = p.get("trailing_stop_price")

        if pnl is not None:
            total_pnl += float(pnl)
        if val is not None:
            total_val += float(val)

        icon = _pnl_icon(pnl)
        side_icon = "📗" if side == "LONG" else "📕"
        pnl_str = _fpnl(pnl)
        pnl_pct_str = f" ({_fpnl(pnl_pct, suffix='%')})" if pnl_pct is not None else ""

        lines.append(f"")
        lines.append(f"{icon} {side_icon} {sym} {side}")
        lines.append(f"   Qty: {_fval(qty, 4)}")
        if entry and cur:
            entry_f = f"{float(entry):.6f}".rstrip("0").rstrip(".")
            cur_f = f"{float(cur):.6f}".rstrip("0").rstrip(".")
            lines.append(f"   Wejście: {entry_f} → Cena: {cur_f}")
        lines.append(f"   PnL: {pnl_str}{pnl_pct_str}")
        if val is not None:
            lines.append(f"   Wartość: {_fval(val)} EUR")
        # SL/TP
        active_sl = trailing_sl or sl
        sl_str = f"{float(active_sl):.6f}".rstrip("0") if active_sl else "—"
        tp_str = f"{float(tp):.6f}".rstrip("0") if tp else "—"
        if active_sl or tp:
            trailing_mark = " (trailing)" if trailing_sl else ""
            lines.append(f"   SL: {sl_str}{trailing_mark}  |  TP: {tp_str}")
        lines.extend(_plan_lines(p))

    lines.append("")
    lines.append("─" * 22)
    lines.append(f"Suma PnL: {_fpnl(total_pnl)}  |  Wartość: {_fval(total_val)} EUR")
    await _send_reply(update, "\n".join(lines), "/portfolio")


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = _mode()
    data = _api("GET", "/api/orders", params={"mode": mode, "limit": 10})
    orders_list = data if isinstance(data, list) else data.get("orders", data.get("data", []))

    if "error" in data and not orders_list:
        # fallback do DB
        db = SessionLocal()
        try:
            rows = db.query(Order).filter(Order.mode == mode).order_by(Order.timestamp.desc()).limit(10).all()
            orders_list = [
                {"symbol": o.symbol, "side": o.side, "quantity": o.quantity,
                 "status": o.status, "timestamp": str(o.timestamp),
                 "executed_price": getattr(o, "executed_price", None), "price": o.price}
                for o in rows
            ]
        finally:
            db.close()

    if not orders_list:
        await _send_reply(update, f"📭 Brak zleceń [{mode.upper()}].", "/orders")
        return

    lines = [f"🧾 Ostatnie zlecenia — {mode.upper()} ({len(orders_list)})", "─" * 22]
    for o in orders_list:
        sym = o.get("symbol", "?")
        side = o.get("side", "?")
        qty = o.get("quantity", 0)
        status = o.get("status", "?")
        price = o.get("executed_price") or o.get("price")
        ts = str(o.get("timestamp", ""))[:16].replace("T", " ")
        side_icon = "🟢" if side == "BUY" else "🔴"
        status_icon = "✅" if status in ("FILLED", "CONFIRMED") else "⏳" if status == "PENDING" else "❌"
        price_str = f"@ {_fval(price)}" if price else ""
        lines.append(f"{status_icon} {side_icon} {sym} {side} {_fval(float(qty), 4)} {price_str}")
        if ts:
            lines.append(f"   {ts}  [{status}]")
        lines.extend(_plan_lines(o))

    await _send_reply(update, "\n".join(lines), "/orders")


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await portfolio_command(update, context)


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uruchamia cykl analizy natychmiast."""
    if not await _check_auth(update):
        return
    await update.message.chat.send_action("typing")
    result = _api("POST", "/api/actions/analyze-now", timeout=30)
    if "error" in result:
        text = f"❌ Błąd analizy: {result['error']}"
    elif result.get("success"):
        msg = result.get("message", "")
        data = result.get("data", {})
        lines = ["🔄 Analiza zakończona ✅"]
        if msg:
            lines.append(msg[:100])
        if data:
            if "signals_generated" in data:
                lines.append(f"📊 Sygnały wygenerowane: {data['signals_generated']}")
            if "symbols_analyzed" in data:
                lines.append(f"🔍 Przeanalizowane symbole: {data['symbols_analyzed']}")
        text = "\n".join(lines)
    else:
        err = result.get("detail") or result.get("message", "Nieznany błąd")
        text = f"⚠️ Analiza: {str(err)[:150]}"
    await _send_reply(update, text, "/analyze")


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skanuje okazje rynkowe."""
    if not await _check_auth(update):
        return
    await update.message.chat.send_action("typing")
    result = _api("POST", "/api/actions/scan-opportunities", timeout=30)
    if "error" in result:
        text = f"❌ Błąd skanu: {result['error']}"
    elif result.get("success"):
        data = result.get("data", {})
        lines = ["🔍 Skan okazji ✅"]
        msg = result.get("message", "")
        if msg:
            lines.append(msg[:120])
        if "ready_count" in data:
            lines.append(f"✅ Gotowych do wejścia: {data['ready_count']}")
        if "blocked_count" in data:
            lines.append(f"🔒 Zablokowanych: {data['blocked_count']}")
        if "best_symbol" in data and data["best_symbol"]:
            lines.append(f"🌟 Najlepsza okazja: {data['best_symbol']}")
        text = "\n".join(lines)
    else:
        text = f"⚠️ Skan: {str(result.get('detail', result))[:150]}"
    await _send_reply(update, text, "/scan")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pokazuje aktualny tryb trading."""
    mode = _mode()
    mode_icon = "🔴" if mode == "live" else "🟡"
    lines = [
        f"{mode_icon} Tryb trading: {mode.upper()}",
        f"Zmienna TRADING_MODE={mode}",
        "",
        "Aby zmienić tryb: edytuj .env → TRADING_MODE=live/demo i zrestartuj backend.",
    ]
    await _send_reply(update, "\n".join(lines), "/mode")


async def lastsignal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        sig = db.query(Signal).order_by(Signal.timestamp.desc()).first()
        if not sig:
            text = "Brak sygnałów."
        else:
            text = (
                "Ostatni sygnał\n"
                f"Para: {sig.symbol}\n"
                f"Kierunek: {sig.signal_type}\n"
                f"Pewność: {int(sig.confidence*100)}%\n"
                f"Czas: {sig.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            plan = {}
            try:
                plan = json.loads(sig.plan_json) if getattr(sig, "plan_json", None) else {}
            except Exception:
                plan = {}
            if plan:
                payload = {
                    "action": plan.get("action"),
                    "plan_status": getattr(sig, "plan_status", None) or plan.get("plan_status"),
                    "entry_price": plan.get("entry_price"),
                    "take_profit_price": plan.get("take_profit_price"),
                    "stop_loss_price": plan.get("stop_loss_price"),
                    "break_even_price": plan.get("break_even_price"),
                    "expected_net_profit": plan.get("expected_net_profit"),
                    "confidence_score": plan.get("confidence_score"),
                    "risk_score": plan.get("risk_score"),
                    "requires_revision": getattr(sig, "requires_revision", False) or plan.get("requires_revision"),
                    "invalidation_reason": getattr(sig, "invalidation_reason", None) or plan.get("invalidation_reason"),
                    "last_consulted_at": sig.last_consulted_at.isoformat() if getattr(sig, "last_consulted_at", None) else plan.get("last_consulted_at"),
                }
                text += "\n" + "\n".join(_plan_lines(payload))
            post = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
            if post and post.market_insights:
                try:
                    insights = json.loads(post.market_insights)
                    for ins in insights:
                        if ins.get("symbol") == sig.symbol and ins.get("range"):
                            r = ins.get("range")
                            text += (
                                "\n\nOpenAI – decyzja\n"
                                f"Kupno: {r.get('buy_action')} (cel: {r.get('buy_target')})\n"
                                f"Sprzedaż: {r.get('sell_action')} (cel: {r.get('sell_target')})\n"
                                f"Zakres BUY: {r.get('buy_low')} – {r.get('buy_high')}\n"
                                f"Zakres SELL: {r.get('sell_low')} – {r.get('sell_high')}"
                            )
                            break
                except Exception:
                    pass
    finally:
        db.close()

    await _send_reply(update, text, "/lastsignal")


async def blog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        post = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
        if not post:
            text = "Brak wpisów bloga."
        else:
            lines = [f"Blog: {post.title}"]
            if post.summary:
                lines.append(f"Podsumowanie: {post.summary}")
            if post.market_insights:
                try:
                    insights = json.loads(post.market_insights)
                    lines.append("\nOpenAI – decyzje kup/sprzedaj")
                    for ins in insights:
                        r = ins.get("range")
                        if r:
                            lines.append(
                                f"• {ins.get('symbol')}\n"
                                f"  Kupno: {r.get('buy_action')} (cel: {r.get('buy_target')})\n"
                                f"  Sprzedaż: {r.get('sell_action')} (cel: {r.get('sell_target')})\n"
                                f"  Zakres BUY: {r.get('buy_low')} – {r.get('buy_high')}\n"
                                f"  Zakres SELL: {r.get('sell_low')} – {r.get('sell_high')}"
                            )
                except Exception:
                    pass
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/blog")


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        # Pokaż ostatnie ERROR + WARNING — nie wszystkie logi
        errors = db.query(SystemLog).filter(SystemLog.level == "ERROR").order_by(SystemLog.id.desc()).limit(5).all()
        warnings = db.query(SystemLog).filter(SystemLog.level == "WARNING").order_by(SystemLog.id.desc()).limit(3).all()
        infos = db.query(SystemLog).filter(SystemLog.level == "INFO").order_by(SystemLog.id.desc()).limit(3).all()
    finally:
        db.close()

    lines = ["🧱 Ostatnie logi systemu", "─" * 22]

    if errors:
        lines.append("🔴 BŁĘDY:")
        for e in errors:
            age = int((utc_now_naive() - e.timestamp).total_seconds())
            age_str = f"{age//60}min" if age >= 60 else f"{age}s"
            lines.append(f"  [{age_str}] {e.module}: {str(e.message or '')[:70]}")
    else:
        lines.append("🟢 Brak błędów")

    if warnings:
        lines.append("🟡 OSTRZEŻENIA:")
        for w in warnings:
            age = int((utc_now_naive() - w.timestamp).total_seconds())
            age_str = f"{age//60}min" if age >= 60 else f"{age}s"
            lines.append(f"  [{age_str}] {w.module}: {str(w.message or '')[:60]}")

    if infos:
        lines.append("ℹ️ INFO (ostatnie):")
        for i in infos:
            lines.append(f"  {i.timestamp.strftime('%H:%M')} {i.module}: {str(i.message or '')[:50]}")

    await _send_reply(update, "\n".join(lines), "/logs")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        orders = db.query(Order).filter(Order.mode == "demo").order_by(Order.timestamp.desc()).limit(10).all()
        if not orders:
            text = "Brak danych do raportu."
        else:
            lines = ["Raport (ostatnie 10 decyzji)"]
            for o in orders:
                alert = db.query(Alert).filter(
                    Alert.symbol == o.symbol,
                    Alert.alert_type == "SIGNAL",
                    Alert.timestamp <= o.timestamp + timedelta(minutes=2),
                    Alert.timestamp >= o.timestamp - timedelta(minutes=2)
                ).order_by(Alert.timestamp.desc()).first()
                reason = alert.message if alert and alert.message else "brak uzasadnienia"
                side_pl = "Kupno" if o.side == "BUY" else "Sprzedaż"
                price = o.executed_price or o.price
                lines.append(
                    f"{o.timestamp.strftime('%H:%M')} — {side_pl} {o.symbol}. "
                    f"Ilość {o.quantity}, cena {price}. "
                    f"Uzasadnienie: {reason}."
                )
            lines.append("\nWniosek: decyzje wykonano zgodnie z filtrem trendu i zakresem AI.")
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/report")


async def confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        if not context.args:
            await _send_reply(update, "Użycie: /confirm <ID>", "/confirm")
            return
        try:
            pending_id = int(context.args[0])
        except ValueError:
            await _send_reply(update, "Nieprawidłowy ID", "/confirm")
            return
        pending = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
        if not pending:
            await _send_reply(update, "Nie znaleziono transakcji", "/confirm")
            return
        pending.status = "CONFIRMED"
        pending.confirmed_at = utc_now_naive()
        db.commit()
        await _send_reply(
            update,
            (
                f"Potwierdzono: ID {pending_id} ({pending.side} {pending.symbol} qty={pending.quantity}).\n"
                "Wykonam w następnym cyklu kolektora (zwykle do 60s)."
            ),
            "/confirm",
        )
    finally:
        db.close()


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        if not context.args:
            await _send_reply(update, "Użycie: /reject <ID>", "/reject")
            return
        try:
            pending_id = int(context.args[0])
        except ValueError:
            await _send_reply(update, "Nieprawidłowy ID", "/reject")
            return
        pending = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
        if not pending:
            await _send_reply(update, "Nie znaleziono transakcji", "/reject")
            return
        pending.status = "REJECTED"
        pending.confirmed_at = utc_now_naive()
        db.commit()
        await _send_reply(
            update,
            f"Odrzucono: ID {pending_id} ({pending.side} {pending.symbol} qty={pending.quantity}).",
            "/reject",
        )
    finally:
        db.close()


async def governance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pipeline status + operator queue summary."""
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        from backend.governance import get_pipeline_status, get_operator_queue

        status = get_pipeline_status(db)
        queue = get_operator_queue(db)

        promo_ok = status.get("promotion_allowed")
        rollback_ok = status.get("rollback_allowed")
        exp_ok = status.get("experiment_allowed")
        rec_ok = status.get("recommendation_allowed")

        all_ok = promo_ok and rollback_ok and exp_ok and rec_ok

        if all_ok:
            lines = ["✅ Pipeline otwarty — wszystko działa normalnie"]
        else:
            lines = ["🟠 Pipeline częściowo zablokowany"]
            if not promo_ok:
                lines.append(f"  🚫 Wdrożenia zablokowane ({status.get('promotion_blockers_count', 0)} alertów)")
            if not rollback_ok:
                lines.append(f"  🚫 Cofanie zmian zablokowane ({status.get('rollback_blockers_count', 0)} alertów)")
            if not exp_ok:
                lines.append(f"  🚫 Eksperymenty zablokowane ({status.get('experiment_blockers_count', 0)} alertów)")
            if not rec_ok:
                lines.append(f"  🚫 Rekomendacje zablokowane ({status.get('recommendation_blockers_count', 0)} alertów)")

        if queue:
            lines.append(f"\nDo przejrzenia: {len(queue)} spraw")
            for item in queue[:5]:
                prio = item.get("priority", "?")
                summary = (item.get("summary") or "-")[:60]
                sla_info = " ⏰ PILNE!" if item.get("sla_breached") else ""
                lines.append(f"  • [{prio}] {summary}{sla_info}")
            if len(queue) > 5:
                lines.append(f"  … i {len(queue) - 5} więcej")
        elif all_ok:
            pass
        else:
            lines.append("\nBrak spraw w kolejce operatora.")

        text = "\n".join(lines)
    except Exception as exc:
        text = f"❌ Błąd governance: {exc}"
    finally:
        db.close()

    await _send_reply(update, text, "/governance")


async def freeze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wyświetl aktywne blokady pipeline."""
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        from backend.governance import check_pipeline_permission

        operations = ["promotion", "rollback", "experiment", "recommendation"]
        any_blocked = False
        lines = []
        op_labels = {
            "promotion": "Wdrożenia",
            "rollback": "Cofanie zmian",
            "experiment": "Eksperymenty",
            "recommendation": "Rekomendacje",
        }
        for op in operations:
            result = check_pipeline_permission(db, op)
            if not result["allowed"]:
                any_blocked = True
                blockers = result["blocking_actions"]
                op_pl = op_labels.get(op, op)
                lines.append(f"\n🚫 {op_pl} — zablokowane ({len(blockers)} alertów)")
                for b in blockers[:3]:
                    pa_id = b.get("policy_action_id", "?")
                    prio = b.get("priority", "?")
                    lines.append(f"  • alert #{pa_id} (pilność: {prio})")
                if len(blockers) > 3:
                    lines.append(f"  … i {len(blockers) - 3} więcej")

        if not any_blocked:
            lines = ["✅ Brak blokad — pipeline otwarty, wszystko działa normalnie"]
        else:
            lines.insert(0, "🔒 Aktywne blokady:")
            lines.append("\nCo zrobić: przejrzyj alerty komendą /incidents")

        text = "\n".join(lines)
    except Exception as exc:
        text = f"❌ Błąd freeze: {exc}"
    finally:
        db.close()

    await _send_reply(update, text, "/freeze")


async def incidents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista aktywnych incydentów."""
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        from backend.governance import list_incidents

        active = list_incidents(db)
        active = [i for i in active if i.get("status") != "resolved"]

        if not active:
            text = "✅ Brak aktywnych incydentów — wszystko w porządku"
        else:
            prio_labels = {"critical": "krytyczna", "high": "wysoka", "medium": "średnia", "low": "niska"}
            lines = [f"🔔 Aktywne incydenty: {len(active)}"]
            for inc in active[:10]:
                inc_id = inc.get("id", "?")
                prio = inc.get("priority", "?")
                prio_pl = prio_labels.get(prio, prio)
                icon = "🔴" if prio == "critical" else "🟠" if prio == "high" else "🟡"
                lines.append(f"{icon} #{inc_id} — pilność: {prio_pl}")
            if len(active) > 10:
                lines.append(f"… i {len(active) - 10} więcej")
            lines.append("\nCo zrobić: przejrzyj i zamknij nieaktualne incydenty")
            text = "\n".join(lines)
    except Exception as exc:
        text = f"❌ Błąd incidents: {exc}"
    finally:
        db.close()

    await _send_reply(update, text, "/incidents")


async def chat_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Obsługuje dowolny tekst (nie komendy) — chat AI jak Copilot."""
    if not await _check_auth(update):
        return

    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    # Pokaż że bot pisze (naturalny feel)
    await update.message.chat.send_action("typing")

    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/actions/ai/chat",
            json={"message": user_text},
            headers={"X-Admin-Token": ADMIN_TOKEN, "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("response", "Brak odpowiedzi.")
            provider = data.get("provider", "?")
            provider_tag = {
                "openai": "GPT-4o",
                "gemini": "Gemini",
                "groq": "Groq/Llama",
                "heuristic": "Heurystyka",
                "heuristic_fallback": "Heurystyka (fallback)",
            }.get(provider, provider)
            text = f"{answer}\n\n_— {provider_tag}_"
        elif resp.status_code == 401:
            text = "⛔ Błąd autoryzacji AI — sprawdź ADMIN_TOKEN w .env."
        else:
            text = f"⚠️ Błąd AI (HTTP {resp.status_code}) — spróbuj /status lub /help."
    except requests.exceptions.Timeout:
        text = "⏳ AI odpowiada za długo (timeout 30s). Spróbuj za chwilę."
    except Exception as exc:
        text = f"❌ Błąd: {exc}"

    await _send_reply(update, text)
    log_telegram_event(
        chat_id=str(update.effective_chat.id),
        direction="incoming",
        raw_text=user_text,
        source_module="telegram_bot",
        message_type="chat",
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN w .env")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("risk", risk_command))
    app.add_handler(CommandHandler("top10", top10_command))
    app.add_handler(CommandHandler("top5", top5_command))
    app.add_handler(CommandHandler("portfolio", portfolio_command))
    app.add_handler(CommandHandler("orders", orders_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("lastsignal", lastsignal_command))
    app.add_handler(CommandHandler("blog", blog_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("confirm", confirm_command))
    app.add_handler(CommandHandler("reject", reject_command))
    app.add_handler(CommandHandler("governance", governance_command))
    app.add_handler(CommandHandler("freeze", freeze_command))
    app.add_handler(CommandHandler("incidents", incidents_command))
    app.add_handler(CommandHandler("ip", ip_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(CommandHandler("mode", mode_command))

    # Obsługa dowolnych wiadomości tekstowych (chat AI)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
