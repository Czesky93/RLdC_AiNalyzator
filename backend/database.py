"""
Database models and configuration for RLdC Trading Bot
"""
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text, Enum, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading_bot.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database Models
class MarketData(Base):
    """Dane rynkowe (tickery)"""
    __tablename__ = "market_data"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    price = Column(Float, nullable=False)
    volume = Column(Float)
    bid = Column(Float)
    ask = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class Kline(Base):
    """Świece (OHLCV)"""
    __tablename__ = "klines"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    timeframe = Column(String(10), nullable=False)  # 1m, 5m, 15m, 1h, 4h, 1d
    open_time = Column(DateTime, index=True, nullable=False)
    close_time = Column(DateTime, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    quote_volume = Column(Float)
    trades = Column(Integer)
    taker_buy_base = Column(Float)
    taker_buy_quote = Column(Float)


class Signal(Base):
    """Sygnały AI"""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    signal_type = Column(String(10), nullable=False)  # BUY, SELL, HOLD
    confidence = Column(Float, nullable=False)  # 0.0 - 1.0
    price = Column(Float, nullable=False)
    indicators = Column(Text)  # JSON z wskaźnikami
    reason = Column(Text)  # Uzasadnienie po polsku
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class Order(Base):
    """Zlecenia (demo i live)"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    side = Column(String(10), nullable=False)  # BUY, SELL
    order_type = Column(String(20), nullable=False)  # MARKET, LIMIT, STOP_LOSS
    price = Column(Float)
    quantity = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)  # NEW, FILLED, CANCELLED, REJECTED
    mode = Column(String(10), nullable=False)  # demo, live
    executed_price = Column(Float)
    executed_quantity = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class Position(Base):
    """Otwarte pozycje"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    side = Column(String(10), nullable=False)  # LONG, SHORT
    entry_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    current_price = Column(Float)
    unrealized_pnl = Column(Float)
    mode = Column(String(10), nullable=False)  # demo, live
    opened_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountSnapshot(Base):
    """Snapshoty konta (equity, margin)"""
    __tablename__ = "account_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    mode = Column(String(10), nullable=False)  # demo, live
    equity = Column(Float, nullable=False)
    free_margin = Column(Float, nullable=False)
    used_margin = Column(Float, nullable=False)
    margin_level = Column(Float)  # (equity / used_margin) * 100
    balance = Column(Float, nullable=False)
    unrealized_pnl = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class Alert(Base):
    """Alerty systemowe"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String(50), nullable=False)  # SIGNAL, RISK, WHALE, NEWS
    severity = Column(String(20), nullable=False)  # INFO, WARNING, CRITICAL
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    symbol = Column(String(20))
    is_sent = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class SystemLog(Base):
    """Logi systemowe"""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    module = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    exception = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class BlogPost(Base):
    """Wpisy blogowe"""
    __tablename__ = "blog_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text)
    market_insights = Column(Text)  # JSON z insights
    status = Column(String(20), default="draft")  # draft, published
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)


class TelegramMessage(Base):
    """Historia wiadomości Telegram"""
    __tablename__ = "telegram_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(50), nullable=False)
    message_type = Column(String(50), nullable=False)  # COMMAND, ALERT
    command = Column(String(50))
    message = Column(Text, nullable=False)
    is_sent = Column(Boolean, default=False)
    error = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class PendingOrder(Base):
    """Oczekujące potwierdzenia transakcji (Telegram)"""
    __tablename__ = "pending_orders"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    side = Column(String(10), nullable=False)
    order_type = Column(String(20), nullable=False)
    price = Column(Float)
    quantity = Column(Float, nullable=False)
    mode = Column(String(10), nullable=False)  # demo, live
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, CONFIRMED, REJECTED, EXECUTED
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime)


class RuntimeSetting(Base):
    """Ustawienia runtime (control plane) - override ENV, persist w DB."""

    __tablename__ = "runtime_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, index=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


# Database initialization
def init_db():
    """Inicjalizacja bazy danych - tworzenie tabel"""
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    print("✅ Baza danych zainicjalizowana")


def _ensure_schema():
    """Minimalna migracja schematu (bez Alembic)."""
    inspector = inspect(engine)

    if "klines" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("klines")}
    if "timeframe" not in columns:
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE klines ADD COLUMN timeframe VARCHAR(10)"))
                print("✅ Dodano kolumnę 'timeframe' do tabeli 'klines'")
            except Exception as exc:
                print(f"⚠️ Nie udało się dodać kolumny 'timeframe': {exc}")


def get_db():
    """Dependency do uzyskania sesji DB"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_database(scope: str = "full"):
    """
    Resetuj dane w bazie.
    scope:
      - full: czyści wszystkie tabele danych (łącznie z market_data/klines)
      - demo: czyści dane demo/alerty/blog/logi/telegram
    """
    tables_full = [
        "market_data",
        "klines",
        "signals",
        "orders",
        "positions",
        "alerts",
        "blog_posts",
        "account_snapshots",
        "system_logs",
        "telegram_messages",
        "pending_orders",
        "runtime_settings",
    ]
    tables_demo = [
        "signals",
        "orders",
        "positions",
        "alerts",
        "blog_posts",
        "account_snapshots",
        "system_logs",
        "telegram_messages",
        "pending_orders",
    ]
    to_clear = tables_full if scope == "full" else tables_demo

    with engine.begin() as conn:
        if "sqlite" in DATABASE_URL:
            try:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
            except Exception:
                pass
        for table in to_clear:
            conn.execute(text(f"DELETE FROM {table}"))
        if "sqlite" in DATABASE_URL:
            try:
                conn.execute(text("PRAGMA foreign_keys=ON"))
            except Exception:
                pass


if __name__ == "__main__":
    init_db()
