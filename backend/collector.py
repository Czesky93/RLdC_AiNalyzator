"""
Data Collector - zbiera dane z Binance i zapisuje do bazy
Uruchamiany jako osobny proces w tle
"""

import asyncio
import json
import logging
import os
import threading
import time
import warnings
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests
import websockets
from dotenv import load_dotenv
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from backend.accounting import compute_demo_account_state, get_demo_quote_ccy
from backend.analysis import (
    _compute_indicators,
    _klines_to_df,
    get_live_context,
    maybe_generate_insights_and_blog,
)
from backend.binance_client import get_binance_client
from backend.database import (
    AccountSnapshot,
    Alert,
    DecisionTrace,
    ExitQuality,
    ForecastRecord,
    Kline,
    MarketData,
    Order,
    PendingOrder,
    Position,
    SessionLocal,
    Signal,
    SystemLog,
    attach_costs_to_order,
    save_cost_entry,
    save_decision_trace,
    utc_now_naive,
)
from backend.portfolio_engine import (
    compute_replacement_decision,
    rank_entry_candidates,
    rank_open_positions,
)
from backend.quote_currency import (
    build_symbol_set,
    check_symbol_allowed,
    convert_eur_amount_to_quote,
    enforce_final_min_quote_usdc,
    ensure_usdc_balance_for_order,
    execute_conversion_eur_to_usdc,
    expand_watchlist_for_mode,
    filter_symbols_by_quote_mode,
    fund_usdc_from_eur_if_needed,
    get_base_asset,
    get_supported_base_assets,
    is_test_symbol,
    resolve_eur_usdc_rate,
    resolve_required_quote_usdc,
    should_convert_eur_to_usdc,
)
from backend.risk import (
    build_long_plan,
    build_risk_context,
    detect_regime,
    estimate_trade_costs,
    evaluate_risk,
    manage_long_position,
    validate_long_entry,
)
from backend.runtime_settings import (
    build_runtime_state,
    build_symbol_tier_map,
    effective_bool,
    get_runtime_config,
    watchlist_override,
)
from backend.system_logger import log_exception, log_to_db
from backend.telegram_formatter import (
    AlertThrottler,
    MessageSeverity,
    MessageType,
    format_status_message,
    format_sync_mismatch_message,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rldc.collector")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [collector] %(levelname)s: %(message)s")
    )
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False

ACTIVE_PENDING_STATUSES = {
    "PENDING_CREATED",
    "PENDING",
    "CONFIRMED",
    "PENDING_CONFIRMED",
    "EXCHANGE_SUBMITTED",
    "PARTIALLY_FILLED",
}
# Kompatybilność: obsługujemy legacy CONFIRMED/PENDING, ale canonical flow to
# PENDING_CREATED -> PENDING_CONFIRMED -> EXCHANGE_SUBMITTED -> FILLED/PARTIALLY_FILLED.
EXECUTABLE_PENDING_STATUSES = {"PENDING_CONFIRMED", "CONFIRMED"}


def _load_timeframe_indicators(
    db: Session,
    symbol: str,
    timeframe: str,
    *,
    limit: int = 220,
) -> Dict[str, float]:
    klines = (
        db.query(Kline)
        .filter(Kline.symbol == symbol, Kline.timeframe == timeframe)
        .order_by(Kline.open_time.desc())
        .limit(limit)
        .all()
    )
    df = _klines_to_df(list(reversed(klines)))
    if df is None or len(df) < 60:
        return {}
    return _compute_indicators(df)


class DataCollector:
    """Kolektor danych rynkowych z Binance"""

    def __init__(self):
        """Inicjalizacja kolektora"""
        self.binance = get_binance_client()
        self.watchlist = self._load_watchlist(allow_env_fallback=True)

        # Fallback: jeśli watchlist jest pusty, użyj stałej listy z .env
        if not self.watchlist:
            logger.warning("⚠️  Watchlist pusta — fallback do WATCHLIST z .env")
            raw_watchlist = os.getenv("WATCHLIST", "BTC/EUR,ETH/EUR")
            items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
            for item in items:
                resolved = self.binance.resolve_symbol(item)
                if not resolved:
                    resolved = item.replace("/", "").strip().upper()
                if resolved and resolved not in self.watchlist:
                    self.watchlist.append(resolved)
            self.watchlist = sorted(self.watchlist) if self.watchlist else []

        self.watchlist_refresh_seconds = int(
            os.getenv("WATCHLIST_REFRESH_SECONDS", "900")
        )
        self.last_watchlist_refresh_ts: Optional[datetime] = None
        self.last_no_watchlist_log_ts: Optional[datetime] = None
        self.interval = int(os.getenv("COLLECTION_INTERVAL_SECONDS", 60))
        self.kline_timeframes = os.getenv("KLINE_TIMEFRAMES", "1m,1h").split(",")
        self.running = False
        self.ws_running = False
        self.ws_thread: threading.Thread | None = None
        self.ws_backoff_seconds = 2
        self.last_risk_alert_ts: Optional[datetime] = None
        self.demo_state = {}
        self.last_crash_alert_ts: Optional[datetime] = None
        self.last_report_ts: Optional[datetime] = None
        self.last_openai_missing_log_ts: Optional[datetime] = None
        # Dedup alertów trailing stop: {symbol: last_trailing_stop_value}
        # Alert tylko przy aktywacji lub zmianie >0.5%
        self._trailing_alert_state: dict[str, float] = {}
        self.last_stale_ai_log_ts: Optional[datetime] = None
        self._last_heuristic_suppl_log_ts: Optional[datetime] = None
        self._last_heuristic_suppl_syms: list = []
        self._last_idle_alert_ts: Optional[datetime] = None
        self._sync_mismatch_throttler = AlertThrottler(
            cooldown_seconds=600
        )  # Throttle sync alerts
        self._sync_mismatch_repeat_count: Dict[str, int] = {}  # Licznik powtórzeń
        self.learning_days = int(os.getenv("LEARNING_DAYS", "180"))
        self.last_learning_ts: Optional[datetime] = None
        self.symbol_params = {}
        self._load_persisted_symbol_params()
        self.last_snapshot_ts: Optional[datetime] = None
        self.last_live_snapshot_ts: Optional[datetime] = None
        self._last_binance_sync_ts: Optional[datetime] = None
        self._last_binance_mismatch_signature: Optional[str] = None
        self._last_binance_mismatch_log_ts: Optional[datetime] = None
        self.binance_mismatch_log_cooldown_seconds = int(
            os.getenv("BINANCE_MISMATCH_LOG_COOLDOWN_SECONDS", "1800")
        )
        self._execution_lock = threading.Lock()
        self._inflight_symbol_orders: dict[str, datetime] = {}
        self._inflight_ttl_seconds = int(
            os.getenv("EXECUTION_INFLIGHT_TTL_SECONDS", "120")
        )

        logger.info(f"📊 DataCollector initialized")
        logger.info(f"   Watchlist: {', '.join(self.watchlist)}")
        logger.info(f"   Interval: {self.interval}s")
        logger.info(f"   Timeframes: {', '.join(self.kline_timeframes)}")

    def _load_persisted_symbol_params(self):
        """Wczytaj symbol_params zapisane przez _learn_from_history z poprzedniej sesji."""
        try:
            import json as _json

            from backend.database import RuntimeSetting
            from backend.database import SessionLocal as _SL

            _db = _SL()
            try:
                row = (
                    _db.query(RuntimeSetting)
                    .filter(RuntimeSetting.key == "learning_symbol_params")
                    .first()
                )
                if row and row.value:
                    loaded = _json.loads(row.value)
                    if isinstance(loaded, dict):
                        self.symbol_params = loaded
                        logger.info(
                            f"📚 Wczytano symbol_params z DB ({len(loaded)} symboli)"
                        )
            finally:
                _db.close()
        except Exception as exc:
            logger.warning(f"⚠️ Nie można wczytać symbol_params z DB: {exc}")

    def _runtime_context(self, db: Session) -> dict[str, Any]:
        active_position_count = int(
            db.query(Position)
            .filter(Position.exit_reason_code.is_(None), Position.quantity > 0)
            .count()
        )
        state = build_runtime_state(
            db,
            collector_watchlist=self.watchlist,
            active_position_count=active_position_count,
        )
        config = get_runtime_config(db)
        return {
            "state": state,
            "config": config,
            "sections": state.get("config_sections") or {},
            "snapshot_id": state.get("config_snapshot_id"),
        }

    def _trace_decision(
        self,
        db: Session,
        *,
        symbol: str,
        action: str,
        reason_code: str,
        runtime_ctx: dict[str, Any],
        mode: str = None,
        signal_summary: Optional[dict[str, Any]] = None,
        risk_check: Optional[dict[str, Any]] = None,
        cost_check: Optional[dict[str, Any]] = None,
        execution_check: Optional[dict[str, Any]] = None,
        details: Optional[dict[str, Any]] = None,
        order_id: Optional[int] = None,
        position_id: Optional[int] = None,
        strategy_name: Optional[str] = "default",
        level: str = "INFO",
    ) -> None:
        mode = getattr(self, "_active_mode", None) or mode or "demo"
        payload = details or {}
        save_decision_trace(
            db,
            symbol=symbol,
            mode=mode,
            action_type=action.lower(),
            reason_code=reason_code,
            strategy_name=strategy_name,
            signal_summary=signal_summary or {},
            risk_gate_result=risk_check or {},
            cost_gate_result=cost_check or {},
            execution_gate_result=execution_check or {},
            config_snapshot_id=runtime_ctx.get("snapshot_id"),
            order_id=order_id,
            position_id=position_id,
            payload=payload,
        )
        db.flush()
        log_to_db(
            level,
            "collector_decision",
            json.dumps(
                {
                    "symbol": symbol,
                    "mode": mode,
                    "final_action": action,
                    "reason_code": reason_code,
                    "config_snapshot_id": runtime_ctx.get("snapshot_id"),
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            db=db,
        )

    def _convert_fee_to_quote(
        self,
        db: Session,
        *,
        fee_amount: float,
        fee_asset: str,
        symbol: str,
        exec_price: float,
        quote_ccy: str,
        notional: float = 0.0,
    ) -> Optional[float]:
        """Konwertuj prowizję Binance (commissionAsset) do waluty kwotowanej symbolu."""
        if fee_amount <= 0:
            return 0.0
        fee_asset_u = (fee_asset or "").upper()
        sym = (symbol or "").upper()
        quote = (quote_ccy or "").upper()
        if not fee_asset_u or not quote:
            return None

        # Bezpiecznik: prowizja nie może przekraczać 2% wartości transakcji
        # (Binance max fee = 0.1% spot; BNB discount = 0.075%; max realistic = 0.5%)
        _max_fee_rate = 0.02
        _notional = (
            notional
            if notional > 0
            else (fee_amount * exec_price if exec_price > 0 else 0.0)
        )

        if fee_asset_u == quote:
            result = float(fee_amount)
            if _notional > 0 and result > _notional * _max_fee_rate:
                logger.warning(
                    f"_convert_fee_to_quote: fee {result:.6f} {quote} > {_max_fee_rate*100:.1f}% notional "
                    f"{_notional:.4f} dla {symbol} — odrzucam, zwracam None"
                )
                return None
            return result

        base = sym
        for q in ("USDC", "USDT", "EUR", "BUSD"):
            if sym.endswith(q):
                base = sym[: -len(q)]
                break

        if fee_asset_u == base and exec_price > 0:
            result = float(fee_amount) * float(exec_price)
            if _notional > 0 and result > _notional * _max_fee_rate:
                logger.warning(
                    f"_convert_fee_to_quote: fee_base {fee_amount:.8g} {fee_asset_u} * price "
                    f"{exec_price:.4f} = {result:.6f} {quote} > {_max_fee_rate*100:.1f}% notional "
                    f"{_notional:.4f} dla {symbol} — odrzucam, zwracam None"
                )
                return None
            return result

        def _latest_md_price(sym_name: str) -> Optional[float]:
            row = (
                db.query(MarketData)
                .filter(MarketData.symbol == sym_name)
                .order_by(MarketData.timestamp.desc())
                .first()
            )
            if row and row.price and float(row.price) > 0:
                return float(row.price)
            return None

        direct = _latest_md_price(f"{fee_asset_u}{quote}")
        if direct:
            return float(fee_amount) * direct

        inverse = _latest_md_price(f"{quote}{fee_asset_u}")
        if inverse and inverse > 0:
            return float(fee_amount) / inverse

        try:
            t = self.binance.get_ticker_price(f"{fee_asset_u}{quote}")
            p = float(t.get("price", 0)) if t else 0.0
            if p > 0:
                return float(fee_amount) * p
        except Exception:
            pass

        try:
            t = self.binance.get_ticker_price(f"{quote}{fee_asset_u}")
            p = float(t.get("price", 0)) if t else 0.0
            if p > 0:
                return float(fee_amount) / p
        except Exception:
            pass

        return None

    def _load_watchlist(self, allow_env_fallback: bool = True) -> List[str]:
        """Wczytaj listę symboli do śledzenia"""
        quotes = [
            q.strip().upper()
            for q in os.getenv("PORTFOLIO_QUOTES", "EUR,USDC").split(",")
            if q.strip()
        ]
        balances = self.binance.get_balances()
        assets = [b.get("asset") for b in balances if (b.get("total") or 0) > 0]

        def _candidates(asset: str) -> List[str]:
            """
            Binance czasem zwraca aktywa typu LD* (Simple Earn / Savings).
            Dla watchlisty traktujemy LDXXX jako XXX, aby mapować na realne pary rynkowe.
            """
            a = (asset or "").strip().upper()
            if not a:
                return []
            if a.startswith("LD") and len(a) > 2:
                return [a[2:], a]
            return [a]

        resolved: List[str] = []
        for asset in assets:
            if not asset:
                continue
            for base in _candidates(asset):
                if not base or base in quotes:
                    continue
                for quote in quotes:
                    pair = f"{base}/{quote}"
                    symbol = self.binance.resolve_symbol(pair)
                    if symbol and symbol not in resolved:
                        resolved.append(symbol)

        # ── Filtruj gegen dozwolone pary SPOT z Binance exchangeInfo ─────────
        if resolved:
            try:
                allowed = self.binance.get_allowed_symbols(quotes=list(quotes))
                if allowed:
                    filtered = [s for s in resolved if s in allowed]
                    blocked = [s for s in resolved if s not in allowed]
                    if blocked:
                        logger.warning(
                            f"⚠️ Symbole spoza whitelist SPOT (pomijam): {blocked}"
                        )
                    if filtered:
                        resolved = filtered
                    # Jeśli wszystkie odfiltrowane (rzadkie) — zachowaj oryginalne aby nie wyzerować watchlisty
            except Exception as exc:
                logger.warning(f"⚠️ Nie można sprawdzić dozwolonych symboli SPOT: {exc}")
        # ─────────────────────────────────────────────────────────────────────

        # ── Scalaj z env WATCHLIST (skonfigurowane cele handlowe) ────────────
        # Env WATCHLIST zawiera pary przeznaczone do handlu (np. BTC/ETH/SOL/BNB EUR).
        # NIE jest tylko fallbackiem — te symbole muszą być w watchliście zawsze wtedy,
        # gdy mamy jakiekolwiek symbole z salda (resolved non-empty) LUB gdy jest to
        # pierwsze załadowanie (allow_env_fallback=True).
        # Wyjątek: podczas odświeżania przy awarii Binance (resolved empty + fallback=False)
        # zwracamy [] → _refresh_watchlist_if_due zachowuje starą listę.
        if resolved or allow_env_fallback:
            raw_watchlist = os.getenv("WATCHLIST", "")
            if raw_watchlist.strip():
                items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
                _supported_bases = set(get_supported_base_assets())
                for item in items:
                    item_clean = item.replace("/", "").replace("-", "").strip().upper()
                    # Bare base asset (np. "BTC", "ETH") — rozszerz do obu quote currencies
                    if item_clean in _supported_bases:
                        for sym in build_symbol_set([item_clean], "BOTH"):
                            if sym not in resolved:
                                resolved.append(sym)
                        continue
                    # Para z quote currency (np. "BTCEUR", "BTC/EUR") —
                    # wyciągnij base i rozszerz do obu wariantów
                    base = get_base_asset(item_clean)
                    if base and base in _supported_bases:
                        for sym in build_symbol_set([base], "BOTH"):
                            if sym not in resolved:
                                resolved.append(sym)
                        continue
                    # Legacy/nieznany format — spróbuj resolve_symbol
                    resolved_symbol = self.binance.resolve_symbol(item)
                    if not resolved_symbol:
                        resolved_symbol = item_clean
                    if resolved_symbol and resolved_symbol not in resolved:
                        resolved.append(resolved_symbol)
        # ─────────────────────────────────────────────────────────────────────

        # Rozszerz o brakujące warianty EUR/USDC dla wszystkich znanych aktywów
        # bazowych w puli. Tryb BOTH → pełna pula; mode filter w
        # _refresh_watchlist_if_due dokona późniejszego cięcia.
        if resolved:
            resolved = expand_watchlist_for_mode(resolved, "BOTH")

        if os.getenv("ENABLE_DYNAMIC_UNIVERSE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            try:
                from backend.symbol_universe import (
                    get_rotating_universe_slice,
                    get_symbol_registry,
                )

                registry = get_symbol_registry(
                    binance_client=self.binance,
                    user_watchlist=list(resolved),
                )
                for sym in registry.get("user_watchlist") or []:
                    if sym not in resolved:
                        resolved.append(sym)
                dynamic_slice, _next_offset = get_rotating_universe_slice(
                    registry=registry,
                    limit=int(os.getenv("MAX_SYMBOL_SCAN_PER_CYCLE", "100") or 100),
                )
                for sym in dynamic_slice:
                    if sym not in resolved:
                        resolved.append(sym)
            except Exception as exc:
                logger.warning("⚠️ Dynamic universe merge failed: %s", exc)

        return sorted(resolved) if resolved else []

    def _has_openai_key(self) -> bool:
        return os.getenv("OPENAI_API_KEY", "").strip() != ""

    def _has_any_ai_key(self) -> bool:
        """Sprawdza czy jest skonfigurowany jakikolwiek provider AI (klucz lub Ollama)."""
        return (
            bool(os.getenv("OLLAMA_BASE_URL", "").strip())
            or bool(os.getenv("GEMINI_API_KEY", "").strip())
            or bool(os.getenv("GROQ_API_KEY", "").strip())
            or bool(os.getenv("OPENAI_API_KEY", "").strip())
        )

    def _is_ai_failed_runtime(self) -> tuple[bool, str]:
        """Zwraca (ai_failed, provider_label) na podstawie statusu orchestratora."""
        provider_env = os.getenv("AI_PROVIDER", "auto").strip().lower()
        provider_label = provider_env or "auto"
        ai_failed = False
        try:
            from backend.ai_orchestrator import get_ai_orchestrator_status

            st = get_ai_orchestrator_status(force=False)
            provider_label = str(st.get("primary") or provider_label)
            fallback_active = bool(st.get("fallback_active"))
            # Jeśli żądany provider AI nie działa i system spadł do heurystyki,
            # traktujemy to jako AI failure dla celów threshold/fallback confidence.
            if provider_env in {"openai", "gemini", "groq", "auto"} and (
                provider_label == "heuristic" or fallback_active
            ):
                ai_failed = True
        except Exception:
            ai_failed = provider_env in {"openai", "gemini", "groq"} and (
                not self._has_any_ai_key()
            )
        return ai_failed, provider_label

    def _calculate_confidence_from_indicators(
        self,
        *,
        signal_type: str,
        rsi: Optional[float],
        ema20: Optional[float],
        ema50: Optional[float],
        volume_ratio: Optional[float],
        momentum_hist: Optional[float],
    ) -> float:
        """Fallback confidence liczony z indikatorów (zawsze > 0 dla normalnego rynku)."""

        def _clamp01(v: float) -> float:
            return max(0.0, min(1.0, float(v)))

        sig = (signal_type or "HOLD").upper()

        # RSI score
        if rsi is None:
            rsi_score = 0.5
        else:
            rsi_val = float(rsi)
            if sig == "BUY":
                rsi_score = _clamp01((70.0 - rsi_val) / 40.0)
            elif sig == "SELL":
                rsi_score = _clamp01((rsi_val - 30.0) / 40.0)
            else:
                rsi_score = _clamp01(1.0 - abs(rsi_val - 50.0) / 35.0)

        # Trend score
        if ema20 is None or ema50 is None:
            trend_score = 0.5
        else:
            if sig == "BUY":
                trend_score = 1.0 if float(ema20) > float(ema50) else 0.2
            elif sig == "SELL":
                trend_score = 1.0 if float(ema20) < float(ema50) else 0.2
            else:
                trend_score = 0.5

        # Volume score
        if volume_ratio is None:
            volume_score = 0.5
        else:
            volume_score = _clamp01(float(volume_ratio) / 1.8)

        # Momentum score
        if momentum_hist is None:
            momentum_score = 0.5
        else:
            mh = float(momentum_hist)
            if sig == "BUY":
                momentum_score = 1.0 if mh > 0 else 0.2
            elif sig == "SELL":
                momentum_score = 1.0 if mh < 0 else 0.2
            else:
                momentum_score = 0.5

        confidence = (
            rsi_score * 0.3
            + trend_score * 0.3
            + volume_score * 0.2
            + momentum_score * 0.2
        )
        return round(max(0.35, min(0.95, confidence)), 4)

    def _dynamic_min_confidence(self, ai_failed: bool) -> float:
        """Próg confidence wymagany przez runtime (AI OK vs fallback)."""
        return 0.4 if ai_failed else 0.6

    def _log_openai_missing(self):
        now = utc_now_naive()
        if (
            self.last_openai_missing_log_ts
            and (now - self.last_openai_missing_log_ts).total_seconds() < 300
        ):
            return
        self.last_openai_missing_log_ts = now
        msg = "Brak klucza AI (Gemini/Groq/OpenAI) — używam heurystyki ATR/Bollinger."
        logger.warning(f"⚠️ {msg}")
        log_to_db("WARNING", "collector", msg)

    def _log_no_watchlist(self, db: Session, hint: Optional[str] = None):
        now = utc_now_naive()
        if (
            self.last_no_watchlist_log_ts
            and (now - self.last_no_watchlist_log_ts).total_seconds() < 300
        ):
            return
        self.last_no_watchlist_log_ts = now
        msg = "Brak symboli z portfela Binance (Spot) — pomijam cykl i ponowię próbę."
        if hint:
            msg = f"{msg} {hint}"
        logger.warning(f"⚠️ {msg}")
        log_to_db("ERROR", "collector", msg, db=db)

    def _refresh_watchlist_if_due(self, db: Session, force: bool = False) -> bool:
        now = utc_now_naive()
        if not force and self.last_watchlist_refresh_ts:
            if (now - self.last_watchlist_refresh_ts).total_seconds() < float(
                self.watchlist_refresh_seconds
            ):
                return False

        self.last_watchlist_refresh_ts = now
        try:
            # Jeśli watchlista już istnieje, nie używaj fallbacku z .env przy chwilowych
            # problemach z saldami Binance - zostaw poprzednią listę i unikaj flappingu.
            new_list = self._load_watchlist(allow_env_fallback=not bool(self.watchlist))
        except Exception as exc:
            log_exception("collector", "Błąd odświeżania watchlisty", exc, db=db)
            return False

        if not new_list:
            # Jeśli mieliśmy watchlistę wcześniej, nie zeruj jej przez chwilową awarię.
            if self.watchlist:
                self._log_no_watchlist(
                    db,
                    hint="Zostawiam poprzednią watchlistę (tymczasowy problem z odczytem sald).",
                )
            else:
                # Diagnostyka: brak kluczy lub brak sald
                if not getattr(self.binance, "api_key", "") or not getattr(
                    self.binance, "api_secret", ""
                ):
                    self._log_no_watchlist(
                        db,
                        hint="Sprawdź BINANCE_API_KEY/BINANCE_API_SECRET i uprawnienia read-only.",
                    )
                else:
                    self._log_no_watchlist(db)
            return False

        if new_list != self.watchlist:
            old = ", ".join(self.watchlist) if self.watchlist else "(pusto)"
            new = ", ".join(new_list)
            logger.info(f"🔁 Watchlista z portfela: {old} -> {new}")
            log_to_db("INFO", "collector", f"Watchlist updated: {old} -> {new}", db=db)
            self.watchlist = new_list
        # Filtrowanie wg quote currency mode (twarde, deterministyczne)
        qcm = os.getenv("QUOTE_CURRENCY_MODE", "BOTH").strip().upper()
        if qcm != "BOTH":
            before = list(self.watchlist)
            filtered = filter_symbols_by_quote_mode(before, qcm)
            blocked = [s for s in before if s not in filtered]
            if blocked:
                logger.info(
                    "🔀 Quote mode=%s — odfiltrowano: %s", qcm, ", ".join(blocked)
                )
                log_to_db(
                    "INFO",
                    "collector",
                    f"quote_mode_filter mode={qcm} blocked={blocked}",
                    db=db,
                )
            if not filtered:
                log_to_db(
                    "WARNING",
                    "collector",
                    f"quote_mode_filter mode={qcm} produced empty watchlist",
                    db=db,
                )
            self.watchlist = filtered

            # Restart WS, aby odświeżyć streamy po zmianie listy symboli
            if self.ws_running:
                self.stop_ws()
                if effective_bool(db, "ws_enabled", "WS_ENABLED", True):
                    self.start_ws()
        else:
            self.watchlist = new_list

        return True

    def reset_demo_state(self):
        self.demo_state = {}
        self.last_report_ts = None
        self.last_risk_alert_ts = None
        self.last_crash_alert_ts = None
        self._last_idle_alert_ts = None
        self.last_snapshot_ts = None
        self._sync_mismatch_throttler = AlertThrottler(cooldown_seconds=600)
        self._sync_mismatch_repeat_count = {}

    def _maybe_auto_convert_funding(self, db: Session):
        """Auto-konwersja EUR→USDC dla trybu USDC/BOTH z preferencją USDC."""
        mode = os.getenv("QUOTE_CURRENCY_MODE", "BOTH").strip().upper()
        primary_quote = os.getenv("PRIMARY_QUOTE", "EUR").strip().upper()
        allow_auto = os.getenv(
            "ALLOW_AUTO_CONVERT_EUR_TO_USDC", "false"
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if not allow_auto:
            return
        if mode not in {"USDC", "BOTH"}:
            return
        if mode == "BOTH" and primary_quote != "USDC":
            return

        try:
            balances = self.binance.get_balances() or []
        except Exception as exc:
            log_exception(
                "collector", "Błąd pobierania sald dla auto-konwersji", exc, db=db
            )
            return

        free_eur = 0.0
        free_usdc = 0.0
        for b in balances:
            asset = str(b.get("asset") or "").upper()
            free_v = float(b.get("free", b.get("total", 0)) or 0.0)
            if asset == "EUR":
                free_eur = free_v
            elif asset == "USDC":
                free_usdc = free_v

        min_eur_reserve = float(os.getenv("MIN_EUR_RESERVE", "10") or 10)
        min_conversion_notional = float(
            os.getenv("MIN_CONVERSION_NOTIONAL", "20") or 20
        )
        conversion_cooldown_minutes = int(
            os.getenv("CONVERSION_COOLDOWN_MINUTES", "60") or 60
        )
        target_usdc_buffer = float(os.getenv("TARGET_USDC_BUFFER", "50") or 50)
        max_conversion_per_hour = int(os.getenv("MAX_CONVERSION_PER_HOUR", "2") or 2)

        should_convert, reason_code, amount = should_convert_eur_to_usdc(
            free_eur=free_eur,
            free_usdc=free_usdc,
            target_usdc_buffer=target_usdc_buffer,
            min_eur_reserve=min_eur_reserve,
            min_conversion_notional=min_conversion_notional,
            conversion_cooldown_minutes=conversion_cooldown_minutes,
            max_conversion_per_hour=max_conversion_per_hour,
        )
        if not should_convert:
            log_to_db(
                "INFO",
                "collector",
                f"funding_conversion_skip reason={reason_code} free_eur={free_eur:.4f} free_usdc={free_usdc:.4f}",
                db=db,
            )
            return

        result = execute_conversion_eur_to_usdc(self.binance, amount_eur=amount, db=db)
        log_to_db(
            "INFO" if result.get("executed") else "ERROR",
            "collector",
            f"funding_conversion result={result}",
            db=db,
        )

    def _create_pending_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        mode: str = None,
        reason: str = "",
        config_snapshot_id: Optional[str] = None,
        strategy_name: Optional[str] = None,
        source: str = "collector",
        pending_type: Optional[str] = None,
    ) -> int:
        mode = getattr(self, "_active_mode", None) or mode or "demo"
        symbol_norm = (symbol or "").strip().upper().replace("/", "").replace("-", "")
        side_norm = (side or "").strip().upper()
        qty_f = float(qty or 0.0)
        if qty_f <= 0:
            raise ValueError(
                f"PendingOrder blocked: non-positive quantity for {symbol_norm} {side_norm} qty={qty_f}"
            )

        existing_active = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.symbol == symbol_norm,
                PendingOrder.side == side_norm,
                PendingOrder.mode == mode,
                PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)),
            )
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        if existing_active is not None:
            return int(existing_active.id)

        now = utc_now_naive()
        config = get_runtime_config(db)
        idempotency_key = (
            f"idem:{mode}:{symbol_norm}:{side_norm}:{int(now.timestamp())}"
        )
        reason_full = (reason or "").strip()
        if reason_full:
            reason_full = f"{reason_full} | {idempotency_key}"
        else:
            reason_full = idempotency_key

        auto_execute = bool(config.get("enable_auto_execute", True))
        manual_confirmation = bool(config.get("require_manual_confirmation", False))
        if mode == "demo":
            manual_confirmation = manual_confirmation or bool(
                config.get("demo_require_manual_confirm", False)
            )
        auto_confirm = auto_execute and not manual_confirmation
        if pending_type is None:
            if source.startswith("manual"):
                pending_type = f"manual_{mode}"
            else:
                pending_type = f"auto_{mode}"
        pending = PendingOrder(
            symbol=symbol_norm,
            side=side_norm,
            order_type="MARKET",
            price=price,
            quantity=qty_f,
            mode=mode,
            status="PENDING_CONFIRMED" if auto_confirm else "PENDING_CREATED",
            reason=reason_full,
            config_snapshot_id=config_snapshot_id,
            strategy_name=strategy_name,
            source=source,
            pending_type=pending_type,
            created_at=now,
            expires_at=now + timedelta(hours=24),
            confirmed_at=now if auto_confirm else None,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        return pending.id

    def _inflight_key(self, mode: str, symbol: str, side: str) -> str:
        return f"{(mode or 'demo').lower()}:{(symbol or '').upper()}:{(side or '').upper()}"

    def _acquire_inflight_slot(self, mode: str, symbol: str, side: str) -> bool:
        now = utc_now_naive()
        key = self._inflight_key(mode, symbol, side)
        if not hasattr(self, "_execution_lock"):
            self._execution_lock = threading.Lock()
        if not hasattr(self, "_inflight_symbol_orders"):
            self._inflight_symbol_orders = {}
        if not hasattr(self, "_inflight_ttl_seconds"):
            self._inflight_ttl_seconds = int(
                os.getenv("EXECUTION_INFLIGHT_TTL_SECONDS", "120")
            )
        with self._execution_lock:
            stale_before = now - timedelta(seconds=max(1, self._inflight_ttl_seconds))
            stale_keys = [
                k for k, ts in self._inflight_symbol_orders.items() if ts < stale_before
            ]
            for k in stale_keys:
                self._inflight_symbol_orders.pop(k, None)
            if key in self._inflight_symbol_orders:
                return False
            self._inflight_symbol_orders[key] = now
            return True

    def _release_inflight_slot(self, mode: str, symbol: str, side: str) -> None:
        key = self._inflight_key(mode, symbol, side)
        if not hasattr(self, "_execution_lock"):
            return
        if not hasattr(self, "_inflight_symbol_orders"):
            return
        with self._execution_lock:
            self._inflight_symbol_orders.pop(key, None)

    def _send_telegram_alert(self, title: str, message: str, force_send: bool = False):
        risk_alerts = os.getenv("TELEGRAM_RISK_ALERTS", "false").lower() == "true"
        error_only = os.getenv("TELEGRAM_ERROR_ONLY", "false").lower() == "true"
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        if not force_send and not risk_alerts and title in {"Limit strat", "Drawdown"}:
            return
        if (
            not force_send
            and error_only
            and title not in {"Błąd", "Error", "Critical", "Limit strat", "Drawdown"}
        ):
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(
                url,
                json={"chat_id": chat_id, "text": f"⚠️ {title}\n{message}"},
                timeout=5,
            )
        except Exception as exc:
            log_exception("collector", "Błąd wysyłki alertu Telegram", exc)

    @staticmethod
    def _quote_asset_from_symbol(symbol: str) -> str:
        sym = str(symbol or "").upper()
        if sym.endswith("USDC"):
            return "USDC"
        if sym.endswith("EUR"):
            return "EUR"
        if sym.endswith("USDT"):
            return "USDT"
        return "EUR"

    def _load_live_balance_map(self) -> dict[str, float]:
        balances = self.binance.get_balances() or []
        out: dict[str, float] = {}
        for b in balances:
            asset = str(b.get("asset") or "").upper()
            out[asset] = float(b.get("free", b.get("total", 0)) or 0.0)
        return out

    def _resolve_min_buy_quote_notional(
        self, symbol: str, config: dict
    ) -> tuple[float, dict]:
        """
        Warstwa referencyjna → USDC/EUR.
        min_buy_reference_eur jest WYŁĄCZNIE referencją (nie egzekwowane w EUR).
        Wynik: (required_quote, meta) gdzie required_quote jest w USDC (lub EUR dla par EUR).
        """
        quote = self._quote_asset_from_symbol(symbol)
        min_buy_reference_eur = float(config.get("min_buy_eur", 60.0))
        allowed = self.binance.get_allowed_symbols() or {}
        exchange_min_notional = float(
            (allowed.get(symbol) or {}).get("min_notional") or 0.0
        )

        if quote == "USDC":
            required_quote_usdc, meta = resolve_required_quote_usdc(
                min_buy_reference_eur,
                self.binance,
                exchange_min_notional=exchange_min_notional,
            )
            return required_quote_usdc, {
                "quote_asset": "USDC",
                "required_quote_usdc": required_quote_usdc,
                **meta,
            }

        # Para EUR: przelicz referencję EUR→ kwota EUR (bez konwersji waluty)
        rate, rate_source = resolve_eur_usdc_rate(self.binance)
        # dla EUR par: wymagamy min_buy_reference_eur EUR
        required_eur = max(min_buy_reference_eur, exchange_min_notional)
        return required_eur, {
            "quote_asset": "EUR",
            "required_quote_eur": required_eur,
            "min_buy_reference_eur": min_buy_reference_eur,
            "eur_usdc_rate": rate,
            "rate_source": rate_source,
            "exchange_min_notional": exchange_min_notional,
        }

    def _ensure_usdc_from_eur(
        self, db: Session, needed_usdc: float, config: dict
    ) -> dict[str, Any]:
        """
        DEPRECATED internals — używaj _ensure_quote_balance_for_order.
        Zachowany jako backward-compat wrapper.
        """
        fee_buffer_pct = float(config.get("execution_quote_buffer_pct", 0.01))
        balances = self._load_live_balance_map()
        return fund_usdc_from_eur_if_needed(
            self.binance,
            required_usdc=needed_usdc,
            available_usdc=float(balances.get("USDC", 0.0)),
            available_eur=float(balances.get("EUR", 0.0)),
            fee_buffer_pct=fee_buffer_pct,
            db=db,
        )

    def _ensure_quote_balance_for_order(
        self,
        db: Session,
        *,
        symbol: str,
        required_quote_notional: float,
        config: dict,
    ) -> dict[str, Any]:
        """
        USDC-first: używa ensure_usdc_balance_for_order (który woła fund_usdc_from_eur_if_needed).
        Dla par EUR: sprawdza saldo EUR bez konwersji.
        """
        fee_buffer_pct = float(config.get("execution_quote_buffer_pct", 0.01))
        return ensure_usdc_balance_for_order(
            self.binance,
            symbol=symbol,
            required_usdc=required_quote_notional,
            fee_buffer_pct=fee_buffer_pct,
            db=db,
        )

    def _normalize_buy_qty_for_exchange(
        self,
        *,
        symbol: str,
        target_qty: float,
        price: float,
        min_quote_notional: float,
    ) -> tuple[float, dict[str, Any]]:
        import math

        allowed = self.binance.get_allowed_symbols() or {}
        info = allowed.get(symbol, {})
        step = float(info.get("step_size") or 0.0)
        min_qty = float(info.get("min_qty") or 0.0)
        ex_min_notional = float(info.get("min_notional") or 0.0)
        required_notional = max(float(min_quote_notional or 0.0), ex_min_notional)

        qty = max(0.0, float(target_qty or 0.0))
        if step > 0:
            qty = math.ceil(qty / step) * step
            decimals = max(0, -int(math.floor(math.log10(step))))
            qty = round(qty, decimals)
        if min_qty > 0 and qty < min_qty:
            qty = min_qty

        if price > 0 and required_notional > 0 and qty * price < required_notional:
            needed_qty = required_notional / price
            if step > 0:
                needed_qty = math.ceil(needed_qty / step) * step
                decimals = max(0, -int(math.floor(math.log10(step))))
                needed_qty = round(needed_qty, decimals)
            qty = max(qty, needed_qty)

        return qty, {
            "step_size": step,
            "min_qty": min_qty,
            "exchange_min_notional": ex_min_notional,
            "required_notional": required_notional,
            "normalized_notional": qty * price if price > 0 else 0.0,
        }

    def _execute_confirmed_pending_orders(self, db: Session):
        """
        Wykonaj potwierdzone transakcje (DEMO + LIVE) zapisane jako PendingOrder.
        DEMO: symulacja ceny rynkowej.
        LIVE: zlecenie na Binance API (place_order) — CHRONIONE FLAGA ALLOW_LIVE_TRADING.
        """
        runtime_ctx = self._runtime_context(db)
        config = runtime_ctx["config"]
        now = utc_now_naive()

        # SAFETY GATE: korzystaj z runtime config (DB/env effective), nie tylko z process env.
        allow_live_trading = bool(config.get("allow_live_trading"))
        trading_mode = str(config.get("trading_mode") or "demo").lower()
        execution_enabled = bool(config.get("execution_enabled", True))

        try:
            expired_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.status.in_(
                        ["PENDING_CREATED", "PENDING_CONFIRMED", "CONFIRMED"]
                    ),
                    PendingOrder.expires_at.is_not(None),
                    PendingOrder.expires_at < now,
                )
                .all()
            )
            for pending in expired_pending:
                pending.status = "EXPIRED"
                pending.reason = (
                    f"{pending.reason or ''} | expired_timeout_cleanup".strip()
                )
            if expired_pending:
                db.commit()
        except Exception:
            db.rollback()

        # GLOBAL EXECUTION KILL SWITCH — blokuje ALL tryby (live i demo)
        if not execution_enabled:
            confirmed_disabled = (
                db.query(PendingOrder)
                .filter(PendingOrder.status.in_(list(EXECUTABLE_PENDING_STATUSES)))
                .order_by(desc(PendingOrder.confirmed_at))
                .limit(50)
                .all()
            )
            for pending in confirmed_disabled:
                self._trace_decision(
                    db,
                    symbol=pending.symbol,
                    action="SKIP_PENDING",
                    reason_code="execution_globally_disabled",
                    runtime_ctx=runtime_ctx,
                    mode=(pending.mode or "demo"),
                    execution_check={
                        "eligible": False,
                        "pending_id": pending.id,
                        "execution_enabled": False,
                    },
                )
            log_to_db(
                "WARNING",
                "execution_gate",
                "EXECUTION_ENABLED=false — wszystkie pending orders zablokowane globalnie (reason_code=execution_globally_disabled)",
                db=db,
            )
            return

        if not allow_live_trading:
            log_to_db(
                "WARNING",
                "execution_gate",
                f"ALLOW_LIVE_TRADING=false (trading_mode={trading_mode}) — pending orders NIE będą wykonane live, tylko DEMO",
                db=db,
            )

        confirmed = (
            db.query(PendingOrder)
            .filter(PendingOrder.status.in_(list(EXECUTABLE_PENDING_STATUSES)))
            .order_by(desc(PendingOrder.confirmed_at))
            .limit(50)
            .all()
        )
        if not confirmed:
            return

        # SELLs najpierw — zapobiega sytuacji gdy BUY wykonuje się po SL-SELL na tym samym symbolu
        confirmed.sort(
            key=lambda o: (
                0 if (o.side or "").upper() == "SELL" else 1,
                (o.confirmed_at.timestamp() if o.confirmed_at else 0.0),
            )
        )

        # Zbierz symbole, dla których SELL już wykona się w tej partii
        _sell_symbols_in_batch = {
            o.symbol for o in confirmed if (o.side or "").upper() == "SELL"
        }
        # Zablokuj BUY dla tych symboli (race condition SL-SELL → pending-BUY)
        cancelled_race = 0
        for o in confirmed:
            if (o.side or "").upper() == "BUY" and o.symbol in _sell_symbols_in_batch:
                o.status = "CANCELLED"
                o.reason = (
                    o.reason or ""
                ) + " [ANULOWANO: konflikt z SELL w tej samej partii]"
                cancelled_race += 1
        if cancelled_race:
            db.commit()
            confirmed = [
                o for o in confirmed if o.status in EXECUTABLE_PENDING_STATUSES
            ]

        executed_count = 0
        for pending in confirmed:
            p_mode = pending.mode or "demo"
            _slot_acquired = self._acquire_inflight_slot(
                p_mode, pending.symbol, pending.side
            )
            if not _slot_acquired:
                self._trace_decision(
                    db,
                    symbol=pending.symbol,
                    action="SKIP_PENDING",
                    reason_code="duplicate_entry",
                    runtime_ctx=runtime_ctx,
                    mode=p_mode,
                    execution_check={
                        "eligible": False,
                        "pending_id": pending.id,
                    },
                    details={
                        "stage": "inflight_lock",
                        "reason": "duplicate_pending_execution_prevented",
                    },
                    level="WARNING",
                )
                continue
            try:
                qty = float(pending.quantity)

                if qty <= 0:
                    pending.status = "REJECTED"
                    pending.confirmed_at = utc_now_naive()
                    self._trace_decision(
                        db,
                        symbol=pending.symbol,
                        action="REJECT_PENDING",
                        reason_code="insufficient_cash_or_qty_below_min",
                        runtime_ctx=runtime_ctx,
                        mode=p_mode,
                        execution_check={
                            "eligible": False,
                            "pending_id": pending.id,
                        },
                        details={
                            "stage": "pending_validation",
                            "reason": "non_positive_quantity",
                            "qty": qty,
                        },
                        level="WARNING",
                    )
                    db.commit()
                    continue

                if p_mode == "live":
                    if trading_mode != "live":
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        self._trace_decision(
                            db,
                            symbol=pending.symbol,
                            action="REJECT_PENDING",
                            reason_code="live_execution_blocked_wrong_trading_mode",
                            runtime_ctx=runtime_ctx,
                            mode=p_mode,
                            execution_check={
                                "eligible": False,
                                "pending_id": pending.id,
                                "reason": "trading_mode_mismatch",
                            },
                            details={
                                "reason": "global_trading_mode_not_live",
                                "trading_mode": trading_mode,
                                "allow_live_trading": allow_live_trading,
                            },
                            level="WARNING",
                        )
                        db.commit()
                        continue

                    if not allow_live_trading:
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        self._trace_decision(
                            db,
                            symbol=pending.symbol,
                            action="REJECT_PENDING",
                            reason_code="live_execution_disabled",
                            runtime_ctx=runtime_ctx,
                            mode=p_mode,
                            execution_check={
                                "eligible": False,
                                "pending_id": pending.id,
                                "reason": "ALLOW_LIVE_TRADING=false",
                            },
                            details={
                                "reason": "global_execution_gate_closed",
                                "allow_live_trading": allow_live_trading,
                            },
                            level="WARNING",
                        )
                        db.commit()
                        continue

                    if is_test_symbol(pending.symbol):
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        self._trace_decision(
                            db,
                            symbol=pending.symbol,
                            action="REJECT_PENDING",
                            reason_code="live_test_symbol_blocked",
                            runtime_ctx=runtime_ctx,
                            mode=p_mode,
                            execution_check={
                                "eligible": False,
                                "pending_id": pending.id,
                            },
                            details={"reason": "test_symbol_live_forbidden"},
                            level="WARNING",
                        )
                        db.commit()
                        continue

                    log_to_db(
                        "INFO",
                        "live_trading",
                        f"pending_found id={pending.id} symbol={pending.symbol} side={pending.side} qty={qty:.8g}",
                        db=db,
                    )

                    # BUY preflight: min 60 EUR -> quote + ewentualna konwersja EUR->USDC + normalizacja qty.
                    if str(pending.side or "").upper() == "BUY":
                        from backend.quote_service import get_validated_quote

                        quote = get_validated_quote(
                            pending.symbol, binance_client=self.binance
                        )
                        live_price = float((quote or {}).get("price") or 0.0)
                        if live_price <= 0:
                            pending.status = "REJECTED"
                            pending.confirmed_at = utc_now_naive()
                            self._trace_decision(
                                db,
                                symbol=pending.symbol,
                                action="REJECT_PENDING",
                                reason_code="missing_binance_price",
                                runtime_ctx=runtime_ctx,
                                mode=p_mode,
                                execution_check={
                                    "eligible": False,
                                    "pending_id": pending.id,
                                },
                                details={
                                    "stage": "pre_trade_price",
                                    "symbol": pending.symbol,
                                },
                                level="ERROR",
                            )
                            db.commit()
                            continue

                        min_quote_notional, min_meta = (
                            self._resolve_min_buy_quote_notional(
                                pending.symbol,
                                config,
                            )
                        )
                        pending_notional = max(0.0, qty * live_price)
                        target_notional = max(min_quote_notional, pending_notional)

                        qty, qty_meta = self._normalize_buy_qty_for_exchange(
                            symbol=pending.symbol,
                            target_qty=(target_notional / live_price),
                            price=live_price,
                            min_quote_notional=target_notional,
                        )
                        target_notional = max(target_notional, qty * live_price)

                        log_to_db(
                            "INFO",
                            "live_trading",
                            (
                                "execution_started "
                                f"pending_id={pending.id} symbol={pending.symbol} side=BUY "
                                f"pre_trade_balance={self._load_live_balance_map()} "
                                f"quote_asset={min_meta.get('quote_asset')} "
                                f"required_quote_usdc={min_meta.get('required_quote_usdc') or min_meta.get('required_quote_eur')} "
                                f"target_notional={target_notional:.6f} "
                                f"min_buy_reference_eur={min_meta.get('min_buy_reference_eur')} "
                                f"eur_usdc_rate={float(min_meta.get('eur_usdc_rate') or 1.0):.8f}"
                            ),
                            db=db,
                        )

                        ensure_result = self._ensure_quote_balance_for_order(
                            db,
                            symbol=pending.symbol,
                            required_quote_notional=target_notional,
                            config=config,
                        )
                        if not ensure_result.get("ok"):
                            reason_code = str(
                                ensure_result.get("reason_code")
                                or "cash_insufficient_after_conversion_attempt"
                            )
                            pending.status = "REJECTED"
                            pending.confirmed_at = utc_now_naive()
                            self._trace_decision(
                                db,
                                symbol=pending.symbol,
                                action="REJECT_PENDING",
                                reason_code=reason_code,
                                runtime_ctx=runtime_ctx,
                                mode=p_mode,
                                execution_check={
                                    "eligible": False,
                                    "pending_id": pending.id,
                                },
                                details={
                                    "stage": "ensure_quote_balance_for_order",
                                    "ensure": ensure_result,
                                    "target_notional": target_notional,
                                    "qty_meta": qty_meta,
                                },
                                level="WARNING",
                            )
                            log_to_db(
                                "WARNING",
                                "live_trading",
                                f"final_buy_blocked pending_id={pending.id} reason={reason_code} details={ensure_result}",
                                db=db,
                            )
                            db.commit()
                            continue

                        if ensure_result.get("converted"):
                            log_to_db(
                                "INFO",
                                "live_trading",
                                (
                                    f"funding_conversion_filled pending_id={pending.id} "
                                    f"usdc_after={ensure_result.get('available_usdc_after')} "
                                    f"required_usdc={target_notional:.6f} "
                                    f"details={ensure_result}"
                                ),
                                db=db,
                            )
                        else:
                            log_to_db(
                                "INFO",
                                "live_trading",
                                (
                                    f"usdc_sufficient pending_id={pending.id} "
                                    f"available_usdc={ensure_result.get('available_usdc_after')} "
                                    f"required_usdc={target_notional:.6f}"
                                ),
                                db=db,
                            )
                    else:
                        # SELL: zachowaj dotychczasową normalizację qty do step_size
                        # BUY: diagnostyczne logi + last-resort floor przed wysłaniem
                        if str(pending.side or "").upper() == "BUY":
                            _avail_usdc_before = float(
                                ensure_result.get("available_usdc")
                                or ensure_result.get("available_usdc_after")
                                or 0.0
                            )
                            _funding_added = float(
                                ensure_result.get("funding_added_usdc") or 0.0
                            )
                            _avail_usdc_after = float(
                                ensure_result.get("available_usdc_after")
                                or (_avail_usdc_before + _funding_added)
                            )
                            _final_notional_pre = qty * live_price
                            log_to_db(
                                "INFO",
                                "live_trading",
                                (
                                    f"pre_order_diagnostics pending_id={pending.id} "
                                    f"symbol={pending.symbol} "
                                    f"required_quote_usdc={min_quote_notional:.4f} "
                                    f"available_usdc_before={_avail_usdc_before:.4f} "
                                    f"funding_added_usdc={_funding_added:.4f} "
                                    f"available_usdc_after_conversion={_avail_usdc_after:.4f} "
                                    f"final_order_qty={qty:.8g} "
                                    f"final_order_quote_usdc={_final_notional_pre:.4f} "
                                    f"final_order_notional_usdc={_final_notional_pre:.4f}"
                                ),
                                db=db,
                            )
                            # enforce_final_min_quote_usdc — OSTATNIA linia obrony
                            qty, _enforce_meta = enforce_final_min_quote_usdc(
                                qty=qty,
                                price=live_price,
                                required_min_notional=target_notional,
                                step_size=float(qty_meta.get("step_size") or 0.0),
                            )
                            if _enforce_meta.get("bumped"):
                                log_to_db(
                                    "WARNING",
                                    "live_trading",
                                    (
                                        f"qty_bumped_min_notional_guard pending_id={pending.id} "
                                        f"old_qty={_enforce_meta['old_qty']:.8g} "
                                        f"new_qty={qty:.8g} "
                                        f"required_min_notional={target_notional:.4f} "
                                        f"new_notional={qty * live_price:.4f}"
                                    ),
                                    db=db,
                                )
                        try:
                            _sym_info = (self.binance.get_allowed_symbols() or {}).get(
                                pending.symbol, {}
                            )
                            _step = float(_sym_info.get("step_size") or 0)
                            if _step > 0:
                                import math as _math

                                qty = _math.floor(qty / _step) * _step
                                _prec = max(0, int(round(-_math.log10(_step))))
                                qty = round(qty, _prec)
                        except Exception:
                            pass

                    # ——— LIVE: wykonaj przez Binance API ———
                    pending.status = "EXCHANGE_SUBMITTED"
                    log_to_db(
                        "INFO",
                        "live_trading",
                        (
                            f"pending_status_updated id={pending.id} "
                            f"status=EXCHANGE_SUBMITTED symbol={pending.symbol} side={pending.side}"
                        ),
                        db=db,
                    )
                    self._send_telegram_alert(
                        f"{pending.side} SUBMITTED: {pending.symbol}",
                        (
                            f"Zlecenie {pending.side} {pending.symbol} wysłane na giełdę. "
                            "Oczekiwanie na fill."
                        ),
                        force_send=True,
                    )
                    result = self.binance.place_order(
                        symbol=pending.symbol,
                        side=pending.side,
                        order_type="MARKET",
                        quantity=qty,
                    )
                    if not result or result.get("_error"):
                        err_msg = (
                            result.get("error_message", "") if result else ""
                        ) or "brak odpowiedzi"
                        log_to_db(
                            "ERROR",
                            "live_trading",
                            f"Binance place_order REJECTED dla {pending.symbol} {pending.side} qty={qty}: {err_msg}",
                            db=db,
                        )
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        # Gdy SELL jest rejected, odblokuj pozycję.
                        # Inaczej exit_reason_code zostaje w stanie pending.
                        _sell_pos = (
                            db.query(Position)
                            .filter(
                                Position.symbol == pending.symbol,
                                Position.mode == p_mode,
                                Position.exit_reason_code
                                == "pending_confirmed_execution",
                                Position.quantity > 0,
                            )
                            .first()
                        )
                        if _sell_pos is not None:
                            _sell_pos.exit_reason_code = None
                            # Przy insufficient balance pobierz realne saldo Binance.
                            if (
                                "insufficient" in err_msg.lower()
                                or "balance" in err_msg.lower()
                            ):
                                try:
                                    _balances = self.binance.get_balances() or []
                                    _sym = (pending.symbol or "").upper()
                                    _actual_qty = 0.0
                                    _base_asset = (
                                        _sym[:-3]
                                        if _sym.endswith("EUR")
                                        else (
                                            _sym[:-4]
                                            if _sym.endswith("USDC")
                                            else _sym[:-4]
                                        )
                                    )
                                    for _b in _balances:
                                        if (
                                            _b.get("asset", "") or ""
                                        ).upper() == _base_asset:
                                            _actual_qty = float(_b.get("free", 0) or 0)
                                            if (
                                                abs(
                                                    _actual_qty
                                                    - float(_sell_pos.quantity)
                                                )
                                                > 1e-8
                                            ):
                                                log_to_db(
                                                    "WARNING",
                                                    "live_trading",
                                                    f"Sync qty {pending.symbol}: DB={float(_sell_pos.quantity):.8g} → Binance={_actual_qty:.8g}",
                                                    db=db,
                                                )
                                                _sell_pos.quantity = _actual_qty
                                            break
                                    if _actual_qty <= 0:
                                        log_to_db(
                                            "WARNING",
                                            "live_trading",
                                            f"Pozycja {pending.symbol} nie istnieje juz na Binance; zamykam rekord DB po rejected SELL.",
                                            db=db,
                                        )
                                        _sell_pos.quantity = 0.0
                                        _sell_pos.exit_reason_code = "full_close"
                                except Exception as _sync_exc:
                                    log_exception(
                                        "live_trading",
                                        "Sync qty po rejected sell failed",
                                        _sync_exc,
                                        db=db,
                                    )
                        db.commit()
                        self._trace_decision(
                            db,
                            symbol=pending.symbol,
                            action="REJECT_PENDING",
                            reason_code="execution_rejected_by_exchange",
                            runtime_ctx=runtime_ctx,
                            mode=p_mode,
                            execution_check={
                                "eligible": False,
                                "pending_id": pending.id,
                            },
                            details={
                                "error": err_msg,
                                "qty": qty,
                                "side": pending.side,
                            },
                            level="ERROR",
                        )
                        continue
                    # Parsuj odpowiedź Binance i aktualizuj status zgodny z rzeczywistością
                    fills = result.get("fills", [])
                    binance_status = str(
                        result.get("status", "UNKNOWN") or "UNKNOWN"
                    ).upper()
                    if fills:
                        total_qty_filled = sum(float(f.get("qty", 0)) for f in fills)
                        total_cost_filled = sum(
                            float(f.get("price", 0)) * float(f.get("qty", 0))
                            for f in fills
                        )
                        exec_price = (
                            total_cost_filled / total_qty_filled
                            if total_qty_filled > 0
                            else float(result.get("price", 0) or pending.price or 0.0)
                        )
                        executed_qty = total_qty_filled
                    else:
                        exec_price = float(result.get("price", 0)) or float(
                            pending.price or 0.0
                        )
                        executed_qty = float(result.get("executedQty", 0) or 0.0)

                    qty = executed_qty if executed_qty > 0 else 0.0
                    _live_actual_fee = sum(float(f.get("commission", 0)) for f in fills)
                    _live_fee_asset = (
                        fills[0].get("commissionAsset", "") if fills else ""
                    )
                    _notional_filled = qty * exec_price
                    _side = str(pending.side or "ORDER").upper()

                    # Brak realnego filla: NIE twórz order/position i NIE komunikuj "kupiono"
                    if binance_status not in {"FILLED", "PARTIALLY_FILLED"} or qty <= 0:
                        if binance_status in {"NEW", "PENDING_NEW", "ACCEPTED", "ACK"}:
                            pending.status = "EXCHANGE_SUBMITTED"
                        elif binance_status in {
                            "REJECTED",
                            "EXPIRED",
                            "CANCELED",
                            "CANCELLED",
                        }:
                            pending.status = "REJECTED"
                        else:
                            pending.status = "FAILED"

                        log_to_db(
                            "INFO",
                            "live_trading",
                            (
                                f"order_not_filled_yet pending_id={pending.id} symbol={pending.symbol} "
                                f"status={binance_status} executed_qty={qty:.8g}"
                            ),
                            db=db,
                        )
                        self._send_telegram_alert(
                            f"{_side} STATUS={binance_status}: {pending.symbol}",
                            (
                                f"Zlecenie {_side} {pending.symbol} wysłane na giełdę, ale bez fill.\n"
                                f"status={binance_status}\n"
                                f"executed_qty={qty:.8g}"
                            ),
                            force_send=True,
                        )
                        db.commit()
                        continue

                    # Realny fill (FILLED/PARTIALLY_FILLED)
                    pending.status = (
                        "FILLED" if binance_status == "FILLED" else "PARTIALLY_FILLED"
                    )
                    logger.info(
                        f"✅ LIVE ORDER FILLED: {pending.side} {pending.symbol} qty={qty} @ {exec_price} fee={_live_actual_fee} {_live_fee_asset} status={binance_status}"
                    )
                    log_to_db(
                        "INFO",
                        "live_trading",
                        f"LIVE {pending.side} {pending.symbol} qty={qty:.8g} @ {exec_price:.6f} fee={_live_actual_fee:.8g} {_live_fee_asset}",
                        db=db,
                    )
                    log_to_db(
                        "INFO",
                        "live_trading",
                        (
                            f"final_buy_sent pending_id={pending.id} symbol={pending.symbol} "
                            f"qty={qty:.8g} status={binance_status}"
                        ),
                        db=db,
                    )
                    if binance_status == "FILLED":
                        self._send_telegram_alert(
                            f"{_side} FILLED: {pending.symbol}",
                            (
                                f"{_side} {pending.symbol} wykonane.\n"
                                f"Filled qty={qty:.8g}\n"
                                f"avg_price={exec_price:.6f}\n"
                                f"notional={_notional_filled:.2f}\n"
                                f"fee={_live_actual_fee:.6g} {_live_fee_asset}"
                            ),
                            force_send=True,
                        )
                    else:
                        self._send_telegram_alert(
                            f"{_side} PARTIALLY_FILLED: {pending.symbol}",
                            (
                                f"{_side} {pending.symbol} częściowo wykonane.\n"
                                f"Filled qty={qty:.8g}\n"
                                f"avg_price={exec_price:.6f}\n"
                                f"notional={_notional_filled:.2f}\n"
                                f"status=PARTIALLY_FILLED — sprawdź Binance"
                            ),
                            force_send=True,
                        )
                else:
                    _live_actual_fee = 0.0
                    _live_fee_asset = ""
                    # ——— DEMO: symulacja po aktualnej cenie rynkowej ———
                    exec_price = pending.price
                    ticker = self.binance.get_ticker_price(pending.symbol)
                    if ticker and ticker.get("price"):
                        exec_price = float(ticker["price"])
                    binance_status = "FILLED"  # DEMO: symulacja — zawsze wypełnione
                    # DEMO BUY: wymuszaj min notional floor
                    if (
                        str(pending.side or "").upper() == "BUY"
                        and float(exec_price or 0) > 0
                    ):
                        _demo_min_notional, _demo_meta = (
                            self._resolve_min_buy_quote_notional(pending.symbol, config)
                        )
                        if qty * float(exec_price) < _demo_min_notional:
                            _old_demo_qty = qty
                            qty = _demo_min_notional / float(exec_price)
                            log_to_db(
                                "INFO",
                                "demo_trading",
                                (
                                    f"demo_qty_bumped_min_notional pending_id={pending.id} "
                                    f"old_qty={_old_demo_qty:.8g} new_qty={qty:.8g} "
                                    f"min_notional={_demo_min_notional:.4f}"
                                ),
                                db=db,
                            )

                order = Order(
                    symbol=pending.symbol,
                    side=pending.side,
                    order_type=pending.order_type,
                    price=pending.price,
                    quantity=qty,
                    status=binance_status,  # LIVE: z Binance; DEMO: "FILLED"
                    mode=p_mode,
                    executed_price=exec_price,
                    executed_quantity=qty,
                    config_snapshot_id=pending.config_snapshot_id
                    or runtime_ctx.get("snapshot_id"),
                    entry_reason_code=(
                        "pending_confirmed_execution" if pending.side == "BUY" else None
                    ),
                    exit_reason_code=(
                        "pending_confirmed_execution"
                        if pending.side == "SELL"
                        else None
                    ),
                    timestamp=utc_now_naive(),
                )
                db.add(order)
                db.flush()

                notional = float(exec_price) * float(qty)
                taker_fee_rate = float(config.get("taker_fee_rate", 0.001))
                slippage_bps = float(config.get("slippage_bps", 5.0))
                spread_buffer_bps = float(config.get("spread_buffer_bps", 3.0))
                fee_cost_estimated = notional * taker_fee_rate
                slippage_cost = notional * (slippage_bps / 10000.0)
                spread_cost = notional * (spread_buffer_bps / 10000.0)

                # LIVE: rzeczywista prowizja z Binance fills; DEMO: szacunek
                if p_mode == "live" and _live_actual_fee > 0:
                    _quote = (
                        "EUR"
                        if str(pending.symbol).upper().endswith("EUR")
                        else (
                            "USDC"
                            if str(pending.symbol).upper().endswith("USDC")
                            else "USDT"
                        )
                    )
                    fee_cost_live = self._convert_fee_to_quote(
                        db,
                        fee_amount=float(_live_actual_fee),
                        fee_asset=str(_live_fee_asset or ""),
                        symbol=str(pending.symbol or ""),
                        exec_price=float(exec_price or 0.0),
                        quote_ccy=_quote,
                        notional=float(notional),
                    )
                    if fee_cost_live is not None and fee_cost_live >= 0:
                        fee_cost = float(fee_cost_live)
                        fee_notes = (
                            f"LIVE actual Binance commission ({_live_fee_asset}) "
                            f"converted_to_{_quote}"
                        )
                    else:
                        fee_cost = fee_cost_estimated
                        fee_notes = (
                            f"LIVE fee conversion failed ({_live_fee_asset}) "
                            f"fallback_estimate_{_quote}"
                        )
                else:
                    fee_cost = fee_cost_estimated
                    fee_notes = f"{p_mode} execution fee estimate"

                save_cost_entry(
                    db,
                    symbol=pending.symbol,
                    cost_type="taker_fee",
                    order_id=order.id,
                    expected_value=fee_cost_estimated,
                    actual_value=fee_cost,
                    notional=notional,
                    bps=taker_fee_rate * 10000.0,
                    config_snapshot_id=order.config_snapshot_id,
                    notes=fee_notes,
                )
                save_cost_entry(
                    db,
                    symbol=pending.symbol,
                    cost_type="slippage",
                    order_id=order.id,
                    expected_value=slippage_cost,
                    actual_value=slippage_cost,
                    notional=notional,
                    bps=slippage_bps,
                    config_snapshot_id=order.config_snapshot_id,
                    notes=f"{p_mode} execution slippage estimate",
                )
                save_cost_entry(
                    db,
                    symbol=pending.symbol,
                    cost_type="spread",
                    order_id=order.id,
                    expected_value=spread_cost,
                    actual_value=spread_cost,
                    notional=notional,
                    bps=spread_buffer_bps,
                    config_snapshot_id=order.config_snapshot_id,
                    notes=f"{p_mode} execution spread estimate",
                )

                position = (
                    db.query(Position)
                    .filter(
                        Position.symbol == pending.symbol,
                        Position.mode == p_mode,
                        Position.exit_reason_code.is_(None),
                    )
                    .first()
                )
                _closed_pos_id: Optional[int] = None  # zachowamy przed db.delete

                if pending.side == "BUY":
                    # Wylicz TP/SL z ATR na potrzeby exit quality tracking
                    _planned_tp = None
                    _planned_sl = None
                    _exit_plan = None
                    try:
                        _ctx = get_live_context(
                            db, pending.symbol, timeframe="1h", limit=120
                        )
                        if _ctx and _ctx.get("atr") and float(_ctx["atr"]) > 0:
                            _atr = float(_ctx["atr"])
                            _costs = estimate_trade_costs(config)
                            _plan = build_long_plan(
                                entry=exec_price,
                                atr=_atr,
                                costs=_costs,
                                rr1=2.0,
                                rr2=3.2,
                            )
                            _planned_tp = _plan.take_profit_2
                            _planned_sl = _plan.stop_loss
                            _exit_plan = {
                                "entry": _plan.entry,
                                "stop_loss": _plan.stop_loss,
                                "take_profit_1": _plan.take_profit_1,
                                "take_profit_2": _plan.take_profit_2,
                                "trailing_activation_price": _plan.trailing_activation_price,
                                "break_even_price": _plan.break_even_price,
                                "estimated_total_cost_pct": _costs.total_cost_pct,
                                "expected_hold_regime": "TREND_UP",
                            }
                    except Exception:
                        pass

                    if not position:
                        position = Position(
                            symbol=pending.symbol,
                            side="LONG",
                            entry_price=exec_price,
                            quantity=qty,
                            current_price=exec_price,
                            unrealized_pnl=0.0,
                            gross_pnl=0.0,
                            net_pnl=-(fee_cost + slippage_cost + spread_cost),
                            total_cost=fee_cost + slippage_cost + spread_cost,
                            fee_cost=fee_cost,
                            slippage_cost=slippage_cost,
                            spread_cost=spread_cost,
                            config_snapshot_id=order.config_snapshot_id,
                            entry_reason_code="pending_confirmed_execution",
                            mode=p_mode,
                            opened_at=utc_now_naive(),
                            planned_tp=_planned_tp,
                            planned_sl=_planned_sl,
                            mfe_price=exec_price,
                            mae_price=exec_price,
                            mfe_pnl=0.0,
                            mae_pnl=0.0,
                            highest_price_seen=exec_price,
                            exit_plan_json=(
                                json.dumps(_exit_plan) if _exit_plan else None
                            ),
                        )
                        db.add(position)
                    else:
                        total_qty = float(position.quantity) + qty
                        if total_qty > 0:
                            position.entry_price = (
                                (float(position.entry_price) * float(position.quantity))
                                + (exec_price * qty)
                            ) / total_qty
                        position.quantity = total_qty
                        position.current_price = exec_price
                        position.total_cost = (
                            float(position.total_cost or 0.0)
                            + fee_cost
                            + slippage_cost
                            + spread_cost
                        )
                        position.fee_cost = float(position.fee_cost or 0.0) + fee_cost
                        position.slippage_cost = (
                            float(position.slippage_cost or 0.0) + slippage_cost
                        )
                        position.spread_cost = (
                            float(position.spread_cost or 0.0) + spread_cost
                        )
                        position.net_pnl = float(position.net_pnl or 0.0) - (
                            fee_cost + slippage_cost + spread_cost
                        )
                        position.config_snapshot_id = (
                            order.config_snapshot_id or position.config_snapshot_id
                        )
                        if _planned_tp is not None:
                            position.planned_tp = _planned_tp
                        if _planned_sl is not None:
                            position.planned_sl = _planned_sl
                        position.highest_price_seen = max(
                            float(position.highest_price_seen or exec_price), exec_price
                        )
                        if _exit_plan:
                            position.exit_plan_json = json.dumps(_exit_plan)
                elif pending.side == "SELL":
                    gross_pnl = 0.0
                    if position and float(position.quantity) > 0:
                        sell_qty = min(float(position.quantity), qty)
                        gross_pnl = (
                            exec_price - float(position.entry_price)
                        ) * sell_qty
                        position.quantity = float(position.quantity) - sell_qty
                        position.current_price = exec_price
                        position.unrealized_pnl = (
                            exec_price - float(position.entry_price)
                        ) * float(position.quantity)
                        position.gross_pnl = (
                            float(position.gross_pnl or 0.0) + gross_pnl
                        )
                        position.total_cost = (
                            float(position.total_cost or 0.0)
                            + fee_cost
                            + slippage_cost
                            + spread_cost
                        )
                        position.fee_cost = float(position.fee_cost or 0.0) + fee_cost
                        position.slippage_cost = (
                            float(position.slippage_cost or 0.0) + slippage_cost
                        )
                        position.spread_cost = (
                            float(position.spread_cost or 0.0) + spread_cost
                        )
                        position.net_pnl = float(position.gross_pnl or 0.0) - float(
                            position.total_cost or 0.0
                        )
                        if float(position.quantity) <= 0:
                            # --- Exit Quality snapshot ---
                            self._save_exit_quality(db, position, exec_price, config)
                            # SOFT-CLOSE: nie usuwaj rekordu z DB, tylko oznacz jako zamknięty
                            # To zapobiega tymczasowym niezgodnościom podczas reconcile gdy DB
                            # nie zdołało commitnąć zanim sprawdzamy Binance.
                            position.quantity = 0.0  # explicit zero
                            position.exit_reason_code = (
                                "full_close"  # mark as closed, not deleted
                            )
                            _closed_pos_id = (
                                position.id
                            )  # pozycja wciąż istnieje w DB dla audia
                            # updated_at jest auto-updated przez SQLAlchemy onupdate
                        else:
                            # Częściowe zamknięcie — inkrementuj licznik i aktywuj trailing
                            position.partial_take_count = (
                                int(position.partial_take_count or 0) + 1
                            )
                    else:
                        # Brak pozycji — zapisujemy zlecenie, ale bez zmian pozycji.
                        pass
                    expected_edge = float(pending.price or exec_price) * float(
                        config.get("min_edge_multiplier", 2.5)
                    )
                    attach_costs_to_order(
                        db,
                        order=order,
                        gross_pnl=gross_pnl,
                        expected_edge=expected_edge,
                        config_snapshot_id=order.config_snapshot_id,
                        exit_reason_code="pending_confirmed_execution",
                    )
                if pending.side == "BUY":
                    attach_costs_to_order(
                        db,
                        order=order,
                        gross_pnl=0.0,
                        expected_edge=float(pending.price or exec_price)
                        * float(config.get("min_edge_multiplier", 2.5)),
                        config_snapshot_id=order.config_snapshot_id,
                        entry_reason_code="pending_confirmed_execution",
                    )

                alert = Alert(
                    alert_type="SIGNAL",
                    severity="INFO",
                    title=f"{p_mode.upper()} EXEC {pending.side} {pending.symbol}",
                    message=f"{pending.side} {pending.symbol} qty={qty} exec_price={exec_price}. Powód: {pending.reason or '--'}",
                    symbol=pending.symbol,
                    is_sent=True,
                    timestamp=utc_now_naive(),
                )
                db.add(alert)

                if p_mode != "live":
                    pending.status = "FILLED"
                elif pending.status not in {"FILLED", "PARTIALLY_FILLED"}:
                    pending.status = "FILLED"
                if not pending.confirmed_at:
                    pending.confirmed_at = utc_now_naive()
                log_to_db(
                    "INFO",
                    "live_trading",
                    f"pending_status_updated id={pending.id} status={pending.status} order_id={order.id}",
                    db=db,
                )

                self._trace_decision(
                    db,
                    symbol=pending.symbol,
                    action="EXECUTE_PENDING",
                    reason_code="pending_confirmed_execution",
                    runtime_ctx=runtime_ctx,
                    mode=p_mode,
                    execution_check={
                        "eligible": True,
                        "pending_id": pending.id,
                        "quantity": qty,
                        "exec_price": exec_price,
                    },
                    details={
                        "side": pending.side,
                        "reason": pending.reason,
                        "order_id": order.id,
                    },
                    order_id=order.id,
                    position_id=(
                        _closed_pos_id
                        if _closed_pos_id is not None
                        else (position.id if position else None)
                    ),
                )

                executed_count += 1
            except Exception as exc:
                log_exception(
                    f"{p_mode}_trading",
                    f"Błąd wykonania pending order {pending.id}",
                    exc,
                    db=db,
                )
                try:
                    pending.status = "REJECTED"
                    pending.confirmed_at = utc_now_naive()
                    self._trace_decision(
                        db,
                        symbol=pending.symbol,
                        action="REJECT_PENDING",
                        reason_code="temporary_execution_error",
                        runtime_ctx=runtime_ctx,
                        mode=p_mode,
                        execution_check={"eligible": False, "pending_id": pending.id},
                        details={
                            "error": str(exc),
                            "governance_freeze_critical_only": True,
                        },
                        level="WARNING",
                    )
                    log_to_db(
                        "WARNING",
                        "live_trading",
                        f"pending_status_updated id={pending.id} status=REJECTED reason=temporary_execution_error",
                        db=db,
                    )
                except Exception:
                    pass
            finally:
                self._release_inflight_slot(p_mode, pending.symbol, pending.side)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_exception(
                "demo_trading", "Błąd commit wykonania pending orders", exc, db=db
            )
            return

        if executed_count:
            logger.info(f"✅ Wykonano potwierdzone transakcje: {executed_count}")

    def _save_exit_quality(
        self, db: Session, position, exit_price: float, config: dict
    ) -> None:
        """Zapisz ExitQuality snapshot przy zamknięciu pozycji."""
        try:
            entry = float(position.entry_price or 0)
            qty = (
                float(position.quantity or 0)
                if float(position.quantity or 0) > 0
                else float(getattr(position, "_orig_qty", 0) or 0)
            )
            # qty może być 0 bo już odjęto — weźmy z gross_pnl / move
            move = exit_price - entry
            if qty <= 0 and move != 0 and position.gross_pnl:
                qty = abs(float(position.gross_pnl) / move)

            gross = float(position.gross_pnl or 0)
            total_cost = float(position.total_cost or 0)
            net = gross - total_cost
            mfe_pnl = float(position.mfe_pnl or 0)
            mae_pnl = float(position.mae_pnl or 0)
            planned_tp = getattr(position, "planned_tp", None)
            planned_sl = getattr(position, "planned_sl", None)

            # Czy dotarło do TP?
            tp_hit = False
            tp_near_miss_pct = None
            if planned_tp is not None and entry > 0:
                tp_range = planned_tp - entry
                if tp_range > 0 and position.mfe_price is not None:
                    mfe_above_entry = float(position.mfe_price) - entry
                    tp_near_miss_pct = (mfe_above_entry / tp_range) * 100.0
                    tp_hit = tp_near_miss_pct >= 100.0

            # Czy dotarło do SL?
            sl_hit = False
            if planned_sl is not None and position.mae_price is not None:
                sl_hit = float(position.mae_price) <= float(planned_sl)

            # R:R
            expected_rr = None
            realized_rr = None
            if planned_tp is not None and planned_sl is not None and entry > 0:
                risk = entry - float(planned_sl)
                reward = float(planned_tp) - entry
                if risk > 0:
                    expected_rr = reward / risk
                    realized_rr = net / (risk * max(qty, 1e-12))

            # Oddany zysk
            gave_back_pct = None
            if mfe_pnl > 0:
                gave_back_pct = ((mfe_pnl - net) / mfe_pnl) * 100.0

            # Edge vs cost
            edge_vs_cost = (net / total_cost) if total_cost > 0 else None

            # Czas trwania
            duration_seconds = None
            if position.opened_at:
                duration_seconds = (
                    utc_now_naive() - position.opened_at
                ).total_seconds()

            eq = ExitQuality(
                symbol=position.symbol,
                mode=position.mode or "demo",
                side=position.side or "LONG",
                entry_price=entry,
                exit_price=exit_price,
                quantity=qty,
                planned_tp=planned_tp,
                planned_sl=planned_sl,
                mfe_price=float(position.mfe_price) if position.mfe_price else None,
                mae_price=float(position.mae_price) if position.mae_price else None,
                gross_pnl=gross,
                net_pnl=net,
                total_cost=total_cost,
                mfe_pnl=mfe_pnl,
                mae_pnl=mae_pnl,
                gave_back_pct=gave_back_pct,
                tp_hit=tp_hit,
                tp_near_miss_pct=tp_near_miss_pct,
                sl_hit=sl_hit,
                expected_rr=expected_rr,
                realized_rr=realized_rr,
                edge_vs_cost=edge_vs_cost,
                duration_seconds=duration_seconds,
                config_snapshot_id=position.config_snapshot_id,
                exit_reason_code=position.exit_reason_code,
                closed_at=utc_now_naive(),
            )
            db.add(eq)
        except Exception as exc:
            log_exception("exit_quality", "Błąd zapisu ExitQuality", exc, db=db)

    def _sync_binance_positions(self, db: Session) -> None:
        """
        Periodyczny monitoring: porównaj pozycje LIVE w DB z rzeczywistymi
        saldami spot na Binance. Loguj niezgodności jako WARNING.
        Auto-koryguj tylko pozycje, których nie ma już na Binance.
        """
        tc = self._runtime_context(db)["config"]
        if tc.get("trading_mode", "demo") != "live":
            return
        if not tc.get("allow_live_trading"):
            return

        # Guard: jeśli mamy świeże pending CONFIRMED/PENDING, odrocz sync żeby
        # nie raportować fałszywego mismatch w oknie Binance execution -> DB commit.
        sync_grace_seconds = int(tc.get("sync_pending_grace_seconds", 45))
        pending_inflight = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "live",
                PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)),
                PendingOrder.created_at
                >= utc_now_naive() - timedelta(seconds=sync_grace_seconds),
            )
            .count()
        )
        if pending_inflight > 0:
            save_decision_trace(
                db,
                symbol="PORTFOLIO",
                mode="live",
                action_type="SKIP",
                reason_code="sync_pending_db_commit",
                strategy_name="sync_monitor",
                payload={
                    "pending_inflight": pending_inflight,
                    "sync_grace_seconds": sync_grace_seconds,
                },
            )
            return

        try:
            balances = self.binance.get_balances()
        except Exception as exc:
            log_exception("binance_sync", "Błąd pobierania saldów Binance", exc, db=db)
            return
        if not balances:
            return

        # Zbuduj mapę asset→quantity z Binance
        # Segreguj: quote currencies (EUR/USDC/USDT), fee assets (BNB), tracked assets
        binance_map: dict[str, float] = {}
        for b in balances:
            asset = b.get("asset", "")
            total = float(b.get("total", 0))
            if total > 0:
                if asset not in ("EUR", "USDC", "USDT"):
                    binance_map[asset] = total

        # Pobierz LIVE pozycje z DB (tylko otwarte)
        db_positions = (
            db.query(Position)
            .filter(
                Position.mode == "live",
                Position.exit_reason_code.is_(None),
                Position.quantity > 0,
            )
            .all()
        )
        db_map: dict[str, float] = {}
        for pos in db_positions:
            # Wyciągnij base asset z symbolu (np. BTCEUR → BTC, ETHUSDC → ETH)
            sym = pos.symbol or ""
            base = sym.replace("EUR", "").replace("USDC", "").replace("USDT", "")
            if base:
                db_map[base] = db_map.get(base, 0.0) + float(pos.quantity or 0)

        # Minimalna wartość (EUR) żeby niezgodność była raportowana — pomijamy dust
        _min_notional = float(tc.get("min_order_notional", 25.0))
        _bnb_dust_threshold = 0.002  # pył BNB fee (≈ 0.06 EUR)

        # Helper: get latest price for asset
        def _get_asset_price(asset_name: str) -> float | None:
            for _quote in ("EUR", "USDC", "USDT"):
                _md = (
                    db.query(MarketData)
                    .filter(MarketData.symbol == f"{asset_name}{_quote}")
                    .order_by(MarketData.timestamp.desc())
                    .first()
                )
                if _md and _md.price:
                    return float(_md.price)
            return None

        def _reconcile_missing_asset(asset_name: str, price_eur: float | None) -> None:
            reconciled = 0
            for _pos in db_positions:
                _sym = _pos.symbol or ""
                _base = _sym.replace("EUR", "").replace("USDC", "").replace("USDT", "")
                if _base != asset_name or float(_pos.quantity or 0) <= 0:
                    continue
                _prev_qty = float(_pos.quantity or 0)
                _pos.quantity = 0.0
                if price_eur is not None:
                    _pos.current_price = price_eur
                _pos.exit_reason_code = "full_close"
                reconciled += 1
                log_to_db(
                    "WARNING",
                    "binance_sync",
                    f"Auto-reconcile {asset_name}: Binance=0, DB={_prev_qty:.8g}; zamykam rekord pozycji {_sym}.",
                    db=db,
                )
            if reconciled:
                save_decision_trace(
                    db,
                    symbol=f"{asset_name}EUR",
                    mode="live",
                    action_type="RECONCILE",
                    reason_code="sync_auto_closed_missing_exchange_asset",
                    strategy_name="sync_monitor",
                    payload={"asset": asset_name, "reconciled_positions": reconciled},
                )

        # Porównaj tracked assets (BTC, ETH, itp)
        mismatches = []
        all_assets = set(list(binance_map.keys()) + list(db_map.keys()))
        for asset in sorted(all_assets):
            binance_qty = binance_map.get(asset, 0.0)
            db_qty = db_map.get(asset, 0.0)
            if abs(binance_qty - db_qty) > max(1e-6, db_qty * 0.01):
                # Sprawdź wartość niezgodności (pomijamy dust poniżej min_notional)
                mismatch_qty = abs(binance_qty - db_qty)
                price_eur = _get_asset_price(asset)

                # Jeśli znamy cenę i wartość jest poniżej progu — to dust, pomijamy
                if price_eur is not None and mismatch_qty * price_eur < _min_notional:
                    save_decision_trace(
                        db,
                        symbol=f"{asset}EUR",
                        mode="live",
                        action_type="SKIP",
                        reason_code="sync_ignored_dust_residual",
                        strategy_name="sync_monitor",
                        payload={
                            "asset": asset,
                            "binance_qty": binance_qty,
                            "db_qty": db_qty,
                            "mismatch_qty": mismatch_qty,
                            "mismatch_value_eur": mismatch_qty * price_eur,
                            "min_notional": _min_notional,
                        },
                    )
                    continue
                if binance_qty <= 0 and db_qty > 0:
                    _reconcile_missing_asset(asset, price_eur)
                    continue
                # Jeśli cena nieznana (brak klines) I bot nie ma tej pozycji w DB
                # (db_qty==0) — asset jest remnant/leftover, nie jest śledzoną pozycją
                if price_eur is None and db_qty == 0:
                    save_decision_trace(
                        db,
                        symbol=f"{asset}EUR",
                        mode="live",
                        action_type="SKIP",
                        reason_code="sync_ignored_dust_residual",
                        strategy_name="sync_monitor",
                        payload={
                            "asset": asset,
                            "binance_qty": binance_qty,
                            "db_qty": db_qty,
                            "note": "unknown_price_no_db_position",
                        },
                    )
                    continue
                # To jest rzeczywista niezgodność
                save_decision_trace(
                    db,
                    symbol=f"{asset}EUR",
                    mode="live",
                    action_type="ALERT",
                    reason_code="sync_detected_real_mismatch",
                    strategy_name="sync_monitor",
                    payload={
                        "asset": asset,
                        "binance_qty": binance_qty,
                        "db_qty": db_qty,
                    },
                )
                mismatches.append(
                    {
                        "asset": asset,
                        "binance_qty": binance_qty,
                        "db_qty": db_qty,
                        "reason_code": "real_position_mismatch",
                    }
                )

        bnb_balance = binance_map.get("BNB", 0.0)
        # Sprawdź BNB fee residual — jeśli jest znaczący BNB a nie ma BNB pozycji, to fee remnant
        if bnb_balance > _bnb_dust_threshold and db_map.get("BNB", 0.0) == 0.0:
            bnb_price = _get_asset_price("BNB")
            bnb_value = (
                bnb_balance * (bnb_price or 25.0) if bnb_price else bnb_balance * 25.0
            )
            if bnb_value < _min_notional:
                # BNB fee dust — ignoruj
                save_decision_trace(
                    db,
                    symbol="BNBEUR",
                    mode="live",
                    action_type="SKIP",
                    reason_code="sync_ignored_fee_asset_residual",
                    strategy_name="sync_monitor",
                    payload={
                        "asset": "BNB",
                        "binance_qty": bnb_balance,
                        "value_eur": bnb_value,
                        "min_notional": _min_notional,
                    },
                )
                pass
            else:
                # BNB residual poza dust — raportuj ale z innym kodem
                save_decision_trace(
                    db,
                    symbol="BNBEUR",
                    mode="live",
                    action_type="ALERT",
                    reason_code="sync_detected_real_mismatch",
                    strategy_name="sync_monitor",
                    payload={
                        "asset": "BNB",
                        "binance_qty": bnb_balance,
                        "db_qty": 0.0,
                        "note": "bnb_fee_residual_above_notional",
                    },
                )
                mismatches.append(
                    {
                        "asset": "BNB",
                        "binance_qty": bnb_balance,
                        "db_qty": 0.0,
                        "reason_code": "bnb_fee_residual",
                    }
                )

        # Formatuj dla Telegram (compat with previous format dla throttlera)
        mismatch_strs = []
        for m in mismatches:
            mismatch_strs.append(
                f"{m['asset']}: Binance={m['binance_qty']:.8g} DB={m['db_qty']:.8g}"
            )

        if mismatch_strs:
            now = utc_now_naive()
            signature = "|".join(mismatch_strs[:10])

            # Throttle + repeat count
            if signature not in self._sync_mismatch_repeat_count:
                self._sync_mismatch_repeat_count[signature] = 1
            else:
                self._sync_mismatch_repeat_count[signature] += 1

            repeat_count = self._sync_mismatch_repeat_count.get(signature, 1)

            # Sprawdzenie cooldown + throttler
            should_send = self._sync_mismatch_throttler.should_send(signature)

            if should_send or repeat_count > 5:  # Zawsze wyślij jeśli repeat > 5
                msg_obj = format_sync_mismatch_message(
                    mismatches=mismatch_strs,
                    repeat_count=repeat_count,
                )
                formatted_msg = msg_obj.format_telegram()

                log_to_db(
                    "WARNING" if repeat_count <= 3 else "ERROR",
                    "binance_sync",
                    f"Niezgodność (x{repeat_count}): {signature}",
                    db=db,
                )
                logger.warning(f"⚠️ Sync mismatch (x{repeat_count}): {signature}")
                self._send_telegram_alert(msg_obj.title, formatted_msg)
                self._sync_mismatch_throttler.track_sent(signature, msg_obj)

                # Wyczyść licznik po wysłaniu
                if repeat_count > 5:
                    self._sync_mismatch_repeat_count[signature] = 0
        else:
            self._last_binance_mismatch_signature = None

    def _mark_to_market_positions(self, db: Session, mode: str = "demo") -> None:
        """
        Aktualizuj `current_price` i `unrealized_pnl` dla otwartych pozycji na bazie ostatnich MarketData.
        """
        try:
            positions = (
                db.query(Position)
                .filter(Position.mode == mode, Position.exit_reason_code.is_(None))
                .all()
            )
            if not positions:
                return

            price_cache: dict[str, float] = {}
            updated = 0
            for p in positions:
                sym = (p.symbol or "").strip().upper()
                if not sym:
                    continue

                price = price_cache.get(sym)
                if price is None:
                    latest = (
                        db.query(MarketData)
                        .filter(MarketData.symbol == sym)
                        .order_by(MarketData.timestamp.desc())
                        .first()
                    )
                    if latest and latest.price is not None:
                        try:
                            price = float(latest.price)
                        except Exception:
                            price = None
                    if price is None:
                        ticker = self.binance.get_ticker_price(sym)
                        if ticker and ticker.get("price"):
                            try:
                                price = float(ticker["price"])
                            except Exception:
                                price = None
                    if price is not None:
                        price_cache[sym] = price

                if price is None:
                    continue

                p.current_price = price
                if p.entry_price is not None and p.quantity is not None:
                    entry = float(p.entry_price)
                    qty = float(p.quantity)
                    is_short = (p.side or "").upper() == "SHORT"
                    if is_short:
                        p.unrealized_pnl = (entry - price) * qty
                    else:
                        p.unrealized_pnl = (price - entry) * qty

                    # --- MFE / MAE tracking ---
                    cur_pnl = float(p.unrealized_pnl)
                    if is_short:
                        if p.mfe_price is None or price < p.mfe_price:
                            p.mfe_price = price
                            p.mfe_pnl = cur_pnl
                        if p.mae_price is None or price > p.mae_price:
                            p.mae_price = price
                            p.mae_pnl = cur_pnl
                    else:
                        if p.mfe_price is None or price > p.mfe_price:
                            p.mfe_price = price
                            p.mfe_pnl = cur_pnl
                        if p.mae_price is None or price < p.mae_price:
                            p.mae_price = price
                            p.mae_pnl = cur_pnl
                updated += 1

            if updated:
                db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            log_exception("collector", "Błąd mark-to-market pozycji", exc, db=db)

    def _persist_demo_snapshot_if_due(self, db: Session, force: bool = False) -> None:
        """
        Zapisz snapshot equity do wykresów co `ACCOUNT_SNAPSHOT_INTERVAL_SECONDS`.
        """
        try:
            interval_s = int(os.getenv("ACCOUNT_SNAPSHOT_INTERVAL_SECONDS", "60"))
        except Exception:
            interval_s = 60

        now = utc_now_naive()
        if not force and self.last_snapshot_ts:
            if (now - self.last_snapshot_ts).total_seconds() < float(interval_s):
                return

        try:
            quote_ccy = get_demo_quote_ccy()
            state = compute_demo_account_state(db, quote_ccy=quote_ccy, now=now)
            snap = AccountSnapshot(
                mode="demo",
                equity=float(state.get("equity") or 0.0),
                free_margin=float(state.get("cash") or 0.0),
                used_margin=0.0,
                margin_level=0.0,
                balance=float(state.get("cash") or 0.0),
                unrealized_pnl=float(state.get("unrealized_pnl") or 0.0),
                timestamp=now,
            )
            db.add(snap)
            db.commit()
            self.last_snapshot_ts = now
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            log_exception("collector", "Błąd zapisu AccountSnapshot (DEMO)", exc, db=db)

    def _persist_live_snapshot_if_due(self, db: Session, force: bool = False) -> None:
        """
        Zapisz snapshot equity LIVE do wykresów co `ACCOUNT_SNAPSHOT_INTERVAL_SECONDS`.
        Korzysta z _build_live_spot_portfolio (rzeczywiste saldo Binance).
        """
        try:
            interval_s = int(os.getenv("ACCOUNT_SNAPSHOT_INTERVAL_SECONDS", "60"))
        except Exception:
            interval_s = 60

        now = utc_now_naive()
        if not force and self.last_live_snapshot_ts:
            if (now - self.last_live_snapshot_ts).total_seconds() < float(interval_s):
                return

        try:
            from backend.routers.portfolio import _build_live_spot_portfolio

            live_data = _build_live_spot_portfolio(db)
            if live_data.get("error"):
                # Brak kluczy Binance lub timeout — nie zapisuj pustego snapshotu
                return
            equity = float(live_data.get("total_equity_eur") or 0.0)
            free_cash = float(live_data.get("free_cash_eur") or 0.0)
            snap = AccountSnapshot(
                mode="live",
                equity=equity,
                free_margin=free_cash,
                used_margin=max(0.0, equity - free_cash),
                margin_level=0.0,
                balance=equity,
                unrealized_pnl=0.0,
                timestamp=now,
            )
            db.add(snap)
            db.commit()
            self.last_live_snapshot_ts = now
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            log_exception("collector", "Błąd zapisu AccountSnapshot (LIVE)", exc, db=db)

    # ------------------------------------------------------------------
    # _demo_trading — orkiestrator (wydzielone etapy)
    # ------------------------------------------------------------------

    def _demo_trading(self, db: Session, mode: str = "demo"):
        self._active_mode = mode
        runtime_ctx = self._runtime_context(db)
        config = runtime_ctx["config"]

        if mode == "demo":
            enabled = bool(config.get("demo_trading_enabled"))
            if not enabled:
                return
        elif mode == "live":
            if not bool(config.get("allow_live_trading")):
                return
            if not bool(config.get("kill_switch_enabled", True)):
                log_to_db(
                    "WARNING",
                    "live_trading",
                    "kill_switch_enabled=false — LIVE trading wyłączony",
                    db=db,
                )
                return
        else:
            return

        now = utc_now_naive()
        tc = self._load_trading_config(db, config, runtime_ctx, now, mode=mode)
        if tc is None:
            return

        if mode == "live":
            cleaned_watchlist = [s for s in self.watchlist if not is_test_symbol(s)]
            if len(cleaned_watchlist) != len(self.watchlist):
                removed = sorted(set(self.watchlist) - set(cleaned_watchlist))
                self.watchlist = cleaned_watchlist
                log_to_db(
                    "WARNING",
                    "live_trading",
                    f"live_watchlist_test_symbols_removed removed={removed}",
                    db=db,
                )

        # 0) Sprawdź enabled_strategies — kill switch
        enabled_strats = tc.get("enabled_strategies", ["default"])
        if not enabled_strats or "default" not in enabled_strats:
            log_to_db(
                "WARNING",
                "demo_trading",
                f"Strategia 'default' wyłączona w enabled_strategies={enabled_strats} — pomijam cykl demo.",
                db=db,
            )
            return

        # 1) Exit management — TP/SL/trailing
        self._check_exits(db, tc)

        # 1b) HOLD — sprawdź czy osiągnięto cel wartości
        self._check_hold_targets(db, tc)

        # 1b2) AUTO-GOALS — ustaw planned_tp/sl dla pozycji bez celu (AI-driven)
        self._auto_set_position_goals(db, tc)

        # 1c) Rotacja kapitału — jeśli brak wolnych środków, zamknij najgorszą pozycję
        rotated = self._maybe_rotate_capital(db, tc)
        if rotated:
            # Odśwież konfigurację tradingową po zwolnieniu kapitału
            db.flush()
            tc = self._load_trading_config(db, config, runtime_ctx, now, mode=mode)
            if tc is None:
                return

        # 2) Nowe wejścia — screening + gating
        entries = self._screen_entry_candidates(db, tc)

        # 2b) Telegram status alert — co 30 min: statystyki pracy bota zamiast "bezczynność"
        if entries == 0:
            idle_interval = 1800  # 30 min
            if (
                not self._last_idle_alert_ts
                or (now - self._last_idle_alert_ts).total_seconds() > idle_interval
            ):
                self._last_idle_alert_ts = now

                # Zbierz statystyki
                aggressiveness = tc.get("aggressiveness", "balanced")
                pos_count = len(tc.get("positions", []))
                max_pos = tc.get("max_open_positions", 5)

                # Ostatnie 30 min: ile kandydatów, ile odrzucono, średnia confidence
                cutoff = now - timedelta(minutes=30)
                recent_traces = (
                    db.query(DecisionTrace)
                    .filter(
                        DecisionTrace.mode == mode, DecisionTrace.timestamp >= cutoff
                    )
                    .all()
                )

                considered_count = len(
                    [t for t in recent_traces if t.action_type == "skip"]
                )
                confidence_vals = []
                skip_reasons_count: Dict[str, int] = {}

                for trace in recent_traces:
                    if trace.action_type == "skip":
                        reason = trace.reason_code or "unknown"
                        skip_reasons_count[reason] = (
                            skip_reasons_count.get(reason, 0) + 1
                        )
                    # DecisionTrace nie ma kolumny confidence — pomijamy

                if confidence_vals:
                    avg_confidence = sum(confidence_vals) / len(confidence_vals)
                else:
                    # Fallback: DecisionTrace nie niesie confidence, więc licz z najnowszych sygnałów.
                    recent_signals = (
                        db.query(Signal)
                        .filter(Signal.timestamp >= cutoff)
                        .order_by(Signal.timestamp.desc())
                        .limit(100)
                        .all()
                    )
                    sig_vals = [
                        float(s.confidence)
                        for s in recent_signals
                        if s.confidence is not None
                    ]
                    avg_confidence = sum(sig_vals) / len(sig_vals) if sig_vals else 0.0

                # Czasy ostatnich akcji
                last_buy_trace = (
                    db.query(DecisionTrace)
                    .filter(
                        DecisionTrace.mode == mode,
                        DecisionTrace.action_type.in_(["buy", "open"]),
                    )
                    .order_by(DecisionTrace.timestamp.desc())
                    .first()
                )
                last_sell_trace = (
                    db.query(DecisionTrace)
                    .filter(
                        DecisionTrace.mode == mode,
                        DecisionTrace.action_type.in_(["sell", "close"]),
                    )
                    .order_by(DecisionTrace.timestamp.desc())
                    .first()
                )

                last_entry_minutes = None
                last_exit_minutes = None
                if last_buy_trace:
                    delta = (now - last_buy_trace.timestamp).total_seconds() / 60
                    last_entry_minutes = int(delta) if delta < 10000 else None
                if last_sell_trace:
                    delta = (now - last_sell_trace.timestamp).total_seconds() / 60
                    last_exit_minutes = int(delta) if delta < 10000 else None

                # Stwórz ładny komunikat
                msg_obj = format_status_message(
                    mode=mode,
                    positions_count=pos_count,
                    max_positions=max_pos,
                    watchlist_count=len(self.watchlist),
                    aggressiveness=aggressiveness,
                    candidates_considered=considered_count,
                    candidates_skipped=considered_count,
                    skip_reasons=skip_reasons_count,
                    avg_confidence=avg_confidence,
                    last_entry_minutes_ago=last_entry_minutes,
                    last_exit_minutes_ago=last_exit_minutes,
                    heartbeat_ok=True,
                )

                formatted_msg = msg_obj.format_telegram()
                self._send_telegram_alert(msg_obj.title, formatted_msg)

        # 3) Globalny hamulec strat
        self._apply_daily_loss_brake(db, tc)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_exception("demo_trading", "Błąd commit demo_trading", exc, db=db)
            return
        finally:
            self._active_mode = None

    # ------------------------------------------------------------------
    # Etap 0: ładowanie konfiguracji tradingowej
    # ------------------------------------------------------------------

    def _load_trading_config(
        self, db: Session, config: dict, runtime_ctx: dict, now, mode: str = "demo"
    ) -> dict | None:
        """Zwraca spłaszczony dict z parametrami do tradingu, lub None jeśli brak danych."""
        demo_quote_ccy = get_demo_quote_ccy()

        if mode == "live":
            # LIVE: użyj QUOTE_CURRENCY_MODE żeby wybrać właściwą walutę quote.
            # get_demo_quote_ccy() domyślnie zwraca "EUR" gdy brak DEMO_QUOTE_CCY,
            # co powoduje że screener ignoruje pary USDC (endswith("EUR") = False).
            _qcm_live = os.getenv("QUOTE_CURRENCY_MODE", "").strip().upper()
            if _qcm_live == "USDC":
                demo_quote_ccy = "USDC"
            elif _qcm_live == "EUR":
                demo_quote_ccy = "EUR"
            elif _qcm_live == "BOTH":
                # Przy BOTH używamy PRIMARY_QUOTE jako głównej quote waluty do screeningu
                demo_quote_ccy = (
                    os.getenv("PRIMARY_QUOTE", "EUR").strip().upper() or "EUR"
                )
            # demo_quote_ccy pozostaje z get_demo_quote_ccy() jeśli brak QUOTE_CURRENCY_MODE
            # LIVE: kapitał z Binance API
            balances = self.binance.get_balances() or []
            cash = 0.0
            for b in balances:
                if (b.get("asset") or "").upper() == demo_quote_ccy.replace(
                    "EUR", "EUR"
                ).replace("USDC", "USDC"):
                    # asset = "EUR" or "USDC"
                    cash = float(b.get("free", 0) or 0)
                    break
            # Wartość otwartych pozycji live z DB
            live_positions_db = (
                db.query(Position)
                .filter(Position.mode == "live", Position.exit_reason_code.is_(None))
                .all()
            )
            positions_value = 0.0
            for p in live_positions_db:
                try:
                    positions_value += float(
                        p.current_price or p.entry_price or 0
                    ) * float(p.quantity or 0)
                except Exception:
                    pass
            equity = cash + positions_value
            initial_balance = max(equity, 1.0)  # unikamy dzielenia przez 0
            account_state = {
                "initial_balance": initial_balance,
                "cash": cash,
                "equity": equity,
                "unrealized_pnl": sum(
                    float(p.unrealized_pnl or 0) for p in live_positions_db
                ),
                "realized_pnl_24h": 0.0,
            }
        else:
            account_state = compute_demo_account_state(
                db, quote_ccy=demo_quote_ccy, now=now
            )
            initial_balance = float(
                account_state.get("initial_balance")
                or float(os.getenv("DEMO_INITIAL_BALANCE", "10000"))
            )
            cash = float(account_state.get("cash") or initial_balance)
            equity = float(account_state.get("equity") or cash)
        reserved_cash = 0.0
        try:
            active_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.side == "BUY",
                    PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)),
                )
                .all()
            )
            for p in active_pending:
                sym = (p.symbol or "").strip().upper().replace("/", "").replace("-", "")
                if not sym.endswith(demo_quote_ccy):
                    continue
                try:
                    reserved_cash += float(p.price or 0.0) * float(p.quantity or 0.0)
                except Exception:
                    continue
        except Exception:
            reserved_cash = 0.0
        available_cash = max(0.0, cash - reserved_cash)

        max_certainty_mode = bool(config.get("max_certainty_mode"))

        # Profil agresywności — nadpisuje domyślne progi
        from backend.runtime_settings import AGGRESSIVENESS_PROFILES

        aggressiveness = str(config.get("trading_aggressiveness", "balanced")).lower()
        aggr_profile = AGGRESSIVENESS_PROFILES.get(
            aggressiveness, AGGRESSIVENESS_PROFILES["balanced"]
        )

        # Runtime-controlled settings (profil agresywności dostarcza domyślne wartości)
        max_daily_loss_pct = float(config.get("max_daily_drawdown", 0.03)) * 100.0
        max_drawdown_pct = float(config.get("max_weekly_drawdown", 0.07)) * 100.0
        base_risk_per_trade = float(
            config.get("risk_per_trade", aggr_profile["risk_per_trade"])
        )
        max_trades_per_day = int(config.get("max_trades_per_day", 20))
        max_open_positions = int(
            config.get("max_open_positions", aggr_profile["max_open_positions"])
        )
        base_cooldown = int(
            float(config.get("cooldown_after_loss_streak_minutes", 60)) * 60
        )
        maker_fee_rate = float(config.get("maker_fee_rate", 0.001))
        taker_fee_rate = float(config.get("taker_fee_rate", 0.001))
        slippage_bps = float(config.get("slippage_bps", 5.0))
        spread_buffer_bps = float(config.get("spread_buffer_bps", 3.0))
        min_edge_multiplier = float(config.get("min_edge_multiplier", 2.5))
        min_expected_rr = float(config.get("min_expected_rr", 1.5))
        min_order_notional = float(config.get("min_order_notional", 25.0))
        loss_streak_limit = int(config.get("loss_streak_limit", 3))

        # Trading-core settings (migrated from env)
        base_qty = float(config.get("demo_order_qty", 0.01))
        base_min_confidence = float(
            config.get(
                "demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]
            )
        )
        max_signal_age = int(config.get("demo_max_signal_age_seconds", 3600))
        min_klines = int(os.getenv("DEMO_MIN_KLINES", "60"))

        crash_window_minutes = int(config.get("crash_window_minutes", 60))
        crash_drop_pct = float(config.get("crash_drop_percent", 6.0))
        crash_cooldown_seconds = int(config.get("crash_cooldown_seconds", 7200))

        atr_stop_mult = float(config.get("atr_stop_mult", 2.0))
        atr_take_mult = float(config.get("atr_take_mult", 3.5))
        trail_mult = float(config.get("atr_trail_mult", 1.5))

        extreme_margin_pct = float(config.get("extreme_range_margin_pct", 0.02))
        extreme_min_conf = float(config.get("extreme_min_confidence", 0.85))
        extreme_min_rating = int(config.get("extreme_min_rating", 4))

        max_qty = float(config.get("demo_max_position_qty", 1.0))
        min_qty = float(config.get("demo_min_position_qty", 0.001))

        # Nowe flagi DEMO (profil agresywności dostarcza domyślne wartości)
        demo_require_manual_confirm = bool(
            config.get("demo_require_manual_confirm", False)
        )
        demo_allow_soft_buy_entries = bool(
            config.get(
                "demo_allow_soft_buy_entries",
                aggr_profile["demo_allow_soft_buy_entries"],
            )
        )
        demo_min_entry_score = float(
            config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"])
        )

        # Maksymalna pewność = mniej transakcji, wyższe progi, dłuższy cooldown.
        if max_certainty_mode:
            base_min_confidence = max(base_min_confidence, 0.9)
            extreme_min_conf = max(extreme_min_conf, 0.92)
            extreme_min_rating = max(extreme_min_rating, 5)
            extreme_margin_pct = min(extreme_margin_pct, 0.01)
            max_trades_per_day = min(max_trades_per_day, 1)
            base_cooldown = max(base_cooldown, 3600)
            base_risk_per_trade = min(base_risk_per_trade, 0.002)
            demo_require_manual_confirm = (
                True  # max_certainty zawsze wymaga potwierdzenia
            )

        pending_cooldown_seconds = int(
            config.get(
                "pending_order_cooldown_seconds",
                aggr_profile["pending_order_cooldown_seconds"],
            )
        )

        # Zakresy z bloga (OpenAI/heurystyka)
        range_map: dict[str, dict] = {}
        max_ai_age_seconds = int(config.get("max_ai_insights_age_seconds", 7200))
        use_heuristic_fallback = bool(
            config.get("demo_use_heuristic_ranges_fallback", True)
        )
        ai_ranges_stale = False
        try:
            from backend.database import BlogPost

            latest_blog = (
                db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
            )
            if latest_blog and latest_blog.created_at:
                age_s = (now - latest_blog.created_at).total_seconds()
                if age_s > max_ai_age_seconds:
                    ai_ranges_stale = True
                    if (
                        not self.last_stale_ai_log_ts
                        or (now - self.last_stale_ai_log_ts).total_seconds() > 300
                    ):
                        self.last_stale_ai_log_ts = now
                        log_to_db(
                            "WARNING",
                            "demo_trading",
                            f"Zakresy AI są nieaktualne ({int(age_s)}s temu) — "
                            + (
                                "używam heurystyki ATR jako fallback."
                                if use_heuristic_fallback
                                else "zatrzymuję DEMO."
                            ),
                            db=db,
                        )
                    if not use_heuristic_fallback:
                        return None
            if latest_blog and latest_blog.market_insights and not ai_ranges_stale:
                insights = json.loads(latest_blog.market_insights)
                for ins in insights:
                    if ins.get("range") and ins.get("symbol"):
                        range_map[str(ins.get("symbol"))] = ins.get("range")
        except Exception as exc:
            log_exception(
                "demo_trading", "Błąd odczytu zakresów OpenAI z bloga", exc, db=db
            )
            ai_ranges_stale = True

        # Fallback/supplement: heurystyczne zakresy ATR
        # Uruchamiaj gdy: range_map pusty LUB blog nieaktualny LUB są symbole watchlisty bez zakresu.
        # Dzięki temu nowe symbole dodane do watchlisty (np. po WATCHLIST merge) zawsze dostaną zakres.
        missing_in_range = [s for s in self.watchlist if s not in range_map]
        if (
            not range_map or ai_ranges_stale or missing_in_range
        ) and use_heuristic_fallback:
            try:
                from backend.analysis import _heuristic_ranges, generate_market_insights

                # Generuj tylko dla brakujących symboli (lub wszystkich gdy blog stale/empty)
                syms_for_heuristic = (
                    missing_in_range
                    if (range_map and not ai_ranges_stale)
                    else self.watchlist
                )
                insights_fallback = generate_market_insights(
                    db, syms_for_heuristic, timeframe="1h"
                )
                heuristic_list = _heuristic_ranges(insights_fallback)
                # _heuristic_ranges zwraca List[Dict] — konwertuj na dict symbol→range
                added = []
                for item in heuristic_list:
                    sym = item.get("symbol")
                    if sym and sym not in range_map:
                        range_map[sym] = item
                        added.append(sym)
                if added:
                    added_sorted = sorted(added)
                    changed = added_sorted != self._last_heuristic_suppl_syms
                    elapsed = (
                        (now - self._last_heuristic_suppl_log_ts).total_seconds()
                        if self._last_heuristic_suppl_log_ts
                        else 9999
                    )
                    if changed or elapsed > 600:
                        self._last_heuristic_suppl_log_ts = now
                        self._last_heuristic_suppl_syms = added_sorted
                        log_to_db(
                            "INFO",
                            "demo_trading",
                            f"Heurystyczne zakresy ATR uzupełnione dla: {', '.join(added_sorted)}.",
                            db=db,
                        )
            except Exception as exc2:
                log_exception(
                    "demo_trading",
                    "Błąd generowania heurystycznych zakresów",
                    exc2,
                    db=db,
                )

        if not range_map:
            log_to_db(
                "ERROR",
                "demo_trading",
                "Brak jakichkolwiek zakresów (AI i heurystyka) — pomijam decyzje DEMO",
                db=db,
            )
            return None

        # Ryzyko (dzienny limit + drawdown)
        unrealized_pnl = float(account_state.get("unrealized_pnl") or 0.0)
        realized_pnl_24h = float(account_state.get("realized_pnl_24h") or 0.0)
        daily_loss_limit = -(initial_balance * max_daily_loss_pct / 100)
        daily_loss_triggered = (realized_pnl_24h + unrealized_pnl) <= daily_loss_limit

        positions_all = db.query(Position).filter(Position.mode == mode).all()
        if mode == "live":
            # LIVE: zarządzaj exit engine dla WSZYSTKICH pozycji w DB (mode=live),
            # włącznie z synced_from_binance. Dust jest wcześniej usuwany przez
            # _get_live_spot_positions — jeśli coś jest w Position.mode=live,
            # to jest prawdziwa, śledzona pozycja.
            positions = [
                p
                for p in positions_all
                if float(p.quantity or 0) > 0
                and float(p.entry_price or 0) > 0
                and (p.symbol or "")
                .strip()
                .upper()
                .replace("/", "")
                .replace("-", "")
                .endswith(demo_quote_ccy)
            ]
        else:
            positions = [
                p
                for p in positions_all
                if (p.symbol or "")
                .strip()
                .upper()
                .replace("/", "")
                .replace("-", "")
                .endswith(demo_quote_ccy)
            ]

        # Helpers for pending order checks
        def _has_active_pending(sym: str) -> bool:
            return (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.symbol == sym,
                    PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)),
                )
                .count()
                > 0
            )

        def _pending_in_cooldown(sym: str) -> bool:
            last = (
                db.query(PendingOrder)
                .filter(PendingOrder.mode == mode, PendingOrder.symbol == sym)
                .order_by(PendingOrder.created_at.desc())
                .first()
            )
            if not last or not last.created_at:
                return False
            return (now - last.created_at).total_seconds() < float(
                pending_cooldown_seconds
            )

        return {
            "now": now,
            "config": config,
            "runtime_ctx": runtime_ctx,
            "demo_quote_ccy": demo_quote_ccy,
            "initial_balance": initial_balance,
            "equity": equity,
            "available_cash": available_cash,
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "base_risk_per_trade": base_risk_per_trade,
            "max_trades_per_day": max_trades_per_day,
            "max_open_positions": max_open_positions,
            "base_cooldown": base_cooldown,
            "loss_streak_limit": loss_streak_limit,
            "maker_fee_rate": maker_fee_rate,
            "taker_fee_rate": taker_fee_rate,
            "slippage_bps": slippage_bps,
            "spread_buffer_bps": spread_buffer_bps,
            "min_edge_multiplier": min_edge_multiplier,
            "min_expected_rr": min_expected_rr,
            "min_order_notional": min_order_notional,
            "base_qty": base_qty,
            "base_min_confidence": base_min_confidence,
            "max_signal_age": max_signal_age,
            "min_klines": min_klines,
            "crash_window_minutes": crash_window_minutes,
            "crash_drop_pct": crash_drop_pct,
            "crash_cooldown_seconds": crash_cooldown_seconds,
            "atr_stop_mult": atr_stop_mult,
            "atr_take_mult": atr_take_mult,
            "trail_mult": trail_mult,
            "extreme_margin_pct": extreme_margin_pct,
            "extreme_min_conf": extreme_min_conf,
            "extreme_min_rating": extreme_min_rating,
            "max_qty": max_qty,
            "min_qty": min_qty,
            "pending_cooldown_seconds": pending_cooldown_seconds,
            "range_map": range_map,
            "daily_loss_triggered": daily_loss_triggered,
            "daily_loss_limit": daily_loss_limit,
            "positions": positions,
            "_has_active_pending": _has_active_pending,
            "_pending_in_cooldown": _pending_in_cooldown,
            "tier_map": build_symbol_tier_map(config.get("symbol_tiers", {})),
            "demo_require_manual_confirm": demo_require_manual_confirm,
            "demo_allow_soft_buy_entries": demo_allow_soft_buy_entries,
            "demo_min_entry_score": demo_min_entry_score,
            "aggressiveness": aggressiveness,
            "enabled_strategies": config.get("enabled_strategies", ["default"]),
            "mode": mode,
        }

    # ------------------------------------------------------------------
    # Etap 1: zarządzanie wyjściami — WARSTWOWY EXIT ENGINE
    # WARSTWA 1: HARD EXIT (stop loss, kill switch)
    # WARSTWA 2: TRAILING STOP (gdy aktywny)
    # WARSTWA 3: TAKE PROFIT (częściowy jeśli trend trwa, pełny przy odwróceniu)
    # WARSTWA 4: REVERSAL CHECK (dla pozycji po pierwszym TP)
    # ------------------------------------------------------------------

    def _check_exits(self, db: Session, tc: dict):
        now = tc["now"]
        runtime_ctx = tc["runtime_ctx"]
        config = tc["config"]
        positions = tc["positions"]
        atr_stop_mult = tc["atr_stop_mult"]
        atr_take_mult = tc["atr_take_mult"]
        trail_mult = tc["trail_mult"]
        min_klines = tc["min_klines"]
        daily_loss_triggered = tc["daily_loss_triggered"]
        base_cooldown = tc["base_cooldown"]
        loss_streak_limit = tc["loss_streak_limit"]
        max_drawdown_pct = tc["max_drawdown_pct"]
        _has_active_pending = tc["_has_active_pending"]
        _pending_in_cooldown = tc["_pending_in_cooldown"]
        tier_map = tc.get("tier_map", {})

        _reason_pl = {
            "stop_loss_hit": "Stop Loss — limit straty osiągnięty",
            "trailing_lock_profit": "Trailing Stop — zabezpieczenie zysku",
            "tp_partial_keep_trend": "Częściowe TP (25%) — trend nadal trwa, zostawiamy resztę",
            "tp_full_reversal": "Pełny TP — trend słabnie lub zmienia kierunek",
            "weak_trend_after_tp": "TP przy słabym trendzie — zabezpieczamy zysk",
            "tp_sl_exit_triggered": "TP lub SL osiągnięty",
        }

        _mode_label = str(tc.get("mode") or "demo").upper()
        _mode = tc.get("mode", "demo")

        def _exit_message(
            reason_code: str,
            sym: str,
            price: float,
            tp: float,
            sl: float,
            qty: float = 0,
            partial: bool = False,
            entry_price: float = 0,
        ) -> str:
            base = _reason_pl.get(reason_code, f"Wyjście ({reason_code})")
            # PnL
            pnl_pct = (
                ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0
            )
            pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
            pnl_str = f"{pnl_emoji} PnL: {pnl_pct:+.2f}%"

            emoji_map = {
                "stop_loss_hit": "🔴",
                "trailing_lock_profit": "🟠",
                "tp_partial_keep_trend": "🟢",
                "tp_full_reversal": "🟡",
                "weak_trend_after_tp": "🟡",
            }
            emoji = emoji_map.get(reason_code, "⚪")

            action_map = {
                "stop_loss_hit": "STOP LOSS",
                "trailing_lock_profit": "TRAILING STOP",
                "tp_partial_keep_trend": "CZĘŚCIOWE TP (25%)",
                "tp_full_reversal": "ZAMKNIĘCIE",
                "weak_trend_after_tp": "ZAMKNIĘCIE",
            }
            action = action_map.get(reason_code, reason_code)

            partial_note = " (częściowe 25%)" if partial else ""

            return (
                f"{emoji} [{_mode_label}] {action} — {sym}{partial_note}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Powód: {base}\n"
                f"Cena wejścia: {entry_price:.6f}\n"
                f"Cena teraz: {price:.6f}\n"
                f"TP: {tp:.6f} | SL: {sl:.6f}\n"
                f"Ilość: {qty:.8g}\n"
                f"{pnl_str}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Typ: {_mode_label.lower()} pozycja"
            )

        for pos in positions:
            sym = pos.symbol
            if not sym or float(pos.quantity or 0) <= 0:
                continue

            # --- HOLD MODE: pomijamy TP/SL exit dla pozycji strategicznych ---
            sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
            sym_tier = tier_map.get(sym_norm, {})
            if sym_tier.get("hold_mode"):
                continue

            if _has_active_pending(sym) or _pending_in_cooldown(sym):
                continue

            latest = (
                db.query(MarketData)
                .filter(MarketData.symbol == sym)
                .order_by(MarketData.timestamp.desc())
                .first()
            )
            price = float(latest.price) if latest else None
            if price is None:
                ticker = self.binance.get_ticker_price(sym)
                if ticker and ticker.get("price"):
                    price = float(ticker["price"])
            if price is None:
                continue

            ctx = get_live_context(db, sym, timeframe="1h", limit=max(min_klines, 120))
            if not ctx or not ctx.get("atr"):
                continue
            atr = float(ctx.get("atr") or 0.0)
            if atr <= 0:
                continue

            entry = float(pos.entry_price)
            qty = float(pos.quantity)
            partial_count = int(pos.partial_take_count or 0)

            # TP/SL: używamy planned_tp/sl z momentu wejścia, fallback do ATR
            stop_loss = (
                float(pos.planned_sl)
                if pos.planned_sl
                else (entry - atr * atr_stop_mult)
            )
            take_profit = (
                float(pos.planned_tp)
                if pos.planned_tp
                else (entry + atr * atr_take_mult)
            )

            # Aktualizuj highest_price_seen (MFE tracking)
            prev_high = float(pos.highest_price_seen or entry)
            if price > prev_high:
                pos.highest_price_seen = price

            # Kontekst techniczny
            ema_20 = ctx.get("ema_20")
            ema_50 = ctx.get("ema_50")
            rsi = float(ctx.get("rsi") or 50.0)

            # Prognoza AI (1h, ≤2h stara) — czy trzymać pozycję dłużej?
            _fc_cutoff = now - timedelta(hours=2)
            _latest_fc = (
                db.query(ForecastRecord)
                .filter(
                    ForecastRecord.symbol == sym,
                    ForecastRecord.checked == False,  # noqa: E712
                    ForecastRecord.forecast_ts >= _fc_cutoff,
                    ForecastRecord.horizon == "1h",
                )
                .order_by(ForecastRecord.forecast_ts.desc())
                .first()
            )
            forecast_bullish = (
                _latest_fc is not None
                and _latest_fc.direction == "WZROST"
                and _latest_fc.forecast_price is not None
                and float(_latest_fc.forecast_price)
                > price * 1.005  # prognoza >0.5% powyżej ceny
            )

            # Trailing stop — aktualizuj poziom jeśli aktywny
            trailing_active = bool(pos.trailing_active)
            trailing_stop = (
                float(pos.trailing_stop_price) if pos.trailing_stop_price else None
            )
            if trailing_active:
                new_trail = price - atr * trail_mult
                if trailing_stop is None or new_trail > trailing_stop:
                    trailing_stop = new_trail
                    pos.trailing_stop_price = trailing_stop

            # ━━━ WARSTWA 1: HARD EXIT — Stop Loss ━━━━━━━━━━━━━━━━━━━━━━━━━
            if price <= stop_loss:
                reason_code = "stop_loss_hit"
                msg = _exit_message(
                    reason_code,
                    sym,
                    price,
                    take_profit,
                    stop_loss,
                    qty,
                    entry_price=entry,
                )
                self._trace_decision(
                    db,
                    symbol=sym,
                    action="CREATE_PENDING_EXIT",
                    reason_code=reason_code,
                    runtime_ctx=runtime_ctx,
                    mode=_mode,
                    signal_summary={
                        "source": "exit_engine",
                        "layer": "hard_exit",
                        "atr": atr,
                        "entry": entry,
                        "price": price,
                    },
                    risk_check={"daily_loss_triggered": daily_loss_triggered},
                    cost_check={"eligible": True},
                    execution_check={"eligible": True},
                    details={
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "quantity": qty,
                    },
                )
                pending_id = self._create_pending_order(
                    db=db,
                    symbol=sym,
                    side="SELL",
                    price=price,
                    qty=qty,
                    mode=_mode,
                    reason=f"[SL] Stop Loss @ {price:.6f} (SL={stop_loss:.6f})",
                    config_snapshot_id=runtime_ctx.get("snapshot_id"),
                    strategy_name=f"{_mode}_collector",
                )
                # Eskalacja cooldown po SL — zapobiega natychmiastowemu re-entry
                sl_state = self.demo_state.get(
                    sym, {"loss_streak": 0, "cooldown": base_cooldown}
                )
                sl_state["loss_streak"] = min(
                    sl_state.get("loss_streak", 0) + 1, loss_streak_limit
                )
                sl_state["cooldown"] = min(
                    base_cooldown * (1 + sl_state["loss_streak"]), 7200
                )
                sl_state["win_streak"] = 0
                self.demo_state[sym] = sl_state
                self._send_telegram_alert(
                    f"{_mode_label}: Stop Loss", msg, force_send=True
                )
                db.add(
                    Alert(
                        alert_type="RISK",
                        severity="WARNING",
                        title=f"SL {sym}",
                        message=msg,
                        symbol=sym,
                        is_sent=True,
                        timestamp=now,
                    )
                )
                continue

            # ━━━ WARSTWA 2: TRAILING STOP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if trailing_active and trailing_stop and price <= trailing_stop:
                reason_code = "trailing_lock_profit"
                msg = _exit_message(
                    reason_code,
                    sym,
                    price,
                    take_profit,
                    trailing_stop,
                    qty,
                    entry_price=entry,
                )
                self._trace_decision(
                    db,
                    symbol=sym,
                    action="CREATE_PENDING_EXIT",
                    reason_code=reason_code,
                    runtime_ctx=runtime_ctx,
                    mode=_mode,
                    signal_summary={
                        "source": "exit_engine",
                        "layer": "trailing",
                        "price": price,
                        "trailing_stop": trailing_stop,
                    },
                    risk_check={},
                    cost_check={"eligible": True},
                    execution_check={"eligible": True},
                    details={"trailing_stop": trailing_stop, "quantity": qty},
                )
                pending_id = self._create_pending_order(
                    db=db,
                    symbol=sym,
                    side="SELL",
                    price=price,
                    qty=qty,
                    mode=_mode,
                    reason=f"[TRAIL] Trailing stop @ {price:.6f} (trail={trailing_stop:.6f})",
                    config_snapshot_id=runtime_ctx.get("snapshot_id"),
                    strategy_name=f"{_mode}_collector",
                )
                _trail_key = f"{_mode}:{sym}:{getattr(pos, 'id', 'na')}"
                _last_trail_alert = self._trailing_alert_state.get(_trail_key)
                _should_alert_trail = _last_trail_alert is None
                if (
                    not _should_alert_trail
                    and _last_trail_alert
                    and trailing_stop
                    and _last_trail_alert > 0
                ):
                    _trail_change_pct = (
                        abs(trailing_stop - _last_trail_alert) / _last_trail_alert
                    )
                    _should_alert_trail = _trail_change_pct >= 0.005
                if _should_alert_trail:
                    self._send_telegram_alert(
                        f"{_mode_label}: Trailing Stop", msg, force_send=True
                    )
                    if trailing_stop:
                        self._trailing_alert_state[_trail_key] = trailing_stop
                db.add(
                    Alert(
                        alert_type="SIGNAL",
                        severity="INFO",
                        title=f"TRAIL {sym}",
                        message=msg,
                        symbol=sym,
                        is_sent=True,
                        timestamp=now,
                    )
                )
                continue

            # ━━━ WARSTWA 3: TAKE PROFIT (częściowy lub pełny) ━━━━━━━━━━━━━
            if price >= take_profit:
                # Oceń siłę trendu — czy kontynuować czy zamknąć
                # forecast_bullish działa jako dodatkowy sygnał utrzymania pozycji
                trend_strong = (
                    ema_20 is not None
                    and ema_50 is not None
                    and float(ema_20) > float(ema_50)
                    and 40.0 < rsi < 75.0
                ) or forecast_bullish  # AI prognoza wzrostu → trzymaj pozycję
                partial_qty = round(qty * 0.25, 8)
                _min_notional = float(tc.get("min_order_notional", 10.0))
                _partial_notional = partial_qty * price
                can_partial = (
                    (partial_count < 2)
                    and (partial_qty > 0)
                    and (partial_qty < qty * 0.95)
                    and (_partial_notional >= _min_notional)  # NOTIONAL guard
                )

                if can_partial and trend_strong:
                    # Częściowe zamknięcie 25% + aktywuj trailing + podnieś SL
                    reason_code = "tp_partial_keep_trend"
                    msg = _exit_message(
                        reason_code,
                        sym,
                        price,
                        take_profit,
                        stop_loss,
                        partial_qty,
                        partial=True,
                        entry_price=entry,
                    )
                    self._trace_decision(
                        db,
                        symbol=sym,
                        action="CREATE_PENDING_EXIT",
                        reason_code=reason_code,
                        runtime_ctx=runtime_ctx,
                        mode=_mode,
                        signal_summary={
                            "source": "exit_engine",
                            "layer": "tp_soft",
                            "price": price,
                            "tp": take_profit,
                            "rsi": rsi,
                            "ema_trend": "up",
                            "forecast_bullish": forecast_bullish,
                        },
                        risk_check={},
                        cost_check={"eligible": True},
                        execution_check={"eligible": True},
                        details={
                            "partial_qty": partial_qty,
                            "full_qty": qty,
                            "partial_count": partial_count,
                        },
                    )
                    pending_id = self._create_pending_order(
                        db=db,
                        symbol=sym,
                        side="SELL",
                        price=price,
                        qty=partial_qty,
                        mode=_mode,
                        reason=f"[TP-PARTIAL] Trend trwa — zamykamy 25% @ {price:.6f} (TP={take_profit:.6f})",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"),
                        strategy_name=f"{_mode}_collector",
                    )
                    # Podnieś SL do break-even lub wyżej
                    pos.planned_sl = max(stop_loss, entry)
                    # Aktywuj trailing
                    pos.trailing_active = True
                    new_trail = price - atr * trail_mult
                    if not pos.trailing_stop_price or new_trail > float(
                        pos.trailing_stop_price
                    ):
                        pos.trailing_stop_price = new_trail
                    self._send_telegram_alert(
                        f"{_mode_label}: Częściowe TP", msg, force_send=True
                    )
                    db.add(
                        Alert(
                            alert_type="SIGNAL",
                            severity="INFO",
                            title=f"TP-PARTIAL {sym}",
                            message=msg,
                            symbol=sym,
                            is_sent=True,
                            timestamp=now,
                        )
                    )
                else:
                    # Pełne zamknięcie
                    reason_code = (
                        "tp_full_reversal"
                        if (not trend_strong)
                        else "weak_trend_after_tp"
                    )
                    msg = _exit_message(
                        reason_code,
                        sym,
                        price,
                        take_profit,
                        stop_loss,
                        qty,
                        entry_price=entry,
                    )
                    self._trace_decision(
                        db,
                        symbol=sym,
                        action="CREATE_PENDING_EXIT",
                        reason_code=reason_code,
                        runtime_ctx=runtime_ctx,
                        mode=_mode,
                        signal_summary={
                            "source": "exit_engine",
                            "layer": "tp_full",
                            "price": price,
                            "tp": take_profit,
                            "rsi": rsi,
                            "trend_strong": trend_strong,
                            "forecast_bullish": forecast_bullish,
                        },
                        risk_check={},
                        cost_check={"eligible": True},
                        execution_check={"eligible": True},
                        details={
                            "quantity": qty,
                            "trend_strong": trend_strong,
                            "partial_count": partial_count,
                        },
                    )
                    pending_id = self._create_pending_order(
                        db=db,
                        symbol=sym,
                        side="SELL",
                        price=price,
                        qty=qty,
                        mode=_mode,
                        reason=f"[TP-FULL] {_reason_pl.get(reason_code, reason_code)} @ {price:.6f}",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"),
                        strategy_name=f"{_mode}_collector",
                    )
                    # Sukces — zeruj loss_streak, zwiększ win_streak
                    tp_state = self.demo_state.get(
                        sym,
                        {"loss_streak": 0, "win_streak": 0, "cooldown": base_cooldown},
                    )
                    tp_state["loss_streak"] = 0
                    tp_state["win_streak"] = tp_state.get("win_streak", 0) + 1
                    tp_state["cooldown"] = base_cooldown
                    self.demo_state[sym] = tp_state
                    self._send_telegram_alert(
                        f"{_mode_label}: EXIT TP", msg, force_send=True
                    )
                    db.add(
                        Alert(
                            alert_type="SIGNAL",
                            severity="INFO",
                            title=f"TP {sym}",
                            message=msg,
                            symbol=sym,
                            is_sent=True,
                            timestamp=now,
                        )
                    )
                continue

            # ━━━ WARSTWA 4: REVERSAL CHECK (dla pozycji po TP lub z trailing) ━━━
            if (
                (trailing_active or partial_count > 0)
                and ema_20 is not None
                and ema_50 is not None
            ):
                pnl_pct = (price - entry) / entry * 100 if entry > 0 else 0
                if pnl_pct > 2.0 and float(ema_20) < float(ema_50) and rsi > 65.0:
                    reason_code = "tp_full_reversal"
                    msg = _exit_message(
                        reason_code,
                        sym,
                        price,
                        take_profit,
                        stop_loss,
                        qty,
                        entry_price=entry,
                    )
                    self._trace_decision(
                        db,
                        symbol=sym,
                        action="CREATE_PENDING_EXIT",
                        reason_code=reason_code,
                        runtime_ctx=runtime_ctx,
                        mode=_mode,
                        signal_summary={
                            "source": "exit_engine",
                            "layer": "reversal",
                            "price": price,
                            "rsi": rsi,
                            "ema_20": float(ema_20),
                            "ema_50": float(ema_50),
                        },
                        risk_check={},
                        cost_check={"eligible": True},
                        execution_check={"eligible": True},
                        details={"pnl_pct": pnl_pct, "quantity": qty},
                    )
                    pending_id = self._create_pending_order(
                        db=db,
                        symbol=sym,
                        side="SELL",
                        price=price,
                        qty=qty,
                        mode=_mode,
                        reason=f"[REVERSAL] Odwrócenie trendu — zysk +{pnl_pct:.1f}% @ {price:.6f}",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"),
                        strategy_name=f"{_mode}_collector",
                    )
                    self._send_telegram_alert(
                        f"{_mode_label}: EXIT Reversal", msg, force_send=True
                    )
                    db.add(
                        Alert(
                            alert_type="SIGNAL",
                            severity="INFO",
                            title=f"REVERSAL {sym}",
                            message=msg,
                            symbol=sym,
                            is_sent=True,
                            timestamp=now,
                        )
                    )
                    continue

        # Drawdown alerts
        for p in positions:
            # --- HOLD MODE: nie wysyłaj alarmów drawdown dla pozycji strategicznych ---
            p_norm = (p.symbol or "").strip().upper().replace("/", "").replace("-", "")
            p_tier = tier_map.get(p_norm, {})
            if p_tier.get("hold_mode"):
                continue

            if p.entry_price and p.current_price and p.entry_price > 0:
                drawdown_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100
                if drawdown_pct <= -max_drawdown_pct:
                    if (
                        not self.last_risk_alert_ts
                        or (now - self.last_risk_alert_ts).total_seconds() > 900
                    ):
                        self.last_risk_alert_ts = now
                        msg = f"🔴 Pozycja {p.symbol} traci za dużo ({drawdown_pct:.1f}%, limit: {max_drawdown_pct}%).\nSystem ograniczył ryzyko na tym symbolu.\nCo zrobić: rozważ zamknięcie pozycji."
                        log_to_db("WARNING", "demo_trading", msg, db=db)
                        self._send_telegram_alert(
                            "RISK: Drawdown", msg, force_send=True
                        )
                        db.add(
                            Alert(
                                alert_type="RISK",
                                severity="WARNING",
                                title="Drawdown",
                                message=msg,
                                symbol=p.symbol,
                                is_sent=True,
                                timestamp=now,
                            )
                        )
                        state = self.demo_state.get(
                            p.symbol, {"loss_streak": 0, "cooldown": base_cooldown}
                        )
                        state["loss_streak"] = min(
                            state.get("loss_streak", 0) + 1, loss_streak_limit
                        )
                        state["cooldown"] = min(
                            base_cooldown * (1 + state["loss_streak"]), 3600
                        )
                        self.demo_state[p.symbol] = state

    # ------------------------------------------------------------------
    # Etap 1b: HOLD — sprawdzenie celów wartości pozycji strategicznych
    # ------------------------------------------------------------------

    def _check_hold_targets(self, db: Session, tc: dict):
        """Sprawdź czy pozycje HOLD osiągnęły target_value_eur → sell all."""
        now = tc["now"]
        runtime_ctx = tc["runtime_ctx"]
        positions = tc["positions"]
        tier_map = tc.get("tier_map", {})
        _has_active_pending = tc["_has_active_pending"]

        for pos in positions:
            sym = pos.symbol
            if not sym or float(pos.quantity or 0) <= 0:
                continue
            sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
            sym_tier = tier_map.get(sym_norm, {})
            if not sym_tier.get("hold_mode"):
                continue

            target_eur = float(sym_tier.get("target_value_eur", 0))
            if target_eur <= 0:
                continue

            # Pobierz aktualną cenę
            price = float(pos.current_price or 0)
            if price <= 0:
                md = (
                    db.query(MarketData)
                    .filter(MarketData.symbol == sym)
                    .order_by(MarketData.timestamp.desc())
                    .first()
                )
                if md:
                    price = float(md.price or 0)
            if price <= 0:
                continue

            qty = float(pos.quantity or 0)
            position_value = qty * price

            if position_value >= target_eur:
                if _has_active_pending(sym):
                    continue

                _m = tc.get("mode", "demo")
                pending_id = self._create_pending_order(
                    db=db,
                    symbol=sym,
                    side="SELL",
                    price=price,
                    qty=qty,
                    mode=_m,
                    reason=f"[HOLD] Cel osiągnięty: {position_value:.2f} EUR >= {target_eur:.0f} EUR",
                )
                msg = (
                    f"🟢 [HOLD] Cel osiągnięty — {sym}\n"
                    f"\n"
                    f"Wartość pozycji: {position_value:.2f} EUR (cel: {target_eur:.0f} EUR)\n"
                    f"Cena: {price:.6f}\n"
                    f"Ilość: {qty}\n"
                    f"\n"
                    f"Zlecenie SELL utworzone i auto-potwierdzone (ID: {pending_id})."
                )
                self._send_telegram_alert("[HOLD] TARGET", msg, force_send=True)
                db.add(
                    Alert(
                        alert_type="SIGNAL",
                        severity="INFO",
                        title=f"[HOLD] TARGET {sym}",
                        message=f"Pozycja {sym} osiągnęła {position_value:.2f} EUR (cel {target_eur:.0f} EUR). Pending SELL ID {pending_id}.",
                        symbol=sym,
                        is_sent=True,
                        timestamp=now,
                    )
                )
                logger.info(
                    "[HOLD] %s osiągnął target %.2f EUR (cel %.0f EUR) → pending SELL %s",
                    sym,
                    position_value,
                    target_eur,
                    pending_id,
                )
            else:
                logger.debug(
                    "[HOLD] %s wartość %.2f EUR < cel %.0f EUR — trzymamy",
                    sym,
                    position_value,
                    target_eur,
                )

    # ------------------------------------------------------------------
    # Etap 1d: rotacja kapitału — zamknij najgorszą pozycję gdy brak środków
    # ------------------------------------------------------------------

    def _maybe_rotate_capital(self, db: Session, tc: dict) -> bool:
        """Jeśli brak wolnych środków i istnieją otwarte pozycje, zamknij najgorszą.

        Logika:
        - available_cash < min_order_notional AND mamy pozycje otwarte
        - Zamknij pozycję z najniższym unrealized_pnl (stop bleeding)
        - Utwórz CONFIRMED SELL → wykonaj natychmiast przez _execute_confirmed_pending_orders
        - Zwraca True jeśli zlecenie sprzedaży zostało złożone.
        """
        available_cash = float(tc.get("available_cash", 0.0))
        min_order_notional = float(tc.get("min_order_notional", 25.0))
        positions = tc.get("positions", [])
        if available_cash >= min_order_notional:
            return False
        if not positions:
            return False

        mode = tc.get("mode", "demo")
        _has_active_pending = tc["_has_active_pending"]
        _pending_in_cooldown = tc["_pending_in_cooldown"]
        runtime_ctx = tc["runtime_ctx"]

        # Pomiń pozycje z aktywnym pending lub w HOLD
        tier_map = tc.get("tier_map", {})
        closeable = []
        for pos in positions:
            sym = (pos.symbol or "").strip().upper().replace("/", "").replace("-", "")
            sym_tier = tier_map.get(sym, {})
            if sym_tier.get("hold_mode"):
                continue
            if _has_active_pending(pos.symbol) or _pending_in_cooldown(pos.symbol):
                continue
            if float(pos.quantity or 0) <= 0:
                continue
            closeable.append(pos)

        if not closeable:
            log_to_db(
                "WARNING",
                "capital_rotation",
                f"Brak wolnych środków ({available_cash:.2f}) — wszystkie pozycje w HOLD lub pending. "
                "Nie można dokonać rotacji kapitału.",
                db=db,
            )
            return False

        # Najgorsza pozycja = najniższy unrealized_pnl (stop bleeding)
        worst = min(closeable, key=lambda p: float(p.unrealized_pnl or 0))
        sym = worst.symbol
        qty = float(worst.quantity)

        # Oblicz PnL% jeszcze przed pobraniem ceny, na podstawie entry + current_price
        _entry_pre = float(worst.entry_price or 0)
        _cur_pre = float(worst.current_price or worst.entry_price or 0)
        _pnl_pct_pre = (
            (_cur_pre - _entry_pre) / _entry_pre * 100 if _entry_pre > 0 else 0.0
        )

        # GUARD: nie rotuj jeśli najgorsza pozycja jest na plusie — nie zamykamy zysków tylko dla nowego wejścia
        if _pnl_pct_pre >= 0:
            log_to_db(
                "INFO",
                "capital_rotation",
                f"Rotacja kapitału pominięta: {sym} PnL={_pnl_pct_pre:+.1f}% — "
                f"wszystkie pozycje na plusie. Nie zamykamy zyskownych pozycji.",
                db=db,
            )
            logger.info(
                "[CAPITAL_ROTATION] SKIP — %s PnL=%+.1f%% (all profitable, no rotation)",
                sym,
                _pnl_pct_pre,
            )
            _mode_label_skip = mode.upper()
            _pos_summary = ", ".join(
                f"{p.symbol} PnL={((float(p.current_price or p.entry_price or 0) - float(p.entry_price or 0)) / float(p.entry_price or 1) * 100):+.1f}%"
                for p in closeable
            )
            self._send_telegram_alert(
                f"{_mode_label_skip}: BRAK ROTACJI",
                f"⏸️ [{_mode_label_skip}] Brak wolnych środków ({available_cash:.2f} EUR)\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Rotacja pominięta — wszystkie pozycje zyskowne.\n"
                f"Nie zamykam zysków, aby otworzyć nowe wejście.\n"
                f"\nPozycje:\n{_pos_summary}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Bot czeka na pojawienie się wolnych środków lub na TP/SL.",
            )
            return False

        # Pobierz aktualną cenę
        latest = (
            db.query(MarketData)
            .filter(MarketData.symbol == sym)
            .order_by(MarketData.timestamp.desc())
            .first()
        )
        price = float(latest.price) if latest else None
        if price is None:
            ticker = self.binance.get_ticker_price(sym)
            if ticker and ticker.get("price"):
                price = float(ticker["price"])
        if not price:
            return False

        pnl = float(worst.unrealized_pnl or 0)
        entry_price = float(worst.entry_price or price)
        pnl_pct = (price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        pnl_emoji = "📉" if pnl < 0 else "📈"

        pending_id = self._create_pending_order(
            db=db,
            symbol=sym,
            side="SELL",
            price=price,
            qty=qty,
            mode=mode,
            reason=f"Rotacja kapitału: brak wolnych środków ({available_cash:.2f} < {min_order_notional:.0f}). "
            f"Zamykam najgorszą pozycję {sym} PnL={pnl_pct:+.1f}%.",
            strategy_name="capital_rotation",
        )

        log_to_db(
            "WARNING",
            "capital_rotation",
            f"Rotacja kapitału: {sym} SELL qty={qty:.6g} @ {price:.6f} | "
            f"PnL={pnl_pct:+.1f}% | wolne środki={available_cash:.2f} < min={min_order_notional:.0f} | "
            f"pending_id={pending_id}",
            db=db,
        )

        _mode_label = mode.upper()
        msg = (
            f"🔄 [{_mode_label}] ROTACJA KAPITAŁU\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Powód: Brak wolnych środków na nowe zlecenie\n"
            f"Wolne środki: {available_cash:.2f} (min: {min_order_notional:.0f})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Zamykam: {sym}\n"
            f"Cena: {price:.6f} | Ilość: {qty:.6g}\n"
            f"{pnl_emoji} PnL: {pnl_pct:+.2f}%\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Kapitał zostanie uwolniony na lepszą okazję."
        )
        self._send_telegram_alert(
            f"{_mode_label}: ROTACJA KAPITAŁU", msg, force_send=True
        )

        # Wykonaj sprzedaż natychmiast (pending jest już CONFIRMED z _create_pending_order)
        try:
            self._execute_confirmed_pending_orders(db)
        except Exception as exc:
            log_exception(
                "capital_rotation", "Błąd wykonania rotacji kapitału", exc, db=db
            )

        return True

    # ------------------------------------------------------------------
    # Etap 1d: AUTO-GOALS — AI ustala planned_tp/sl dla pozycji bez celu
    # ------------------------------------------------------------------

    def _auto_set_position_goals(self, db: Session, tc: dict) -> int:
        """Automatycznie ustawia planned_tp/sl dla pozycji które ich nie mają.

        Cel = entry_price + ATR × atr_take_mult.
        Przy silnym trendzie 4h (EMA20 > EMA50 i RSI > 55) multiplikator rośnie o 30%.
        Zwraca liczbę zaktualizowanych pozycji.
        """
        positions = tc.get("positions", [])
        atr_take_mult = float(tc.get("atr_take_mult", 3.5))
        atr_stop_mult = float(tc.get("atr_stop_mult", 2.0))
        min_klines = int(tc.get("min_klines", 60))

        set_count = 0
        for pos in positions:
            needs_tp = pos.planned_tp is None
            needs_sl = pos.planned_sl is None
            if not needs_tp and not needs_sl:
                continue

            sym = pos.symbol
            if not sym or float(pos.quantity or 0) <= 0:
                continue

            entry = float(pos.entry_price or 0)
            if entry <= 0:
                continue

            ctx = get_live_context(db, sym, timeframe="1h", limit=max(min_klines, 120))
            if not ctx or not ctx.get("atr"):
                continue
            atr = float(ctx["atr"])
            if atr <= 0:
                continue

            # HTF bias — ambitniejszy TP gdy 4h trend silny w górę
            tp_mult = atr_take_mult
            try:
                htf_ctx = get_live_context(db, sym, timeframe="4h", limit=50)
                if htf_ctx:
                    ema20_4h = htf_ctx.get("ema_20")
                    ema50_4h = htf_ctx.get("ema_50")
                    rsi_4h = float(htf_ctx.get("rsi") or 50)
                    if (
                        ema20_4h
                        and ema50_4h
                        and float(ema20_4h) > float(ema50_4h)
                        and rsi_4h > 55
                    ):
                        tp_mult = atr_take_mult * 1.3  # +30% TP w silnym trendzie
            except Exception:
                pass

            if needs_tp:
                pos.planned_tp = entry + atr * tp_mult
            if needs_sl:
                pos.planned_sl = entry - atr * atr_stop_mult

            set_count += 1
            log_to_db(
                "INFO",
                "auto_goals",
                f"Auto-cele: {sym} tp={pos.planned_tp:.6f} sl={pos.planned_sl:.6f} "
                f"(entry={entry:.6f} ATR={atr:.6f} tp×{tp_mult:.1f} sl×{atr_stop_mult:.1f})",
                db=db,
            )
            logger.info(
                "[AUTO_GOALS] %s: tp=%.6f sl=%.6f (entry=%.6f ATR×%.1f)",
                sym,
                pos.planned_tp,
                pos.planned_sl,
                entry,
                tp_mult,
            )

        if set_count:
            db.flush()

        return set_count

    # ------------------------------------------------------------------
    # Etap 2: screening kandydatów wejścia + gating
    # ------------------------------------------------------------------

    def _screen_entry_candidates(self, db: Session, tc: dict) -> int:
        """Screening kandydatów wejścia + gating. Zwraca liczbę utworzonych pending orders."""
        now = tc["now"]
        config = tc["config"]
        runtime_ctx = tc["runtime_ctx"]
        demo_quote_ccy = tc["demo_quote_ccy"]
        equity = tc["equity"]
        base_qty = tc["base_qty"]
        base_min_confidence = tc["base_min_confidence"]
        max_signal_age = tc["max_signal_age"]
        min_klines = tc["min_klines"]
        atr_stop_mult = tc["atr_stop_mult"]
        atr_take_mult = tc["atr_take_mult"]
        base_risk_per_trade = tc["base_risk_per_trade"]
        base_cooldown = tc["base_cooldown"]
        crash_window_minutes = tc["crash_window_minutes"]
        crash_drop_pct = tc["crash_drop_pct"]
        crash_cooldown_seconds = tc["crash_cooldown_seconds"]
        extreme_margin_pct = tc["extreme_margin_pct"]
        extreme_min_conf = tc["extreme_min_conf"]
        extreme_min_rating = tc["extreme_min_rating"]
        max_qty = tc["max_qty"]
        min_qty = tc["min_qty"]
        pending_cooldown_seconds = tc["pending_cooldown_seconds"]
        range_map = tc["range_map"]
        maker_fee_rate = tc["maker_fee_rate"]
        taker_fee_rate = tc["taker_fee_rate"]
        slippage_bps = tc["slippage_bps"]
        spread_buffer_bps = tc["spread_buffer_bps"]
        min_edge_multiplier = tc["min_edge_multiplier"]
        min_expected_rr = tc["min_expected_rr"]
        min_order_notional = tc["min_order_notional"]
        _has_active_pending = tc["_has_active_pending"]
        _pending_in_cooldown = tc["_pending_in_cooldown"]
        tier_map = tc.get("tier_map", {})
        demo_require_manual_confirm = tc.get("demo_require_manual_confirm", False)
        demo_allow_soft_buy = tc.get("demo_allow_soft_buy_entries", True)
        demo_min_entry_score = float(tc.get("demo_min_entry_score", 50.0))
        # Legacy compatibility: historycznie próg bywał w skali 0-10.
        # Obecnie signal_score jest w skali 0-100.
        entry_score_threshold = (
            demo_min_entry_score * 10.0
            if demo_min_entry_score <= 10.0
            else demo_min_entry_score
        )
        # rating pozostaje osobną bramką jakości (0-5).
        min_rating_gate = float(config.get("min_rating_gate", 3.0))

        available_cash = tc["available_cash"]
        _mode_label = str(tc.get("mode") or "demo").upper()

        # Diagnostyka: ostrzeż gdy brak gotówki na nowe pozycje (rotacja kapitału nie pomogła)
        if available_cash < min_order_notional:
            log_to_db(
                "WARNING",
                "screen_candidates",
                f"[{_mode_label}] Brak gotówki ({available_cash:.2f} EUR < min {min_order_notional:.0f} EUR) "
                f"— pomijam screening. Jeśli LIVE: uzupełnij saldo Binance; jeśli DEMO: sprawdź reset balansu.",
                db=db,
            )
            return

        # Zbieramy kandydatów, sortujemy po expected value netto, potem tworzymy pending
        candidates: list[dict] = []
        open_positions = list(tc.get("positions", []) or [])
        open_positions_scored = rank_open_positions(open_positions, now, config)
        max_positions = int(tc.get("max_open_positions", 3))
        # Wyklucz pozycje "stuck" (exit_reason_code != None) z liczenia zajętych slotów.
        # Stuck pozycje są w trakcie zamykania — nie powinny blokować nowych wejść.
        _real_open = [
            p for p in open_positions if not getattr(p, "exit_reason_code", None)
        ]
        slots_available = max(0, max_positions - len(_real_open))
        min_replacement_edge = float(config.get("min_replacement_edge", 0.015))
        replacement_cooldown_minutes = int(
            config.get("replacement_cooldown_minutes", 20)
        )
        min_position_lifetime_minutes = int(
            config.get("min_position_lifetime_minutes", 20)
        )
        max_rotation_per_hour = int(config.get("max_rotation_per_hour", 2))

        _current_mode = tc.get("mode", "demo")
        scanner_enabled = bool(config.get("collector_use_market_scanner", True))
        scanner_force = bool(config.get("collector_scanner_force_refresh", False))
        scanner_top_n = int(config.get("collector_scanner_top_n", 50))

        no_entry_relax_after_cycles = int(config.get("no_entry_relax_after_cycles", 3))
        relaxed_min_conf_floor = float(config.get("relaxed_min_confidence_floor", 0.50))
        relaxed_min_entry_score = float(config.get("relaxed_min_entry_score", 40.0))
        relaxed_buy_zone_tolerance = float(
            config.get("relaxed_buy_zone_tolerance_pct", 0.03)
        )

        lookback_seconds = max(
            60, int(self.interval) * max(1, no_entry_relax_after_cycles)
        )
        open_positions_count = len(
            [p for p in open_positions if not getattr(p, "exit_reason_code", None)]
        )
        recent_buy_count = (
            db.query(Order)
            .filter(
                Order.mode == _current_mode,
                Order.side == "BUY",
                Order.timestamp >= now - timedelta(seconds=lookback_seconds),
            )
            .count()
        )
        relaxed_entry_mode = (
            open_positions_count == 0
            and recent_buy_count == 0
            and no_entry_relax_after_cycles > 0
        )
        if relaxed_entry_mode:
            logger.info(
                "ENTRY_RELAX_ACTIVE mode=%s reason=no_trades_cycles lookback_s=%s cycles=%s",
                _current_mode,
                lookback_seconds,
                no_entry_relax_after_cycles,
            )

        def _log_why_not_buy(sym: str, reason: str, **kwargs):
            details = (
                ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else "-"
            )
            logger.info(
                "WHY_NOT_BUY mode=%s symbol=%s reason=%s details=%s",
                _current_mode,
                sym,
                reason,
                details,
            )

        candidate_symbols: List[str] = list(self.watchlist)
        scanner_symbols: List[str] = []
        if scanner_enabled:
            try:
                from backend.market_scanner import run_market_scan

                snap = run_market_scan(db, mode=_current_mode, force=scanner_force)
                best_exec = snap.get("best_executable_candidate") or {}
                best_analytical = snap.get("best_analytical_candidate") or {}
                opps = snap.get("opportunities_top_n") or []
                rejected = snap.get("rejected_candidates") or []

                for item in [best_exec, best_analytical]:
                    sym = (item.get("symbol") or "").strip().upper()
                    if sym:
                        scanner_symbols.append(sym)
                for item in opps:
                    sym = (item.get("symbol") or "").strip().upper()
                    if sym:
                        scanner_symbols.append(sym)
                for item in rejected:
                    sym = (item.get("symbol") or "").strip().upper()
                    if sym:
                        scanner_symbols.append(sym)

                # Dodatkowe rozszerzenie: top-N z pełnego universe skanera
                try:
                    from backend.market_scanner import get_trade_universe

                    ext_universe = get_trade_universe(db, extended=True) or []
                    if ext_universe:
                        scanner_symbols.extend(ext_universe[: max(1, scanner_top_n)])
                except Exception:
                    pass

                scanner_symbols = list(dict.fromkeys(scanner_symbols))
                if scanner_symbols:
                    candidate_symbols = list(
                        dict.fromkeys(candidate_symbols + scanner_symbols)
                    )
            except Exception as exc:
                log_exception(
                    "screen_candidates",
                    "Błąd rozszerzania universe przez market_scanner",
                    exc,
                    db=db,
                )

        # Uzupełnij brakujące zakresy dla symboli poza watchlistą,
        # żeby nie odrzucać ich wyłącznie przez brak range_map.
        missing_ranges = [s for s in candidate_symbols if s not in range_map]
        if missing_ranges:
            try:
                from backend.analysis import _heuristic_ranges, generate_market_insights

                insights_fallback = generate_market_insights(
                    db, missing_ranges, timeframe="1h"
                )
                heuristic_list = _heuristic_ranges(insights_fallback)
                for item in heuristic_list:
                    sym = item.get("symbol")
                    if sym and sym not in range_map:
                        range_map[sym] = item
            except Exception as exc:
                log_exception(
                    "screen_candidates",
                    "Błąd uzupełniania range_map dla symboli scanner",
                    exc,
                    db=db,
                )

        def _resolve_signal(sym: str):
            sig_row = (
                db.query(Signal)
                .filter(Signal.symbol == sym)
                .order_by(Signal.timestamp.desc())
                .first()
            )
            if sig_row:
                return sig_row

            # Fallback: live sygnał on-demand dla symboli bez sygnału w DB.
            try:
                from backend.routers.signals import _build_live_signals

                live = _build_live_signals(db, [sym], limit=1)
                if live:
                    row = live[0]
                    return SimpleNamespace(
                        symbol=sym,
                        signal_type=str(row.get("signal_type") or "HOLD"),
                        confidence=float(row.get("confidence") or 0.0),
                        timestamp=now,
                        reason=str(row.get("reason") or "live_signal_fallback"),
                    )
            except Exception:
                return None
            return None

        for symbol in candidate_symbols:
            if not symbol:
                continue
            sym_norm = (symbol or "").strip().upper().replace("/", "").replace("-", "")
            if _current_mode == "live":
                _live_qcm = os.getenv("QUOTE_CURRENCY_MODE", "BOTH").strip().upper()
                if _live_qcm == "USDC" and not sym_norm.endswith("USDC"):
                    continue
                if _live_qcm == "EUR" and not sym_norm.endswith("EUR"):
                    continue
                if _live_qcm == "BOTH" and not (
                    sym_norm.endswith("EUR") or sym_norm.endswith("USDC")
                ):
                    continue
            else:
                if not sym_norm.endswith(demo_quote_ccy):
                    continue

            # --- Quote currency mode gate ---
            _qcm = os.getenv("QUOTE_CURRENCY_MODE", "BOTH").strip().upper()
            _qcm_allowed, _qcm_reason = check_symbol_allowed(sym_norm, _qcm)
            if not _qcm_allowed:
                self._trace_decision(
                    db,
                    symbol=sym_norm,
                    action="SKIP",
                    reason_code=_qcm_reason,
                    runtime_ctx=runtime_ctx,
                )
                continue

            # --- Tier gating: symbol musi należeć do zdefiniowanego tieru ---
            sym_tier = tier_map.get(sym_norm)
            if tier_map and not sym_tier:
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="symbol_not_in_any_tier",
                    runtime_ctx=runtime_ctx,
                )
                continue

            # --- HOLD MODE: nie generuj nowych wejść dla pozycji strategicznych ---
            if sym_tier and sym_tier.get("no_new_entries"):
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="hold_mode_no_new_entries",
                    runtime_ctx=runtime_ctx,
                )
                continue

            # Tier overrides (addytywne do bazowych)
            tier_conf_add = (
                float(sym_tier.get("min_confidence_add", 0.0)) if sym_tier else 0.0
            )
            tier_edge_add = (
                float(sym_tier.get("min_edge_multiplier_add", 0.0)) if sym_tier else 0.0
            )
            tier_risk_scale = (
                float(sym_tier.get("risk_scale", 1.0)) if sym_tier else 1.0
            )
            tier_max_trades = (
                int(sym_tier.get("max_trades_per_day_per_symbol", 99))
                if sym_tier
                else 99
            )
            tier_name = sym_tier.get("tier", "UNKNOWN") if sym_tier else "UNKNOWN"

            # Limit dziennych transakcji na symbol (z tieru)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            sym_trades_today = (
                db.query(Order)
                .filter(
                    Order.symbol == symbol,
                    Order.mode == _current_mode,
                    Order.timestamp >= day_start,
                )
                .count()
            )
            if sym_trades_today >= tier_max_trades:
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="tier_daily_trade_limit",
                    runtime_ctx=runtime_ctx,
                    risk_check={
                        "tier": tier_name,
                        "trades_today": sym_trades_today,
                        "limit": tier_max_trades,
                    },
                )
                continue
            # Pending orders NIE blokują już globalnie decyzji BUY.
            # Portfolio engine decyduje: keep/cancel/replace pending.
            has_active_pending = _has_active_pending(symbol)
            pending_cooldown_active = _pending_in_cooldown(symbol)

            latest = (
                db.query(MarketData)
                .filter(MarketData.symbol == symbol)
                .order_by(MarketData.timestamp.desc())
                .first()
            )
            price = float(latest.price) if latest else None
            if price is None:
                ticker = self.binance.get_ticker_price(symbol)
                if ticker and ticker.get("price"):
                    price = float(ticker["price"])
            if price is None:
                continue

            position = (
                db.query(Position)
                .filter(
                    Position.symbol == symbol,
                    Position.mode == _current_mode,
                    Position.exit_reason_code.is_(None),
                )
                .first()
            )
            # Dla LIVE: jeśli brak rekordu w DB, sprawdź Binance spot (tylko wartość >= min_notional, pył nie blokuje)
            if position is None and _current_mode == "live":
                try:
                    from backend.routers.positions import _get_live_spot_positions

                    for _sp in _get_live_spot_positions(db):
                        if (
                            _sp["symbol"] == symbol
                            and float(_sp.get("value_eur") or 0) >= min_order_notional
                        ):
                            position = object()  # sentinel: blokuje BUY
                            break
                except Exception:
                    pass

            # Cooldown po ostatniej wykonanej transakcji
            last_order = (
                db.query(Order)
                .filter(Order.symbol == symbol, Order.mode == _current_mode)
                .order_by(Order.timestamp.desc())
                .first()
            )
            state = self.demo_state.get(
                symbol, {"loss_streak": 0, "win_streak": 0, "cooldown": base_cooldown}
            )
            cooldown = int(state.get("cooldown", base_cooldown))
            if last_order and (now - last_order.timestamp).total_seconds() < float(
                cooldown
            ):
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="symbol_cooldown_active",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    risk_check={"cooldown_active": True, "cooldown_seconds": cooldown},
                )
                continue

            sig = _resolve_signal(symbol)
            if not sig:
                _log_why_not_buy(symbol, "missing_signal")
                continue

            # Zbuduj kontekst wskaźnikowy wcześnie, żeby fallback confidence
            # działał także gdy AI provider jest niedostępny.
            ctx = get_live_context(
                db, symbol, timeframe="1h", limit=max(min_klines, 120)
            )
            if not ctx:
                continue
            ind_15m = _load_timeframe_indicators(
                db, symbol, "15m", limit=max(min_klines, 120)
            )
            ind_1h = _load_timeframe_indicators(
                db, symbol, "1h", limit=max(min_klines, 120)
            )

            ema20 = ctx.get("ema_20")
            ema50 = ctx.get("ema_50")
            rsi = ctx.get("rsi")
            rsi_buy = ctx.get("rsi_buy")
            rsi_sell = ctx.get("rsi_sell")
            atr = ctx.get("atr")

            raw_confidence = float(sig.confidence or 0.0)
            ai_failed, provider_used = self._is_ai_failed_runtime()
            fallback_confidence = self._calculate_confidence_from_indicators(
                signal_type=sig.signal_type,
                rsi=(float(rsi) if rsi is not None else None),
                ema20=(float(ema20) if ema20 is not None else None),
                ema50=(float(ema50) if ema50 is not None else None),
                volume_ratio=(
                    float(ind_15m.get("volume_ratio"))
                    if ind_15m.get("volume_ratio") is not None
                    else None
                ),
                momentum_hist=(
                    float(ind_15m.get("macd_hist"))
                    if ind_15m.get("macd_hist") is not None
                    else None
                ),
            )
            # Nigdy nie zostawiaj confidence=0 gdy wskaźniki są dostępne.
            effective_confidence = (
                fallback_confidence
                if raw_confidence <= 0.0
                else max(raw_confidence, fallback_confidence)
            )
            sig.confidence = effective_confidence

            # Dynamiczny próg confidence zależny od stanu AI.
            min_confidence_effective = self._dynamic_min_confidence(ai_failed)

            # DEBUG wymagany operacyjnie
            print("CONFIDENCE:", round(effective_confidence, 4))
            print("AI_USED:", provider_used)
            print("AI_FAILED:", ai_failed)

            signal_summary = {
                "signal_type": sig.signal_type,
                "confidence": float(effective_confidence),
                "timestamp": sig.timestamp.isoformat() if sig.timestamp else None,
                "ai_provider": provider_used,
                "ai_failed": ai_failed,
            }
            params = self.symbol_params.get(symbol, {})
            learned_conf = float(params.get("min_confidence", base_min_confidence))
            # Learned params mogą podnieść próg max o 0.10 powyżej base — nie blokuj trading
            min_confidence = min(
                base_min_confidence + 0.10, max(base_min_confidence, learned_conf)
            )
            # Tier override: podniesienie min_confidence
            min_confidence = min(1.0, min_confidence + tier_conf_add)
            # Wymuszenie runtime progu zależnego od stanu AI
            min_confidence = min_confidence_effective
            if relaxed_entry_mode:
                min_confidence = min(min_confidence, max(0.0, relaxed_min_conf_floor))
            # Mikrotolerancja dla BUY: redukuje fałszywe odrzuty na granicy 0.50 vs 0.51.
            buy_confidence_tolerance = float(
                config.get("buy_confidence_tolerance", 0.01)
            )
            confidence_tolerance = (
                max(0.0, buy_confidence_tolerance) if sig.signal_type == "BUY" else 0.0
            )
            if float(effective_confidence) + confidence_tolerance < float(
                min_confidence
            ):
                if str(sig.signal_type).upper() == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "signal_confidence_too_low",
                        confidence=round(float(effective_confidence), 4),
                        min_confidence=round(float(min_confidence), 4),
                        ai_provider=provider_used,
                        ai_failed=ai_failed,
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="signal_confidence_too_low",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check={
                        "min_confidence": min_confidence,
                        "effective_confidence": effective_confidence,
                        "raw_confidence": raw_confidence,
                        "fallback_confidence": fallback_confidence,
                        "ai_provider": provider_used,
                        "ai_failed": ai_failed,
                        "confidence_tolerance": confidence_tolerance,
                        "tier": tier_name,
                    },
                )
                continue
            if (now - sig.timestamp).total_seconds() > float(max_signal_age):
                if str(sig.signal_type).upper() == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "signal_too_old",
                        age_seconds=int((now - sig.timestamp).total_seconds()),
                        max_signal_age=max_signal_age,
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="signal_too_old",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check={"max_signal_age_seconds": max_signal_age},
                )
                continue

            r = range_map.get(symbol)
            if not r:
                continue

            # Shortcut: SELL sygnał bez otwartej pozycji — nie ma sensu sprawdzać filtrów
            # Zapobiega spamowi "signal_filters_not_met" gdy nie ma pozycji do sprzedania
            if sig.signal_type == "SELL" and position is None:
                continue

            crash = self._detect_crash(db, symbol, crash_window_minutes, crash_drop_pct)
            if crash:
                if float(sig.confidence) < extreme_min_conf:
                    continue
                state["cooldown"] = max(
                    int(state.get("cooldown", base_cooldown)), crash_cooldown_seconds
                )
                self.demo_state[symbol] = state
                if (
                    not self.last_crash_alert_ts
                    or (now - self.last_crash_alert_ts).total_seconds() > 1800
                ):
                    self.last_crash_alert_ts = now
                    msg = (
                        f"🔴 Gwałtowny spadek: {symbol}\n"
                        f"Spadek > {crash_drop_pct}% w ciągu {crash_window_minutes} min.\n"
                        f"System: ograniczenie ryzyka, bot nadal działa.\n"
                        f"Co zrobić: obserwuj sytuację, nie otwieraj nowych pozycji ręcznie."
                    )
                    log_to_db("WARNING", "demo_trading", msg, db=db)
                    self._send_telegram_alert("RISK: Crash mode", msg, force_send=True)

            if not atr or float(atr) <= 0:
                continue
            regime_state = detect_regime(
                price=float(price),
                ema21_15m=ind_15m.get("ema_20"),
                ema50_15m=ind_15m.get("ema_50"),
                ema21_1h=ind_1h.get("ema_20"),
                ema50_1h=ind_1h.get("ema_50"),
                ema200_1h=ind_1h.get("ema_50"),
                rsi_15m=ind_15m.get("rsi_14"),
                macd_hist_15m=ind_15m.get("macd_hist"),
                volume_ratio_15m=ind_15m.get("volume_ratio"),
            )

            # Filtry wejścia/wyjścia — z 3% tolerancją cenową (rynek może wyjść poza zakres AI)
            side = None
            reasons: list[str] = []
            price_tolerance = float(config.get("buy_zone_tolerance_pct", 0.02))
            if relaxed_entry_mode:
                price_tolerance = max(price_tolerance, relaxed_buy_zone_tolerance)
            # RSI: próg z konfiguracji (rsi_buy_gate_max > 0 ustawia podłogę) lub hardcoded 65
            _rsi_buy_gate_max = float(config.get("rsi_buy_gate_max", 0.0))
            _rsi_sell_gate_min = float(config.get("rsi_sell_gate_min", 0.0))
            rsi_buy_gate = float(rsi_buy) if rsi_buy is not None else 65.0
            if _rsi_buy_gate_max > 0.0:
                rsi_buy_gate = max(rsi_buy_gate, min(_rsi_buy_gate_max, 85.0))
            else:
                rsi_buy_gate = max(rsi_buy_gate, 65.0)
            rsi_sell_gate = float(rsi_sell) if rsi_sell is not None else 35.0
            if _rsi_sell_gate_min > 0.0:
                rsi_sell_gate = min(rsi_sell_gate, max(_rsi_sell_gate_min, 15.0))
            else:
                rsi_sell_gate = min(rsi_sell_gate, 35.0)

            if (
                sig.signal_type == "BUY"
                and r.get("buy_low") is not None
                and r.get("buy_high") is not None
            ):
                buy_low_tol = float(r.get("buy_low")) * (1 - price_tolerance)
                buy_high_tol = float(r.get("buy_high")) * (1 + price_tolerance)
                in_range = buy_low_tol <= price <= buy_high_tol
                trend_up = regime_state.regime == "TREND_UP"
                range_buyable = regime_state.regime == "RANGE"
                rsi_ok = rsi is not None and float(rsi) <= rsi_buy_gate
                if in_range and (trend_up or range_buyable) and rsi_ok:
                    side = "BUY"
                    reasons = [
                        f"Regime: {regime_state.regime}",
                        "RSI potwierdza",
                        "Cena w zakresie BUY (AI)",
                    ]
                elif demo_allow_soft_buy and trend_up and rsi_ok and not in_range:
                    # Soft entry: trend + RSI spełnione, cena poza zakresem AI
                    # Dodatkowy filtr: RSI < 55 — nie kupuj na overextension
                    rsi_val = float(rsi) if rsi is not None else 50.0
                    if rsi_val < 55.0:
                        side = "BUY"
                        reasons = [
                            f"Regime: {regime_state.regime}",
                            "RSI potwierdza (bez overextension)",
                            "Wejście miękkie — cena poza zakresem AI, ale trend OK",
                        ]
                    # else: RSI za wysoki dla soft entry — filtr zapobiega kupowaniu na szczycie
            elif (
                sig.signal_type == "SELL"
                and r.get("sell_low") is not None
                and r.get("sell_high") is not None
            ):
                sell_low_tol = float(r.get("sell_low")) * (1 - price_tolerance)
                sell_high_tol = float(r.get("sell_high")) * (1 + price_tolerance)
                if (
                    sell_low_tol <= price <= sell_high_tol
                    and ema20 is not None
                    and ema50 is not None
                    and float(ema20) < float(ema50)
                    and rsi is not None
                    and float(rsi) >= rsi_sell_gate
                ):
                    side = "SELL"
                    reasons = [
                        "Trend spadkowy (EMA20<EMA50)",
                        "RSI (wysoki) potwierdza",
                        "Cena w zakresie SELL (AI)",
                    ]

            if side is None:
                # Diagnostyka: które konkretnie filtry zawiodły
                _filter_fails: list[str] = []
                if sig.signal_type == "BUY":
                    if regime_state.regime in {"TREND_DOWN", "CHAOS"}:
                        _filter_fails.append(
                            f"regime={regime_state.regime} blokuje nowe longi"
                        )
                    bl = r.get("buy_low")
                    bh = r.get("buy_high")
                    if bl is not None and bh is not None:
                        buy_low_tol = float(bl) * (1 - price_tolerance)
                        buy_high_tol = float(bh) * (1 + price_tolerance)
                        if not (buy_low_tol <= price <= buy_high_tol):
                            _filter_fails.append(
                                f"cena {round(price,4)} poza strefą BUY [{round(buy_low_tol,4)}–{round(buy_high_tol,4)}]"
                            )
                    if (
                        ema20 is not None
                        and ema50 is not None
                        and float(ema20) <= float(ema50)
                    ):
                        _filter_fails.append(
                            f"trend: EMA20({round(float(ema20),2)}) ≤ EMA50({round(float(ema50),2)}) — trend spadkowy"
                        )
                    if rsi is not None and float(rsi) > rsi_buy_gate:
                        _filter_fails.append(
                            f"RSI({round(float(rsi),1)}) > próg kupna {round(rsi_buy_gate,1)}"
                        )
                elif sig.signal_type == "SELL":
                    sl = r.get("sell_low")
                    sh = r.get("sell_high")
                    if sl is not None and sh is not None:
                        sell_low_tol = float(sl) * (1 - price_tolerance)
                        sell_high_tol = float(sh) * (1 + price_tolerance)
                        if not (sell_low_tol <= price <= sell_high_tol):
                            _filter_fails.append(
                                f"cena {round(price,4)} poza strefą SELL [{round(sell_low_tol,4)}–{round(sell_high_tol,4)}]"
                            )
                    if (
                        ema20 is not None
                        and ema50 is not None
                        and float(ema20) >= float(ema50)
                    ):
                        _filter_fails.append(
                            f"trend: EMA20({round(float(ema20),2)}) ≥ EMA50({round(float(ema50),2)}) — trend wzrostowy"
                        )
                    if rsi is not None and float(rsi) < rsi_sell_gate:
                        _filter_fails.append(
                            f"RSI({round(float(rsi),1)}) < próg sprzedaży {round(rsi_sell_gate,1)}"
                        )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="signal_filters_not_met",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check={
                        "ema20": ema20,
                        "ema50": ema50,
                        "rsi": rsi,
                        "rsi_buy_gate": rsi_buy_gate,
                        "rsi_sell_gate": rsi_sell_gate,
                        "current_price": price,
                        "signal_type": sig.signal_type,
                    },
                    details={"range": r, "filter_fails": _filter_fails},
                )
                if str(sig.signal_type).upper() == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "signal_filters_not_met",
                        fails=" | ".join(_filter_fails[:3]),
                        regime=regime_state.regime,
                    )
                continue

            if side == "SELL":
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="spot_sell_managed_by_exit_engine",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary={
                        **signal_summary,
                        "market_regime": regime_state.regime,
                    },
                    details={"reasons": reasons},
                )
                continue

            position_action = "new_entry"
            if side == "BUY" and position is not None:
                # Nie blokuj ślepo BUY na istniejącej pozycji.
                # Dopuszczamy add/rebalance, a ostateczna decyzja zapadnie na poziomie portfela.
                position_action = "add_to_position"
            if side == "SELL" and position is None:
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="sell_blocked_no_position",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                )
                continue

            # Pozycjonowanie wg ATR (risk per trade)
            loss_streak = int(state.get("loss_streak", 0))
            win_streak = int(state.get("win_streak", 0))
            risk_scale = float(params.get("risk_scale", 1.0))
            # Tier override: mnożnik rozmiaru pozycji
            risk_scale *= tier_risk_scale
            risk_amount = equity * base_risk_per_trade * risk_scale
            stop_distance = float(atr) * atr_stop_mult
            atr_qty = risk_amount / stop_distance if stop_distance > 0 else base_qty
            qty = max(min_qty, min(max_qty, atr_qty))
            qty = (
                qty
                * max(0.2, 1 - (loss_streak * 0.15))
                * (1 + min(win_streak * 0.05, 0.2))
            )
            if crash:
                qty = max(base_qty * 0.1, qty * 0.25)
            if side == "SELL" and position is not None:
                qty = min(float(position.quantity), qty)
            if side == "BUY":
                if price > 0:
                    # Ogranicz do max_cash_pct_per_trade (domyślnie 1/max_open_positions)
                    # Zapobiega wydaniu całej gotówki na jeden trade
                    max_open = tc.get("max_open_positions", 3)
                    max_cash_pct = float(
                        config.get("max_cash_pct_per_trade", 1.0 / max(max_open, 1))
                    )
                    max_cash_for_trade = available_cash * max_cash_pct
                    # Odlicz prowizję od dostępnych środków (entry + exit fee)
                    _taker = float(config.get("taker_fee_rate", 0.001))
                    max_cash_after_fees = max_cash_for_trade / (1 + _taker)
                    max_affordable = max_cash_after_fees / float(price)
                    qty = min(qty, max_affordable)
                    # Podnieś do min_order_notional gdy ATR-sizing daje za małą kwotę
                    # (np. BTC: ryzyko 10 EUR / ATR 1000 EUR = 0.01 BTC = poniżej min)
                    if (
                        qty * price < min_order_notional
                        and max_affordable * price >= min_order_notional
                    ):
                        qty = min_order_notional / float(price)
                if qty < min_qty:
                    self._trace_decision(
                        db,
                        symbol=symbol,
                        action="SKIP",
                        reason_code="insufficient_cash_or_qty_below_min",
                        runtime_ctx=runtime_ctx,
                        mode=_current_mode,
                        signal_summary=signal_summary,
                        execution_check={
                            "eligible": False,
                            "available_cash": available_cash,
                            "min_qty": min_qty,
                        },
                    )
                    continue

            # Rating decyzji 1-5
            rating = 1
            if float(sig.confidence) >= 0.75:
                rating += 1
            if float(sig.confidence) >= 0.85:
                rating += 1
            if ema20 is not None and ema50 is not None:
                if (side == "BUY" and float(ema20) > float(ema50)) or (
                    side == "SELL" and float(ema20) < float(ema50)
                ):
                    rating += 1
            if rsi is not None:
                if (side == "BUY" and float(rsi) <= float(rsi_buy or 50)) or (
                    side == "SELL" and float(rsi) >= float(rsi_sell or 50)
                ):
                    rating += 1
            rating = min(rating, 5)

            # Extreme entry — bonus jakości, NIE blokada obowiązkowa
            # Premia za idealny punkt wejścia (cena na ekstremalnym poziomie zakresu AI)
            is_extreme = False
            if all(k in r for k in ["buy_low", "buy_high", "sell_low", "sell_high"]):
                buy_low_v = float(r.get("buy_low"))
                buy_high_v = float(r.get("buy_high"))
                sell_low_v = float(r.get("sell_low"))
                sell_high_v = float(r.get("sell_high"))
                buy_edge = buy_low_v + (buy_high_v - buy_low_v) * extreme_margin_pct
                sell_edge = (
                    sell_high_v - (sell_high_v - sell_low_v) * extreme_margin_pct
                )
                if side == "BUY" and price <= buy_edge:
                    is_extreme = True
                if side == "SELL" and price >= sell_edge:
                    is_extreme = True

            if is_extreme:
                # Premia: idealne wejście → +1 do ratingu
                rating = min(5, rating + 1)

            trend_score = (
                30
                if regime_state.regime == "TREND_UP"
                else (14 if regime_state.regime == "RANGE" else 0)
            )
            momentum_score = min(20, max(0, int(float(sig.confidence) * 20)))
            volume_ratio_15m = float(ind_15m.get("volume_ratio") or 1.0)
            volume_score = (
                15
                if volume_ratio_15m >= 1.05
                else (8 if volume_ratio_15m >= 0.95 else 2)
            )
            order_book_score = 5
            realized_vol_pct = (
                ((float(atr) / float(price)) * 100.0) if price > 0 else 0.0
            )
            volatility_score = (
                10
                if 0.4 <= realized_vol_pct <= 4.0
                else (6 if realized_vol_pct > 0 else 0)
            )
            ai_conf_score = min(15, max(0, int(float(sig.confidence) * 15)))
            signal_score = float(
                trend_score
                + momentum_score
                + volume_score
                + order_book_score
                + volatility_score
                + ai_conf_score
            )

            # Bramka jakości wejścia — odrzuć słabe sygnały.
            # rating (0-5) i signal_score (0-100) są oceniane niezależnie.
            effective_entry_score_threshold = float(entry_score_threshold)
            if relaxed_entry_mode:
                effective_entry_score_threshold = min(
                    effective_entry_score_threshold,
                    max(0.0, relaxed_min_entry_score),
                )

            if (
                rating < min_rating_gate
                or signal_score < effective_entry_score_threshold
            ):
                if str(sig.signal_type).upper() == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "entry_score_below_min",
                        rating=rating,
                        min_rating=min_rating_gate,
                        signal_score=round(float(signal_score), 2),
                        min_signal_score=round(
                            float(effective_entry_score_threshold), 2
                        ),
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="entry_score_below_min",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check={
                        "rating": rating,
                        "min_rating_gate": min_rating_gate,
                        "signal_score": signal_score,
                        "signal_score_min": effective_entry_score_threshold,
                        "market_regime": regime_state.regime,
                        "relaxed_entry_mode": relaxed_entry_mode,
                    },
                )
                continue

            expected_move_ratio = (
                (float(atr) * atr_take_mult) / float(price) if price > 0 else 0.0
            )
            risk_reward = atr_take_mult / max(atr_stop_mult, 1e-9)
            costs_pct = estimate_trade_costs(config)
            total_cost_ratio = costs_pct.total_cost_pct / 100.0
            # Tier override: wyższy min_edge_multiplier, ale nigdy poniżej 1.8
            effective_edge_mult = max(1.8, min_edge_multiplier + tier_edge_add)
            entry_decision = validate_long_entry(
                regime=regime_state.regime,
                signal_score=signal_score,
                expected_move_pct=expected_move_ratio * 100.0,
                risk_reward=risk_reward,
                costs=costs_pct,
                min_score=50.0,
                min_rr=max(1.6, min_expected_rr),
                min_profit_buffer_pct=float(config.get("min_net_profit_pct", 0.8)),
                allow_range=True,
            )
            cost_gate_pass = entry_decision.allowed
            notional = float(price) * float(qty)

            cost_check = {
                "eligible": cost_gate_pass,
                "expected_move_ratio": expected_move_ratio,
                "expected_move_pct": expected_move_ratio * 100.0,
                "required_move_ratio": total_cost_ratio * effective_edge_mult,
                "total_cost_ratio": total_cost_ratio,
                "estimated_total_cost_pct": costs_pct.total_cost_pct,
                "maker_fee_rate": maker_fee_rate,
                "taker_fee_rate": taker_fee_rate,
                "slippage_bps": slippage_bps,
                "spread_buffer_bps": spread_buffer_bps,
                "min_edge_multiplier": effective_edge_mult,
                "risk_reward": risk_reward,
                "market_regime": regime_state.regime,
                "reasons": entry_decision.reasons,
                "tier": tier_name,
            }
            execution_check = {
                "eligible": notional >= min_order_notional,
                "notional": notional,
                "min_order_notional": min_order_notional,
            }
            # BUY zawsze przechodzi przez portfolio-level decision (bez ślepego max_open gate).
            portfolio_rotation_candidate = side == "BUY"
            risk_context = build_risk_context(
                db,
                symbol=symbol,
                side=side,
                notional=notional,
                strategy_name=f"{_current_mode}_collector",
                mode=_current_mode,
                runtime_config=config,
                config_snapshot_id=runtime_ctx.get("snapshot_id"),
                signal_summary={
                    **signal_summary,
                    "position_action": position_action,
                    "portfolio_rotation_candidate": portfolio_rotation_candidate,
                },
            )
            risk_decision = evaluate_risk(risk_context)
            risk_check = risk_decision.to_dict()

            if not risk_decision.allowed:
                if side == "BUY":
                    _log_why_not_buy(
                        symbol,
                        str(risk_decision.reason_codes[0]),
                        risk_score=round(float(risk_decision.risk_score), 4),
                        action=risk_decision.action,
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code=risk_decision.reason_codes[0],
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check=risk_check,
                )
                continue

            qty = qty * float(risk_decision.position_size_multiplier or 1.0)
            notional = float(price) * float(qty)
            execution_check["notional"] = notional
            execution_check["eligible"] = notional >= min_order_notional

            if not cost_gate_pass:
                if side == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "cost_gate_failed",
                        expected_move_pct=round(
                            float(cost_check["expected_move_pct"]), 4
                        ),
                        total_cost_pct=round(
                            float(cost_check["estimated_total_cost_pct"]), 4
                        ),
                        risk_reward=round(float(cost_check["risk_reward"]), 4),
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="cost_gate_failed",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check=risk_check,
                    cost_check=cost_check,
                    execution_check=execution_check,
                )
                continue

            if not execution_check["eligible"]:
                if side == "BUY":
                    _log_why_not_buy(
                        symbol,
                        "min_notional_guard",
                        notional=round(float(notional), 4),
                        min_notional=round(float(min_order_notional), 4),
                    )
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="min_notional_guard",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    signal_summary=signal_summary,
                    risk_check=risk_check,
                    cost_check=cost_check,
                    execution_check=execution_check,
                )
                continue

            # Zbierz kandydata — pending i Telegram po sortowaniu
            tp = price + float(atr) * atr_take_mult
            sl = price - float(atr) * atr_stop_mult
            why = (
                ", ".join(reasons)
                if reasons
                else "Sygnał + zakresy OpenAI + filtry ryzyka"
            )
            edge_net_score = expected_move_ratio - total_cost_ratio
            candidates.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "price": price,
                    "qty": qty,
                    "tp": tp,
                    "sl": sl,
                    "rating": rating,
                    "why": why,
                    "signal_summary": signal_summary,
                    "risk_check": risk_check,
                    "cost_check": cost_check,
                    "execution_check": execution_check,
                    "range": r,
                    "tier_name": tier_name,
                    "confidence": float(sig.confidence),
                    "edge_net_score": edge_net_score,
                    "expected_move_ratio": expected_move_ratio,
                    "total_cost_ratio": total_cost_ratio,
                    "risk_reward": risk_reward,
                    "market_regime": regime_state.regime,
                    "signal_score": signal_score,
                    "atr": float(atr),
                    "position_action": position_action,
                    "existing_position": position,
                    "has_active_pending": has_active_pending,
                    "pending_cooldown_active": pending_cooldown_active,
                }
            )

        # --- Ranking kandydatów: portfolio-level ranking ---
        candidate_scores = rank_entry_candidates(candidates, config)
        score_map = {c.symbol: c for c in candidate_scores}
        for cand in candidates:
            s = score_map.get(cand["symbol"])
            cand["entry_score"] = s.entry_score if s else 0.0
            cand["expected_value_net"] = (
                s.expected_value_net if s else cand.get("edge_net_score", 0.0)
            )
            cand["risk_adjusted_return"] = s.risk_adjusted_return if s else 0.0
        candidates.sort(
            key=lambda c: (c.get("entry_score", 0.0), c.get("edge_net_score", 0.0)),
            reverse=True,
        )

        entries_created = 0
        selected_candidates: list[dict] = []

        # 1) Najpierw kandydaci add/rebalance na istniejących pozycjach (nie zużywają slotu)
        add_candidates = [
            c
            for c in candidates
            if c.get("position_action") in {"add_to_position", "rebalance"}
        ]
        if add_candidates:
            selected_candidates.extend(add_candidates[:1])

        # 2) Jeśli są wolne sloty, dodaj najlepsze nowe wejścia
        if slots_available > 0:
            new_entries = [
                c for c in candidates if c.get("position_action") == "new_entry"
            ]
            selected_candidates.extend(new_entries[:slots_available])
        else:
            # 3) Brak wolnych slotów -> sprawdź czy warto rotować portfel
            new_entries = [
                c for c in candidates if c.get("position_action") == "new_entry"
            ]
            if new_entries and open_positions_scored:
                best_new = new_entries[0]
                best_new_score = score_map.get(best_new["symbol"])
                worst_open_score = open_positions_scored[0]

                if best_new_score is not None:
                    decision = compute_replacement_decision(
                        best_new_score, worst_open_score, config
                    )

                    # Anty-churn guards
                    rotations_last_hour = (
                        db.query(DecisionTrace)
                        .filter(
                            DecisionTrace.mode == _current_mode,
                            DecisionTrace.reason_code == "portfolio_rotation_triggered",
                            DecisionTrace.timestamp >= now - timedelta(hours=1),
                        )
                        .count()
                    )
                    worst_position_obj = next(
                        (
                            p
                            for p in open_positions
                            if (p.symbol or "") == worst_open_score.symbol
                        ),
                        None,
                    )
                    worst_age_minutes = worst_open_score.age_minutes
                    cooldown_ok = True
                    if (
                        worst_position_obj is not None
                        and worst_position_obj.updated_at is not None
                    ):
                        cooldown_ok = (
                            now - worst_position_obj.updated_at
                        ).total_seconds() >= replacement_cooldown_minutes * 60

                    churn_ok = rotations_last_hour < max_rotation_per_hour
                    age_ok = worst_age_minutes >= min_position_lifetime_minutes
                    edge_ok = decision.replacement_net_advantage > min_replacement_edge
                    logger.info(
                        "PORTFOLIO DECISION: best_new=%s score=%.4f | worst_open=%s score=%.4f | net_advantage=%+.4f | decision=%s",
                        best_new["symbol"],
                        float(best_new.get("entry_score", 0.0)),
                        worst_open_score.symbol,
                        float(worst_open_score.hold_score),
                        float(decision.replacement_net_advantage),
                        (
                            "REPLACE"
                            if (
                                decision.should_replace
                                and cooldown_ok
                                and churn_ok
                                and age_ok
                                and edge_ok
                            )
                            else "HOLD"
                        ),
                    )

                    if (
                        decision.should_replace
                        and cooldown_ok
                        and churn_ok
                        and age_ok
                        and edge_ok
                        and worst_position_obj is not None
                    ):
                        # Utwórz pending SELL dla najsłabszej pozycji
                        self._create_pending_order(
                            db=db,
                            symbol=worst_position_obj.symbol,
                            side="SELL",
                            price=float(
                                worst_position_obj.current_price
                                or worst_position_obj.entry_price
                                or 0.0
                            ),
                            qty=float(worst_position_obj.quantity or 0.0),
                            mode=_current_mode,
                            reason=(
                                f"portfolio_rotation_triggered: replace {worst_position_obj.symbol} "
                                f"({worst_open_score.hold_score:.3f}) -> {best_new['symbol']} "
                                f"({best_new.get('entry_score', 0.0):.3f}), net_adv={decision.replacement_net_advantage:.4f}"
                            ),
                            config_snapshot_id=runtime_ctx.get("snapshot_id"),
                            strategy_name=f"{_current_mode}_collector",
                        )
                        self._trace_decision(
                            db,
                            symbol=best_new["symbol"],
                            action="ROTATE",
                            reason_code="portfolio_rotation_triggered",
                            runtime_ctx=runtime_ctx,
                            mode=_current_mode,
                            signal_summary=best_new.get("signal_summary", {}),
                            details={
                                "worst_open_symbol": worst_open_score.symbol,
                                "worst_hold_score": worst_open_score.hold_score,
                                "best_new_entry_score": best_new.get(
                                    "entry_score", 0.0
                                ),
                                "replacement_net_advantage": decision.replacement_net_advantage,
                                "total_replacement_cost": decision.total_replacement_cost,
                            },
                        )
                        best_new["portfolio_rotation_candidate"] = True
                        selected_candidates.append(best_new)
                    else:
                        self._trace_decision(
                            db,
                            symbol=best_new["symbol"],
                            action="SKIP",
                            reason_code=(
                                "buy_deferred_insufficient_rotation_edge"
                                if not edge_ok
                                else "buy_rejected_inferior_to_open_positions"
                            ),
                            runtime_ctx=runtime_ctx,
                            mode=_current_mode,
                            signal_summary=best_new.get("signal_summary", {}),
                            details={
                                "replacement_net_advantage": decision.replacement_net_advantage,
                                "required_min_replacement_edge": min_replacement_edge,
                                "cooldown_ok": cooldown_ok,
                                "churn_ok": churn_ok,
                                "age_ok": age_ok,
                                "rotations_last_hour": rotations_last_hour,
                                "max_rotation_per_hour": max_rotation_per_hour,
                            },
                        )

        for cand in selected_candidates:
            symbol = cand["symbol"]
            side = cand["side"]
            price = cand["price"]
            qty = cand["qty"]
            tp = cand["tp"]
            sl = cand["sl"]
            rating = cand["rating"]
            why = cand["why"]
            tier_name = cand["tier_name"]
            signal_summary = {
                **cand["signal_summary"],
                "position_action": cand.get("position_action", "new_entry"),
                "portfolio_rotation_candidate": bool(
                    cand.get("portfolio_rotation_candidate", False)
                ),
            }
            risk_check = cand["risk_check"]
            cost_check = cand["cost_check"]
            execution_check = cand["execution_check"]
            r = cand["range"]
            action_pl = "KUP" if side == "BUY" else "SPRZEDAJ"
            decision_reason_code = "all_gates_passed"
            if cand.get("portfolio_rotation_candidate"):
                decision_reason_code = "buy_replaced_worst_position"

            portfolio_action = "ADD_NEW"
            if cand.get("position_action") in {"add_to_position", "rebalance"}:
                portfolio_action = "REBALANCE"
            if cand.get("portfolio_rotation_candidate"):
                portfolio_action = "REPLACE_WORST"

            # Pending orders są teraz oceniane portfelowo, nie blokują ślepo.
            active_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.symbol == symbol,
                    PendingOrder.mode == _current_mode,
                    PendingOrder.status.in_(list(ACTIVE_PENDING_STATUSES)),
                )
                .order_by(PendingOrder.created_at.desc())
                .first()
            )
            if active_pending is not None:
                min_pending_replace_delta = float(
                    config.get("min_pending_replace_delta", 0.03)
                )
                pending_ref_price = float(active_pending.price or price or 0.0)
                pending_entry_score = 0.0
                if pending_ref_price > 0:
                    pending_entry_score = float(active_pending.quantity or 0.0) / max(
                        pending_ref_price, 1e-9
                    )
                if (
                    cand.get("entry_score", 0.0)
                    > pending_entry_score + min_pending_replace_delta
                ):
                    active_pending.status = "REJECTED"
                    active_pending.reason = (
                        "cancelled_by_portfolio_engine_better_candidate: "
                        f"{symbol} new_entry_score={cand.get('entry_score', 0.0):.4f} "
                        f"> pending_ref={pending_entry_score:.4f}"
                    )
                    portfolio_action = "CANCEL_PENDING_AND_REPLACE"
                else:
                    self._trace_decision(
                        db,
                        symbol=symbol,
                        action="HOLD",
                        reason_code="buy_rejected_inferior_to_open_positions",
                        runtime_ctx=runtime_ctx,
                        mode=_current_mode,
                        signal_summary=signal_summary,
                        details={
                            "pending_id": active_pending.id,
                            "pending_entry_score_ref": pending_entry_score,
                            "candidate_entry_score": cand.get("entry_score", 0.0),
                            "min_pending_replace_delta": min_pending_replace_delta,
                        },
                    )
                    continue

            # Re-check dostępnej gotówki (available_cash był współdzielony podczas screeningu)
            if side == "BUY" and price > 0:
                current_max_affordable = available_cash / float(price)
                if current_max_affordable < min_qty:
                    if side == "BUY":
                        _log_why_not_buy(
                            symbol,
                            "insufficient_cash_or_qty_below_min",
                            available_cash=round(float(available_cash), 4),
                            min_qty=round(float(min_qty), 8),
                        )
                    self._trace_decision(
                        db,
                        symbol=symbol,
                        action="SKIP",
                        reason_code="insufficient_cash_or_qty_below_min",
                        runtime_ctx=runtime_ctx,
                        mode=_current_mode,
                        signal_summary=signal_summary,
                        execution_check={
                            "eligible": False,
                            "available_cash": available_cash,
                            "min_qty": min_qty,
                        },
                    )
                    continue
                qty = min(qty, current_max_affordable)

            self._trace_decision(
                db,
                symbol=symbol,
                action=portfolio_action,
                reason_code=decision_reason_code,
                runtime_ctx=runtime_ctx,
                mode=_current_mode,
                signal_summary=signal_summary,
                risk_check=risk_check,
                cost_check=cost_check,
                execution_check=execution_check,
                details={
                    "side": side,
                    "qty": qty,
                    "price": price,
                    "rating": rating,
                    "why": why,
                    "tier": tier_name,
                    "edge_net_score": cand["edge_net_score"],
                    "entry_score": cand.get("entry_score", 0.0),
                    "expected_value_net": cand.get("expected_value_net", 0.0),
                    "rank": candidates.index(cand) + 1,
                    "total_candidates": len(candidates),
                    "portfolio_action": portfolio_action,
                    "auto_execute": not demo_require_manual_confirm,
                },
            )
            if side == "BUY":
                logger.info(
                    "BUY_ALLOWED mode=%s symbol=%s entry_score=%.3f reason=%s risk_score=%.3f",
                    _current_mode,
                    symbol,
                    float(cand.get("entry_score", 0.0)),
                    decision_reason_code,
                    float(risk_check.get("risk_score", 0.0)),
                )
            pending_id = self._create_pending_order(
                db=db,
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                mode=_current_mode,
                reason=f"{why}. Pewność {int(cand['confidence']*100)}%, rating {rating}/5.",
                config_snapshot_id=runtime_ctx.get("snapshot_id"),
                strategy_name=f"{_current_mode}_collector",
            )

            # Auto-confirm + auto-execute gdy demo_require_manual_confirm=False
            if not demo_require_manual_confirm:
                try:
                    pending_obj = (
                        db.query(PendingOrder)
                        .filter(PendingOrder.id == pending_id)
                        .first()
                    )
                    if pending_obj:
                        pending_obj.status = "PENDING_CONFIRMED"
                        pending_obj.confirmed_at = now
                        db.flush()
                except Exception as exc_confirm:
                    log_exception(
                        "demo_trading", "Błąd auto-confirm pending", exc_confirm, db=db
                    )

            if side == "BUY":
                try:
                    available_cash = max(
                        0.0, float(available_cash) - (float(price) * float(qty))
                    )
                except Exception:
                    pass

            buy_rng = f"{r.get('buy_low')} – {r.get('buy_high')}"
            sell_rng = f"{r.get('sell_low')} – {r.get('sell_high')}"
            action_emoji = "🟢" if side == "BUY" else "🔴"
            if demo_require_manual_confirm:
                confirm_block = (
                    f"\nCo zrobić:\n"
                    f"/confirm {pending_id} — potwierdź\n"
                    f"/reject {pending_id} — odrzuć"
                )
                alert_title = f"{_mode_label}: POTWIERDŹ"
            else:
                confirm_block = "\n✅ Auto-potwierdzone — zlecenie przekazane do execution (oczekiwanie na fill)."
                alert_title = f"{_mode_label}: ZLECENIE W KOLEJCE"
            rank_info = f"Kandydat #{candidates.index(cand) + 1}/{len(candidates)}"
            conf_pct = int(cand["confidence"] * 100)
            edge_score = cand.get("edge_net_score", 0)
            msg = (
                f"{action_emoji} [{_mode_label}] {alert_title}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol: {symbol} [{tier_name}]\n"
                f"Akcja: {action_pl}\n"
                f"Cena: {price}\n"
                f"TP: {tp:.6f} | SL: {sl:.6f}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Pewność: {conf_pct}% | Ocena: {rating}/5 | Edge: {edge_score:.1f}\n"
                f"Powód techniczny: {why}\n"
                f"Pozycja: {rank_info}\n"
                f"Zakresy AI: KUP {buy_rng} | SPRZEDAJ {sell_rng}\n"
                f"Typ pozycji: {_mode_label.lower()}"
                f"{confirm_block}"
            )
            self._send_telegram_alert(alert_title, msg, force_send=True)
            db.add(
                Alert(
                    alert_type="SIGNAL",
                    severity="INFO",
                    title=f"{_mode_label} {'AUTO' if not demo_require_manual_confirm else 'PENDING'} {side} {symbol}",
                    message=f"{'Auto-potwierdzono i zakolejkowano do execution' if not demo_require_manual_confirm else 'Pending'} ID {pending_id}. {side} {symbol} qty={qty} price={price}. {why}.",
                    symbol=symbol,
                    is_sent=True,
                    timestamp=now,
                )
            )
            entries_created += 1

        return entries_created

    # ------------------------------------------------------------------
    # Etap 3: globalny hamulec strat
    # ------------------------------------------------------------------

    def _apply_daily_loss_brake(self, db: Session, tc: dict):
        daily_loss_triggered = tc["daily_loss_triggered"]
        if not daily_loss_triggered:
            return
        demo_quote_ccy = tc["demo_quote_ccy"]
        base_cooldown = tc["base_cooldown"]
        loss_streak_limit = tc["loss_streak_limit"]
        tier_map = tc.get("tier_map", {})
        for sym in self.watchlist:
            sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
            if not sym_norm.endswith(demo_quote_ccy):
                continue
            # HOLD MODE: nie modyfikuj cooldownów dla pozycji strategicznych
            sym_tier = tier_map.get(sym_norm, {})
            if sym_tier.get("hold_mode"):
                continue
            state = self.demo_state.get(
                sym, {"loss_streak": 0, "cooldown": base_cooldown}
            )
            state["loss_streak"] = min(
                int(state.get("loss_streak", 0)) + 1, loss_streak_limit
            )
            state["cooldown"] = min(
                base_cooldown * (1 + int(state["loss_streak"])), 3600
            )
            self.demo_state[sym] = state
        msg = "🟠 Dzienny limit straty osiągnięty\nSystem ograniczył ryzyko na wszystkich symbolach.\nBot nadal działa, ale nowe transakcje są wstrzymane.\nCo zrobić: poczekaj na następny dzień lub przejrzyj otwarte pozycje."
        log_to_db("WARNING", "demo_trading", msg, db=db)
        self._send_telegram_alert("RISK: Daily loss", msg, force_send=True)

    def _detect_crash(
        self, db: Session, symbol: str, window_minutes: int, drop_pct: float
    ) -> bool:
        """
        Wykryj gwałtowny spadek w krótkim oknie na live danych.
        """
        since = utc_now_naive() - timedelta(minutes=window_minutes)
        klines = (
            db.query(Kline)
            .filter(
                Kline.symbol == symbol,
                Kline.timeframe == "1m",
                Kline.open_time >= since,
            )
            .order_by(Kline.open_time)
            .all()
        )
        if len(klines) < 5:
            return False
        start_price = klines[0].open
        end_price = klines[-1].close
        if start_price and start_price > 0:
            change_pct = ((end_price - start_price) / start_price) * 100
            return change_pct <= -abs(drop_pct)
        return False

    def collect_market_data(self, db: Session):
        """
        Zbierz dane rynkowe (ticker prices) dla watchlist

        Args:
            db: Sesja bazy danych
        """
        logger.info("📊 Collecting market data...")

        for symbol in self.watchlist:
            try:
                # Pobierz 24h ticker
                ticker = self.binance.get_24hr_ticker(symbol)

                if ticker:
                    # Zapisz do bazy
                    market_data = MarketData(
                        symbol=symbol,
                        price=ticker["last_price"],
                        volume=ticker["volume"],
                        bid=ticker["bid_price"],
                        ask=ticker["ask_price"],
                        timestamp=utc_now_naive(),
                    )
                    db.add(market_data)

                    logger.info(
                        f"✅ {symbol}: ${ticker['last_price']:.2f} "
                        f"({ticker['price_change_percent']:+.2f}%)"
                    )
                else:
                    logger.warning(f"⚠️  Failed to get ticker for {symbol}")
                    log_to_db(
                        "WARNING", "collector", f"Brak tickera dla {symbol}", db=db
                    )

                # Rate limiting - nie bombardujemy API
                time.sleep(0.2)

            except Exception as e:
                logger.error(f"❌ Error collecting data for {symbol}: {str(e)}")
                log_exception(
                    "collector", f"Błąd collect_market_data dla {symbol}", e, db=db
                )

        try:
            db.commit()
            logger.info("✅ Market data committed to database")
        except Exception as e:
            logger.error(f"❌ Error committing market data: {str(e)}")
            log_exception("collector", "Błąd commit market data", e, db=db)
            db.rollback()

    def collect_klines(self, db: Session):
        """
        Zbierz dane świecowe (klines) dla watchlist

        Args:
            db: Sesja bazy danych
        """
        logger.info("📈 Collecting klines...")

        for symbol in self.watchlist:
            for timeframe in self.kline_timeframes:
                try:
                    # Pobierz ostatnie 100 świec
                    klines = self.binance.get_klines(symbol, timeframe, limit=100)

                    if klines:
                        saved_count = 0
                        for k in klines:
                            # Sprawdź czy już istnieje (unikamy duplikatów)
                            open_time = datetime.fromtimestamp(k["open_time"] / 1000)
                            close_time = datetime.fromtimestamp(k["close_time"] / 1000)

                            existing = (
                                db.query(Kline)
                                .filter(
                                    Kline.symbol == symbol,
                                    Kline.timeframe == timeframe,
                                    Kline.open_time == open_time,
                                )
                                .first()
                            )

                            if not existing:
                                kline = Kline(
                                    symbol=symbol,
                                    timeframe=timeframe,
                                    open_time=open_time,
                                    close_time=close_time,
                                    open=k["open"],
                                    high=k["high"],
                                    low=k["low"],
                                    close=k["close"],
                                    volume=k["volume"],
                                    quote_volume=k["quote_volume"],
                                    trades=k["trades"],
                                    taker_buy_base=k["taker_buy_base"],
                                    taker_buy_quote=k["taker_buy_quote"],
                                )
                                db.add(kline)
                                saved_count += 1

                        if saved_count > 0:
                            logger.info(
                                f"✅ {symbol} {timeframe}: saved {saved_count} new klines"
                            )
                    else:
                        logger.warning(
                            f"⚠️  Failed to get klines for {symbol} {timeframe}"
                        )
                        log_to_db(
                            "WARNING",
                            "collector",
                            f"Brak klines {symbol} {timeframe}",
                            db=db,
                        )

                    # Rate limiting
                    time.sleep(0.2)

                except Exception as e:
                    logger.error(
                        f"❌ Error collecting klines for {symbol} {timeframe}: {str(e)}"
                    )
                    log_exception(
                        "collector",
                        f"Błąd collect_klines dla {symbol} {timeframe}",
                        e,
                        db=db,
                    )

        try:
            db.commit()
            logger.info("✅ Klines committed to database")
        except Exception as e:
            logger.error(f"❌ Error committing klines: {str(e)}")
            log_exception("collector", "Błąd commit klines", e, db=db)
            db.rollback()

    def run_once(self):
        """Wykonaj jeden cykl zbierania danych"""
        logger.info("🔄 Starting data collection cycle...")

        db = SessionLocal()
        try:
            provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
            # W trybie jednego providera — sprawdź czy klucz jest.
            # W trybie auto — bot nigdy się nie zatrzymuje (fallback → heurystyka).
            if provider in ("openai", "gemini", "groq") and not self._has_any_ai_key():
                self._log_openai_missing()
                # Nie blokuj bota — fallback do heurystyki zadziała w analysis.py
            if provider == "auto" and not self._has_any_ai_key():
                now = utc_now_naive()
                if (
                    not self.last_openai_missing_log_ts
                    or (now - self.last_openai_missing_log_ts).total_seconds() > 300
                ):
                    self.last_openai_missing_log_ts = now
                    msg = "Brak kluczy AI (Gemini/Groq/OpenAI) — AI_PROVIDER=auto → heurystyka ATR/Bollinger."
                    logger.warning(f"⚠️ {msg}")
                    log_to_db("WARNING", "collector", msg, db=db)

            # Zrealizuj zatwierdzone transakcje (DEMO) zanim policzysz kolejne decyzje.
            try:
                self._execute_confirmed_pending_orders(db)
            except Exception as exc:
                log_exception(
                    "collector", "Błąd wykonania potwierdzonych transakcji", exc, db=db
                )

            ws_enabled = effective_bool(db, "ws_enabled", "WS_ENABLED", True)

            # Control Plane: watchlist override z DB (jeśli ustawiona) ma pierwszeństwo.
            wl_override = None
            try:
                wl_override = watchlist_override(db)
            except Exception:
                wl_override = None

            if wl_override is not None:
                if wl_override != self.watchlist:
                    old = ", ".join(self.watchlist) if self.watchlist else "(pusto)"
                    new = ", ".join(wl_override) if wl_override else "(pusto)"
                    logger.info(f"🛠️ Watchlista (override): {old} -> {new}")
                    log_to_db(
                        "INFO",
                        "collector",
                        f"Watchlist override: {old} -> {new}",
                        db=db,
                    )
                    self.watchlist = wl_override
                    if self.ws_running:
                        self.stop_ws()
                        if ws_enabled and self.watchlist:
                            self.start_ws()
                else:
                    self.watchlist = wl_override
            else:
                # Aktualizuj watchlist z portfela tylko co N sekund (lub częściej jeśli pusta).
                self._refresh_watchlist_if_due(db, force=(not self.watchlist))
            if not self.watchlist:
                self._log_no_watchlist(db)
                return

            # Start/stop WS zależnie od ustawień i dostępnej watchlisty
            if ws_enabled and not self.ws_running:
                self.start_ws()
            if (not ws_enabled) and self.ws_running:
                self.stop_ws()

            # Uczenie / kalibracja co 1h
            now = utc_now_naive()
            if (
                not self.last_learning_ts
                or (now - self.last_learning_ts).seconds > 3600
            ):
                self._learn_from_history(db)
                self.last_learning_ts = now

            # Retencja danych — zapobiega przepełnieniu dysku
            self._purge_stale_data(db)

            # Zbierz dane rynkowe
            self.collect_market_data(db)

            # Auto-konwersja fundingu EUR→USDC (jeśli aktywna i wymagana)
            try:
                self._maybe_auto_convert_funding(db)
            except Exception as exc:
                log_exception("collector", "Błąd auto-konwersji fundingu", exc, db=db)

            # Mark-to-market pozycji + snapshoty KPI (DEMO + LIVE)
            self._mark_to_market_positions(db, mode="demo")
            self._mark_to_market_positions(db, mode="live")
            self._persist_demo_snapshot_if_due(db)
            self._persist_live_snapshot_if_due(db)

            # Sync pozycji LIVE DB ↔ Binance (co 5 min)
            try:
                now_sync = utc_now_naive()
                if (
                    not self._last_binance_sync_ts
                    or (now_sync - self._last_binance_sync_ts).total_seconds() > 300
                ):
                    self._sync_binance_positions(db)
                    self._last_binance_sync_ts = now_sync
            except Exception as exc:
                log_exception("collector", "Błąd sync Binance", exc, db=db)

            # DB self-heal / reconcile z Binance (co 60s dla LIVE)
            try:
                from backend.portfolio_reconcile import run_reconcile_cycle
                from backend.runtime_settings import build_runtime_state as _brs

                _rc = _brs(db)
                _rc_mode = str(_rc.get("trading_mode") or "demo").lower()
                if _rc_mode == "live":
                    run_reconcile_cycle(
                        mode="live", trigger="scheduled", notify_telegram=True
                    )
            except Exception as exc:
                log_exception("collector", "Błąd cyklu reconcile", exc, db=db)

            # Generuj sygnały heurystyczne co cykl (do DB dla collectora)
            try:
                from backend.analysis import (
                    _heuristic_ranges,
                    _merge_ranges_with_insights,
                    generate_market_insights,
                    persist_insights_as_signals,
                )

                insights = generate_market_insights(db, self.watchlist, timeframe="1h")
                if insights:
                    ranges = _heuristic_ranges(insights)
                    insights = _merge_ranges_with_insights(insights, ranges)
                    persist_insights_as_signals(db, insights)
            except Exception as exc:
                log_exception(
                    "collector", "Błąd generacji sygnałów heurystycznych", exc, db=db
                )

            # Zbierz świece
            self.collect_klines(db)

            # Analiza + blog (co najmniej raz na godzinę)
            maybe_generate_insights_and_blog(db, self.watchlist)

            # DEMO trading
            self._demo_trading(db, mode="demo")

            # LIVE trading (równoległe z demo)
            try:
                self._demo_trading(db, mode="live")
            except Exception as exc:
                log_exception("collector", "Błąd cyklu LIVE trading", exc, db=db)

            # Wykonaj auto-confirmed transakcje (demo + live)
            try:
                self._execute_confirmed_pending_orders(db)
            except Exception as exc:
                log_exception(
                    "collector", "Błąd wykonania auto-confirmed transakcji", exc, db=db
                )

            # Sprawdź trafność prognoz (co cykl — szybkie)
            try:
                self._check_forecast_accuracy(db)
            except Exception as exc:
                log_exception(
                    "collector", "Błąd weryfikacji trafności prognoz", exc, db=db
                )

            logger.info("✅ Collection cycle completed")
        except Exception as e:
            logger.error(f"❌ Error in collection cycle: {str(e)}")
            log_exception("collector", "Błąd w cyklu zbierania danych", e, db=db)
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Trafność prognoz — weryfikacja po upłynięciu horyzontu
    # ------------------------------------------------------------------
    def _check_forecast_accuracy(self, db: Session):
        """Dla prognoz, których target_ts minął, pobiera aktualną cenę i liczy błąd."""
        now = utc_now_naive()
        pending = (
            db.query(ForecastRecord)
            .filter(
                ForecastRecord.checked == False, ForecastRecord.target_ts <= now
            )  # noqa: E712
            .limit(50)
            .all()
        )
        if not pending:
            return

        binance = get_binance_client()
        price_cache: dict = {}

        for rec in pending:
            try:
                sym = rec.symbol
                if sym not in price_cache:
                    ticker = binance.get_ticker(symbol=sym)
                    price_cache[sym] = float(ticker.get("lastPrice", 0))
                actual = price_cache[sym]
                if actual and rec.forecast_price and rec.forecast_price > 0:
                    rec.actual_price = actual
                    rec.error_pct = (
                        abs((actual - rec.forecast_price) / rec.forecast_price) * 100
                    )
                    if rec.direction and rec.current_price_at_forecast:
                        expected_up = rec.direction == "WZROST"
                        actual_up = actual >= rec.current_price_at_forecast
                        rec.correct_direction = (
                            (expected_up == actual_up)
                            if rec.direction != "BOCZNY"
                            else None
                        )
                rec.checked = True
            except Exception:
                rec.checked = True  # nie blokuj pętlą nieudanych
        try:
            db.commit()
        except Exception:
            db.rollback()

    # ------------------------------------------------------------------
    # Retencja danych — zapobiega przepełnieniu dysku
    # ------------------------------------------------------------------
    _PURGE_BATCH = 5000

    def _purge_stale_data(self, db: Session):
        """Usuwa stare dane w batchach (raw SQL) i opcjonalnie wywołuje VACUUM."""
        now = utc_now_naive()

        # Uruchamiaj co najwyżej raz na godzinę
        if (
            hasattr(self, "_last_purge_ts")
            and self._last_purge_ts
            and (now - self._last_purge_ts).total_seconds() < 3600
        ):
            return
        self._last_purge_ts = now

        purge_specs = [
            ("market_data", "timestamp", timedelta(days=7)),
            ("signals", "timestamp", timedelta(days=7)),
            ("system_logs", "timestamp", timedelta(days=14)),
            ("klines", "open_time", timedelta(days=30)),
            ("decision_traces", "timestamp", timedelta(days=30)),
        ]

        total_deleted = 0
        for table, ts_col, retention in purge_specs:
            cutoff = now - retention
            try:
                batch_total = 0
                while True:
                    result = db.execute(
                        text(
                            f"DELETE FROM {table} WHERE id IN "
                            f"(SELECT id FROM {table} WHERE {ts_col} < :cutoff LIMIT :batch)"
                        ),
                        {"cutoff": cutoff, "batch": self._PURGE_BATCH},
                    )
                    db.commit()
                    deleted = result.rowcount
                    if deleted == 0:
                        break
                    batch_total += deleted
                if batch_total:
                    log_to_db(
                        "INFO",
                        "collector",
                        f"Retencja: usunięto {batch_total} starych wierszy {table}",
                        db=db,
                    )
                    total_deleted += batch_total
            except Exception as exc:
                log_exception("collector", f"Błąd retencji {table}", exc, db=db)
                db.rollback()

        # Wygasanie starych pending orders (>24h)
        try:
            cutoff_pending = now - timedelta(hours=24)
            expired = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.status == "PENDING",
                    PendingOrder.created_at < cutoff_pending,
                )
                .update({"status": "EXPIRED"}, synchronize_session=False)
            )
            if expired:
                log_to_db(
                    "INFO",
                    "collector",
                    f"Retencja: oznaczono {expired} starych pending orders jako EXPIRED (>24h)",
                    db=db,
                )
            db.commit()
        except Exception as exc:
            log_exception("collector", "Błąd retencji pending_orders", exc, db=db)
            db.rollback()

        # VACUUM — odzyskuje miejsce na dysku po dużym czyszczeniu
        if total_deleted > 1000:
            try:
                db.commit()
                db.execute(text("VACUUM"))
                log_to_db(
                    "INFO",
                    "collector",
                    f"VACUUM po usunięciu {total_deleted} wierszy",
                    db=db,
                )
            except Exception:
                pass  # VACUUM nie jest krytyczny

    def _learn_from_history(self, db: Session):
        """Prosta kalibracja parametrów na historii (konserwatywna)."""
        report_lines = []
        # Wczytaj config raz — nie w pętli per-symbol
        _learn_cfg = get_runtime_config(db)
        _base_conf_cfg = float(_learn_cfg.get("demo_min_signal_confidence", 0.48))
        for symbol in self.watchlist:
            since = utc_now_naive() - timedelta(days=self.learning_days)
            klines = (
                db.query(Kline)
                .filter(
                    Kline.symbol == symbol,
                    Kline.timeframe == "1h",
                    Kline.open_time >= since,
                )
                .order_by(Kline.open_time)
                .all()
            )
            if len(klines) < 50:
                continue
            prices = [k.close for k in klines if k.close]
            if len(prices) < 50:
                continue
            returns = []
            for i in range(1, len(prices)):
                if prices[i - 1] > 0:
                    returns.append((prices[i] - prices[i - 1]) / prices[i - 1])
            if not returns:
                continue
            # Volatility estimate
            mean_r = sum(returns) / len(returns)
            var = sum((r - mean_r) ** 2 for r in returns) / max(1, (len(returns) - 1))
            vol = var**0.5

            # Trend strength estimate
            ema20 = sum(prices[-20:]) / 20
            ema50 = sum(prices[-50:]) / 50
            trend_strength = abs(ema20 - ema50) / max(prices[-1], 1e-9)

            # Conservative tuning — base_conf z runtime config (nie hardkod)
            base_conf = _base_conf_cfg
            conf = min(
                base_conf + 0.20,
                base_conf
                + min(0.10, vol * 2)
                + (0.04 if trend_strength < 0.002 else 0),
            )
            risk_scale = max(0.3, min(1.0, 1.0 - vol * 3))

            self.symbol_params[symbol] = {
                "min_confidence": conf,
                "risk_scale": risk_scale,
                "volatility": vol,
                "trend_strength": trend_strength,
            }

            report_lines.append(
                f"{symbol}: conf>={conf:.2f}, risk_scale={risk_scale:.2f}, vol={vol:.4f}"
            )

        if report_lines:
            log_to_db(
                "INFO",
                "learning",
                f"Kalibracja na {self.learning_days} dni: " + " | ".join(report_lines),
                db=db,
            )
            # Persystuj symbol_params do RuntimeSetting (klucz learning_symbol_params)
            try:
                import json as _json

                from backend.runtime_settings import upsert_overrides

                upsert_overrides(
                    db, {"learning_symbol_params": _json.dumps(self.symbol_params)}
                )
            except Exception as _exc:
                log_exception(
                    "learning", "Błąd persistowania symbol_params", _exc, db=db
                )
            # Nie wysyłamy automatycznych raportów uczenia na Telegram (tylko na żądanie)

    def _ws_streams(self) -> str:
        """Buduj URL strumieni WS do Binance. Max URL ~8000 znaków."""
        streams = []
        char_count = 0
        max_url_len = 7000  # Binance limit jest ~8000, zostaw margines

        for symbol in self.watchlist:
            s = symbol.lower()
            # Każda para: "btceur@ticker/btceur@kline_1m/btceur@kline_1h"  ~40 znaków
            new_streams = [f"{s}@ticker", f"{s}@kline_1m", f"{s}@kline_1h"]
            new_str = "/".join(new_streams)
            if char_count + len(new_str) + 1 > max_url_len:
                logger.warning(
                    f"⚠️  WS streams URL >7000 chars, omitting {symbol} (watchlist zbyt długa)"
                )
                break
            streams.extend(new_streams)
            char_count += len(new_str) + 1

        return "/".join(streams)

    async def _handle_ws_message(self, msg: dict):
        data = msg.get("data") or msg
        event = data.get("e")

        if event == "24hrTicker":
            symbol = data.get("s")
            if not symbol:
                return

            db = SessionLocal()
            try:
                market_data = MarketData(
                    symbol=symbol,
                    price=float(data.get("c", 0)),
                    volume=float(data.get("v", 0)),
                    bid=float(data.get("b", 0)),
                    ask=float(data.get("a", 0)),
                    timestamp=utc_now_naive(),
                )
                db.add(market_data)
                db.commit()
            except Exception as exc:
                log_exception(
                    "collector_ws", f"Błąd zapisu tickera {symbol}", exc, db=db
                )
                db.rollback()
            finally:
                db.close()

        elif event == "kline":
            k = data.get("k", {})
            if not k or not k.get("x"):
                return

            symbol = k.get("s")
            timeframe = k.get("i")
            if not symbol or not timeframe:
                return

            db = SessionLocal()
            try:
                open_time = datetime.fromtimestamp(k["t"] / 1000)
                close_time = datetime.fromtimestamp(k["T"] / 1000)

                existing = (
                    db.query(Kline)
                    .filter(
                        Kline.symbol == symbol,
                        Kline.timeframe == timeframe,
                        Kline.open_time == open_time,
                    )
                    .first()
                )
                if not existing:
                    kline = Kline(
                        symbol=symbol,
                        timeframe=timeframe,
                        open_time=open_time,
                        close_time=close_time,
                        open=float(k.get("o", 0)),
                        high=float(k.get("h", 0)),
                        low=float(k.get("l", 0)),
                        close=float(k.get("c", 0)),
                        volume=float(k.get("v", 0)),
                        quote_volume=float(k.get("q", 0)),
                        trades=int(k.get("n", 0)),
                        taker_buy_base=float(k.get("V", 0)),
                        taker_buy_quote=float(k.get("Q", 0)),
                    )
                    db.add(kline)
                    db.commit()
            except Exception as exc:
                log_exception(
                    "collector_ws",
                    f"Błąd zapisu kline {symbol} {timeframe}",
                    exc,
                    db=db,
                )
                db.rollback()
            finally:
                db.close()

    async def _ws_loop(self):
        while self.ws_running:
            streams = self._ws_streams()
            if not streams:
                logger.warning("⚠️ Watchlist empty, waiting for data...")
                await asyncio.sleep(5)
                continue

            url = f"wss://stream.binance.com:9443/stream?streams={streams}"
            try:
                # Zwiększone timeout'y dla bardziej niezawodnego połączenia
                async with websockets.connect(
                    url,
                    ping_interval=30,  # 30s zamiast 20s
                    ping_timeout=10,  # 10s zamiast 20s
                    close_timeout=10,
                    max_size=10000000,  # max message size
                ) as ws:
                    log_to_db(
                        "INFO",
                        "collector_ws",
                        f"Połączono z Binance WS ({len(self.watchlist)} symboli)",
                    )
                    logger.info(
                        f"📡 WS connected ({len(self.watchlist)} symboli na URL: {url[:80]}...)"
                    )
                    self.ws_backoff_seconds = 2

                    while self.ws_running:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=60)
                            msg = json.loads(raw)
                            await self._handle_ws_message(msg)
                        except asyncio.TimeoutError:
                            logger.warning("⚠️ WS recv timeout — reconnecting")
                            break
            except ConnectionRefusedError as exc:
                log_exception(
                    "collector_ws", "Connection refused — Binance WS niedostępny", exc
                )
                await asyncio.sleep(self.ws_backoff_seconds)
                self.ws_backoff_seconds = min(self.ws_backoff_seconds * 2, 120)
            except asyncio.TimeoutError as exc:
                log_exception("collector_ws", "WS connect timeout — network issue", exc)
                await asyncio.sleep(self.ws_backoff_seconds)
                self.ws_backoff_seconds = min(self.ws_backoff_seconds * 2, 120)
            except Exception as exc:
                log_exception("collector_ws", "Błąd połączenia WS - reconnect", exc)
                await asyncio.sleep(self.ws_backoff_seconds)
                self.ws_backoff_seconds = min(self.ws_backoff_seconds * 2, 120)

    def _run_ws_thread(self):
        asyncio.run(self._ws_loop())

    def start_ws(self):
        if self.ws_running:
            return
        if not self.watchlist:
            logger.info("📡 WS pominięty — pusta watchlista")
            return
        self.ws_running = True
        self.ws_thread = threading.Thread(target=self._run_ws_thread, daemon=True)
        self.ws_thread.start()
        logger.info("📡 Binance WS started")

    def stop_ws(self):
        if not self.ws_running:
            return
        self.ws_running = False
        if self.ws_thread and self.ws_thread.is_alive():
            try:
                self.ws_thread.join(timeout=5)
            except Exception:
                pass
        self.ws_thread = None
        logger.info("🛑 Binance WS stopped")

    def start(self):
        """Uruchom kolektor w pętli"""
        self.running = True
        logger.info("🚀 DataCollector started")

        while self.running:
            try:
                self.run_once()

                # Czekaj do następnego cyklu
                logger.info(f"⏰ Next collection in {self.interval} seconds...")
                time.sleep(self.interval)

            except KeyboardInterrupt:
                logger.info("⚠️  Keyboard interrupt received")
                self.stop()
            except Exception as e:
                logger.error(f"❌ Unexpected error in collector loop: {str(e)}")
                log_exception("collector", "Błąd w pętli kolektora", e)
                time.sleep(5)  # Krótka pauza przed ponowną próbą

    def stop(self):
        """Zatrzymaj kolektor"""
        self.running = False
        self.stop_ws()
        logger.info("🛑 DataCollector stopped")


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("RLdC Trading Bot - Data Collector")
    logger.info("=" * 60)

    collector = DataCollector()

    try:
        collector.start()
    except Exception as e:
        logger.error(f"❌ Fatal error: {str(e)}")
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
