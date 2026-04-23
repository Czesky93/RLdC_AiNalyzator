"""
Portfolio Reconcile — DB self-heal z Binance.

Porównuje stan DB (pozycje, pending ordery, salda) z realnym stanem konta Binance.
Wykrywa i naprawia niezgodności, w tym manualne transakcje wykonane poza botem.

Source of truth = Binance.
Każda naprawa ma audit trail (ReconciliationRun + ReconciliationEvent).
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.database import (
    ManualTradeDetection,
    Order,
    PendingOrder,
    Position,
    ReconciliationEvent,
    ReconciliationRun,
    SessionLocal,
    SystemLog,
    utc_now_naive,
)

logger = logging.getLogger(__name__)

_RECONCILE_LOCK = threading.Lock()
_last_reconcile_ts: Optional[datetime] = None
_RECONCILE_MIN_INTERVAL_SECONDS = int(os.getenv("RECONCILE_MIN_INTERVAL_SECONDS", "30"))

# Minimalna wartość pozycji w USDC żeby uznać ją za realną (dust guard)
_DUST_THRESHOLD_USDC = float(os.getenv("RECONCILE_DUST_THRESHOLD_USDC", "5.0"))

# Symbole które ignorujemy podczas reconcylacji (np. stablecoiny, EUR bal)
_SKIP_RECONCILE_SYMBOLS = {"USDC", "USDT", "EUR", "BUSD", "FDUSD", "TUSD"}


def _log(msg: str, level: str = "INFO", db: Optional[Session] = None) -> None:
    getattr(logger, level.lower(), logger.info)(msg)
    if db is not None:
        try:
            db.add(
                SystemLog(
                    level=level,
                    module="portfolio_reconcile",
                    message=msg[:500],
                )
            )
            db.flush()
        except Exception:
            pass


def _get_binance_client():
    """Zwróć klienta Binance lub None jeśli brak konfiguracji."""
    try:
        from backend.binance_client import get_binance_client

        return get_binance_client()
    except Exception as exc:
        logger.warning("Nie można pobrać klienta Binance: %s", exc)
        return None


def _get_binance_balances() -> Dict[str, float]:
    """Pobierz mapę asset→total z Binance. Zwraca {} przy błędzie."""
    client = _get_binance_client()
    if client is None:
        return {}
    try:
        balances = client.get_balances()
        result: Dict[str, float] = {}
        for b in (balances or []):
            asset = str(b.get("asset") or "").upper()
            total = float(b.get("total") or 0.0)
            if total > 0:
                result[asset] = total
        return result
    except Exception as exc:
        logger.warning("Błąd pobierania sald Binance: %s", exc)
        return {}


def _get_binance_open_orders(symbol: Optional[str] = None) -> List[Dict]:
    """Pobierz otwarte ordery z Binance."""
    client = _get_binance_client()
    if client is None:
        return []
    try:
        if symbol:
            return client.get_open_orders(symbol=symbol) or []
        return client.get_open_orders() or []
    except Exception as exc:
        logger.warning("Błąd pobierania otwartych orderów Binance: %s", exc)
        return []


def _get_binance_recent_trades(symbol: str, limit: int = 50) -> List[Dict]:
    """Pobierz ostatnie trades z Binance dla symbolu."""
    client = _get_binance_client()
    if client is None:
        return []
    try:
        return client.get_my_trades(symbol=symbol, limit=limit) or []
    except Exception as exc:
        logger.warning("Błąd pobierania trades Binance %s: %s", symbol, exc)
        return []


def _get_binance_order_status(symbol: str, order_id: int) -> Optional[Dict]:
    """Pobierz status konkretnego orderu z Binance."""
    client = _get_binance_client()
    if client is None:
        return None
    try:
        return client.get_order(symbol=symbol, orderId=order_id)
    except Exception as exc:
        logger.warning(
            "Błąd pobierania statusu orderu %s #%s: %s", symbol, order_id, exc
        )
        return None


def _get_ticker_price(symbol: str) -> float:
    """Pobierz bieżącą cenę symbolu."""
    client = _get_binance_client()
    if client is None:
        return 0.0
    try:
        from backend.quote_service import get_validated_quote

        quote = get_validated_quote(symbol, binance_client=client)
        return float((quote or {}).get("price") or 0.0)
    except Exception:
        return 0.0


def _resolve_eur_rate() -> float:
    """Kurs EUR/USDC do przeliczania wartości."""
    try:
        price = _get_ticker_price("EURUSDC")
        return price if price > 0.5 else 1.08
    except Exception:
        return 1.08


def _base_asset(symbol: str) -> str:
    sym = symbol.upper()
    for quote in ("USDC", "USDT", "EUR", "BTC", "ETH", "BNB", "BUSD"):
        if sym.endswith(quote):
            return sym[: -len(quote)]
    return sym


def _quote_asset(symbol: str) -> str:
    sym = symbol.upper()
    for quote in ("USDC", "USDT", "EUR", "BTC", "ETH", "BNB", "BUSD"):
        if sym.endswith(quote):
            return quote
    return "USDC"


# ---------------------------------------------------------------------------
# GŁÓWNA FUNKCJA — reconcile_with_binance
# ---------------------------------------------------------------------------


def reconcile_with_binance(
    db: Session,
    mode: str = "live",
    trigger: str = "scheduled",
    notify_telegram: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Porównuje stan DB z Binance i naprawia niezgodności.

    Returns:
        Dict z kluczami: run_id, events, repairs, manual_trades, summary, skipped_reason
    """
    global _last_reconcile_ts

    # Throttle — nie częściej niż co _RECONCILE_MIN_INTERVAL_SECONDS, chyba że force
    if not force and _last_reconcile_ts is not None:
        elapsed = (utc_now_naive() - _last_reconcile_ts).total_seconds()
        if elapsed < _RECONCILE_MIN_INTERVAL_SECONDS:
            return {
                "skipped_reason": "throttled",
                "elapsed_s": round(elapsed, 1),
                "min_interval_s": _RECONCILE_MIN_INTERVAL_SECONDS,
            }

    # Jeden reconcile naraz
    acquired = _RECONCILE_LOCK.acquire(blocking=False)
    if not acquired:
        return {"skipped_reason": "already_running"}

    run = ReconciliationRun(
        mode=mode,
        trigger=trigger,
        status="running",
        started_at=utc_now_naive(),
    )
    db.add(run)
    db.flush()
    run_id = run.id

    try:
        _last_reconcile_ts = utc_now_naive()
        events: List[Dict] = []
        repairs = 0
        manual_trades_count = 0

        _log(f"[reconcile] START run_id={run_id} mode={mode} trigger={trigger}", db=db)

        # Pobierz dane z Binance
        binance_balances = _get_binance_balances()
        if not binance_balances and mode == "live":
            _log(
                "[reconcile] Brak odpowiedzi Binance — pomijam reconcile",
                level="WARNING",
                db=db,
            )
            run.status = "failed"
            run.error = "binance_unavailable"
            run.finished_at = utc_now_naive()
            db.commit()
            return {"run_id": run_id, "skipped_reason": "binance_unavailable"}

        # 1. Napraw pending ordery (sprawdź czy nie zostały już wykonane/anulowane na Binance)
        pending_events, pending_repairs = _reconcile_pending_orders(
            db, run_id, mode, binance_balances
        )
        events.extend(pending_events)
        repairs += pending_repairs

        # 2. Napraw pozycje (sprawdź niezgodności qty, avg_price, osierocone pozycje)
        position_events, position_repairs, manual_count = _reconcile_positions(
            db, run_id, mode, binance_balances
        )
        events.extend(position_events)
        repairs += position_repairs
        manual_trades_count += manual_count

        # 3. Sprawdź saldo (balance mismatch)
        balance_events, balance_repairs = _reconcile_balances(
            db, run_id, mode, binance_balances
        )
        events.extend(balance_events)
        repairs += balance_repairs

        repaired_orders = sum(
            1 for ev in events if str(ev.get("event_type") or "").startswith("order_")
        )
        repaired_positions = sum(
            1
            for ev in events
            if ev.get("event_type")
            in {"orphan_position", "qty_mismatch", "duplicate_position"}
        )
        repaired_pending = sum(
            1
            for ev in events
            if "pending" in str(ev.get("event_type") or "")
        )
        orphaned_records = sum(
            1 for ev in events if ev.get("event_type") in {"orphan_position", "duplicate_position"}
        )

        summary = {
            "run_id": run_id,
            "mode": mode,
            "trigger": trigger,
            "events_total": len(events),
            "repairs": repairs,
            "repaired_orders": repaired_orders,
            "repaired_positions": repaired_positions,
            "repaired_pending": repaired_pending,
            "manual_trades_detected": manual_trades_count,
            "detected_manual_live": manual_trades_count if mode == "live" else 0,
            "detected_manual_demo": manual_trades_count if mode == "demo" else 0,
            "orphaned_records": orphaned_records,
            "binance_assets_count": len(binance_balances),
            "finished_at": utc_now_naive().isoformat(),
        }

        run.status = "completed"
        run.events_count = len(events)
        run.repairs_count = repairs
        run.manual_trades_detected = manual_trades_count
        run.summary_json = json.dumps(summary)
        run.finished_at = utc_now_naive()
        db.commit()

        _log(
            f"[reconcile] DONE run_id={run_id} events={len(events)} repairs={repairs} manual_trades={manual_trades_count}",
            db=db,
        )
        db.commit()

        if notify_telegram and (repairs > 0 or manual_trades_count > 0):
            _notify_telegram_reconcile(summary, events)

        return summary

    except Exception as exc:
        logger.exception("Błąd reconcile run_id=%s: %s", run_id, exc)
        try:
            run.status = "failed"
            run.error = str(exc)[:500]
            run.finished_at = utc_now_naive()
            db.commit()
        except Exception:
            pass
        return {"run_id": run_id, "error": str(exc)}
    finally:
        _RECONCILE_LOCK.release()


# ---------------------------------------------------------------------------
# RECONCILE — PENDING ORDERS
# ---------------------------------------------------------------------------


def _reconcile_pending_orders(
    db: Session, run_id: int, mode: str, binance_balances: Dict[str, float]
) -> Tuple[List[Dict], int]:
    """
    Sprawdź pending ordery w DB:
    - jeśli mają binance_order_id i są FILLED/CANCELED na Binance → zaktualizuj DB
    - jeśli są zbyt stare (> RECONCILE_PENDING_MAX_AGE_HOURS) → oznacz jako STALE/CANCELLED
    """
    events: List[Dict] = []
    repairs = 0
    max_age_h = int(os.getenv("RECONCILE_PENDING_MAX_AGE_HOURS", "24"))
    stale_cutoff = utc_now_naive() - timedelta(hours=max_age_h)

    active_statuses = [
        "PENDING_CREATED",
        "PENDING",
        "PENDING_CONFIRMED",
        "CONFIRMED",
        "EXCHANGE_SUBMITTED",
        "PARTIALLY_FILLED",
    ]
    pendings = (
        db.query(PendingOrder)
        .filter(
            PendingOrder.mode == mode,
            PendingOrder.status.in_(active_statuses),
        )
        .all()
    )

    for p in pendings:
        before = {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side,
            "status": p.status,
            "created_at": str(p.created_at),
        }

        expired_at = getattr(p, "expires_at", None)
        if expired_at and expired_at < utc_now_naive():
            p.status = "EXPIRED"
            p.confirmed_at = utc_now_naive()
            ev = _save_event(
                db,
                run_id=run_id,
                event_type="stale_pending_expired",
                symbol=p.symbol,
                mode=mode,
                before=before,
                after={"status": "EXPIRED"},
                action="db_updated",
                reason="pending przekroczył expires_at",
                repaired=True,
            )
            events.append(ev)
            repairs += 1
            continue

        # Zbyt stare pending bez potwierdzenia
        if (
            p.created_at
            and p.created_at < stale_cutoff
            and p.status in ("PENDING_CREATED", "PENDING")
        ):
            p.status = "CANCELLED"
            p.confirmed_at = utc_now_naive()
            ev = _save_event(
                db,
                run_id=run_id,
                event_type="stale_pending_cancelled",
                symbol=p.symbol,
                mode=mode,
                before=before,
                after={"status": "CANCELLED"},
                action="db_updated",
                reason=f"pending starszy niż {max_age_h}h bez potwierdzenia",
                repaired=True,
            )
            events.append(ev)
            repairs += 1

    try:
        db.commit()
    except Exception:
        db.rollback()

    return events, repairs


# ---------------------------------------------------------------------------
# RECONCILE — POZYCJE
# ---------------------------------------------------------------------------


def _reconcile_positions(
    db: Session,
    run_id: int,
    mode: str,
    binance_balances: Dict[str, float],
) -> Tuple[List[Dict], int, int]:
    """
    Porównaj otwarte pozycje w DB z rzeczywistymi saldami na Binance.

    - Pozycja w DB, brak na Binance → oznacz jako zamkniętą (exit_reason_code=reconcile_closed)
    - Pozycja na Binance, brak w DB → utwórz pozycję (manual_trade_detected)
    - Niezgodność qty > TOLERANCE → zaktualizuj qty z Binance

    Zwraca: (events, repairs, manual_trades_count)
    """
    events: List[Dict] = []
    repairs = 0
    manual_trades = 0

    qty_tolerance = float(os.getenv("RECONCILE_QTY_TOLERANCE_PCT", "2.0")) / 100.0
    eur_rate = _resolve_eur_rate()

    # Otwarte pozycje w DB
    open_positions = (
        db.query(Position)
        .filter(
            Position.mode == mode,
            Position.exit_reason_code.is_(None),
            Position.quantity > 0,
        )
        .all()
    )

    db_symbols: Dict[str, Position] = {p.symbol: p for p in open_positions}

    # Symbole dostępne na Binance (tylko te które mamy w DB lub mają > dust threshold)
    # Budujemy mapę: base_asset → (symbol_in_db, binance_qty)
    # dla każdej pozycji w DB sprawdzamy czy base_asset jest w balances
    reconciled_db_symbols = set()

    for symbol, pos in db_symbols.items():
        if symbol.upper() in _SKIP_RECONCILE_SYMBOLS:
            continue

        base = _base_asset(symbol)
        binance_qty = binance_balances.get(base, 0.0)
        db_qty = float(pos.quantity or 0.0)

        before = {
            "symbol": symbol,
            "db_qty": db_qty,
            "binance_qty": binance_qty,
            "entry_price": pos.entry_price,
        }

        # Sprawdź czy pozycja istnieje na Binance
        current_price = _get_ticker_price(symbol) if binance_qty > 0 else 0.0
        binance_value_usdc = binance_qty * current_price if current_price > 0 else 0.0

        if binance_qty < _DUST_THRESHOLD_USDC / max(current_price, 1.0):
            # Pozycja w DB, brak/pył na Binance → zamknij pozycję
            pos.exit_reason_code = "reconcile_closed_missing_on_binance"
            pos.quantity = 0.0
            pos.updated_at = utc_now_naive()
            ev = _save_event(
                db,
                run_id=run_id,
                event_type="orphan_position",
                symbol=symbol,
                mode=mode,
                before=before,
                after={
                    "exit_reason_code": "reconcile_closed_missing_on_binance",
                    "qty": 0,
                },
                action="db_closed",
                reason=f"Binance qty={binance_qty:.8g} < dust threshold, pozycja zamknięta",
                repaired=True,
            )
            events.append(ev)
            repairs += 1
            reconciled_db_symbols.add(symbol)
            continue

        reconciled_db_symbols.add(symbol)

        # Sprawdź niezgodność qty
        if db_qty > 0:
            diff_pct = abs(binance_qty - db_qty) / db_qty
            if diff_pct > qty_tolerance:
                old_qty = pos.quantity
                pos.quantity = binance_qty
                pos.updated_at = utc_now_naive()
                ev = _save_event(
                    db,
                    run_id=run_id,
                    event_type="qty_mismatch",
                    symbol=symbol,
                    mode=mode,
                    before=before,
                    after={"qty": binance_qty},
                    action="db_updated",
                    reason=f"qty DB={old_qty:.8g} vs Binance={binance_qty:.8g} ({diff_pct*100:.1f}%)",
                    repaired=True,
                )
                events.append(ev)
                repairs += 1

    # Pozycje na Binance, których nie ma w DB (manualne BUY)
    if mode == "live":
        for base_asset, binance_qty in binance_balances.items():
            if base_asset in _SKIP_RECONCILE_SYMBOLS:
                continue

            # Spróbuj znaleźć pasujący symbol (USDC para)
            candidate_symbols = [
                f"{base_asset}USDC",
                f"{base_asset}EUR",
                f"{base_asset}USDT",
            ]
            matched_symbol = None
            current_price = 0.0
            for sym in candidate_symbols:
                price = _get_ticker_price(sym)
                if price > 0:
                    matched_symbol = sym
                    current_price = price
                    break

            if matched_symbol is None:
                continue

            binance_value_usdc = binance_qty * current_price
            if binance_value_usdc < _DUST_THRESHOLD_USDC:
                continue

            # Czy jest już w DB jako otwarta pozycja (JAKIKOLWIEK symbol dla tego base_asset)?
            # Sprawdzamy nie tylko matched_symbol, ale cały base_asset — inaczej BTCEUR powoduje
            # tworzenie BTCUSDC i wpadamy w pętlę duplikatów.
            base_already_in_db = any(
                _base_asset(sym) == base_asset for sym in db_symbols.keys()
            )
            if base_already_in_db:
                continue

            # Sprawdź czy nie mamy pending order który właśnie się wykonuje
            active_pending = (
                db.query(PendingOrder)
                .filter(
                    PendingOrder.mode == mode,
                    PendingOrder.symbol == matched_symbol,
                    PendingOrder.side == "BUY",
                    PendingOrder.status.in_(
                        ["PENDING_CREATED", "PENDING", "PENDING_CONFIRMED", "CONFIRMED"]
                    ),
                )
                .first()
            )
            if active_pending:
                continue  # Poczekaj aż kolektor to przetworzy

            # Sprawdź czy nie było już zdetekowane
            existing_detection = (
                db.query(ManualTradeDetection)
                .filter(
                    ManualTradeDetection.symbol == matched_symbol,
                    ManualTradeDetection.mode == mode,
                    ManualTradeDetection.db_synced.is_(False),
                )
                .first()
            )
            if existing_detection:
                continue

            # Manualne wejście wykryte — utwórz pozycję w DB i zapis detekcji
            notional_eur = (binance_value_usdc / eur_rate) if eur_rate > 0 else 0.0

            new_pos = Position(
                symbol=matched_symbol,
                side="LONG",
                entry_price=current_price,
                quantity=binance_qty,
                current_price=current_price,
                mode=mode,
                entry_reason_code="manual_trade_reconcile_synced",
                opened_at=utc_now_naive(),
            )
            db.add(new_pos)
            db.flush()

            detection = ManualTradeDetection(
                symbol=matched_symbol,
                mode=mode,
                side="BUY",
                quantity=binance_qty,
                price=current_price,
                notional_eur=notional_eur,
                detection_source="reconcile",
                db_synced=True,
                detected_at=utc_now_naive(),
                synced_at=utc_now_naive(),
            )
            db.add(detection)

            ev = _save_event(
                db,
                run_id=run_id,
                event_type="manual_trade_detected",
                symbol=matched_symbol,
                mode=mode,
                before={"db": "no_position", "binance_qty": binance_qty},
                after={
                    "db": "position_created",
                    "qty": binance_qty,
                    "entry_price": current_price,
                },
                action="db_created",
                reason=f"Manualne BUY na Binance: {base_asset}={binance_qty:.8g} (≈{notional_eur:.2f} EUR)",
                repaired=True,
            )
            events.append(ev)
            repairs += 1
            manual_trades += 1

    # Post-check: wykryj duplikaty pozycji dla tego samego base_asset
    # Jeśli > 1 otwarta pozycja DB dzieli ten sam base_asset, zamknij tę z większą niezgodnością qty.
    from collections import defaultdict as _defaultdict
    base_to_open: dict = _defaultdict(list)
    for pos in open_positions:
        if pos.exit_reason_code is None and float(pos.quantity or 0) > 0:
            base = _base_asset(pos.symbol)
            base_to_open[base].append(pos)

    for base, dup_list in base_to_open.items():
        if len(dup_list) <= 1:
            continue
        binance_total = binance_balances.get(base, 0.0)
        # Sortuj wg odchylenia qty od salda Binance (najlepsze dopasowanie zachowujemy)
        dup_list.sort(key=lambda p: abs(float(p.quantity or 0) - binance_total))
        to_keep = dup_list[0]
        to_close = dup_list[1:]
        for dup in to_close:
            before_dup = {
                "symbol": dup.symbol,
                "db_qty": float(dup.quantity or 0),
                "binance_qty": binance_total,
            }
            dup.exit_reason_code = "reconcile_duplicate_base_asset"
            dup.quantity = 0.0
            dup.updated_at = utc_now_naive()
            ev = _save_event(
                db,
                run_id=run_id,
                event_type="duplicate_position",
                symbol=dup.symbol,
                mode=mode,
                before=before_dup,
                after={"exit_reason_code": "reconcile_duplicate_base_asset", "qty": 0},
                action="db_closed",
                reason=(
                    f"Duplikat pozycji dla {base}: {dup.symbol} (qty={before_dup['db_qty']:.8g}) "
                    f"vs {to_keep.symbol} (qty={float(to_keep.quantity or 0):.8g}), "
                    f"Binance {base}={binance_total:.8g}"
                ),
                repaired=True,
            )
            events.append(ev)
            repairs += 1
        _log(
            f"[reconcile] Duplikaty {base}: zamknieto {len(to_close)} z {len(dup_list)}, zachowano {to_keep.symbol}",
            db=db,
        )

    try:
        db.commit()
    except Exception:
        db.rollback()

    return events, repairs, manual_trades


# ---------------------------------------------------------------------------
# RECONCILE — SALDA
# ---------------------------------------------------------------------------


def _reconcile_balances(
    db: Session,
    run_id: int,
    mode: str,
    binance_balances: Dict[str, float],
) -> Tuple[List[Dict], int]:
    """
    Loguje informację o saldach (tylko wykrywanie, bez modyfikacji — salda nie są w DB lokalnie).
    """
    events: List[Dict] = []
    repairs = 0

    usdc_balance = binance_balances.get("USDC", 0.0)
    eur_balance = binance_balances.get("EUR", 0.0)

    # Ostrzeżenie: za mało USDC do handlu
    min_trade_usdc = float(os.getenv("MIN_TRADE_NOTIONAL_USDC", "15.0"))
    if usdc_balance < min_trade_usdc and mode == "live":
        ev = _save_event(
            db,
            run_id=run_id,
            event_type="balance_mismatch",
            symbol="USDC",
            mode=mode,
            before={"usdc": usdc_balance, "eur": eur_balance},
            after={"note": "insufficient_usdc_for_trading"},
            action="skipped",
            reason=f"Niskie saldo USDC={usdc_balance:.2f} < min={min_trade_usdc:.2f}",
            repaired=False,
        )
        events.append(ev)

    return events, repairs


# ---------------------------------------------------------------------------
# POMOCNICZE
# ---------------------------------------------------------------------------


def _save_event(
    db: Session,
    run_id: int,
    event_type: str,
    symbol: Optional[str],
    mode: Optional[str],
    before: Any,
    after: Any,
    action: str,
    reason: str,
    repaired: bool,
) -> Dict:
    """Zapisz event reconcylacji do DB i zwróć dict."""
    ev = ReconciliationEvent(
        run_id=run_id,
        event_type=event_type,
        symbol=symbol,
        mode=mode,
        before_json=json.dumps(before, default=str),
        after_json=json.dumps(after, default=str),
        source_of_truth="binance",
        action_taken=action,
        reason=reason[:500] if reason else None,
        repaired=repaired,
        created_at=utc_now_naive(),
    )
    db.add(ev)
    try:
        db.flush()
    except Exception:
        pass
    return {
        "event_type": event_type,
        "symbol": symbol,
        "action": action,
        "reason": reason,
        "repaired": repaired,
    }


def _notify_telegram_reconcile(summary: Dict, events: List[Dict]) -> None:
    """Wyślij powiadomienie Telegram o naprawach."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests

        repairs = summary.get("repairs", 0)
        manual = summary.get("manual_trades_detected", 0)

        lines = ["🔧 DB Reconcile zakończony"]
        lines.append(f"Naprawiono: {repairs} niezgodności")
        if manual > 0:
            lines.append(f"⚠️ Wykryto {manual} manualnych transakcji na Binance!")
        # Pokaż max 5 zdarzeń
        for ev in events[:5]:
            if ev.get("repaired"):
                sym = ev.get("symbol") or "?"
                lines.append(f"  • {sym}: {ev.get('event_type')} → {ev.get('action')}")
        if len(events) > 5:
            lines.append(f"  … i {len(events)-5} więcej")

        msg = "\n".join(lines)
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Błąd powiadomienia Telegram z reconcile: %s", exc)


# ---------------------------------------------------------------------------
# PUBLICZNE ENTRY POINTS
# ---------------------------------------------------------------------------


def run_reconcile_cycle(
    mode: str = "live",
    trigger: str = "scheduled",
    notify_telegram: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Główny punkt wejścia do reconcylacji.
    Tworzy własną sesję DB, wykonuje reconcile, zamyka sesję.
    Bezpieczne do wywołania z tła (collector, worker, startup).
    """
    db = SessionLocal()
    try:
        return reconcile_with_binance(
            db, mode=mode, trigger=trigger, notify_telegram=notify_telegram, force=force
        )
    except Exception as exc:
        logger.exception("run_reconcile_cycle error: %s", exc)
        return {"error": str(exc)}
    finally:
        db.close()


def get_last_reconcile_run(db: Session, mode: str = "live") -> Optional[Dict]:
    """Zwróć ostatni zakończony run reconcylacji."""
    run = (
        db.query(ReconciliationRun)
        .filter(ReconciliationRun.mode == mode, ReconciliationRun.status == "completed")
        .order_by(ReconciliationRun.started_at.desc())
        .first()
    )
    if run is None:
        return None
    return {
        "run_id": run.id,
        "mode": run.mode,
        "trigger": run.trigger,
        "events_count": run.events_count,
        "repairs_count": run.repairs_count,
        "manual_trades_detected": run.manual_trades_detected,
        "started_at": str(run.started_at),
        "finished_at": str(run.finished_at),
        "summary": json.loads(run.summary_json or "{}"),
    }


def get_reconcile_status(db: Session) -> Dict[str, Any]:
    """Zwróć status reconcylacji (dla endpointów diagnostycznych)."""
    last_live = get_last_reconcile_run(db, "live")
    last_demo = get_last_reconcile_run(db, "demo")
    running = (
        db.query(ReconciliationRun)
        .filter(ReconciliationRun.status == "running")
        .count()
    )
    total_manual = (
        db.query(ManualTradeDetection)
        .filter(ManualTradeDetection.db_synced.is_(True))
        .count()
    )
    pending_manual = (
        db.query(ManualTradeDetection)
        .filter(ManualTradeDetection.db_synced.is_(False))
        .count()
    )
    return {
        "last_live_reconcile": last_live,
        "last_demo_reconcile": last_demo,
        "currently_running": running > 0,
        "total_manual_trades_synced": total_manual,
        "pending_manual_trades": pending_manual,
        "last_ts": _last_reconcile_ts.isoformat() if _last_reconcile_ts else None,
        "min_interval_s": _RECONCILE_MIN_INTERVAL_SECONDS,
    }


def reconcile_after_manual_trade(
    db: Session,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    mode: str = "live",
    binance_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wywoływane gdy wykryto manualną transakcję.
    Synchronizuje DB ze stanem Binance dla konkretnego symbolu.
    """
    eur_rate = _resolve_eur_rate()
    notional_eur = (qty * price / eur_rate) if eur_rate > 0 else 0.0

    # Utwórz wpis detekcji
    detection = ManualTradeDetection(
        symbol=symbol,
        mode=mode,
        side=side.upper(),
        quantity=qty,
        price=price,
        notional_eur=notional_eur,
        binance_order_id=binance_order_id,
        detection_source="explicit_call",
        db_synced=False,
        telegram_notified=False,
        detected_at=utc_now_naive(),
    )
    db.add(detection)
    db.flush()

    result: Dict[str, Any] = {
        "detection_id": detection.id,
        "symbol": symbol,
        "side": side.upper(),
        "qty": qty,
        "price": price,
    }

    if side.upper() == "BUY":
        # Sprawdź czy pozycja już istnieje
        existing = (
            db.query(Position)
            .filter(
                Position.symbol == symbol,
                Position.mode == mode,
                Position.exit_reason_code.is_(None),
                Position.quantity > 0,
            )
            .first()
        )
        if existing:
            # Aktualizuj qty (uśredniony wejście)
            old_qty = float(existing.quantity or 0.0)
            old_ep = float(existing.entry_price or price)
            new_qty = old_qty + qty
            new_ep = (
                (old_ep * old_qty + price * qty) / new_qty if new_qty > 0 else price
            )
            existing.quantity = new_qty
            existing.entry_price = new_ep
            existing.updated_at = utc_now_naive()
            result["action"] = "position_qty_updated"
        else:
            new_pos = Position(
                symbol=symbol,
                side="LONG",
                entry_price=price,
                quantity=qty,
                current_price=price,
                mode=mode,
                entry_reason_code="manual_trade_direct_sync",
                opened_at=utc_now_naive(),
            )
            db.add(new_pos)
            result["action"] = "position_created"

    elif side.upper() == "SELL":
        existing = (
            db.query(Position)
            .filter(
                Position.symbol == symbol,
                Position.mode == mode,
                Position.exit_reason_code.is_(None),
                Position.quantity > 0,
            )
            .first()
        )
        if existing:
            new_qty = float(existing.quantity or 0.0) - qty
            if new_qty <= _DUST_THRESHOLD_USDC / max(price, 1.0):
                existing.exit_reason_code = "manual_sell_reconcile"
                existing.quantity = 0.0
                result["action"] = "position_closed"
            else:
                existing.quantity = new_qty
                existing.updated_at = utc_now_naive()
                result["action"] = "position_qty_reduced"
        else:
            result["action"] = "no_matching_position"

    detection.db_synced = True
    detection.synced_at = utc_now_naive()

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        result["error"] = str(exc)
        return result

    # Powiadom Telegram
    _notify_telegram_manual_trade(
        symbol, side, qty, price, notional_eur, result.get("action", "")
    )
    detection.telegram_notified = True
    try:
        db.commit()
    except Exception:
        pass

    return result


def _notify_telegram_manual_trade(
    symbol: str, side: str, qty: float, price: float, notional_eur: float, action: str
) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests

        direction = "zakup" if side.upper() == "BUY" else "sprzedaż"
        msg = (
            f"⚠️ Wykryto manualną {direction} na Binance!\n"
            f"Symbol: {symbol}\n"
            f"Ilość: {qty:.8g}\n"
            f"Cena: {price:.4f}\n"
            f"Wartość: ≈{notional_eur:.2f} EUR\n"
            f"DB zsynchronizowana: {action}\n"
            "Bot automatycznie zaktualizował bazę danych."
        )
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Błąd powiadomienia manualne trade: %s", exc)
