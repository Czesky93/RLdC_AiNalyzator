"""
Database models and configuration for RLdC Trading Bot.
"""
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, Boolean, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import json
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
    gross_pnl = Column(Float)
    net_pnl = Column(Float)
    total_cost = Column(Float)
    fee_cost = Column(Float)
    slippage_cost = Column(Float)
    spread_cost = Column(Float)
    expected_edge = Column(Float)
    realized_rr = Column(Float)
    config_snapshot_id = Column(String(64), index=True)
    entry_reason_code = Column(String(80))
    exit_reason_code = Column(String(80))
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
    gross_pnl = Column(Float)
    net_pnl = Column(Float)
    total_cost = Column(Float)
    fee_cost = Column(Float)
    slippage_cost = Column(Float)
    spread_cost = Column(Float)
    expected_edge = Column(Float)
    realized_rr = Column(Float)
    config_snapshot_id = Column(String(64), index=True)
    entry_reason_code = Column(String(80))
    exit_reason_code = Column(String(80))
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
    config_snapshot_id = Column(String(64), index=True)
    strategy_name = Column(String(80))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    confirmed_at = Column(DateTime)


class RuntimeSetting(Base):
    """Ustawienia runtime (control plane) - override ENV, persist w DB."""

    __tablename__ = "runtime_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, index=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class ConfigSnapshot(Base):
    """Immutable-ish persisted payload for a runtime configuration version."""

    __tablename__ = "config_snapshots"

    id = Column(String(64), primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    config_hash = Column(String(128), index=True, nullable=False)
    payload_json = Column(Text, nullable=False)
    source = Column(String(40), nullable=False, default="runtime_state")
    changed_fields_json = Column(Text)
    previous_snapshot_id = Column(String(64), index=True)
    notes = Column(Text)
    is_current = Column(Boolean, default=False, index=True)


class Experiment(Base):
    """Tracked comparison between baseline and candidate config snapshots."""

    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, index=True)
    description = Column(Text)
    status = Column(String(20), nullable=False, default="planned", index=True)
    mode = Column(String(10), nullable=False, default="demo", index=True)
    baseline_snapshot_id = Column(String(64), nullable=False, index=True)
    candidate_snapshot_id = Column(String(64), nullable=False, index=True)
    scope = Column(String(20), nullable=False, default="global")
    symbol = Column(String(20), index=True)
    strategy_name = Column(String(80), index=True)
    start_at = Column(DateTime)
    end_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    ended_at = Column(DateTime)
    notes = Column(Text)


class ExperimentResult(Base):
    """Persisted comparison output for experiment variants and verdict."""

    __tablename__ = "experiment_results"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, nullable=False, index=True)
    variant = Column(String(20), nullable=False, index=True)
    snapshot_id = Column(String(64), nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    breakdown_json = Column(Text)
    verdict = Column(String(20))
    reason_codes_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Recommendation(Base):
    """Evidence-based recommendation derived from an experiment."""

    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    experiment_id = Column(Integer, nullable=False, index=True)
    baseline_snapshot_id = Column(String(64), nullable=False, index=True)
    candidate_snapshot_id = Column(String(64), nullable=False, index=True)
    recommendation = Column(String(32), nullable=False, index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    reason_codes_json = Column(Text)
    summary = Column(Text, nullable=False)
    parameter_changes_json = Column(Text)
    net_effect_summary_json = Column(Text)
    risk_effect_summary_json = Column(Text)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    notes = Column(Text)


class RecommendationReview(Base):
    """Human review decision over a recommendation."""

    __tablename__ = "recommendation_reviews"

    id = Column(Integer, primary_key=True, index=True)
    recommendation_id = Column(Integer, nullable=False, index=True)
    review_status = Column(String(20), nullable=False, index=True)
    reviewed_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewed_by = Column(String(120), nullable=False)
    decision_reason = Column(String(120))
    notes = Column(Text)
    promotion_ready = Column(Boolean, default=False, index=True)
    previous_review_id = Column(Integer, index=True)
    superseded_by = Column(Integer, index=True)


class ConfigPromotion(Base):
    """Controlled promotion event from one approved snapshot to another."""

    __tablename__ = "config_promotions"

    id = Column(Integer, primary_key=True, index=True)
    recommendation_id = Column(Integer, nullable=False, index=True)
    review_id = Column(Integer, nullable=False, index=True)
    from_snapshot_id = Column(String(64), nullable=False, index=True)
    to_snapshot_id = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    initiated_at = Column(DateTime, default=datetime.utcnow, index=True)
    applied_at = Column(DateTime)
    failed_at = Column(DateTime)
    initiated_by = Column(String(120), nullable=False)
    failure_reason = Column(Text)
    rollback_available = Column(Boolean, default=False)
    rollback_snapshot_id = Column(String(64), index=True)
    post_promotion_monitoring_status = Column(String(20), nullable=False, default="pending", index=True)
    validation_summary_json = Column(Text)
    runtime_apply_result_json = Column(Text)
    notes = Column(Text)


class PromotionMonitoring(Base):
    """Observed post-promotion performance and risk evaluation."""

    __tablename__ = "promotion_monitoring"

    id = Column(Integer, primary_key=True, index=True)
    promotion_id = Column(Integer, nullable=False, index=True)
    from_snapshot_id = Column(String(64), nullable=False, index=True)
    to_snapshot_id = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_evaluated_at = Column(DateTime)
    evaluation_window_start = Column(DateTime)
    evaluation_window_end = Column(DateTime)
    baseline_reference_summary_json = Column(Text)
    observed_summary_json = Column(Text)
    deviation_summary_json = Column(Text)
    reason_codes_json = Column(Text)
    rollback_recommended = Column(Boolean, default=False, index=True)
    min_trade_count_gate_passed = Column(Boolean, default=False)
    min_time_window_gate_passed = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    evaluation_version = Column(String(20), default="v1")
    notes = Column(Text)


class ConfigRollback(Base):
    """Rollback decision/execution record linked to a promotion lineage."""

    __tablename__ = "config_rollbacks"

    id = Column(Integer, primary_key=True, index=True)
    promotion_id = Column(Integer, nullable=False, index=True)
    monitoring_id = Column(Integer, nullable=False, index=True)
    decision_source = Column(String(20), nullable=False, default="monitoring", index=True)
    decision_status = Column(String(24), nullable=False, index=True)
    execution_status = Column(String(20), nullable=False, default="pending", index=True)
    from_snapshot_id = Column(String(64), nullable=False, index=True)
    to_snapshot_id = Column(String(64), nullable=False, index=True)
    rollback_snapshot_id = Column(String(64), index=True)
    initiated_at = Column(DateTime, default=datetime.utcnow, index=True)
    executed_at = Column(DateTime)
    failed_at = Column(DateTime)
    initiated_by = Column(String(120))
    failure_reason = Column(Text)
    validation_summary_json = Column(Text)
    runtime_apply_result_json = Column(Text)
    rollback_reason_codes_json = Column(Text)
    urgency = Column(String(16), default="low", index=True)
    notes = Column(Text)
    post_rollback_monitoring_status = Column(String(20), default="pending", index=True)


class RollbackMonitoring(Base):
    """Observed post-rollback stabilization monitoring."""

    __tablename__ = "rollback_monitoring"

    id = Column(Integer, primary_key=True, index=True)
    rollback_id = Column(Integer, nullable=False, index=True)
    promotion_id = Column(Integer, nullable=False, index=True)
    from_snapshot_id = Column(String(64), nullable=False, index=True)
    to_snapshot_id = Column(String(64), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="pending", index=True)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_evaluated_at = Column(DateTime)
    evaluation_window_start = Column(DateTime)
    evaluation_window_end = Column(DateTime)
    pre_rollback_summary_json = Column(Text)
    observed_summary_json = Column(Text)
    deviation_summary_json = Column(Text)
    reason_codes_json = Column(Text)
    min_trade_count_gate_passed = Column(Boolean, default=False)
    min_time_window_gate_passed = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    evaluation_version = Column(String(20), default="v1")
    notes = Column(Text)


class PolicyAction(Base):
    """Operational policy action derived from existing verdict records."""

    __tablename__ = "policy_actions"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(40), nullable=False, index=True)
    source_id = Column(Integer, nullable=False, index=True)
    policy_action = Column(String(40), nullable=False, index=True)
    priority = Column(String(16), nullable=False, default="low", index=True)
    requires_human_review = Column(Boolean, default=False, index=True)
    promotion_allowed = Column(Boolean, default=True, index=True)
    rollback_allowed = Column(Boolean, default=False, index=True)
    experiments_allowed = Column(Boolean, default=True, index=True)
    freeze_recommendations = Column(Boolean, default=False, index=True)
    summary = Column(Text, nullable=False)
    reason_codes_json = Column(Text)
    status = Column(String(20), nullable=False, default="open", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    resolved_at = Column(DateTime)
    superseded_by = Column(Integer, index=True)
    notes = Column(Text)


class DecisionTrace(Base):
    """Structured trace for both blocked and executed decisions."""

    __tablename__ = "decision_traces"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    timeframe = Column(String(10))
    mode = Column(String(10), nullable=False)
    action_type = Column(String(40), nullable=False)
    reason_code = Column(String(80), nullable=False)
    strategy_name = Column(String(80))
    signal_summary = Column(Text)
    risk_gate_result = Column(Text)
    cost_gate_result = Column(Text)
    execution_gate_result = Column(Text)
    config_snapshot_id = Column(String(64), index=True)
    position_id = Column(Integer, index=True)
    order_id = Column(Integer, index=True)
    payload = Column(Text)


class CostLedger(Base):
    """Breakdown of expected and actual costs per order/position."""

    __tablename__ = "cost_ledger"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, index=True)
    position_id = Column(Integer, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    cost_type = Column(String(40), nullable=False)
    expected_value = Column(Float)
    actual_value = Column(Float)
    currency = Column(String(16), nullable=False, default="QUOTE")
    notional = Column(Float)
    bps = Column(Float)
    config_snapshot_id = Column(String(64), index=True)
    notes = Column(Text)


# Database initialization
def init_db():
    """Inicjalizacja bazy danych - tworzenie tabel"""
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    print("✅ Baza danych zainicjalizowana")


def _ensure_schema():
    """Minimalna migracja schematu (bez Alembic)."""
    inspector = inspect(engine)

    def _ensure_column(table_name: str, column_name: str, ddl: str) -> None:
        if table_name not in inspector.get_table_names():
            return
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if column_name in columns:
            return
        with engine.begin() as conn:
            try:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
                print(f"✅ Dodano kolumnę '{column_name}' do tabeli '{table_name}'")
            except Exception as exc:
                print(f"⚠️ Nie udało się dodać kolumny '{column_name}' do '{table_name}': {exc}")

    _ensure_column("klines", "timeframe", "VARCHAR(10)")
    for table_name in ("orders", "positions"):
        _ensure_column(table_name, "gross_pnl", "FLOAT")
        _ensure_column(table_name, "net_pnl", "FLOAT")
        _ensure_column(table_name, "total_cost", "FLOAT")
        _ensure_column(table_name, "fee_cost", "FLOAT")
        _ensure_column(table_name, "slippage_cost", "FLOAT")
        _ensure_column(table_name, "spread_cost", "FLOAT")
        _ensure_column(table_name, "expected_edge", "FLOAT")
        _ensure_column(table_name, "realized_rr", "FLOAT")
        _ensure_column(table_name, "config_snapshot_id", "VARCHAR(64)")
        _ensure_column(table_name, "entry_reason_code", "VARCHAR(80)")
        _ensure_column(table_name, "exit_reason_code", "VARCHAR(80)")
    _ensure_column("pending_orders", "config_snapshot_id", "VARCHAR(64)")
    _ensure_column("config_rollbacks", "execution_status", "VARCHAR(20) DEFAULT 'pending'")
    _ensure_column("pending_orders", "strategy_name", "VARCHAR(80)")
    _ensure_column("config_snapshots", "config_hash", "VARCHAR(128)")
    _ensure_column("config_snapshots", "payload_json", "TEXT")
    _ensure_column("config_snapshots", "source", "VARCHAR(40)")
    _ensure_column("config_snapshots", "changed_fields_json", "TEXT")
    _ensure_column("config_snapshots", "previous_snapshot_id", "VARCHAR(64)")
    _ensure_column("config_snapshots", "notes", "TEXT")
    _ensure_column("config_snapshots", "is_current", "BOOLEAN")


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
        "config_snapshots",
        "experiments",
        "experiment_results",
        "recommendations",
        "recommendation_reviews",
        "config_promotions",
        "promotion_monitoring",
        "config_rollbacks",
        "rollback_monitoring",
        "policy_actions",
        "decision_traces",
        "cost_ledger",
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
        "decision_traces",
        "cost_ledger",
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


def _json_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _json_load(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def save_config_snapshot(
    db,
    *,
    snapshot_id: str,
    config_hash: str,
    payload,
    source: str = "runtime_state",
    changed_fields=None,
    previous_snapshot_id: str | None = None,
    notes: str | None = None,
    is_current: bool = True,
) -> ConfigSnapshot:
    existing = db.query(ConfigSnapshot).filter(ConfigSnapshot.id == snapshot_id).first()
    if existing is not None:
        if is_current:
            db.query(ConfigSnapshot).update({ConfigSnapshot.is_current: False}, synchronize_session=False)
            existing.is_current = True
        if source and not existing.source:
            existing.source = source
        if previous_snapshot_id and not existing.previous_snapshot_id:
            existing.previous_snapshot_id = previous_snapshot_id
        if changed_fields is not None and not existing.changed_fields_json:
            existing.changed_fields_json = _json_text(changed_fields)
        if notes and not existing.notes:
            existing.notes = notes
        return existing

    if is_current:
        db.query(ConfigSnapshot).update({ConfigSnapshot.is_current: False}, synchronize_session=False)

    row = ConfigSnapshot(
        id=snapshot_id,
        config_hash=config_hash,
        payload_json=_json_text(payload),
        source=source,
        changed_fields_json=_json_text(changed_fields),
        previous_snapshot_id=previous_snapshot_id,
        notes=notes,
        is_current=is_current,
    )
    db.add(row)
    return row


def get_config_snapshot(db, snapshot_id: str | None) -> dict | None:
    if not snapshot_id:
        return None
    row = db.query(ConfigSnapshot).filter(ConfigSnapshot.id == snapshot_id).first()
    if row is None:
        return None
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "config_hash": row.config_hash,
        "payload": _json_load(row.payload_json),
        "source": row.source,
        "changed_fields": _json_load(row.changed_fields_json) or [],
        "previous_snapshot_id": row.previous_snapshot_id,
        "notes": row.notes,
        "is_current": bool(row.is_current),
    }


def list_config_snapshots(db) -> list[dict]:
    rows = db.query(ConfigSnapshot).order_by(ConfigSnapshot.created_at.desc(), ConfigSnapshot.id.desc()).all()
    return [get_config_snapshot(db, row.id) for row in rows if row.id]


def compare_config_snapshots(db, snapshot_a: str, snapshot_b: str) -> dict:
    left = get_config_snapshot(db, snapshot_a)
    right = get_config_snapshot(db, snapshot_b)
    if left is None or right is None:
        missing = []
        if left is None:
            missing.append(str(snapshot_a))
        if right is None:
            missing.append(str(snapshot_b))
        raise ValueError(f"Missing config snapshot(s): {', '.join(missing)}")

    payload_a = left.get("payload") or {}
    payload_b = right.get("payload") or {}
    diffs: list[dict] = []

    def _walk(prefix: str, a, b) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a.keys()) | set(b.keys())):
                next_prefix = f"{prefix}.{key}" if prefix else key
                _walk(next_prefix, a.get(key), b.get(key))
            return
        if a != b:
            diffs.append({"field": prefix, "old_value": a, "new_value": b})

    _walk("", payload_a, payload_b)
    return {
        "snapshot_a": left,
        "snapshot_b": right,
        "changed_fields": [item["field"] for item in diffs],
        "diff": diffs,
    }


def save_decision_trace(
    db,
    *,
    symbol: str,
    mode: str,
    action_type: str,
    reason_code: str,
    timeframe: str | None = None,
    strategy_name: str | None = None,
    signal_summary=None,
    risk_gate_result=None,
    cost_gate_result=None,
    execution_gate_result=None,
    config_snapshot_id: str | None = None,
    position_id: int | None = None,
    order_id: int | None = None,
    payload=None,
    timestamp: datetime | None = None,
) -> DecisionTrace:
    trace = DecisionTrace(
        timestamp=timestamp or datetime.utcnow(),
        symbol=symbol,
        timeframe=timeframe,
        mode=mode,
        action_type=action_type,
        reason_code=reason_code,
        strategy_name=strategy_name,
        signal_summary=_json_text(signal_summary),
        risk_gate_result=_json_text(risk_gate_result),
        cost_gate_result=_json_text(cost_gate_result),
        execution_gate_result=_json_text(execution_gate_result),
        config_snapshot_id=config_snapshot_id,
        position_id=position_id,
        order_id=order_id,
        payload=_json_text(payload),
    )
    db.add(trace)
    return trace


def save_cost_entry(
    db,
    *,
    symbol: str,
    cost_type: str,
    order_id: int | None = None,
    position_id: int | None = None,
    expected_value: float | None = None,
    actual_value: float | None = None,
    currency: str = "QUOTE",
    notional: float | None = None,
    bps: float | None = None,
    config_snapshot_id: str | None = None,
    notes: str | None = None,
    timestamp: datetime | None = None,
) -> CostLedger:
    entry = CostLedger(
        order_id=order_id,
        position_id=position_id,
        symbol=symbol,
        timestamp=timestamp or datetime.utcnow(),
        cost_type=cost_type,
        expected_value=expected_value,
        actual_value=actual_value,
        currency=currency,
        notional=notional,
        bps=bps,
        config_snapshot_id=config_snapshot_id,
        notes=notes,
    )
    db.add(entry)
    return entry


def load_order_cost_summary(db, order_id: int) -> dict:
    rows = db.query(CostLedger).filter(CostLedger.order_id == order_id).all()
    summary = {
        "fee_cost": 0.0,
        "slippage_cost": 0.0,
        "spread_cost": 0.0,
        "total_cost": 0.0,
        "rows": len(rows),
    }
    for row in rows:
        value = float(row.actual_value or row.expected_value or 0.0)
        summary["total_cost"] += value
        if row.cost_type in {"maker_fee", "taker_fee"}:
            summary["fee_cost"] += value
        elif row.cost_type == "slippage":
            summary["slippage_cost"] += value
        elif row.cost_type == "spread":
            summary["spread_cost"] += value
    return summary


def attach_costs_to_order(
    db,
    *,
    order: Order,
    gross_pnl: float | None = None,
    expected_edge: float | None = None,
    realized_rr: float | None = None,
    entry_reason_code: str | None = None,
    exit_reason_code: str | None = None,
    config_snapshot_id: str | None = None,
) -> dict:
    try:
        db.flush()
    except Exception:
        pass
    summary = load_order_cost_summary(db, int(order.id))
    order.fee_cost = summary["fee_cost"]
    order.slippage_cost = summary["slippage_cost"]
    order.spread_cost = summary["spread_cost"]
    order.total_cost = summary["total_cost"]
    if gross_pnl is not None:
        order.gross_pnl = gross_pnl
        order.net_pnl = float(gross_pnl) - float(summary["total_cost"])
    if expected_edge is not None:
        order.expected_edge = expected_edge
    if realized_rr is not None:
        order.realized_rr = realized_rr
    if entry_reason_code is not None:
        order.entry_reason_code = entry_reason_code
    if exit_reason_code is not None:
        order.exit_reason_code = exit_reason_code
    if config_snapshot_id is not None:
        order.config_snapshot_id = config_snapshot_id
    return summary
