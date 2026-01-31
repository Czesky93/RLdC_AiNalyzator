import json
import logging
import os
from typing import Any, Dict, List

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = os.getenv("API_URL", "http://backend:8000")
MARKET_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("MARKET_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if s.strip()
]

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("RLdC-Telegram")


def api_get(path: str) -> Dict[str, Any]:
    response = requests.get(f"{API_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def format_list(items: List[Dict[str, Any]], keys: List[str]) -> str:
    lines = []
    for item in items:
        line = " | ".join(f"{k}: {item.get(k)}" for k in keys)
        lines.append(line)
    return "\n".join(lines) if lines else "Brak danych."


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Witaj! Bot RLdC AiNalyzer jest aktywny. /status aby sprawdzić system."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/health")
        await update.message.reply_text(f"Status API: {data.get('status', 'unknown')}")
    except Exception as exc:
        await update.message.reply_text(f"Błąd statusu: {exc}")


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Profil ryzyka: domyślny. Ustawienia rozbuduj w panelu administracyjnym."
    )


async def cmd_top10(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        symbols = MARKET_SYMBOLS[:10]
        data = api_get("/api/market/summary")
        items = data.get("dane", [])
        items = [i for i in items if i.get("symbol") in symbols]
        await update.message.reply_text(
            format_list(items, ["symbol", "last_price", "change_percent"])
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd top10: {exc}")


async def cmd_top5(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        symbols = MARKET_SYMBOLS[:5]
        data = api_get("/api/market/summary")
        items = data.get("dane", [])
        items = [i for i in items if i.get("symbol") in symbols]
        await update.message.reply_text(
            format_list(items, ["symbol", "last_price", "change_percent"])
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd top5: {exc}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/live/account")
        balances = data.get("balances", [])
        await update.message.reply_text(
            format_list(balances, ["asset", "free", "locked"])
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd portfolio: {exc}")


async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/live/orders")
        orders = data.get("orders", [])
        await update.message.reply_text(
            format_list(orders, ["symbol", "side", "price", "origQty", "status"])
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd zleceń: {exc}")


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/live/positions")
        positions = data.get("positions", [])
        await update.message.reply_text(
            format_list(positions, ["symbol", "positionAmt", "entryPrice"])
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd pozycji: {exc}")


async def cmd_lastsignal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/analysis")
        latest = data[0] if data else None
        await update.message.reply_text(
            json.dumps(latest, ensure_ascii=False, indent=2)
            if latest
            else "Brak sygnałów."
        )
    except Exception as exc:
        await update.message.reply_text(f"Błąd sygnału: {exc}")


async def cmd_blog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/blog?status=published")
        posts = data[:5]
        msg = (
            "\n".join(f"{p.get('title')} ({p.get('published_at')})" for p in posts)
            or "Brak wpisów."
        )
        await update.message.reply_text(msg)
    except Exception as exc:
        await update.message.reply_text(f"Błąd bloga: {exc}")


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        data = api_get("/api/logs?limit=10")
        msg = (
            "\n".join(
                f"{i.get('timestamp')} {i.get('level')}: {i.get('message')}"
                for i in data
            )
            or "Brak logów."
        )
        await update.message.reply_text(msg)
    except Exception as exc:
        await update.message.reply_text(f"Błąd logów: {exc}")


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot RLdC AiNalyzer pozostaje w trybie nasłuchiwania. Użyj /status."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Brak TELEGRAM_BOT_TOKEN")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("top10", cmd_top10))
    app.add_handler(CommandHandler("top5", cmd_top5))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("lastsignal", cmd_lastsignal))
    app.add_handler(CommandHandler("blog", cmd_blog))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("stop", cmd_stop))

    app.run_polling()


if __name__ == "__main__":
    main()
