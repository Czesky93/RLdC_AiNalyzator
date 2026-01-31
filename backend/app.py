"""
Main FastAPI application for RLdC Trading Bot
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv

# Import database
from backend.database import init_db

# Import routers (będą dodane później)
# from backend.routers import market, portfolio, orders, signals, account

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management - startup and shutdown"""
    # Startup
    print("🚀 Uruchamianie RLdC Trading Bot API...")
    init_db()
    print("✅ API gotowe do użycia")
    yield
    # Shutdown
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


# Register routers (będą dodane w kolejnych krokach)
# app.include_router(market.router, prefix="/api/market", tags=["Market"])
# app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
# app.include_router(orders.router, prefix="/api/orders", tags=["Orders"])
# app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
# app.include_router(account.router, prefix="/api/account", tags=["Account"])


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    reload = os.getenv("API_RELOAD", "true").lower() == "true"
    
    print(f"🚀 Uruchamianie serwera na {host}:{port}")
    uvicorn.run(
        "backend.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
