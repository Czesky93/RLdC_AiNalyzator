"""
Database models and configuration for RLdC Trading Bot.
"""

import json
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)
from dotenv import load_dotenv


def utc_now_naive() -> datetime:
    """
    Zwraca aktualny czas UTC jako naive datetime (bez tzinfo).

    Projekt używa UTC, ale SQLite przechowuje daty jako naive strings.
    NIE wolno mieszać aware i naive w filtrach SQLAlchemy — to powoduje
    ciche błędy (puste wyniki zapytań).
    Używaj tej funkcji wszędzie tam, gdzie czas jest porównywany z kolumnami DB.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading_bot.db")

_sqlite_connect_args: dict = {}
if "sqlite" in DATABASE_URL:
    _sqlite_connect_args = {"check_same_thread": False, "timeout": 30}

# SQLite: używamy NullPool aby każde żądanie dostawało świeże połączenie.
# QueuePool (domyślny) powoduje problemy z izolacją WAL — sesje z puli widują
# stare snapshoty zanim nastąpi checkpoint, co skutkuje zwrotem null dla entry_price.
_engine_kwargs: dict = {
    "connect_args": _sqlite_connect_args,
    "echo": False,
}
if "sqlite" in DATABASE_URL:
    from sqlalchemy.pool import NullPool as _NullPool

    _engine_kwargs["poolclass"] = _NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_engine(DATABASE_URL, **_engine_kwargs)

# WAL mode — pozwala na równoczesny odczyt i zapis (SQLite)
if "sqlite" in DATABASE_URL:
    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


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
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


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
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


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
    strategy_name = Column(String(80))
    source = Column(String(40))
    execution_mode = Column(String(20))
    notes = Column(Text)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


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
    opened_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    # Exit quality tracking (MFE/MAE)
    planned_tp = Column(Float)  # TP ustawiony przy wejściu
    planned_sl = Column(Float)  # SL ustawiony przy wejściu
    mfe_price = Column(Float)  # Maximum Favorable Excursion — najlepsza cena od wejścia
    mae_price = Column(Float)  # Maximum Adverse Excursion — najgorsza cena od wejścia
    mfe_pnl = Column(Float)  # PnL w momencie MFE
    mae_pnl = Column(Float)  # PnL w momencie MAE
    # Exit engine — warstwowe zarządzanie wyjściem
    highest_price_seen = Column(Float)  # max cena od wejścia (na bieżąco)
    trailing_active = Column(Boolean, default=False)  # czy trailing stop jest aktywny
    trailing_stop_price = Column(Float)  # aktualny poziom trailing stop
    partial_take_count = Column(
        Integer, default=0
    )  # ile razy już było częściowe zamknięcie
    exit_plan_json = Column(Text)  # JSON z planem wyjścia


class ExitQuality(Base):
    """Podsumowanie jakości trade'u — tworzone przy zamknięciu pozycji."""

    __tablename__ = "exit_quality"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    mode = Column(String(10), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    planned_tp = Column(Float)
    planned_sl = Column(Float)
    mfe_price = Column(Float)
    mae_price = Column(Float)
    gross_pnl = Column(Float)
    net_pnl = Column(Float)
    total_cost = Column(Float)
    # Metryki diagnostyczne
    mfe_pnl = Column(Float)  # max zysk osiągnięty w trakcie pozycji
    mae_pnl = Column(Float)  # max strata osiągnięta w trakcie pozycji
    gave_back_pct = Column(
        Float
    )  # % zysku oddanego po MFE: (mfe_pnl - net_pnl) / mfe_pnl * 100
    tp_hit = Column(Boolean)  # czy cena dotarła do TP
    tp_near_miss_pct = Column(
        Float
    )  # jak blisko TP dotarł MFE: (mfe - entry) / (tp - entry) * 100
    sl_hit = Column(Boolean)  # czy cena dotarła do SL
    expected_rr = Column(Float)  # planowany R:R = (tp-entry) / (entry-sl)
    realized_rr = Column(Float)  # zrealizowany R:R = net_pnl / |planned_risk|
    edge_vs_cost = Column(Float)  # net_pnl / total_cost — >1 = edge pokrył koszty
    duration_seconds = Column(Float)  # czas trwania pozycji
    config_snapshot_id = Column(String(64), index=True)
    exit_reason_code = Column(String(80))
    closed_at = Column(DateTime, default=utc_now_naive, index=True)


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
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


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
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


class SystemLog(Base):
    """Logi systemowe"""

    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    module = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    exception = Column(Text)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)


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
    created_at = Column(DateTime, default=utc_now_naive)


class TelegramMessage(Base):
    """Historia wiadomości Telegram — z klasyfikacją i parserem (Telegram Intelligence Layer)"""

    __tablename__ = "telegram_messages"

    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(String(50), nullable=False)
    message_type = Column(
        String(50), nullable=False
    )  # command | alert | signal | execution | status | error
    command = Column(String(50))
    message = Column(Text, nullable=False)
    is_sent = Column(Boolean, default=False)
    error = Column(Text)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)
    # Telegram Intelligence Layer — pola klasyfikacji
    direction = Column(String(20))  # incoming | outgoing | internal
    msg_category = Column(
        String(40)
    )  # SIGNAL_MESSAGE | EXECUTION_MESSAGE | BLOCKER_MESSAGE | ...
    severity = Column(String(20))  # info | warning | critical
    source_module = Column(
        String(50)
    )  # collector | telegram_bot | risk | orders | control | ui
    parsed_symbol = Column(String(20))
    parsed_side = Column(String(10))
    parsed_confidence = Column(Float)
    action_required = Column(Boolean, default=False)
    parsed_payload_json = Column(Text)  # JSON z wyciągniętymi danymi
    linked_order_id = Column(Integer)
    linked_position_id = Column(Integer)


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
    status = Column(
        String(20), nullable=False, default="PENDING"
    )  # PENDING, CONFIRMED, REJECTED, EXECUTED
    reason = Column(Text)
    config_snapshot_id = Column(String(64), index=True)
    strategy_name = Column(String(80))
    source = Column(String(40))
    pending_type = Column(String(40))
    expires_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    confirmed_at = Column(DateTime)


class RuntimeSetting(Base):
    """Ustawienia runtime (control plane) - override ENV, persist w DB."""

    __tablename__ = "runtime_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, index=True, nullable=False)
    value = Column(Text)
    updated_at = Column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive, index=True
    )


class ConfigSnapshot(Base):
    """Immutable-ish persisted payload for a runtime configuration version."""

    __tablename__ = "config_snapshots"

    id = Column(String(64), primary_key=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
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
    created_at = Column(DateTime, default=utc_now_naive, index=True)
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
    created_at = Column(DateTime, default=utc_now_naive, index=True)


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
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    notes = Column(Text)


class RecommendationReview(Base):
    """Human review decision over a recommendation."""

    __tablename__ = "recommendation_reviews"

    id = Column(Integer, primary_key=True, index=True)
    recommendation_id = Column(Integer, nullable=False, index=True)
    review_status = Column(String(20), nullable=False, index=True)
    reviewed_at = Column(DateTime, default=utc_now_naive, index=True)
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
    initiated_at = Column(DateTime, default=utc_now_naive, index=True)
    applied_at = Column(DateTime)
    failed_at = Column(DateTime)
    initiated_by = Column(String(120), nullable=False)
    failure_reason = Column(Text)
    rollback_available = Column(Boolean, default=False)
    rollback_snapshot_id = Column(String(64), index=True)
    post_promotion_monitoring_status = Column(
        String(20), nullable=False, default="pending", index=True
    )
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
    started_at = Column(DateTime, default=utc_now_naive, index=True)
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
    decision_source = Column(
        String(20), nullable=False, default="monitoring", index=True
    )
    decision_status = Column(String(24), nullable=False, index=True)
    execution_status = Column(String(20), nullable=False, default="pending", index=True)
    from_snapshot_id = Column(String(64), nullable=False, index=True)
    to_snapshot_id = Column(String(64), nullable=False, index=True)
    rollback_snapshot_id = Column(String(64), index=True)
    initiated_at = Column(DateTime, default=utc_now_naive, index=True)
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
    started_at = Column(DateTime, default=utc_now_naive, index=True)
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
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    resolved_at = Column(DateTime)
    superseded_by = Column(Integer, index=True)
    notes = Column(Text)


class Incident(Base):
    """Governance incident lifecycle record linked to a policy action."""

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    policy_action_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="open", index=True)
    priority = Column(String(16), nullable=False, default="low", index=True)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String(80))
    escalated_at = Column(DateTime)
    resolved_at = Column(DateTime)
    resolved_by = Column(String(80))
    resolution_notes = Column(Text)
    sla_deadline = Column(DateTime)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class DecisionTrace(Base):
    """Structured trace for both blocked and executed decisions."""

    __tablename__ = "decision_traces"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)
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


class ForecastRecord(Base):
    """Zapis prognozy ceny — do śledzenia trafności AI."""

    __tablename__ = "forecast_records"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    horizon = Column(String(10), nullable=False)  # "1h", "4h", "24h"
    forecast_ts = Column(DateTime, default=utc_now_naive, index=True)
    forecast_price = Column(Float, nullable=False)  # przewidywana cena
    current_price_at_forecast = Column(Float, nullable=False)
    projected_pct = Column(Float)
    direction = Column(String(20))  # WZROST / SPADEK / BOCZNY
    target_ts = Column(DateTime, index=True)  # kiedy sprawdzić
    actual_price = Column(Float, nullable=True)
    error_pct = Column(Float, nullable=True)  # abs((actual-forecast)/forecast)*100
    correct_direction = Column(Boolean, nullable=True)  # czy kierunek był trafny
    checked = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=utc_now_naive)


class CostLedger(Base):
    """Breakdown of expected and actual costs per order/position."""

    __tablename__ = "cost_ledger"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, index=True)
    position_id = Column(Integer, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    timestamp = Column(DateTime, default=utc_now_naive, index=True)
    cost_type = Column(String(40), nullable=False)
    expected_value = Column(Float)
    actual_value = Column(Float)
    currency = Column(String(16), nullable=False, default="QUOTE")
    notional = Column(Float)
    bps = Column(Float)
    config_snapshot_id = Column(String(64), index=True)
    notes = Column(Text)


class UserExpectation(Base):
    """Oczekiwania użytkownika wobec symbolu lub całego portfela."""

    __tablename__ = "user_expectations"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(
        String(20), index=True, nullable=True
    )  # None = dotyczy całego portfela
    mode = Column(String(10), nullable=False, default="demo", index=True)

    # Typy celu: "target_value_eur", "target_price", "target_profit_pct",
    #            "no_buy", "no_sell", "profile_mode"
    expectation_type = Column(String(40), nullable=False)

    # Cele ilościowe
    target_value_eur = Column(Float, nullable=True)  # cel wartości pozycji w EUR
    target_price = Column(Float, nullable=True)  # cel ceny symbolu
    target_profit_pct = Column(Float, nullable=True)  # cel zysku procentowego

    # Zakazy i reguły ochronne
    no_buy = Column(Boolean, default=False)
    no_sell = Column(Boolean, default=False)
    no_auto_exit = Column(Boolean, default=False)

    # Preferencje stylu działania
    preferred_horizon = Column(String(20), nullable=True)  # "1d", "3d", "7d", "30d"
    profile_mode = Column(
        String(30), nullable=True
    )  # "scalp", "swing", "long_term", "capital_protection"

    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)


class DecisionAudit(Base):
    """Ślad warstw decyzji — która warstwa wygrała i dlaczego."""

    __tablename__ = "decision_audit"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    mode = Column(String(10), nullable=False, index=True)

    # Decyzje poszczególnych warstw (przed scaleniem)
    symbol_signal = Column(String(20))  # BUY/SELL/HOLD z analizy technicznej
    user_goal_decision = Column(String(30))  # z warstwy oczekiwań użytkownika
    position_decision = Column(String(30))  # z warstwy zarządzania pozycją
    portfolio_decision = Column(String(30))  # z warstwy trybu portfelowego / tiera

    # Wynik finalny
    final_action = Column(String(30), nullable=False)
    winning_priority = Column(String(40))  # która warstwa zdecydowała
    confidence = Column(Float)
    expectation_id = Column(
        Integer, nullable=True
    )  # FK do user_expectations (nie przez ORM)

    details_json = Column(Text)  # pełny kontekst w JSON
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class GoalAssessment(Base):
    """Ocena realności celu użytkownika — kalkulowana automatycznie."""

    __tablename__ = "goal_assessments"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True, nullable=False)
    expectation_id = Column(Integer, index=True, nullable=True)

    target_type = Column(String(30))  # "value_eur", "price", "pct"
    target_value = Column(Float)
    current_value = Column(Float)
    missing_value = Column(Float)
    required_move_pct = Column(Float)

    realism_score = Column(Float)  # 0.0–1.0
    realism_label = Column(String(40))  # "bardzo_realny"..."mało_realny"

    scenario_fast_days = Column(Float)
    scenario_base_days = Column(Float)
    scenario_slow_days = Column(Float)
    blockers_json = Column(Text)

    created_at = Column(DateTime, default=utc_now_naive, index=True)


class ReconciliationRun(Base):
    """Przebieg reconcylacji DB ↔ Binance."""

    __tablename__ = "reconciliation_runs"

    id = Column(Integer, primary_key=True, index=True)
    mode = Column(String(10), nullable=False, index=True)  # demo, live, both
    trigger = Column(String(40), nullable=False, default="scheduled")
    # startup | scheduled | post_fill | post_error | manual | telegram
    status = Column(String(20), nullable=False, default="running", index=True)
    # running | completed | failed
    events_count = Column(Integer, default=0)
    repairs_count = Column(Integer, default=0)
    manual_trades_detected = Column(Integer, default=0)
    error = Column(Text)
    summary_json = Column(Text)
    started_at = Column(DateTime, default=utc_now_naive, index=True)
    finished_at = Column(DateTime)


class ReconciliationEvent(Base):
    """Pojedyncze zdarzenie naprawcze wykryte podczas reconcylacji."""

    __tablename__ = "reconciliation_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, nullable=False, index=True)
    event_type = Column(String(60), nullable=False, index=True)
    # missing_position | orphan_position | pending_filled | pending_cancelled
    # qty_mismatch | avg_price_mismatch | balance_mismatch | manual_trade_detected
    symbol = Column(String(20), index=True)
    mode = Column(String(10))
    before_json = Column(Text)  # stan przed naprawą
    after_json = Column(Text)  # stan po naprawie
    source_of_truth = Column(String(20), default="binance")
    action_taken = Column(String(60))  # db_updated | db_created | db_closed | skipped
    reason = Column(Text)
    repaired = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=utc_now_naive, index=True)


class ManualTradeDetection(Base):
    """Wykryta manualna transakcja wykonana bezpośrednio na Binance."""

    __tablename__ = "manual_trade_detections"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    mode = Column(String(10), nullable=False, default="live")
    side = Column(String(10))  # BUY | SELL
    quantity = Column(Float)
    price = Column(Float)
    notional_eur = Column(Float)
    binance_order_id = Column(String(50), index=True)
    detection_source = Column(String(40), default="reconcile")
    db_synced = Column(Boolean, default=False, index=True)
    telegram_notified = Column(Boolean, default=False)
    detected_at = Column(DateTime, default=utc_now_naive, index=True)
    synced_at = Column(DateTime)


# Database initialization
def init_db():
    """Inicjalizacja bazy danych - tworzenie tabel"""
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.critical("Nie udało się utworzyć tabel: %s", exc)
        raise
    _ensure_schema()
    logger.info("Baza danych zainicjalizowana")


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
                conn.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")
                )
                logger.info(
                    "Dodano kolumnę '%s' do tabeli '%s'", column_name, table_name
                )
            except Exception as exc:
                logger.warning(
                    "Nie udało się dodać kolumny '%s' do '%s': %s",
                    column_name,
                    table_name,
                    exc,
                )

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
    _ensure_column("orders", "strategy_name", "VARCHAR(80)")
    _ensure_column("orders", "source", "VARCHAR(40)")
    _ensure_column("orders", "execution_mode", "VARCHAR(20)")
    _ensure_column("orders", "notes", "TEXT")
    # Exit quality tracking — pozycje
    for col, ddl in [
        ("planned_tp", "FLOAT"),
        ("planned_sl", "FLOAT"),
        ("mfe_price", "FLOAT"),
        ("mae_price", "FLOAT"),
        ("mfe_pnl", "FLOAT"),
        ("mae_pnl", "FLOAT"),
        ("highest_price_seen", "FLOAT"),
        ("trailing_active", "BOOLEAN DEFAULT 0"),
        ("trailing_stop_price", "FLOAT"),
        ("partial_take_count", "INTEGER DEFAULT 0"),
        ("exit_plan_json", "TEXT"),
    ]:
        _ensure_column("positions", col, ddl)

    _ensure_column("pending_orders", "config_snapshot_id", "VARCHAR(64)")
    _ensure_column("pending_orders", "source", "VARCHAR(40)")
    _ensure_column("pending_orders", "pending_type", "VARCHAR(40)")
    _ensure_column("pending_orders", "expires_at", "DATETIME")
    _ensure_column(
        "config_rollbacks", "execution_status", "VARCHAR(20) DEFAULT 'pending'"
    )
    _ensure_column("pending_orders", "strategy_name", "VARCHAR(80)")
    _ensure_column("config_snapshots", "config_hash", "VARCHAR(128)")
    _ensure_column("config_snapshots", "payload_json", "TEXT")
    _ensure_column("config_snapshots", "source", "VARCHAR(40)")
    _ensure_column("config_snapshots", "changed_fields_json", "TEXT")
    _ensure_column("config_snapshots", "previous_snapshot_id", "VARCHAR(64)")
    _ensure_column("config_snapshots", "notes", "TEXT")
    _ensure_column("config_snapshots", "is_current", "BOOLEAN")
    # Telegram Intelligence Layer — nowe kolumny w istniejącej tabeli
    _ensure_column("telegram_messages", "direction", "VARCHAR(20)")
    _ensure_column("telegram_messages", "msg_category", "VARCHAR(40)")
    _ensure_column("telegram_messages", "severity", "VARCHAR(20)")
    _ensure_column("telegram_messages", "source_module", "VARCHAR(50)")
    _ensure_column("telegram_messages", "parsed_symbol", "VARCHAR(20)")
    _ensure_column("telegram_messages", "parsed_side", "VARCHAR(10)")
    _ensure_column("telegram_messages", "parsed_confidence", "FLOAT")
    _ensure_column("telegram_messages", "action_required", "BOOLEAN")
    _ensure_column("telegram_messages", "parsed_payload_json", "TEXT")
    _ensure_column("telegram_messages", "linked_order_id", "INTEGER")
    _ensure_column("telegram_messages", "linked_position_id", "INTEGER")
    # Reconciliation tables — dodatkowe kolumny jeśli tabela istnieje ale jest stara
    _ensure_column("reconciliation_runs", "trigger", "VARCHAR(40) DEFAULT 'scheduled'")
    _ensure_column("reconciliation_runs", "repairs_count", "INTEGER DEFAULT 0")
    _ensure_column("reconciliation_runs", "manual_trades_detected", "INTEGER DEFAULT 0")
    _ensure_column(
        "reconciliation_events", "source_of_truth", "VARCHAR(20) DEFAULT 'binance'"
    )
    _ensure_column("reconciliation_events", "action_taken", "VARCHAR(60)")
    _ensure_column(
        "manual_trade_detections", "detection_source", "VARCHAR(40) DEFAULT 'reconcile'"
    )


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
        "incidents",
        "decision_traces",
        "cost_ledger",
        "user_expectations",
        "decision_audit",
        "goal_assessments",
        "reconciliation_runs",
        "reconciliation_events",
        "manual_trade_detections",
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
        "decision_audit",
        "goal_assessments",
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
            db.query(ConfigSnapshot).update(
                {ConfigSnapshot.is_current: False}, synchronize_session=False
            )
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
        db.query(ConfigSnapshot).update(
            {ConfigSnapshot.is_current: False}, synchronize_session=False
        )

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
    rows = (
        db.query(ConfigSnapshot)
        .order_by(ConfigSnapshot.created_at.desc(), ConfigSnapshot.id.desc())
        .all()
    )
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
        timestamp=timestamp or utc_now_naive(),
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
        timestamp=timestamp or utc_now_naive(),
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
