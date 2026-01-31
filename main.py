import csv
import io
import logging
import os
import sqlite3
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from binance.client import Client
    from binance.enums import (
        KLINE_INTERVAL_1DAY,
        KLINE_INTERVAL_1HOUR,
        KLINE_INTERVAL_1MINUTE,
        KLINE_INTERVAL_4HOUR,
        KLINE_INTERVAL_5MINUTE,
        KLINE_INTERVAL_15MINUTE,
    )
except Exception:  # pragma: no cover - fallback when package missing in tests
    Client = None
    KLINE_INTERVAL_1MINUTE = "1m"
    KLINE_INTERVAL_5MINUTE = "5m"
    KLINE_INTERVAL_15MINUTE = "15m"
    KLINE_INTERVAL_1HOUR = "1h"
    KLINE_INTERVAL_4HOUR = "4h"
    KLINE_INTERVAL_1DAY = "1d"

APP_NAME = "RLdC AiNalyzer"
APP_VERSION = "0.7-beta"

DB_PATH = os.getenv("DB_PATH", "/data/trading_history.db")
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
BINANCE_FUTURES = os.getenv("BINANCE_FUTURES", "false").lower() == "true"
PERSIST_MARKET_DATA = os.getenv("PERSIST_MARKET_DATA", "true").lower() == "true"
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "false").lower() == "true"
MARKET_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("MARKET_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    if s.strip()
]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(APP_NAME)

log_buffer: deque = deque(maxlen=500)


def log_event(
    level: str, message: str, details: Optional[Dict[str, Any]] = None
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        "details": details or {},
    }
    log_buffer.appendleft(entry)
    getattr(logger, level.lower(), logger.info)(f"{message} | {details}")


def with_retry(func, description: str, retries: int = 3, backoff: float = 1.0):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:  # pragma: no cover - log retry path
            last_error = exc
            log_event(
                "warning",
                f"Ponowienie: {description}",
                {"proba": attempt, "error": str(exc)},
            )
            time.sleep(backoff * attempt)
    log_event(
        "error",
        f"Nieudane połączenie: {description}",
        {"error": str(last_error)},
    )
    raise last_error


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            indicator TEXT NOT NULL,
            value REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS market_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            last_price REAL NOT NULL,
            change_percent REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS klines_1h (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS demo_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            published_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def get_binance_client() -> Optional[Client]:
    if OFFLINE_MODE:
        return None
    if Client is None:
        return None
    return Client(api_key=BINANCE_API_KEY, api_secret=BINANCE_API_SECRET)


def ensure_private_access() -> None:
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise HTTPException(
            status_code=503, detail="Brak konfiguracji Binance dla danych prywatnych."
        )


def map_interval(tf: str) -> str:
    mapping = {
        "1m": KLINE_INTERVAL_1MINUTE,
        "5m": KLINE_INTERVAL_5MINUTE,
        "15m": KLINE_INTERVAL_15MINUTE,
        "1h": KLINE_INTERVAL_1HOUR,
        "4h": KLINE_INTERVAL_4HOUR,
        "1d": KLINE_INTERVAL_1DAY,
    }
    if tf not in mapping:
        raise HTTPException(status_code=400, detail="Nieobsługiwany interwał czasu.")
    return mapping[tf]


class TradeIn(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float


class AnalysisIn(BaseModel):
    symbol: str
    indicator: str
    value: float


class DemoOrderIn(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    status: str = Field(default="NEW")


class BlogPostIn(BaseModel):
    title: str
    content: str


class TelegramAlertIn(BaseModel):
    message: str


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    init_db()
    log_event("info", "Aplikacja uruchomiona", {"version": APP_VERSION})
    yield


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = (time.time() - start_time) * 1000
    log_event(
        "info",
        "Żądanie HTTP",
        {
            "path": request.url.path,
            "status": response.status_code,
            "ms": round(duration, 2),
        },
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_event("error", "Błąd aplikacji", {"path": request.url.path, "error": str(exc)})
    return JSONResponse(status_code=500, content={"error": "Wewnętrzny błąd serwera."})


@app.get("/")
def root() -> Dict[str, Any]:
    return {"nazwa": APP_NAME, "wersja": APP_VERSION}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/logs")
def api_logs(limit: int = Query(100, ge=1, le=500)) -> List[Dict[str, Any]]:
    return list(log_buffer)[:limit]


@app.get("/api/trades")
def list_trades() -> List[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/trades")
def create_trade(payload: TradeIn) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO trades(symbol, side, qty, price, timestamp) VALUES (?,?,?,?,?)",
        (
            payload.symbol.upper(),
            payload.side.upper(),
            payload.qty,
            payload.price,
            timestamp,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "timestamp": timestamp}


@app.get("/api/analysis")
def list_analysis() -> List[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM analysis ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/analysis")
def create_analysis(payload: AnalysisIn) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO analysis(symbol, indicator, value, timestamp) VALUES (?,?,?,?)",
        (payload.symbol.upper(), payload.indicator, payload.value, timestamp),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "timestamp": timestamp}


@app.get("/api/summary")
def api_summary() -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    trades = cur.execute("SELECT COUNT(*) AS cnt FROM trades").fetchone()[0]
    analysis = cur.execute("SELECT COUNT(*) AS cnt FROM analysis").fetchone()[0]
    last_trade = cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 1").fetchone()
    last_analysis = cur.execute(
        "SELECT * FROM analysis ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "trades": trades,
        "analysis": analysis,
        "ostatni_trade": dict(last_trade) if last_trade else None,
        "ostatnia_analiza": dict(last_analysis) if last_analysis else None,
    }


def fetch_market_summary(symbol: str) -> Dict[str, Any]:
    if OFFLINE_MODE:
        return {
            "symbol": symbol,
            "last_price": 42000.0,
            "change_percent": 1.23,
            "volume": 1234.0,
            "quote_volume": 4567.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    client = get_binance_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Brak klienta Binance.")
    ticker = with_retry(
        lambda: client.get_ticker(symbol=symbol), "pobranie market summary"
    )
    summary = {
        "symbol": ticker["symbol"],
        "last_price": float(ticker["lastPrice"]),
        "change_percent": float(ticker["priceChangePercent"]),
        "volume": float(ticker["volume"]),
        "quote_volume": float(ticker["quoteVolume"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if PERSIST_MARKET_DATA:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO market_summary(symbol, last_price, change_percent, volume, quote_volume, timestamp) VALUES (?,?,?,?,?,?)",
            (
                summary["symbol"],
                summary["last_price"],
                summary["change_percent"],
                summary["volume"],
                summary["quote_volume"],
                summary["timestamp"],
            ),
        )
        conn.commit()
        conn.close()
    return summary


@app.get("/api/market/summary")
def api_market_summary(symbol: Optional[str] = None) -> Dict[str, Any]:
    symbols = [symbol.upper()] if symbol else MARKET_SYMBOLS
    data = [fetch_market_summary(s) for s in symbols]
    return {"dane": data, "liczba": len(data)}


@app.get("/api/market/kline")
def api_market_kline(
    symbol: str = Query(...),
    tf: str = Query("1h"),
    limit: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    symbol = symbol.upper()
    interval = map_interval(tf)
    if OFFLINE_MODE:
        fake = [
            {"open_time": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0}
        ]
        return {"symbol": symbol, "tf": tf, "klines": fake}
    client = get_binance_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Brak klienta Binance.")
    klines = with_retry(
        lambda: client.get_klines(symbol=symbol, interval=interval, limit=limit),
        "pobranie kline",
    )
    data = []
    for k in klines:
        item = {
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
        }
        data.append(item)
    if PERSIST_MARKET_DATA and tf == "1h":
        conn = get_db()
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO klines_1h(symbol, open_time, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    symbol,
                    d["open_time"],
                    d["open"],
                    d["high"],
                    d["low"],
                    d["close"],
                    d["volume"],
                )
                for d in data
            ],
        )
        conn.commit()
        conn.close()
    return {"symbol": symbol, "tf": tf, "klines": data}


@app.get("/api/market/summary/history")
def api_market_summary_history(
    symbol: str = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM market_summary WHERE symbol = ? ORDER BY id DESC LIMIT ?",
        (symbol.upper(), limit),
    ).fetchall()
    conn.close()
    return {"symbol": symbol.upper(), "historia": [dict(r) for r in rows]}


@app.get("/api/market/kline/history")
def api_market_kline_history(
    symbol: str = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM klines_1h WHERE symbol = ? ORDER BY id DESC LIMIT ?",
        (symbol.upper(), limit),
    ).fetchall()
    conn.close()
    return {"symbol": symbol.upper(), "tf": "1h", "historia": [dict(r) for r in rows]}


@app.get("/api/live/account")
def api_live_account() -> Dict[str, Any]:
    ensure_private_access()
    client = get_binance_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Brak klienta Binance.")
    try:
        account = with_retry(lambda: client.get_account(), "konto Binance")
        balances = [
            b
            for b in account.get("balances", [])
            if float(b.get("free", 0)) > 0 or float(b.get("locked", 0)) > 0
        ]
        return {"balances": balances, "updateTime": account.get("updateTime")}
    except Exception as exc:
        log_event("error", "Błąd pobierania konta Binance", {"error": str(exc)})
        raise HTTPException(
            status_code=502, detail="Nie udało się pobrać konta Binance."
        )


@app.get("/api/live/orders")
def api_live_orders(symbol: Optional[str] = None) -> Dict[str, Any]:
    ensure_private_access()
    client = get_binance_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Brak klienta Binance.")
    try:
        orders = with_retry(
            lambda: (
                client.get_open_orders(symbol=symbol.upper())
                if symbol
                else client.get_open_orders()
            ),
            "zlecenia Binance",
        )
        return {"orders": orders, "liczba": len(orders)}
    except Exception as exc:
        log_event("error", "Błąd pobierania zleceń Binance", {"error": str(exc)})
        raise HTTPException(
            status_code=502, detail="Nie udało się pobrać zleceń Binance."
        )


@app.get("/api/live/positions")
def api_live_positions() -> Dict[str, Any]:
    ensure_private_access()
    client = get_binance_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Brak klienta Binance.")
    try:
        if BINANCE_FUTURES:
            positions = with_retry(
                lambda: client.futures_position_information(),
                "pozycje futures",
            )
            positions = [p for p in positions if float(p.get("positionAmt", 0)) != 0]
            return {"positions": positions, "typ": "futures"}
        account = with_retry(lambda: client.get_account(), "pozycje spot")
        balances = [
            b
            for b in account.get("balances", [])
            if float(b.get("free", 0)) > 0 or float(b.get("locked", 0)) > 0
        ]
        return {"positions": balances, "typ": "spot"}
    except Exception as exc:
        log_event("error", "Błąd pobierania pozycji Binance", {"error": str(exc)})
        raise HTTPException(
            status_code=502, detail="Nie udało się pobrać pozycji Binance."
        )


@app.get("/api/demo/summary")
def api_demo_summary() -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0]
    filled = cur.execute(
        "SELECT COUNT(*) FROM demo_orders WHERE status = 'FILLED'"
    ).fetchone()[0]
    notional = (
        cur.execute("SELECT SUM(qty * price) FROM demo_orders").fetchone()[0] or 0
    )
    conn.close()
    return {"liczba_zlecen": total, "wypelnione": filled, "wartosc": round(notional, 4)}


@app.get("/api/demo/orders")
def api_demo_orders() -> List[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM demo_orders ORDER BY id DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/demo/orders")
def api_demo_order_create(payload: DemoOrderIn) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO demo_orders(symbol, side, qty, price, status, created_at) VALUES (?,?,?,?,?,?)",
        (
            payload.symbol.upper(),
            payload.side.upper(),
            payload.qty,
            payload.price,
            payload.status.upper(),
            created_at,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "created_at": created_at}


@app.get("/api/demo/orders/export")
def api_demo_orders_export() -> StreamingResponse:
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM demo_orders ORDER BY id DESC").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "symbol", "side", "qty", "price", "status", "created_at"])
    for row in rows:
        writer.writerow(
            [
                row["id"],
                row["symbol"],
                row["side"],
                row["qty"],
                row["price"],
                row["status"],
                row["created_at"],
            ]
        )
    output.seek(0)
    headers = {"Content-Disposition": "attachment; filename=demo_orders.csv"}
    return StreamingResponse(output, media_type="text/csv", headers=headers)


@app.get("/api/blog")
def api_blog_list(status: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db()
    cur = conn.cursor()
    if status:
        rows = cur.execute(
            "SELECT * FROM blog_posts WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()
    else:
        rows = cur.execute("SELECT * FROM blog_posts ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/blog")
def api_blog_create(payload: BlogPostIn) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    created_at = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO blog_posts(title, content, status, created_at) VALUES (?,?,?,?)",
        (payload.title, payload.content, "draft", created_at),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "created_at": created_at}


@app.put("/api/blog/{post_id}")
def api_blog_update(post_id: int, payload: BlogPostIn) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE blog_posts SET title = ?, content = ? WHERE id = ?",
        (payload.title, payload.content, post_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.put("/api/blog/{post_id}/publish")
def api_blog_publish(post_id: int) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    published_at = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "UPDATE blog_posts SET status = ?, published_at = ? WHERE id = ?",
        ("published", published_at, post_id),
    )
    conn.commit()
    conn.close()
    return {"status": "ok", "published_at": published_at}


@app.delete("/api/blog/{post_id}")
def api_blog_delete(post_id: int) -> Dict[str, Any]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.post("/api/alerts/telegram")
def api_alerts_telegram(
    payload: Optional[TelegramAlertIn] = Body(None),
    message: Optional[str] = Query(None),
) -> Dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=503, detail="Brak konfiguracji Telegram.")
    final_message = payload.message if payload else message
    if not final_message:
        raise HTTPException(status_code=400, detail="Brak treści wiadomości.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": final_message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return {"status": "ok"}
    except Exception as exc:
        log_event("error", "Błąd Telegram", {"error": str(exc)})
        raise HTTPException(
            status_code=502, detail="Nie udało się wysłać alertu Telegram."
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
