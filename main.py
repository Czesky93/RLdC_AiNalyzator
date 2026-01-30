"""
RLdC AiNalyzator - Main Backend Application
AI-powered trading analysis and monitoring system
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import sqlite3
from datetime import datetime
import os

app = FastAPI(
    title="RLdC AiNalyzator API",
    description="AI-powered trading analysis and monitoring system",
    version="1.0.0"
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
DB_PATH = os.getenv("DB_PATH", "trading_history.db")


def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            total_value REAL NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            analysis_type TEXT NOT NULL,
            result TEXT NOT NULL,
            confidence REAL
        )
    """)
    
    conn.commit()
    conn.close()


# Models
class Trade(BaseModel):
    symbol: str
    action: str
    quantity: float
    price: float
    total_value: float
    status: Optional[str] = "pending"


class Analysis(BaseModel):
    symbol: str
    analysis_type: str
    result: str
    confidence: Optional[float] = None


class TradeResponse(BaseModel):
    id: int
    timestamp: str
    symbol: str
    action: str
    quantity: float
    price: float
    total_value: float
    status: str


class AnalysisResponse(BaseModel):
    id: int
    timestamp: str
    symbol: str
    analysis_type: str
    result: str
    confidence: Optional[float]


# Routes
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    init_db()
    print(f"Database initialized at {DB_PATH}")


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "RLdC AiNalyzator API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "trades": "/api/trades",
            "analysis": "/api/analysis",
            "health": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = 100):
    """Get all trades with optional limit"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, symbol, action, quantity, price, total_value, status "
            "FROM trades ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        trades = []
        for row in cursor.fetchall():
            trades.append(TradeResponse(
                id=row[0],
                timestamp=row[1],
                symbol=row[2],
                action=row[3],
                quantity=row[4],
                price=row[5],
                total_value=row[6],
                status=row[7]
            ))
        conn.close()
        return trades
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trades", response_model=TradeResponse)
async def create_trade(trade: Trade):
    """Create a new trade record"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO trades (timestamp, symbol, action, quantity, price, total_value, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (timestamp, trade.symbol, trade.action, trade.quantity, trade.price, trade.total_value, trade.status)
        )
        conn.commit()
        trade_id = cursor.lastrowid
        conn.close()
        
        return TradeResponse(
            id=trade_id,
            timestamp=timestamp,
            symbol=trade.symbol,
            action=trade.action,
            quantity=trade.quantity,
            price=trade.price,
            total_value=trade.total_value,
            status=trade.status
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/analysis", response_model=List[AnalysisResponse])
async def get_analysis(limit: int = 100):
    """Get all analysis records with optional limit"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, symbol, analysis_type, result, confidence "
            "FROM analysis ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        analyses = []
        for row in cursor.fetchall():
            analyses.append(AnalysisResponse(
                id=row[0],
                timestamp=row[1],
                symbol=row[2],
                analysis_type=row[3],
                result=row[4],
                confidence=row[5]
            ))
        conn.close()
        return analyses
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis", response_model=AnalysisResponse)
async def create_analysis(analysis: Analysis):
    """Create a new analysis record"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "INSERT INTO analysis (timestamp, symbol, analysis_type, result, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (timestamp, analysis.symbol, analysis.analysis_type, analysis.result, analysis.confidence)
        )
        conn.commit()
        analysis_id = cursor.lastrowid
        conn.close()
        
        return AnalysisResponse(
            id=analysis_id,
            timestamp=timestamp,
            symbol=analysis.symbol,
            analysis_type=analysis.analysis_type,
            result=analysis.result,
            confidence=analysis.confidence
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
