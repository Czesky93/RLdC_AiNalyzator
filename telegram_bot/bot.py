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
from telegram.ext import Application, CommandHandler, ContextTypes

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
        "RLdC Trading Bot\n"
        "Dostępne komendy:\n"
        "/status /risk /portfolio /orders /positions /lastsignal /blog /logs /report\n"
        "Potwierdzanie transakcji:\n"
        "/confirm <ID>  /reject <ID>\n"
        "Governance:\n"
        "/governance /freeze /incidents\n"
        "Diagnostyka:\n"
        "/chatid /ip /ai"
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
    db = SessionLocal()
    try:
        last_signal = db.query(Signal).order_by(Signal.timestamp.desc()).first()
        last_signal_text = "brak" if not last_signal else f"{last_signal.symbol} {last_signal.signal_type}"
        text = (
            "✅ Status systemu\n"
            f"Tryb: {TRADING_MODE}\n"
            f"Ostatni sygnał: {last_signal_text}\n"
            f"Czas: {utc_now_naive().isoformat()}"
        )
    finally:
        db.close()

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
            text = f"⚠️ Nie udało się zatrzymać (status {resp.status_code}). Sprawdź API."
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
    db = SessionLocal()
    try:
        positions = db.query(Position).filter(Position.mode == TRADING_MODE).all()
        if not positions:
            text = "Brak otwartych pozycji."
        else:
            lines = ["💼 Portfolio:"]
            for p in positions:
                lines.append(f"{p.symbol} {p.side} qty={p.quantity} PnL={p.unrealized_pnl}")
            text = "\n".join(lines)
    finally:
        db.close()

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
                lines.append(f"{l.timestamp.strftime('%H:%M:%S')} {l.level} {l.module}: {l.message}")
            text = "\n".join(lines)
    finally:
        db.close()

    await _send_reply(update, text, "/logs")


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


async def ip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wyświetla IP publiczne bota (pobrane z Cloudflare DNS API)."""
    if not await _check_auth(update):
        return
    try:
        # Używamy Cloudflare DNS API do pobrania IP publicznego
        resp = requests.get("https://1.1.1.1/dns-query?name=whoami.cloudflare&type=TXT", 
                           headers={"accept": "application/dns-json"},
                           timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            ip = None
            if "Answer" in data:
                for answer in data["Answer"]:
                    if answer.get("type") == 16:  # TXT record
                        txt = answer.get("data", "")
                        if txt.startswith('"') and txt.endswith('"'):
                            ip = txt[1:-1]
                        else:
                            ip = txt
                        break
            if ip:
                text = f"🌍 IP publiczne bota:\n{ip}"
            else:
                text = "⚠️ Nie udało się wyodrębnić IP z odpowiedzi DNS"
        else:
            text = "❌ Błąd Cloudflare DNS API"
    except requests.Timeout:
        text = "⏱️ Timeout: Cloudflare nie odpowiadał w ciągu 5 sekund"
    except Exception as exc:
        text = f"❌ Błąd pobrania IP: {exc}"
    await _send_reply(update, text, "/ip")


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wyświetla status systemu AI (OpenAI status i AI provider)."""
    if not await _check_auth(update):
        return
    try:
        resp = requests.get(f"{API_BASE_URL}/api/account/openai-status", timeout=10)
        if resp.status_code == 200:
            result = resp.json()
            data = result.get("data", {})
            status = data.get("status", "unknown")
            msg = data.get("message", "")
            code = data.get("code")
            model = data.get("model", "unknown")
            key_fp = data.get("key_fingerprint", "none")
            
            if status == "ok":
                icon = "✅"
                text = f"{icon} AI System: OK\n"
                text += f"Model: {model}\n"
                text += f"Status: {msg}\n"
                text += f"Key fingerprint: {key_fp}"
            elif status == "error":
                icon = "⚠️"
                text = f"{icon} AI System: ERROR\n"
                text += f"Code: {code}\n"
                text += f"Message: {msg}"
            elif status == "missing":
                icon = "❌"
                text = f"{icon} AI System: MISSING\n"
                text += f"Brak OPENAI_API_KEY w .env"
            else:
                text = f"❓ AI System: {status}\n{msg}"
        else:
            text = f"❌ Błąd API: status {resp.status_code}"
    except requests.Timeout:
        text = "⏱️ Timeout: Backend nie odpowiadał"
    except Exception as exc:
        text = f"❌ Błąd: {exc}"
    await _send_reply(update, text, "/ai")


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
    app.add_handler(CommandHandler("ip", ip_command))
    app.add_handler(CommandHandler("ai", ai_command))

    app.run_polling()


if __name__ == "__main__":
    main()
