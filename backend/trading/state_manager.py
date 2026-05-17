"""
state_manager.py — Reconcile Binance↔DB i recovery po restarcie.

Odpowiada za:
  1. Reconcile pozycji (Binance balances vs DB positions)
  2. Wykrywanie osieroconych zleceń (EXCHANGE_SUBMITTED bez potwierdzenia z Binance)
  3. Recovery na starcie (query open orders Binance → aktualizacja DB)
  4. Polling fill statusu dla EXCHANGE_SUBMITTED orders
  5. Dust detection (wartość poniżej min_notional → ignoruj)

Każde zdarzenie reconcile jest logowane do decision_traces.

Użycie:
    from backend.trading.state_manager import StateManager
    sm = StateManager(cfg, binance_client)

    # Na starcie serwera
    sm.recover_on_startup(db)

    # W każdym cyklu
    sm.check_pending_fills(db, mode='live')
    sm.reconcile_live_positions(db)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database import utc_now_naive

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Wynik reconcile sesji."""
    orphan_orders_found: int = 0
    orphan_orders_fixed: int = 0
    positions_reconciled: int = 0
    positions_discrepancy: int = 0
    fills_detected: int = 0
    errors: List[str] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)


class StateManager:
    """
    Zarządza spójnością stanu między Binance a lokalną bazą danych.

    Cykl działania:
      1. recover_on_startup — wywołaj raz na start procesu
      2. check_pending_fills — wywołaj co N sekund (np. 30s) dla otwartych zleceń
      3. reconcile_live_positions — wywołaj co M minut (np. 5 min) w trybie live
    """

    def __init__(self, cfg, binance_client):
        self.cfg = cfg
        self.binance = binance_client
        self._last_reconcile_ts: float = 0.0

    def _reconcile_interval_sec(self) -> float:
        """Kanoniczny interwał reconcile z fallbackiem dla starszych testów/configu."""
        interval = getattr(self.cfg, "reconcile_interval_sec", None)
        if interval is None:
            interval = getattr(self.cfg, "sync_interval_sec", 300.0)
        try:
            return float(interval)
        except (TypeError, ValueError):
            return 300.0

    # ─────────────────────────────────────────────────────────────────────────
    # 1. RECOVERY NA STARCIE
    # ─────────────────────────────────────────────────────────────────────────

    def recover_on_startup(self, db: Session, mode: str = "live") -> ReconcileResult:
        """
        Na starcie serwera pobiera wszystkie otwarte zlecenia z Binance
        i aktualizuje DB, aby uniknąć osieroconych orderów.

        Wywołaj jednokrotnie po inicjalizacji DataCollector.
        """
        result = ReconcileResult()

        if mode != "live":
            return result

        logger.info("StateManager.recover_on_startup: rozpoczynam recovery...")

        try:
            # Pobierz otwarte zlecenia z Binance (wszystkie symbole)
            open_orders = self._get_open_orders_binance(symbol=None)
            logger.info("Binance open orders: %d", len(open_orders))

            # Zbuduj mapę orderId → order_data
            binance_order_map: Dict[str, Dict] = {
                str(o.get("orderId", "")): o
                for o in open_orders
            }

            # Sprawdź EXCHANGE_SUBMITTED orders w DB
            from backend.database import PendingOrder
            db_orders = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.status.in_(["EXCHANGE_SUBMITTED", "PENDING_CONFIRMED", "CONFIRMED"]),
                )
                .all()
            )

            for db_order in db_orders:
                eid = str(db_order.exchange_order_id or "")

                if not eid:
                    # DB order bez exchange_order_id → nie wiemy czy wysłany → orphan candidate
                    result.details.append({
                        "type": "no_exchange_id",
                        "db_id": db_order.id,
                        "symbol": db_order.symbol,
                        "status": db_order.status,
                    })
                    continue

                if eid in binance_order_map:
                    # Order nadal otwarty na Binance — aktualizuj status
                    b_order = binance_order_map[eid]
                    b_status = b_order.get("status", "")
                    if b_status in ("CANCELED", "EXPIRED", "REJECTED"):
                        db_order.status = f"CANCELLED_BY_EXCHANGE_{b_status}"
                        db.add(db_order)
                        result.orphan_orders_fixed += 1
                        result.details.append({
                            "type": "exchange_cancelled",
                            "symbol": db_order.symbol,
                            "exchange_id": eid,
                            "binance_status": b_status,
                        })
                else:
                    # Order nie ma odpowiednika na Binance
                    # Może być FILLED lub CANCELLED — zapytaj bezpośrednio
                    filled = self._query_order_status(db_order.symbol, eid)
                    if filled:
                        b_status = filled.get("status", "UNKNOWN")
                        if b_status == "FILLED":
                            db_order.status = "FILLED_CONFIRMED"
                            db.add(db_order)
                            result.fills_detected += 1
                            result.details.append({
                                "type": "fill_recovered",
                                "symbol": db_order.symbol,
                                "exchange_id": eid,
                                "executed_qty": filled.get("executedQty"),
                                "price": filled.get("cummulativeQuoteQty"),
                            })
                        elif b_status in ("CANCELED", "EXPIRED", "REJECTED"):
                            db_order.status = f"CANCELLED_{b_status}"
                            db.add(db_order)
                            result.orphan_orders_fixed += 1
                        else:
                            result.details.append({
                                "type": "unknown_status",
                                "symbol": db_order.symbol,
                                "exchange_id": eid,
                                "binance_status": b_status,
                            })

            db.commit()
            result.orphan_orders_found = len(db_orders)
            logger.info(
                "StateManager.recover_on_startup: fills=%d orphans_fixed=%d",
                result.fills_detected, result.orphan_orders_fixed,
            )

        except Exception as exc:
            logger.error("recover_on_startup: błąd: %s", exc)
            result.errors.append(str(exc))

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 2. POLLING FILL STATUSU
    # ─────────────────────────────────────────────────────────────────────────

    def check_pending_fills(self, db: Session, mode: str = "live") -> ReconcileResult:
        """
        Sprawdź statusy EXCHANGE_SUBMITTED orders i wykryj FILL.

        Wywołuj co 30s (cykl DB). Nie wysyła zleceń — tylko odczytuje.
        """
        result = ReconcileResult()

        if mode != "live":
            return result

        try:
            from backend.database import PendingOrder

            pending_rows = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.status == "EXCHANGE_SUBMITTED",
                )
                .all()
            )

            if not pending_rows:
                return result

            for pending in pending_rows:
                eid = str(pending.exchange_order_id or "")
                if not eid:
                    continue

                # Grace period: skip jeśli order złożony < 10s temu
                if pending.created_at:
                    age = (utc_now_naive() - pending.created_at).total_seconds()
                    if age < 10:
                        continue

                filled = self._query_order_status(pending.symbol, eid)
                if not filled:
                    continue

                b_status = filled.get("status", "")

                if b_status == "FILLED":
                    exec_price = self._parse_exec_price(filled)
                    exec_qty = float(filled.get("executedQty", 0) or 0)

                    pending.status = "FILLED"
                    pending.exec_price = exec_price
                    pending.exec_qty = exec_qty
                    pending.filled_at = utc_now_naive()
                    db.add(pending)
                    result.fills_detected += 1
                    result.details.append({
                        "type": "fill",
                        "symbol": pending.symbol,
                        "side": pending.side,
                        "exchange_id": eid,
                        "exec_price": exec_price,
                        "exec_qty": exec_qty,
                    })
                    logger.info(
                        "FILL wykryty: %s %s id=%s qty=%.8g @%.6f",
                        pending.symbol, pending.side, eid, exec_qty, exec_price,
                    )

                elif b_status == "PARTIALLY_FILLED":
                    exec_qty = float(filled.get("executedQty", 0) or 0)
                    exec_price = self._parse_exec_price(filled)
                    pending.status = "PARTIALLY_FILLED"
                    pending.exec_price = exec_price
                    pending.exec_qty = exec_qty
                    db.add(pending)
                    result.details.append({
                        "type": "partial_fill",
                        "symbol": pending.symbol,
                        "side": pending.side,
                        "exchange_id": eid,
                        "exec_qty": exec_qty,
                    })

                elif b_status in ("CANCELED", "EXPIRED", "REJECTED"):
                    pending.status = f"CANCELLED_{b_status}"
                    db.add(pending)
                    result.orphan_orders_fixed += 1
                    logger.warning(
                        "Order anulowany na Binance: %s id=%s status=%s",
                        pending.symbol, eid, b_status,
                    )

            db.commit()

        except Exception as exc:
            logger.error("check_pending_fills: błąd: %s", exc)
            result.errors.append(str(exc))

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 3. RECONCILE LIVE POSITIONS
    # ─────────────────────────────────────────────────────────────────────────

    def reconcile_live_positions(
        self,
        db: Session,
        force: bool = False,
    ) -> ReconcileResult:
        """
        Porównaj salda Binance z otwartymi pozycjami w DB.

        Wykonywany co cfg.sync_interval_sec sekund (domyślnie 300s = 5 min).

        Wykrywa:
          - Pozycje w DB bez pokrycia w saldzie Binance → oznacz jako orphan
          - Salda Binance bez pozycji w DB → loguj jako discrepancy (nie tworzy auto)
          - Różnice ilości > tolerance → loguj discrepancy
        """
        result = ReconcileResult()
        now = time.monotonic()

        if not force and (now - self._last_reconcile_ts) < self._reconcile_interval_sec():
            return result

        self._last_reconcile_ts = now

        try:
            from backend.database import Position

            # Aktywne pozycje w DB (live)
            db_positions = (
                db.query(Position)
                .filter(
                    Position.mode == "live",
                    Position.exit_reason_code.is_(None),
                    Position.quantity > 0,
                )
                .all()
            )

            # Pobierz faktyczne salda z Binance
            binance_balances = self._get_binance_balances()
            balance_map: Dict[str, float] = {
                b["asset"].upper(): float(b.get("free", 0) or 0) + float(b.get("locked", 0) or 0)
                for b in binance_balances
                if float(b.get("free", 0) or 0) + float(b.get("locked", 0) or 0) > 0
            }

            for pos in db_positions:
                symbol = pos.symbol or ""
                base_asset = self._symbol_to_base(symbol)
                db_qty = float(pos.quantity or 0)
                binance_qty = balance_map.get(base_asset, 0.0)

                # Pobierz aktualną cenę dla wartości notional
                current_price = self._get_mark_price(symbol) or float(pos.entry_price or 0)
                notional = binance_qty * current_price

                # Dust check — poniżej min_notional ignoruj rozbieżność
                if notional < self.cfg.min_order_notional:
                    continue

                tolerance = 0.01  # 1% tolerancja na rozbieżność qty
                if binance_qty > db_qty * (1 + tolerance):
                    result.positions_discrepancy += 1
                    result.details.append({
                        "type": "qty_discrepancy_high",
                        "symbol": symbol,
                        "base": base_asset,
                        "db_qty": db_qty,
                        "binance_qty": binance_qty,
                        "diff_pct": round((binance_qty - db_qty) / max(db_qty, 1e-10) * 100, 2),
                    })
                    logger.warning(
                        "RECONCILE DISCREPANCY: %s db_qty=%.8g binance_qty=%.8g",
                        symbol, db_qty, binance_qty,
                    )
                elif binance_qty < db_qty * (1 - tolerance):
                    # Binance ma mniej niż DB — pozycja mogła być zamknięta zewnętrznie
                    result.positions_discrepancy += 1
                    if binance_qty < 1e-9:
                        # Saldo zerowe → oznacz pozycję jako closed
                        pos.exit_reason_code = "closed_externally_reconcile"
                        pos.closed_at = utc_now_naive()
                        db.add(pos)
                        logger.warning(
                            "RECONCILE: pozycja %s DB qty=%.8g ale Binance=0 → oznaczam closed",
                            symbol, db_qty,
                        )
                    else:
                        result.details.append({
                            "type": "qty_discrepancy_low",
                            "symbol": symbol,
                            "db_qty": db_qty,
                            "binance_qty": binance_qty,
                        })

                # Zaktualizuj current_price w DB
                if current_price > 0:
                    pos.current_price = current_price
                    unrealized = (current_price - float(pos.entry_price or current_price)) * db_qty
                    pos.unrealized_pnl = unrealized
                    db.add(pos)

                result.positions_reconciled += 1

            db.commit()

            logger.info(
                "StateManager.reconcile: reconciled=%d discrepancies=%d",
                result.positions_reconciled, result.positions_discrepancy,
            )

        except Exception as exc:
            logger.error("reconcile_live_positions: błąd: %s", exc)
            result.errors.append(str(exc))

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 4. ORPHAN DETECTION
    # ─────────────────────────────────────────────────────────────────────────

    def detect_orphan_orders(
        self,
        db: Session,
        mode: str = "live",
    ) -> ReconcileResult:
        """
        Znajdź EXCHANGE_SUBMITTED orders starsze niż orphan_order_ttl_sec
        bez odpowiednika na Binance → oznacz jako orphan.
        """
        result = ReconcileResult()

        if mode != "live":
            return result

        try:
            from backend.database import PendingOrder

            ttl = self.cfg.orphan_order_ttl_sec
            cutoff = utc_now_naive() - timedelta(seconds=ttl)

            orphan_candidates = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.status == "EXCHANGE_SUBMITTED",
                    PendingOrder.created_at < cutoff,
                )
                .all()
            )

            for pending in orphan_candidates:
                eid = str(pending.exchange_order_id or "")
                if not eid:
                    pending.status = "ORPHAN_NO_EXCHANGE_ID"
                    db.add(pending)
                    result.orphan_orders_found += 1
                    continue

                # Zapytaj Binance
                filled = self._query_order_status(pending.symbol, eid)
                if not filled:
                    # Brak odpowiedzi lub order nie istnieje
                    pending.status = "ORPHAN_NOT_FOUND_ON_EXCHANGE"
                    db.add(pending)
                    result.orphan_orders_found += 1
                    logger.warning(
                        "ORPHAN: %s id=%s nie znaleziony na Binance",
                        pending.symbol, eid,
                    )
                else:
                    b_status = filled.get("status", "")
                    if b_status == "FILLED":
                        exec_price = self._parse_exec_price(filled)
                        exec_qty = float(filled.get("executedQty", 0) or 0)
                        pending.status = "FILLED"
                        pending.exec_price = exec_price
                        pending.exec_qty = exec_qty
                        pending.filled_at = utc_now_naive()
                        db.add(pending)
                        result.fills_detected += 1
                        logger.info(
                            "ORPHAN FILL odzyskany: %s id=%s qty=%.8g @%.6f",
                            pending.symbol, eid, exec_qty, exec_price,
                        )
                    elif b_status in ("CANCELED", "EXPIRED", "REJECTED"):
                        pending.status = f"ORPHAN_CANCELLED_{b_status}"
                        db.add(pending)
                        result.orphan_orders_fixed += 1

            db.commit()

        except Exception as exc:
            logger.error("detect_orphan_orders: błąd: %s", exc)
            result.errors.append(str(exc))

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_open_orders_binance(self, symbol: Optional[str] = None) -> List[Dict]:
        """Pobierz otwarte zlecenia z Binance (wszystkie lub per symbol)."""
        try:
            if hasattr(self.binance, "get_open_orders"):
                return self.binance.get_open_orders(symbol=symbol) or []
            elif hasattr(self.binance, "client"):
                kwargs = {"symbol": symbol} if symbol else {}
                return self.binance.client.get_open_orders(**kwargs) or []
        except Exception as exc:
            logger.error("_get_open_orders_binance: %s", exc)
        return []

    def _query_order_status(self, symbol: str, order_id: str) -> Optional[Dict]:
        """Zapytaj Binance o status konkretnego zlecenia."""
        try:
            if hasattr(self.binance, "get_order"):
                return self.binance.get_order(symbol=symbol, order_id=order_id)
            elif hasattr(self.binance, "client"):
                return self.binance.client.get_order(
                    symbol=symbol, orderId=int(order_id)
                )
        except Exception as exc:
            # Order nie istnieje lub błąd sieci
            logger.debug("_query_order_status %s id=%s: %s", symbol, order_id, exc)
        return None

    def _get_binance_balances(self) -> List[Dict]:
        """Pobierz salda z Binance."""
        try:
            if hasattr(self.binance, "get_balances"):
                return self.binance.get_balances() or []
            elif hasattr(self.binance, "client"):
                info = self.binance.client.get_account() or {}
                return info.get("balances", [])
        except Exception as exc:
            logger.error("_get_binance_balances: %s", exc)
        return []

    def _get_mark_price(self, symbol: str) -> float:
        """Pobierz ostatnią cenę z Binance."""
        try:
            if hasattr(self.binance, "get_price"):
                return float(self.binance.get_price(symbol) or 0)
            elif hasattr(self.binance, "client"):
                r = self.binance.client.get_symbol_ticker(symbol=symbol) or {}
                return float(r.get("price", 0) or 0)
        except Exception:
            pass
        return 0.0

    def _symbol_to_base(self, symbol: str) -> str:
        """
        Wyciągnij base asset z symbolu Binance.
        Uwaga: bez meta to heurystyka. W pełnej implementacji użyj SymbolMeta.base_asset.
        """
        for quote in ("USDT", "USDC", "BUSD", "EUR", "BTC", "ETH", "BNB"):
            if symbol.endswith(quote):
                return symbol[: -len(quote)]
        # Fallback: usuń ostatnie 4 znaki
        return symbol[:-4] if len(symbol) > 4 else symbol

    def _parse_exec_price(self, order: Dict) -> float:
        """
        Wylicz faktyczną cenę wykonania z cummulativeQuoteQty / executedQty.
        Bardziej precyzyjne niż price z nagłówka.
        """
        try:
            quote_qty = float(order.get("cummulativeQuoteQty", 0) or 0)
            exec_qty = float(order.get("executedQty", 0) or 0)
            if exec_qty > 0 and quote_qty > 0:
                return quote_qty / exec_qty
            return float(order.get("price", 0) or 0)
        except Exception:
            return float(order.get("price", 0) or 0)
