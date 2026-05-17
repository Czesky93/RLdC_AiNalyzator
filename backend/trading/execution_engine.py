"""
execution_engine.py — State machine per symbol dla Binance Spot.

Stany symbolu:
  IDLE            → brak aktywności, gotowy do nowego wejścia
  CANDIDATE       → sygnał wykryty, oczekuje na potwierdzenie risk engine
  PENDING_BUY     → PendingOrder BUY w DB, oczekuje na wykonanie
  LONG_OPEN       → pozycja otwarta, monitoruje exit conditions
  PENDING_SELL    → PendingOrder SELL w DB (SL/TP/exit)
  PARTIAL_FILL    → częściowo wypełniony BUY / SELL
  COOLDOWN        → po zamknięciu pozycji / odrzuceniu, cooldown przed nowym wejściem
  ERROR           → błąd execution, wymaga ręcznej interwencji

Maszynę wywołuje się per-symbol per-cykl.
Stan jest zapisywany w pamięci (process-local) + w tabeli decision_traces dla auditability.

Użycie:
    from backend.trading.execution_engine import ExecutionEngine
    engine = ExecutionEngine(cfg, binance_client)

    # W każdym cyklu:
    state = engine.get_state(symbol)
    new_state = engine.run_cycle(db, symbol, signal_result, risk_result)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class SymbolState(str, Enum):
    IDLE = "IDLE"
    CANDIDATE = "CANDIDATE"
    PENDING_BUY = "PENDING_BUY"
    LONG_OPEN = "LONG_OPEN"
    PENDING_SELL = "PENDING_SELL"
    PARTIAL_FILL = "PARTIAL_FILL"
    COOLDOWN = "COOLDOWN"
    ERROR = "ERROR"


@dataclass
class SymbolExecState:
    """Stan wykonania per symbol (w pamięci)."""
    symbol: str
    state: SymbolState = SymbolState.IDLE
    mode: str = "demo"

    # Dane aktywnej pozycji (ustawiane po LONG_OPEN)
    position_id: Optional[int] = None
    entry_price: float = 0.0
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    take_profit_2: float = 0.0
    trailing_activation: float = 0.0
    trailing_stop: Optional[float] = None
    trailing_active: bool = False
    partial_take_count: int = 0
    atr: float = 0.0

    # Tracking
    pending_order_id: Optional[int] = None
    last_transition_ts: float = field(default_factory=time.monotonic)
    cooldown_until: float = 0.0
    error_message: str = ""
    last_exit_reason: str = ""

    # OCO/protection order IDs (Binance)
    oco_list_client_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None

    def is_in_cooldown(self) -> bool:
        return time.monotonic() < self.cooldown_until

    def cooldown_remaining_sec(self) -> int:
        r = self.cooldown_until - time.monotonic()
        return int(r) if r > 0 else 0

    def transition(self, new_state: SymbolState, reason: str = "") -> None:
        old = self.state
        self.state = new_state
        self.last_transition_ts = time.monotonic()
        if reason:
            logger.info(
                "StateMachine %s: %s → %s (%s)",
                self.symbol, old.value, new_state.value, reason,
            )
        else:
            logger.debug("StateMachine %s: %s → %s", self.symbol, old.value, new_state.value)


class _StateRegistry:
    """Thread-safe rejestr stanów per symbol."""

    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[str, SymbolExecState] = {}

    def get(self, symbol: str, mode: str = "demo") -> SymbolExecState:
        with self._lock:
            key = f"{mode}:{symbol}"
            if key not in self._states:
                self._states[key] = SymbolExecState(symbol=symbol, mode=mode)
            return self._states[key]

    def set(self, state: SymbolExecState) -> None:
        with self._lock:
            key = f"{state.mode}:{state.symbol}"
            self._states[key] = state

    def all_states(self) -> List[SymbolExecState]:
        with self._lock:
            return list(self._states.values())


_registry = _StateRegistry()


def get_state_registry() -> _StateRegistry:
    return _registry


@dataclass
class CycleResult:
    """Wynik jednego cyklu execution per symbol."""
    symbol: str
    mode: str
    old_state: SymbolState
    new_state: SymbolState
    action_taken: str = ""       # NONE | BUY_QUEUED | SELL_QUEUED | COOLDOWN_SET | ERROR_SET
    pending_order_id: Optional[int] = None
    reason_code: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class ExecutionEngine:
    """
    Silnik wykonania transakcji per symbol.

    Odpowiada za:
      1. Walidację zlecenia (symbol_filter.validate_order)
      2. Kolejkowanie BUY/SELL jako PendingOrder
      3. Śledzenie stanu per symbol (state machine)
      4. Pełne sprawdzenie przed wejściem (filtry exchange)
      5. Logowanie zmian stanu (reason_code)
    """

    def __init__(self, cfg, binance_client):
        self.cfg = cfg
        self.binance = binance_client
        self._registry = _registry

    def get_state(self, symbol: str, mode: str = "demo") -> SymbolExecState:
        return self._registry.get(symbol, mode)

    def queue_buy(
        self,
        db: Session,
        symbol: str,
        qty: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        take_profit_2: float,
        trailing_activation: float,
        atr: float,
        mode: str = "demo",
        reason: str = "",
        signal_details: Optional[Dict] = None,
        config_snapshot_id: Optional[str] = None,
    ) -> CycleResult:
        """
        Kolejkuje BUY PendingOrder po walidacji wszystkich filtrów exchange.

        Zwraca CycleResult z new_state = PENDING_BUY lub ERROR.
        """
        from backend.trading.symbol_filter import load_symbol_universe, validate_order, round_qty

        sym_state = self._registry.get(symbol, mode)
        old_state = sym_state.state
        result = CycleResult(
            symbol=symbol, mode=mode,
            old_state=old_state, new_state=old_state,
        )

        # Guard: tylko z IDLE lub CANDIDATE
        if sym_state.state not in (SymbolState.IDLE, SymbolState.CANDIDATE):
            result.reason_code = "invalid_state_for_buy"
            result.details["current_state"] = sym_state.state.value
            return result

        # Cooldown check
        if sym_state.is_in_cooldown():
            result.reason_code = "cooldown_active"
            result.details["cooldown_remaining_sec"] = sym_state.cooldown_remaining_sec()
            return result

        # Pobierz meta z exchangeInfo
        try:
            universe = load_symbol_universe(
                self.binance,
                allowed_quotes=self.cfg.allowed_quotes,
            )
            meta = universe.get(symbol)
        except Exception as exc:
            logger.error("queue_buy: load_symbol_universe error: %s", exc)
            meta = None

        if meta is None:
            result.reason_code = "symbol_not_in_universe"
            result.details["symbol"] = symbol
            sym_state.transition(SymbolState.ERROR, "symbol_not_in_universe")
            sym_state.error_message = "Symbol nie znaleziony w exchangeInfo"
            self._registry.set(sym_state)
            result.new_state = SymbolState.ERROR
            return result

        # Zaokrąglij qty do step_size (floor)
        from backend.trading.symbol_filter import round_qty
        qty_rounded = round_qty(qty, meta)

        if qty_rounded <= 0 or qty_rounded * entry_price < meta.min_notional:
            result.reason_code = "qty_too_small_after_rounding"
            result.details["qty"] = qty
            result.details["qty_rounded"] = qty_rounded
            result.details["notional"] = qty_rounded * entry_price
            result.details["min_notional"] = meta.min_notional
            return result

        # Pobierz avg_price dla PERCENT_PRICE_BY_SIDE
        avg_price = self._get_avg_price(symbol)

        # Pełna walidacja filtrów exchange
        ok, reason_code = validate_order(
            symbol=symbol,
            side="BUY",
            qty=qty_rounded,
            price=entry_price,
            meta=meta,
            avg_price=avg_price,
        )
        if not ok:
            result.reason_code = reason_code
            result.details["qty"] = qty_rounded
            result.details["price"] = entry_price
            result.details["avg_price"] = avg_price
            return result

        # Sprawdź duplikat pending
        from backend.database import PendingOrder
        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.symbol == symbol,
                PendingOrder.side == "BUY",
                PendingOrder.mode == mode,
                PendingOrder.status.in_(["PENDING_CREATED", "PENDING_CONFIRMED", "CONFIRMED"]),
            )
            .first()
        )
        if existing:
            result.reason_code = "duplicate_pending_buy"
            result.details["existing_pending_id"] = existing.id
            return result

        # Utwórz PendingOrder
        pending_id = self._create_pending_order(
            db=db,
            symbol=symbol,
            side="BUY",
            qty=qty_rounded,
            price=entry_price,
            mode=mode,
            reason=reason or f"signal_engine:{signal_details}",
            config_snapshot_id=config_snapshot_id,
        )

        # Przejście stanu
        sym_state.state = SymbolState.PENDING_BUY
        sym_state.pending_order_id = pending_id
        sym_state.entry_price = entry_price
        sym_state.quantity = qty_rounded
        sym_state.stop_loss = stop_loss
        sym_state.take_profit = take_profit
        sym_state.take_profit_2 = take_profit_2
        sym_state.trailing_activation = trailing_activation
        sym_state.atr = atr
        sym_state.last_transition_ts = time.monotonic()
        self._registry.set(sym_state)

        result.new_state = SymbolState.PENDING_BUY
        result.action_taken = "BUY_QUEUED"
        result.pending_order_id = pending_id
        result.reason_code = "buy_queued"

        logger.info(
            "ExecutionEngine.queue_buy: %s mode=%s qty=%.8g price=%.6f pending_id=%s",
            symbol, mode, qty_rounded, entry_price, pending_id,
        )
        return result

    def queue_sell(
        self,
        db: Session,
        symbol: str,
        qty: float,
        price: float,
        mode: str = "demo",
        reason: str = "",
        reason_code: str = "exit_triggered",
        config_snapshot_id: Optional[str] = None,
        partial: bool = False,
    ) -> CycleResult:
        """
        Kolejkuje SELL PendingOrder po walidacji filtrów exchange.
        """
        from backend.trading.symbol_filter import load_symbol_universe, validate_order, round_qty
        from backend.database import PendingOrder

        sym_state = self._registry.get(symbol, mode)
        old_state = sym_state.state
        result = CycleResult(
            symbol=symbol, mode=mode,
            old_state=old_state, new_state=old_state,
        )

        if sym_state.state not in (SymbolState.LONG_OPEN, SymbolState.PARTIAL_FILL, SymbolState.PENDING_SELL):
            result.reason_code = "invalid_state_for_sell"
            result.details["current_state"] = sym_state.state.value
            return result

        # Duplikat check
        existing_sell = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.symbol == symbol,
                PendingOrder.side == "SELL",
                PendingOrder.mode == mode,
                PendingOrder.status.in_(["PENDING_CREATED", "PENDING_CONFIRMED", "CONFIRMED"]),
            )
            .first()
        )
        if existing_sell:
            result.reason_code = "duplicate_pending_sell"
            result.details["existing_pending_id"] = existing_sell.id
            return result

        # Meta z exchangeInfo dla filtrów
        try:
            universe = load_symbol_universe(self.binance, allowed_quotes=self.cfg.allowed_quotes)
            meta = universe.get(symbol)
        except Exception:
            meta = None

        # Zaokrąglij qty
        sell_qty = qty
        if meta and meta.step_size and meta.step_size > 0:
            sell_qty = round_qty(qty, meta)

        if sell_qty <= 0:
            result.reason_code = "qty_zero_after_rounding"
            return result

        # Walidacja ceny (PRICE_FILTER, PERCENT_PRICE_BY_SIDE)
        if meta:
            avg_price = self._get_avg_price(symbol)
            ok, val_reason = validate_order(
                symbol=symbol,
                side="SELL",
                qty=sell_qty,
                price=price,
                meta=meta,
                avg_price=avg_price,
            )
            if not ok:
                # Walidacja sprzedaży odrzucona — logujemy ale NIE blokujemy stop loss
                # (nie można nie wychodzić z pozycji tylko dlatego że cena poza filtrem)
                if reason_code in ("stop_loss_hit", "trailing_lock_profit"):
                    logger.warning(
                        "queue_sell: exchange filter %s dla %s — kontynuuję mimo błędu filter (exit krytyczny)",
                        val_reason, symbol,
                    )
                else:
                    result.reason_code = val_reason
                    result.details["sell_qty"] = sell_qty
                    result.details["price"] = price
                    return result

        pending_id = self._create_pending_order(
            db=db,
            symbol=symbol,
            side="SELL",
            qty=sell_qty,
            price=price,
            mode=mode,
            reason=reason or reason_code,
            config_snapshot_id=config_snapshot_id,
        )

        sym_state.transition(SymbolState.PENDING_SELL, reason_code)
        sym_state.last_exit_reason = reason_code
        sym_state.pending_order_id = pending_id
        self._registry.set(sym_state)

        result.new_state = SymbolState.PENDING_SELL
        result.action_taken = "SELL_QUEUED"
        result.pending_order_id = pending_id
        result.reason_code = "sell_queued"

        logger.info(
            "ExecutionEngine.queue_sell: %s mode=%s qty=%.8g price=%.6f reason=%s pending_id=%s",
            symbol, mode, sell_qty, price, reason_code, pending_id,
        )
        return result

    def on_buy_filled(
        self,
        db: Session,
        symbol: str,
        mode: str,
        position_id: int,
        exec_price: float,
        exec_qty: float,
        stop_loss: float,
        take_profit: float,
    ) -> None:
        """
        Wywoływana po potwierdzeniu FILL BUY.
        Przechodzi stan: PENDING_BUY → LONG_OPEN.
        Opcjonalnie składa OCO/TP/SL na Binance.
        """
        sym_state = self._registry.get(symbol, mode)
        sym_state.transition(SymbolState.LONG_OPEN, "buy_filled")
        sym_state.position_id = position_id
        sym_state.entry_price = exec_price
        sym_state.quantity = exec_qty
        sym_state.stop_loss = stop_loss
        sym_state.take_profit = take_profit
        sym_state.pending_order_id = None
        self._registry.set(sym_state)

        # Złóż zlecenia zabezpieczające na Binance
        if self.cfg.use_oco_for_protection:
            self._place_oco_or_protection(db, symbol, mode, sym_state)

        logger.info(
            "ExecutionEngine.on_buy_filled: %s mode=%s pos_id=%s "
            "entry=%.6f qty=%.8g sl=%.6f tp=%.6f",
            symbol, mode, position_id, exec_price, exec_qty, stop_loss, take_profit,
        )

    def on_sell_filled(
        self,
        db: Session,
        symbol: str,
        mode: str,
        net_pnl: float,
        partial: bool = False,
        cooldown_sec: int = 0,
    ) -> None:
        """
        Wywoływana po potwierdzeniu FILL SELL.
        Przechodzi stan: PENDING_SELL → COOLDOWN lub IDLE.
        """
        from backend.trading.risk_engine import _cooldown_tracker

        sym_state = self._registry.get(symbol, mode)

        if partial:
            sym_state.transition(SymbolState.PARTIAL_FILL, "sell_partial_filled")
            sym_state.partial_take_count += 1
        else:
            # Poinformuj risk engine
            if net_pnl < 0:
                _cooldown_tracker.on_loss(
                    symbol,
                    max_streak=self.cfg.max_losing_streak,
                    cooldown_sec=self.cfg.cooldown_after_loss_streak_min * 60,
                )
            else:
                _cooldown_tracker.on_win(symbol)

            # Ustaw cooldown dla state machine
            cd_sec = cooldown_sec or self.cfg.pending_order_cooldown_sec
            sym_state.cooldown_until = time.monotonic() + cd_sec
            sym_state.transition(SymbolState.COOLDOWN, "sell_filled_cooldown")
            sym_state.position_id = None
            sym_state.entry_price = 0.0
            sym_state.quantity = 0.0
            sym_state.stop_loss = 0.0
            sym_state.take_profit = 0.0
            sym_state.trailing_active = False
            sym_state.trailing_stop = None
            sym_state.partial_take_count = 0
            sym_state.pending_order_id = None
            sym_state.oco_list_client_order_id = None
            sym_state.sl_order_id = None
            sym_state.tp_order_id = None

        self._registry.set(sym_state)

        logger.info(
            "ExecutionEngine.on_sell_filled: %s mode=%s pnl=%.4f partial=%s cooldown=%ds",
            symbol, mode, net_pnl, partial, cooldown_sec,
        )

    def tick_cooldowns(self) -> List[str]:
        """
        Sprawdź czy jakiekolwiek symbole wyszły z cooldown → ustaw IDLE.
        Zwraca listę symboli które zmieniły stan.
        """
        now = time.monotonic()
        transitioned = []
        for sym_state in self._registry.all_states():
            if sym_state.state == SymbolState.COOLDOWN and now >= sym_state.cooldown_until:
                sym_state.transition(SymbolState.IDLE, "cooldown_expired")
                self._registry.set(sym_state)
                transitioned.append(sym_state.symbol)
        return transitioned

    def sync_from_db(self, db: Session, mode: str = "demo") -> None:
        """
        Synchronizuj stan state machine z DB po restarcie.

        Sprawdza:
          - Które symbole mają otwarte pozycje → LONG_OPEN
          - Które mają aktywne pending BUY → PENDING_BUY
          - Które mają aktywne pending SELL → PENDING_SELL
        """
        from backend.database import Position, PendingOrder

        try:
            open_pos = (
                db.query(Position)
                .filter(
                    Position.mode == mode,
                    Position.exit_reason_code.is_(None),
                    Position.quantity > 0,
                )
                .all()
            )
            for pos in open_pos:
                sym = pos.symbol or ""
                if not sym:
                    continue
                sym_state = self._registry.get(sym, mode)
                if sym_state.state == SymbolState.IDLE:
                    sym_state.transition(SymbolState.LONG_OPEN, "sync_from_db")
                    sym_state.position_id = pos.id
                    sym_state.entry_price = float(pos.entry_price or 0)
                    sym_state.quantity = float(pos.quantity or 0)
                    sym_state.stop_loss = float(pos.planned_sl or 0)
                    sym_state.take_profit = float(pos.planned_tp or 0)
                    self._registry.set(sym_state)

            pending_orders = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.status.in_(
                        ["PENDING_CREATED", "PENDING_CONFIRMED", "CONFIRMED"]
                    ),
                )
                .all()
            )
            for po in pending_orders:
                sym = po.symbol or ""
                if not sym:
                    continue
                sym_state = self._registry.get(sym, mode)
                target = SymbolState.PENDING_BUY if (po.side or "").upper() == "BUY" else SymbolState.PENDING_SELL
                if sym_state.state == SymbolState.IDLE:
                    sym_state.transition(target, "sync_from_db_pending")
                    sym_state.pending_order_id = po.id
                    self._registry.set(sym_state)

            logger.info(
                "ExecutionEngine.sync_from_db: mode=%s open_pos=%d pending=%d",
                mode, len(open_pos), len(pending_orders),
            )
        except Exception as exc:
            logger.error("ExecutionEngine.sync_from_db: błąd: %s", exc)

    def _get_avg_price(self, symbol: str) -> float:
        """Pobierz 5-minutową średnią cenę z Binance (dla PERCENT_PRICE_BY_SIDE)."""
        try:
            r = self.binance.client.get_avg_price(symbol=symbol) if hasattr(self.binance, "client") else {}
            return float((r or {}).get("price", 0) or 0)
        except Exception:
            return 0.0

    def _place_oco_or_protection(
        self,
        db: Session,
        symbol: str,
        mode: str,
        sym_state: SymbolExecState,
    ) -> None:
        """
        Złóż zlecenia OCO (TP + SL) na Binance po LONG_OPEN.
        Działa tylko w trybie LIVE.

        Jeśli OCO dostępne (meta.oco_allowed) → place_oco_order.
        Fallback: dwa osobne zlecenia LIMIT (TP) + STOP_LOSS_LIMIT (SL).
        """
        if mode != "live":
            return  # DEMO — nie wysyłamy na exchange

        from backend.trading.symbol_filter import load_symbol_universe, round_price, round_qty

        try:
            universe = load_symbol_universe(self.binance, allowed_quotes=self.cfg.allowed_quotes)
            meta = universe.get(symbol)
        except Exception:
            meta = None

        if not meta:
            logger.warning("_place_oco_or_protection: brak meta dla %s", symbol)
            return

        tp = sym_state.take_profit
        sl = sym_state.stop_loss
        qty = sym_state.quantity

        if not tp or not sl or not qty or tp <= 0 or sl <= 0 or qty <= 0:
            logger.warning(
                "_place_oco_or_protection: niepełne dane %s tp=%.6f sl=%.6f qty=%.8g",
                symbol, tp or 0, sl or 0, qty or 0,
            )
            return

        # Zaokrąglij ceny i qty
        tp_rounded = round_price(tp, meta)
        sl_rounded = round_price(sl, meta)
        sl_limit = round_price(sl * 0.995, meta)  # limit SL 0.5% poniżej stop price
        qty_rounded = round_qty(qty, meta)

        if qty_rounded <= 0:
            return

        try:
            if meta.oco_allowed and self.cfg.use_oco_for_protection:
                # OCO: LIMIT MAKER (TP) + STOP_LOSS_LIMIT (SL) w jednym zleceniu
                result = self.binance.place_oco_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=qty_rounded,
                    price=tp_rounded,                    # limit TP price
                    stop_price=sl_rounded,               # stop trigger
                    stop_limit_price=sl_limit,           # limit na stop (0.5% poniżej)
                )
                if result and not result.get("_error"):
                    sym_state.oco_list_client_order_id = result.get("listClientOrderId")
                    self._registry.set(sym_state)
                    logger.info(
                        "OCO złożone: %s tp=%.6f sl=%.6f qty=%.8g oco_id=%s",
                        symbol, tp_rounded, sl_rounded, qty_rounded,
                        sym_state.oco_list_client_order_id,
                    )
                else:
                    err = (result or {}).get("error_message", "unknown")
                    logger.warning("OCO rejected dla %s: %s — próba fallback", symbol, err)
                    self._place_two_protection_orders(
                        db, symbol, mode, sym_state, meta,
                        tp_rounded, sl_rounded, sl_limit, qty_rounded,
                    )
            elif self.cfg.oco_fallback_to_two_orders:
                self._place_two_protection_orders(
                    db, symbol, mode, sym_state, meta,
                    tp_rounded, sl_rounded, sl_limit, qty_rounded,
                )
        except Exception as exc:
            logger.error("_place_oco_or_protection: błąd dla %s: %s", symbol, exc)
            from backend.system_logger import log_exception
            log_exception("execution_engine", f"OCO/protection order error {symbol}", exc, db=db)

    def _place_two_protection_orders(
        self,
        db: Session,
        symbol: str,
        mode: str,
        sym_state: SymbolExecState,
        meta,
        tp: float,
        sl: float,
        sl_limit: float,
        qty: float,
    ) -> None:
        """Dwa osobne zlecenia LIMIT (TP) + STOP_LOSS_LIMIT (SL)."""
        # TP LIMIT
        try:
            tp_result = self.binance.place_order(
                symbol=symbol,
                side="SELL",
                order_type="LIMIT",
                quantity=qty,
                price=tp,
            )
            if tp_result and not tp_result.get("_error"):
                sym_state.tp_order_id = str(tp_result.get("orderId", ""))
                logger.info("TP LIMIT złożone: %s @ %.6f qty=%.8g id=%s", symbol, tp, qty, sym_state.tp_order_id)
            else:
                logger.warning("TP LIMIT rejected dla %s: %s", symbol, (tp_result or {}).get("error_message"))
        except Exception as exc:
            logger.error("TP LIMIT error %s: %s", symbol, exc)

        # SL STOP_LOSS_LIMIT
        try:
            sl_result = self.binance.place_order(
                symbol=symbol,
                side="SELL",
                order_type="STOP_LOSS_LIMIT",
                quantity=qty,
                price=sl_limit,
                stop_price=sl,
            )
            if sl_result and not sl_result.get("_error"):
                sym_state.sl_order_id = str(sl_result.get("orderId", ""))
                logger.info("SL STOP złożone: %s stop=%.6f limit=%.6f qty=%.8g id=%s",
                    symbol, sl, sl_limit, qty, sym_state.sl_order_id)
            else:
                logger.warning("SL STOP rejected dla %s: %s", symbol, (sl_result or {}).get("error_message"))
        except Exception as exc:
            logger.error("SL STOP error %s: %s", symbol, exc)

        self._registry.set(sym_state)

    def cancel_protection_orders(self, symbol: str, mode: str) -> None:
        """
        Anuluj OCO/TP/SL zlecenia gdy pozycja jest zamykana przez exit engine.
        Wywoływać przed queue_sell aby uniknąć podwójnej sprzedaży.
        """
        if mode != "live":
            return

        sym_state = self._registry.get(symbol, mode)

        if sym_state.oco_list_client_order_id:
            try:
                self.binance.cancel_order(symbol=symbol, list_client_order_id=sym_state.oco_list_client_order_id)
                logger.info("OCO anulowane: %s id=%s", symbol, sym_state.oco_list_client_order_id)
            except Exception as exc:
                logger.warning("Błąd anulowania OCO %s: %s", symbol, exc)
            sym_state.oco_list_client_order_id = None

        if sym_state.tp_order_id:
            try:
                self.binance.cancel_order(symbol=symbol, order_id=sym_state.tp_order_id)
                logger.info("TP anulowane: %s id=%s", symbol, sym_state.tp_order_id)
            except Exception as exc:
                logger.warning("Błąd anulowania TP %s: %s", symbol, exc)
            sym_state.tp_order_id = None

        if sym_state.sl_order_id:
            try:
                self.binance.cancel_order(symbol=symbol, order_id=sym_state.sl_order_id)
                logger.info("SL anulowane: %s id=%s", symbol, sym_state.sl_order_id)
            except Exception as exc:
                logger.warning("Błąd anulowania SL %s: %s", symbol, exc)
            sym_state.sl_order_id = None

        self._registry.set(sym_state)

    def _create_pending_order(
        self,
        db: Session,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        mode: str,
        reason: str = "",
        config_snapshot_id: Optional[str] = None,
    ) -> int:
        """
        Utwórz PendingOrder w DB.
        Zwraca id nowego lub istniejącego (idempotentne).
        """
        from backend.database import PendingOrder
        from backend.runtime_settings import get_runtime_config
        from datetime import timedelta

        def utc_now():
            return datetime.utcnow()

        now = utc_now()
        symbol_norm = symbol.strip().upper()
        side_norm = side.strip().upper()

        # Dedup check
        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.symbol == symbol_norm,
                PendingOrder.side == side_norm,
                PendingOrder.mode == mode,
                PendingOrder.status.in_(["PENDING_CREATED", "PENDING_CONFIRMED", "CONFIRMED"]),
            )
            .order_by(PendingOrder.created_at.desc())
            .first()
        )
        if existing:
            return int(existing.id)

        config = get_runtime_config(db)
        auto_execute = bool(config.get("enable_auto_execute", True))
        require_manual = bool(config.get("require_manual_confirmation", False))
        auto_confirm = auto_execute and not require_manual

        idempotency_key = f"exec_engine:{mode}:{symbol_norm}:{side_norm}:{int(now.timestamp())}"
        reason_full = f"{reason} | {idempotency_key}".strip(" |")

        pending = PendingOrder(
            symbol=symbol_norm,
            side=side_norm,
            order_type="MARKET",
            price=price,
            quantity=qty,
            mode=mode,
            status="PENDING_CONFIRMED" if auto_confirm else "PENDING_CREATED",
            reason=reason_full,
            config_snapshot_id=config_snapshot_id,
            strategy_name="execution_engine",
            source="execution_engine",
            pending_type=f"auto_{mode}",
            created_at=now,
            expires_at=now + timedelta(hours=24),
            confirmed_at=now if auto_confirm else None,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        return int(pending.id)

    def get_all_states(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Zwróć listę stanów wszystkich symboli dla danego mode."""
        all_s = self._registry.all_states()
        if mode:
            all_s = [s for s in all_s if s.mode == mode]
        return [
            {
                "symbol": s.symbol,
                "mode": s.mode,
                "state": s.state.value,
                "in_cooldown": s.is_in_cooldown(),
                "cooldown_remaining_sec": s.cooldown_remaining_sec(),
                "pending_order_id": s.pending_order_id,
                "position_id": s.position_id,
                "entry_price": s.entry_price,
                "quantity": s.quantity,
                "stop_loss": s.stop_loss,
                "take_profit": s.take_profit,
                "trailing_active": s.trailing_active,
                "partial_take_count": s.partial_take_count,
                "last_exit_reason": s.last_exit_reason,
                "error_message": s.error_message,
            }
            for s in all_s
        ]
