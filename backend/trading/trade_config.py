"""
trade_config.py — Centralny config silnika handlu Binance Spot.

Jeden config dict obsługuje wszystkie moduły trading/*.
Pobiera wartości z DB (RuntimeSetting) i .env w deterministycznej kolejności.

Priorytety (malejąco):
  1. DB RuntimeSetting (operator może nadpisać w runtime)
  2. .env (deployment config)
  3. Hardcoded defaults (bezpieczne minimalne wartości)

Użycie:
    from backend.trading.trade_config import get_trade_config
    cfg = get_trade_config(db)
    max_pos = cfg.max_open_positions
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key, "")
    try:
        return float(v) if v.strip() else default
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key, "")
    try:
        return int(v) if v.strip() else default
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _env_str(key: str, default: str) -> str:
    return os.getenv(key, default).strip() or default


@dataclass
class TradeConfig:
    # ── Tryb / Mode ────────────────────────────────────────────────────
    trading_mode: str = "demo"              # demo | live
    allow_live_trading: bool = False
    demo_trading_enabled: bool = True
    paper_mode: bool = False                # dry-run: generuje sygnały, NIE składa zleceń
    execution_enabled: bool = True          # global kill switch

    # ── Universe symboli ───────────────────────────────────────────────
    quote_currency_mode: str = "USDC"       # USDC | EUR | BOTH
    allowed_quotes: list = field(default_factory=lambda: ["USDC", "EUR"])
    max_symbol_scan_per_cycle: int = 200    # ile symboli na jeden cykl
    enable_dynamic_universe: bool = True    # używaj exchangeInfo zamiast watchlisty

    # ── Parametry kosztów (obowiązkowe w każdym obliczeniu edge) ────────
    maker_fee_pct: float = 0.075            # % (z BNB discount)
    taker_fee_pct: float = 0.100            # %
    slippage_bps: float = 5.0               # basis points
    spread_buffer_bps: float = 3.0          # basis points
    max_spread_bps: float = 60.0            # twardy limit spreadu (bps)
    max_slippage_bps: float = 50.0          # guard poślizgu (bps)
    min_spread_pct_to_allow_entry: float = 0.0   # jeśli 0 → nie blokuj po spread
    max_allowed_spread_pct: float = 0.30    # spread > 0.3% = zbyt szeroki, blokuj

    # ── Min edge / expected value gate ────────────────────────────────
    min_net_edge_pct: float = 0.60          # min expected move netto po kosztach (%)
    min_expected_rr: float = 1.8            # min risk:reward ratio
    min_edge_multiplier: float = 2.5        # koszt × multiplier = minimalny edge

    # ── Market health gate (LIVE) ─────────────────────────────────────
    market_data_max_age_sec: int = 240
    require_ws_for_live: bool = True
    market_health_error_window_min: int = 15
    market_health_reduce_only_error_count: int = 6
    market_health_no_trade_error_count: int = 15
    market_health_reduce_only_on_stale_data: bool = True
    market_health_alert_cooldown_sec: int = 600

    # ── Position sizing ────────────────────────────────────────────────
    risk_per_trade_pct: float = 0.5         # % equity na trade
    max_position_pct_equity: float = 5.0    # max % equity w jednej pozycji
    atr_stop_multiplier: float = 2.0        # ATR × mult = stop loss distance
    atr_take_multiplier: float = 3.5        # ATR × mult = take profit distance
    atr_trail_multiplier: float = 1.5       # ATR × mult = trailing stop distance
    min_order_notional: float = 10.0        # min USD/EUR wartość zlecenia (exchange)
    min_buy_notional: float = 60.0          # min wejście (nasza polityka)

    # ── Limity ryzyka (twarde) ─────────────────────────────────────────
    max_open_positions: int = 5
    max_trades_per_day: int = 20
    max_daily_drawdown_pct: float = 3.0     # % equity → global stop
    max_weekly_drawdown_pct: float = 7.0    # % equity → tygodniowy stop
    max_losing_streak: int = 3              # N strat z rzędu → cooldown
    cooldown_after_loss_streak_min: int = 60  # minut
    cooldown_after_single_loss_min: int = 0   # 0 = wyłączone
    max_total_exposure_pct: float = 80.0    # % equity zainwestowane łącznie
    max_exposure_per_symbol_pct: float = 10.0  # % equity na jeden symbol

    # ── Sygnał — progi ─────────────────────────────────────────────────
    min_signal_confidence: float = 0.65
    min_entry_score: float = 0.60           # złożony score (trend+momentum+volume+regime)
    require_volume_confirmation: bool = True
    volume_ratio_min: float = 1.2           # wolumen / średni_wolumen
    min_liquidity_score: float = 0.40       # 0.0–1.0
    min_quote_volume_trade: float = 75000.0 # minimalny 24h quoteVolume do realnego trade
    use_dynamic_volume_threshold: bool = True
    min_depth_to_order_ratio: float = 8.0   # minimalna głębokość ask vs min buy notional
    orderbook_depth_bps: float = 20.0       # ile bps wokół mid liczyć depth
    require_htf_trend_agreement: bool = True  # 1h musi potwierdzać 4h
    htf_timeframe: str = "4h"
    entry_timeframe: str = "1h"
    fast_timeframe: str = "15m"

    # ── Zarządzanie pozycją ───────────────────────────────────────────
    enable_trailing_stop: bool = True
    enable_partial_tp: bool = True
    partial_tp_fraction: float = 0.25       # zamknij 25% przy pierwszym TP
    max_partial_tp_count: int = 2
    break_even_after_partial_tp: bool = True

    # ── OCO / zlecenia zabezpieczające ────────────────────────────────
    use_oco_for_protection: bool = True     # jeśli symbol ma ocoAllowed
    oco_fallback_to_two_orders: bool = True  # jeśli OCO niedostępne
    tp_order_type: str = "LIMIT"
    sl_order_type: str = "STOP_LOSS_LIMIT"

    # ── Reconcile / recovery ──────────────────────────────────────────
    reconcile_interval_sec: int = 120
    orphan_order_ttl_sec: int = 300         # EXCHANGE_SUBMITTED bez odpowiedzi
    sync_pending_grace_sec: int = 45        # ignoruj mismatch gdy pending

    # ── Misc ──────────────────────────────────────────────────────────
    max_signal_age_sec: int = 3600
    pending_order_cooldown_sec: int = 300
    binance_rejection_cooldown_sec: int = 600
    inflight_ttl_sec: int = 120


def _db_get(db: Optional[Session], key: str, default: Any = None) -> Any:
    """Pobierz wartość RuntimeSetting z DB lub zwróć default."""
    if db is None:
        return default
    try:
        from backend.database import RuntimeSetting
        row = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
        if row and row.value is not None:
            return row.value
    except Exception:
        pass
    return default


def _merge(db_val: Any, env_val: Any, default: Any) -> Any:
    """Wybierz wartość: DB > env > default."""
    if db_val is not None:
        return db_val
    if env_val is not None:
        return env_val
    return default


def get_trade_config(db: Optional[Session] = None) -> TradeConfig:
    """
    Zbuduj TradeConfig z DB (RuntimeSetting) i .env.

    Kolejność priorytetów: DB > .env > hardcoded default.
    Wszystkie klucze DB są prefiksowane 'trade_' (np. 'trade_max_open_positions').
    """

    _COMPAT_DB_ALIASES = {
        # Runtime control-plane: min_symbol_net_expectancy (% netto po kosztach)
        "min_net_edge_pct": "min_symbol_net_expectancy",
    }

    def _get(key: str, env_key: str, default: Any, cast=None) -> Any:
        db_v = _db_get(db, f"trade_{key}")
        if db_v is None:
            alias = _COMPAT_DB_ALIASES.get(key)
            if alias:
                db_v = _db_get(db, alias)
        env_v = os.getenv(env_key)
        val = _merge(db_v, env_v, default)
        if cast and val is not None:
            try:
                return cast(val)
            except (ValueError, TypeError):
                return default
        return val

    cfg = TradeConfig(
        # Mode
        trading_mode=_get("trading_mode", "TRADING_MODE", "demo", str),
        allow_live_trading=_get("allow_live_trading", "ALLOW_LIVE_TRADING", False, lambda v: str(v).lower() in ("1","true","yes","on")),
        demo_trading_enabled=_get("demo_trading_enabled", "DEMO_TRADING_ENABLED", True, lambda v: str(v).lower() in ("1","true","yes","on")),
        paper_mode=_get("paper_mode", "PAPER_MODE", False, lambda v: str(v).lower() in ("1","true","yes","on")),
        execution_enabled=_get("execution_enabled", "EXECUTION_ENABLED", True, lambda v: str(v).lower() not in ("0","false","no","off")),

        # Universe
        quote_currency_mode=_get("quote_currency_mode", "QUOTE_CURRENCY_MODE", "USDC", str),
        allowed_quotes=[q.strip().upper() for q in _get("allowed_quotes", "ALLOWED_QUOTES", "USDC,EUR", str).split(",") if q.strip()],
        max_symbol_scan_per_cycle=_get("max_symbol_scan_per_cycle", "MAX_SYMBOL_SCAN_PER_CYCLE", 200, int),
        enable_dynamic_universe=_get("enable_dynamic_universe", "ENABLE_DYNAMIC_UNIVERSE", True, lambda v: str(v).lower() not in ("0","false","no","off")),

        # Koszty
        maker_fee_pct=_get("maker_fee_pct", "MAKER_FEE_PCT", 0.075, float),
        taker_fee_pct=_get("taker_fee_pct", "TAKER_FEE_PCT", 0.100, float),
        slippage_bps=_get("slippage_bps", "SLIPPAGE_BPS", 5.0, float),
        spread_buffer_bps=_get("spread_buffer_bps", "SPREAD_BUFFER_BPS", 3.0, float),
        max_spread_bps=_get("max_spread_bps", "MAX_SPREAD_BPS", 60.0, float),
        max_slippage_bps=_get("max_slippage_bps", "MAX_SLIPPAGE_BPS", 50.0, float),
        max_allowed_spread_pct=_get("max_allowed_spread_pct", "MAX_ALLOWED_SPREAD_PCT", 0.30, float),
        min_net_edge_pct=_get("min_net_edge_pct", "MIN_NET_EDGE_PCT", 0.60, float),
        min_expected_rr=_get("min_expected_rr", "MIN_EXPECTED_RR", 1.8, float),
        min_edge_multiplier=_get("min_edge_multiplier", "MIN_EDGE_MULTIPLIER", 2.5, float),
        market_data_max_age_sec=_get("market_data_max_age_sec", "MARKET_DATA_MAX_AGE_SEC", 240, int),
        require_ws_for_live=_get("require_ws_for_live", "REQUIRE_WS_FOR_LIVE", True, lambda v: str(v).lower() not in ("0", "false", "no", "off")),
        market_health_error_window_min=_get("market_health_error_window_min", "MARKET_HEALTH_ERROR_WINDOW_MIN", 15, int),
        market_health_reduce_only_error_count=_get("market_health_reduce_only_error_count", "MARKET_HEALTH_REDUCE_ONLY_ERROR_COUNT", 6, int),
        market_health_no_trade_error_count=_get("market_health_no_trade_error_count", "MARKET_HEALTH_NO_TRADE_ERROR_COUNT", 15, int),
        market_health_reduce_only_on_stale_data=_get("market_health_reduce_only_on_stale_data", "MARKET_HEALTH_REDUCE_ONLY_ON_STALE_DATA", True, lambda v: str(v).lower() not in ("0", "false", "no", "off")),
        market_health_alert_cooldown_sec=_get("market_health_alert_cooldown_sec", "MARKET_HEALTH_ALERT_COOLDOWN_SEC", 600, int),

        # Position sizing
        risk_per_trade_pct=_get("risk_per_trade_pct", "RISK_PER_TRADE_PCT", 0.5, float),
        max_position_pct_equity=_get("max_position_pct_equity", "MAX_POSITION_PCT_EQUITY", 5.0, float),
        atr_stop_multiplier=_get("atr_stop_multiplier", "ATR_STOP_MULT", 2.0, float),
        atr_take_multiplier=_get("atr_take_multiplier", "ATR_TAKE_MULT", 3.5, float),
        atr_trail_multiplier=_get("atr_trail_multiplier", "ATR_TRAIL_MULT", 1.5, float),
        min_order_notional=_get("min_order_notional", "MIN_ORDER_NOTIONAL", 10.0, float),
        min_buy_notional=_get("min_buy_notional", "MIN_BUY_NOTIONAL", 60.0, float),

        # Limity ryzyka
        max_open_positions=_get("max_open_positions", "MAX_OPEN_POSITIONS", 5, int),
        max_trades_per_day=_get("max_trades_per_day", "MAX_TRADES_PER_DAY", 20, int),
        max_daily_drawdown_pct=_get("max_daily_drawdown_pct", "MAX_DAILY_DRAWDOWN_PCT", 3.0, float),
        max_weekly_drawdown_pct=_get("max_weekly_drawdown_pct", "MAX_WEEKLY_DRAWDOWN_PCT", 7.0, float),
        max_losing_streak=_get("max_losing_streak", "MAX_LOSING_STREAK", 3, int),
        cooldown_after_loss_streak_min=_get("cooldown_after_loss_streak_min", "COOLDOWN_AFTER_LOSS_STREAK_MIN", 60, int),
        cooldown_after_single_loss_min=_get("cooldown_after_single_loss_min", "COOLDOWN_AFTER_SINGLE_LOSS_MIN", 0, int),
        max_total_exposure_pct=_get("max_total_exposure_pct", "MAX_TOTAL_EXPOSURE_PCT", 80.0, float),
        max_exposure_per_symbol_pct=_get("max_exposure_per_symbol_pct", "MAX_EXPOSURE_PER_SYMBOL_PCT", 10.0, float),

        # Sygnał
        min_signal_confidence=_get("min_signal_confidence", "MIN_SIGNAL_CONFIDENCE", 0.65, float),
        min_entry_score=_get("min_entry_score", "MIN_ENTRY_SCORE", 0.60, float),
        require_volume_confirmation=_get("require_volume_confirmation", "REQUIRE_VOLUME_CONFIRMATION", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        volume_ratio_min=_get("volume_ratio_min", "VOLUME_RATIO_MIN", 1.2, float),
        min_liquidity_score=_get("min_liquidity_score", "MIN_LIQUIDITY_SCORE", 0.40, float),
        min_quote_volume_trade=_get("min_quote_volume_trade", "MIN_QUOTE_VOLUME_TRADE", 75000.0, float),
        use_dynamic_volume_threshold=_get("use_dynamic_volume_threshold", "USE_DYNAMIC_VOLUME_THRESHOLD", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        min_depth_to_order_ratio=_get("min_depth_to_order_ratio", "MIN_DEPTH_TO_ORDER_RATIO", 8.0, float),
        orderbook_depth_bps=_get("orderbook_depth_bps", "ORDERBOOK_DEPTH_BPS", 20.0, float),
        require_htf_trend_agreement=_get("require_htf_trend_agreement", "REQUIRE_HTF_TREND_AGREEMENT", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        htf_timeframe=_get("htf_timeframe", "HTF_TIMEFRAME", "4h", str),
        entry_timeframe=_get("entry_timeframe", "ENTRY_TIMEFRAME", "1h", str),
        fast_timeframe=_get("fast_timeframe", "FAST_TIMEFRAME", "15m", str),

        # Zarządzanie pozycją
        enable_trailing_stop=_get("enable_trailing_stop", "ENABLE_TRAILING_STOP", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        enable_partial_tp=_get("enable_partial_tp", "ENABLE_PARTIAL_TP", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        partial_tp_fraction=_get("partial_tp_fraction", "PARTIAL_TP_FRACTION", 0.25, float),
        break_even_after_partial_tp=_get("break_even_after_partial_tp", "BREAK_EVEN_AFTER_PARTIAL_TP", True, lambda v: str(v).lower() not in ("0","false","no","off")),

        # OCO
        use_oco_for_protection=_get("use_oco_for_protection", "USE_OCO_FOR_PROTECTION", True, lambda v: str(v).lower() not in ("0","false","no","off")),
        oco_fallback_to_two_orders=_get("oco_fallback_to_two_orders", "OCO_FALLBACK_TO_TWO_ORDERS", True, lambda v: str(v).lower() not in ("0","false","no","off")),

        # Reconcile
        reconcile_interval_sec=_get("reconcile_interval_sec", "RECONCILE_INTERVAL_SEC", 120, int),
        orphan_order_ttl_sec=_get("orphan_order_ttl_sec", "ORPHAN_ORDER_TTL_SEC", 300, int),
        sync_pending_grace_sec=_get("sync_pending_grace_sec", "SYNC_PENDING_GRACE_SEC", 45, int),

        # Misc
        max_signal_age_sec=_get("max_signal_age_sec", "MAX_SIGNAL_AGE_SEC", 3600, int),
        pending_order_cooldown_sec=_get("pending_order_cooldown_sec", "PENDING_ORDER_COOLDOWN_SEC", 300, int),
        binance_rejection_cooldown_sec=_get("binance_rejection_cooldown_sec", "BINANCE_REJECTION_COOLDOWN_SEC", 600, int),
        inflight_ttl_sec=_get("inflight_ttl_sec", "INFLIGHT_TTL_SEC", 120, int),
    )
    return cfg


def total_entry_cost_pct(cfg: TradeConfig) -> float:
    """Łączny koszt wejścia (%) = taker fee + slippage + spread."""
    return cfg.taker_fee_pct / 100.0 + cfg.slippage_bps / 10000.0 + cfg.spread_buffer_bps / 10000.0


def total_round_trip_cost_pct(cfg: TradeConfig) -> float:
    """Łączny koszt transakcji (wejście + wyjście) w %."""
    return total_entry_cost_pct(cfg) * 2


def min_required_move_pct(cfg: TradeConfig) -> float:
    """Minimalny ruch ceny (%) żeby trade był opłacalny po wszystkich kosztach."""
    return total_round_trip_cost_pct(cfg) + cfg.min_net_edge_pct / 100.0
