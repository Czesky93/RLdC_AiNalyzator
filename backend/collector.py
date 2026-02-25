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
from datetime import datetime, timedelta
from typing import List, Optional
from dotenv import load_dotenv
import logging
import websockets
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import SessionLocal, MarketData, Kline, Order, Position, Alert, Signal, PendingOrder, AccountSnapshot
from backend.binance_client import get_binance_client
from backend.system_logger import log_to_db, log_exception
from backend.analysis import maybe_generate_insights_and_blog, get_live_context
from backend.accounting import compute_demo_account_state, get_demo_quote_ccy
from backend.runtime_settings import effective_bool, watchlist_override
import requests

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)

# Python 3.12+ może emitować DeprecationWarning dla datetime.utcnow().
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
        self.last_crash_alert_ts: Optional[datetime] = None
        self.last_report_ts: Optional[datetime] = None
        self.last_openai_missing_log_ts: Optional[datetime] = None
        self.last_stale_ai_log_ts: Optional[datetime] = None
        self.learning_days = int(os.getenv("LEARNING_DAYS", "180"))
        self.last_learning_ts: Optional[datetime] = None
        self.symbol_params = {}
        self.last_snapshot_ts: Optional[datetime] = None
        
        logger.info(f"📊 DataCollector initialized")
        logger.info(f"   Watchlist: {', '.join(self.watchlist)}")
        logger.info(f"   Interval: {self.interval}s")
        logger.info(f"   Timeframes: {', '.join(self.kline_timeframes)}")
    
    def _load_watchlist(self) -> List[str]:
        """Wczytaj listę symboli do śledzenia"""
        quotes = [q.strip().upper() for q in os.getenv("PORTFOLIO_QUOTES", "EUR,USDC").split(",") if q.strip()]
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
        if resolved:
            return sorted(resolved)

        # Fallback: stała watchlista z `.env` (działa nawet bez kluczy Binance).
        raw_watchlist = os.getenv("WATCHLIST", "")
        if not raw_watchlist.strip():
            return []

        items = [s.strip() for s in raw_watchlist.split(",") if s.strip()]
        fallback: List[str] = []
        for item in items:
            resolved_symbol = self.binance.resolve_symbol(item)
            if not resolved_symbol:
                resolved_symbol = item.replace("/", "").strip().upper()
            if resolved_symbol and resolved_symbol not in fallback:
                fallback.append(resolved_symbol)
        return sorted(fallback)

    def _has_openai_key(self) -> bool:
        return os.getenv("OPENAI_API_KEY", "").strip() != ""

    def _log_openai_missing(self):
        now = datetime.utcnow()
        if self.last_openai_missing_log_ts and (now - self.last_openai_missing_log_ts).total_seconds() < 300:
            return
        self.last_openai_missing_log_ts = now
        msg = "Brak OPENAI_API_KEY — bot wstrzymany (OpenAI jest wymagany)."
        logger.error(f"⛔ {msg}")
        log_to_db("ERROR", "collector", msg)

    def _log_no_watchlist(self, db: Session, hint: Optional[str] = None):
        now = datetime.utcnow()
        if self.last_no_watchlist_log_ts and (now - self.last_no_watchlist_log_ts).total_seconds() < 300:
            return
        self.last_no_watchlist_log_ts = now
        msg = "Brak symboli z portfela Binance (Spot) — pomijam cykl i ponowię próbę."
        if hint:
            msg = f"{msg} {hint}"
        logger.warning(f"⚠️ {msg}")
        log_to_db("ERROR", "collector", msg, db=db)

    def _refresh_watchlist_if_due(self, db: Session, force: bool = False) -> bool:
        now = datetime.utcnow()
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

    def _create_pending_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        mode: str,
        reason: str,
    ) -> int:
        pending = PendingOrder(
            symbol=symbol,
            side=side,
            order_type="MARKET",
            price=price,
            quantity=qty,
            mode=mode,
            status="PENDING",
            reason=reason,
            created_at=datetime.utcnow(),
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

    def _execute_confirmed_pending_orders(self, db: Session):
        """
        Wykonaj potwierdzone transakcje (DEMO) zapisane jako PendingOrder.
        Telegram ustawia status=CONFIRMED; kolektor dokonuje symulacji i oznacza jako EXECUTED.
        """
        trading_mode = os.getenv("TRADING_MODE", "demo").lower()
        if trading_mode != "demo":
            return

        confirmed = (
            db.query(PendingOrder)
            .filter(PendingOrder.mode == "demo", PendingOrder.status == "CONFIRMED")
            .order_by(desc(PendingOrder.confirmed_at))
            .limit(50)
            .all()
        )
        if not confirmed:
            return

        executed_count = 0
        for pending in confirmed:
            try:
                # DEMO "market" execution at current price (fallback: saved price)
                exec_price = pending.price
                ticker = self.binance.get_ticker_price(pending.symbol)
                if ticker and ticker.get("price"):
                    exec_price = float(ticker["price"])
                qty = float(pending.quantity)

                order = Order(
                    symbol=pending.symbol,
                    side=pending.side,
                    order_type=pending.order_type,
                    price=pending.price,
                    quantity=qty,
                    status="FILLED",
                    mode="demo",
                    executed_price=exec_price,
                    executed_quantity=qty,
                    timestamp=datetime.utcnow(),
                )
                db.add(order)

                position = (
                    db.query(Position)
                    .filter(Position.symbol == pending.symbol, Position.mode == "demo")
                    .first()
                )

                if pending.side == "BUY":
                    if not position:
                        position = Position(
                            symbol=pending.symbol,
                            side="LONG",
                            entry_price=exec_price,
                            quantity=qty,
                            current_price=exec_price,
                            unrealized_pnl=0.0,
                            mode="demo",
                            opened_at=datetime.utcnow(),
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
                elif pending.side == "SELL":
                    if position and float(position.quantity) > 0:
                        sell_qty = min(float(position.quantity), qty)
                        position.quantity = float(position.quantity) - sell_qty
                        position.current_price = exec_price
                        position.unrealized_pnl = (exec_price - float(position.entry_price)) * float(position.quantity)
                        if float(position.quantity) <= 0:
                            db.delete(position)
                    else:
                        # Brak pozycji — zapisujemy zlecenie, ale bez zmian pozycji.
                        pass

                alert = Alert(
                    alert_type="SIGNAL",
                    severity="INFO",
                    title=f"DEMO EXEC {pending.side} {pending.symbol}",
                    message=f"{pending.side} {pending.symbol} qty={qty} exec_price={exec_price}. Powód: {pending.reason or '--'}",
                    symbol=pending.symbol,
                    is_sent=True,
                    timestamp=datetime.utcnow(),
                )
                db.add(alert)

                pending.status = "EXECUTED"
                if not pending.confirmed_at:
                    pending.confirmed_at = datetime.utcnow()

                executed_count += 1
            except Exception as exc:
                log_exception("demo_trading", f"Błąd wykonania pending order {pending.id}", exc, db=db)
                try:
                    pending.status = "REJECTED"
                    pending.confirmed_at = datetime.utcnow()
                except Exception:
                    pass

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_exception("demo_trading", "Błąd commit wykonania pending orders", exc, db=db)
            return

        if executed_count:
            logger.info(f"✅ Wykonano potwierdzone transakcje DEMO: {executed_count}")

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
                    if (p.side or "").upper() == "SHORT":
                        p.unrealized_pnl = (entry - price) * qty
                    else:
                        p.unrealized_pnl = (price - entry) * qty
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

        now = datetime.utcnow()
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

    def _demo_trading(self, db: Session):
        enabled = effective_bool(db, "demo_trading_enabled", "DEMO_TRADING_ENABLED", True)
        if not enabled:
            return

        trading_mode = os.getenv("TRADING_MODE", "demo").lower()
        if trading_mode != "demo":
            log_to_db("WARNING", "demo_trading", "TRADING_MODE != demo — demo trading wyłączony", db=db)
            return

        now = datetime.utcnow()
        demo_quote_ccy = get_demo_quote_ccy()
        account_state = compute_demo_account_state(db, quote_ccy=demo_quote_ccy, now=now)
        initial_balance = float(account_state.get("initial_balance") or float(os.getenv("DEMO_INITIAL_BALANCE", "10000")))
        cash = float(account_state.get("cash") or initial_balance)
        equity = float(account_state.get("equity") or cash)
        reserved_cash = 0.0
        try:
            active_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == "demo",
                    PendingOrder.side == "BUY",
                    PendingOrder.status.in_(["PENDING", "CONFIRMED"]),
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

        max_certainty_mode = effective_bool(db, "max_certainty_mode", "MAX_CERTAINTY_MODE", False)

        # Ustawienia (konserwatywne)
        max_daily_loss_pct = float(os.getenv("MAX_DAILY_LOSS_PERCENT", "5.0"))
        max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PERCENT", "10.0"))
        base_qty = float(os.getenv("DEMO_ORDER_QTY", "0.01"))
        base_cooldown = int(os.getenv("DEMO_COOLDOWN_SECONDS", "600"))
        max_trades_per_day = int(os.getenv("DEMO_MAX_TRADES_PER_DAY", "4"))
        base_min_confidence = float(os.getenv("DEMO_MIN_SIGNAL_CONFIDENCE", "0.75"))
        max_signal_age = int(os.getenv("DEMO_MAX_SIGNAL_AGE_SECONDS", "3600"))
        min_klines = int(os.getenv("DEMO_MIN_KLINES", "60"))

        crash_window_minutes = int(os.getenv("CRASH_WINDOW_MINUTES", "60"))
        crash_drop_pct = float(os.getenv("CRASH_DROP_PERCENT", "6.0"))
        crash_cooldown_seconds = int(os.getenv("CRASH_COOLDOWN_SECONDS", "7200"))

        base_risk_per_trade = float(os.getenv("DEMO_RISK_PER_TRADE", "0.005"))
        atr_stop_mult = float(os.getenv("ATR_STOP_MULT", "1.3"))
        atr_take_mult = float(os.getenv("ATR_TAKE_MULT", "2.2"))
        trail_mult = float(os.getenv("ATR_TRAIL_MULT", "1.0"))

        extreme_margin_pct = float(os.getenv("EXTREME_RANGE_MARGIN_PCT", "0.02"))
        extreme_min_conf = float(os.getenv("EXTREME_MIN_CONFIDENCE", "0.85"))
        extreme_min_rating = int(os.getenv("EXTREME_MIN_RATING", "4"))

        max_qty = float(os.getenv("DEMO_MAX_POSITION_QTY", "1.0"))
        min_qty = float(os.getenv("DEMO_MIN_POSITION_QTY", "0.001"))

        # Maksymalna pewność = mniej transakcji, wyższe progi, dłuższy cooldown.
        if max_certainty_mode:
            base_min_confidence = max(base_min_confidence, 0.9)
            extreme_min_conf = max(extreme_min_conf, 0.92)
            extreme_min_rating = max(extreme_min_rating, 5)
            extreme_margin_pct = min(extreme_margin_pct, 0.01)
            max_trades_per_day = min(max_trades_per_day, 1)
            base_cooldown = max(base_cooldown, 3600)
            base_risk_per_trade = min(base_risk_per_trade, 0.002)

        pending_cooldown_seconds = int(os.getenv("PENDING_ORDER_COOLDOWN_SECONDS", "3600"))
        now = datetime.utcnow()

        def _has_active_pending(sym: str) -> bool:
            return (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == "demo",
                    PendingOrder.symbol == sym,
                    PendingOrder.status.in_(["PENDING", "CONFIRMED"]),
                )
                .count()
                > 0
            )

        def _pending_in_cooldown(sym: str) -> bool:
            last = (
                db.query(PendingOrder)
                .filter(PendingOrder.mode == "demo", PendingOrder.symbol == sym)
                .order_by(PendingOrder.created_at.desc())
                .first()
            )
            if not last or not last.created_at:
                return False
            return (now - last.created_at).total_seconds() < float(pending_cooldown_seconds)

        # Zakresy z bloga (OpenAI) są wymagane — bez nich brak decyzji.
        range_map: dict[str, dict] = {}
        max_ai_age_seconds = int(os.getenv("MAX_AI_INSIGHTS_AGE_SECONDS", "7200"))
        try:
            from backend.database import BlogPost

            latest_blog = db.query(BlogPost).order_by(BlogPost.created_at.desc()).first()
            if latest_blog and latest_blog.created_at:
                age_s = (now - latest_blog.created_at).total_seconds()
                if age_s > max_ai_age_seconds:
                    if not self.last_stale_ai_log_ts or (now - self.last_stale_ai_log_ts).total_seconds() > 300:
                        self.last_stale_ai_log_ts = now
                        log_to_db(
                            "ERROR",
                            "demo_trading",
                            f"Zakresy AI są nieaktualne (ostatnia analiza {int(age_s)}s temu) — pomijam decyzje DEMO.",
                            db=db,
                        )
                    return
            if latest_blog and latest_blog.market_insights:
                insights = json.loads(latest_blog.market_insights)
                for ins in insights:
                    if ins.get("range") and ins.get("symbol"):
                        range_map[str(ins.get("symbol"))] = ins.get("range")
        except Exception as exc:
            log_exception("demo_trading", "Błąd odczytu zakresów OpenAI z bloga", exc, db=db)
            range_map = {}

        if not range_map:
            log_to_db("ERROR", "demo_trading", "Brak zakresów AI — pomijam decyzje DEMO", db=db)
            return

        # Ryzyko (dzienny limit + drawdown)
        since = now - timedelta(hours=24)
        positions_all = db.query(Position).filter(Position.mode == "demo").all()
        positions = [
            p
            for p in positions_all
            if (p.symbol or "").strip().upper().replace("/", "").replace("-", "").endswith(demo_quote_ccy)
        ]
        unrealized_pnl = float(account_state.get("unrealized_pnl") or 0.0)
        realized_pnl_24h = float(account_state.get("realized_pnl_24h") or 0.0)
        daily_loss_limit = -(initial_balance * max_daily_loss_pct / 100)
        daily_loss_triggered = (realized_pnl_24h + unrealized_pnl) <= daily_loss_limit

        for p in positions:
            if p.entry_price and p.current_price and p.entry_price > 0:
                drawdown_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100
                if drawdown_pct <= -max_drawdown_pct:
                    if not self.last_risk_alert_ts or (now - self.last_risk_alert_ts).total_seconds() > 900:
                        self.last_risk_alert_ts = now
                        msg = f"Pozycja {p.symbol} przekroczyła DD {max_drawdown_pct}% ({drawdown_pct:.2f}%)."
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
                        state["loss_streak"] = min(state.get("loss_streak", 0) + 1, 5)
                        state["cooldown"] = min(base_cooldown * (1 + state["loss_streak"]), 3600)
                        self.demo_state[p.symbol] = state

        # 1) Najpierw: jeśli otwarta pozycja osiągnęła TP/SL — przygotuj EXIT (pending)
        for pos in positions:
            sym = pos.symbol
            if not sym or float(pos.quantity or 0) <= 0:
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
            stop = entry - atr * atr_stop_mult
            take = entry + atr * atr_take_mult
            if ctx.get("ema_20") and ctx.get("ema_50") and ctx.get("ema_20") > ctx.get("ema_50"):
                trail = price - atr * trail_mult
                if trail > stop:
                    stop = trail

            if price <= stop or price >= take:
                sell_qty = float(pos.quantity)
                pending_id = self._create_pending_order(
                    db=db,
                    symbol=sym,
                    side="SELL",
                    price=price,
                    qty=sell_qty,
                    mode="demo",
                    reason=f"Exit TP/SL (TP={take:.6f}, SL={stop:.6f})",
                )
                msg = (
                    "DEMO — Potwierdzenie transakcji\n"
                    f"Para: {sym}\n"
                    "Akcja: SPRZEDAJ (zamknięcie pozycji)\n"
                    f"Cena teraz: {price}\n"
                    f"TP (cel): {take:.6f}\n"
                    f"SL (limit straty): {stop:.6f}\n"
                    f"Potwierdź: /confirm {pending_id}   Odrzuć: /reject {pending_id}"
                )
                self._send_telegram_alert("DEMO: EXIT", msg, force_send=True)
                db.add(
                    Alert(
                        alert_type="SIGNAL",
                        severity="INFO",
                        title=f"DEMO PENDING SELL {sym}",
                        message=f"Pending EXIT TP/SL. ID {pending_id}. Cena {price}. TP {take:.6f} SL {stop:.6f}.",
                        symbol=sym,
                        is_sent=True,
                        timestamp=now,
                    )
                )

        # 2) Nowe decyzje (entry/exit) — TYLKO w skrajnych momentach + TYLKO po potwierdzeniu (pending)
        for symbol in self.watchlist:
            if not symbol:
                continue
            sym_norm = (symbol or "").strip().upper().replace("/", "").replace("-", "")
            if not sym_norm.endswith(demo_quote_ccy):
                continue
            if _has_active_pending(symbol) or _pending_in_cooldown(symbol):
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
                .filter(Position.symbol == symbol, Position.mode == "demo")
                .first()
            )

            # Cooldown po ostatniej wykonanej transakcji (nie po pending)
            last_order = (
                db.query(Order)
                .filter(Order.symbol == symbol, Order.mode == "demo")
                .order_by(Order.timestamp.desc())
                .first()
            )
            state = self.demo_state.get(symbol, {"loss_streak": 0, "win_streak": 0, "cooldown": base_cooldown})
            cooldown = int(state.get("cooldown", base_cooldown))
            if last_order and (now - last_order.timestamp).total_seconds() < float(cooldown):
                continue

            trades_24h = (
                db.query(Order)
                .filter(Order.symbol == symbol, Order.mode == "demo", Order.timestamp >= since)
                .count()
            )
            if trades_24h >= max_trades_per_day:
                continue

            sig = (
                db.query(Signal)
                .filter(Signal.symbol == symbol)
                .order_by(Signal.timestamp.desc())
                .first()
            )
            if not sig:
                continue
            params = self.symbol_params.get(symbol, {})
            min_confidence = max(base_min_confidence, float(params.get("min_confidence", base_min_confidence)))
            if float(sig.confidence) < float(min_confidence):
                continue
            if (now - sig.timestamp).total_seconds() > float(max_signal_age):
                continue

            r = range_map.get(symbol)
            if not r:
                continue

            crash = self._detect_crash(db, symbol, crash_window_minutes, crash_drop_pct)
            if crash:
                min_conf_crash = float(os.getenv("CRASH_MIN_CONFIDENCE", "0.85"))
                if float(sig.confidence) < min_conf_crash:
                    continue
                state["cooldown"] = max(int(state.get("cooldown", base_cooldown)), crash_cooldown_seconds)
                self.demo_state[symbol] = state
                if not self.last_crash_alert_ts or (now - self.last_crash_alert_ts).total_seconds() > 1800:
                    self.last_crash_alert_ts = now
                    msg = (
                        f"Crash mode: {symbol} spadek > {crash_drop_pct}% w {crash_window_minutes} min. "
                        "DEMO: ograniczenie ryzyka, bez wyłączania."
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
            if not atr or float(atr) <= 0:
                continue

            # Filtry wejścia/wyjścia (konserwatywne)
            side = None
            reasons: list[str] = []
            if sig.signal_type == "BUY" and r.get("buy_low") is not None and r.get("buy_high") is not None:
                if (
                    float(r.get("buy_low")) <= price <= float(r.get("buy_high"))
                    and ema20 is not None and ema50 is not None and float(ema20) > float(ema50)
                    and rsi is not None and rsi_buy is not None and float(rsi) <= float(rsi_buy)
                ):
                    side = "BUY"
                    reasons = ["Trend wzrostowy (EMA20>EMA50)", "RSI (niski) potwierdza", "Cena w zakresie BUY (AI)"]
            elif sig.signal_type == "SELL" and r.get("sell_low") is not None and r.get("sell_high") is not None:
                if (
                    float(r.get("sell_low")) <= price <= float(r.get("sell_high"))
                    and ema20 is not None and ema50 is not None and float(ema20) < float(ema50)
                    and rsi is not None and rsi_sell is not None and float(rsi) >= float(rsi_sell)
                ):
                    side = "SELL"
                    reasons = ["Trend spadkowy (EMA20<EMA50)", "RSI (wysoki) potwierdza", "Cena w zakresie SELL (AI)"]

            if side is None:
                continue

            # DEMO: bez shortów; SELL tylko jeśli mamy pozycję, BUY tylko jeśli brak pozycji (konserwatywnie)
            if side == "BUY" and position is not None:
                continue
            if side == "SELL" and position is None:
                continue
            if daily_loss_triggered and side == "BUY":
                continue

            # Pozycjonowanie wg ATR (risk per trade)
            loss_streak = int(state.get("loss_streak", 0))
            win_streak = int(state.get("win_streak", 0))
            risk_scale = float(params.get("risk_scale", 1.0))
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
                # DEMO: nie twórz BUY, jeśli nie stać — clamp po cash.
                if price > 0:
                    max_affordable = available_cash / float(price)
                    qty = min(qty, max_affordable)
                if qty < min_qty:
                    continue

            # Rating decyzji 1–5
            rating = 1
            if float(sig.confidence) >= 0.85:
                rating += 2
            if ema20 is not None and ema50 is not None:
                if (side == "BUY" and float(ema20) > float(ema50)) or (side == "SELL" and float(ema20) < float(ema50)):
                    rating += 1
            if rsi is not None:
                if (side == "BUY" and float(rsi) <= float(rsi_buy or 50)) or (side == "SELL" and float(rsi) >= float(rsi_sell or 50)):
                    rating += 1
            rating = min(rating, 5)

            # Tylko skrajne momenty zakresu + wysokie confidence/rating
            is_extreme = False
            if all(k in r for k in ["buy_low", "buy_high", "sell_low", "sell_high"]):
                buy_low = float(r.get("buy_low"))
                buy_high = float(r.get("buy_high"))
                sell_low = float(r.get("sell_low"))
                sell_high = float(r.get("sell_high"))
                buy_edge = buy_low + (buy_high - buy_low) * extreme_margin_pct
                sell_edge = sell_high - (sell_high - sell_low) * extreme_margin_pct
                if side == "BUY" and price <= buy_edge:
                    is_extreme = True
                if side == "SELL" and price >= sell_edge:
                    is_extreme = True

            if float(sig.confidence) < float(extreme_min_conf) or int(rating) < int(extreme_min_rating):
                is_extreme = False

            if not is_extreme:
                continue

            # Utwórz pending i wyślij czytelną wiadomość
            tp = price + float(atr) * atr_take_mult
            sl = price - float(atr) * atr_stop_mult
            action_pl = "KUP" if side == "BUY" else "SPRZEDAJ"
            why = ", ".join(reasons) if reasons else "Sygnał + zakresy OpenAI + filtry ryzyka"
            pending_id = self._create_pending_order(
                db=db,
                symbol=symbol,
                side=side,
                price=price,
                qty=qty,
                mode="demo",
                reason=f"{why}. Pewność {int(float(sig.confidence)*100)}%, rating {rating}/5.",
            )
            if side == "BUY":
                try:
                    available_cash = max(0.0, float(available_cash) - (float(price) * float(qty)))
                except Exception:
                    pass

            buy_rng = f"{r.get('buy_low')} – {r.get('buy_high')}"
            sell_rng = f"{r.get('sell_low')} – {r.get('sell_high')}"
            msg = (
                "DEMO — Potwierdzenie transakcji\n"
                f"Para: {symbol}\n"
                f"Akcja: {action_pl} TERAZ\n"
                f"Cena teraz: {price}\n"
                f"TP (cel): {tp:.6f}\n"
                f"SL (limit straty): {sl:.6f}\n"
                f"Zakresy AI: BUY {buy_rng} | SELL {sell_rng}\n"
                f"Dlaczego: {why}\n"
                f"Pewność AI: {int(float(sig.confidence)*100)}% | Ocena: {rating}/5\n"
                f"Potwierdź: /confirm {pending_id}   Odrzuć: /reject {pending_id}"
            )
            self._send_telegram_alert("DEMO: POTWIERDŹ", msg, force_send=True)
            db.add(
                Alert(
                    alert_type="SIGNAL",
                    severity="INFO",
                    title=f"DEMO PENDING {side} {symbol}",
                    message=f"Pending ID {pending_id}. {side} {symbol} qty={qty} price={price}. {why}.",
                    symbol=symbol,
                    is_sent=True,
                    timestamp=now,
                )
            )

        # Globalny hamulec (bez wyłączania): wydłuż cooldown dla wszystkich symboli
        if daily_loss_triggered:
            for sym in self.watchlist:
                sym_norm = (sym or "").strip().upper().replace("/", "").replace("-", "")
                if not sym_norm.endswith(demo_quote_ccy):
                    continue
                state = self.demo_state.get(sym, {"loss_streak": 0, "cooldown": base_cooldown})
                state["loss_streak"] = min(int(state.get("loss_streak", 0)) + 1, 5)
                state["cooldown"] = min(base_cooldown * (1 + int(state["loss_streak"])), 3600)
                self.demo_state[sym] = state
            msg = "Limit dziennej straty osiągnięty — ograniczam ryzyko (DEMO), bez wyłączania bota."
            log_to_db("WARNING", "demo_trading", msg, db=db)
            self._send_telegram_alert("RISK: Daily loss", msg, force_send=True)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_exception("demo_trading", "Błąd commit demo_trading", exc, db=db)
            return

    def _detect_crash(self, db: Session, symbol: str, window_minutes: int, drop_pct: float) -> bool:
        """
        Wykryj gwałtowny spadek w krótkim oknie na live danych.
        """
        since = datetime.utcnow() - timedelta(minutes=window_minutes)
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
                        timestamp=datetime.utcnow()
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
            provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
            # OpenAI jest wymagany tylko w trybie provider=openai.
            # provider=auto może działać bez klucza (fallback -> heuristic).
            if provider == "openai" and not self._has_openai_key():
                self._log_openai_missing()
                return
            if provider == "auto" and not self._has_openai_key():
                # Nie wyłączaj bota — poinformuj w logach, że działa fallback.
                now = datetime.utcnow()
                if not self.last_openai_missing_log_ts or (now - self.last_openai_missing_log_ts).total_seconds() > 300:
                    self.last_openai_missing_log_ts = now
                    msg = "Brak OPENAI_API_KEY — AI_PROVIDER=auto uruchamia fallback (heurystyka)."
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
            now = datetime.utcnow()
            if not self.last_learning_ts or (now - self.last_learning_ts).seconds > 3600:
                self._learn_from_history(db)
                self.last_learning_ts = now

            # Zbierz dane rynkowe
            self.collect_market_data(db)

            # Mark-to-market pozycji + snapshoty KPI (DEMO)
            self._mark_to_market_positions(db, mode="demo")
            self._persist_demo_snapshot_if_due(db)
            
            # Zbierz świece
            self.collect_klines(db)

            # Analiza + blog (co najmniej raz na godzinę)
            maybe_generate_insights_and_blog(db, self.watchlist)

            # Demo trading na danych live
            self._demo_trading(db)
            
            logger.info("✅ Collection cycle completed")
        except Exception as e:
            logger.error(f"❌ Error in collection cycle: {str(e)}")
            log_exception("collector", "Błąd w cyklu zbierania danych", e, db=db)
        finally:
            db.close()

    def _learn_from_history(self, db: Session):
        """Prosta kalibracja parametrów na historii (konserwatywna)."""
        report_lines = []
        for symbol in self.watchlist:
            since = datetime.utcnow() - timedelta(days=self.learning_days)
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
            base_conf = 0.75
            conf = min(0.9, base_conf + min(0.15, vol * 2) + (0.05 if trend_strength < 0.002 else 0))
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
                    timestamp=datetime.utcnow(),
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
