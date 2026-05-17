"""
risk_engine.py — Silnik ryzyka i position sizing dla Binance Spot.

Odpowiada za:
  1. Twarde limity — blokuje wejście jeśli naruszono limit
  2. Position sizing — liczy qty na podstawie ATR i kapitału (nie flat notional)
  3. Cooldown management — śledzi streak i cooldown per symbol
  4. Drawdown gate — dzienny i tygodniowy limit strat
  5. Exposure gate — łączna ekspozycja portfela
  6. Estimated TP/SL — na podstawie ATR × multiplier

Każde odrzucenie ma reason_code + reason_pl (dla DecisionTrace / Telegram).

Użycie:
    from backend.trading.risk_engine import RiskEngine, RiskGateResult
    engine = RiskEngine(cfg)
    result = engine.evaluate(db, symbol, entry_signal, account_state)
    if result.is_allowed:
        qty = result.recommended_qty
        tp = result.take_profit_price
        sl = result.stop_loss_price
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class AccountState:
    """Stan konta (z Binance lub demo DB)."""
    equity: float = 0.0
    available_cash: float = 0.0
    positions_count: int = 0
    positions_value: float = 0.0
    realized_pnl_24h: float = 0.0
    realized_pnl_7d: float = 0.0
    unrealized_pnl: float = 0.0
    initial_balance: float = 0.0


@dataclass
class PositionMeta:
    """Metadane otwartej pozycji do oceny ekspozycji."""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float


@dataclass
class RiskGateResult:
    """Wynik oceny bramy ryzyka."""
    is_allowed: bool
    reason_code: str = ""
    reason_pl: str = ""

    # Position sizing
    recommended_qty: float = 0.0
    recommended_notional: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    take_profit_2_price: float = 0.0
    trailing_activation_price: float = 0.0
    break_even_price: float = 0.0
    risk_amount: float = 0.0           # kwota ryzyka (entry - sl) * qty
    expected_reward: float = 0.0       # kwota nagrody (tp - entry) * qty

    # Diagnoza
    details: Dict[str, Any] = field(default_factory=dict)
    cooldown_remaining_sec: int = 0

    def summary(self) -> str:
        if self.is_allowed:
            return (
                f"ALLOWED qty={self.recommended_qty:.8g} "
                f"sl={self.stop_loss_price:.6f} tp={self.take_profit_price:.6f}"
            )
        return f"BLOCKED reason={self.reason_code}"


_REASON_PL: Dict[str, str] = {
    "max_positions_reached": "Osiągnięto limit otwartych pozycji",
    "max_trades_per_day": "Osiągnięto limit transakcji na dziś",
    "daily_loss_limit_hit": "Dzienny limit strat osiągnięty — trading wstrzymany",
    "weekly_loss_limit_hit": "Tygodniowy limit strat osiągnięty — trading wstrzymany",
    "max_total_exposure_hit": "Osiągnięto limit łącznej ekspozycji portfela",
    "max_symbol_exposure_hit": "Osiągnięto limit ekspozycji na ten symbol",
    "insufficient_cash": "Niewystarczający dostępny kapitał",
    "cooldown_after_loss_streak": "Cooldown po serii strat — czekamy",
    "qty_too_small": "Wymagana ilość poniżej minimum exchange",
    "no_atr_for_sizing": "Brak ATR — nie można wyliczyć rozmiarów TP/SL",
    "symbol_has_open_position": "Symbol ma już otwartą pozycję — duplikat entry",
    "kill_switch_active": "Kill switch aktywny — trading wyłączony",
}


class _CooldownTracker:
    """Thread-safe tracker cooldown i streak per symbol."""

    def __init__(self):
        self._lock = threading.Lock()
        # symbol → {"loss_streak": int, "win_streak": int, "cooldown_until": float}
        self._state: Dict[str, Dict] = {}

    def get(self, symbol: str) -> Dict:
        with self._lock:
            return dict(self._state.get(symbol, {"loss_streak": 0, "win_streak": 0, "cooldown_until": 0.0}))

    def on_loss(self, symbol: str, max_streak: int, cooldown_sec: int) -> None:
        with self._lock:
            s = self._state.get(symbol, {"loss_streak": 0, "win_streak": 0, "cooldown_until": 0.0})
            s["loss_streak"] = min(s.get("loss_streak", 0) + 1, max_streak + 2)
            s["win_streak"] = 0
            # Eskalacja cooldown: base × (1 + streak)
            streak = s["loss_streak"]
            cd = min(cooldown_sec * (1 + streak), 7200)  # max 2h
            s["cooldown_until"] = time.monotonic() + cd
            self._state[symbol] = s

    def on_win(self, symbol: str) -> None:
        with self._lock:
            s = self._state.get(symbol, {"loss_streak": 0, "win_streak": 0, "cooldown_until": 0.0})
            s["win_streak"] = s.get("win_streak", 0) + 1
            s["loss_streak"] = 0
            s["cooldown_until"] = 0.0
            self._state[symbol] = s

    def is_in_cooldown(self, symbol: str) -> Tuple[bool, int]:
        """Zwraca (in_cooldown, remaining_sec)."""
        now = time.monotonic()
        with self._lock:
            s = self._state.get(symbol, {})
            until = float(s.get("cooldown_until", 0.0))
        if until > now:
            return True, int(until - now)
        return False, 0

    def reset(self, symbol: str) -> None:
        with self._lock:
            self._state.pop(symbol, None)

    def get_all_states(self) -> Dict[str, Dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._state.items()}


# Singleton tracker (per-process)
_cooldown_tracker = _CooldownTracker()


def get_cooldown_tracker() -> _CooldownTracker:
    return _cooldown_tracker


class RiskEngine:
    """
    Silnik oceny ryzyka i position sizing.

    Instancja powinna być tworzona na startup i reużywana (singleton w collector.py).
    Stan cooldown/streak jest przechowywany w _CooldownTracker (w pamięci).
    """

    def __init__(self, cfg):
        """
        Args:
            cfg: TradeConfig
        """
        self.cfg = cfg
        self._tracker = _cooldown_tracker

    def evaluate(
        self,
        db: Session,
        symbol: str,
        entry_price: float,
        atr: float,
        account: AccountState,
        open_positions: Optional[List[PositionMeta]] = None,
        meta=None,                  # SymbolMeta
        mode: str = "demo",
    ) -> RiskGateResult:
        """
        Pełna ocena ryzyka dla planowanego wejścia.

        Args:
            db:             Session DB (do odczytu orders/positions)
            symbol:         symbol np. 'BTCUSDC'
            entry_price:    planowana cena wejścia
            atr:            Average True Range (entry timeframe)
            account:        stan konta
            open_positions: lista aktualnych otwartych pozycji
            meta:           SymbolMeta z symbol_filter
            mode:           'demo' | 'live'

        Returns:
            RiskGateResult
        """
        cfg = self.cfg
        result = RiskGateResult(is_allowed=False)
        open_pos = open_positions or []

        # ── 1. Kill switch ─────────────────────────────────────────────────
        if not cfg.execution_enabled:
            result.reason_code = "kill_switch_active"
            result.reason_pl = _REASON_PL["kill_switch_active"]
            return result

        # ── 2. Duplikat pozycji na symbolu ──────────────────────────────────
        for pos in open_pos:
            if pos.symbol == symbol and pos.quantity > 0:
                result.reason_code = "symbol_has_open_position"
                result.reason_pl = _REASON_PL["symbol_has_open_position"]
                result.details["existing_qty"] = pos.quantity
                result.details["existing_entry"] = pos.entry_price
                return result

        # ── 3. Cooldown po streak strat ─────────────────────────────────────
        in_cd, cd_remaining = self._tracker.is_in_cooldown(symbol)
        if in_cd:
            result.reason_code = "cooldown_after_loss_streak"
            result.reason_pl = _REASON_PL["cooldown_after_loss_streak"]
            result.cooldown_remaining_sec = cd_remaining
            result.details["cooldown_remaining_sec"] = cd_remaining
            return result

        # ── 4. Max open positions ────────────────────────────────────────────
        active_count = sum(1 for p in open_pos if p.quantity > 0)
        if active_count >= cfg.max_open_positions:
            result.reason_code = "max_positions_reached"
            result.reason_pl = _REASON_PL["max_positions_reached"]
            result.details["active_count"] = active_count
            result.details["max_allowed"] = cfg.max_open_positions
            return result

        # ── 5. Max trades per day ────────────────────────────────────────────
        daily_count = self._count_daily_trades(db, mode)
        if daily_count >= cfg.max_trades_per_day:
            result.reason_code = "max_trades_per_day"
            result.reason_pl = _REASON_PL["max_trades_per_day"]
            result.details["daily_count"] = daily_count
            result.details["max_allowed"] = cfg.max_trades_per_day
            return result

        # ── 6. Dzienny limit strat ───────────────────────────────────────────
        equity = max(account.equity, account.initial_balance, 1.0)
        daily_pnl = account.realized_pnl_24h + account.unrealized_pnl
        daily_loss_limit = -equity * cfg.max_daily_drawdown_pct / 100.0
        if daily_pnl <= daily_loss_limit:
            result.reason_code = "daily_loss_limit_hit"
            result.reason_pl = _REASON_PL["daily_loss_limit_hit"]
            result.details["daily_pnl"] = round(daily_pnl, 4)
            result.details["limit"] = round(daily_loss_limit, 4)
            return result

        # ── 7. Tygodniowy limit strat ────────────────────────────────────────
        weekly_pnl = account.realized_pnl_7d
        weekly_loss_limit = -equity * cfg.max_weekly_drawdown_pct / 100.0
        if weekly_pnl <= weekly_loss_limit:
            result.reason_code = "weekly_loss_limit_hit"
            result.reason_pl = _REASON_PL["weekly_loss_limit_hit"]
            result.details["weekly_pnl"] = round(weekly_pnl, 4)
            result.details["limit"] = round(weekly_loss_limit, 4)
            return result

        # ── 8. Ekspozycja łączna portfela ────────────────────────────────────
        total_exposed = sum(p.quantity * p.current_price for p in open_pos if p.current_price > 0)
        max_total_exposure = equity * cfg.max_total_exposure_pct / 100.0
        if total_exposed >= max_total_exposure:
            result.reason_code = "max_total_exposure_hit"
            result.reason_pl = _REASON_PL["max_total_exposure_hit"]
            result.details["total_exposed"] = round(total_exposed, 2)
            result.details["max_allowed"] = round(max_total_exposure, 2)
            return result

        # ── 9. Ekspozycja na symbol ──────────────────────────────────────────
        symbol_exposed = sum(
            p.quantity * p.current_price for p in open_pos
            if p.symbol == symbol and p.current_price > 0
        )
        max_symbol_exposure = equity * cfg.max_exposure_per_symbol_pct / 100.0
        if symbol_exposed >= max_symbol_exposure:
            result.reason_code = "max_symbol_exposure_hit"
            result.reason_pl = _REASON_PL["max_symbol_exposure_hit"]
            result.details["symbol_exposed"] = round(symbol_exposed, 2)
            result.details["max_allowed"] = round(max_symbol_exposure, 2)
            return result

        # ── 10. ATR guard ────────────────────────────────────────────────────
        if atr <= 0 or entry_price <= 0:
            result.reason_code = "no_atr_for_sizing"
            result.reason_pl = _REASON_PL["no_atr_for_sizing"]
            return result

        # ── 11. Position sizing (ATR-based) ──────────────────────────────────
        sl_distance = atr * cfg.atr_stop_multiplier
        stop_loss_price = entry_price - sl_distance

        # Kwota ryzyka per trade = equity × risk_per_trade_pct%
        risk_amount = equity * cfg.risk_per_trade_pct / 100.0

        # qty = risk_amount / sl_distance
        qty_by_risk = risk_amount / sl_distance if sl_distance > 0 else 0.0

        # Max position per symbol cap
        max_notional_by_exposure = max_symbol_exposure - symbol_exposed
        qty_by_exposure = max_notional_by_exposure / entry_price if entry_price > 0 else 0.0

        # Cap do dostępnego kapitału (z buforem 1% na fee)
        available_for_trade = account.available_cash * 0.99
        qty_by_cash = available_for_trade / entry_price if entry_price > 0 else 0.0

        # Wybierz minimalny (nigdy nie przekraczaj limitów)
        qty = min(qty_by_risk, qty_by_exposure, qty_by_cash)

        # Nie podbijamy qty do minimum notional kosztem ryzyka.
        # Jeśli policzony rozmiar jest zbyt mały, wejście blokujemy.
        raw_notional = qty * entry_price
        if qty <= 0 or raw_notional < cfg.min_buy_notional:
            result.reason_code = "qty_too_small"
            result.reason_pl = _REASON_PL["qty_too_small"]
            result.details["qty_by_risk"] = round(qty_by_risk, 8)
            result.details["qty_by_exposure"] = round(qty_by_exposure, 8)
            result.details["qty_by_cash"] = round(qty_by_cash, 8)
            result.details["notional_by_limits"] = round(raw_notional, 4)
            result.details["min_buy_notional"] = cfg.min_buy_notional
            return result

        # Zaokrąglij do step_size (floor)
        if meta and meta.step_size and meta.step_size > 0:
            step = meta.step_size
            qty = math.floor(qty / step) * step
            prec = max(0, -int(math.floor(math.log10(step))))
            qty = round(qty, prec)

        if qty <= 0 or qty * entry_price < cfg.min_order_notional:
            result.reason_code = "qty_too_small"
            result.reason_pl = _REASON_PL["qty_too_small"]
            result.details["qty_by_risk"] = round(qty_by_risk, 8)
            result.details["qty_by_exposure"] = round(qty_by_exposure, 8)
            result.details["qty_by_cash"] = round(qty_by_cash, 8)
            result.details["available_cash"] = round(account.available_cash, 4)
            result.details["min_order_notional"] = cfg.min_order_notional
            return result

        # Check czy dostępna gotówka jest wystarczająca
        required_cash = qty * entry_price
        if required_cash > account.available_cash * 1.05:  # 5% tolerancja
            result.reason_code = "insufficient_cash"
            result.reason_pl = _REASON_PL["insufficient_cash"]
            result.details["required"] = round(required_cash, 4)
            result.details["available"] = round(account.available_cash, 4)
            return result

        # ── 12. Wylicz TP/SL ─────────────────────────────────────────────────
        take_profit_1 = entry_price + atr * cfg.atr_take_multiplier
        take_profit_2 = entry_price + atr * cfg.atr_take_multiplier * 1.5
        trailing_activation = entry_price + atr * cfg.atr_stop_multiplier
        break_even = entry_price + atr * 0.5  # przesuwamy SL na BE po 0.5×ATR zysku

        expected_reward = (take_profit_1 - entry_price) * qty

        result.is_allowed = True
        result.reason_code = "risk_gate_passed"
        result.recommended_qty = qty
        result.recommended_notional = qty * entry_price
        result.stop_loss_price = stop_loss_price
        result.take_profit_price = take_profit_1
        result.take_profit_2_price = take_profit_2
        result.trailing_activation_price = trailing_activation
        result.break_even_price = break_even
        result.risk_amount = risk_amount
        result.expected_reward = expected_reward
        result.details.update({
            "qty_by_risk": round(qty_by_risk, 8),
            "qty_by_exposure": round(qty_by_exposure, 8),
            "qty_by_cash": round(qty_by_cash, 8),
            "final_qty": qty,
            "notional": round(qty * entry_price, 4),
            "atr": round(atr, 8),
            "sl_distance": round(sl_distance, 8),
            "risk_pct": cfg.risk_per_trade_pct,
            "equity": round(equity, 4),
        })

        logger.debug(
            "RiskEngine.evaluate: %s ALLOWED qty=%.8g sl=%.6f tp=%.6f risk=%.4f",
            symbol, qty, stop_loss_price, take_profit_1, risk_amount,
        )

        return result

    def _count_daily_trades(self, db: Session, mode: str) -> int:
        """Liczba transakcji BUY dziś dla danego mode."""
        try:
            from backend.database import Order
            from datetime import timezone
            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).replace(tzinfo=None)
            return (
                db.query(Order)
                .filter(
                    Order.mode == mode,
                    Order.side == "BUY",
                    Order.timestamp >= cutoff,
                    Order.status.in_(["FILLED", "PARTIALLY_FILLED"]),
                )
                .count()
            )
        except Exception:
            return 0

    def on_trade_result(self, symbol: str, pnl: float) -> None:
        """
        Powiadom silnik o wyniku transakcji.
        Wywoływać po zamknięciu pozycji (z net_pnl).
        """
        if pnl < 0:
            self._tracker.on_loss(
                symbol,
                max_streak=self.cfg.max_losing_streak,
                cooldown_sec=self.cfg.cooldown_after_loss_streak_min * 60,
            )
        else:
            self._tracker.on_win(symbol)

    def get_symbol_state(self, symbol: str) -> Dict[str, Any]:
        """Zwróć stan cooldown/streak dla symbolu."""
        in_cd, remaining = self._tracker.is_in_cooldown(symbol)
        state = self._tracker.get(symbol)
        return {
            "symbol": symbol,
            "loss_streak": state.get("loss_streak", 0),
            "win_streak": state.get("win_streak", 0),
            "in_cooldown": in_cd,
            "cooldown_remaining_sec": remaining,
        }

    def reset_symbol(self, symbol: str) -> None:
        """Wyczyść cooldown/streak dla symbolu (np. po manual override)."""
        self._tracker.reset(symbol)
        logger.info("RiskEngine: reset_symbol %s", symbol)


def build_account_state(
    db: Session,
    mode: str = "demo",
    binance_client=None,
) -> AccountState:
    """
    Zbuduj AccountState z DB (demo) lub Binance API (live).

    Args:
        db:             Session DB
        mode:           'demo' | 'live'
        binance_client: do saldów live (wymagane dla mode='live')
    """
    from backend.database import Position, Order

    try:
        now = datetime.utcnow()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)

        # Otwarte pozycje
        open_pos = (
            db.query(Position)
            .filter(
                Position.mode == mode,
                Position.exit_reason_code.is_(None),
                Position.quantity > 0,
            )
            .all()
        )

        positions_count = len(open_pos)
        positions_value = sum(
            float(p.current_price or p.entry_price or 0) * float(p.quantity or 0)
            for p in open_pos
        )
        unrealized_pnl = sum(float(p.unrealized_pnl or 0) for p in open_pos)

        # PnL zrealizowany
        closed_orders_24h = (
            db.query(Order)
            .filter(
                Order.mode == mode,
                Order.side == "SELL",
                Order.status.in_(["FILLED", "PARTIALLY_FILLED"]),
                Order.timestamp >= cutoff_24h,
            )
            .all()
        )
        realized_pnl_24h = sum(float(o.net_pnl or 0) for o in closed_orders_24h if hasattr(o, 'net_pnl'))

        closed_orders_7d = (
            db.query(Order)
            .filter(
                Order.mode == mode,
                Order.side == "SELL",
                Order.status.in_(["FILLED", "PARTIALLY_FILLED"]),
                Order.timestamp >= cutoff_7d,
            )
            .all()
        )
        realized_pnl_7d = sum(float(o.net_pnl or 0) for o in closed_orders_7d if hasattr(o, 'net_pnl'))

        if mode == "live" and binance_client:
            balances = binance_client.get_balances() or []
            cash = 0.0
            for b in balances:
                asset = (b.get("asset") or "").upper()
                if asset in ("EUR", "USDC", "USDT"):
                    cash += float(b.get("free", 0) or 0)
            equity = cash + positions_value
            initial_balance = max(equity, 1.0)
        else:
            # Demo — z DB
            try:
                from backend.portfolio_engine import compute_demo_account_state
                from backend.quote_currency import get_demo_quote_ccy
                state = compute_demo_account_state(db, quote_ccy=get_demo_quote_ccy(), now=now)
                cash = float(state.get("cash") or 0)
                equity = float(state.get("equity") or cash)
                initial_balance = float(
                    state.get("initial_balance")
                    or float(__import__("os").getenv("DEMO_INITIAL_BALANCE", "10000"))
                )
            except Exception:
                cash = 0.0
                equity = 0.0
                initial_balance = 10000.0

        return AccountState(
            equity=equity,
            available_cash=cash,
            positions_count=positions_count,
            positions_value=positions_value,
            realized_pnl_24h=realized_pnl_24h,
            realized_pnl_7d=realized_pnl_7d,
            unrealized_pnl=unrealized_pnl,
            initial_balance=initial_balance,
        )

    except Exception as exc:
        logger.error("build_account_state: błąd: %s", exc)
        return AccountState()


def build_open_positions(db: Session, mode: str = "demo") -> List[PositionMeta]:
    """Pobierz listę otwartych pozycji jako PositionMeta."""
    from backend.database import Position
    try:
        rows = (
            db.query(Position)
            .filter(
                Position.mode == mode,
                Position.exit_reason_code.is_(None),
                Position.quantity > 0,
            )
            .all()
        )
        return [
            PositionMeta(
                symbol=p.symbol or "",
                quantity=float(p.quantity or 0),
                entry_price=float(p.entry_price or 0),
                current_price=float(p.current_price or p.entry_price or 0),
                unrealized_pnl=float(p.unrealized_pnl or 0),
            )
            for p in rows
        ]
    except Exception as exc:
        logger.error("build_open_positions: błąd: %s", exc)
        return []
