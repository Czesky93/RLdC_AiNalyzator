"""
Main FastAPI application for RLdC Trading Bot
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import time as _time_module
from contextlib import asynccontextmanager
from datetime import datetime, timezone

_startup_time = _time_module.time()

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import tunnel_manager as _tunnel_mgr
from backend.collector import DataCollector

# Import database
from backend.database import init_db
from backend.reevaluation_worker import start_worker, stop_worker

# Import routers
from backend.routers import account, blog, control, dashboard
from backend.routers import debug as debug_router
from backend.routers import market, orders, portfolio, positions, signals
from backend.routers import system as system_router
from backend.routers import telegram_intel

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
# Nie nadpisuj zmiennych już ustawionych przez środowisko (np. pytest).
load_dotenv(dotenv_path=_ENV_PATH, override=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management - startup and shutdown"""
    # Startup
    print("🚀 Uruchamianie RLdC Trading Bot API...")
    init_db()
    # Auto-start kolektora danych
    collector = None
    disable_collector = os.getenv("DISABLE_COLLECTOR", "false").lower() == "true"
    if not disable_collector:
        collector = DataCollector()
        app.state.collector = collector
        collector_thread = threading.Thread(target=collector.start, daemon=True)
        collector_thread.start()
    # Auto-start reevaluation worker
    worker_started = False
    if not disable_collector:
        worker_started = start_worker()

    # Warm-up cache portfela i scannera w tle (pierwsze otwarcie strony szybkie)
    def _warmup_caches():
        try:
            import time as _time

            _time.sleep(8)  # poczekaj aż kolektor i DB się zainicjalizują
            from backend.database import SessionLocal
            from backend.routers.market import (
                _scanner_cache,
                _scanner_cache_lock,
                _scanner_cache_ts,
                _scanner_cache_ttl,
                _score_symbol,
            )
            from backend.routers.portfolio import _build_live_spot_portfolio

            db = SessionLocal()
            try:
                _build_live_spot_portfolio(db)
            except Exception:
                pass
            finally:
                db.close()
        except Exception:
            pass

    warmup_thread = threading.Thread(target=_warmup_caches, daemon=True)
    warmup_thread.start()

    # Reconcile przy starcie aplikacji (tylko LIVE, w tle)
    def _startup_reconcile():
        try:
            import time as _time

            _time.sleep(15)  # Poczekaj aż Binance client się zainicjalizuje
            from backend.portfolio_reconcile import run_reconcile_cycle

            trading_mode = os.getenv("TRADING_MODE", "demo").lower()
            if trading_mode == "live":
                run_reconcile_cycle(mode="live", trigger="startup", force=True)
        except Exception as exc:
            logger.warning("Startup reconcile error: %s", exc)

    if not disable_collector:
        reconcile_startup_thread = threading.Thread(
            target=_startup_reconcile, daemon=True
        )
        reconcile_startup_thread.start()

    # Sprawdź / napraw tunnel publiczny przy starcie (w tle, nie blokuje API)
    tunnel_startup_thread = threading.Thread(
        target=_tunnel_mgr.startup_ensure, daemon=True
    )
    tunnel_startup_thread.start()

    print("✅ API gotowe do użycia")
    yield
    # Shutdown
    if worker_started:
        try:
            stop_worker()
        except Exception:
            pass
    if collector is not None:
        try:
            collector.stop()
        except Exception:
            pass
    print("🛑 Zamykanie RLdC Trading Bot API...")


# Initialize FastAPI app
app = FastAPI(
    title="RLdC Trading Bot API",
    description="API dla systemu autonomicznego tradingu RLdC AiNalyzator",
    version="0.7.0-beta",
    lifespan=lifespan,
    redirect_slashes=False,
)

# CORS middleware - pozwala na łączenie z frontendem
_CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:3000,http://192.168.0.109:3000"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
async def root():
    """Root endpoint - health check"""
    return {
        "status": "online",
        "service": "RLdC Trading Bot API",
        "version": "0.7.0-beta",
        "message": "API działa poprawnie ✅",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint — stan backendu, Binance, AI i uptime."""
    import time as _time

    from backend.database import SessionLocal

    uptime: float = 0.0
    try:
        uptime = _time.time() - _startup_time
    except Exception:
        pass

    # Binance connectivity
    binance_status = "unknown"
    try:
        from backend.binance_client import BinanceClient

        _bc = BinanceClient()
        # Sprawdź czas serwera (minimalne zapytanie)
        _ticker = _bc.get_ticker_price("BTCEUR")
        binance_status = "ok" if _ticker else "no_data"
    except Exception as _e:
        binance_status = f"error: {type(_e).__name__}"

    # DB connectivity
    db_status = "unknown"
    try:
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        db_status = "connected"
    except Exception as _e:
        db_status = f"error: {type(_e).__name__}"

    # AI provider status — użyj statusu z cache orchestratora
    ai_status = os.getenv("AI_PROVIDER", "heuristic")
    ai_local_enabled = None
    ai_local_configured = None
    ai_local_reachable = None
    ai_local_selected = None
    ai_local_last_error = None
    ai_local_last_healthcheck = None
    ai_local_latency_ms = None
    ai_local_model = None
    ai_local_endpoint = None
    ai_local_model_installed = None
    try:
        from backend.ai_orchestrator import get_ai_orchestrator_status as _ai_status_fn

        _ai = _ai_status_fn(force=False)
        ai_status = _ai.get("primary") or os.getenv("AI_PROVIDER", "heuristic")
        ai_local_enabled = _ai.get("local_ai_enabled")
        ai_local_configured = _ai.get("local_ai_configured")
        ai_local_reachable = _ai.get("local_ai_reachable")
        ai_local_selected = _ai.get("local_ai_selected")
        ai_local_last_error = _ai.get("local_ai_last_error")
        ai_local_last_healthcheck = _ai.get("local_ai_last_healthcheck")
        ai_local_latency_ms = _ai.get("local_ai_latency_ms")
        ai_local_model = _ai.get("local_ai_model")
        ai_local_endpoint = _ai.get("local_ai_endpoint")
        ai_local_model_installed = _ai.get("local_ai_model_installed")
    except Exception:
        pass

    # Collector / bot running
    collector_running = False
    try:
        collector_running = (
            hasattr(app.state, "collector")
            and app.state.collector is not None
            and getattr(app.state.collector, "running", False)
        )
    except Exception:
        pass

    return {
        "backend": "ok",
        "database": db_status,
        "binance": binance_status,
        "ai": ai_status,
        "local_ai": {
            "enabled": ai_local_enabled,
            "configured": ai_local_configured,
            "reachable": ai_local_reachable,
            "selected": ai_local_selected,
            "model": ai_local_model,
            "model_installed": ai_local_model_installed,
            "endpoint": ai_local_endpoint,
            "latency_ms": ai_local_latency_ms,
            "last_error": ai_local_last_error,
            "last_healthcheck": ai_local_last_healthcheck,
        },
        "collector": "running" if collector_running else "stopped",
        "uptime": round(uptime, 1),
        "uptime_h": round(uptime / 3600, 2),
        "version": "0.7.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
async def api_health_check():
    """Alias /api/health → /health"""
    return await health_check()


# Register routers
app.include_router(market.router, prefix="/api/market", tags=["Market"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(account.router, prefix="/api/account", tags=["Account"])
app.include_router(positions.router, prefix="/api/positions", tags=["Positions"])
app.include_router(blog.router, prefix="/api/blog", tags=["Blog"])
app.include_router(control.router, prefix="/api/control", tags=["Control"])
app.include_router(
    telegram_intel.router, prefix="/api/telegram-intel", tags=["Telegram Intelligence"]
)
app.include_router(
    debug_router.router, prefix="/api/debug", tags=["Debug / Diagnostics"]
)
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(
    system_router.router, prefix="/api/system", tags=["System Diagnostics"]
)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    env_reload = os.getenv("API_RELOAD", "false").lower() == "true"
    if "--reload" in sys.argv:
        reload = True
    elif "--no-reload" in sys.argv:
        reload = False
    else:
        reload = env_reload

    if reload:
        logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

    def _stream_logs(prefix: str, proc: subprocess.Popen):
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            print(f"[{prefix}] {line.rstrip()}")

    def run_all():
        print("🚀 Uruchamiam WSZYSTKO: backend + web + telegram")
        env = os.environ.copy()
        processes = []

        # Backend (API + collector)
        backend_cmd = [
            sys.executable,
            "-m",
            "backend.app",
            "--reload" if reload else "--no-reload",
        ]
        backend_proc = subprocess.Popen(
            backend_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        processes.append(("backend", backend_proc))

        # Telegram bot
        telegram_cmd = [
            sys.executable,
            "-m",
            "telegram_bot.bot",
        ]
        telegram_proc = subprocess.Popen(
            telegram_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        processes.append(("telegram", telegram_proc))

        # Web portal (Next.js)
        web_cmd = [
            "bash",
            "-lc",
            'export NVM_DIR="$HOME/.nvm" && . "$NVM_DIR/nvm.sh" && nvm use 20.11.1 >/dev/null && cd web_portal && npm run dev',
        ]
        web_proc = subprocess.Popen(
            web_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        processes.append(("web", web_proc))

        # Log threads
        threads = []
        for name, proc in processes:
            t = threading.Thread(target=_stream_logs, args=(name, proc), daemon=True)
            t.start()
            threads.append(t)

        print("✅ Wszystkie procesy uruchomione. Logi będą wypisywane poniżej.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("🛑 Zatrzymywanie wszystkich procesów...")
            for _, proc in processes:
                try:
                    proc.send_signal(signal.SIGINT)
                except Exception:
                    pass
            for _, proc in processes:
                try:
                    proc.terminate()
                except Exception:
                    pass

    if "--all" in sys.argv:
        run_all()
        sys.exit(0)

    print(f"🚀 Uruchamianie serwera na {host}:{port}")
    uvicorn.run(
        "backend.app:app", host=host, port=port, reload=reload, log_level="info"
    )
