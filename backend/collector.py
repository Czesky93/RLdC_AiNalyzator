"""
Data Collector - zbiera dane z Binance i zapisuje do bazy
Uruchamiany jako osobny proces w tle
"""
import os
import time
import json
import asyncio
import threading
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
import logging
import websockets
from sqlalchemy.orm import Session
from sqlalchemy import desc, text

from backend.database import (
    SessionLocal,
    MarketData,
    Kline,
    Order,
    Position,
    Alert,
    Signal,
    PendingOrder,
    AccountSnapshot,
    ExitQuality,
    ForecastRecord,
    SystemLog,
    DecisionTrace,
    attach_costs_to_order,
    save_cost_entry,
    save_decision_trace,
    utc_now_naive
)
from backend.binance_client import get_binance_client
from backend.system_logger import log_to_db, log_exception
from backend.analysis import (
    maybe_generate_insights_and_blog,
    get_live_context,
    build_market_snapshot,
    consult_trade_plan,
    evaluate_plan_revision,
)
from backend.accounting import compute_demo_account_state, get_demo_quote_ccy, build_profitability_guard
from backend.risk import build_risk_context, evaluate_risk
from backend.runtime_settings import build_runtime_state, build_symbol_tier_map, effective_bool, get_runtime_config, watchlist_override
import requests

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

# Python 3.12+ może emitować DeprecationWarning dla utc_now_naive().
# W runtime (dev) to tylko szum w logach — wyciszamy, żeby nie wyglądało jak błąd.
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Konfiguracja loggera (uvicorn może nadpisać basicConfig — dodajemy własny handler)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rldc.collector")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [collector] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class DataCollector:
    """Kolektor danych rynkowych z Binance"""
    
    def __init__(self):
        """Inicjalizacja kolektora"""
        self.binance = get_binance_client()
        self.watchlist = self._load_watchlist()
        self.watchlist_refresh_seconds = int(os.getenv("WATCHLIST_REFRESH_SECONDS", "900"))
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
        self._load_persisted_demo_state()
        self.last_crash_alert_ts: Optional[datetime] = None
        self.last_report_ts: Optional[datetime] = None
        self.last_openai_missing_log_ts: Optional[datetime] = None
        self.last_stale_ai_log_ts: Optional[datetime] = None
        self._last_idle_alert_ts: Optional[datetime] = None
        self.learning_days = int(os.getenv("LEARNING_DAYS", "180"))
        self.last_learning_ts: Optional[datetime] = None
        self.symbol_params = {}
        self._load_persisted_symbol_params()
        self.last_snapshot_ts: Optional[datetime] = None
        self._last_binance_sync_ts: Optional[datetime] = None
        self._last_sync_warn_ts: Optional[datetime] = None
        
        logger.info(f"📊 DataCollector initialized")
        logger.info(f"   Watchlist: {', '.join(self.watchlist)}")
        logger.info(f"   Interval: {self.interval}s")
        logger.info(f"   Timeframes: {', '.join(self.kline_timeframes)}")

    def _load_persisted_symbol_params(self):
        """Wczytaj symbol_params zapisane przez _learn_from_history z poprzedniej sesji."""
        try:
            import json as _json
            from backend.database import SessionLocal as _SL, RuntimeSetting
            _db = _SL()
            try:
                row = _db.query(RuntimeSetting).filter(RuntimeSetting.key == "learning_symbol_params").first()
                if row and row.value:
                    loaded = _json.loads(row.value)
                    if isinstance(loaded, dict):
                        self.symbol_params = loaded
                        logger.info(f"📚 Wczytano symbol_params z DB ({len(loaded)} symboli)")
            finally:
                _db.close()
        except Exception as exc:
            logger.warning(f"⚠️ Nie można wczytać symbol_params z DB: {exc}")

    def _load_persisted_demo_state(self):
        """Wczytaj demo_state (loss_streak, win_streak, cooldown per symbol) z poprzedniej sesji."""
        try:
            import json as _json
            from backend.database import SessionLocal as _SL, RuntimeSetting
            _db = _SL()
            try:
                row = _db.query(RuntimeSetting).filter(RuntimeSetting.key == "demo_state_persistence").first()
                if row and row.value:
                    loaded = _json.loads(row.value)
                    if isinstance(loaded, dict):
                        self.demo_state = loaded
                        logger.info(f"📚 Wczytano demo_state z DB ({len(loaded)} symboli)")
            finally:
                _db.close()
        except Exception as exc:
            logger.warning(f"⚠️ Nie można wczytać demo_state z DB: {exc}")

    def _save_demo_state(self, db: Session) -> None:
        """Zapisz demo_state (loss_streak, win_streak, cooldown per symbol) do RuntimeSetting."""
        if not self.demo_state:
            return
        try:
            import json as _json
            from backend.runtime_settings import upsert_overrides
            upsert_overrides(db, {"demo_state_persistence": _json.dumps(self.demo_state)})
        except Exception as exc:
            log_exception("demo_state", "Błąd persistowania demo_state", exc, db=db)

    def _runtime_context(self, db: Session) -> dict[str, Any]:
        active_position_count = int(db.query(Position).count())
        state = build_runtime_state(db, collector_watchlist=self.watchlist, active_position_count=active_position_count)
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
        snapshot: Optional[dict[str, Any]] = None,
        plan: Optional[dict[str, Any]] = None,
        revision_of_trace_id: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
        order_id: Optional[int] = None,
        position_id: Optional[int] = None,
        strategy_name: Optional[str] = "default",
        level: str = "INFO",
    ) -> None:
        mode = getattr(self, '_active_mode', None) or mode or 'demo'
        payload = details or {}
        try:
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
                snapshot_json=snapshot or {},
                plan_json=plan or {},
                revision_of_trace_id=revision_of_trace_id,
                payload=payload,
            )
            db.flush()
        except Exception as _flush_exc:
            logger.error("_trace_decision flush error sym=%s reason=%s: %s", symbol, reason_code, _flush_exc)
            try:
                db.rollback()
            except Exception:
                pass
            return
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
    
    def _load_watchlist(self) -> List[str]:
        """Wczytaj listę symboli do śledzenia.

        Źródła (łączone w jedną listę):
        1. Aktywa z portfela Binance (co trzymasz → pary EUR/USDC)
        2. ENV WATCHLIST — ręcznie skonfigurowane symbole
        3. Top-N symboli po wolumenie 24h ze SPOT Binance (WATCHLIST_SCAN_TOP_N)
        """
        # Domyślnie: tylko aktywna waluta tradera (spójne z WATCHLIST_SCAN_QUOTES).
        # Można nadpisać przez PORTFOLIO_QUOTES=EUR,USDC w .env jeśli celowo chcesz obie waluty.
        _pq_env = os.getenv("PORTFOLIO_QUOTES", "").strip()
        if _pq_env:
            quotes = [q.strip().upper() for q in _pq_env.split(",") if q.strip()]
        else:
            quotes = [get_demo_quote_ccy()]  # np. ["EUR"] — nie mieszaj EUR z USDC
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

        # ── Uzupełnij o symbole z ENV WATCHLIST (konfiguracja ważniejsza niż samo saldo) ──
        raw_watchlist = os.getenv("WATCHLIST", "")
        if raw_watchlist.strip():
            items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
            for item in items:
                env_symbol = self.binance.resolve_symbol(item)
                if not env_symbol:
                    env_symbol = item.replace("/", "").strip().upper()
                if env_symbol and env_symbol not in resolved:
                    resolved.append(env_symbol)
        # ─────────────────────────────────────────────────────────────────────

        # ── Filtruj do dozwolonych par SPOT z Binance exchangeInfo ───────────
        allowed_spot: dict = {}
        if resolved:
            try:
                allowed_spot = self.binance.get_allowed_symbols(quotes=list(quotes))
                if allowed_spot:
                    filtered = [s for s in resolved if s in allowed_spot]
                    blocked = [s for s in resolved if s not in allowed_spot]
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

        # ── Dodaj top-N symboli wg wolumenu 24h (skaner okazji poza portfelem) ──
        # Filtruj quotes do tych, na których bot faktycznie handluje (z ENV lub domyślnie EUR)
        _trade_quote = get_demo_quote_ccy()  # EUR lub USDC — aktywna waluta portfela (import na górze modułu)
        _scan_quotes_env = os.getenv("WATCHLIST_SCAN_QUOTES", "")
        if _scan_quotes_env.strip():
            _scan_quotes = [q.strip().upper() for q in _scan_quotes_env.split(",") if q.strip()]
        else:
            # Domyślnie: tylko aktywna waluta tradera (nie mieszaj EUR z USDC)
            _scan_quotes = [_trade_quote]
        scan_top_n = int(os.getenv("WATCHLIST_SCAN_TOP_N", "30"))
        if scan_top_n > 0:
            try:
                top_symbols = self.binance.get_top_symbols_by_volume(
                    quotes=_scan_quotes,
                    top_n=scan_top_n,
                )
                added = 0
                for sym in top_symbols:
                    if sym not in resolved:
                        resolved.append(sym)
                        added += 1
                if added > 0:
                    logger.info(f"📈 Dodano {added} symboli z top-{scan_top_n} wolumen skanera do watchlisty")
            except Exception as exc:
                logger.warning(f"⚠️ Błąd skanowania top symboli: {exc}")
        # ─────────────────────────────────────────────────────────────────────

        if resolved:
            return sorted(resolved)

        # Ostatni fallback: tylko ENV WATCHLIST parsowany statycznie.
        if raw_watchlist.strip():
            items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
            fallback: List[str] = []
            for item in items:
                resolved_symbol = item.replace("/", "").strip().upper()
                if resolved_symbol and resolved_symbol not in fallback:
                    fallback.append(resolved_symbol)
            return sorted(fallback)

        return []

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

    def _log_openai_missing(self):
        now = utc_now_naive()
        if self.last_openai_missing_log_ts and (now - self.last_openai_missing_log_ts).total_seconds() < 300:
            return
        self.last_openai_missing_log_ts = now
        msg = "Brak klucza AI (Gemini/Groq/OpenAI) — używam heurystyki ATR/Bollinger."
        logger.warning(f"⚠️ {msg}")
        log_to_db("WARNING", "collector", msg)

    def _log_no_watchlist(self, db: Session, hint: Optional[str] = None):
        now = utc_now_naive()
        if self.last_no_watchlist_log_ts and (now - self.last_no_watchlist_log_ts).total_seconds() < 300:
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
            if (now - self.last_watchlist_refresh_ts).total_seconds() < float(self.watchlist_refresh_seconds):
                return False

        self.last_watchlist_refresh_ts = now
        try:
            new_list = self._load_watchlist()
        except Exception as exc:
            log_exception("collector", "Błąd odświeżania watchlisty", exc, db=db)
            return False

        if not new_list:
            # Jeśli mieliśmy watchlistę wcześniej, nie zeruj jej przez chwilową awarię.
            if self.watchlist:
                self._log_no_watchlist(db, hint="Zostawiam poprzednią watchlistę (tymczasowy problem z odczytem sald).")
            else:
                # Diagnostyka: brak kluczy lub brak sald
                if not getattr(self.binance, "api_key", "") or not getattr(self.binance, "api_secret", ""):
                    self._log_no_watchlist(db, hint="Sprawdź BINANCE_API_KEY/BINANCE_API_SECRET i uprawnienia read-only.")
                else:
                    self._log_no_watchlist(db)
            return False

        if new_list != self.watchlist:
            old = ", ".join(self.watchlist) if self.watchlist else "(pusto)"
            new = ", ".join(new_list)
            logger.info(f"🔁 Watchlista z portfela: {old} -> {new}")
            log_to_db("INFO", "collector", f"Watchlist updated: {old} -> {new}", db=db)
            self.watchlist = new_list
            # Restart WS, aby odświeżyć streamy
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
        # Wyczyść persystencję demo_state w DB
        try:
            from backend.database import SessionLocal as _SL, RuntimeSetting
            _db = _SL()
            try:
                row = _db.query(RuntimeSetting).filter(RuntimeSetting.key == "demo_state_persistence").first()
                if row:
                    _db.delete(row)
                    _db.commit()
            finally:
                _db.close()
        except Exception:
            pass

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
        exit_reason_code: Optional[str] = None,
        order_type: str = "MARKET",
        decision_plan: Optional[dict[str, Any]] = None,
    ) -> int:
        mode = getattr(self, '_active_mode', None) or mode or 'demo'
        # Auto-potwierdź w obu trybach (live_auto_confirm=true domyślnie)
        auto_confirm = True
        pending = PendingOrder(
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=qty,
            mode=mode,
            status="CONFIRMED" if auto_confirm else "PENDING",
            reason=reason,
            config_snapshot_id=config_snapshot_id,
            strategy_name=strategy_name,
            exit_reason_code=exit_reason_code,
            decision_plan_json=json.dumps(decision_plan, ensure_ascii=True, sort_keys=True) if decision_plan else None,
            plan_status=(decision_plan or {}).get("plan_status", "pending") if decision_plan else "pending",
            requires_revision=bool((decision_plan or {}).get("requires_revision", False)) if decision_plan else False,
            invalidation_reason=(decision_plan or {}).get("invalidation_reason") if decision_plan else None,
            last_consulted_at=utc_now_naive() if decision_plan else None,
            created_at=utc_now_naive(),
            confirmed_at=utc_now_naive() if auto_confirm else None,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        return pending.id

    def _send_telegram_alert(self, title: str, message: str, force_send: bool = False):
        risk_alerts = os.getenv("TELEGRAM_RISK_ALERTS", "false").lower() == "true"
        error_only = os.getenv("TELEGRAM_ERROR_ONLY", "false").lower() == "true"
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        if not force_send and not risk_alerts and title in {"Limit strat", "Drawdown"}:
            return
        if not force_send and error_only and title not in {"Błąd", "Error", "Critical", "Limit strat", "Drawdown"}:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": f"⚠️ {title}\n{message}"}, timeout=5)
        except Exception as exc:
            log_exception("collector", "Błąd wysyłki alertu Telegram", exc)

    def _load_plan_json(self, raw: Any) -> Optional[dict[str, Any]]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _build_symbol_plan(
        self,
        db: Session,
        symbol: str,
        *,
        mode: str,
        position: Optional[Position] = None,
        force_reconsult: bool = False,
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        snapshot = build_market_snapshot(db, symbol, mode=mode, position=position)
        if not snapshot:
            return None, None, None
        plan = consult_trade_plan(snapshot, force=force_reconsult)
        revision = evaluate_plan_revision(snapshot, plan)
        if revision.get("requires_revision"):
            plan = dict(plan)
            plan["requires_revision"] = True
            plan["invalidation_reason"] = revision.get("invalidation_reason")
            if force_reconsult:
                reconsulted = consult_trade_plan(snapshot, force=True)
                reconsulted["requires_revision"] = False
                reconsulted["invalidation_reason"] = None
                plan = reconsulted
                revision = evaluate_plan_revision(snapshot, plan)
        return snapshot, plan, revision

    def _exit_allowed_by_plan(
        self,
        *,
        snapshot: Optional[dict[str, Any]],
        plan: Optional[dict[str, Any]],
        reason_code: str,
        current_price: float,
        position: Position,
    ) -> dict[str, Any]:
        if not snapshot or not plan:
            return {"allowed": True, "why": "Brak planu — fallback legacy"}

        hard_exit_reason_codes = {"stop_loss_hit"}
        if reason_code in hard_exit_reason_codes:
            return {"allowed": True, "why": "Hard exit"}

        action = str(plan.get("action") or "HOLD").upper()
        expected_net = float(plan.get("expected_net_profit") or 0.0)
        min_profit_price = float(plan.get("minimal_profit_to_allow_exit") or 0.0)
        break_even_price = float(plan.get("break_even_price") or 0.0)
        revision = evaluate_plan_revision(snapshot, plan)
        if revision.get("requires_revision"):
            return {
                "allowed": True,
                "why": "Plan wymaga rewizji — dozwolone wyjście po re-konsultacji",
                "revision": revision,
            }
        if action in {"SELL", "REDUCE"}:
            return {"allowed": True, "why": f"Plan action={action}"}
        if expected_net <= 0:
            return {"allowed": False, "why": "Expected net profit <= 0 bez rewizji planu"}
        if min_profit_price > 0 and current_price < min_profit_price and reason_code not in {"trailing_lock_profit", "tp_full_reversal"}:
            return {"allowed": False, "why": "Cena poniżej minimalnego sensownego zysku netto"}
        if break_even_price > 0 and current_price < break_even_price and reason_code not in {"trailing_lock_profit"}:
            return {"allowed": False, "why": "Cena poniżej break-even planu"}
        if float(position.unrealized_pnl or 0.0) < 0 and reason_code not in {"stop_loss_hit"}:
            return {"allowed": False, "why": "Sprzedaż stratna bez twardego powodu"}
        return {"allowed": True, "why": "Plan pozwala na ochronę zysku"}

    def _get_limit_order_timeout_seconds(self, config: dict[str, Any]) -> int:
        """Timeout dla LIVE LIMIT BUY zanim system uruchomi fallback do MARKET."""
        raw = config.get("limit_order_timeout", os.getenv("LIMIT_ORDER_TIMEOUT", "300"))
        try:
            return max(60, int(float(raw or 300)))
        except Exception:
            return 300

    def _monitor_limit_orders(self, db: Session, runtime_ctx: Optional[dict[str, Any]] = None) -> int:
        """Monitoruj otwarte LIMIT BUY na Binance i wykonuj fallback po timeout."""
        runtime_ctx = runtime_ctx or self._runtime_context(db)
        config = runtime_ctx["config"]
        timeout_seconds = self._get_limit_order_timeout_seconds(config)
        now = utc_now_naive()
        handled = 0

        pending_orders = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "live",
                PendingOrder.side == "BUY",
                PendingOrder.order_type == "LIMIT",
                PendingOrder.status == "OPEN",
                PendingOrder.exchange_order_id.isnot(None),
            )
            .order_by(PendingOrder.created_at.asc())
            .all()
        )
        if not pending_orders:
            return 0

        open_orders_resp = self.binance.get_open_orders()
        if isinstance(open_orders_resp, dict) and open_orders_resp.get("_error"):
            err_msg = open_orders_resp.get("error_message", "openOrders error")
            log_to_db("ERROR", "live_limit_monitor", f"Binance get_open_orders błąd: {err_msg}", db=db)
            return 0
        open_orders = open_orders_resp or []
        open_ids = {str(o.get("orderId")) for o in open_orders if o.get("orderId") is not None}

        def _persist_live_limit_fill(pending: PendingOrder, fill_qty: float, fill_price: float, note: str) -> Optional[Order]:
            if fill_qty <= 0:
                return None
            order = Order(
                symbol=pending.symbol,
                side="BUY",
                order_type="LIMIT",
                price=pending.price,
                quantity=float(pending.quantity or fill_qty),
                status="FILLED",
                mode="live",
                executed_price=fill_price if fill_price > 0 else float(pending.price or 0),
                executed_quantity=fill_qty,
                config_snapshot_id=pending.config_snapshot_id or runtime_ctx.get("snapshot_id"),
                entry_reason_code="limit_order_filled",
                exchange_order_id=str(pending.exchange_order_id or ""),
                notes=note,
                created_at=pending.created_at or now,
                filled_at=now,
                decision_plan_json=pending.decision_plan_json,
                timestamp=now,
            )
            db.add(order)

            position = db.query(Position).filter(
                Position.symbol == pending.symbol,
                Position.mode == "live",
            ).first()
            if position:
                old_qty = float(position.quantity or 0.0)
                total_qty = old_qty + fill_qty
                if total_qty > 0:
                    position.entry_price = (
                        (float(position.entry_price or 0.0) * old_qty) +
                        (float(order.executed_price or 0.0) * fill_qty)
                    ) / total_qty
                position.quantity = total_qty
                position.current_price = float(order.executed_price or position.current_price or 0.0)
                position.config_snapshot_id = order.config_snapshot_id or position.config_snapshot_id
            else:
                db.add(Position(
                    symbol=pending.symbol,
                    side="LONG",
                    entry_price=float(order.executed_price or pending.price or 0.0),
                    quantity=fill_qty,
                    current_price=float(order.executed_price or pending.price or 0.0),
                    unrealized_pnl=0.0,
                    gross_pnl=0.0,
                    net_pnl=0.0,
                    total_cost=0.0,
                    fee_cost=0.0,
                    slippage_cost=0.0,
                    spread_cost=0.0,
                    config_snapshot_id=order.config_snapshot_id,
                    entry_reason_code="limit_order_filled",
                    mode="live",
                    opened_at=now,
                    decision_plan_json=pending.decision_plan_json,
                    plan_status=pending.plan_status or "active",
                    requires_revision=bool(pending.requires_revision),
                    invalidation_reason=pending.invalidation_reason,
                    last_consulted_at=pending.last_consulted_at,
                ))
            return order

        for pending in pending_orders:
            pending.last_checked_at = now
            exchange_order_id = str(pending.exchange_order_id or "").strip()
            if not exchange_order_id:
                pending.status = "REJECTED"
                log_to_db("ERROR", "live_limit_monitor",
                          f"Pending LIMIT bez exchange_order_id dla {pending.symbol} id={pending.id}",
                          db=db)
                handled += 1
                continue

            order_resp = self.binance.get_order(pending.symbol, int(exchange_order_id))
            if isinstance(order_resp, dict) and order_resp.get("_error"):
                err_msg = order_resp.get("error_message", "get_order error")
                log_to_db("ERROR", "live_limit_monitor",
                          f"Binance get_order błąd dla {pending.symbol} #{exchange_order_id}: {err_msg}",
                          db=db)
                continue
            if not order_resp:
                continue

            status = str(order_resp.get("status") or "").upper()
            executed_qty = float(order_resp.get("executedQty", 0) or 0)
            orig_qty = float(order_resp.get("origQty", pending.quantity) or pending.quantity or 0)
            quote_qty = float(order_resp.get("cummulativeQuoteQty", 0) or 0)
            avg_price = (quote_qty / executed_qty) if executed_qty > 0 and quote_qty > 0 else float(order_resp.get("price", pending.price) or pending.price or 0)

            if status == "FILLED":
                _persist_live_limit_fill(
                    pending,
                    executed_qty if executed_qty > 0 else float(pending.quantity or 0),
                    avg_price if avg_price > 0 else float(pending.price or 0),
                    f"Filled by monitor from pending #{pending.id}",
                )
                pending.status = "EXECUTED"
                if not pending.confirmed_at:
                    pending.confirmed_at = now
                log_to_db("INFO", "live_limit_monitor",
                          f"LIMIT BUY filled: {pending.symbol} qty={executed_qty:.8g} avg={avg_price:.8g} pending_id={pending.id}",
                          db=db)
                handled += 1
                continue

            if status in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED"}:
                pending.status = "REJECTED"
                log_to_db("WARNING", "live_limit_monitor",
                          f"LIMIT BUY zakończony bez fill: {pending.symbol} status={status} pending_id={pending.id}",
                          db=db)
                handled += 1
                continue

            expires_at = pending.expires_at or (pending.created_at + timedelta(seconds=timeout_seconds) if pending.created_at else now)
            pending.expires_at = expires_at
            is_still_open = exchange_order_id in open_ids or status in {"NEW", "PARTIALLY_FILLED"}
            if is_still_open and now < expires_at:
                continue

            cancel_resp = self.binance.cancel_order(pending.symbol, int(exchange_order_id))
            if isinstance(cancel_resp, dict) and cancel_resp.get("_error"):
                err_msg = cancel_resp.get("error_message", "cancel_order error")
                log_to_db("ERROR", "live_limit_monitor",
                          f"Cancel LIMIT BUY failed {pending.symbol} #{exchange_order_id}: {err_msg}",
                          db=db)
                continue

            remaining_qty = max(0.0, orig_qty - executed_qty)
            if executed_qty > 0:
                _persist_live_limit_fill(
                    pending,
                    executed_qty,
                    avg_price if avg_price > 0 else float(pending.price or 0),
                    f"Partial fill before MARKET fallback from pending #{pending.id}",
                )
            if remaining_qty <= 0:
                pending.status = "EXECUTED"
                pending.expires_at = None
                log_to_db("INFO", "live_limit_monitor",
                          f"LIMIT BUY {pending.symbol} domknięty częściowym fillem bez reszty do fallbacku (pending_id={pending.id})",
                          db=db)
                handled += 1
                continue

            pending.status = "CONFIRMED"
            pending.order_type = "MARKET"
            pending.exchange_order_id = None
            pending.expires_at = None
            pending.price = None
            pending.quantity = remaining_qty
            pending.reason = (
                f"{pending.reason or 'LIMIT BUY timeout'}. LIMIT timeout {timeout_seconds}s -> MARKET fallback."
            )[:2000]
            log_to_db("WARNING", "live_limit_monitor",
                      f"LIMIT BUY timeout {pending.symbol} #{exchange_order_id} -> MARKET fallback (pending_id={pending.id})",
                      db=db)
            handled += 1

        return handled

    def _execute_confirmed_pending_orders(self, db: Session):
        """
        Wykonaj potwierdzone transakcje (DEMO + LIVE) zapisane jako PendingOrder.
        DEMO: symulacja ceny rynkowej.
        LIVE: zlecenie na Binance API (place_order).
        """
        runtime_ctx = self._runtime_context(db)
        config = runtime_ctx["config"]

        confirmed = (
            db.query(PendingOrder)
            .filter(PendingOrder.status == "CONFIRMED")
            .order_by(desc(PendingOrder.confirmed_at))
            .limit(50)
            .all()
        )
        if not confirmed:
            return

        # Pobierz aktualne salda Binance raz przed pętlą — potrzebne do cap SELL qty
        # (DB qty może nieznacznie przekraczać Binance free po zaokrągleniach)
        live_balances_free: dict = {}
        if any(p.mode == "live" and p.side == "SELL" for p in confirmed):
            try:
                _bal = self.binance.get_balances() or []
                for b in _bal:
                    live_balances_free[(b.get("asset") or "").upper()] = float(b.get("free", 0))
            except Exception as _be:
                logger.error("Błąd pobierania sald Binance dla SELL qty cap: %s", _be)

        executed_count = 0
        for pending in confirmed:
            p_mode = pending.mode or "demo"
            try:
                qty = float(pending.quantity)
                pending_plan = self._load_plan_json(getattr(pending, "decision_plan_json", None))

                if p_mode == "live":
                    # ——— LIVE: wykonaj przez Binance API ———
                    # Normalizuj qty do step_size symbolu (wymóg LOT_SIZE Binance)
                    normalized_qty = self.binance.normalize_quantity(pending.symbol, qty)

                    # BUG-17: Dla SELL obetnij qty do faktycznego salda Binance
                    # (DB qty może być wyższe przez zaokrąglenia przy BUY lub imporcie)
                    if pending.side == "SELL" and live_balances_free:
                        sym_upper = (pending.symbol or "").upper()
                        if sym_upper.endswith("USDC"):
                            _asset = sym_upper[:-4]
                        elif sym_upper.endswith("EUR"):
                            _asset = sym_upper[:-3]
                        else:
                            _asset = sym_upper
                        _free = live_balances_free.get(_asset, 0.0)
                        if _free > 0 and normalized_qty > _free:
                            _capped = self.binance.normalize_quantity(pending.symbol, _free)
                            logger.warning(
                                "SELL %s: qty=%s → %s (cap do Binance free=%s)",
                                pending.symbol, normalized_qty, _capped, _free
                            )
                            normalized_qty = _capped

                    if normalized_qty <= 0:
                        log_to_db("ERROR", "live_trading",
                                  f"Qty po normalizacji LOT_SIZE = 0 dla {pending.symbol} {pending.side} qty_orig={qty}",
                                  db=db)
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        # Zamknij dust pozycję LIVE — ustaw qty=0 aby uniknąć pętli exit
                        if pending.side == "SELL":
                            dust_pos = db.query(Position).filter(
                                Position.symbol == pending.symbol,
                                Position.mode == "live",
                                Position.quantity > 0,
                            ).first()
                            if dust_pos:
                                dust_pos.quantity = 0.0
                                dust_pos.exit_reason_code = "dust_quantity"
                                log_to_db("INFO", "live_trading",
                                          f"Dust pozycja {pending.symbol} zamknięta (qty={qty:.2e} < min LOT_SIZE)",
                                          db=db)
                        continue
                    qty = normalized_qty
                    # Użyj order_type z PendingOrder (MARKET lub LIMIT wg config)
                    exec_order_type = pending.order_type or "MARKET"
                    exec_price = pending.price if exec_order_type == "LIMIT" else None
                    result = self.binance.place_order(
                        symbol=pending.symbol,
                        side=pending.side,
                        order_type=exec_order_type,
                        quantity=qty,
                        price=exec_price,
                    )
                    if not result or result.get("_error"):
                        err_msg = (result or {}).get("error_message", "brak odpowiedzi") if result else "brak odpowiedzi"
                        log_to_db("ERROR", "live_trading",
                                  f"Binance place_order błąd dla {pending.symbol} {pending.side} qty={qty}: {err_msg}",
                                  db=db)
                        logger.error(f"❌ LIVE ORDER FAILED: {pending.side} {pending.symbol} qty={qty}: {err_msg}")
                        pending.status = "REJECTED"
                        pending.confirmed_at = utc_now_naive()
                        # Zapisz Order z ERROR + error_reason dla diagnostyki
                        error_order = Order(
                            symbol=pending.symbol,
                            side=pending.side,
                            order_type=pending.order_type or "MARKET",
                            price=pending.price,
                            quantity=qty,
                            status="ERROR",
                            mode="live",
                            config_snapshot_id=pending.config_snapshot_id,
                            exit_reason_code=pending.exit_reason_code,
                            error_reason=err_msg[:500],
                            timestamp=utc_now_naive(),
                        )
                        db.add(error_order)
                        continue
                    binance_status = str(result.get("status", "FILLED")).upper()
                    if pending.side == "BUY" and exec_order_type == "LIMIT" and binance_status in {"NEW", "PARTIALLY_FILLED"}:
                        pending.status = "OPEN"
                        pending.exchange_order_id = str(result.get("orderId") or "")
                        pending.expires_at = utc_now_naive() + timedelta(
                            seconds=self._get_limit_order_timeout_seconds(config)
                        )
                        pending.last_checked_at = utc_now_naive()
                        log_to_db(
                            "INFO",
                            "live_trading",
                            f"LIVE LIMIT BUY open: {pending.symbol} qty={qty:.8g} @ {pending.price or exec_price} "
                            f"status={binance_status} order_id={pending.exchange_order_id}",
                            db=db,
                        )
                        logger.info(
                            "⏳ LIVE LIMIT BUY OPEN: %s qty=%s price=%s status=%s orderId=%s",
                            pending.symbol,
                            qty,
                            pending.price,
                            binance_status,
                            pending.exchange_order_id,
                        )
                        executed_count += 1
                        continue
                    # Parsuj odpowiedź Binance
                    fills = result.get("fills", [])
                    if fills:
                        total_qty_filled = sum(float(f.get("qty", 0)) for f in fills)
                        total_cost_filled = sum(float(f.get("price", 0)) * float(f.get("qty", 0)) for f in fills)
                        exec_price = total_cost_filled / total_qty_filled if total_qty_filled > 0 else float(pending.price)
                        qty = total_qty_filled if total_qty_filled > 0 else qty
                    else:
                        exec_price = float(result.get("price", 0)) or float(pending.price)
                    # Prowizja rzeczywista z fills Binance
                    _live_actual_fee = sum(float(f.get("commission", 0)) for f in fills)
                    _live_fee_asset = fills[0].get("commissionAsset", "") if fills else ""
                    logger.info(f"✅ LIVE ORDER EXECUTED: {pending.side} {pending.symbol} qty={qty} @ {exec_price} fee={_live_actual_fee} {_live_fee_asset} status={binance_status}")
                    log_to_db("INFO", "live_trading",
                              f"LIVE {pending.side} {pending.symbol} qty={qty:.8g} @ {exec_price:.6f} fee={_live_actual_fee:.8g} {_live_fee_asset}",
                              db=db)
                else:
                    _live_actual_fee = 0.0
                    _live_fee_asset = ""
                    # ——— DEMO: symulacja po aktualnej cenie rynkowej ———
                    exec_price = pending.price
                    ticker = self.binance.get_ticker_price(pending.symbol)
                    if ticker and ticker.get("price"):
                        _ticker_price = float(ticker["price"])
                        # BUG-19: sanity check — ticker nie może różnić się od pending.price
                        # o więcej niż 50× (ochrona przed złym ticker dla tokenów mikro-cena).
                        # Błędny ticker (np. 0.95 EUR dla PEPE zamiast 2.88e-6) → notional×330k
                        # → fee i kill_switch fałszywie triggered.
                        _pending_p = float(pending.price)
                        if _pending_p > 0 and (_ticker_price / _pending_p > 50 or _pending_p / _ticker_price > 50):
                            logger.warning(
                                "BUG-19: ticker price sanity FAIL sym=%s ticker=%.8g pending=%.8g ratio=%.1f — using pending.price",
                                pending.symbol, _ticker_price, _pending_p, _ticker_price / _pending_p,
                            )
                        else:
                            exec_price = _ticker_price

                order = Order(
                    symbol=pending.symbol,
                    side=pending.side,
                    order_type=pending.order_type,
                    price=pending.price,
                    quantity=qty,
                    status="FILLED",
                    mode=p_mode,
                    executed_price=exec_price,
                    executed_quantity=qty,
                    config_snapshot_id=pending.config_snapshot_id or runtime_ctx.get("snapshot_id"),
                    entry_reason_code="pending_confirmed_execution" if pending.side == "BUY" else None,
                    exit_reason_code=(pending.exit_reason_code or "pending_confirmed_execution") if pending.side == "SELL" else None,
                    exchange_order_id=str(result.get("orderId")) if p_mode == "live" and result else None,
                    notes=pending.reason,
                    created_at=utc_now_naive(),
                    filled_at=utc_now_naive(),
                    decision_plan_json=json.dumps(pending_plan, ensure_ascii=True, sort_keys=True) if pending_plan else None,
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
                # BUG FIX: _live_actual_fee może być w walucie bazowej (PEPE, RENDER itp.)
                # a nie w EUR/USDC — nie używamy jej bezpośrednio jako wartości EUR.
                # Konwertujemy: jeśli commissionAsset == quote (EUR/USDC/USDT) → wprost.
                # Jeśli token bazowy → fee_in_base * exec_price. Sanity cap = 1% notional.
                _quote_upper = get_demo_quote_ccy().upper()
                _fee_asset_upper = (_live_fee_asset or "").upper()
                if p_mode == "live" and _live_actual_fee > 0:
                    if _fee_asset_upper in (_quote_upper, "USDT", "USDC", "EUR"):
                        # Prowizja bezpośrednio w walucie kwotowania — OK
                        fee_cost = min(_live_actual_fee, notional * 0.05)
                    else:
                        # Prowizja w tokenie bazowym (lub BNB) — przelicz przez cenę egzekucji
                        fee_cost = min(_live_actual_fee * float(exec_price), notional * 0.05)
                    fee_notes = f"LIVE Binance commission ({_live_fee_asset}, converted to {_quote_upper})"
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
                    .filter(Position.symbol == pending.symbol, Position.mode == p_mode)
                    .first()
                )

                if pending.side == "BUY":
                    # Wylicz TP/SL z ATR na potrzeby exit quality tracking
                    _planned_tp = None
                    _planned_sl = None
                    try:
                        _ctx = get_live_context(db, pending.symbol, timeframe="1h", limit=120)
                        if _ctx and _ctx.get("atr") and float(_ctx["atr"]) > 0:
                            _atr = float(_ctx["atr"])
                            _atr_take = float(config.get("atr_take_mult", 3.5))
                            _atr_stop = float(config.get("atr_stop_mult", 2.0))
                            _planned_tp = exec_price + _atr * _atr_take
                            _planned_sl = exec_price - _atr * _atr_stop
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
                            decision_plan_json=json.dumps(pending_plan, ensure_ascii=True, sort_keys=True) if pending_plan else None,
                            plan_status=(pending_plan or {}).get("plan_status", "active") if pending_plan else "active",
                            requires_revision=bool((pending_plan or {}).get("requires_revision", False)) if pending_plan else False,
                            invalidation_reason=(pending_plan or {}).get("invalidation_reason") if pending_plan else None,
                            last_consulted_at=utc_now_naive() if pending_plan else None,
                        )
                        db.add(position)
                    else:
                        total_qty = float(position.quantity) + qty
                        if total_qty > 0:
                            position.entry_price = (
                                (float(position.entry_price) * float(position.quantity)) + (exec_price * qty)
                            ) / total_qty
                        position.quantity = total_qty
                        position.current_price = exec_price
                        position.total_cost = float(position.total_cost or 0.0) + fee_cost + slippage_cost + spread_cost
                        position.fee_cost = float(position.fee_cost or 0.0) + fee_cost
                        position.slippage_cost = float(position.slippage_cost or 0.0) + slippage_cost
                        position.spread_cost = float(position.spread_cost or 0.0) + spread_cost
                        position.net_pnl = float(position.net_pnl or 0.0) - (fee_cost + slippage_cost + spread_cost)
                        position.config_snapshot_id = order.config_snapshot_id or position.config_snapshot_id
                        if pending_plan:
                            position.decision_plan_json = json.dumps(pending_plan, ensure_ascii=True, sort_keys=True)
                            position.plan_status = pending_plan.get("plan_status", "active")
                            position.requires_revision = bool(pending_plan.get("requires_revision", False))
                            position.invalidation_reason = pending_plan.get("invalidation_reason")
                            position.last_consulted_at = utc_now_naive()
                elif pending.side == "SELL":
                    gross_pnl = 0.0
                    if position and float(position.quantity) > 0:
                        sell_qty = min(float(position.quantity), qty)
                        gross_pnl = (exec_price - float(position.entry_price)) * sell_qty
                        position.quantity = float(position.quantity) - sell_qty
                        position.current_price = exec_price
                        position.unrealized_pnl = (exec_price - float(position.entry_price)) * float(position.quantity)
                        position.gross_pnl = float(position.gross_pnl or 0.0) + gross_pnl
                        position.total_cost = float(position.total_cost or 0.0) + fee_cost + slippage_cost + spread_cost
                        position.fee_cost = float(position.fee_cost or 0.0) + fee_cost
                        position.slippage_cost = float(position.slippage_cost or 0.0) + slippage_cost
                        position.spread_cost = float(position.spread_cost or 0.0) + spread_cost
                        position.net_pnl = float(position.gross_pnl or 0.0) - float(position.total_cost or 0.0)
                        # Zamknij pozycję jeśli: qty=0 LUB pozostała wartość < 1 EUR (dust)
                        remaining_value = float(position.quantity) * exec_price
                        if float(position.quantity) <= 0 or remaining_value < 1.0:
                            # Pełne zamknięcie — ustaw exit_reason_code TYLKO tutaj
                            position.exit_reason_code = pending.exit_reason_code or "pending_confirmed_execution"
                            # --- Exit Quality snapshot ---
                            self._save_exit_quality(db, position, exec_price, config)
                            db.delete(position)
                            position = None
                            logger.info(f"✅ Pozycja {pending.symbol} zamknięta (dust < 1 EUR lub qty=0)")
                        else:
                            # Częściowe zamknięcie — inkrementuj licznik i aktywuj trailing
                            # exit_reason_code NIE jest ustawiany — pozycja nadal otwarta
                            position.partial_take_count = int(position.partial_take_count or 0) + 1
                            if pending_plan:
                                position.decision_plan_json = json.dumps(pending_plan, ensure_ascii=True, sort_keys=True)
                                position.plan_status = pending_plan.get("plan_status", "active")
                                position.requires_revision = bool(pending_plan.get("requires_revision", False))
                                position.invalidation_reason = pending_plan.get("invalidation_reason")
                                position.last_consulted_at = utc_now_naive()
                    else:
                        # Brak pozycji — zapisujemy zlecenie, ale bez zmian pozycji.
                        pass
                    expected_edge = float(pending.price or exec_price) * float(config.get("min_edge_multiplier", 2.5))
                    _exit_rc = pending.exit_reason_code or "pending_confirmed_execution"
                    attach_costs_to_order(
                        db,
                        order=order,
                        gross_pnl=gross_pnl,
                        expected_edge=expected_edge,
                        config_snapshot_id=order.config_snapshot_id,
                        exit_reason_code=_exit_rc,
                    )
                if pending.side == "BUY":
                    attach_costs_to_order(
                        db,
                        order=order,
                        gross_pnl=0.0,
                        expected_edge=float(pending.price or exec_price) * float(config.get("min_edge_multiplier", 2.5)),
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

                pending.status = "EXECUTED"
                if not pending.confirmed_at:
                    pending.confirmed_at = utc_now_naive()

                self._trace_decision(
                    db,
                    symbol=pending.symbol,
                    action="EXECUTE_PENDING",
                    reason_code="pending_confirmed_execution",
                    runtime_ctx=runtime_ctx,
                    mode=p_mode,
                    execution_check={"eligible": True, "pending_id": pending.id, "quantity": qty, "exec_price": exec_price},
                    plan=pending_plan,
                    details={"side": pending.side, "reason": pending.reason, "order_id": order.id},
                    order_id=order.id,
                    position_id=position.id if position else None,
                )

                executed_count += 1
            except Exception as exc:
                log_exception("demo_trading", f"Błąd wykonania pending order {pending.id}", exc, db=db)
                try:
                    pending.status = "REJECTED"
                    pending.confirmed_at = utc_now_naive()
                    self._trace_decision(
                        db,
                        symbol=pending.symbol,
                        action="REJECT_PENDING",
                        reason_code="pending_execution_error",
                        runtime_ctx=runtime_ctx,
                        mode=p_mode,
                        execution_check={"eligible": False, "pending_id": pending.id},
                        details={"error": str(exc)},
                        level="ERROR",
                    )
                except Exception:
                    pass

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_exception("demo_trading", "Błąd commit wykonania pending orders", exc, db=db)
            return

        if executed_count:
            logger.info(f"✅ Wykonano potwierdzone transakcje: {executed_count}")

    def _save_exit_quality(self, db: Session, position, exit_price: float, config: dict) -> None:
        """Zapisz ExitQuality snapshot przy zamknięciu pozycji."""
        try:
            entry = float(position.entry_price or 0)
            qty = float(position.quantity or 0) if float(position.quantity or 0) > 0 else float(getattr(position, "_orig_qty", 0) or 0)
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
                duration_seconds = (utc_now_naive() - position.opened_at).total_seconds()

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
        NIE auto-koryguje — informuje operatora.
        """
        tc = self._runtime_context(db)["config"]
        if tc.get("trading_mode", "demo") != "live":
            return
        if not tc.get("allow_live_trading"):
            return

        try:
            balances = self.binance.get_balances()
        except Exception as exc:
            log_exception("binance_sync", "Błąd pobierania saldów Binance", exc, db=db)
            return
        if not balances:
            return

        # Zbuduj mapę asset→quantity z Binance
        binance_map: dict[str, float] = {}
        eur_balance_total = 0.0
        for b in balances:
            asset = b.get("asset", "")
            total = float(b.get("total", 0))
            if asset == "EUR":
                eur_balance_total = total
            if total > 0 and asset not in ("EUR", "USDC", "USDT", "BNB"):
                binance_map[asset] = total

        # Persistuj saldo EUR do RuntimeSetting — używane przez kill switch jako baza kapitału
        if eur_balance_total > 0:
            from backend.database import RuntimeSetting
            lb_setting = db.query(RuntimeSetting).filter(RuntimeSetting.key == "live_balance_eur").first()
            if lb_setting:
                lb_setting.value = str(round(eur_balance_total, 4))
            else:
                db.add(RuntimeSetting(key="live_balance_eur", value=str(round(eur_balance_total, 4))))

        # Pobierz LIVE pozycje z DB
        db_positions = db.query(Position).filter(Position.mode == "live").all()
        db_map: dict[str, float] = {}
        for pos in db_positions:
            # Wyciągnij base asset z symbolu (np. BTCEUR → BTC, ETHUSDC → ETH)
            sym = pos.symbol or ""
            base = sym.replace("EUR", "").replace("USDC", "").replace("USDT", "")
            if base:
                db_map[base] = db_map.get(base, 0.0) + float(pos.quantity or 0)

        # Zbuduj szybki cache cen z MarketData (jeden query na asset)
        all_assets = set(list(binance_map.keys()) + list(db_map.keys()))
        _price_cache: dict[str, float] = {}
        for _asset in all_assets:
            for _quote in ("EUR", "USDC", "USDT"):
                _sym = f"{_asset}{_quote}"
                _md = db.query(MarketData).filter(MarketData.symbol == _sym).order_by(MarketData.timestamp.desc()).first()
                if _md and _md.price:
                    try:
                        _price_cache[_asset] = float(_md.price)
                        break
                    except Exception:
                        pass

        # Minimalna wartość niezgodności w EUR poniżej której ignorujemy (pył)
        _DUST_THRESHOLD_EUR = 2.0

        # Porównaj
        mismatches = []
        for asset in sorted(all_assets):
            binance_qty = binance_map.get(asset, 0.0)
            db_qty = db_map.get(asset, 0.0)
            if abs(binance_qty - db_qty) > max(1e-6, db_qty * 0.01):
                # Sprawdź wartość niezgodności — ignoruj pył poniżej progu
                # Jeśli cena nieznana (0), traktuj jako pył i też pomiń
                _price = _price_cache.get(asset, 0.0)
                if _price <= 0 or abs(binance_qty - db_qty) * _price < _DUST_THRESHOLD_EUR:
                    continue  # brak ceny lub wartość poniżej progu pyłu — pomiń
                mismatches.append(f"{asset}: Binance={binance_qty:.8g} DB={db_qty:.8g}")

        # Auto-import aktywów z Binance (które nie są w DB) jako pozycje LIVE
        imported: list[str] = []
        watchlist_upper = {s.strip().upper().replace("/", "").replace("-", "") for s in self.watchlist}
        for asset in sorted(all_assets):
            binance_qty = binance_map.get(asset, 0.0)
            db_qty = db_map.get(asset, 0.0)
            if binance_qty <= 0 or db_qty >= binance_qty * 0.99:
                continue  # brak aktywa na Binance lub już śledzony w DB
            # Znajdź symbol w watchliście (preferuj EUR, potem USDC)
            sym = None
            for quote in ["EUR", "USDC", "USDT"]:
                candidate = f"{asset}{quote}"
                if candidate in watchlist_upper:
                    sym = candidate
                    break
            if not sym:
                continue  # żaden symbol z watchlisty — pomijamy
            # Sprawdź czy jest istniejąca pozycja dla tego symbolu LIVE
            existing = db.query(Position).filter(
                Position.symbol == sym, Position.mode == "live"
            ).first()
            if existing:
                continue
            # Pobierz aktualną cenę
            try:
                ticker = self.binance.get_ticker_price(sym)
                if not ticker or not ticker.get("price"):
                    continue
                current_price = float(ticker["price"])
            except Exception:
                continue
            notional = current_price * binance_qty
            if notional < 1.0:
                continue  # dust — pomijamy
            # Utwórz Position LIVE z entry = current price
            now_ts = utc_now_naive()
            new_pos = Position(
                symbol=sym,
                side="LONG",
                entry_price=current_price,
                quantity=binance_qty,
                current_price=current_price,
                unrealized_pnl=0.0,
                mode="live",
                opened_at=now_ts,
                entry_reason_code="binance_import",
            )
            db.add(new_pos)
            imported.append(f"{sym} qty={binance_qty:.8g} @ {current_price:.6g}")
        if imported:
            try:
                db.commit()
            except Exception as exc_imp:
                db.rollback()
                log_exception("binance_sync", "Błąd importu pozycji Binance", exc_imp, db=db)
                imported = []
        if imported:
            imp_msg = "Auto-import pozycji LIVE z Binance: " + ", ".join(imported)
            log_to_db("INFO", "binance_sync", imp_msg, db=db)
            logger.info(f"✅ {imp_msg}")
            self._send_telegram_alert("SYNC: Import pozycji", imp_msg)

        # Auto-korekcja ghost positions i dust: jeśli DB qty > 0 ale Binance qty = 0 lub wartość < 1 EUR → zamknij
        now_sync = utc_now_naive()
        for pos in db_positions:
            sym = pos.symbol or ""
            base = sym.replace("EUR", "").replace("USDC", "").replace("USDT", "")
            binance_qty = binance_map.get(base, 0.0)
            db_qty = float(pos.quantity or 0.0)
            if db_qty <= 0:
                # Pozycja z qty=0 — usuń bez sprawdzania Binance (ghost)
                logger.info(f"🧹 Usuwam ghost position: {sym} qty={db_qty} (DB qty=0)")
                db.delete(pos)
                continue
            # Pobierz cenę do oceny wartości
            try:
                ticker_d = self.binance.get_ticker_price(sym)
                curr_price = float(ticker_d["price"]) if ticker_d and ticker_d.get("price") else 0.0
            except Exception:
                curr_price = 0.0
            binance_value = binance_qty * (curr_price or float(pos.entry_price or 0))
            db_value = db_qty * (curr_price or float(pos.entry_price or 0))
            # Jeśli Binance value < 1 EUR I DB value < 2 EUR → dust, zamknij
            if binance_value < 1.0 and db_value < 2.0:
                logger.info(f"🧹 Dust position zamknięta przez sync: {sym} Binance={binance_qty:.8g} value={binance_value:.4f}EUR")
                log_to_db("INFO", "binance_sync", f"Auto-zamknięcie dust: {sym} Binance={binance_qty:.8g} EUR<1", db=db)
                db.delete(pos)
                continue
            # Jeśli rozbieżność qty > 10% I DB > Binance → dostosuj qty do Binance
            if binance_qty > 0 and db_qty > binance_qty * 1.05:
                old_qty = db_qty
                pos.quantity = binance_qty
                if curr_price > 0:
                    pos.unrealized_pnl = (curr_price - float(pos.entry_price or curr_price)) * binance_qty
                logger.info(f"🔧 Korekcja qty: {sym} DB {old_qty:.8g}→{binance_qty:.8g} (Binance)")
                log_to_db("INFO", "binance_sync", f"Korekta qty {sym}: {old_qty:.8g}→{binance_qty:.8g}", db=db)
        try:
            db.commit()
        except Exception as exc_sync:
            db.rollback()
            log_exception("binance_sync", "Błąd auto-korekty pozycji", exc_sync, db=db)

        if mismatches:
            # Ogranicz spam logu — alert tylko raz na 30 minut jeśli brak importu
            now_warn = utc_now_naive()
            if not hasattr(self, "_last_sync_warn_ts") or self._last_sync_warn_ts is None or \
                    (now_warn - self._last_sync_warn_ts).total_seconds() > 1800:
                self._last_sync_warn_ts = now_warn
                msg = "Niezgodność pozycji DB↔Binance: " + " | ".join(mismatches[:10])
                log_to_db("WARNING", "binance_sync", msg, db=db)
                logger.warning(f"⚠️ {msg}")
                self._send_telegram_alert("SYNC: Niezgodność", msg)

    def _mark_to_market_positions(self, db: Session, mode: str = "demo") -> None:
        """
        Aktualizuj `current_price` i `unrealized_pnl` dla otwartych pozycji na bazie ostatnich MarketData.
        """
        try:
            positions = db.query(Position).filter(Position.mode == mode).all()
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
                log_to_db("WARNING", "live_trading",
                          "kill_switch_enabled=false — LIVE trading wyłączony", db=db)
                return
        else:
            return

        now = utc_now_naive()
        tc = self._load_trading_config(db, config, runtime_ctx, now, mode=mode)
        if tc is None:
            return

        # 0) Sprawdź enabled_strategies — kill switch
        enabled_strats = tc.get("enabled_strategies", ["default"])
        if not enabled_strats or "default" not in enabled_strats:
            log_to_db("WARNING", "demo_trading",
                      f"Strategia 'default' wyłączona w enabled_strategies={enabled_strats} — pomijam cykl demo.",
                      db=db)
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

        # 2b) Telegram idle alert — co 30 min gdy brak nowych wejść
        if entries == 0:
            idle_interval = 1800  # 30 min
            if not self._last_idle_alert_ts or (now - self._last_idle_alert_ts).total_seconds() > idle_interval:
                self._last_idle_alert_ts = now
                aggressiveness = tc.get("aggressiveness", "balanced")
                pos_count = len(tc.get("positions", []))
                max_pos = tc.get("max_open_positions", 5)
                # Zbierz powody blokad z ostatnich decyzji
                recent_skips = (
                    db.query(DecisionTrace.symbol, DecisionTrace.reason_code)
                    .filter(DecisionTrace.mode == mode, DecisionTrace.action_type == "skip")
                    .order_by(DecisionTrace.timestamp.desc())
                    .limit(20)
                    .all()
                )
                skip_summary = {}
                for sym, reason in recent_skips:
                    if reason not in skip_summary:
                        skip_summary[reason] = []
                    if sym not in skip_summary[reason]:
                        skip_summary[reason].append(sym)
                skip_lines = "\n".join(
                    f"  • {reason}: {', '.join(syms[:3])}"
                    for reason, syms in list(skip_summary.items())[:5]
                )
                msg = (
                    f"⏸️ [{mode.upper()}] Bot bezczynny — brak nowych wejść\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Tryb: {aggressiveness.upper()}\n"
                    f"Pozycje: {pos_count}/{max_pos}\n"
                    f"Watchlist: {len(self.watchlist)} symboli\n"
                    f"\nPowody pominięcia:\n{skip_lines}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Bot nadal działa i monitoruje rynek."
                )
                self._send_telegram_alert(f"{mode.upper()}: IDLE", msg)

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

    def _load_trading_config(self, db: Session, config: dict, runtime_ctx: dict, now, mode: str = "demo") -> dict | None:
        """Zwraca spłaszczony dict z parametrami do tradingu, lub None jeśli brak danych."""
        demo_quote_ccy = get_demo_quote_ccy()

        if mode == "live":
            # LIVE: kapitał z Binance API
            balances = self.binance.get_balances() or []
            cash = 0.0
            for b in balances:
                if (b.get("asset") or "").upper() == demo_quote_ccy.replace("EUR", "EUR").replace("USDC", "USDC"):
                    # asset = "EUR" or "USDC"
                    cash = float(b.get("free", 0) or 0)
                    break
            # Wartość otwartych pozycji live z DB
            live_positions_db = db.query(Position).filter(Position.mode == "live").all()
            positions_value = 0.0
            for p in live_positions_db:
                try:
                    positions_value += float(p.current_price or p.entry_price or 0) * float(p.quantity or 0)
                except Exception:
                    pass
            equity = cash + positions_value
            initial_balance = max(equity, 1.0)  # unikamy dzielenia przez 0
            account_state = {
                "initial_balance": initial_balance,
                "cash": cash,
                "equity": equity,
                "unrealized_pnl": sum(float(p.unrealized_pnl or 0) for p in live_positions_db),
                "realized_pnl_24h": 0.0,
            }
        else:
            account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy, now=now)
            initial_balance = float(account_state.get("initial_balance") or float(os.getenv("DEMO_INITIAL_BALANCE", "10000")))
            cash = float(account_state.get("cash") or initial_balance)
            equity = float(account_state.get("equity") or cash)
        reserved_cash = 0.0
        try:
            active_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.side == "BUY",
                    PendingOrder.status.in_(["PENDING", "CONFIRMED", "OPEN"]),
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
        aggr_profile = AGGRESSIVENESS_PROFILES.get(aggressiveness, AGGRESSIVENESS_PROFILES["balanced"])

        # Runtime-controlled settings (profil agresywności dostarcza domyślne wartości)
        max_daily_loss_pct = float(config.get("max_daily_drawdown", 0.03)) * 100.0
        max_drawdown_pct = float(config.get("max_weekly_drawdown", 0.07)) * 100.0
        base_risk_per_trade = float(config.get("risk_per_trade", aggr_profile["risk_per_trade"]))
        max_trades_per_day = int(config.get("max_trades_per_day", 20))
        max_open_positions = int(config.get("max_open_positions", aggr_profile["max_open_positions"]))
        base_cooldown = int(float(config.get("cooldown_after_loss_streak_minutes", 0)) * 60)
        maker_fee_rate = float(config.get("maker_fee_rate", 0.001))
        taker_fee_rate = float(config.get("taker_fee_rate", 0.001))
        slippage_bps = float(config.get("slippage_bps", 5.0))
        spread_buffer_bps = float(config.get("spread_buffer_bps", 3.0))
        min_edge_multiplier = float(config.get("min_edge_multiplier", 2.5))
        min_expected_rr = float(config.get("min_expected_rr", 1.5))
        min_order_notional = float(config.get("min_order_notional", 60.0))
        loss_streak_limit = int(config.get("loss_streak_limit", 3))

        # Trading-core settings (migrated from env)
        base_qty = float(config.get("demo_order_qty", 0.01))
        base_min_confidence = float(config.get("demo_min_signal_confidence", aggr_profile["demo_min_signal_confidence"]))
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
        demo_require_manual_confirm = bool(config.get("demo_require_manual_confirm", False))
        demo_allow_soft_buy_entries = bool(config.get("demo_allow_soft_buy_entries", aggr_profile["demo_allow_soft_buy_entries"]))
        demo_min_entry_score = float(config.get("demo_min_entry_score", aggr_profile["demo_min_entry_score"]))

        # Maksymalna pewność = mniej transakcji, wyższe progi, dłuższy cooldown.
        if max_certainty_mode:
            base_min_confidence = max(base_min_confidence, 0.9)
            extreme_min_conf = max(extreme_min_conf, 0.92)
            extreme_min_rating = max(extreme_min_rating, 5)
            extreme_margin_pct = min(extreme_margin_pct, 0.01)
            max_trades_per_day = min(max_trades_per_day, 1)
            base_cooldown = max(base_cooldown, 3600)
            base_risk_per_trade = min(base_risk_per_trade, 0.002)
            demo_require_manual_confirm = True  # max_certainty zawsze wymaga potwierdzenia

        pending_cooldown_seconds = int(config.get("pending_order_cooldown_seconds", aggr_profile["pending_order_cooldown_seconds"]))

        # Zakresy z bloga (OpenAI/heurystyka)
        range_map: dict[str, dict] = {}
        max_ai_age_seconds = int(config.get("max_ai_insights_age_seconds", 7200))
        use_heuristic_fallback = bool(config.get("demo_use_heuristic_ranges_fallback", True))
        ai_ranges_stale = False
        try:
            from backend.database import BlogPost

            latest_blog = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
            if latest_blog and latest_blog.created_at:
                age_s = (now - latest_blog.created_at).total_seconds()
                if age_s > max_ai_age_seconds:
                    ai_ranges_stale = True
                    if not self.last_stale_ai_log_ts or (now - self.last_stale_ai_log_ts).total_seconds() > 300:
                        self.last_stale_ai_log_ts = now
                        log_to_db(
                            "WARNING",
                            "demo_trading",
                            f"Zakresy AI są nieaktualne ({int(age_s)}s temu) — "
                            + ("używam heurystyki ATR jako fallback." if use_heuristic_fallback else "zatrzymuję DEMO."),
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
            log_exception("demo_trading", "Błąd odczytu zakresów OpenAI z bloga", exc, db=db)
            ai_ranges_stale = True

        # Fallback: heurystyczne zakresy ATR dla symboli bez zakresów AI
        # Uruchamiamy gdy: brak danych z bloga LUB blog jest nieaktualny LUB watchlist ma nowe symbole
        missing_syms = [s for s in self.watchlist if s not in range_map]
        if (not range_map or ai_ranges_stale or missing_syms) and use_heuristic_fallback:
            try:
                from backend.analysis import generate_market_insights, _heuristic_ranges
                # Generuj tylko dla brakujących symboli (optimalizacja) albo całej watchlisty gdy stale
                syms_for_heuristic = self.watchlist if (not range_map or ai_ranges_stale) else missing_syms
                insights_fallback = generate_market_insights(db, syms_for_heuristic, timeframe="1h")
                heuristic_list = _heuristic_ranges(insights_fallback)
                # _heuristic_ranges zwraca List[Dict] — konwertuj na dict symbol→range
                for item in heuristic_list:
                    sym = item.get("symbol")
                    if sym and sym not in range_map:
                        range_map[sym] = item
                if missing_syms and range_map:
                    log_to_db("INFO", "demo_trading",
                              f"Heurystyczne zakresy ATR dla {len(missing_syms)} brakujących symboli.", db=db)
                elif ai_ranges_stale and range_map:
                    log_to_db("INFO", "demo_trading",
                              f"Heurystyczne zakresy ATR dla {len(range_map)} symboli (fallback AI).", db=db)
            except Exception as exc2:
                log_exception("demo_trading", "Błąd generowania heurystycznych zakresów", exc2, db=db)

        if not range_map:
            log_to_db("ERROR", "demo_trading", "Brak jakichkolwiek zakresów (AI i heurystyka) — pomijam decyzje DEMO", db=db)
            return None

        # Ryzyko (dzienny limit + drawdown)
        unrealized_pnl = float(account_state.get("unrealized_pnl") or 0.0)
        realized_pnl_24h = float(account_state.get("realized_pnl_24h") or 0.0)
        daily_loss_limit = -(initial_balance * max_daily_loss_pct / 100)
        daily_loss_triggered = (realized_pnl_24h + unrealized_pnl) <= daily_loss_limit

        positions_all = db.query(Position).filter(Position.mode == mode).all()
        positions = [
            p
            for p in positions_all
            if (p.symbol or "").strip().upper().replace("/", "").replace("-", "").endswith(demo_quote_ccy)
        ]

        # Helpers for pending order checks
        def _has_active_pending(sym: str) -> bool:
            return (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.symbol == sym,
                    PendingOrder.status.in_(["PENDING", "CONFIRMED", "OPEN"]),
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
            return (now - last.created_at).total_seconds() < float(pending_cooldown_seconds)

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
        _exit_mode = tc.get("mode", "demo")

        def _exit_message(reason_code: str, sym: str, price: float, tp: float, sl: float,
                          qty: float = 0, partial: bool = False,
                          entry_price: float = 0) -> str:
            base = _reason_pl.get(reason_code, f"Wyjście ({reason_code})")
            # PnL
            pnl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else 0
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
            snapshot, plan, revision = self._build_symbol_plan(db, sym, mode=_exit_mode, position=pos, force_reconsult=False)
            if plan:
                pos.decision_plan_json = json.dumps(plan, ensure_ascii=True, sort_keys=True)
                pos.plan_status = plan.get("plan_status", "active")
                pos.requires_revision = bool(plan.get("requires_revision", False))
                pos.invalidation_reason = plan.get("invalidation_reason")
                pos.last_consulted_at = utc_now_naive()

            # TP/SL: używamy planned_tp/sl z momentu wejścia, fallback do ATR
            stop_loss = float(pos.planned_sl) if pos.planned_sl else (entry - atr * atr_stop_mult)
            take_profit = float(pos.planned_tp) if pos.planned_tp else (entry + atr * atr_take_mult)
            if plan:
                stop_loss = float(plan.get("stop_loss_price") or stop_loss)
                take_profit = float(plan.get("take_profit_price") or take_profit)

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
                and float(_latest_fc.forecast_price) > price * 1.005  # prognoza >0.5% powyżej ceny
            )

            # Trailing stop — aktualizuj poziom jeśli aktywny
            trailing_active = bool(pos.trailing_active)
            trailing_stop = float(pos.trailing_stop_price) if pos.trailing_stop_price else None
            if trailing_active:
                new_trail = price - atr * trail_mult
                if trailing_stop is None or new_trail > trailing_stop:
                    trailing_stop = new_trail
                    pos.trailing_stop_price = trailing_stop

            # ── Break-even upgrade: gdy zysk ≥ 1×ATR → przesuń SL do entry ──────────
            # Zabezpiecza kapitał bez zamykania pozycji — trader "na zero" gdy rynek wraca
            be_atr_trigger = float(config.get("break_even_atr_trigger", 1.0))
            be_trigger_price = entry + atr * be_atr_trigger
            if price >= be_trigger_price and float(pos.planned_sl or 0) < entry:
                new_be_sl = entry + atr * 0.05  # mały bufor nad entry (unikaj fałszywego SL przy spread)
                pos.planned_sl = new_be_sl
                stop_loss = new_be_sl  # zaktualizuj zmienną lokalną dla bieżącej iteracji
                db.add(pos)
                _be_msg = (
                    f"[BE] Break-even SL aktywowany: {sym} | "
                    f"Zysk {price - entry:.6f} ≥ 1×ATR={atr:.6f} | "
                    f"SL podniesiony do {new_be_sl:.6f} (entry={entry:.6f})"
                )
                log_to_db("INFO", "exit_engine", _be_msg, db=db)

            # ━━━ WARSTWA 1: HARD EXIT — Stop Loss ━━━━━━━━━━━━━━━━━━━━━━━━━
            if price <= stop_loss:
                reason_code = "stop_loss_hit"
                msg = _exit_message(reason_code, sym, price, take_profit, stop_loss, qty, entry_price=entry)
                self._trace_decision(
                    db, symbol=sym, action="CREATE_PENDING_EXIT", reason_code=reason_code,
                    runtime_ctx=runtime_ctx, mode=_exit_mode,
                    signal_summary={"source": "exit_engine", "layer": "hard_exit", "atr": atr, "entry": entry, "price": price},
                    risk_check={"daily_loss_triggered": daily_loss_triggered},
                    cost_check={"eligible": True}, execution_check={"eligible": True},
                    snapshot=snapshot, plan=plan,
                    details={"stop_loss": stop_loss, "take_profit": take_profit, "quantity": qty},
                )
                pending_id = self._create_pending_order(
                    db=db, symbol=sym, side="SELL", price=price, qty=qty, mode=_exit_mode,
                    reason=f"[SL] Stop Loss @ {price:.6f} (SL={stop_loss:.6f})",
                    config_snapshot_id=runtime_ctx.get("snapshot_id"), strategy_name="demo_collector",
                    exit_reason_code="stop_loss_hit",
                    decision_plan=plan,
                )
                # Eskalacja cooldown po SL — zapobiega natychmiastowemu re-entry
                sl_state = self.demo_state.get(sym, {"loss_streak": 0, "cooldown": base_cooldown})
                sl_state["loss_streak"] = min(sl_state.get("loss_streak", 0) + 1, loss_streak_limit)
                # PROFIT-FIX: cooldown po SL skaluje z loss_streak; cap = base_cooldown (nie < base_cooldown)
                # base_cooldown = cooldown_after_loss_streak_minutes*60 — teraz 7200s (120min)
                sl_cooldown = base_cooldown * (1 + sl_state["loss_streak"])
                sl_state["cooldown"] = max(base_cooldown, min(sl_cooldown, base_cooldown * 4))
                sl_state["win_streak"] = 0
                self.demo_state[sym] = sl_state
                self._send_telegram_alert(f"{_mode_label}: Stop Loss", msg, force_send=True)
                db.add(Alert(alert_type="RISK", severity="WARNING", title=f"SL {sym}",
                             message=msg, symbol=sym, is_sent=True, timestamp=now))
                continue

            # ━━━ WARSTWA 2: TRAILING STOP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if trailing_active and trailing_stop and price <= trailing_stop:
                exit_guard = self._exit_allowed_by_plan(snapshot=snapshot, plan=plan, reason_code="trailing_lock_profit", current_price=price, position=pos)
                if not exit_guard.get("allowed"):
                    self._trace_decision(
                        db, symbol=sym, action="SKIP", reason_code="exit_blocked_below_breakeven",
                        runtime_ctx=runtime_ctx, mode=_exit_mode,
                        signal_summary={"source": "exit_engine", "layer": "trailing", "price": price},
                        cost_check={"eligible": False, "why": exit_guard.get("why")},
                        snapshot=snapshot, plan=plan,
                    )
                    continue
                reason_code = "trailing_lock_profit"
                msg = _exit_message(reason_code, sym, price, take_profit, trailing_stop, qty, entry_price=entry)
                self._trace_decision(
                    db, symbol=sym, action="CREATE_PENDING_EXIT", reason_code=reason_code,
                    runtime_ctx=runtime_ctx, mode=_exit_mode,
                    signal_summary={"source": "exit_engine", "layer": "trailing", "price": price, "trailing_stop": trailing_stop},
                    risk_check={}, cost_check={"eligible": True}, execution_check={"eligible": True},
                    snapshot=snapshot, plan=plan,
                    details={"trailing_stop": trailing_stop, "quantity": qty},
                )
                pending_id = self._create_pending_order(
                    db=db, symbol=sym, side="SELL", price=price, qty=qty, mode=_exit_mode,
                    reason=f"[TRAIL] Trailing stop @ {price:.6f} (trail={trailing_stop:.6f})",
                    config_snapshot_id=runtime_ctx.get("snapshot_id"), strategy_name="demo_collector",
                    exit_reason_code="trailing_lock_profit",
                    decision_plan=plan,
                )
                self._send_telegram_alert(f"{_mode_label}: Trailing Stop", msg, force_send=True)
                db.add(Alert(alert_type="SIGNAL", severity="INFO", title=f"TRAIL {sym}",
                             message=msg, symbol=sym, is_sent=True, timestamp=now))
                continue

            # ━━━ WARSTWA 3: TAKE PROFIT (częściowy lub pełny) ━━━━━━━━━━━━━
            if price >= take_profit:
                exit_guard = self._exit_allowed_by_plan(snapshot=snapshot, plan=plan, reason_code="tp_full_reversal", current_price=price, position=pos)
                if not exit_guard.get("allowed"):
                    self._trace_decision(
                        db, symbol=sym, action="SKIP", reason_code="exit_blocked_below_breakeven",
                        runtime_ctx=runtime_ctx, mode=_exit_mode,
                        signal_summary={"source": "exit_engine", "layer": "tp", "price": price},
                        cost_check={"eligible": False, "why": exit_guard.get("why")},
                        snapshot=snapshot, plan=plan,
                    )
                    continue
                # P1-FIX: Oceń siłę trendu — RSI górna granica podniesiona 75→82.
                # W silnym bull runie RSI naturalnie jest 75-85, stary próg powodował
                # przedwczesne zamykanie zyskownych pozycji (BTC rosło, bot zamykał).
                # ADX z get_live_context() (teraz dostępny) potwierdza siłę trendu.
                _adx_ctx = ctx.get("adx")  # dostępne po P1-FIX w get_live_context()
                _st_ctx = ctx.get("supertrend_dir")  # dostępne po P1-FIX
                _ema_bullish = (
                    ema_20 is not None and ema_50 is not None
                    and float(ema_20) > float(ema_50)
                )
                # Trend silny gdy: EMA bycze + RSI < 82 LUB ADX > 25 + EMA bycze LUB forecast AI LUB Supertrend bycze
                trend_strong = (
                    (_ema_bullish and rsi < 82.0)                                      # P1-FIX: 75→82
                    or forecast_bullish                                                 # AI prognoza wzrostu
                    or (_ema_bullish and _adx_ctx is not None and float(_adx_ctx) >= 25)  # silny trend ADX
                    or (_st_ctx is not None and float(_st_ctx) > 0 and _ema_bullish)   # Supertrend bycze
                )
                partial_qty = round(qty * 0.25, 8)
                can_partial = (partial_count < 2) and (partial_qty > 0) and (partial_qty < qty * 0.95)

                if can_partial and trend_strong:
                    # Częściowe zamknięcie 25% + aktywuj trailing + podnieś SL
                    reason_code = "tp_partial_keep_trend"
                    msg = _exit_message(reason_code, sym, price, take_profit, stop_loss, partial_qty, partial=True, entry_price=entry)
                    self._trace_decision(
                        db, symbol=sym, action="CREATE_PENDING_EXIT", reason_code=reason_code,
                        runtime_ctx=runtime_ctx, mode=_exit_mode,
                        signal_summary={"source": "exit_engine", "layer": "tp_soft", "price": price,
                                        "tp": take_profit, "rsi": rsi, "ema_trend": "up",
                                        "forecast_bullish": forecast_bullish, "adx": _adx_ctx,
                                        "trend_strong_reason": "ema+rsi<82" if (_ema_bullish and rsi < 82.0) else (
                                            "forecast_bullish" if forecast_bullish else ("adx>=25" if _adx_ctx and float(_adx_ctx) >= 25 else "supertrend"))},
                        risk_check={}, cost_check={"eligible": True}, execution_check={"eligible": True},
                        snapshot=snapshot, plan=plan,
                        details={"partial_qty": partial_qty, "full_qty": qty, "partial_count": partial_count},
                    )
                    pending_id = self._create_pending_order(
                        db=db, symbol=sym, side="SELL", price=price, qty=partial_qty, mode=_exit_mode,
                        reason=f"[TP-PARTIAL] Trend trwa — zamykamy 25% @ {price:.6f} (TP={take_profit:.6f})",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"), strategy_name="demo_collector",
                        exit_reason_code="tp_partial_keep_trend",
                        decision_plan=plan,
                    )
                    # Podnieś SL do break-even lub wyżej
                    pos.planned_sl = max(stop_loss, entry)
                    # Aktywuj trailing
                    pos.trailing_active = True
                    new_trail = price - atr * trail_mult
                    if not pos.trailing_stop_price or new_trail > float(pos.trailing_stop_price):
                        pos.trailing_stop_price = new_trail
                    self._send_telegram_alert(f"{_mode_label}: Częściowe TP", msg, force_send=True)
                    db.add(Alert(alert_type="SIGNAL", severity="INFO", title=f"TP-PARTIAL {sym}",
                                 message=msg, symbol=sym, is_sent=True, timestamp=now))
                else:
                    # Pełne zamknięcie
                    reason_code = "tp_full_reversal" if (not trend_strong) else "weak_trend_after_tp"
                    msg = _exit_message(reason_code, sym, price, take_profit, stop_loss, qty, entry_price=entry)
                    self._trace_decision(
                        db, symbol=sym, action="CREATE_PENDING_EXIT", reason_code=reason_code,
                        runtime_ctx=runtime_ctx, mode=_exit_mode,
                        signal_summary={"source": "exit_engine", "layer": "tp_full", "price": price,
                                        "tp": take_profit, "rsi": rsi, "trend_strong": trend_strong,
                                        "forecast_bullish": forecast_bullish},
                        risk_check={}, cost_check={"eligible": True}, execution_check={"eligible": True},
                        snapshot=snapshot, plan=plan,
                        details={"quantity": qty, "trend_strong": trend_strong, "partial_count": partial_count},
                    )
                    pending_id = self._create_pending_order(
                        db=db, symbol=sym, side="SELL", price=price, qty=qty, mode=_exit_mode,
                        reason=f"[TP-FULL] {_reason_pl.get(reason_code, reason_code)} @ {price:.6f}",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"), strategy_name="demo_collector",
                        exit_reason_code=reason_code,
                        decision_plan=plan,
                    )
                    # Sukces — zeruj loss_streak, zwiększ win_streak
                    tp_state = self.demo_state.get(sym, {"loss_streak": 0, "win_streak": 0, "cooldown": base_cooldown})
                    tp_state["loss_streak"] = 0
                    tp_state["win_streak"] = tp_state.get("win_streak", 0) + 1
                    tp_state["cooldown"] = base_cooldown
                    self.demo_state[sym] = tp_state
                    self._send_telegram_alert(f"{_mode_label}: EXIT TP", msg, force_send=True)
                    db.add(Alert(alert_type="SIGNAL", severity="INFO", title=f"TP {sym}",
                                 message=msg, symbol=sym, is_sent=True, timestamp=now))
                continue

            # ━━━ WARSTWA 4: REVERSAL CHECK (dla pozycji po TP lub z trailing) ━━━
            if (trailing_active or partial_count > 0) and ema_20 is not None and ema_50 is not None:
                pnl_pct = (price - entry) / entry * 100 if entry > 0 else 0
                # P1-FIX: RSI threshold 65→70 — w bull runie RSI 65 jest normalny,
                # wymagaj wyraźniejszego sygnału wykupienia + bearish EMA jednocześnie
                if pnl_pct > 2.0 and float(ema_20) < float(ema_50) and rsi > 70.0:
                    exit_guard = self._exit_allowed_by_plan(snapshot=snapshot, plan=plan, reason_code="tp_full_reversal", current_price=price, position=pos)
                    if not exit_guard.get("allowed"):
                        self._trace_decision(
                            db, symbol=sym, action="SKIP", reason_code="exit_blocked_below_breakeven",
                            runtime_ctx=runtime_ctx, mode=_exit_mode,
                            signal_summary={"source": "exit_engine", "layer": "reversal", "price": price},
                            cost_check={"eligible": False, "why": exit_guard.get("why")},
                            snapshot=snapshot, plan=plan,
                        )
                        continue
                    reason_code = "tp_full_reversal"
                    msg = _exit_message(reason_code, sym, price, take_profit, stop_loss, qty, entry_price=entry)
                    self._trace_decision(
                        db, symbol=sym, action="CREATE_PENDING_EXIT", reason_code=reason_code,
                        runtime_ctx=runtime_ctx, mode=_exit_mode,
                        signal_summary={"source": "exit_engine", "layer": "reversal", "price": price,
                                        "rsi": rsi, "ema_20": float(ema_20), "ema_50": float(ema_50)},
                        risk_check={}, cost_check={"eligible": True}, execution_check={"eligible": True},
                        snapshot=snapshot, plan=plan,
                        details={"pnl_pct": pnl_pct, "quantity": qty},
                    )
                    pending_id = self._create_pending_order(
                        db=db, symbol=sym, side="SELL", price=price, qty=qty, mode=_exit_mode,
                        reason=f"[REVERSAL] Odwrócenie trendu — zysk +{pnl_pct:.1f}% @ {price:.6f}",
                        config_snapshot_id=runtime_ctx.get("snapshot_id"), strategy_name="demo_collector",
                        exit_reason_code=reason_code,
                        decision_plan=plan,
                    )
                    self._send_telegram_alert(f"{_mode_label}: EXIT Reversal", msg, force_send=True)
                    db.add(Alert(alert_type="SIGNAL", severity="INFO", title=f"REVERSAL {sym}",
                                 message=msg, symbol=sym, is_sent=True, timestamp=now))
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
                    if not self.last_risk_alert_ts or (now - self.last_risk_alert_ts).total_seconds() > 900:
                        self.last_risk_alert_ts = now
                        msg = f"🔴 Pozycja {p.symbol} traci za dużo ({drawdown_pct:.1f}%, limit: {max_drawdown_pct}%).\nSystem ograniczył ryzyko na tym symbolu.\nCo zrobić: rozważ zamknięcie pozycji."
                        log_to_db("WARNING", "demo_trading", msg, db=db)
                        self._send_telegram_alert("RISK: Drawdown", msg, force_send=True)
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
                        state = self.demo_state.get(p.symbol, {"loss_streak": 0, "cooldown": base_cooldown})
                        state["loss_streak"] = min(state.get("loss_streak", 0) + 1, loss_streak_limit)
                        state["cooldown"] = min(base_cooldown * (1 + state["loss_streak"]), 3600)
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
                md = db.query(MarketData).filter(MarketData.symbol == sym).order_by(MarketData.timestamp.desc()).first()
                if md:
                    price = float(md.price or 0)
            if price <= 0:
                continue

            qty = float(pos.quantity or 0)
            position_value = qty * price

            if position_value >= target_eur:
                if _has_active_pending(sym):
                    continue

                pending_id = f"HOLD_SELL_{sym}_{now.strftime('%Y%m%d%H%M%S')}"
                _m = tc.get("mode", "demo")
                db.add(
                    Order(
                        order_id=pending_id,
                        symbol=sym,
                        side="SELL",
                        order_type="LIMIT",
                        quantity=qty,
                        price=price,
                        status="pending_review",
                        mode=_m,
                        timestamp=now,
                    )
                )
                msg = (
                    f"🟢 [HOLD] Cel osiągnięty — {sym}\n"
                    f"\n"
                    f"Wartość pozycji: {position_value:.2f} EUR (cel: {target_eur:.0f} EUR)\n"
                    f"Cena: {price:.6f}\n"
                    f"Ilość: {qty}\n"
                    f"\n"
                    f"Co zrobić:\n"
                    f"/confirm {pending_id} — potwierdź sprzedaż\n"
                    f"/reject {pending_id} — odrzuć"
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
                    sym, position_value, target_eur, pending_id,
                )
            else:
                logger.debug(
                    "[HOLD] %s wartość %.2f EUR < cel %.0f EUR — trzymamy",
                    sym, position_value, target_eur,
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
        min_order_notional = float(tc.get("min_order_notional", 60.0))
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
            log_to_db("WARNING", "capital_rotation",
                      f"Brak wolnych środków ({available_cash:.2f}) — wszystkie pozycje w HOLD lub pending. "
                      "Nie można dokonać rotacji kapitału.", db=db)
            return False

        # Najgorsza pozycja = najniższy unrealized_pnl (stop bleeding)
        worst = min(closeable, key=lambda p: float(p.unrealized_pnl or 0))
        sym = worst.symbol
        qty = float(worst.quantity)

        # Oblicz PnL% jeszcze przed pobraniem ceny, na podstawie entry + current_price
        _entry_pre = float(worst.entry_price or 0)
        _cur_pre = float(worst.current_price or worst.entry_price or 0)
        _pnl_pct_pre = (_cur_pre - _entry_pre) / _entry_pre * 100 if _entry_pre > 0 else 0.0

        # GUARD: nie rotuj jeśli najgorsza pozycja jest na plusie — nie zamykamy zysków tylko dla nowego wejścia
        if _pnl_pct_pre >= 0:
            log_to_db("INFO", "capital_rotation",
                      f"Rotacja kapitału pominięta: {sym} PnL={_pnl_pct_pre:+.1f}% — "
                      f"wszystkie pozycje na plusie. Nie zamykamy zyskownych pozycji.",
                      db=db)
            logger.info(
                "[CAPITAL_ROTATION] SKIP — %s PnL=%+.1f%% (all profitable, no rotation)",
                sym, _pnl_pct_pre,
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
            db=db, symbol=sym, side="SELL", price=price, qty=qty,
            mode=mode,
            reason=f"Rotacja kapitału: brak wolnych środków ({available_cash:.2f} < {min_order_notional:.0f}). "
                   f"Zamykam najgorszą pozycję {sym} PnL={pnl_pct:+.1f}%.",
            strategy_name="capital_rotation",
        )

        log_to_db("WARNING", "capital_rotation",
                  f"Rotacja kapitału: {sym} SELL qty={qty:.6g} @ {price:.6f} | "
                  f"PnL={pnl_pct:+.1f}% | wolne środki={available_cash:.2f} < min={min_order_notional:.0f} | "
                  f"pending_id={pending_id}",
                  db=db)

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
        self._send_telegram_alert(f"{_mode_label}: ROTACJA KAPITAŁU", msg, force_send=True)

        # Wykonaj sprzedaż natychmiast (pending jest już CONFIRMED z _create_pending_order)
        try:
            self._execute_confirmed_pending_orders(db)
        except Exception as exc:
            log_exception("capital_rotation", "Błąd wykonania rotacji kapitału", exc, db=db)

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

            # Grace period dla importowanych pozycji — poczekaj 2 godziny zanim ustawisz TP/SL.
            # Zapobiega natychmiastowemu wyjściu na pozycjach importowanych z Binance
            # gdy ATR jest obliczony na bazie starych danych lub cena zdążyła przesunąć się
            # względem poziomu importu.
            if (
                getattr(pos, "entry_reason_code", None) == "binance_import"
                and needs_tp and needs_sl  # tylko gdy brak OBUŻ: TP i SL
                and pos.updated_at is not None
                and (utc_now_naive() - pos.updated_at).total_seconds() < 7200  # < 2h
            ):
                logger.debug(
                    "[AUTO_GOALS] %s: grace period aktywny (imported %d min temu) — pomijam TP/SL",
                    sym, int((utc_now_naive() - pos.updated_at).total_seconds() / 60),
                )
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
                        ema20_4h and ema50_4h
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

            # Minimum distance guard — zapobiega degeneracji TP/SL gdy ATR jest zbyt mały
            # (np. SHIB gdzie ATR ≈ 0 → tp=sl=price → natychmiastowy exit)
            min_tp_dist = entry * 0.005   # min TP: +0.5% od ceny wejścia
            min_sl_dist = entry * 0.003   # min SL: -0.3% od ceny wejścia
            if pos.planned_tp is not None and pos.planned_tp < entry + min_tp_dist:
                pos.planned_tp = entry + min_tp_dist
            if pos.planned_sl is not None and pos.planned_sl > entry - min_sl_dist:
                pos.planned_sl = entry - min_sl_dist

            set_count += 1
            log_to_db(
                "INFO", "auto_goals",
                f"Auto-cele: {sym} tp={pos.planned_tp:.6f} sl={pos.planned_sl:.6f} "
                f"(entry={entry:.6f} ATR={atr:.6f} tp×{tp_mult:.1f} sl×{atr_stop_mult:.1f})",
                db=db,
            )
            logger.info(
                "[AUTO_GOALS] %s: tp=%.6f sl=%.6f (entry=%.6f ATR×%.1f)",
                sym, pos.planned_tp, pos.planned_sl, entry, tp_mult,
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
        demo_min_entry_score = tc.get("demo_min_entry_score", 5.5)

        available_cash = tc["available_cash"]
        _mode_label = str(tc.get("mode") or "demo").upper()

        # Diagnostyka: ostrzeż gdy brak gotówki na nowe pozycje (rotacja kapitału nie pomogła)
        if available_cash < min_order_notional:
            log_to_db(
                "WARNING", "screen_candidates",
                f"[{_mode_label}] Brak gotówki ({available_cash:.2f} EUR < min {min_order_notional:.0f} EUR) "
                f"— pomijam screening. Jeśli LIVE: uzupełnij saldo Binance; jeśli DEMO: sprawdź reset balansu.",
                db=db,
            )
            return

        # Zbieramy kandydatów, sortujemy po expected value netto, potem tworzymy pending
        candidates: list[dict] = []

        for symbol in self.watchlist:
            if not symbol:
                continue
            sym_norm = (symbol or "").strip().upper().replace("/", "").replace("-", "")
            if not sym_norm.endswith(demo_quote_ccy):
                continue

            # --- Tier gating: symbole spoza tiers wchodzą jako tier "SCANNER" ---
            # Symbole dodane przez skaner wolumenowy nie są w konfiguracji tiers,
            # ale mogą handlować z ostrożniejszymi parametrami (risk_scale=0.5, max 1/dzień)
            sym_tier = tier_map.get(sym_norm)
            if tier_map and not sym_tier:
                sym_tier = {
                    "tier": "SCANNER",
                    "min_confidence_add": 0.07,   # wyższy próg dla nowych symboli
                    "min_edge_multiplier_add": 0.5,
                    "risk_scale": 0.5,             # połowa pozycji
                    "max_trades_per_day_per_symbol": 1,
                }

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
            tier_conf_add = float(sym_tier.get("min_confidence_add", 0.0)) if sym_tier else 0.0
            tier_edge_add = float(sym_tier.get("min_edge_multiplier_add", 0.0)) if sym_tier else 0.0
            tier_risk_scale = float(sym_tier.get("risk_scale", 1.0)) if sym_tier else 1.0
            tier_max_trades = int(sym_tier.get("max_trades_per_day_per_symbol", 99)) if sym_tier else 99
            tier_name = sym_tier.get("tier", "UNKNOWN") if sym_tier else "UNKNOWN"

            # Limit dziennych transakcji na symbol (z tieru)
            _current_mode = tc.get("mode", "demo")
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Liczymy tylko BUY (wejścia) — partial take-profit generuje 3 SELL/pozycję,
            # zliczanie ich jako osobne "tradesie" blokowałoby symbol po 1 pełnym cyklu.
            sym_trades_today = (
                db.query(Order)
                .filter(
                    Order.symbol == symbol,
                    Order.mode == _current_mode,
                    Order.side == "BUY",
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
                    risk_check={"tier": tier_name, "trades_today": sym_trades_today, "limit": tier_max_trades},
                )
                continue
            if _has_active_pending(symbol):
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="active_pending_exists",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    execution_check={"eligible": False, "has_active_pending": True},
                )
                continue
            if _pending_in_cooldown(symbol):
                self._trace_decision(
                    db,
                    symbol=symbol,
                    action="SKIP",
                    reason_code="pending_cooldown_active",
                    runtime_ctx=runtime_ctx,
                    mode=_current_mode,
                    risk_check={"cooldown_active": True, "pending_cooldown_seconds": pending_cooldown_seconds},
                )
                continue

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
                .filter(Position.symbol == symbol, Position.mode == _current_mode)
                .first()
            )

            # Cooldown po ostatniej wykonanej transakcji
            last_order = (
                db.query(Order)
                .filter(Order.symbol == symbol, Order.mode == _current_mode)
                .order_by(Order.timestamp.desc())
                .first()
            )
            state = self.demo_state.get(symbol, {"loss_streak": 0, "win_streak": 0, "cooldown": base_cooldown})
            cooldown = int(state.get("cooldown", base_cooldown))
            if cooldown > 0 and last_order and (now - last_order.timestamp).total_seconds() < float(cooldown):
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

            sig = (
                db.query(Signal)
                .filter(Signal.symbol == symbol)
                .order_by(Signal.timestamp.desc())
                .first()
            )
            if not sig:
                continue

            signal_summary = {
                "signal_type": sig.signal_type,
                "confidence": float(sig.confidence),
                "timestamp": sig.timestamp.isoformat() if sig.timestamp else None,
            }
            params = self.symbol_params.get(symbol, {})
            learned_conf = float(params.get("min_confidence", base_min_confidence))
            # Learned params mogą podnieść próg max o 0.10 powyżej base — nie blokuj trading
            min_confidence = min(base_min_confidence + 0.10, max(base_min_confidence, learned_conf))
            # Tier override: podniesienie min_confidence
            min_confidence = min(1.0, min_confidence + tier_conf_add)

            # Reżim rynkowy — dostosuj min_confidence na podstawie F&G + CoinGecko
            from backend.analysis import get_market_regime
            market_regime = get_market_regime()
            regime_adj = float(market_regime.get("buy_confidence_adj", 0.0))
            if sig.signal_type == "BUY":
                # Blokuj BUY gdy reżim CRASH lub BEAR.
                # WYJĄTEK: ekstremalnie wyprzedany symbol (RSI < extreme_oversold_rsi_threshold)
                # może wejść jako mean-reversion z niższym progiem confidence.
                if market_regime.get("buy_blocked"):
                    bear_min_conf = float(config.get("bear_regime_min_conf", 0.62))
                    oversold_thresh = float(config.get("extreme_oversold_rsi_threshold", 28.0))
                    oversold_bypass_conf = float(config.get("bear_oversold_bypass_conf", 0.55))
                    # RSI z wskaźników sygnału (szybki odczyt bez ctx)
                    _sig_ind = json.loads(sig.indicators) if sig.indicators else {}
                    _sig_rsi = float(_sig_ind.get("rsi") or 50.0)
                    _is_extreme_oversold_regime = _sig_rsi < oversold_thresh
                    # W ekstremalnym wyprzedaniu: obniż wymagany próg confidence
                    effective_bear_min = oversold_bypass_conf if _is_extreme_oversold_regime else bear_min_conf
                    if float(sig.confidence) < effective_bear_min:
                        self._trace_decision(
                            db, symbol=symbol, action="SKIP", reason_code="market_regime_buy_blocked",
                            runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                            risk_check={
                                "regime": market_regime.get("regime"),
                                "reason": market_regime.get("reason", "")[:200],
                                "bear_min_conf": effective_bear_min,
                                "signal_conf": float(sig.confidence),
                                "sig_rsi": _sig_rsi,
                                "oversold_bypass": _is_extreme_oversold_regime,
                            },
                        )
                        continue
                    # P1-FIX: Sygnał przeszedł specyficzny test BEAR/CRASH — NIE dodawaj buy_confidence_adj
                    # na wierzch min_confidence (to powodowało double-blocking: sygnał 0.62 był
                    # blokowany przez min_confidence 0.55+0.10=0.65 mimo przejścia przez bear_min_conf 0.62).
                    # Ustaw min_confidence = effective_bear_min to uniknąć podwójnego blokowania.
                    signal_summary = dict(signal_summary) if signal_summary else {}
                    signal_summary["bear_regime_override"] = True
                    signal_summary["mean_reversion_entry"] = _is_extreme_oversold_regime
                    min_confidence = min(min_confidence, effective_bear_min)  # nie podnoś powyżej użytego progu
                # Podnieś próg confidence w słabych reżimach (BEAR_SOFT)
                elif regime_adj > 0:
                    min_confidence = min(1.0, min_confidence + regime_adj)

            if float(sig.confidence) < float(min_confidence):
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="signal_confidence_too_low",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check={"min_confidence": min_confidence, "tier": tier_name, "regime": market_regime.get("regime")},
                )
                continue
            if (now - sig.timestamp).total_seconds() > float(max_signal_age):
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="signal_too_old",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check={"max_signal_age_seconds": max_signal_age},
                )
                continue

            r = range_map.get(symbol)
            # Brak zakresu AI: fallback na czyste wskaźniki (Supertrend + EMA + RSI)
            # Trader bez poziomu AI wchodzi gdy trend + RSI są zgodne — nie stoi z boku
            _synthetic_range = not bool(r)
            if _synthetic_range:
                r = {}  # pusty dict — filtry price-in-zone zostaną pominięte

            crash = self._detect_crash(db, symbol, crash_window_minutes, crash_drop_pct)
            if crash:
                # Symbol-level crash: wyższy próg, ale z bypasem dla ekstremalnego wyprzedania
                _sig_ind_c = json.loads(sig.indicators) if sig.indicators else {}
                _sig_rsi_c = float(_sig_ind_c.get("rsi") or 50.0)
                _oversold_thresh_c = float(config.get("extreme_oversold_rsi_threshold", 28.0))
                _is_oversold_crash = _sig_rsi_c < _oversold_thresh_c
                _crash_conf_thresh = float(config.get("bear_oversold_bypass_conf", 0.55)) if _is_oversold_crash else extreme_min_conf
                if float(sig.confidence) < _crash_conf_thresh:
                    continue
                state["cooldown"] = max(int(state.get("cooldown", base_cooldown)), crash_cooldown_seconds)
                self.demo_state[symbol] = state
                if not self.last_crash_alert_ts or (now - self.last_crash_alert_ts).total_seconds() > 1800:
                    self.last_crash_alert_ts = now
                    msg = (
                        f"🔴 Gwałtowny spadek: {symbol}\n"
                        f"Spadek > {crash_drop_pct}% w ciągu {crash_window_minutes} min.\n"
                        f"System: ograniczenie ryzyka, bot nadal działa.\n"
                        f"Co zrobić: obserwuj sytuację, nie otwieraj nowych pozycji ręcznie."
                    )
                    log_to_db("WARNING", "demo_trading", msg, db=db)
                    self._send_telegram_alert("RISK: Crash mode", msg, force_send=True)

            ctx = get_live_context(db, symbol, timeframe="1h", limit=max(min_klines, 120))
            if not ctx:
                continue
            ema20 = ctx.get("ema_20")
            ema50 = ctx.get("ema_50")
            rsi = ctx.get("rsi")
            rsi_buy = ctx.get("rsi_buy")
            rsi_sell = ctx.get("rsi_sell")
            atr = ctx.get("atr")
            supertrend_dir = ctx.get("supertrend_dir")   # +1 bycze, -1 niedźwiedzie
            adx_val = ctx.get("adx")                      # 0-100, >25 = silny trend
            volume_ratio = ctx.get("volume_ratio")        # wolumen / SMA20
            if not atr or float(atr) <= 0:
                continue

            snapshot, plan, revision = self._build_symbol_plan(db, symbol, mode=_current_mode, position=position, force_reconsult=False)
            if not snapshot or not plan:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="missing_trade_plan",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                )
                continue

            # PROFIT-FIX: ATR zbyt małe = ruch cenowy nie pokryje kosztów round-trip
            # Przy ATR/price < 0.5% nawet TP×3.5 = 1.75% vs koszty ≈0.36% — margines za wąski
            # w praktyce na wol. microalt (WIFEUR 0.3% ATR → spread i fee zjadają cały edge)
            _min_atr_pct = float(config.get("min_atr_pct", 0.005))  # 0.5% domyślnie
            if price and float(price) > 0 and float(atr) / float(price) < _min_atr_pct:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="atr_below_min_pct",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check={"atr": float(atr), "price": float(price),
                                "atr_pct": round(float(atr)/float(price)*100, 4),
                                "min_atr_pct": _min_atr_pct*100},
                )
                continue

            # Filtry wejścia/wyjścia — z 3% tolerancją cenową (rynek może wyjść poza zakres AI)
            side = None
            reasons: list[str] = []
            price_tolerance = float(config.get("range_price_tolerance_pct", 0.03))
            # RSI: zaostrzony próg — BUY tylko przy niższym RSI, SELL tylko przy wyższym RSI
            rsi_buy_gate = float(rsi_buy) if rsi_buy is not None else 52.0
            rsi_buy_gate = min(rsi_buy_gate, 55.0)
            rsi_sell_gate = float(rsi_sell) if rsi_sell is not None else 48.0
            rsi_sell_gate = max(rsi_sell_gate, 45.0)

            # Trend gate: wymagaj zgodności EMA i Supertrend, a nie jednego z nich
            _ema_trend_up = ema20 is not None and ema50 is not None and float(ema20) > float(ema50)
            _ema_trend_down = ema20 is not None and ema50 is not None and float(ema20) < float(ema50)
            _st_up = supertrend_dir is not None and float(supertrend_dir) > 0
            _st_down = supertrend_dir is not None and float(supertrend_dir) < 0
            trend_up = _ema_trend_up and (_st_up or supertrend_dir is None)
            trend_down = _ema_trend_down and (_st_down or supertrend_dir is None)
            _trend_reason_up = "EMA20>EMA50 + Supertrend bycze" if (_ema_trend_up and _st_up) else ("EMA20>EMA50" if _ema_trend_up else "brak trendu")
            _trend_reason_down = "EMA20<EMA50 + Supertrend niedźwiedzie" if (_ema_trend_down and _st_down) else ("EMA20<EMA50" if _ema_trend_down else "brak trendu")
            _momentum_buy_ok = adx_val is not None and float(adx_val) >= 18 and volume_ratio is not None and float(volume_ratio) >= 0.9
            _momentum_sell_ok = adx_val is not None and float(adx_val) >= 18

            if sig.signal_type == "BUY":
                rsi_ok = rsi is not None and float(rsi) <= rsi_buy_gate
                _rsi_val_buy = float(rsi) if rsi is not None else 50.0
                _trend_ok_buy = trend_up and _momentum_buy_ok
                if _synthetic_range:
                    # Brak zakresu AI — wejście tylko przy pełnym potwierdzeniu trend-following
                    if _trend_ok_buy and rsi_ok:
                        side = "BUY"
                        reasons = [f"Trend wzrostowy ({_trend_reason_up})", "RSI potwierdza", "ADX i wolumen potwierdzają", "Wejście fallback (brak strefy AI)"]
                elif r.get("buy_low") is not None and r.get("buy_high") is not None:
                    buy_low_tol = float(r.get("buy_low")) * (1 - price_tolerance)
                    buy_high_tol = float(r.get("buy_high")) * (1 + price_tolerance)
                    in_range = buy_low_tol <= price <= buy_high_tol
                    if in_range and _trend_ok_buy and rsi_ok:
                        side = "BUY"
                        reasons = [f"Trend wzrostowy ({_trend_reason_up})", "RSI potwierdza", "ADX i wolumen potwierdzają", "Cena w zakresie BUY (AI)"]
                    elif demo_allow_soft_buy and _trend_ok_buy and rsi_ok and not in_range:
                        # Soft entry: tylko przy pełnym potwierdzeniu trend-following
                        rsi_val = float(rsi) if rsi is not None else 50.0
                        if rsi_val < 55.0:
                            side = "BUY"
                            reasons = [f"Trend wzrostowy ({_trend_reason_up})", "RSI potwierdza", "ADX i wolumen potwierdzają", "Wejście miękkie — cena poza zakresem AI, ale setup silny"]
            elif sig.signal_type == "SELL":
                # W reżimie CRASH/BEAR: obniż RSI gate dla SELL
                # RSI=28-35 jest "wyprzedany" ale rynek nadal spada — SELL jest prawidłowy
                _rsi_sell_min = rsi_sell_gate  # domyślnie 35
                if market_regime.get("buy_blocked"):
                    _rsi_sell_min = float(config.get("bear_rsi_sell_gate", 20.0))
                rsi_ok_sell = rsi is not None and float(rsi) >= _rsi_sell_min
                if _synthetic_range:
                    if trend_down and rsi_ok_sell and _momentum_sell_ok:
                        side = "SELL"
                        reasons = [f"Trend spadkowy ({_trend_reason_down})", "RSI potwierdza", "ADX potwierdza", "Wyjście fallback (brak strefy AI)"]
                elif r.get("sell_low") is not None and r.get("sell_high") is not None:
                    sell_low_tol = float(r.get("sell_low")) * (1 - price_tolerance)
                    sell_high_tol = float(r.get("sell_high")) * (1 + price_tolerance)
                    if (
                        sell_low_tol <= price <= sell_high_tol
                        and trend_down
                        and rsi_ok_sell
                        and _momentum_sell_ok
                    ):
                        side = "SELL"
                        reasons = [f"Trend spadkowy ({_trend_reason_down})", "RSI potwierdza", "ADX potwierdza", "Cena w zakresie SELL (AI)"]

            if side is None:
                # Diagnostyka: które konkretnie filtry zawiodły
                _filter_fails: list[str] = []
                if sig.signal_type == "BUY":
                    bl = r.get("buy_low"); bh = r.get("buy_high")
                    if bl is not None and bh is not None:
                        buy_low_tol = float(bl) * (1 - price_tolerance)
                        buy_high_tol = float(bh) * (1 + price_tolerance)
                        if not (buy_low_tol <= price <= buy_high_tol):
                            _filter_fails.append(f"cena {round(price,4)} poza strefą BUY [{round(buy_low_tol,4)}–{round(buy_high_tol,4)}]")
                    elif _synthetic_range:
                        _filter_fails.append("brak strefy AI (zakres syntetyczny)")
                    # Trend gate: EMA i/lub Supertrend
                    if not trend_up:
                        _ema_fail = f"EMA20({round(float(ema20),2)})≤EMA50({round(float(ema50),2)})" if (ema20 is not None and ema50 is not None) else "brak EMA"
                        _st_fail = f"Supertrend={supertrend_dir}" if supertrend_dir is not None else "brak Supertrend"
                        _filter_fails.append(f"trend spadkowy: {_ema_fail}, {_st_fail}")
                    if rsi is not None and float(rsi) > rsi_buy_gate:
                        _filter_fails.append(f"RSI({round(float(rsi),1)}) > próg kupna {round(rsi_buy_gate,1)}")
                elif sig.signal_type == "SELL":
                    sl = r.get("sell_low"); sh = r.get("sell_high")
                    if sl is not None and sh is not None:
                        sell_low_tol = float(sl) * (1 - price_tolerance)
                        sell_high_tol = float(sh) * (1 + price_tolerance)
                        if not (sell_low_tol <= price <= sell_high_tol):
                            _filter_fails.append(f"cena {round(price,4)} poza strefą SELL [{round(sell_low_tol,4)}–{round(sell_high_tol,4)}]")
                    elif _synthetic_range:
                        _filter_fails.append("brak strefy AI (zakres syntetyczny)")
                    if not trend_down:
                        _ema_fail = f"EMA20({round(float(ema20),2)})≥EMA50({round(float(ema50),2)})" if (ema20 is not None and ema50 is not None) else "brak EMA"
                        _st_fail = f"Supertrend={supertrend_dir}" if supertrend_dir is not None else "brak Supertrend"
                        _filter_fails.append(f"trend wzrostowy: {_ema_fail}, {_st_fail}")
                    if rsi is not None and float(rsi) < _rsi_sell_min:
                        _filter_fails.append(f"RSI({round(float(rsi),1)}) < próg sprzedaży {round(_rsi_sell_min,1)}{' (CRASH: obniżony)' if _rsi_sell_min < rsi_sell_gate else ''}")
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="signal_filters_not_met",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check={"ema20": ema20, "ema50": ema50, "rsi": rsi,
                                "rsi_buy_gate": rsi_buy_gate, "rsi_sell_gate": rsi_sell_gate,
                                "current_price": price, "signal_type": sig.signal_type},
                    details={"range": r, "filter_fails": _filter_fails},
                )
                continue

            plan_action = str(plan.get("action") or "WAIT").upper()
            if side == "BUY" and plan_action not in {"BUY"}:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="plan_action_blocks_entry",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    snapshot=snapshot, plan=plan,
                    cost_check={"eligible": False, "plan_action": plan_action, "expected_net_profit": plan.get("expected_net_profit")},
                )
                continue
            if side == "SELL" and plan_action not in {"SELL", "REDUCE"}:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="plan_action_blocks_exit",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    snapshot=snapshot, plan=plan,
                    cost_check={"eligible": False, "plan_action": plan_action, "expected_net_profit": plan.get("expected_net_profit")},
                )
                continue

            if side == "BUY" and position is not None:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="buy_blocked_existing_position",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                )
                continue
            if side == "SELL" and position is None:
                # P2-03: SELL signal bez otwartej pozycji — pomijamy cicho.
                # reason_code: sell_blocked_no_position (zachowane dla wstecznej kompatybilności narzędzi diagnostycznych)
                # Sygnał jest już persisted w tabeli Signal przez generate_market_insights.
                # Nie tworzymy SKIP trace — eliminujemy 90%+ szumu w decision_traces.
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
            qty = qty * max(0.2, 1 - (loss_streak * 0.15)) * (1 + min(win_streak * 0.05, 0.2))
            if crash:
                qty = max(base_qty * 0.1, qty * 0.25)
            if side == "SELL" and position is not None:
                qty = min(float(position.quantity), qty)
            if side == "BUY":
                if price > 0:
                    # Ogranicz do max_cash_pct_per_trade (domyślnie 1/max_open_positions)
                    # Zapobiega wydaniu całej gotówki na jeden trade
                    max_open = tc.get("max_open_positions", 3)
                    max_cash_pct = float(config.get("max_cash_pct_per_trade", 1.0 / max(max_open, 1)))
                    max_cash_for_trade = available_cash * max_cash_pct
                    # Gdy pct-cap daje mniej niż min_order_notional, ale jest dość gotówki —
                    # pozwól na min_order_notional (minimum viable trade nadrzędne nad pct cap).
                    # Zapobiega blokadom przy niskim saldzie + wielu maksymalnych pozycjach.
                    if max_cash_for_trade < min_order_notional and available_cash >= min_order_notional:
                        max_cash_for_trade = min_order_notional
                    # Odlicz prowizję od dostępnych środków (entry + exit fee)
                    _taker = float(config.get("taker_fee_rate", 0.001))
                    max_cash_after_fees = max_cash_for_trade / (1 + _taker)
                    max_affordable = max_cash_after_fees / float(price)
                    qty = min(qty, max_affordable)
                    # Podnieś do min_order_notional gdy ATR-sizing daje za małą kwotę
                    # (np. BTC: ryzyko 10 EUR / ATR 1000 EUR = 0.01 BTC = poniżej min)
                    # UWAGA: max_cash_after_fees = max_cash_for_trade / (1+fee) < min_order_notional
                    # nawet gdy max_cash_for_trade = min_order_notional — sprawdzamy max_cash_for_trade.
                    if qty * price < min_order_notional and max_cash_for_trade >= min_order_notional:
                        qty = min_order_notional / float(price)
                if qty < min_qty:
                    self._trace_decision(
                        db, symbol=symbol, action="SKIP", reason_code="insufficient_cash_or_qty_below_min",
                        runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                        execution_check={"eligible": False, "available_cash": available_cash, "min_qty": min_qty},
                    )
                    continue

            # Rating decyzji 1-5 (EMA + Supertrend + ADX + Wolumen + RSI + Confidence)
            rating = 1
            if float(sig.confidence) >= 0.75:
                rating += 1
            if float(sig.confidence) >= 0.85:
                rating += 1
            # EMA trend bonus
            if (side == "BUY" and _ema_trend_up) or (side == "SELL" and _ema_trend_down):
                rating += 1
            # Supertrend bonus — niezależny od EMA (podwójne potwierdzenie np. EMA+ST = 5/5)
            if (side == "BUY" and _st_up) or (side == "SELL" and _st_down):
                rating += 1
            # RSI bonus
            if rsi is not None:
                if (side == "BUY" and float(rsi) <= float(rsi_buy or 50)) or (side == "SELL" and float(rsi) >= float(rsi_sell or 50)):
                    rating += 1
            # ADX bonus: silny ruch kierunkowy ≥ 25
            if adx_val is not None and float(adx_val) >= 25:
                rating += 1
            # Wolumen bonus: ponadprzeciętny wolumen potwierdza breakout
            if volume_ratio is not None and float(volume_ratio) >= 1.3:
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
                sell_edge = sell_high_v - (sell_high_v - sell_low_v) * extreme_margin_pct
                if side == "BUY" and price <= buy_edge:
                    is_extreme = True
                if side == "SELL" and price >= sell_edge:
                    is_extreme = True

            if is_extreme:
                # Premia: idealne wejście → +1 do ratingu
                rating = min(5, rating + 1)

            # Bramka jakości wejścia — odrzuć słabe sygnały
            # demo_min_entry_score jest w skali wait-status (0-12+), rating w skali 1-5.
            # Przeliczenie: ≤5 → min_rating 1; 5-6 → 2; 6-8 → 3; 8-10 → 4; ≥10 → 5
            _score_thresh = float(demo_min_entry_score)
            if _score_thresh < 5.0:
                _min_rating = 1
            elif _score_thresh < 6.0:
                _min_rating = 2
            elif _score_thresh < 8.0:
                _min_rating = 3
            elif _score_thresh < 10.0:
                _min_rating = 4
            else:
                _min_rating = 5
            if rating < _min_rating:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="entry_score_below_min",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check={"rating": rating, "min_rating": _min_rating, "min_entry_score": demo_min_entry_score},
                )
                continue

            expected_move_ratio = (float(atr) * atr_take_mult) / float(price) if price > 0 else 0.0
            total_cost_ratio = (2 * taker_fee_rate) + (2 * slippage_bps / 10000.0) + (2 * spread_buffer_bps / 10000.0)
            # Tier override: wyższy min_edge_multiplier
            effective_edge_mult = min_edge_multiplier + tier_edge_add
            required_move_ratio = total_cost_ratio * effective_edge_mult
            # PROFIT-FIX: wymagamy też oczekiwanego RR >= min_expected_rr (domyślnie 1.5)
            # i ATR% >= min_atr_pct (filtr powtórzony tu dla cost_check diagnostyki)
            _atr_pct = float(atr) / float(price) if price and float(price) > 0 else 0.0
            cost_gate_pass = (
                expected_move_ratio >= required_move_ratio
                and atr_take_mult / max(atr_stop_mult, 1e-9) >= min_expected_rr
                and _atr_pct >= _min_atr_pct
            )
            notional = float(price) * float(qty)

            cost_check = {
                "eligible": cost_gate_pass,
                "expected_move_ratio": expected_move_ratio,
                "required_move_ratio": required_move_ratio,
                "total_cost_ratio": total_cost_ratio,
                "plan_expected_net_profit": plan.get("expected_net_profit"),
                "plan_break_even_price": plan.get("break_even_price"),
                "maker_fee_rate": maker_fee_rate,
                "taker_fee_rate": taker_fee_rate,
                "slippage_bps": slippage_bps,
                "spread_buffer_bps": spread_buffer_bps,
                "min_edge_multiplier": effective_edge_mult,
                "tier": tier_name,
            }
            execution_check = {
                "eligible": notional >= min_order_notional - 0.01,
                "notional": notional,
                "min_order_notional": min_order_notional,
            }
            risk_context = build_risk_context(
                db, symbol=symbol, side=side, notional=notional,
                strategy_name="demo_collector", mode=_current_mode,
                runtime_config=config,
                config_snapshot_id=runtime_ctx.get("snapshot_id"),
                signal_summary=signal_summary,
            )
            risk_decision = evaluate_risk(risk_context)
            risk_check = risk_decision.to_dict()

            if not risk_decision.allowed:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP",
                    reason_code=risk_decision.reason_codes[0],
                    runtime_ctx=runtime_ctx, mode=_current_mode,
                    signal_summary=signal_summary, risk_check=risk_check,
                    snapshot=snapshot, plan=plan,
                )
                continue

            qty = qty * float(risk_decision.position_size_multiplier or 1.0)
            notional = float(price) * float(qty)
            execution_check["notional"] = notional
            execution_check["eligible"] = notional >= min_order_notional - 0.01

            if not cost_gate_pass:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="cost_gate_failed",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check=risk_check, cost_check=cost_check, execution_check=execution_check,
                    snapshot=snapshot, plan=plan,
                )
                continue

            if not execution_check["eligible"]:
                self._trace_decision(
                    db, symbol=symbol, action="SKIP", reason_code="min_notional_guard",
                    runtime_ctx=runtime_ctx, mode=_current_mode, signal_summary=signal_summary,
                    risk_check=risk_check, cost_check=cost_check, execution_check=execution_check,
                    snapshot=snapshot, plan=plan,
                )
                continue

            # Zbierz kandydata — pending i Telegram po sortowaniu
            tp = float(plan.get("take_profit_price") or (price + float(atr) * atr_take_mult))
            sl = float(plan.get("stop_loss_price") or (price - float(atr) * atr_stop_mult))
            why = ", ".join(reasons) if reasons else "Sygnał + zakresy OpenAI + filtry ryzyka"
            edge_net_score = expected_move_ratio - total_cost_ratio

            # P2-01: HTF (4h) alignment — soft penalty/bonus na composite_score, NIE blokuje wejścia.
            # BUY zgodny z 4h wzrostem: +10% ranking.  BUY contra 4h spadkowi: -20% ranking.
            # Dane 4h pobiez z TTL cache (55s) — koszt = 0 przy ciepłym cache.
            htf_align_factor = 1.0
            htf_align_note = "4h:brak_danych"
            try:
                _ctx_4h = get_live_context(db, symbol, timeframe="4h", limit=100)
                if _ctx_4h:
                    _ema20_4h = _ctx_4h.get("ema_20")
                    _ema50_4h = _ctx_4h.get("ema_50")
                    if _ema20_4h is not None and _ema50_4h is not None:
                        _4h_bull = float(_ema20_4h) > float(_ema50_4h)
                        _4h_bear = float(_ema20_4h) < float(_ema50_4h)
                        if side == "BUY":
                            if _4h_bull:
                                htf_align_factor = 1.10
                                htf_align_note = "4h:bycze(+10%)"
                            elif _4h_bear:
                                htf_align_factor = 0.80
                                htf_align_note = "4h:niedz(-20%)"
                        elif side == "SELL":
                            if _4h_bear:
                                htf_align_factor = 1.10
                                htf_align_note = "4h:niedz(+10%)"
                            elif _4h_bull:
                                htf_align_factor = 0.80
                                htf_align_note = "4h:bycze(-20%)"
            except Exception:
                pass
            signal_summary["htf_4h_align"] = htf_align_note

            # composite_score = edge × pewność × jakość techniczna (rating/5) × HTF alignment (4h)
            # Odzwierciedla: wysoki edge + wysoką pewność + silne potwierdzenia 1h + zgodność kierunku 4h
            composite_score = edge_net_score * float(sig.confidence) * (rating / 5.0) * htf_align_factor
            candidates.append({
                "symbol": symbol, "side": side, "price": price, "qty": qty,
                "tp": tp, "sl": sl, "rating": rating, "why": why,
                "signal_summary": signal_summary, "risk_check": risk_check,
                "cost_check": cost_check, "execution_check": execution_check,
                "range": r, "tier_name": tier_name,
                "confidence": float(sig.confidence),
                "edge_net_score": edge_net_score,
                "composite_score": composite_score,
                "htf_align_note": htf_align_note,
                "htf_align_factor": htf_align_factor,
                "atr": float(atr),
                "snapshot": snapshot,
                "plan": plan,
            })

        # --- Ranking kandydatów: sortuj po composite_score (edge × confidence × rating/5) ---
        candidates.sort(key=lambda c: c["composite_score"], reverse=True)
        max_new = max(1, tc["max_open_positions"] - len(tc.get("positions", [])))
        entries_created = 0

        for cand in candidates[:max_new]:
            symbol = cand["symbol"]
            side = cand["side"]
            price = cand["price"]
            qty = cand["qty"]
            tp = cand["tp"]
            sl = cand["sl"]
            rating = cand["rating"]
            why = cand["why"]
            tier_name = cand["tier_name"]
            signal_summary = cand["signal_summary"]
            risk_check = cand["risk_check"]
            cost_check = cand["cost_check"]
            execution_check = cand["execution_check"]
            snapshot = cand["snapshot"]
            plan = cand["plan"]
            r = cand["range"]
            action_pl = "KUP" if side == "BUY" else "SPRZEDAJ"

            # Re-check dostępnej gotówki (available_cash był współdzielony podczas screeningu)
            if side == "BUY" and price > 0:
                current_max_affordable = available_cash / float(price)
                if current_max_affordable < min_qty:
                    self._trace_decision(
                        db, symbol=symbol, action="SKIP",
                        reason_code="insufficient_cash_or_qty_below_min",
                        runtime_ctx=runtime_ctx, mode=_current_mode,
                        signal_summary=signal_summary,
                        execution_check={"eligible": False, "available_cash": available_cash, "min_qty": min_qty},
                    )
                    continue
                qty = min(qty, current_max_affordable)

            self._trace_decision(
                db, symbol=symbol,
                action="CREATE_PENDING_ENTRY" if side == "BUY" else "CREATE_PENDING_EXIT",
                reason_code="all_gates_passed",
                runtime_ctx=runtime_ctx, mode=_current_mode,
                signal_summary=signal_summary, risk_check=risk_check,
                cost_check=cost_check, execution_check=execution_check,
                snapshot=snapshot, plan=plan,
                details={
                    "side": side, "qty": qty, "price": price, "rating": rating,
                    "why": why, "tier": tier_name,
                    "edge_net_score": cand["edge_net_score"],
                    "composite_score": cand["composite_score"],
                    "range_origin": r.get("origin", "unknown") if r else "no_range",
                    "htf_bias_4h": cand.get("htf_align_note", "4h:brak_danych"),
                    "htf_4h_mult": cand.get("htf_align_factor", 1.0),
                    "rank": candidates.index(cand) + 1,
                    "total_candidates": len(candidates),
                    "auto_execute": not demo_require_manual_confirm,
                },
            )
            pending_id = self._create_pending_order(
                db=db, symbol=symbol, side=side, price=price, qty=qty,
                mode=_current_mode,
                reason=f"{why}. Pewność {int(cand['confidence']*100)}%, rating {rating}/5.",
                config_snapshot_id=runtime_ctx.get("snapshot_id"),
                strategy_name="demo_collector",
                # T-08: typ zlecenia z konfiguracji (MARKET/LIMIT) — tylko dla BUY entries LIVE
                # SELL exits zawsze MARKET (czas > koszt przy wychodzeniu)
                order_type=tc.get("live_entry_order_type", "MARKET") if _current_mode == "live" and side == "BUY" else "MARKET",
                decision_plan=plan,
            )

            # Auto-confirm + auto-execute gdy demo_require_manual_confirm=False
            if not demo_require_manual_confirm:
                try:
                    pending_obj = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
                    if pending_obj:
                        pending_obj.status = "CONFIRMED"
                        pending_obj.confirmed_at = now
                        db.flush()
                except Exception as exc_confirm:
                    log_exception("demo_trading", "Błąd auto-confirm pending", exc_confirm, db=db)

            if side == "BUY":
                try:
                    available_cash = max(0.0, float(available_cash) - (float(price) * float(qty)))
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
                confirm_block = "\n✅ Auto-potwierdzone — pozycja otwarta automatycznie."
                alert_title = f"{_mode_label}: OTWARTO POZYCJĘ"
            rank_info = f"Kandydat #{candidates.index(cand) + 1}/{len(candidates)}"
            conf_pct = int(cand['confidence'] * 100)
            edge_score = cand.get('edge_net_score', 0)
            composite = cand.get('composite_score', 0)
            htf_note = cand.get('htf_align_note', '')
            msg = (
                f"{action_emoji} [{_mode_label}] {alert_title}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol: {symbol} [{tier_name}]\n"
                f"Akcja: {action_pl}\n"
                f"Cena: {price}\n"
                f"TP: {tp:.6f} | SL: {sl:.6f}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Pewność: {conf_pct}% | Ocena: {rating}/5 | Edge: {edge_score:.4f} | Q: {composite:.4f}\n"
                f"HTF: {htf_note}\n"
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
                    message=f"{'Auto-wykonano' if not demo_require_manual_confirm else 'Pending'} ID {pending_id}. {side} {symbol} qty={qty} price={price}. {why}.",
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
            state = self.demo_state.get(sym, {"loss_streak": 0, "cooldown": base_cooldown})
            state["loss_streak"] = min(int(state.get("loss_streak", 0)) + 1, loss_streak_limit)
            state["cooldown"] = min(base_cooldown * (1 + int(state["loss_streak"])), 3600)
            self.demo_state[sym] = state
        msg = "🟠 Dzienny limit straty osiągnięty\nSystem ograniczył ryzyko na wszystkich symbolach.\nBot nadal działa, ale nowe transakcje są wstrzymane.\nCo zrobić: poczekaj na następny dzień lub przejrzyj otwarte pozycje."
        log_to_db("WARNING", "demo_trading", msg, db=db)
        self._send_telegram_alert("RISK: Daily loss", msg, force_send=True)

    def _detect_crash(self, db: Session, symbol: str, window_minutes: int, drop_pct: float) -> bool:
        """
        Wykryj gwałtowny spadek w krótkim oknie na live danych.
        """
        since = utc_now_naive() - timedelta(minutes=window_minutes)
        klines = db.query(Kline).filter(
            Kline.symbol == symbol,
            Kline.timeframe == "1m",
            Kline.open_time >= since
        ).order_by(Kline.open_time).all()
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
                        timestamp=utc_now_naive()
                    )
                    db.add(market_data)
                    
                    logger.info(f"✅ {symbol}: ${ticker['last_price']:.2f} "
                              f"({ticker['price_change_percent']:+.2f}%)")
                else:
                    logger.warning(f"⚠️  Failed to get ticker for {symbol}")
                    log_to_db("WARNING", "collector", f"Brak tickera dla {symbol}", db=db)
                
                # Rate limiting - nie bombardujemy API
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"❌ Error collecting data for {symbol}: {str(e)}")
                log_exception("collector", f"Błąd collect_market_data dla {symbol}", e, db=db)
        
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
                            
                            existing = db.query(Kline).filter(
                                Kline.symbol == symbol,
                                Kline.timeframe == timeframe,
                                Kline.open_time == open_time
                            ).first()
                            
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
                                    taker_buy_quote=k["taker_buy_quote"]
                                )
                                db.add(kline)
                                saved_count += 1
                        
                        if saved_count > 0:
                            logger.info(f"✅ {symbol} {timeframe}: saved {saved_count} new klines")
                    else:
                        logger.warning(f"⚠️  Failed to get klines for {symbol} {timeframe}")
                        log_to_db("WARNING", "collector", f"Brak klines {symbol} {timeframe}", db=db)
                    
                    # Rate limiting
                    time.sleep(0.2)
                    
                except Exception as e:
                    logger.error(f"❌ Error collecting klines for {symbol} {timeframe}: {str(e)}")
                    log_exception("collector", f"Błąd collect_klines dla {symbol} {timeframe}", e, db=db)
        
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
                if not self.last_openai_missing_log_ts or (now - self.last_openai_missing_log_ts).total_seconds() > 300:
                    self.last_openai_missing_log_ts = now
                    msg = "Brak kluczy AI (Gemini/Groq/OpenAI) — AI_PROVIDER=auto → heurystyka ATR/Bollinger."
                    logger.warning(f"⚠️ {msg}")
                    log_to_db("WARNING", "collector", msg, db=db)

            # Zrealizuj zatwierdzone transakcje (DEMO) zanim policzysz kolejne decyzje.
            try:
                self._execute_confirmed_pending_orders(db)
            except Exception as exc:
                log_exception("collector", "Błąd wykonania potwierdzonych transakcji", exc, db=db)

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
                    log_to_db("INFO", "collector", f"Watchlist override: {old} -> {new}", db=db)
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
            if not self.last_learning_ts or (now - self.last_learning_ts).seconds > 3600:
                self._learn_from_history(db)
                self.last_learning_ts = now

            # Retencja danych — zapobiega przepełnieniu dysku
            self._purge_stale_data(db)

            # Zbierz dane rynkowe
            self.collect_market_data(db)

            # Mark-to-market pozycji + snapshoty KPI (DEMO + LIVE)
            self._mark_to_market_positions(db, mode="demo")
            self._mark_to_market_positions(db, mode="live")
            self._persist_demo_snapshot_if_due(db)

            # Sync pozycji LIVE DB ↔ Binance (co 5 min)
            try:
                now_sync = utc_now_naive()
                if not self._last_binance_sync_ts or (now_sync - self._last_binance_sync_ts).total_seconds() > 300:
                    self._sync_binance_positions(db)
                    self._last_binance_sync_ts = now_sync
            except Exception as exc:
                log_exception("collector", "Błąd sync Binance", exc, db=db)

            # Monitor LIVE LIMIT BUY przed generowaniem nowych wejść, aby uniknąć dubli.
            try:
                self._monitor_limit_orders(db, runtime_ctx=self._runtime_context(db))
            except Exception as exc:
                log_exception("collector", "Błąd monitoringu LIMIT orders", exc, db=db)

            # Generuj sygnały heurystyczne co cykl (do DB dla collectora)
            try:
                from backend.analysis import generate_market_insights, _heuristic_ranges, _merge_ranges_with_insights, persist_insights_as_signals
                insights = generate_market_insights(db, self.watchlist, timeframe="1h")
                if insights:
                    ranges = _heuristic_ranges(insights)
                    insights = _merge_ranges_with_insights(insights, ranges)
                    persist_insights_as_signals(db, insights)
            except Exception as exc:
                log_exception("collector", "Błąd generacji sygnałów heurystycznych", exc, db=db)


            # Zbierz świece
            self.collect_klines(db)

            # Analiza + blog (co najmniej raz na godzinę)
            maybe_generate_insights_and_blog(db, self.watchlist)

            # DEMO trading
            self._demo_trading(db, mode="demo")

            # Zapisz demo_state do DB (cooldowny i streaki przeżywają restart)
            try:
                self._save_demo_state(db)
            except Exception as exc:
                log_exception("collector", "Błąd zapisu demo_state", exc, db=db)

            # LIVE trading (równoległe z demo)
            try:
                self._demo_trading(db, mode="live")
            except Exception as exc:
                log_exception("collector", "Błąd cyklu LIVE trading", exc, db=db)

            # Wykonaj auto-confirmed transakcje (demo + live)
            try:
                self._execute_confirmed_pending_orders(db)
            except Exception as exc:
                log_exception("collector", "Błąd wykonania auto-confirmed transakcji", exc, db=db)

            try:
                self._monitor_limit_orders(db, runtime_ctx=self._runtime_context(db))
            except Exception as exc:
                log_exception("collector", "Błąd końcowego monitoringu LIMIT orders", exc, db=db)

            # Sprawdź trafność prognoz (co cykl — szybkie)
            try:
                self._check_forecast_accuracy(db)
            except Exception as exc:
                log_exception("collector", "Błąd weryfikacji trafności prognoz", exc, db=db)
            
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
            .filter(ForecastRecord.checked == False, ForecastRecord.target_ts <= now)  # noqa: E712
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
                    rec.error_pct = abs((actual - rec.forecast_price) / rec.forecast_price) * 100
                    if rec.direction and rec.current_price_at_forecast:
                        expected_up = rec.direction == "WZROST"
                        actual_up = actual >= rec.current_price_at_forecast
                        rec.correct_direction = (expected_up == actual_up) if rec.direction != "BOCZNY" else None
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
        if hasattr(self, "_last_purge_ts") and self._last_purge_ts and (now - self._last_purge_ts).total_seconds() < 3600:
            return
        self._last_purge_ts = now

        purge_specs = [
            ("market_data", "timestamp", timedelta(days=2)),   # tick data — 2 dni wystarczy; klines(30d) ma historię
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
                        text(f"DELETE FROM {table} WHERE id IN "
                             f"(SELECT id FROM {table} WHERE {ts_col} < :cutoff LIMIT :batch)"),
                        {"cutoff": cutoff, "batch": self._PURGE_BATCH}
                    )
                    db.commit()
                    deleted = result.rowcount
                    if deleted == 0:
                        break
                    batch_total += deleted
                if batch_total:
                    log_to_db("INFO", "collector", f"Retencja: usunięto {batch_total} starych wierszy {table}", db=db)
                    total_deleted += batch_total
            except Exception as exc:
                log_exception("collector", f"Błąd retencji {table}", exc, db=db)
                db.rollback()

        # Wygasanie starych pending orders (>24h)
        try:
            cutoff_pending = now - timedelta(hours=24)
            expired = (
                db.query(PendingOrder)
                .filter(PendingOrder.status == "PENDING", PendingOrder.created_at < cutoff_pending)
                .update({"status": "EXPIRED"}, synchronize_session=False)
            )
            if expired:
                log_to_db("INFO", "collector", f"Retencja: oznaczono {expired} starych pending orders jako EXPIRED (>24h)", db=db)
            db.commit()
        except Exception as exc:
            log_exception("collector", "Błąd retencji pending_orders", exc, db=db)
            db.rollback()

        # VACUUM — odzyskuje miejsce na dysku po dużym czyszczeniu
        if total_deleted > 1000:
            try:
                db.commit()
                db.execute(text("VACUUM"))
                log_to_db("INFO", "collector", f"VACUUM po usunięciu {total_deleted} wierszy", db=db)
            except Exception:
                pass  # VACUUM nie jest krytyczny

        # WAL checkpoint PASSIVE — co godzinę przenosi zacommitowane strony WAL → main DB
        # Nie blokuje aktywnych czytelników; zapobiega narastaniu pliku WAL do setek MB.
        try:
            db.commit()
            result = db.execute(text("PRAGMA wal_checkpoint(PASSIVE)")).fetchone()
            if result:
                busy, total_wal, moved = result
                if total_wal > 500:  # wiele stron oczekujących — loguj jako info
                    log_to_db("INFO", "collector",
                               f"WAL checkpoint PASSIVE: busy={busy}, wal={total_wal}, moved={moved}", db=db)
        except Exception:
            pass  # checkpoint nie jest krytyczny

    def _learn_from_history(self, db: Session):
        """Prosta kalibracja parametrów na historii (konserwatywna)."""
        report_lines = []
        for symbol in self.watchlist:
            since = utc_now_naive() - timedelta(days=self.learning_days)
            klines = db.query(Kline).filter(
                Kline.symbol == symbol,
                Kline.timeframe == "1h",
                Kline.open_time >= since
            ).order_by(Kline.open_time).all()
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
            vol = var ** 0.5

            # Trend strength estimate
            ema20 = sum(prices[-20:]) / 20
            ema50 = sum(prices[-50:]) / 50
            trend_strength = abs(ema20 - ema50) / max(prices[-1], 1e-9)

            # Conservative tuning
            base_conf = 0.55
            conf = min(0.72, base_conf + min(0.12, vol * 2) + (0.05 if trend_strength < 0.002 else 0))
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
            log_to_db("INFO", "learning", f"Kalibracja na {self.learning_days} dni: " + " | ".join(report_lines), db=db)
            # Persystuj symbol_params do RuntimeSetting (klucz learning_symbol_params)
            try:
                import json as _json
                from backend.runtime_settings import upsert_overrides
                upsert_overrides(db, {"learning_symbol_params": _json.dumps(self.symbol_params)})
            except Exception as _exc:
                log_exception("learning", "Błąd persistowania symbol_params", _exc, db=db)
            # Nie wysyłamy automatycznych raportów uczenia na Telegram (tylko na żądanie)

    def _ws_streams(self) -> str:
        streams = []
        for symbol in self.watchlist:
            s = symbol.lower()
            streams.append(f"{s}@ticker")
            streams.append(f"{s}@kline_1m")
            streams.append(f"{s}@kline_1h")
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
                log_exception("collector_ws", f"Błąd zapisu tickera {symbol}", exc, db=db)
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
                log_exception("collector_ws", f"Błąd zapisu kline {symbol} {timeframe}", exc, db=db)
                db.rollback()
            finally:
                db.close()

    async def _ws_loop(self):
        while self.ws_running:
            streams = self._ws_streams()
            if not streams:
                await asyncio.sleep(2)
                continue
            url = f"wss://stream.binance.com:9443/stream?streams={streams}"
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    log_to_db("INFO", "collector_ws", f"Połączono z Binance WS ({len(self.watchlist)} symboli)")
                    logger.info(f"📡 WS connected ({len(self.watchlist)} symboli)")
                    self.ws_backoff_seconds = 2

                    while self.ws_running:
                        raw = await ws.recv()
                        msg = json.loads(raw)
                        await self._handle_ws_message(msg)
            except Exception as exc:
                log_exception("collector_ws", "Błąd połączenia WS - reconnect", exc)
                await asyncio.sleep(self.ws_backoff_seconds)
                self.ws_backoff_seconds = min(self.ws_backoff_seconds * 2, 60)

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
