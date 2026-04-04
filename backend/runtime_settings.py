"""
Central runtime configuration and control-plane validation.

DB overrides remain optional: if a key is not present in DB, the system falls back to ENV defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from sqlalchemy.orm import Session

from backend.database import RuntimeSetting, get_config_snapshot, save_config_snapshot, utc_now_naive
from backend.system_logger import log_to_db


_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}
_LIVE_GUARD_KEYS = {
    "trading_mode",
    "allow_live_trading",
    "risk_per_trade",
    "max_open_positions",
    "max_daily_drawdown",
    "max_weekly_drawdown",
    "maker_fee_rate",
    "taker_fee_rate",
    "slippage_bps",
    "spread_buffer_bps",
    "min_edge_multiplier",
    "min_order_notional",
}


class RuntimeSettingsError(ValueError):
    """Validation or guard-rail error for runtime settings."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SettingSpec:
    key: str
    section: str
    parser: Callable[[Any], Any]
    serializer: Callable[[Any], str]
    default: Any
    env_var: Optional[str] = None
    validators: tuple[Callable[[Any], None], ...] = ()
    clearable: bool = False


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeSettingsError(message)


def _parse_bool(raw: Any) -> Optional[bool]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    v = str(raw).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def _parse_required_bool(raw: Any) -> bool:
    parsed = _parse_bool(raw)
    if parsed is None:
        raise RuntimeSettingsError(f"Invalid boolean value: {raw!r}")
    return parsed


def _parse_positive_float(raw: Any) -> float:
    try:
        value = float(raw)
    except Exception as exc:
        raise RuntimeSettingsError(f"Invalid float value: {raw!r}") from exc
    return value


def _parse_positive_int(raw: Any) -> int:
    try:
        value = int(raw)
    except Exception as exc:
        raise RuntimeSettingsError(f"Invalid integer value: {raw!r}") from exc
    return value


def _parse_mode(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value not in {"paper", "demo", "live"}:
        raise RuntimeSettingsError("trading_mode must be one of: paper, demo, live")
    return value


def _parse_aggressiveness(raw: Any) -> str:
    value = str(raw or "balanced").strip().lower()
    if value not in {"safe", "balanced", "aggressive"}:
        raise RuntimeSettingsError("trading_aggressiveness must be one of: safe, balanced, aggressive")
    return value


# Profile agresywności — nadpisują domyślne progi w collectorze
AGGRESSIVENESS_PROFILES = {
    "safe": {
        "max_open_positions": 2,
        "demo_min_signal_confidence": 0.70,
        "demo_min_entry_score": 7.0,
        "pending_order_cooldown_seconds": 900,
        "risk_per_trade": 0.005,
        "demo_allow_soft_buy_entries": False,
    },
    "balanced": {
        "max_open_positions": 3,
        "demo_min_signal_confidence": 0.55,
        "demo_min_entry_score": 5.5,
        "pending_order_cooldown_seconds": 300,
        "risk_per_trade": 0.01,
        "demo_allow_soft_buy_entries": True,
    },
    "aggressive": {
        "max_open_positions": 5,
        "demo_min_signal_confidence": 0.50,
        "demo_min_entry_score": 4.5,
        "pending_order_cooldown_seconds": 300,
        "risk_per_trade": 0.02,
        "demo_allow_soft_buy_entries": True,
    },
}


def _parse_text(raw: Any) -> str:
    value = str(raw or "").strip()
    return value


def parse_watchlist(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = [s.strip() for s in str(raw or "").split(",") if s.strip()]
    wl: list[str] = []
    for item in items:
        sym = (item or "").strip().replace(" ", "").replace("/", "").replace("-", "").upper()
        if sym and sym not in wl:
            wl.append(sym)
    return wl


def _parse_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(s).strip() for s in raw if str(s).strip()]
    else:
        items = [s.strip() for s in str(raw or "").split(",") if s.strip()]
    values: list[str] = []
    for item in items:
        normalized = item.strip().lower()
        if normalized and normalized not in values:
            values.append(normalized)
    return values


def _serialize_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _serialize_float(value: Any) -> str:
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


def _serialize_int(value: Any) -> str:
    return str(int(value))


def _serialize_text(value: Any) -> str:
    return str(value or "").strip()


def _serialize_str_list(value: Any) -> str:
    return ",".join(_parse_str_list(value))


def _serialize_watchlist(value: Any) -> str:
    return ",".join(parse_watchlist(value))


def _validate_positive(name: str) -> Callable[[Any], None]:
    def _validator(value: Any) -> None:
        _require(float(value) > 0, f"{name} must be > 0")

    return _validator


def _validate_non_negative(name: str) -> Callable[[Any], None]:
    def _validator(value: Any) -> None:
        _require(float(value) >= 0, f"{name} must be >= 0")

    return _validator


def _validate_probability(name: str) -> Callable[[Any], None]:
    def _validator(value: Any) -> None:
        _require(0 < float(value) <= 1, f"{name} must be in range (0, 1]")

    return _validator


_SETTINGS: Dict[str, SettingSpec] = {
    "trading_mode": SettingSpec(
        key="trading_mode",
        section="mode",
        parser=_parse_mode,
        serializer=_serialize_text,
        default="demo",
        env_var="TRADING_MODE",
    ),
    "allow_live_trading": SettingSpec(
        key="allow_live_trading",
        section="mode",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=False,
        env_var="ALLOW_LIVE_TRADING",
    ),
    "demo_trading_enabled": SettingSpec(
        key="demo_trading_enabled",
        section="mode",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,
        env_var="DEMO_TRADING_ENABLED",
    ),
    "trading_aggressiveness": SettingSpec(
        key="trading_aggressiveness",
        section="mode",
        parser=_parse_aggressiveness,
        serializer=_serialize_text,
        default="balanced",
        env_var="TRADING_AGGRESSIVENESS",
    ),
    "ws_enabled": SettingSpec(
        key="ws_enabled",
        section="data",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,
        env_var="WS_ENABLED",
    ),
    "max_certainty_mode": SettingSpec(
        key="max_certainty_mode",
        section="ai",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=False,
        env_var="MAX_CERTAINTY_MODE",
    ),
    "watchlist": SettingSpec(
        key="watchlist",
        section="trading",
        parser=parse_watchlist,
        serializer=_serialize_watchlist,
        default=[],
        env_var="WATCHLIST",
        clearable=True,
    ),
    "enabled_strategies": SettingSpec(
        key="enabled_strategies",
        section="trading",
        parser=_parse_str_list,
        serializer=_serialize_str_list,
        default=["default"],
        env_var="ENABLED_STRATEGIES",
        clearable=True,
    ),
    "max_open_positions": SettingSpec(
        key="max_open_positions",
        section="trading",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=5,
        env_var="MAX_OPEN_POSITIONS",
        validators=(_validate_positive("max_open_positions"),),
    ),
    "max_trades_per_day": SettingSpec(
        key="max_trades_per_day",
        section="trading",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=20,
        env_var="MAX_TRADES_PER_DAY",
        validators=(_validate_positive("max_trades_per_day"),),
    ),
    "max_trades_per_hour_per_symbol": SettingSpec(
        key="max_trades_per_hour_per_symbol",
        section="trading",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=2,
        env_var="MAX_TRADES_PER_HOUR_PER_SYMBOL",
        validators=(_validate_positive("max_trades_per_hour_per_symbol"),),
    ),
    "max_total_exposure_ratio": SettingSpec(
        key="max_total_exposure_ratio",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.8,
        env_var="MAX_TOTAL_EXPOSURE_RATIO",
        validators=(_validate_probability("max_total_exposure_ratio"),),
    ),
    "max_symbol_exposure_ratio": SettingSpec(
        key="max_symbol_exposure_ratio",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.35,
        env_var="MAX_SYMBOL_EXPOSURE_RATIO",
        validators=(_validate_probability("max_symbol_exposure_ratio"),),
    ),
    "loss_streak_limit": SettingSpec(
        key="loss_streak_limit",
        section="risk",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=3,
        env_var="LOSS_STREAK_LIMIT",
        validators=(_validate_positive("loss_streak_limit"),),
    ),
    "cooldown_after_loss_streak_minutes": SettingSpec(
        key="cooldown_after_loss_streak_minutes",
        section="risk",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=15,  # DEMO: 15 min zamiast 60 — bot nie stoi godzinami
        env_var="COOLDOWN_AFTER_LOSS_STREAK_MINUTES",
        validators=(_validate_positive("cooldown_after_loss_streak_minutes"),),
    ),
    "risk_per_trade": SettingSpec(
        key="risk_per_trade",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.01,
        env_var="RISK_PER_TRADE",
        validators=(_validate_probability("risk_per_trade"),),
    ),
    "max_daily_drawdown": SettingSpec(
        key="max_daily_drawdown",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.03,
        env_var="MAX_DAILY_DRAWDOWN",
        validators=(_validate_probability("max_daily_drawdown"),),
    ),
    "max_weekly_drawdown": SettingSpec(
        key="max_weekly_drawdown",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.07,
        env_var="MAX_WEEKLY_DRAWDOWN",
        validators=(_validate_probability("max_weekly_drawdown"),),
    ),
    "kill_switch_enabled": SettingSpec(
        key="kill_switch_enabled",
        section="risk",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,
        env_var="KILL_SWITCH_ENABLED",
    ),
    "max_cost_leakage_ratio": SettingSpec(
        key="max_cost_leakage_ratio",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.5,
        env_var="MAX_COST_LEAKAGE_RATIO",
        validators=(_validate_non_negative("max_cost_leakage_ratio"),),
    ),
    "min_symbol_net_expectancy": SettingSpec(
        key="min_symbol_net_expectancy",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.0,
        env_var="MIN_SYMBOL_NET_EXPECTANCY",
        validators=(_validate_non_negative("min_symbol_net_expectancy"),),
    ),
    "maker_fee_rate": SettingSpec(
        key="maker_fee_rate",
        section="costs",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.001,
        env_var="MAKER_FEE_RATE",
        validators=(_validate_non_negative("maker_fee_rate"),),
    ),
    "taker_fee_rate": SettingSpec(
        key="taker_fee_rate",
        section="costs",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.001,
        env_var="TAKER_FEE_RATE",
        validators=(_validate_non_negative("taker_fee_rate"),),
    ),
    "slippage_bps": SettingSpec(
        key="slippage_bps",
        section="costs",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=5.0,
        env_var="SLIPPAGE_BPS",
        validators=(_validate_non_negative("slippage_bps"),),
    ),
    "spread_buffer_bps": SettingSpec(
        key="spread_buffer_bps",
        section="costs",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=3.0,
        env_var="SPREAD_BUFFER_BPS",
        validators=(_validate_non_negative("spread_buffer_bps"),),
    ),
    "min_edge_multiplier": SettingSpec(
        key="min_edge_multiplier",
        section="costs",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=2.5,
        env_var="MIN_EDGE_MULTIPLIER",
        validators=(_validate_positive("min_edge_multiplier"),),
    ),
    "min_expected_rr": SettingSpec(
        key="min_expected_rr",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=1.5,
        env_var="MIN_EXPECTED_RR",
        validators=(_validate_positive("min_expected_rr"),),
    ),
    "min_order_notional": SettingSpec(
        key="min_order_notional",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=25.0,
        env_var="MIN_ORDER_NOTIONAL",
        validators=(_validate_positive("min_order_notional"),),
    ),
    # --- Trading core: ATR / TP-SL ---
    "atr_stop_mult": SettingSpec(
        key="atr_stop_mult",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=1.3,
        env_var="ATR_STOP_MULT",
        validators=(_validate_positive("atr_stop_mult"),),
    ),
    "atr_take_mult": SettingSpec(
        key="atr_take_mult",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=2.2,
        env_var="ATR_TAKE_MULT",
        validators=(_validate_positive("atr_take_mult"),),
    ),
    "atr_trail_mult": SettingSpec(
        key="atr_trail_mult",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=1.0,
        env_var="ATR_TRAIL_MULT",
        validators=(_validate_positive("atr_trail_mult"),),
    ),
    # --- Konfigurowalne progi RSI i momentum (odblokowanie tradingu) ---
    "rsi_buy_gate_max": SettingSpec(
        key="rsi_buy_gate_max",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.0,  # 0.0 = wyłączone (domyślny cap 55); > 0 = podłoga dla progu RSI BUY
        env_var="RSI_BUY_GATE_MAX",
        validators=(_validate_non_negative("rsi_buy_gate_max"),),
    ),
    "min_volume_ratio": SettingSpec(
        key="min_volume_ratio",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.9,  # 0.9 = domyślny próg volume ratio; 0.0 = wyłączone
        env_var="MIN_VOLUME_RATIO",
        validators=(_validate_non_negative("min_volume_ratio"),),
    ),
    "min_adx_for_entry": SettingSpec(
        key="min_adx_for_entry",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=18.0,
        env_var="MIN_ADX_FOR_ENTRY",
        validators=(_validate_non_negative("min_adx_for_entry"),),
    ),
    # --- Trading core: extreme entry filter ---
    "extreme_range_margin_pct": SettingSpec(
        key="extreme_range_margin_pct",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.02,
        env_var="EXTREME_RANGE_MARGIN_PCT",
        validators=(_validate_non_negative("extreme_range_margin_pct"),),
    ),
    "extreme_min_confidence": SettingSpec(
        key="extreme_min_confidence",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.85,
        env_var="EXTREME_MIN_CONFIDENCE",
        validators=(_validate_probability("extreme_min_confidence"),),
    ),
    "extreme_min_rating": SettingSpec(
        key="extreme_min_rating",
        section="execution",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=4,
        env_var="EXTREME_MIN_RATING",
        validators=(_validate_positive("extreme_min_rating"),),
    ),
    # --- Trading core: signal & sizing ---
    "demo_min_signal_confidence": SettingSpec(
        key="demo_min_signal_confidence",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.55,  # DEMO jest agresywny — obniżone z 0.75
        env_var="DEMO_MIN_SIGNAL_CONFIDENCE",
        validators=(_validate_probability("demo_min_signal_confidence"),),
    ),
    "demo_max_signal_age_seconds": SettingSpec(
        key="demo_max_signal_age_seconds",
        section="execution",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=3600,
        env_var="DEMO_MAX_SIGNAL_AGE_SECONDS",
        validators=(_validate_positive("demo_max_signal_age_seconds"),),
    ),
    "demo_order_qty": SettingSpec(
        key="demo_order_qty",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.01,
        env_var="DEMO_ORDER_QTY",
        validators=(_validate_positive("demo_order_qty"),),
    ),
    "demo_max_position_qty": SettingSpec(
        key="demo_max_position_qty",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=1.0,
        env_var="DEMO_MAX_POSITION_QTY",
        validators=(_validate_positive("demo_max_position_qty"),),
    ),
    "demo_min_position_qty": SettingSpec(
        key="demo_min_position_qty",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=0.001,
        env_var="DEMO_MIN_POSITION_QTY",
        validators=(_validate_positive("demo_min_position_qty"),),
    ),
    # --- Trading core: cooldowns & crash ---
    "pending_order_cooldown_seconds": SettingSpec(
        key="pending_order_cooldown_seconds",
        section="execution",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=300,  # 5 min — obniżone z 3600; dla DEMO szybka rotacja
        env_var="PENDING_ORDER_COOLDOWN_SECONDS",
        validators=(_validate_positive("pending_order_cooldown_seconds"),),
    ),
    # --- DEMO-specific controls ---
    "demo_require_manual_confirm": SettingSpec(
        key="demo_require_manual_confirm",
        section="execution",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=False,  # False = auto-execute; True = wymaga /confirm w Telegramie
        env_var="DEMO_REQUIRE_MANUAL_CONFIRM",
    ),
    "demo_allow_soft_buy_entries": SettingSpec(
        key="demo_allow_soft_buy_entries",
        section="execution",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,  # ROZWAŻ_ZAKUP traktuje jak akcjonalny kandydat
        env_var="DEMO_ALLOW_SOFT_BUY_ENTRIES",
    ),
    "demo_use_heuristic_ranges_fallback": SettingSpec(
        key="demo_use_heuristic_ranges_fallback",
        section="execution",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,  # gdy brak AI ranges, użyj ATR-based heurystyki
        env_var="DEMO_USE_HEURISTIC_RANGES_FALLBACK",
    ),
    "demo_min_entry_score": SettingSpec(
        key="demo_min_entry_score",
        section="execution",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=5.5,
        env_var="DEMO_MIN_ENTRY_SCORE",
        validators=(_validate_positive("demo_min_entry_score"),),
    ),
    "max_ai_insights_age_seconds": SettingSpec(
        key="max_ai_insights_age_seconds",
        section="ai",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=7200,
        env_var="MAX_AI_INSIGHTS_AGE_SECONDS",
        validators=(_validate_positive("max_ai_insights_age_seconds"),),
    ),
    "crash_window_minutes": SettingSpec(
        key="crash_window_minutes",
        section="risk",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=60,
        env_var="CRASH_WINDOW_MINUTES",
        validators=(_validate_positive("crash_window_minutes"),),
    ),
    "crash_drop_percent": SettingSpec(
        key="crash_drop_percent",
        section="risk",
        parser=_parse_positive_float,
        serializer=_serialize_float,
        default=6.0,
        env_var="CRASH_DROP_PERCENT",
        validators=(_validate_positive("crash_drop_percent"),),
    ),
    "crash_cooldown_seconds": SettingSpec(
        key="crash_cooldown_seconds",
        section="risk",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=7200,
        env_var="CRASH_COOLDOWN_SECONDS",
        validators=(_validate_positive("crash_cooldown_seconds"),),
    ),
    "ai_enabled": SettingSpec(
        key="ai_enabled",
        section="ai",
        parser=_parse_required_bool,
        serializer=_serialize_bool,
        default=True,
        env_var="AI_ENABLED",
    ),
    "market_data_timeout_seconds": SettingSpec(
        key="market_data_timeout_seconds",
        section="data",
        parser=_parse_positive_int,
        serializer=_serialize_int,
        default=30,
        env_var="MARKET_DATA_TIMEOUT_SECONDS",
        validators=(_validate_positive("market_data_timeout_seconds"),),
    ),
    "log_level": SettingSpec(
        key="log_level",
        section="logging",
        parser=lambda raw: str(raw or "INFO").strip().upper(),
        serializer=_serialize_text,
        default="INFO",
        env_var="LOG_LEVEL",
    ),
    # --- Symbol tiers: konfiguracja per-tier overrides ---
    "symbol_tiers": SettingSpec(
        key="symbol_tiers",
        section="trading",
        parser=lambda raw: json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {}),
        serializer=lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v or "{}"),
        default={
            "CORE": {
                "symbols": ["BTCEUR", "BTCUSDC", "ETHEUR", "ETHUSDC", "SOLEUR", "SOLUSDC", "BNBEUR", "BNBUSDC"],
                "min_confidence_add": 0.0,
                "min_edge_multiplier_add": 0.0,
                "risk_scale": 1.0,
                "max_trades_per_day_per_symbol": 10,
            },
            "ALTCOIN": {
                "symbols": ["ETCUSDC", "SHIBEUR", "SHIBUSDC", "SXTUSDC"],
                "min_confidence_add": 0.05,
                "min_edge_multiplier_add": 0.5,
                "risk_scale": 0.7,
                "max_trades_per_day_per_symbol": 3,
            },
            "SPECULATIVE": {
                "symbols": ["WLFIEUR", "WLFIUSDC"],
                "min_confidence_add": 0.10,
                "min_edge_multiplier_add": 1.0,
                "risk_scale": 0.3,
                "max_trades_per_day_per_symbol": 2,
            },
        },
        env_var="SYMBOL_TIERS",
        clearable=True,
    ),
}


# --- Tier helpers --------------------------------------------------------

_TIER_DEFAULTS = {
    "min_confidence_add": 0.0,
    "min_edge_multiplier_add": 0.0,
    "risk_scale": 1.0,
    "max_trades_per_day_per_symbol": 2,
}


def build_symbol_tier_map(tiers_config: dict) -> Dict[str, dict]:
    """Zbuduj lookup: symbol → tier overrides z konfiguracji tierów."""
    result: Dict[str, dict] = {}
    _HOLD_KEYS = ("hold_mode", "no_auto_exit", "no_new_entries", "target_value_eur")
    for tier_name, tier_data in (tiers_config or {}).items():
        if not isinstance(tier_data, dict):
            continue
        symbols = tier_data.get("symbols", [])
        overrides = {k: tier_data.get(k, v) for k, v in _TIER_DEFAULTS.items()}
        overrides["tier"] = tier_name
        for hk in _HOLD_KEYS:
            if hk in tier_data:
                overrides[hk] = tier_data[hk]
        for sym in symbols:
            sym_norm = str(sym).strip().upper().replace("/", "").replace("-", "")
            if sym_norm:
                result[sym_norm] = overrides
    return result


def get_overrides(db: Session, keys: Iterable[str]) -> Dict[str, str]:
    key_list = [k for k in keys if k]
    if not key_list:
        return {}
    rows = db.query(RuntimeSetting).filter(RuntimeSetting.key.in_(key_list)).all()
    return {r.key: (r.value or "") for r in rows if r and r.key}


def _get_all_overrides(db: Session) -> Dict[str, str]:
    rows = db.query(RuntimeSetting).all()
    return {r.key: (r.value or "") for r in rows if r and r.key}


def _parse_env_value(spec: SettingSpec) -> Any:
    if not spec.env_var:
        return spec.default
    raw = os.getenv(spec.env_var)
    if raw is None or str(raw).strip() == "":
        return spec.default
    return spec.parser(raw)


def _resolve_value(spec: SettingSpec, overrides: Mapping[str, str]) -> Any:
    if spec.key in overrides:
        return spec.parser(overrides.get(spec.key))
    return _parse_env_value(spec)


def _validate_setting_value(spec: SettingSpec, value: Any) -> Any:
    parsed = spec.parser(value)
    for validator in spec.validators:
        validator(parsed)
    return parsed


def _normalize_update(spec: SettingSpec, value: Any) -> Optional[str]:
    if value is None and spec.clearable:
        return None
    parsed = _validate_setting_value(spec, value)
    if spec.clearable and isinstance(parsed, list) and not parsed:
        return None
    return spec.serializer(parsed)


def _cross_validate(config: Dict[str, Any]) -> None:
    _require(
        config["max_trades_per_day"] >= config["max_trades_per_hour_per_symbol"],
        "max_trades_per_day must be >= max_trades_per_hour_per_symbol",
    )
    _require(
        config["maker_fee_rate"] <= 0.05 and config["taker_fee_rate"] <= 0.05,
        "fee rates must be realistic and <= 0.05",
    )
    _require(
        config["max_weekly_drawdown"] >= config["max_daily_drawdown"],
        "max_weekly_drawdown must be >= max_daily_drawdown",
    )
    _require(
        config["min_edge_multiplier"] >= 1.0,
        "min_edge_multiplier must be >= 1.0",
    )
    _require(
        config["min_expected_rr"] >= 1.0,
        "min_expected_rr must be >= 1.0",
    )
    _require(
        config["atr_take_mult"] > config["atr_stop_mult"],
        "atr_take_mult must be > atr_stop_mult (otherwise R:R < 1)",
    )
    if config["trading_mode"] == "live":
        _require(config["allow_live_trading"], "Live mode requires allow_live_trading=true")
        _require(config["kill_switch_enabled"], "Live mode requires kill_switch_enabled=true")
        _require(config["min_edge_multiplier"] >= 2.0, "Live mode requires min_edge_multiplier >= 2.0")
        _require(config["max_open_positions"] <= 10, "Live mode max_open_positions must be <= 10")


def _build_effective_flat_config(overrides: Mapping[str, str]) -> Dict[str, Any]:
    config = {key: _resolve_value(spec, overrides) for key, spec in _SETTINGS.items()}
    _cross_validate(config)
    return config


def _build_sections(config: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    sections: Dict[str, Dict[str, Any]] = {
        "mode": {},
        "trading": {},
        "risk": {},
        "execution": {},
        "costs": {},
        "ai": {},
        "data": {},
        "logging": {},
    }
    for key, spec in _SETTINGS.items():
        sections.setdefault(spec.section, {})[key] = config[key]
    return sections


def _snapshot_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _config_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _snapshot_payload(
    *,
    sections: Mapping[str, Any],
    watchlist: list[str],
    watchlist_source: str,
) -> Dict[str, Any]:
    return {
        "sections": sections,
        "watchlist": list(watchlist),
        "watchlist_source": watchlist_source,
    }


def ensure_runtime_snapshot(
    db: Session,
    *,
    sections: Mapping[str, Any],
    watchlist: list[str],
    watchlist_source: str,
    source: str,
    changed_fields: Optional[Iterable[str]] = None,
    previous_snapshot_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    payload = _snapshot_payload(
        sections=sections,
        watchlist=watchlist,
        watchlist_source=watchlist_source,
    )
    snapshot_id = _snapshot_id(payload)
    config_hash = _config_hash(payload)
    save_config_snapshot(
        db,
        snapshot_id=snapshot_id,
        config_hash=config_hash,
        payload=payload,
        source=source,
        changed_fields=list(changed_fields or []),
        previous_snapshot_id=previous_snapshot_id,
        notes=notes,
        is_current=True,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    snapshot = get_config_snapshot(db, snapshot_id)
    return snapshot or {
        "id": snapshot_id,
        "config_hash": config_hash,
        "payload": payload,
        "source": source,
        "changed_fields": list(changed_fields or []),
        "previous_snapshot_id": previous_snapshot_id,
    }


def watchlist_override(db: Session) -> Optional[list[str]]:
    overrides = get_overrides(db, ["watchlist"])
    if "watchlist" not in overrides:
        return None
    return parse_watchlist(overrides.get("watchlist") or "")


def upsert_overrides(db: Session, updates: Dict[str, Optional[str]]) -> None:
    if not updates:
        return

    keys = [k for k in updates.keys() if k]
    existing = {}
    if keys:
        rows = db.query(RuntimeSetting).filter(RuntimeSetting.key.in_(keys)).all()
        existing = {r.key: r for r in rows if r and r.key}

    now = utc_now_naive()
    for key, value in updates.items():
        if not key:
            continue
        row = existing.get(key)
        if value is None:
            if row is not None:
                db.delete(row)
            continue
        if row is None:
            db.add(RuntimeSetting(key=key, value=value, updated_at=now))
        else:
            row.value = value
            row.updated_at = now

    db.commit()


def effective_bool(db: Session, key: str, env_var: str, default: bool) -> bool:
    spec = _SETTINGS.get(key)
    if spec is None:
        raw = (os.getenv(env_var, "true" if default else "false") or "").strip().lower()
        return raw in _TRUE
    try:
        overrides = get_overrides(db, [key])
    except Exception:
        overrides = {}
    if key in overrides:
        parsed = _parse_bool(overrides.get(key))
        if parsed is not None:
            return parsed
    raw = os.getenv(spec.env_var or env_var, "true" if default else "false")
    parsed = _parse_bool(raw)
    return default if parsed is None else parsed


def build_runtime_state(
    db: Session,
    collector_watchlist: Optional[list[str]] = None,
    active_position_count: int = 0,
) -> Dict[str, Any]:
    overrides = _get_all_overrides(db)
    effective = _build_effective_flat_config(overrides)
    sections = _build_sections(effective)
    watchlist_override_items = parse_watchlist(overrides["watchlist"]) if "watchlist" in overrides else None
    effective_watchlist = watchlist_override_items if watchlist_override_items is not None else (collector_watchlist or effective["watchlist"])
    watchlist_source = "override" if watchlist_override_items is not None else ("collector" if collector_watchlist else "env")
    live_guard_issues = get_live_guard_issues(effective, active_position_count=active_position_count)
    snapshot = ensure_runtime_snapshot(
        db,
        sections=sections,
        watchlist=effective_watchlist,
        watchlist_source=watchlist_source,
        source="runtime_state",
    )
    return {
        "trading_mode": effective["trading_mode"],
        "allow_live_trading": effective["allow_live_trading"],
        "demo_trading_enabled": effective["demo_trading_enabled"],
        "ws_enabled": effective["ws_enabled"],
        "max_certainty_mode": effective["max_certainty_mode"],
        "watchlist": effective_watchlist,
        "watchlist_override": watchlist_override_items,
        "watchlist_source": watchlist_source,
        "enabled_strategies": effective["enabled_strategies"],
        "active_position_count": active_position_count,
        "config_sections": sections,
        "config_snapshot_id": snapshot["id"],
        "config_hash": snapshot.get("config_hash"),
        "config_snapshot": snapshot,
        "live_ready": len(live_guard_issues) == 0,
        "live_guard_issues": live_guard_issues,
        "symbol_tiers": effective.get("symbol_tiers"),
        "updated_at": utc_now_naive().isoformat(),
    }


def get_runtime_config(db: Session) -> Dict[str, Any]:
    overrides = _get_all_overrides(db)
    return _build_effective_flat_config(overrides)


def get_live_guard_issues(config: Mapping[str, Any], active_position_count: int = 0) -> list[str]:
    issues: list[str] = []
    if config["trading_mode"] == "live":
        if not os.getenv("BINANCE_API_KEY", "").strip() or not os.getenv("BINANCE_API_SECRET", "").strip():
            issues.append("Live mode requires BINANCE_API_KEY and BINANCE_API_SECRET")
        if not os.getenv("ADMIN_TOKEN", "").strip():
            issues.append("Live mode requires ADMIN_TOKEN to be configured")
        if active_position_count > 0 and not config["kill_switch_enabled"]:
            issues.append("Open positions require kill_switch_enabled=true in live mode")
    if config["allow_live_trading"] and config["trading_mode"] != "live":
        # Dual mode — demo + live mogą działać równolegle
        pass
    return issues


def apply_runtime_updates(
    db: Session,
    updates: Mapping[str, Any],
    actor: str,
    active_position_count: int = 0,
) -> Dict[str, Any]:
    unknown = sorted(k for k in updates.keys() if k not in _SETTINGS)
    if unknown:
        raise RuntimeSettingsError(f"Unknown runtime settings: {', '.join(unknown)}")

    override_updates: Dict[str, Optional[str]] = {}
    for key, value in updates.items():
        spec = _SETTINGS[key]
        override_updates[key] = _normalize_update(spec, value)

    existing_overrides = _get_all_overrides(db)
    before = _build_effective_flat_config(existing_overrides)
    before_sections = _build_sections(before)
    before_watchlist_override_items = parse_watchlist(existing_overrides["watchlist"]) if "watchlist" in existing_overrides else None
    before_effective_watchlist = before_watchlist_override_items if before_watchlist_override_items is not None else before["watchlist"]
    before_watchlist_source = "override" if before_watchlist_override_items is not None else "env"
    previous_snapshot = ensure_runtime_snapshot(
        db,
        sections=before_sections,
        watchlist=before_effective_watchlist,
        watchlist_source=before_watchlist_source,
        source="runtime_state",
    )
    candidate_overrides = dict(existing_overrides)
    for key, value in override_updates.items():
        if value is None:
            candidate_overrides.pop(key, None)
        else:
            candidate_overrides[key] = value

    after = _build_effective_flat_config(candidate_overrides)
    changed_keys = [key for key in override_updates.keys() if before.get(key) != after.get(key)]
    if not changed_keys:
        return {"changed": [], "state": build_runtime_state(db, active_position_count=active_position_count)}

    if active_position_count > 0 and any(key in _LIVE_GUARD_KEYS for key in changed_keys):
        raise RuntimeSettingsError(
            "Cannot change live-critical risk/cost/mode settings while positions are open",
            status_code=409,
        )

    live_guard_issues = get_live_guard_issues(after, active_position_count=active_position_count)
    if live_guard_issues and after["trading_mode"] == "live":
        raise RuntimeSettingsError("; ".join(live_guard_issues), status_code=409)

    upsert_overrides(db, override_updates)

    sections = _build_sections(after)
    watchlist_override_items = parse_watchlist(candidate_overrides["watchlist"]) if "watchlist" in candidate_overrides else None
    effective_watchlist = watchlist_override_items if watchlist_override_items is not None else after["watchlist"]
    watchlist_source = "override" if watchlist_override_items is not None else "env"
    snapshot = ensure_runtime_snapshot(
        db,
        sections=sections,
        watchlist=effective_watchlist,
        watchlist_source=watchlist_source,
        source="runtime_update",
        changed_fields=changed_keys,
        previous_snapshot_id=previous_snapshot.get("id"),
        notes=f"actor={actor}",
    )

    audit_trail: list[Dict[str, Any]] = []
    for key in changed_keys:
        entry = {
            "key": key,
            "section": _SETTINGS[key].section,
            "old_value": before.get(key),
            "new_value": after.get(key),
            "changed_at": utc_now_naive().isoformat(),
            "changed_by": actor,
        }
        audit_trail.append(entry)
        log_to_db(
            "INFO",
            "control_plane",
            f"runtime setting changed: {json.dumps(entry, ensure_ascii=True, sort_keys=True)}",
            db=db,
        )

    return {
        "changed": audit_trail,
        "state": build_runtime_state(db, active_position_count=active_position_count),
        "snapshot": snapshot,
    }
