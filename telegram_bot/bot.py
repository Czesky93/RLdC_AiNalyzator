"""
Telegram Bot for RLdC Trading Bot
"""

import asyncio
import json
import os
from datetime import timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from backend.database import (
    Alert,
    BlogPost,
    Incident,
    ManualTradeDetection,
    Order,
    PendingOrder,
    PolicyAction,
    Position,
    ReconciliationRun,
    SessionLocal,
    Signal,
    SystemLog,
    utc_now_naive,
)
from backend.telegram_intelligence import log_telegram_event

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
TRADING_MODE = os.getenv("TRADING_MODE", "demo")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
_HTTP_TIMEOUT_LIGHT = (2, 6)
_HTTP_TIMEOUT_HEAVY = (2, 12)

ACTIVE_PENDING_STATUSES = [
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
]
FINAL_PENDING_STATUSES = ["EXECUTED", "REJECTED", "CANCELLED", "FAILED", "FILLED"]


def _api_headers() -> dict:
    headers = {}
    if ADMIN_TOKEN:
        headers["X-Admin-Token"] = ADMIN_TOKEN
    return headers


def _http_get_json(
    url: str, timeout: tuple = _HTTP_TIMEOUT_LIGHT
) -> tuple[dict, Optional[str]]:
    try:
        resp = requests.get(url, headers=_api_headers(), timeout=timeout)
    except requests.Timeout:
        return {}, "timeout"
    except requests.RequestException as exc:
        return {}, f"request_error:{exc}"
    if resp.status_code != 200:
        return {}, f"http_{resp.status_code}"
    try:
        return resp.json() or {}, None
    except Exception:
        return {}, "invalid_json"


def _is_lightweight_nl(text: str) -> Optional[str]:
    norm = (text or "").strip().lower()
    if not norm:
        return None
    if norm in {"status", "stan", "health", "zdrowie"}:
        return "status"
    if norm in {"ai", "model", "modele"}:
        return "ai"
    if norm in {"ip", "tunnel", "tunel"}:
        return "ip"
    if norm in {"portfolio", "portfel", "pozycje"}:
        return "portfolio"
    return None


def _command_timeout_message() -> str:
    return (
        "⏱️ Backend odpowiada zbyt wolno dla tego polecenia. "
        "Spróbuj za chwilę albo użyj lekkich komend: /status, /ai, /ip."
    )


def _fmt_money(value: Optional[float], ccy: str = "EUR") -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f} {ccy}"


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
        chat_id = str(update.effective_chat.id) if update.effective_chat else "unknown"
        await update.message.reply_text(
            f"⛔ Brak dostępu. Ten chat_id={chat_id}, oczekiwany TELEGRAM_CHAT_ID={TELEGRAM_CHAT_ID or 'brak konfiguracji'}"
        )
        return False
    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 RLdC Trading Bot\n"
        "\n"
        "📈 Trading:\n"
        "  /status     — pełny status systemu\n"
        "  /portfolio  — portfel i pozycje\n"
        "  /positions  — alias /portfolio\n"
        "  /orders     — ostatnie zlecenia\n"
        "  /risk       — parametry ryzyka\n"
        "\n"
        "⏸ Pending trades:\n"
        "  /pending             — lista oczekujących transakcji\n"
        "  /trade <ID>          — szczegóły transakcji\n"
        "  /confirm <trade_ID>  — potwierdź transakcję\n"
        "  /reject <trade_ID>   — odrzuć transakcję\n"
        "\n"
        "🔔 Incydenty (pipeline/governance):\n"
        "  /incidents            — lista aktywnych incydentów\n"
        "  /incident <ID>        — szczegóły incydentu\n"
        "  /close_incident <ID>  — zamknij incydent\n"
        "  /governance           — status pipeline + kolejka\n"
        "  /freeze               — aktywne blokady\n"
        "\n"
        "🔧 Diagnostyka:\n"
        "  /health     — stan systemu\n"
        "  /reconcile  — synchronizuj DB z Binance\n"
        "  /ai         — status AI providers\n"
        "  /ai_budget  — dzienny budżet external AI\n"
        "  /execution  — status execution layer\n"
        "  /universe   — symbol universe\n"
        "  /universe_stats — statystyki pełnego universe\n"
        "  /quote <SYMBOL> — quote dla prawdziwego symbolu Binance\n"
        "  /quote_status — status walut quote\n"
        "  /ip         — diagnostyka IP / tunnel\n"
        "  /logs       — ostatnie logi\n"
        "  /env        — zmienne konfiguracyjne\n"
        "\n"
        "💬 Natural language:\n"
        "  kup btc / sprzedaj eth\n"
        "  pokaż pending / pokaż incydenty\n"
        "  potwierdź trade 12 / odrzuć trade 12\n"
        "  zamknij incydent 33\n"
        "\n"
        f"Tryb: {TRADING_MODE}"
    )
    await _send_reply(update, text, "/start")


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id) if update.effective_chat else "unknown"
    text = (
        "🧭 Diagnostyka Telegram\n"
        f"Twoj chat_id: {chat_id}\n"
        f"Skonfigurowany TELEGRAM_CHAT_ID: {TELEGRAM_CHAT_ID or 'brak'}"
    )
    await _send_reply(update, text, "/chatid")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        full_payload, full_err = _http_get_json(
            f"{API_BASE_URL}/api/system/full-status", timeout=_HTTP_TIMEOUT_LIGHT
        )
        runtime_payload, runtime_err = _http_get_json(
            f"{API_BASE_URL}/api/account/runtime-activity?mode={TRADING_MODE}",
            timeout=_HTTP_TIMEOUT_LIGHT,
        )
        ai_payload, ai_err = _http_get_json(
            f"{API_BASE_URL}/api/account/ai-orchestrator-status",
            timeout=_HTTP_TIMEOUT_LIGHT,
        )

        full = (full_payload or {}).get("data") or {}
        runtime = (runtime_payload or {}).get("data") or {}
        ai = (ai_payload or {}).get("data") or {}

        collector = runtime.get("collector") or {}
        last_decision = runtime.get("last_decision") or {}
        last_order = runtime.get("last_order") or {}
        market_data = runtime.get("market_data") or {}
        open_positions_count = int(full.get("open_positions") or 0)
        pending_orders_count = int(full.get("pending_active") or 0)
        exchange_connected = (full.get("live_execution_ok") is True) or (
            full.get("trading_mode") != "live"
        )
        mode_label = str(full.get("trading_mode") or TRADING_MODE)

        text = (
            "✅ Pelny status systemu\n"
            f"Tryb: {mode_label}\n"
            f"Collector active: {'TAK' if collector.get('running') else 'NIE'}\n"
            f"WebSocket connected: {'TAK' if collector.get('ws_running') else 'NIE'}\n"
            f"Exchange connectivity: {'TAK' if exchange_connected else 'NIE'}\n"
            f"AI provider active: {ai.get('primary', 'unknown')}\n"
            f"Fallback active: {'TAK' if ai.get('fallback_active') else 'NIE'}\n"
            f"Open positions: {open_positions_count}\n"
            f"Pending orders: {pending_orders_count}\n"
            f"Last signal: {last_decision.get('symbol', 'brak')} {last_decision.get('reason_code', '')}\n"
            f"Last order: {last_order.get('symbol', 'brak')} {last_order.get('side', '')} {last_order.get('status', '')}\n"
            f"Last market update age: {market_data.get('last_tick_age_s', 'brak')}s\n"
            f"Last reconcile: {collector.get('last_binance_sync_ts', 'brak')}\n"
            f"Last error: {(runtime.get('last_error') or {}).get('message', 'brak')}\n"
            f"Governance/freeze: blocker_count={int(full.get('incidents_open') or 0)}"
        )
        warn_bits = [x for x in (full_err, runtime_err, ai_err) if x]
        if warn_bits:
            text += "\n⚠️ Część danych niedostępna (degradacja kontrolowana)."
    except Exception as exc:
        text = f"❌ Blad statusu: {exc}"
    await _send_reply(update, text, "/status")


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
            text = (
                f"⚠️ Nie udało się zatrzymać (status {resp.status_code}). Sprawdź API."
            )
    except Exception as exc:
        text = f"❌ Błąd wywołania API: {exc}"
    await _send_reply(update, text, "/stop")


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    max_daily_loss = float(os.getenv("MAX_DAILY_LOSS_PERCENT", "5.0"))
    max_drawdown = float(os.getenv("MAX_DRAWDOWN_PERCENT", "10.0"))
    initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000"))

    db = SessionLocal()
    try:
        positions = db.query(Position).filter(Position.mode == TRADING_MODE).all()
        unrealized_pnl = sum((p.unrealized_pnl or 0.0) for p in positions)
        worst_dd = 0.0
        for p in positions:
            if p.entry_price and p.current_price and p.entry_price > 0:
                dd = ((p.current_price - p.entry_price) / p.entry_price) * 100
                if dd < worst_dd:
                    worst_dd = dd
    finally:
        db.close()

    daily_loss_limit = -(initial_balance * max_daily_loss / 100)
    text = (
        "⚠️ Ryzyko\n"
        f"Maks. dzienna strata: {max_daily_loss}% (limit {daily_loss_limit:.2f})\n"
        f"Maks. drawdown: {max_drawdown}%\n"
        f"Unrealized PnL: {unrealized_pnl:.2f}\n"
        f"Najgorszy DD: {worst_dd:.2f}%"
    )
    await _send_reply(update, text, "/risk")


async def top10_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        signals = (
            db.query(Signal)
            .filter(Signal.signal_type.in_(["BUY", "SELL"]))
            .order_by(Signal.confidence.desc())
            .limit(10)
            .all()
        )
        if not signals:
            text = "Brak sygnałów w bazie."
        else:
            lines = ["📊 Top 10 sygnałów:"]
            for s in signals:
                lines.append(f"{s.symbol} {s.signal_type} ({int(s.confidence*100)}%)")
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/top10")


async def top5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        signals = (
            db.query(Signal)
            .filter(Signal.signal_type.in_(["BUY", "SELL"]))
            .order_by(Signal.confidence.desc())
            .limit(5)
            .all()
        )
        if not signals:
            text = "Brak sygnałów w bazie."
        else:
            lines = ["📈 Top 5 sygnałów:"]
            for s in signals:
                lines.append(f"{s.symbol} {s.signal_type} ({int(s.confidence*100)}%)")
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/top5")


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/portfolio/wealth?mode={TRADING_MODE}",
            timeout=8,
        )
        if resp.status_code != 200:
            await _send_reply(
                update, f"❌ API portfolio error: {resp.status_code}", "/portfolio"
            )
            return

        data = (resp.json() or {}).get("data") or {}
        items = list(data.get("items") or [])
        if not items:
            text = "Brak otwartych pozycji."
            await _send_reply(update, text, "/portfolio")
            return

        items = sorted(
            items, key=lambda x: float(x.get("pnl_eur") or 0.0), reverse=True
        )
        green = sum(1 for i in items if float(i.get("pnl_eur") or 0.0) >= 0)
        red = len(items) - green
        best = items[0]
        worst = items[-1]

        lines = [
            "💼 Portfolio",
            f"Wartosc portfela: {_fmt_money(float(data.get('portfolio_value') or 0.0))}",
            f"Ekspozycja: {_fmt_money(float(data.get('positions_value') or 0.0))}",
            f"Pozycje zielone/czerwone: {green}/{red}",
            f"Najlepsza: {best.get('symbol')} {_fmt_money(float(best.get('pnl_eur') or 0.0))} ({float(best.get('pnl_pct') or 0.0):+.2f}%)",
            f"Najsłabsza: {worst.get('symbol')} {_fmt_money(float(worst.get('pnl_eur') or 0.0))} ({float(worst.get('pnl_pct') or 0.0):+.2f}%)",
            "",
            "Ranking pozycji:",
        ]
        for idx, p in enumerate(items, 1):
            qty = float(p.get("quantity") or 0.0)
            pnl = float(p.get("pnl_eur") or 0.0)
            pnl_pct = float(p.get("pnl_pct") or 0.0)
            lines.append(
                f"{idx}. {p.get('symbol')} qty={qty:.6f} PnL: {_fmt_money(pnl)} ({pnl_pct:+.2f}%)"
            )
        text = "\n".join(lines)
    except Exception as exc:
        text = f"❌ Blad portfolio: {exc}"

    await _send_reply(update, text, "/portfolio")


async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .filter(Order.mode == TRADING_MODE)
            .order_by(Order.timestamp.desc())
            .limit(10)
            .all()
        )
        if not orders:
            text = "Brak zleceń."
        else:
            lines = ["🧾 Ostatnie zlecenia:"]
            for o in orders:
                lines.append(f"{o.symbol} {o.side} {o.quantity} {o.status}")
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/orders")


async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await portfolio_command(update, context)


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
        logs = db.query(SystemLog).order_by(SystemLog.timestamp.desc()).limit(5).all()
        if not logs:
            text = "Brak logów."
        else:
            lines = ["🧱 Ostatnie logi:"]
            for l in logs:
                lines.append(
                    f"{l.timestamp.strftime('%H:%M:%S')} {l.level} {l.module}: {l.message}"
                )
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/logs")


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        orders = (
            db.query(Order)
            .filter(Order.mode == "demo")
            .order_by(Order.timestamp.desc())
            .limit(10)
            .all()
        )
        if not orders:
            text = "Brak danych do raportu."
        else:
            lines = ["Raport (ostatnie 10 decyzji)"]
            for o in orders:
                alert = (
                    db.query(Alert)
                    .filter(
                        Alert.symbol == o.symbol,
                        Alert.alert_type == "SIGNAL",
                        Alert.timestamp <= o.timestamp + timedelta(minutes=2),
                        Alert.timestamp >= o.timestamp - timedelta(minutes=2),
                    )
                    .order_by(Alert.timestamp.desc())
                    .first()
                )
                reason = (
                    alert.message if alert and alert.message else "brak uzasadnienia"
                )
                side_pl = "Kupno" if o.side == "BUY" else "Sprzedaż"
                price = o.executed_price or o.price
                lines.append(
                    f"{o.timestamp.strftime('%H:%M')} — {side_pl} {o.symbol}. "
                    f"Ilość {o.quantity}, cena {price}. "
                    f"Uzasadnienie: {reason}."
                )
            lines.append(
                "\nWniosek: decyzje wykonano zgodnie z filtrem trendu i zakresem AI."
            )
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
            await _send_reply(update, "Użycie: /confirm <trade_ID>", "/confirm")
            return
        try:
            pending_id = int(context.args[0])
        except ValueError:
            await _send_reply(
                update, "Nieprawidłowy ID — podaj liczbę całkowitą.", "/confirm"
            )
            return

        # Sprawdź czy to pending trade
        pending = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.id == pending_id,
                PendingOrder.mode == TRADING_MODE,
            )
            .first()
        )
        if pending:
            if pending.status in FINAL_PENDING_STATUSES:
                await _send_reply(
                    update,
                    f"⚠️ Trade #{pending_id} nie może być potwierdzone — status: {pending.status}.",
                    "/confirm",
                )
                return
            pending.status = "PENDING_CONFIRMED"
            pending.confirmed_at = utc_now_naive()
            db.commit()
            await _send_reply(
                update,
                (
                    f"✅ Potwierdzono trade #{pending_id}\n"
                    f"Symbol: {pending.symbol} | Strona: {pending.side} | Qty: {pending.quantity}\n"
                    "Kolektor wykona w następnym cyklu (~30-60s)."
                ),
                "/confirm",
            )
            return

        # Nie znaleziono pending — sprawdź czy to incydent
        incident = db.query(Incident).filter(Incident.id == pending_id).first()
        if incident:
            await _send_reply(
                update,
                (
                    f"⚠️ ID {pending_id} to INCYDENT, nie trade.\n"
                    f"Incydenty zarządzasz przez:\n"
                    f"  /incident {pending_id}   — szczegóły\n"
                    f"  /close_incident {pending_id}  — zamknij incydent\n"
                    f"\n"
                    f"Aby potwierdzić TRANSAKCJĘ: /confirm <trade_ID>\n"
                    f"Listę transakcji zobaczysz przez: /pending"
                ),
                "/confirm",
            )
            return

        # Nie znaleziono nic
        await _send_reply(
            update,
            (
                f"❌ Nie znaleziono pending trade #{pending_id} w trybie {TRADING_MODE}.\n"
                f"Sprawdź listę: /pending"
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
            await _send_reply(update, "Użycie: /reject <trade_ID>", "/reject")
            return
        try:
            pending_id = int(context.args[0])
        except ValueError:
            await _send_reply(
                update, "Nieprawidłowy ID — podaj liczbę całkowitą.", "/reject"
            )
            return

        # Sprawdź czy to pending trade
        pending = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.id == pending_id,
                PendingOrder.mode == TRADING_MODE,
            )
            .first()
        )
        if pending:
            if pending.status in FINAL_PENDING_STATUSES:
                await _send_reply(
                    update,
                    f"⚠️ Trade #{pending_id} nie może być odrzucone — status: {pending.status}.",
                    "/reject",
                )
                return
            pending.status = "REJECTED"
            pending.confirmed_at = utc_now_naive()
            db.commit()
            await _send_reply(
                update,
                f"🚫 Odrzucono trade #{pending_id} ({pending.side} {pending.symbol} qty={pending.quantity}).",
                "/reject",
            )
            return

        # Nie znaleziono pending — sprawdź czy to incydent
        incident = db.query(Incident).filter(Incident.id == pending_id).first()
        if incident:
            await _send_reply(
                update,
                (
                    f"⚠️ ID {pending_id} to INCYDENT, nie trade.\n"
                    f"Do zamykania incydentów używaj:\n"
                    f"  /close_incident {pending_id}\n"
                    f"\n"
                    f"Aby odrzucić TRANSAKCJĘ: /reject <trade_ID>\n"
                    f"Listę transakcji zobaczysz przez: /pending"
                ),
                "/reject",
            )
            return

        await _send_reply(
            update,
            (
                f"❌ Nie znaleziono pending trade #{pending_id} w trybie {TRADING_MODE}.\n"
                f"Sprawdź listę: /pending"
            ),
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
        from backend.governance import (
            get_operator_queue_with_summary,
            get_pipeline_status,
        )

        status = get_pipeline_status(db)
        queue_payload = get_operator_queue_with_summary(db)
        queue = queue_payload.get("items") or []
        summary = queue_payload.get("summary") or {}

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
                lines.append(
                    f"  🚫 Wdrożenia zablokowane ({status.get('promotion_blockers_count', 0)} alertów)"
                )
            if not rollback_ok:
                lines.append(
                    f"  🚫 Cofanie zmian zablokowane ({status.get('rollback_blockers_count', 0)} alertów)"
                )
            if not exp_ok:
                lines.append(
                    f"  🚫 Eksperymenty zablokowane ({status.get('experiment_blockers_count', 0)} alertów)"
                )
            if not rec_ok:
                lines.append(
                    f"  🚫 Rekomendacje zablokowane ({status.get('recommendation_blockers_count', 0)} alertów)"
                )

        if queue:
            lines.append(
                "\nKolejka operatora: "
                f"backlog={summary.get('backlog_total', len(queue))}, "
                f"SLA breach={summary.get('sla_breached_count', 0)}, "
                f"SLA <=15m={summary.get('sla_due_15m_count', 0)}"
            )
            for item in queue[:5]:
                prio = item.get("priority", "?")
                item_summary = (item.get("summary") or "-")[:60]
                sla_info = " ⏰ PILNE!" if item.get("sla_breached") else ""
                incident_id = item.get("incident_id")
                trade_id = item.get("trade_id")
                id_hint = (
                    f"inc#{incident_id}"
                    if incident_id is not None
                    else f"pa#{item.get('policy_action_id')}"
                )
                if trade_id is not None:
                    id_hint += f" trade#{trade_id}"
                lines.append(f"  • [{prio}] {id_hint} {item_summary}{sla_info}")
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
            prio_labels = {
                "critical": "krytyczna",
                "high": "wysoka",
                "medium": "średnia",
                "low": "niska",
            }
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


async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pelna diagnostyka IP dla direct/proxy/tunnel — z weryfikacją reachability + auto-heal."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/account/ip-diagnostics", timeout=12)
        tun_resp = requests.get(f"{API_BASE_URL}/api/account/tunnel-status", timeout=8)
        tun_data: dict = {}
        if tun_resp.status_code == 200:
            tun_data = (tun_resp.json() or {}).get("data") or {}

        if resp.status_code != 200:
            text = f"❌ API error: {resp.status_code}"
        else:
            d = (resp.json() or {}).get("data") or {}
            notes = d.get("notes") or []
            url_status = d.get("url_status") or []

            lines = [
                "🌍 IP / Tunnel diagnostics",
                f"Hostname: {d.get('hostname') or '-'}",
                f"Local IP: {d.get('local_ip') or '-'}",
                f"Public egress IP: {d.get('public_egress_ip') or '-'}",
                f"Local frontend (:{tun_data.get('local_frontend_port', 3000)}): "
                f"{'✅ OK' if tun_data.get('local_frontend_ok') else '❌ DOWN'}",
                f"Tunnel process running: {'✅' if d.get('tunnel_process_running') else '❌ NIE'}",
                "",
            ]

            if url_status:
                lines.append("🔗 URL status (HTTP probe):")
                for u in url_status:
                    icon = "✅" if u.get("reachable") else "❌"
                    ttype = u.get("tunnel_type", "?")
                    status = u.get("status", "?")
                    lines.append(f"{icon} [{ttype}] {u.get('url')} — {status}")
            else:
                lines.append("Brak skonfigurowanych publicznych URL-i")

            act_fe = d.get("active_frontend_url") or tun_data.get("active_url")
            if act_fe:
                lines.append("")
                lines.append("🟢 Aktywny adres publiczny:")
                src = tun_data.get("source") or "?"
                lines.append(f"  {act_fe} [{src}]")
            elif url_status:
                lines.append("")
                any_reachable = any(u.get("reachable") for u in url_status)
                if not any_reachable:
                    # Spróbuj auto-heal
                    lines.append(
                        "🔴 Żaden URL nie jest osiągalny — próbuję auto-naprawę..."
                    )
                    heal_resp = requests.post(
                        f"{API_BASE_URL}/api/account/tunnel-heal?force=false",
                        timeout=60,
                    )
                    if heal_resp.status_code == 200:
                        heal = (heal_resp.json() or {}).get("data") or {}
                        new_url = heal.get("active_url")
                        if new_url:
                            lines.append(f"✅ Auto-naprawa udana! Nowy URL: {new_url}")
                            lines.append(f"   Źródło: {heal.get('source')}")
                            lines.append(
                                f"   .env zaktualizowane: {'✅' if heal.get('env_updated') else '—'}"
                            )
                        else:
                            lines.append(
                                "✅ Auto-naprawa: brak nowego URL w odpowiedzi"
                            )
                    else:
                        heal_err = (
                            heal_resp.json() if heal_resp.status_code < 500 else {}
                        )
                        step = heal_err.get("detail", {})
                        if isinstance(step, dict):
                            step = step.get("error_step", heal_resp.status_code)
                        lines.append(f"❌ Auto-naprawa nie powiodła się: {step}")

            # Info o ostatnim recovery
            if tun_data.get("last_recovery_at"):
                lines.append("")
                lines.append(
                    f"🔄 Ostatni restart: {tun_data['last_recovery_at'][:19]} "
                    f"[{tun_data.get('last_recovery_result', '?')}]"
                )
                if tun_data.get("recovery_count"):
                    lines.append(f"   Próby recovery: {tun_data['recovery_count']}")

            if notes:
                lines.append("")
                lines.append("⚠️ Uwagi:")
                for n in notes:
                    lines.append(f"- {n}")

            text = "\n".join(lines)
    except requests.Timeout:
        text = "⏱️ Timeout: backend nie odpowiedzial"
    except Exception as exc:
        text = f"❌ Blad pobrania IP: {exc}"
    await _send_reply(update, text, "/ip")


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rozszerzona diagnostyka multi-provider AI i fallback chain."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/account/ai-orchestrator-status", timeout=10
        )
        if resp.status_code == 200:
            data = (resp.json() or {}).get("data") or {}
            providers = data.get("providers") or {}
            openai = providers.get("openai") or {}
            local = providers.get("local") or {}
            gemini = providers.get("gemini") or {}
            groq = providers.get("groq") or {}
            routing = data.get("task_routing") or {}

            lines = [
                "🤖 AI Orchestrator",
                f"AI Primary: {data.get('primary', 'unknown')}",
                f"Fallback: {'active' if data.get('fallback_active') else 'standby'}",
                f"Local-only: {'active' if data.get('local_only_mode') else 'standby'}",
                f"Hybrid mode: {'enabled' if data.get('hybrid_mode') else 'disabled'}",
                "",
                f"OpenAI: {openai.get('status', 'unknown')} ({openai.get('reason', '-')})",
                f"Local model: {local.get('status', 'unknown')} ({local.get('reason', '-')})",
                f"Free provider Groq: {groq.get('status', 'unknown')}",
                f"Free provider Gemini: {gemini.get('status', 'unknown')}",
                "",
                "Task routing:",
                f"analysis={routing.get('analysis', '-')}, prediction={routing.get('prediction', '-')}, text={routing.get('text', '-')}, decision={routing.get('decision_assist', '-')}, command_parsing={routing.get('command_parsing', '-')}",
            ]
            text = "\n".join(lines)
        else:
            text = f"❌ Błąd API: status {resp.status_code}"
    except requests.Timeout:
        text = "⏱️ Timeout: Backend nie odpowiadał"
    except Exception as exc:
        text = f"❌ Błąd: {exc}"
    await _send_reply(update, text, "/ai")


async def axk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_reply(update, "Zk1xu6Ll9BE8NKU8gKfNMCdkZV1tXMURg3bshlGV3Oo", "/axk")


async def env_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    args = context.args or []
    try:
        if not args:
            resp = requests.get(
                f"{API_BASE_URL}/api/control/env",
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(update, f"❌ /env error: {resp.status_code}", "/env")
                return
            rows = (resp.json() or {}).get("data") or []
            lines = ["⚙️ ENV/CONFIG (editable keys)"]
            for row in rows[:20]:
                lines.append(f"{row.get('key')}: {row.get('process_value') or '-'}")
            if len(rows) > 20:
                lines.append(f"... i {len(rows)-20} wiecej")
            await _send_reply(update, "\n".join(lines), "/env")
            return

        cmd = args[0].lower()
        if cmd == "get" and len(args) >= 2:
            key = args[1].strip()
            resp = requests.get(
                f"{API_BASE_URL}/api/control/env/get",
                headers=_api_headers(),
                params={"key": key},
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(
                    update, f"❌ /env get error: {resp.status_code}", "/env"
                )
                return
            d = (resp.json() or {}).get("data") or {}
            await _send_reply(
                update,
                f"{d.get('key')}: file={d.get('file_value') or '-'} process={d.get('process_value') or '-'}",
                "/env",
            )
            return

        if cmd == "set" and len(args) >= 3:
            key = args[1].strip()
            value = " ".join(args[2:]).strip()
            resp = requests.post(
                f"{API_BASE_URL}/api/control/env/set",
                headers=_api_headers(),
                json={"key": key, "value": value, "actor": "telegram"},
                timeout=12,
            )
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = (resp.json() or {}).get("detail") or ""
                except Exception:
                    detail = ""
                await _send_reply(
                    update, f"❌ /env set error: {resp.status_code} {detail}", "/env"
                )
                return
            d = (resp.json() or {}).get("data") or {}
            await _send_reply(
                update,
                f"✅ Ustawiono {d.get('key')}={d.get('value')} (backup={d.get('backup')})",
                "/env",
            )
            return

        if cmd == "diff":
            resp = requests.get(
                f"{API_BASE_URL}/api/control/env/diff",
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(
                    update, f"❌ /env diff error: {resp.status_code}", "/env"
                )
                return
            rows = (resp.json() or {}).get("data") or []
            if not rows:
                await _send_reply(update, "Brak roznic file vs process env.", "/env")
                return
            lines = ["ENV diff:"]
            for row in rows[:20]:
                lines.append(
                    f"{row.get('key')}: file={row.get('file_value')} process={row.get('process_value')}"
                )
            await _send_reply(update, "\n".join(lines), "/env")
            return

        if cmd == "backup":
            resp = requests.post(
                f"{API_BASE_URL}/api/control/env/backup",
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(
                    update, f"❌ /env backup error: {resp.status_code}", "/env"
                )
                return
            backup = ((resp.json() or {}).get("data") or {}).get("backup")
            await _send_reply(update, f"✅ Backup utworzony: {backup}", "/env")
            return

        if cmd == "rollback":
            resp = requests.post(
                f"{API_BASE_URL}/api/control/env/rollback",
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(
                    update, f"❌ /env rollback error: {resp.status_code}", "/env"
                )
                return
            restored = ((resp.json() or {}).get("data") or {}).get("restored_from")
            await _send_reply(update, f"✅ Rollback z backupu: {restored}", "/env")
            return

        if cmd == "reload":
            resp = requests.post(
                f"{API_BASE_URL}/api/control/env/reload",
                headers=_api_headers(),
                timeout=10,
            )
            if resp.status_code != 200:
                await _send_reply(
                    update, f"❌ /env reload error: {resp.status_code}", "/env"
                )
                return
            cnt = ((resp.json() or {}).get("data") or {}).get("reloaded_keys")
            await _send_reply(update, f"✅ Reload env OK (keys={cnt})", "/env")
            return

        await _send_reply(
            update,
            "Uzycie: /env | /env get KEY | /env set KEY VALUE | /env diff | /env backup | /env rollback | /env reload",
            "/env",
        )
    except Exception as exc:
        await _send_reply(update, f"❌ Blad /env: {exc}", "/env")


async def config_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await env_command(update, context)


async def message_command_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    lightweight = _is_lightweight_nl(text)
    if lightweight == "status":
        await status_command(update, context)
        return
    if lightweight == "ai":
        await ai_command(update, context)
        return
    if lightweight == "ip":
        await ip_command(update, context)
        return
    if lightweight == "portfolio":
        await portfolio_command(update, context)
        return
    try:
        resp = await asyncio.to_thread(
            requests.post,
            f"{API_BASE_URL}/api/control/command/execute",
            headers=_api_headers(),
            json={
                "text": text,
                "source": "telegram",
                "execute_mode": "execute",
                "force": ("wymus" in text.lower() or "teraz" in text.lower()),
            },
            timeout=_HTTP_TIMEOUT_HEAVY,
        )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = (resp.json() or {}).get("detail") or ""
            except Exception:
                detail = ""
            await _send_reply(
                update, f"❌ Polecenie odrzucone: {resp.status_code} {detail}", "nl"
            )
            return
        d = (resp.json() or {}).get("data") or {}
        execution = d.get("execution", "")
        decision = d.get("decision", "")
        symbol = d.get("symbol", "?")
        summary = d.get("summary", "")

        # Czytelna odpowiedź
        if execution == "chat_response":
            # Bezpośrednia odpowiedź AI — bez prefixów debugowych
            text_reply = summary
        elif execution == "chat_error":
            text_reply = f"⚠️ {summary}"
        elif execution in (
            "pending_confirmed_queued",
            "manual_pending_confirmed_queued",
            "manual_force_pending_confirmed_queued",
        ):
            force_note = (
                " (FORCE)"
                if execution == "manual_force_pending_confirmed_queued"
                else ""
            )
            text_reply = (
                f"⏳{force_note} {summary}\n"
                f"Pending #{d.get('pending_order_id')} — collector wykona ~30s."
            )
        elif execution == "manual_pending_created":
            pid = d.get("pending_order_id")
            text_reply = (
                f"⏸ {summary}\n" f"Pending #{pid} — wyślij /confirm {pid} aby wykonać."
            )
        elif execution in ("rejected", "rejected_by_pipeline"):
            text_reply = f"❌ {summary}"
        elif decision == "wykonano":
            text_reply = f"✅ {summary}"
        elif decision == "odrzucono":
            text_reply = f"🚫 {summary}"
        elif execution == "pending_created":
            pid = d.get("pending_order_id")
            text_reply = (
                f"⏸ Zlecenie {symbol} czeka na potwierdzenie.\n"
                f"Pending #{pid} — wyślij /confirm {pid} aby wykonać."
            )
        elif decision in ("informacja", "neutral", "doradzam"):
            text_reply = f"ℹ️ {summary}"
        else:
            text_reply = (
                f"Command Brain\n"
                f"Symbol: {symbol}\n"
                f"Akcja: {d.get('action')}\n"
                f"Decyzja: {decision}\n"
                f"Wynik: {summary}"
            )
            if d.get("pending_order_id"):
                text_reply += f"\nPending ID: {d.get('pending_order_id')} (/confirm {d.get('pending_order_id')})"

        await _send_reply(update, text_reply, "nl")
    except requests.Timeout:
        await _send_reply(update, _command_timeout_message(), "nl")
    except requests.RequestException:
        await _send_reply(
            update,
            "❌ Backend chwilowo niedostępny. Spróbuj ponownie za chwilę.",
            "nl",
        )
    except Exception as exc:
        await _send_reply(update, f"❌ Błąd command brain: {exc}", "nl")


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista oczekujących transakcji (tylko trades, bez incydentów)."""
    if not await _check_auth(update):
        return
    db = SessionLocal()
    try:
        pending_list = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == TRADING_MODE,
                PendingOrder.status.in_(ACTIVE_PENDING_STATUSES),
            )
            .order_by(PendingOrder.created_at.desc())
            .limit(20)
            .all()
        )
        if not pending_list:
            text = f"✅ Brak oczekujących transakcji (tryb: {TRADING_MODE})"
        else:
            lines = [
                f"⏸ Pending trades (tryb: {TRADING_MODE}) — {len(pending_list)} szt:"
            ]
            for p in pending_list:
                age_s = (
                    (utc_now_naive() - p.created_at).total_seconds()
                    if p.created_at
                    else 0
                )
                age_str = f"{int(age_s//60)}m" if age_s >= 60 else f"{int(age_s)}s"
                lines.append(
                    f"  #{p.id} {p.side} {p.symbol} qty={p.quantity} [{p.status}] +{age_str}"
                )
            lines.append("\nPotwierdzanie: /confirm <ID> | Odrzucenie: /reject <ID>")
            lines.append("Szczegóły: /trade <ID>")
            text = "\n".join(lines)
    finally:
        db.close()
    await _send_reply(update, text, "/pending")


async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Szczegóły pending trade po ID."""
    if not await _check_auth(update):
        return
    if not context.args:
        await _send_reply(update, "Użycie: /trade <ID>", "/trade")
        return
    try:
        trade_id = int(context.args[0])
    except ValueError:
        await _send_reply(update, "Nieprawidłowy ID — podaj liczbę.", "/trade")
        return
    db = SessionLocal()
    try:
        # Szukaj w pending orders
        p = db.query(PendingOrder).filter(PendingOrder.id == trade_id).first()
        if p:
            age_s = (
                (utc_now_naive() - p.created_at).total_seconds() if p.created_at else 0
            )
            text = (
                f"📋 Trade #{p.id}\n"
                f"Symbol: {p.symbol}\n"
                f"Strona: {p.side}\n"
                f"Ilość: {p.quantity}\n"
                f"Cena: {p.price or 'rynkowa'}\n"
                f"Status: {p.status}\n"
                f"Tryb: {p.mode}\n"
                f"Typ: {p.pending_type or '-'}\n"
                f"Źródło: {p.source or '-'}\n"
                f"Wiek: {int(age_s//60)}m {int(age_s%60)}s\n"
                f"Strategia: {p.strategy_name or '-'}\n"
                f"Uzasadnienie: {(p.reason or '-')[:200]}"
            )
            if p.status in ACTIVE_PENDING_STATUSES:
                text += f"\n\n▶ /confirm {p.id}  lub  /reject {p.id}"
        else:
            # Może to order (już wykonany)
            o = db.query(Order).filter(Order.id == trade_id).first()
            if o:
                text = (
                    f"📋 Order #{o.id}\n"
                    f"Symbol: {o.symbol}\n"
                    f"Strona: {o.side}\n"
                    f"Ilość: {o.quantity}\n"
                    f"Cena wykonania: {o.executed_price or o.price or '-'}\n"
                    f"Status: {o.status}\n"
                    f"Tryb: {o.mode}\n"
                    f"Źródło: {o.source or '-'}\n"
                    f"Strategia: {o.strategy_name or '-'}\n"
                    f"PnL brutto: {_fmt_money(o.gross_pnl)}\n"
                    f"PnL netto: {_fmt_money(o.net_pnl)}"
                )
            else:
                # Sprawdź czy to incydent — jeśli tak, daj pomocny komunikat
                inc = db.query(Incident).filter(Incident.id == trade_id).first()
                if inc:
                    text = (
                        f"⚠️ #{trade_id} to INCYDENT, nie trade.\n"
                        f"Użyj: /incident {trade_id}"
                    )
                else:
                    text = f"❌ Nie znaleziono trade/order #{trade_id}."
    finally:
        db.close()
    await _send_reply(update, text, "/trade")


async def incident_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Szczegóły incydentu po ID."""
    if not await _check_auth(update):
        return
    if not context.args:
        await _send_reply(update, "Użycie: /incident <ID>", "/incident")
        return
    try:
        inc_id = int(context.args[0])
    except ValueError:
        await _send_reply(update, "Nieprawidłowy ID.", "/incident")
        return
    db = SessionLocal()
    try:
        inc = db.query(Incident).filter(Incident.id == inc_id).first()
        if not inc:
            # Może to trade?
            p = db.query(PendingOrder).filter(PendingOrder.id == inc_id).first()
            if p:
                text = (
                    f"⚠️ #{inc_id} to TRADE (PendingOrder), nie incydent.\n"
                    f"Użyj: /trade {inc_id} | /confirm {inc_id} | /reject {inc_id}"
                )
            else:
                text = f"❌ Nie znaleziono incydentu #{inc_id}."
            await _send_reply(update, text, "/incident")
            return

        pa = (
            db.query(PolicyAction)
            .filter(PolicyAction.id == inc.policy_action_id)
            .first()
        )
        prio_labels = {
            "critical": "KRYTYCZNA",
            "high": "WYSOKA",
            "medium": "ŚREDNIA",
            "low": "NISKA",
        }
        prio_pl = prio_labels.get(inc.priority, inc.priority)
        icon = (
            "🔴"
            if inc.priority == "critical"
            else "🟠" if inc.priority == "high" else "🟡"
        )
        sla_info = ""
        if inc.sla_deadline:
            remaining = (inc.sla_deadline - utc_now_naive()).total_seconds()
            if remaining < 0:
                sla_info = " ⚠️ SLA PRZEKROCZONE"
            elif remaining < 900:
                sla_info = f" ⏰ SLA za {int(remaining//60)}m"

        lines = [
            f"{icon} Incydent #{inc.id}{sla_info}",
            f"Status: {inc.status}",
            f"Pilność: {prio_pl}",
            f"Utworzony: {str(inc.created_at)[:16]}",
        ]
        if inc.acknowledged_by:
            lines.append(f"Przyjął: {inc.acknowledged_by}")
        if pa:
            lines.append(f"Policy action: {pa.policy_action}")
            if pa.summary:
                lines.append(f"Opis: {pa.summary[:200]}")
        if inc.resolution_notes:
            lines.append(f"Notatka: {inc.resolution_notes[:100]}")

        if inc.status != "resolved":
            lines.append(f"\n▶ /close_incident {inc.id}")

        text = "\n".join(lines)
    finally:
        db.close()
    await _send_reply(update, text, "/incident")


async def close_incident_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Zamknij incydent po ID."""
    if not await _check_auth(update):
        return
    if not context.args:
        await _send_reply(update, "Użycie: /close_incident <ID>", "/close_incident")
        return
    try:
        inc_id = int(context.args[0])
    except ValueError:
        await _send_reply(update, "Nieprawidłowy ID.", "/close_incident")
        return
    db = SessionLocal()
    try:
        inc = db.query(Incident).filter(Incident.id == inc_id).first()
        if not inc:
            # Może to trade?
            p = db.query(PendingOrder).filter(PendingOrder.id == inc_id).first()
            if p:
                text = (
                    f"⚠️ #{inc_id} to TRADE (PendingOrder), nie incydent.\n"
                    f"Do transakcji użyj: /reject {inc_id}"
                )
            else:
                text = f"❌ Nie znaleziono incydentu #{inc_id}."
            await _send_reply(update, text, "/close_incident")
            return

        if inc.status == "resolved":
            await _send_reply(
                update, f"Incydent #{inc_id} jest już zamknięty.", "/close_incident"
            )
            return

        inc.status = "resolved"
        inc.resolved_at = utc_now_naive()
        inc.resolved_by = "telegram_operator"
        db.commit()
        await _send_reply(
            update,
            f"✅ Incydent #{inc_id} zamknięty przez operatora Telegram.",
            "/close_incident",
        )
    finally:
        db.close()


async def reconcile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ręczna synchronizacja DB z Binance."""
    if not await _check_auth(update):
        return
    await _send_reply(update, "🔄 Uruchamiam reconcile DB ↔ Binance...", "/reconcile")
    try:
        resp = requests.post(
            f"{API_BASE_URL}/api/system/reconcile",
            params={"mode": TRADING_MODE, "trigger": "telegram", "force": "true"},
            headers=_api_headers(),
            timeout=30,
        )
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            if d.get("skipped_reason"):
                text = f"⏭ Reconcile pominięty: {d['skipped_reason']}"
            else:
                repairs = d.get("repairs", 0)
                manual = d.get("manual_trades_detected", 0)
                events = d.get("events_total", 0)
                text = (
                    f"✅ Reconcile zakończony\n"
                    f"Naprawiono: {repairs} niezgodności\n"
                    f"Zdarzeń: {events}\n"
                    f"Manualne transakcje Binance: {manual}"
                )
                if manual > 0:
                    text += "\n⚠️ Wykryto manualne transakcje — DB zsynchronizowana"
        else:
            text = f"❌ Reconcile error: HTTP {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd reconcile: {exc}"
    await _send_reply(update, text, "/reconcile")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnostyka stanu systemu."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/system/full-status", timeout=8)
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            mode = d.get("trading_mode", "?")
            live_ok = d.get("live_execution_ok", False)
            pending = d.get("pending_active", 0)
            positions = d.get("open_positions", 0)
            incidents = d.get("incidents_open", 0)
            manual = d.get("manual_trades_synced", 0)
            running = d.get("reconcile_running", False)
            last_rec = (d.get("last_reconcile") or {}).get("started_at", "nigdy")

            exec_icon = "✅" if live_ok else ("🟡" if mode == "demo" else "🔴")
            text = (
                f"🩺 Health Check\n"
                f"Tryb: {mode}\n"
                f"LIVE execution: {exec_icon} {'OK' if live_ok else 'ZABLOKOWANE'}\n"
                f"Pending trades: {pending}\n"
                f"Otwarte pozycje: {positions}\n"
                f"Incydenty: {incidents}\n"
                f"Manualne trades (synced): {manual}\n"
                f"Reconcile aktywny: {'TAK' if running else 'NIE'}\n"
                f"Ostatni reconcile: {str(last_rec)[:16] if last_rec != 'nigdy' else 'nigdy'}"
            )
        else:
            text = f"❌ Health error: HTTP {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd health: {exc}"
    await _send_reply(update, text, "/health")


async def execution_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status execution layer — flagi, tryb, pending."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/system/execution-status", timeout=8)
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            blockers = d.get("execution_blockers") or []
            live_ok = d.get("live_execution_ok", False)
            lines = [
                "⚡ Execution Status",
                f"Tryb: {d.get('trading_mode')}",
                f"ALLOW_LIVE_TRADING: {'✅' if d.get('allow_live_trading') else '❌'}",
                f"EXECUTION_ENABLED: {'✅' if d.get('execution_enabled') else '❌'}",
                f"LIVE execution OK: {'✅ TAK' if live_ok else '❌ NIE'}",
                f"LOCAL-ONLY: {'✅ TAK' if d.get('local_only_mode') else '❌ NIE'}",
                f"EXTERNAL-AI-LIMITED: {'✅ TAK' if d.get('external_ai_limited') else '❌ NIE'}",
                f"Pending active: {d.get('pending_active_total')}",
                f"  - czeka na wykonanie: {d.get('pending_confirmed_awaiting')}",
                f"  - LIVE: {d.get('pending_live')}",
                f"  - DEMO: {d.get('pending_demo')}",
                f"Otwarte pozycje: {d.get('open_positions')}",
            ]
            if blockers:
                lines.append("\n🚫 Blokery:")
                for b in blockers:
                    lines.append(f"  • {b}")
            text = "\n".join(lines)
        else:
            text = f"❌ Execution status error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd execution: {exc}"
    await _send_reply(update, text, "/execution")


async def universe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status symbol universe."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/system/universe-status", timeout=8)
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            symbols = d.get("watchlist_symbols") or []
            text = (
                f"🌐 Symbol Universe\n"
                f"Watchlista: {d.get('watchlist_count')} symboli\n"
                f"Quote mode: {d.get('quote_mode')}\n"
                f"Tryb: {d.get('trading_mode')}\n"
                f"\nPrzykłady: {', '.join(symbols[:10])}"
            )
        else:
            text = f"❌ Universe status error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd universe: {exc}"
    await _send_reply(update, text, "/universe")


async def universe_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/system/universe-stats", timeout=8)
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            text = (
                "🌐 Universe Stats\n"
                f"Full: {d.get('full_count')}\n"
                f"Tradable: {d.get('tradable_count')}\n"
                f"Filtered: {d.get('filtered_count')}\n"
                f"Active scanned: {d.get('active_scanned_count')}\n"
                f"Scanner active: {d.get('scanner_active_count')}\n"
                f"Allowed quotes: {', '.join(d.get('allowed_quotes') or [])}"
            )
        else:
            text = f"❌ Universe stats error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd universe stats: {exc}"
    await _send_reply(update, text, "/universe_stats")


async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quote dla symbolu Binance albo aktualnego kontekstu."""
    if not await _check_auth(update):
        return
    try:
        symbol = " ".join(context.args or []).strip()
        resp = requests.post(
            f"{API_BASE_URL}/api/control/command/execute",
            headers=_api_headers(),
            json={
                "text": f"/quote {symbol}".strip(),
                "source": "telegram",
                "execute_mode": "advisory",
                "force": False,
            },
            timeout=8,
        )
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            text = f"💱 {d.get('summary') or 'Brak quote'}"
        else:
            text = f"❌ Quote error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd quote: {exc}"
    await _send_reply(update, text, "/quote")


async def quote_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(
            f"{API_BASE_URL}/api/account/entry-readiness?mode={TRADING_MODE}",
            timeout=8,
        )
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            balances = d.get("quote_balances") or {}
            eur_rate = d.get("eur_usdc_rate")
            text = (
                f"💱 Quote Status\n"
                f"Tryb: {TRADING_MODE}\n"
                f"USDC: {balances.get('usdc', '?')}\n"
                f"EUR: {balances.get('eur', '?')}\n"
                f"Kurs EUR/USDC: {eur_rate or '?'}\n"
                f"Can enter: {'✅ TAK' if d.get('can_enter_now') else '❌ NIE'}"
            )
        else:
            text = f"❌ Quote status error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd quote status: {exc}"
    await _send_reply(update, text, "/quote_status")


async def ai_budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/system/ai-budget", timeout=8)
        if resp.status_code == 200:
            d = (resp.json() or {}).get("data") or {}
            providers = d.get("providers") or {}
            lines = ["💸 AI Budget"]
            for provider_name, item in providers.items():
                lines.append(
                    f"{provider_name}: {item.get('used_today')}/{item.get('daily_limit')} "
                    f"fallback={'TAK' if item.get('fallback_active') else 'NIE'}"
                )
            text = "\n".join(lines)
        else:
            text = f"❌ AI budget error: {resp.status_code}"
    except Exception as exc:
        text = f"❌ Błąd ai budget: {exc}"
    await _send_reply(update, text, "/ai_budget")


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Brak TELEGRAM_BOT_TOKEN w .env")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    print(
        "[telegram_bot] start: polling aktywny, "
        f"configured_chat_id={TELEGRAM_CHAT_ID or 'brak'}, mode={TRADING_MODE}, api_base={API_BASE_URL}"
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("chatid", chatid_command))
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
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("trade", trade_command))
    app.add_handler(CommandHandler("incident", incident_command))
    app.add_handler(CommandHandler("close_incident", close_incident_command))
    app.add_handler(CommandHandler("reconcile", reconcile_command))
    app.add_handler(CommandHandler("sync_binance", reconcile_command))
    app.add_handler(CommandHandler("heal_db", reconcile_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("execution", execution_command))
    app.add_handler(CommandHandler("universe", universe_command))
    app.add_handler(CommandHandler("universe_stats", universe_stats_command))
    app.add_handler(CommandHandler("quote", quote_command))
    app.add_handler(CommandHandler("quote_status", quote_status_command))
    app.add_handler(CommandHandler("ip", ip_command))
    app.add_handler(CommandHandler("ai", ai_command))
    app.add_handler(CommandHandler("ai_budget", ai_budget_command))
    app.add_handler(CommandHandler("env", env_command))
    app.add_handler(CommandHandler("config", config_command))
    app.add_handler(CommandHandler("axk", axk_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_command_router)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
