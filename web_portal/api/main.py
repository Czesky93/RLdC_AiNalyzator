"""FastAPI application for the trading web portal."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database.session import init_db
from web_portal.api.routers import trading
import os

# Initialize database tables only if not in test mode
if os.getenv("TESTING") != "1":
    init_db()

# Create FastAPI app
app = FastAPI(
    title="Trading Bot API",
    description="API for visualizing paper trading results",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(trading.router)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Trading Bot API",
        "version": "1.0.0",
        "endpoints": {
            "trading_history": "/trading/history",
            "equity_curve": "/trading/equity",
            "trading_stats": "/trading/stats"
        }
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
