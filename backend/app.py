"""
Main FastAPI application for RLdC Trading Bot
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import threading
import os
import sys
import subprocess
import signal
import time
from dotenv import load_dotenv

# Import database
from backend.database import init_db

# Import routers
from backend.routers import market, portfolio, orders, signals, account, positions, blog, control
from backend.collector import DataCollector
from backend.reevaluation_worker import start_worker, stop_worker

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
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
    lifespan=lifespan
)

# CORS middleware - pozwala na łączenie z frontendem
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
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
        "message": "API działa poprawnie ✅"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected",
        "timestamp": "2026-01-31T17:30:00Z"
    }


# Register routers
app.include_router(market.router, prefix="/api/market", tags=["Market"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(account.router, prefix="/api/account", tags=["Account"])
app.include_router(positions.router, prefix="/api/positions", tags=["Positions"])
app.include_router(blog.router, prefix="/api/blog", tags=["Blog"])
app.include_router(control.router, prefix="/api/control", tags=["Control"])


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
            "export NVM_DIR=\"$HOME/.nvm\" && . \"$NVM_DIR/nvm.sh\" && nvm use 20.11.1 >/dev/null && cd web_portal && npm run dev",
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
        "backend.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
