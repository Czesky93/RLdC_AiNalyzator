"""
RLdC AiNalyzator - Główna Aplikacja Backendowa
System analizy i monitorowania transakcji oparty na AI
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Optional
import uvicorn
import sqlite3
from datetime import datetime
import os
import logging

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RLdC AiNalyzator API",
    description="System analizy i monitorowania transakcji oparty na AI",
    version="1.0.0"
)

# Pobierz dozwolone źródła z zmiennej środowiskowej, domyślnie localhost dla developmentu
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost").split(",")

# Middleware CORS dla komunikacji z frontendem
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Konfiguracja bazy danych
DB_PATH = os.getenv("DB_PATH", "trading_history.db")


def init_db():
    """Inicjalizacja bazy danych z wymaganymi tabelami"""
    try:
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
        logger.info(f"Baza danych zainicjalizowana pomyślnie: {DB_PATH}")
    except Exception as e:
        logger.error(f"Nie udało się zainicjalizować bazy danych: {e}")
        raise


# Modele
class Trade(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, description="Symbol transakcji")
    action: str = Field(..., description="Akcja transakcji (KUP lub SPRZEDAJ)")
    quantity: float = Field(..., gt=0, description="Ilość musi być dodatnia")
    price: float = Field(..., gt=0, description="Cena musi być dodatnia")
    total_value: float = Field(..., gt=0, description="Wartość całkowita musi być dodatnia")
    status: Optional[str] = Field(default="pending", description="Status transakcji")
    
    @validator('action')
    def validate_action(cls, v):
        if v.upper() not in ['BUY', 'SELL', 'KUP', 'SPRZEDAJ']:
            raise ValueError('Akcja musi być KUP lub SPRZEDAJ')
        # Normalizuj do angielskich wartości dla spójności w bazie danych
        if v.upper() in ['KUP']:
            return 'BUY'
        elif v.upper() in ['SPRZEDAJ']:
            return 'SELL'
        return v.upper()
    
    @validator('status')
    def validate_status(cls, v):
        # Normalizuj statusy do angielskich wartości dla spójności w bazie danych
        status_map = {
            'OCZEKUJĄCE': 'pending',
            'OCZEKUJACE': 'pending',
            'UKOŃCZONE': 'completed',
            'UKONCZONE': 'completed',
            'ANULOWANE': 'cancelled'
        }
        normalized = status_map.get(v.upper(), v)
        if normalized.lower() not in ['pending', 'completed', 'cancelled']:
            raise ValueError('Status musi być: pending, completed lub cancelled (lub po polsku: oczekujące, ukończone, anulowane)')
        return normalized.lower()
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()


class Analysis(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=10, description="Symbol transakcji")
    analysis_type: str = Field(..., min_length=1, description="Typ analizy")
    result: str = Field(..., min_length=1, description="Wynik analizy")
    confidence: Optional[float] = Field(default=None, ge=0, le=1, description="Poziom pewności (0-1)")
    
    @validator('symbol')
    def validate_symbol(cls, v):
        return v.upper()


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


# Endpointy
@app.on_event("startup")
async def startup_event():
    """Inicjalizacja bazy danych podczas uruchamiania"""
    init_db()


@app.get("/")
async def root():
    """Główny endpoint z informacjami o API"""
    return {
        "nazwa": "RLdC AiNalyzator API",
        "wersja": "1.0.0",
        "status": "działa",
        "endpointy": {
            "transakcje": "/api/trades",
            "analizy": "/api/analysis",
            "zdrowie": "/health"
        }
    }


@app.get("/health")
async def health_check():
    """Endpoint sprawdzania stanu"""
    return {"status": "zdrowy", "timestamp": datetime.now().isoformat()}


@app.get("/api/trades", response_model=List[TradeResponse])
async def get_trades(limit: int = 100):
    """Pobierz wszystkie transakcje z opcjonalnym limitem"""
    # Walidacja parametru limit
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="Limit musi być między 1 a 1000")
    
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
    except sqlite3.Error as e:
        logger.error(f"Błąd bazy danych podczas pobierania transakcji: {e}")
        raise HTTPException(status_code=500, detail="Nie udało się pobrać transakcji")
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas pobierania transakcji: {e}")
        raise HTTPException(status_code=500, detail="Wystąpił nieoczekiwany błąd")


@app.post("/api/trades", response_model=TradeResponse)
async def create_trade(trade: Trade):
    """Utwórz nowy rekord transakcji"""
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
    except sqlite3.Error as e:
        logger.error(f"Błąd bazy danych podczas tworzenia transakcji: {e}")
        raise HTTPException(status_code=500, detail="Nie udało się utworzyć transakcji")
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas tworzenia transakcji: {e}")
        raise HTTPException(status_code=500, detail="Wystąpił nieoczekiwany błąd")


@app.get("/api/analysis", response_model=List[AnalysisResponse])
async def get_analysis(limit: int = 100):
    """Pobierz wszystkie analizy z opcjonalnym limitem"""
    # Walidacja parametru limit
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="Limit musi być między 1 a 1000")
    
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
    except sqlite3.Error as e:
        logger.error(f"Błąd bazy danych podczas pobierania analiz: {e}")
        raise HTTPException(status_code=500, detail="Nie udało się pobrać analiz")
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas pobierania analiz: {e}")
        raise HTTPException(status_code=500, detail="Wystąpił nieoczekiwany błąd")


@app.post("/api/analysis", response_model=AnalysisResponse)
async def create_analysis(analysis: Analysis):
    """Utwórz nowy rekord analizy"""
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
    except sqlite3.Error as e:
        logger.error(f"Błąd bazy danych podczas tworzenia analizy: {e}")
        raise HTTPException(status_code=500, detail="Nie udało się utworzyć analizy")
    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas tworzenia analizy: {e}")
        raise HTTPException(status_code=500, detail="Wystąpił nieoczekiwany błąd")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
