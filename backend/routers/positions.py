"""
Positions API Router - endpoints dla pozycji (otwarte pozycje)
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.analysis import (
    _compute_indicators,
    _insight_from_indicators,
    _klines_to_df,
    get_live_context,
)
from backend.auth import require_admin
from backend.binance_client import get_binance_client
from backend.database import (
    DecisionTrace,
    Kline,
    MarketData,
    Order,
    PendingOrder,
    Position,
    RuntimeSetting,
    get_db,
    utc_now_naive,
)
from backend.runtime_settings import build_symbol_tier_map, get_runtime_config

router = APIRouter()


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _trade_ts_to_naive(ts_ms: Any) -> Optional[datetime]:
    try:
        ts_int = int(ts_ms)
    except Exception:
        return None
    if ts_int <= 0:
        return None
    return datetime.fromtimestamp(ts_int / 1000, tz=timezone.utc).replace(tzinfo=None)


def _estimate_live_entry_from_trades(
    trades: Optional[List[Dict[str, Any]]],
    current_qty: float,
) -> tuple[Optional[float], Optional[datetime], str]:
    """Odtwórz średni koszt aktualnie trzymanej pozycji z historii myTrades."""
    if current_qty <= 0:
        return None, None, "no_open_quantity"

    held_qty = 0.0
    avg_entry = 0.0
    opened_at: Optional[datetime] = None

    for trade in sorted(trades or [], key=lambda item: int(item.get("time", 0) or 0)):
        qty = _as_float(trade.get("qty"))
        price = _as_float(trade.get("price"))
        if qty <= 0 or price <= 0:
            continue

        if bool(trade.get("isBuyer")):
            new_qty = held_qty + qty
            if held_qty <= 1e-12:
                opened_at = _trade_ts_to_naive(trade.get("time"))
            avg_entry = (
                (((avg_entry * held_qty) + (price * qty)) / new_qty)
                if new_qty > 0
                else 0.0
            )
            held_qty = new_qty
        else:
            if held_qty <= 1e-12:
                continue
            held_qty = max(0.0, held_qty - qty)
            if held_qty <= 1e-12:
                avg_entry = 0.0
                opened_at = None

    if held_qty <= 1e-12 or avg_entry <= 0:
        return None, None, "missing_trade_history"

    mismatch = abs(held_qty - current_qty)
    source = "binance_trade_history"
    if mismatch > max(1e-6, current_qty * 0.05):
        source = "binance_trade_history_partial"

    return avg_entry, opened_at, source


def _resolve_live_position_baseline(
    db: Session,
    symbol: str,
    quantity: float,
    current_price: float,
    *,
    binance_client: Any,
) -> Dict[str, Any]:
    """Znajdź lub odtwórz baseline LIVE i uzupełnij lokalną pozycję, jeśli to możliwe."""
    now = utc_now_naive()
    existing = (
        db.query(Position)
        .filter(Position.symbol == symbol, Position.mode == "live")
        .order_by(desc(Position.updated_at), desc(Position.opened_at))
        .first()
    )

    if existing and _as_float(existing.entry_price) > 0:
        entry_price = _as_float(existing.entry_price)
        unrealized_pnl = (current_price - entry_price) * quantity
        dirty = False

        if abs(_as_float(existing.quantity) - quantity) > max(1e-8, quantity * 1e-6):
            existing.quantity = quantity
            dirty = True
        if abs(_as_float(existing.current_price) - current_price) > max(
            1e-8, current_price * 1e-6
        ):
            existing.current_price = current_price
            dirty = True
        if abs(_as_float(existing.unrealized_pnl) - unrealized_pnl) > 1e-8:
            existing.unrealized_pnl = unrealized_pnl
            existing.gross_pnl = unrealized_pnl
            existing.net_pnl = unrealized_pnl
            dirty = True
        if dirty:
            existing.updated_at = now

        return {
            "entry_price": entry_price,
            "opened_at": existing.opened_at,
            "updated_at": existing.updated_at,
            "unrealized_pnl": unrealized_pnl,
            "pnl_percent": (
                ((unrealized_pnl / (entry_price * quantity)) * 100)
                if entry_price > 0 and quantity > 0
                else None
            ),
            "source": "local_live_position",
            "dirty": dirty,
        }

    entry_price: Optional[float] = None
    opened_at: Optional[datetime] = None
    source = "missing_trade_history"
    try:
        trades = binance_client.get_my_trades(symbol, limit=500) or []
        entry_price, opened_at, source = _estimate_live_entry_from_trades(
            trades, quantity
        )
    except Exception:
        trades = []

    if entry_price is None:
        return {
            "entry_price": None,
            "opened_at": None,
            "updated_at": existing.updated_at if existing else None,
            "unrealized_pnl": None,
            "pnl_percent": None,
            "source": source,
            "dirty": False,
        }

    unrealized_pnl = (current_price - entry_price) * quantity
    if existing:
        existing.entry_price = entry_price
        existing.quantity = quantity
        existing.current_price = current_price
        existing.unrealized_pnl = unrealized_pnl
        existing.gross_pnl = unrealized_pnl
        existing.net_pnl = unrealized_pnl
        existing.updated_at = now
        existing.opened_at = opened_at or existing.opened_at or now
        existing.entry_reason_code = "synced_from_binance"
    else:
        existing = Position(
            symbol=symbol,
            side="LONG",
            entry_price=entry_price,
            quantity=quantity,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            gross_pnl=unrealized_pnl,
            net_pnl=unrealized_pnl,
            total_cost=0.0,
            fee_cost=0.0,
            slippage_cost=0.0,
            spread_cost=0.0,
            mode="live",
            opened_at=opened_at or now,
            updated_at=now,
            entry_reason_code="synced_from_binance",
        )
        db.add(existing)
        # Flush natychmiast — zapobiegamy duplikatom przy równoległych wywołaniach
        # w tej samej sesji i usprawniamy widoczność dla kolejnych zapytań
        try:
            db.flush()
        except Exception:
            db.rollback()
            raise

    return {
        "entry_price": entry_price,
        "opened_at": existing.opened_at,
        "updated_at": existing.updated_at,
        "unrealized_pnl": unrealized_pnl,
        "pnl_percent": (
            ((unrealized_pnl / (entry_price * quantity)) * 100)
            if entry_price > 0 and quantity > 0
            else None
        ),
        "source": source,
        "dirty": True,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Buduj listę LIVE spot positions z Binance (źródło prawdy dla LIVE)
# ─────────────────────────────────────────────────────────────────────────────


def _get_live_spot_positions(db: Session) -> List[Dict[str, Any]]:
    """
    Pobiera aktywa z Binance spot i zwraca listę pozycji w formacie
    kompatybilnym z lokalnym Position (symbol, qty, price_eur, value_eur).
    Reużywa _build_live_spot_portfolio z portfolio router.
    Timeout 8s — Binance retry może trwać do ~15s.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeoutError

    from backend.routers.portfolio import _build_live_spot_portfolio

    binance_client = get_binance_client()
    try:
        with ThreadPoolExecutor(max_workers=1) as _pool:
            _fut = _pool.submit(_build_live_spot_portfolio, db)
            try:
                live_data = _fut.result(timeout=8.0)
            except FuturesTimeoutError:
                return []
    except Exception:
        return []
    if live_data.get("error"):
        return []
    result = []
    dirty = False
    import os as _os

    # DISPLAY_DUST_EUR: próg prawdziwego pyłu dla wyświetlania danych (osobny od min_order_notional!)
    # min_order_notional (25 EUR) to próg HANDLOWY — nie używaj go do filtrowania wyświetlania.
    _display_dust_eur = float(_os.getenv("DISPLAY_DUST_EUR", "0.50"))
    for p in live_data["spot_positions"]:
        asset = p["asset"]
        # Pomijaj stablecoiny jako "pozycje" — one to gotówka
        if asset in ("EUR", "USDT", "USDC", "BUSD"):
            continue
        symbol = f"{asset}EUR"
        qty = _as_float(p.get("total"))
        current_price = _as_float(p.get("price_eur"))
        value_eur = qty * current_price
        # Pomijaj mikropył — wartość < 0.50 EUR to faktycznie bezwartościowe fragmenty
        # UWAGA: min_order_notional służy tylko jako próg HANDLOWY (minimalna kwota zlecenia),
        # nie jako filtr wyświetlania danych. Nawet pozycja za 5 EUR zasługuje na PnL.
        if value_eur < _display_dust_eur:
            # Usuń ewentualny stary DB-rekord jeśli istnieje (cleanup po bootstrapie)
            _dust_pos = (
                db.query(Position)
                .filter(Position.symbol == symbol, Position.mode == "live")
                .first()
            )
            if _dust_pos:
                db.delete(_dust_pos)
                dirty = True
            result.append(
                {
                    "id": None,
                    "symbol": symbol,
                    "asset": asset,
                    "side": "LONG",
                    "entry_price": None,
                    "current_price": current_price,
                    "quantity": qty,
                    "free": p.get("free"),
                    "locked": p.get("locked"),
                    "value_eur": value_eur,
                    "price_source": p.get("price_source"),
                    "source": "binance_spot_dust",
                    "entry_price_source": "dust",
                    "unrealized_pnl": None,
                    "pnl_percent": None,
                    "opened_at": None,
                    "updated_at": None,
                }
            )
            continue
        baseline = _resolve_live_position_baseline(
            db,
            symbol,
            qty,
            current_price,
            binance_client=binance_client,
        )
        dirty = dirty or bool(baseline.get("dirty"))
        result.append(
            {
                "id": None,
                "symbol": symbol,
                "asset": asset,
                "side": "LONG",
                "entry_price": baseline.get("entry_price"),
                "current_price": p["price_eur"],
                "quantity": p["total"],
                "free": p["free"],
                "locked": p["locked"],
                "value_eur": p["value_eur"],
                "price_source": p["price_source"],
                "source": "binance_spot",
                "entry_price_source": baseline.get("source"),
                "unrealized_pnl": baseline.get("unrealized_pnl"),
                "pnl_percent": baseline.get("pnl_percent"),
                "opened_at": (
                    baseline.get("opened_at").isoformat()
                    if baseline.get("opened_at")
                    else None
                ),
                "updated_at": (
                    baseline.get("updated_at").isoformat()
                    if baseline.get("updated_at")
                    else None
                ),
            }
        )
    if dirty:
        db.commit()
    return result


@router.get("")
def get_positions(
    mode: str = Query("live", description="Tryb: demo lub live"),
    symbol: Optional[str] = Query(None, description="Filtr po symbolu"),
    db: Session = Depends(get_db),
):
    """
    Pobierz listę otwartych pozycji.
    Dla LIVE: źródłem prawdy jest Binance spot, nie lokalna tabela Position.
    """
    try:
        if mode == "live":
            spots = _get_live_spot_positions(db)
            if symbol:
                spots = [s for s in spots if s["symbol"] == symbol]
            return {
                "success": True,
                "mode": mode,
                "data": spots,
                "count": len(spots),
                "source": "binance_spot",
            }

        query = db.query(Position).filter(Position.mode == mode)
        if symbol:
            query = query.filter(Position.symbol == symbol)

        positions = query.order_by(desc(Position.opened_at)).all()

        result = []
        for pos in positions:
            unrealized_pnl = pos.unrealized_pnl or 0.0
            denom = (
                (pos.entry_price * pos.quantity)
                if pos.entry_price and pos.quantity
                else 0
            )
            pnl_percent = round((unrealized_pnl / denom * 100) if denom > 0 else 0, 2)

            result.append(
                {
                    "id": pos.id,
                    "symbol": pos.symbol,
                    "side": pos.side,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "quantity": pos.quantity,
                    "unrealized_pnl": unrealized_pnl,
                    "pnl_percent": pnl_percent,
                    "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
                    "updated_at": (
                        pos.updated_at.isoformat() if pos.updated_at else None
                    ),
                }
            )

        return {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting positions: {str(e)}"
        )


def _latest_price_for_symbol(db: Session, symbol: str) -> Optional[float]:
    latest = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol)
        .order_by(desc(MarketData.timestamp))
        .first()
    )
    if latest and latest.price is not None:
        try:
            return float(latest.price)
        except Exception:
            return None
    return None


@router.post("/{position_id}/close")
def close_position(
    position_id: int,
    mode: str = Query("live", description="Tryb: demo lub live"),
    quantity: Optional[float] = Query(
        None, gt=0, description="Ile zamknąć (domyślnie: całość)"
    ),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Zamknij pozycję. DEMO: tworzy PendingOrder. LIVE: wywołuje Binance SELL MARKET.
    """
    pos = db.query(Position).filter(Position.id == position_id).first()
    if not pos:
        raise HTTPException(status_code=404, detail="Pozycja nie znaleziona")

    pos_mode = (pos.mode or "demo").lower()
    if pos_mode != mode.lower():
        raise HTTPException(
            status_code=409, detail=f"Pozycja jest w trybie {pos_mode}, nie {mode}"
        )

    if (pos.side or "").upper() == "SHORT":
        raise HTTPException(
            status_code=409, detail="Zamykanie SHORT nie jest wspierane"
        )

    sym = (
        (pos.symbol or "")
        .strip()
        .replace(" ", "")
        .replace("/", "")
        .replace("-", "")
        .upper()
    )
    if not sym:
        raise HTTPException(status_code=400, detail="Nieprawidłowy symbol pozycji")

    pos_qty = float(pos.quantity or 0.0)
    if pos_qty <= 0:
        raise HTTPException(
            status_code=409, detail="Quantity pozycji nie jest dodatnie"
        )

    qty = pos_qty
    if quantity is not None:
        try:
            qty = float(quantity)
        except Exception:
            raise HTTPException(status_code=400, detail="Nieprawidłowe quantity")
        if qty <= 0:
            raise HTTPException(status_code=400, detail="Quantity musi być dodatnie")
        if qty > pos_qty:
            raise HTTPException(
                status_code=409, detail="Quantity przekracza rozmiar pozycji"
            )

    # ─── DEMO ────────────────────────────────────────────────────────────────
    if mode.lower() == "demo":
        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == "demo",
                PendingOrder.symbol == sym,
                PendingOrder.status.in_(
                    ["PENDING", "PENDING_CREATED", "CONFIRMED", "PENDING_CONFIRMED"]
                ),
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Istnieje już aktywny pending order dla tego symbolu",
            )

        price = _latest_price_for_symbol(db, sym)
        if price is None and pos.current_price is not None:
            try:
                price = float(pos.current_price)
            except Exception:
                price = None
        if price is None or price <= 0:
            raise HTTPException(
                status_code=400, detail="Brak ceny do stworzenia zlecenia zamknięcia"
            )

        p = PendingOrder(
            symbol=sym,
            side="SELL",
            order_type="MARKET",
            price=price,
            quantity=qty,
            mode="demo",
            status="PENDING_CREATED",
            reason=(
                f"Zamknięcie pozycji #{pos.id}"
                if qty == pos_qty
                else f"Częściowe zamknięcie pozycji #{pos.id} qty={qty}"
            ),
            created_at=utc_now_naive(),
        )
        db.add(p)
        db.commit()
        db.refresh(p)
        return {
            "success": True,
            "data": {
                "pending_id": p.id,
                "position_id": pos.id,
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "price": p.price,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            },
        }

    # ─── LIVE ─────────────────────────────────────────────────────────────────
    binance = get_binance_client()
    if not binance or not binance.api_key or not binance.api_secret:
        raise HTTPException(
            status_code=503,
            detail="Brak kluczy Binance API — uzupełnij .env (BINANCE_API_KEY, BINANCE_API_SECRET)",
        )

    binance_response = binance.place_order(
        symbol=sym,
        side="SELL",
        order_type="MARKET",
        quantity=qty,
    )
    if binance_response is None:
        raise HTTPException(
            status_code=502,
            detail="Binance nie odpowiedział na zlecenie SELL — sprawdź logi",
        )
    if binance_response.get("_error"):
        raise HTTPException(
            status_code=400,
            detail=f"Binance odrzucił zlecenie zamknięcia: {binance_response.get('error_message', 'nieznany błąd')} (kod: {binance_response.get('error_code', '?')})",
        )

    fills = binance.get_order_fills(sym, binance_response.get("orderId")) or {}
    executed_price = fills.get("executed_price") or float(
        pos.current_price or pos.entry_price or 0
    )
    executed_qty = fills.get("executed_qty") or qty
    fee = fills.get("fee") or 0.0
    fee_asset = fills.get("fee_asset") or "BNB"
    binance_order_id = str(binance_response.get("orderId", ""))
    binance_status = binance_response.get("status", "FILLED")

    # Zapisz Order do DB
    order = Order(
        symbol=sym,
        side="SELL",
        order_type="MARKET",
        price=executed_price,
        quantity=executed_qty,
        status=binance_status,
        mode="live",
        created_at=utc_now_naive(),
        filled_at=utc_now_naive() if binance_status == "FILLED" else None,
        notes=f"Close position #{pos.id} | binance_order_id={binance_order_id} | fee={fee} {fee_asset}",
    )
    db.add(order)

    # Aktualizuj pozycję
    remaining_qty = round(pos_qty - executed_qty, 8)
    if remaining_qty <= 1e-8:
        db.delete(pos)
    else:
        pos.quantity = remaining_qty
        pos.updated_at = utc_now_naive()

    db.commit()

    return {
        "success": True,
        "data": {
            "position_id": position_id,
            "symbol": sym,
            "side": "SELL",
            "executed_price": executed_price,
            "executed_qty": executed_qty,
            "remaining_qty": max(0.0, remaining_qty),
            "position_closed": remaining_qty <= 1e-8,
            "binance_order_id": binance_order_id,
            "binance_status": binance_status,
            "fee": fee,
            "fee_asset": fee_asset,
            "mode": "live",
        },
    }


@router.post("/close-all")
def close_all_positions(
    mode: str = Query("live", description="Tryb: live lub demo"),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Zamknij wszystkie pozycje.
    DEMO: tworzy PENDING ordery.
    LIVE: wykonuje SELL MARKET na Binance dla każdej pozycji.
    """
    if mode not in ("live", "demo"):
        raise HTTPException(status_code=400, detail="Nieprawidłowy mode")

    positions = (
        db.query(Position)
        .filter(Position.mode == mode)
        .order_by(desc(Position.opened_at))
        .all()
    )
    if not positions:
        return {
            "success": True,
            "data": {
                "created": 0,
                "skipped_existing": 0,
                "skipped_short": 0,
                "skipped_invalid": 0,
            },
        }

    created: list[PendingOrder] = []
    skipped_existing = 0
    skipped_short = 0
    skipped_invalid = 0
    live_results: list[dict] = []

    for pos in positions:
        if (pos.side or "").upper() == "SHORT":
            skipped_short += 1
            continue

        sym = (
            (pos.symbol or "")
            .strip()
            .replace(" ", "")
            .replace("/", "")
            .replace("-", "")
            .upper()
        )
        if not sym:
            skipped_invalid += 1
            continue

        qty = float(pos.quantity or 0.0)
        if qty <= 0:
            skipped_invalid += 1
            continue

        if mode == "live":
            # LIVE: wykonaj sell market na Binance bezpośrednio
            try:
                from backend.binance_client import get_binance_client

                binance = get_binance_client()
                if not binance or not binance.api_key or not binance.api_secret:
                    skipped_invalid += 1
                    continue
                result = binance.place_order(
                    symbol=sym, side="SELL", order_type="MARKET", quantity=qty
                )
                if result and not result.get("_error"):
                    live_results.append({"symbol": sym, "qty": qty, "status": "OK"})
                else:
                    live_results.append(
                        {
                            "symbol": sym,
                            "qty": qty,
                            "status": "ERROR",
                            "detail": str(result),
                        }
                    )
                    skipped_invalid += 1
            except Exception as ex:
                live_results.append(
                    {
                        "symbol": sym,
                        "qty": qty,
                        "status": "EXCEPTION",
                        "detail": str(ex),
                    }
                )
                skipped_invalid += 1
            continue

        # DEMO: tworzy PendingOrder
        existing = (
            db.query(PendingOrder)
            .filter(
                PendingOrder.mode == mode,
                PendingOrder.symbol == sym,
                PendingOrder.status.in_(
                    ["PENDING", "PENDING_CREATED", "CONFIRMED", "PENDING_CONFIRMED"]
                ),
            )
            .first()
        )
        if existing:
            skipped_existing += 1
            continue

        price = _latest_price_for_symbol(db, sym)
        if price is None and pos.current_price is not None:
            try:
                price = float(pos.current_price)
            except Exception:
                price = None
        if price is None or price <= 0:
            skipped_invalid += 1
            continue

        p = PendingOrder(
            symbol=sym,
            side="SELL",
            order_type="MARKET",
            price=price,
            quantity=qty,
            mode=mode,
            status="PENDING_CREATED",
            reason=f"Close all (position #{pos.id})",
            created_at=utc_now_naive(),
        )
        db.add(p)
        created.append(p)

    db.commit()
    for p in created:
        db.refresh(p)

    result_data: dict = {
        "created": len(created),
        "skipped_existing": skipped_existing,
        "skipped_short": skipped_short,
        "skipped_invalid": skipped_invalid,
    }
    if mode == "live" and live_results:
        result_data["live_sells"] = live_results
    return {"success": True, "data": result_data}


def _analyze_position(
    pos: Position, db: Session, tier_map: Dict[str, Any]
) -> Dict[str, Any]:
    """Buduje kartę analizy dla jednej pozycji."""
    sym = (pos.symbol or "").strip()
    entry = float(pos.entry_price or 0)
    qty = float(pos.quantity or 0)
    current = float(pos.current_price or 0)
    tier_info = tier_map.get(sym, {})
    is_hold = tier_info.get("hold_mode", False)

    # PnL
    cost = entry * qty
    value = current * qty
    pnl_eur = round(value - cost, 2)
    pnl_pct = round((pnl_eur / cost * 100) if cost > 0 else 0, 2)

    # Wskaźniki techniczne
    ctx = get_live_context(db, sym, timeframe="1h", limit=200)
    rsi = ctx.get("rsi") if ctx else None
    ema_20 = ctx.get("ema_20") if ctx else None
    ema_50 = ctx.get("ema_50") if ctx else None
    atr = ctx.get("atr") if ctx else None

    # Pełne wskaźniki z compute_indicators
    klines = (
        db.query(Kline)
        .filter(Kline.symbol == sym, Kline.timeframe == "1h")
        .order_by(Kline.open_time.desc())
        .limit(200)
        .all()
    )
    import pandas as pd

    df = _klines_to_df(list(reversed(klines)))
    full_indicators = None
    insight = None
    if df is not None and len(df) >= 60:
        full_indicators = _compute_indicators(df)
        insight = _insight_from_indicators(full_indicators)

    # Trend
    if ema_20 is not None and ema_50 is not None:
        if ema_20 > ema_50:
            trend = "WZROSTOWY"
        else:
            trend = "SPADKOWY"
    else:
        trend = "BRAK DANYCH"

    # MFE/MAE
    mfe_pnl = float(pos.mfe_pnl) if pos.mfe_pnl is not None else None
    mae_pnl = float(pos.mae_pnl) if pos.mae_pnl is not None else None

    # Logika decyzji — myślenie od pozycji użytkownika
    reasons: List[str] = []
    decision = "CZEKAJ"
    strength = "NEUTRALNY"

    if is_hold:
        target = tier_info.get("target_value_eur", 300)
        remaining = round(target - value, 2)
        decision = "TRZYMAJ"
        strength = "SILNY"
        if value >= target:
            decision = "SPRZEDAJ"
            reasons.append(
                f"Osiągnięto cel {target} EUR (wartość: {round(value, 2)} EUR)"
            )
        else:
            reasons.append(f"Do celu {target} EUR brakuje {remaining} EUR")
            if trend == "WZROSTOWY":
                reasons.append("Trend wzrostowy — szansa na osiągnięcie celu")
            elif trend == "SPADKOWY":
                reasons.append(
                    "Trend spadkowy, ale tryb HOLD — trzymaj i czekaj na odbicie"
                )
            if rsi is not None and rsi < 35:
                reasons.append(f"RSI {round(rsi, 1)} — wyprzedanie, szansa na wzrost")
    else:
        # Normalna pozycja (CORE)
        # Planowane TP/SL
        tp = float(pos.planned_tp) if pos.planned_tp else None
        sl = float(pos.planned_sl) if pos.planned_sl else None

        if pnl_pct > 5:
            # Solidny zysk
            if trend == "SPADKOWY":
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Zysk {pnl_pct}% przy spadkowym trendzie — zabierz zysk"
                )
            elif rsi is not None and rsi > 70:
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Zysk {pnl_pct}%, RSI {round(rsi, 1)} — wykupienie, zabierz zysk"
                )
            else:
                decision = "TRZYMAJ"
                strength = "UMIARKOWANY"
                reasons.append(
                    f"Zysk {pnl_pct}%, trend {trend.lower()} — można jeszcze trzymać"
                )
                if tp is not None:
                    dist_tp = round(((tp - current) / current) * 100, 2)
                    reasons.append(f"Do TP ({round(tp, 2)}) zostało {dist_tp}%")
        elif pnl_pct > 0:
            # Mały zysk
            if trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                strength = "UMIARKOWANY"
                reasons.append(f"Mały zysk {pnl_pct}%, trend wzrostowy — trzymaj")
            else:
                decision = "CZEKAJ"
                reasons.append(f"Mały zysk {pnl_pct}%, trend spadkowy — obserwuj")
                if sl is not None:
                    dist_sl = round(((current - sl) / current) * 100, 2)
                    reasons.append(
                        f"SL ({round(sl, 2)}) jest {dist_sl}% poniżej — bufor OK"
                    )
        elif pnl_pct > -3:
            # Mała strata
            if trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                reasons.append(
                    f"Strata {pnl_pct}%, ale trend wzrostowy — szansa na odbicie"
                )
            elif rsi is not None and rsi < 30:
                decision = "TRZYMAJ"
                reasons.append(
                    f"Strata {pnl_pct}%, RSI {round(rsi, 1)} — wyprzedanie, szansa na odbicie"
                )
            else:
                decision = "CZEKAJ"
                reasons.append(
                    f"Strata {pnl_pct}%, trend {trend.lower()} — obserwuj SL"
                )
        else:
            # Duża strata
            if rsi is not None and rsi < 25:
                decision = "TRZYMAJ"
                strength = "SŁABY"
                reasons.append(
                    f"Strata {pnl_pct}%, ale RSI {round(rsi, 1)} — skrajne wyprzedanie, szansa na odbicie"
                )
            elif trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                strength = "SŁABY"
                reasons.append(
                    f"Strata {pnl_pct}%, trend się odwraca — szansa na odrobienie"
                )
            else:
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Strata {pnl_pct}%, trend spadkowy — zamknij pozycję, ogranicz straty"
                )

        # Dodaj info o insight z analizy technicznej
        if insight:
            sig = insight.get("signal", "")
            conf = insight.get("confidence", 0)
            if sig == "SELL" and conf > 0.7 and decision != "SPRZEDAJ":
                reasons.append(
                    f"Analiza techniczna sygnalizuje SELL (pewność {round(conf * 100)}%)"
                )
            elif sig == "BUY" and conf > 0.7 and decision == "SPRZEDAJ":
                reasons.append(
                    f"Uwaga: analiza techniczna sygnalizuje BUY mimo straty (pewność {round(conf * 100)}%)"
                )

    # Precyzja: dla małych kwot używamy 6 miejsc
    decimals = 6 if max(value, cost) < 1.0 else 4 if max(value, cost) < 100 else 2
    # DEMO: entry_price zawsze jest z DB → always valid_position (jeśli qty > 0 i entry > 0)
    _is_valid_demo = entry > 0 and qty > 0 and current > 0
    card: Dict[str, Any] = {
        "symbol": sym,
        "side": pos.side,
        "quantity": qty,
        "entry_price": entry if entry > 0 else None,
        "current_price": current,
        "position_value_eur": round(value, decimals),
        "cost_eur": round(cost, decimals),
        "pnl_eur": round(pnl_eur, decimals),
        "pnl_pct": pnl_pct,
        "trend": trend,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "ema_20": round(ema_20, 6) if ema_20 is not None else None,
        "ema_50": round(ema_50, 6) if ema_50 is not None else None,
        "atr": round(atr, 6) if atr is not None else None,
        "planned_tp": float(pos.planned_tp) if pos.planned_tp else None,
        "planned_sl": float(pos.planned_sl) if pos.planned_sl else None,
        "mfe_pnl": mfe_pnl,
        "mae_pnl": mae_pnl,
        "is_hold": is_hold,
        "decision": decision,
        "strength": strength,
        "reasons": reasons,
        # Pola kontraktu API
        "classification": "valid_position" if _is_valid_demo else "missing_entry_price",
        "is_dust": False,
        "has_entry_price": entry > 0,
        "can_analyze": _is_valid_demo,
        "can_compute_pnl": _is_valid_demo,
        "warning_message": (
            None
            if _is_valid_demo
            else "Brak ceny wejścia lub ilości w rekordzie pozycji"
        ),
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
        "updated_at": pos.updated_at.isoformat() if pos.updated_at else None,
    }

    if is_hold:
        card["hold_target_eur"] = tier_info.get("target_value_eur", 300)
        card["hold_remaining_eur"] = round(
            tier_info.get("target_value_eur", 300) - value, 2
        )

    return card


def _analyze_spot_position(
    spot: Dict[str, Any], db: Session, tier_map: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Buduje kartę analizy dla pozycji LIVE spot (z Binance).

    Klasyfikacja pozycji (twarde reguły domenowe):
    - dust_position       — wartość < DISPLAY_DUST_EUR lub source=binance_spot_dust
    - missing_entry_price — brak ceny wejścia z historii Binance/fillów
    - valid_position      — pełna pozycja z potwierdzoną ceną wejścia

    Silnik rekomendacji (TRZYMAJ / SPRZEDAJ / REDUKUJ) działa WYŁĄCZNIE
    dla valid_position. Dla pozostałych: decision = "DUST" lub "BRAK DANYCH".
    """
    sym = spot["symbol"]
    asset = spot.get("asset", sym.replace("EUR", ""))
    qty = float(spot.get("quantity", 0))
    current = float(spot.get("current_price", 0))
    value = float(spot.get("value_eur", current * qty))
    entry_price = (
        float(spot["entry_price"]) if spot.get("entry_price") is not None else None
    )
    cost_eur = (
        round(entry_price * qty, 4) if entry_price is not None and qty > 0 else None
    )
    pnl_eur = round(value - cost_eur, 4) if cost_eur is not None else None
    pnl_pct = (
        round((pnl_eur / cost_eur) * 100, 2)
        if pnl_eur is not None and cost_eur and cost_eur > 0
        else None
    )
    tier_info = tier_map.get(sym, {})
    is_hold = tier_info.get("hold_mode", False)

    # ── KLASYFIKACJA POZYCJI ────────────────────────────────────────────────
    # Twarde reguły domenowe: nie zgaduj, nie podstawiaj fake danych.
    is_dust: bool = spot.get("source") == "binance_spot_dust" or value < 0.50
    has_entry_price: bool = entry_price is not None
    can_analyze: bool = not is_dust and has_entry_price and current > 0 and qty > 0
    can_compute_pnl: bool = has_entry_price and qty > 0 and not is_dust

    if is_dust:
        classification = "dust_position"
    elif not has_entry_price:
        classification = "missing_entry_price"
    else:
        classification = "valid_position"

    # Wskaźniki techniczne — pobieramy zawsze (do info), ale decyzja NA ICH PODSTAWIE
    # tylko dla valid_position.
    ctx = get_live_context(db, sym, timeframe="1h", limit=200) if can_analyze else None
    rsi = ctx.get("rsi") if ctx else None
    ema_20 = ctx.get("ema_20") if ctx else None
    ema_50 = ctx.get("ema_50") if ctx else None
    atr = ctx.get("atr") if ctx else None

    # Trend
    if ema_20 is not None and ema_50 is not None:
        trend = "WZROSTOWY" if ema_20 > ema_50 else "SPADKOWY"
    else:
        trend = "BRAK DANYCH"

    reasons: List[str] = []
    decision: str
    strength: str
    warning_message: Optional[str] = None

    # ── GUARDRAIL: silnik rekomendacji działa TYLKO dla valid_position ──────
    if is_dust:
        decision = "DUST"
        strength = "BRAK"
        warning_message = "Mikropozycja poniżej progu analizy tradingowej."
        reasons = [
            f"Wartość pozycji ({round(value, 6)} EUR) poniżej progu analizy.",
            "Brak rekomendacji tradingowej dla pyłu — to resztka po transakcjach.",
        ]
    elif not has_entry_price:
        decision = "BRAK DANYCH"
        strength = "BRAK"
        warning_message = "Brak potwierdzonej ceny wejścia — analiza niemożliwa."
        reasons = [
            "Brak potwierdzonej ceny wejścia w historii transakcji Binance.",
            "System nie może wiarygodnie policzyć wyniku tej pozycji.",
            "Zasób kupiony poza historią dostępną przez API (np. Convert, transfer) "
            "lub historia przekracza limit 1000 transakcji.",
        ]
    elif is_hold:
        # ── Tryb HOLD — rekomendacja na podstawie celu wyceny ────────────────
        target = tier_info.get("target_value_eur", 300)
        remaining = round(target - value, 2)
        strength = "SILNY"
        if value >= target:
            decision = "SPRZEDAJ"
            reasons.append(
                f"Osiągnięto cel {target} EUR (wartość: {round(value, 2)} EUR)"
            )
        else:
            decision = "TRZYMAJ"
            reasons.append(f"Do celu {target} EUR brakuje {remaining} EUR")
            if trend == "WZROSTOWY":
                reasons.append("Trend wzrostowy — szansa na osiągnięcie celu")
            elif trend == "SPADKOWY":
                reasons.append(
                    "Trend spadkowy, ale tryb HOLD — trzymaj i czekaj na odbicie"
                )
    else:
        # ── Normalna pozycja z potwierdzoną ceną wejścia ─────────────────────
        # PnL-based + trend/RSI logic
        if pnl_pct is not None and pnl_pct > 5:
            if trend == "SPADKOWY":
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Zysk {pnl_pct}% przy spadkowym trendzie — zabierz zysk"
                )
            elif rsi is not None and rsi > 70:
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Zysk {pnl_pct}%, RSI {round(rsi, 1)} — wykupienie, zabierz zysk"
                )
            else:
                decision = "TRZYMAJ"
                strength = "UMIARKOWANY"
                reasons.append(
                    f"Zysk {pnl_pct}%, trend {trend.lower()} — można jeszcze trzymać"
                )
        elif pnl_pct is not None and pnl_pct >= 0:
            if trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                strength = "UMIARKOWANY"
                reasons.append(f"Mały zysk {pnl_pct}%, trend wzrostowy — trzymaj")
            else:
                decision = "CZEKAJ"
                strength = "NEUTRALNY"
                reasons.append(
                    f"Mały zysk {pnl_pct}%, trend {trend.lower()} — obserwuj"
                )
        elif pnl_pct is not None and pnl_pct > -3:
            if trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                strength = "NEUTRALNY"
                reasons.append(
                    f"Strata {pnl_pct}%, ale trend wzrostowy — szansa na odbicie"
                )
            elif rsi is not None and rsi < 30:
                decision = "TRZYMAJ"
                strength = "NEUTRALNY"
                reasons.append(
                    f"Strata {pnl_pct}%, RSI {round(rsi, 1)} — wyprzedanie, szansa na odbicie"
                )
            else:
                decision = "CZEKAJ"
                strength = "NEUTRALNY"
                reasons.append(
                    f"Strata {pnl_pct}%, trend {trend.lower()} — obserwuj SL"
                )
        elif pnl_pct is not None:
            if rsi is not None and rsi < 25:
                decision = "TRZYMAJ"
                strength = "SŁABY"
                reasons.append(
                    f"Strata {pnl_pct}%, ale RSI {round(rsi, 1)} — skrajne wyprzedanie, szansa na odbicie"
                )
            elif trend == "WZROSTOWY":
                decision = "TRZYMAJ"
                strength = "SŁABY"
                reasons.append(
                    f"Strata {pnl_pct}%, trend się odwraca — szansa na odrobienie"
                )
            else:
                decision = "SPRZEDAJ"
                strength = "SILNY"
                reasons.append(
                    f"Strata {pnl_pct}%, trend spadkowy — zamknij pozycję, ogranicz straty"
                )
        else:
            # pnl_pct is None ale valid_position (nie powinno wystąpić, ale defensywnie)
            if trend == "SPADKOWY":
                if rsi is not None and rsi < 30:
                    decision = "TRZYMAJ"
                    strength = "SŁABY"
                    reasons.append(
                        f"Trend spadkowy, ale RSI {round(rsi, 1)} — skrajne wyprzedanie, szansa na odbicie"
                    )
                elif rsi is not None and rsi > 65:
                    decision = "REDUKUJ"
                    strength = "UMIARKOWANY"
                    reasons.append(
                        f"Trend spadkowy + RSI {round(rsi, 1)} — rozważ częściowe wyjście"
                    )
                else:
                    decision = "TRZYMAJ"
                    strength = "NEUTRALNY"
                    reasons.append(
                        "Trend spadkowy — obserwuj, brak pilnej potrzeby wyjścia"
                    )
            elif trend == "WZROSTOWY":
                if rsi is not None and rsi > 75:
                    decision = "REDUKUJ"
                    strength = "UMIARKOWANY"
                    reasons.append(
                        f"Trend wzrostowy, RSI {round(rsi, 1)} — wykupienie, rozważ częściowy zysk"
                    )
                else:
                    decision = "TRZYMAJ"
                    strength = "UMIARKOWANY"
                    reasons.append("Trend wzrostowy — trzymaj")
            else:
                decision = "CZEKAJ"
                strength = "NEUTRALNY"
                reasons.append("Brak danych trendowych — obserwuj")

    decimals = 6 if value < 1.0 else 4 if value < 100 else 2
    card: Dict[str, Any] = {
        "symbol": sym,
        "asset": asset,
        "side": "LONG",
        "quantity": qty,
        # Dane finansowe — null jeśli niemożliwe do wyliczenia
        "entry_price": entry_price,
        "current_price": current,
        "position_value_eur": round(value, decimals),
        "cost_eur": cost_eur if can_compute_pnl else None,
        "pnl_eur": pnl_eur if can_compute_pnl else None,
        "pnl_pct": pnl_pct if can_compute_pnl else None,
        # Wskaźniki techniczne
        "trend": trend,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "ema_20": round(ema_20, 6) if ema_20 is not None else None,
        "ema_50": round(ema_50, 6) if ema_50 is not None else None,
        "atr": round(atr, 6) if atr is not None else None,
        "planned_tp": None,
        "planned_sl": None,
        "mfe_pnl": None,
        "mae_pnl": None,
        "is_hold": is_hold,
        # Rekomendacja — tylko dla valid_position
        "decision": decision,
        "strength": strength,
        "reasons": reasons,
        # ── Pola kontraktu API (jawna informacja o jakości danych) ──────────
        "classification": classification,
        "is_dust": is_dust,
        "has_entry_price": has_entry_price,
        "can_analyze": can_analyze,
        "can_compute_pnl": can_compute_pnl,
        "warning_message": warning_message,
        # ────────────────────────────────────────────────────────────────────
        "opened_at": None,
        "updated_at": None,
        "source": spot.get("source", "binance_spot"),
        "price_source": spot.get("price_source"),
        "entry_price_source": spot.get("entry_price_source"),
    }

    if is_hold:
        card["hold_target_eur"] = tier_info.get("target_value_eur", 300)
        card["hold_remaining_eur"] = round(
            tier_info.get("target_value_eur", 300) - value, 2
        )

    return card


@router.get("/analysis")
def position_analysis(
    mode: str = Query("live", description="Tryb: demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Analiza pozycji — karta decyzyjna dla każdego symbolu.
    LIVE: źródłem prawdy jest Binance spot (spot_positions).
    DEMO: źródłem prawdy jest lokalna tabela Position.
    """
    try:
        settings = get_runtime_config(db)
        tier_map = build_symbol_tier_map(settings.get("symbol_tiers", {}))

        if mode == "live":
            spots = _get_live_spot_positions(db)
            cards = [_analyze_spot_position(sp, db, tier_map) for sp in spots]
        else:
            positions = (
                db.query(Position)
                .filter(Position.mode == mode)
                .order_by(desc(Position.opened_at))
                .all()
            )
            cards = [_analyze_position(pos, db, tier_map) for pos in positions]

        # Podsumowanie — tylko valid_position wchodzi do statystyk finansowych
        # (dust i missing_entry_price nie mają wiarygodnego PnL)
        valid_cards = [c for c in cards if c.get("classification") == "valid_position"]
        dust_cards = [c for c in cards if c.get("is_dust")]
        missing_cards = [
            c for c in cards if c.get("classification") == "missing_entry_price"
        ]

        total_value = sum(c["position_value_eur"] for c in valid_cards)
        total_pnl = sum(c["pnl_eur"] or 0 for c in valid_cards)
        total_cost = sum((c["cost_eur"] or 0) for c in valid_cards)
        # Wartość wszystkich aktywów (dust też ma bieżącą wartość rynkową)
        all_value = sum(c["position_value_eur"] for c in cards)
        dust_value = sum(c["position_value_eur"] for c in dust_cards)
        missing_value = sum(c["position_value_eur"] for c in missing_cards)

        sdec = (
            6
            if max(total_value, total_cost, abs(total_pnl), 0.000001) < 1.0
            else 4 if max(total_value, total_cost) < 100 else 2
        )

        return {
            "success": True,
            "mode": mode,
            "source": "binance_spot" if mode == "live" else "local_db",
            "summary": {
                "positions_count": len(cards),
                "valid_positions_count": len(valid_cards),
                "dust_positions_count": len(dust_cards),
                "missing_entry_count": len(missing_cards),
                # Statystyki tylko z valid_position
                "total_value_eur": round(total_value, sdec),
                "total_cost_eur": round(total_cost, sdec) if total_cost > 0 else None,
                "total_pnl_eur": round(total_pnl, sdec) if total_cost > 0 else None,
                "total_pnl_pct": round(
                    (total_pnl / total_cost * 100) if total_cost > 0 else 0, 2
                ),
                # Wartości rynkowe do informacji (bez PnL bo brak baseline)
                "all_assets_value_eur": round(all_value, 2),
                "dust_value_eur": round(dust_value, 6) if dust_value > 0 else None,
                "missing_entry_value_eur": (
                    round(missing_value, 2) if missing_value > 0 else None
                ),
            },
            "data": cards,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd analizy pozycji: {str(e)}")


# USER GOALS — persystencja celu na symbol
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/goal/{symbol}")
def get_goal(
    symbol: str,
    db: Session = Depends(get_db),
):
    """Zwraca zapisany cel użytkownika dla symbolu."""
    key = f"user_goal_{symbol}"
    rec = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
    if not rec:
        return {"symbol": symbol, "goal": None}
    try:
        return {"symbol": symbol, "goal": json.loads(rec.value)}
    except Exception:
        return {"symbol": symbol, "goal": None}


@router.put("/goal/{symbol}")
def set_goal(
    symbol: str,
    payload: dict,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Zapisuje cel użytkownika dla symbolu (target_eur, label)."""
    target_eur = payload.get("target_eur")
    if (
        target_eur is None
        or not isinstance(target_eur, (int, float))
        or target_eur <= 0
    ):
        raise HTTPException(
            status_code=422, detail="Pole target_eur musi być liczbą > 0"
        )
    goal = {
        "target_eur": float(target_eur),
        "label": payload.get("label", ""),
        "set_at": utc_now_naive().isoformat(),
    }
    key = f"user_goal_{symbol}"
    rec = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).first()
    if rec:
        rec.value = json.dumps(goal)
    else:
        db.add(RuntimeSetting(key=key, value=json.dumps(goal)))
    db.commit()
    return {"success": True, "symbol": symbol, "goal": goal}


@router.delete("/goal/{symbol}")
def delete_goal(
    symbol: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Usuwa cel użytkownika dla symbolu."""
    key = f"user_goal_{symbol}"
    deleted = db.query(RuntimeSetting).filter(RuntimeSetting.key == key).delete()
    db.commit()
    return {"success": True, "deleted": deleted > 0}


# GOAL ANALYSIS — silnik oceny celu użytkownika
# ─────────────────────────────────────────────────────────────────────────────


def _score_for_alt_target(
    alt_value: float,
    quantity: Optional[float],
    current_price: Optional[float],
    atr_hourly_pct: Optional[float],
    trend: str,
) -> int:
    """Oblicza reality score dla alternatywnego celu."""
    if not quantity or not current_price or current_price == 0:
        return 50
    tp = alt_value / quantity
    mp = (tp - current_price) / current_price * 100
    if mp <= 0:
        return 90
    if not atr_hourly_pct or atr_hourly_pct == 0:
        return 50
    dn = (mp / (atr_hourly_pct * 0.25)) / 24
    s = max(5, min(95, int(100 - dn * 7)))
    if trend == "WZROSTOWY":
        s = min(95, s + 10)
    elif trend == "SPADKOWY":
        s = max(5, s - 15)
    return s


@router.get("/goal-analysis/{symbol}")
def get_goal_analysis(
    symbol: str,
    mode: str = Query("live", description="demo lub live"),
    target_eur: Optional[float] = Query(
        None,
        description="Docelowa wartość pozycji w EUR (opcjonalnie nadpisuje zapisany cel)",
    ),
    db: Session = Depends(get_db),
):
    """
    Ocena celu użytkownika dla symbolu.
    Zwraca: realność celu, szacowany czas, warunki, blokery, alternatywy, decyzję.
    Parametr target_eur w query nadpisuje zapisany cel.
    """
    try:
        # 1. Pozycja — dla LIVE korzystamy z Binance spot jako źródła prawdy
        pos = (
            db.query(Position)
            .filter(Position.symbol == symbol, Position.mode == mode)
            .first()
        )
        spot_pos = None
        if mode == "live" and not pos:
            for s in _get_live_spot_positions(db):
                if s["symbol"] == symbol:
                    spot_pos = s
                    break

        # 2. Zapisany cel
        stored_goal = None
        goal_key = f"user_goal_{symbol}"
        goal_rec = (
            db.query(RuntimeSetting).filter(RuntimeSetting.key == goal_key).first()
        )
        if goal_rec:
            try:
                stored_goal = json.loads(goal_rec.value)
            except Exception:
                pass

        # 3. Efektywny cel (query param > zapisany cel > auto-10%)
        effective_target: Optional[float] = None
        goal_label = ""
        goal_set_at = None
        goal_source = None

        if target_eur is not None and target_eur > 0:
            effective_target = float(target_eur)
            goal_source = "query_param"
        elif stored_goal:
            effective_target = float(stored_goal.get("target_eur", 0) or 0) or None
            goal_label = stored_goal.get("label", "")
            goal_set_at = stored_goal.get("set_at")
            goal_source = "saved"

        # 4. Wskaźniki techniczne
        ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
        current_price: Optional[float] = ctx["close"] if ctx else None
        if pos and pos.current_price:
            current_price = float(pos.current_price)
        elif spot_pos:
            current_price = spot_pos.get("current_price") or current_price

        ema_20: Optional[float] = ctx.get("ema_20") if ctx else None
        ema_50: Optional[float] = ctx.get("ema_50") if ctx else None
        rsi: Optional[float] = ctx.get("rsi") if ctx else None
        atr: Optional[float] = ctx.get("atr") if ctx else None
        rsi_buy: float = float(ctx.get("rsi_buy") or 30.0) if ctx else 30.0
        rsi_sell: float = float(ctx.get("rsi_sell") or 70.0) if ctx else 70.0

        # 5. Dane pozycji (lokalna Position LUB Binance spot)
        has_position = pos is not None or spot_pos is not None
        entry_price = float(pos.entry_price) if pos and pos.entry_price else None
        quantity = float(pos.quantity) if pos and pos.quantity else None
        if not quantity and spot_pos:
            quantity = spot_pos.get("quantity")
        pos_value_eur = (
            round(current_price * quantity, 4) if current_price and quantity else None
        )
        if not pos_value_eur and spot_pos:
            pos_value_eur = spot_pos.get("value_eur")
        cost_eur = (
            round(entry_price * quantity, 4) if entry_price and quantity else None
        )
        pnl_eur = (
            round(pos_value_eur - cost_eur, 4)
            if pos_value_eur is not None and cost_eur is not None
            else None
        )
        pnl_pct = (
            round(pnl_eur / cost_eur * 100, 2)
            if pnl_eur is not None and cost_eur and cost_eur > 0
            else None
        )

        # Domyślny cel +10% jeśli brak celu i jest pozycja
        if effective_target is None and pos_value_eur:
            effective_target = round(pos_value_eur * 1.10, 2)
            goal_source = "auto_10pct"

        # 6. Obliczenia celu
        needed_move_eur: Optional[float] = None
        needed_move_pct: Optional[float] = None
        target_price: Optional[float] = None

        if effective_target and pos_value_eur is not None:
            needed_move_eur = round(effective_target - pos_value_eur, 4)
            if quantity and quantity > 0:
                target_price = effective_target / quantity
                if current_price and current_price > 0:
                    needed_move_pct = round(
                        (target_price - current_price) / current_price * 100, 2
                    )

        # 7. Zmienność — ATR jako % ceny za godzinę
        atr_hourly_pct: Optional[float] = None
        atr_daily_pct: Optional[float] = None
        atr_daily_eur: Optional[float] = None
        if atr and current_price and current_price > 0:
            atr_hourly_pct = atr / current_price * 100
            atr_daily_pct = atr_hourly_pct * 24
        if atr and quantity:
            atr_daily_eur = atr * 24 * quantity

        # 8. Trend
        if ema_20 and ema_50:
            trend = "WZROSTOWY" if ema_20 > ema_50 else "SPADKOWY"
        else:
            trend = "BRAK DANYCH"

        # 9. Reality score
        reality_score = 50
        days_needed: Optional[float] = None

        if needed_move_pct is not None and atr_hourly_pct and atr_hourly_pct > 0:
            if needed_move_pct <= 0:
                reality_score = 95
            else:
                # Oszacowanie czasu: ile godzin potrzeba przy efektywności kierunkowej ~25%
                hours_needed = needed_move_pct / (atr_hourly_pct * 0.25)
                days_needed = round(hours_needed / 24, 1)
                score_base = max(5, min(95, 100 - days_needed * 7))
                # Modyfikatory trendu i RSI
                if trend == "WZROSTOWY":
                    score_base = min(95, score_base + 10)
                elif trend == "SPADKOWY":
                    score_base = max(5, score_base - 15)
                if rsi is not None:
                    if rsi < rsi_buy:
                        score_base = min(95, score_base + 5)
                    elif rsi > rsi_sell:
                        score_base = max(5, score_base - 10)
                reality_score = int(score_base)

        # Reality label
        if reality_score >= 80:
            reality_label = "bardzo_realny"
            reality_label_pl = "Bardzo realny"
        elif reality_score >= 60:
            reality_label = "realny"
            reality_label_pl = "Realny"
        elif reality_score >= 40:
            reality_label = "mozliwy"
            reality_label_pl = "Możliwy"
        elif reality_score >= 20:
            reality_label = "trudny"
            reality_label_pl = "Trudny"
        else:
            reality_label = "malo_realny"
            reality_label_pl = "Mało realny"

        # 10. ETA
        eta_label: Optional[str] = None
        if days_needed is not None:
            if days_needed < 1:
                eta_label = "możliwe dzisiaj"
            elif days_needed < 3:
                eta_label = "w ciągu kilku dni"
            elif days_needed < 7:
                eta_label = "w ciągu tygodnia"
            elif days_needed < 14:
                eta_label = "w ciągu 2 tygodni"
            elif days_needed < 30:
                eta_label = "w ciągu miesiąca"
            else:
                eta_label = "ponad miesiąc"
        elif needed_move_pct is not None and needed_move_pct <= 0:
            eta_label = "cel już osiągnięty"

        # 11. Warunki wymagane do osiągnięcia celu
        required_conditions: List[str] = []
        if target_price and current_price and needed_move_pct is not None:
            sign = "+" if needed_move_pct > 0 else ""
            required_conditions.append(
                f"Cena musi wzrosnąć do {round(target_price, 6)} EUR ({sign}{round(needed_move_pct, 2)}%)"
            )
        required_conditions.append(
            "Trend EMA20 > EMA50 powinien być utrzymany lub osiągnięty"
        )
        if rsi_sell:
            required_conditions.append(
                f"RSI nie powinno przekroczyć {int(rsi_sell)} przed osiągnięciem celu"
            )
        if atr_daily_pct:
            min_daily_move = round(atr_daily_pct * 0.3, 2)
            required_conditions.append(
                f"Dzienny ruch cenowy w kierunku wzrostowym ≥ {min_daily_move}%"
            )

        # 12. Blokery
        main_blockers: List[str] = []
        if trend == "SPADKOWY":
            main_blockers.append(
                "Trend 1h jest spadkowy — EMA20 < EMA50, rynek idzie w dół"
            )
        if rsi is not None and rsi > rsi_sell:
            main_blockers.append(
                f"RSI {round(rsi, 1)} przekroczył {int(rsi_sell)} — rynek wykupiony, ryzyko korekty"
            )
        if needed_move_pct and atr_daily_pct and needed_move_pct > atr_daily_pct * 14:
            main_blockers.append(
                f"Potrzebny ruch +{round(needed_move_pct, 2)}% jest ponad 14-krotnym ATR dziennym ({round(atr_daily_pct, 2)}%) — cel bardzo odległy"
            )
        if pnl_pct is not None and pnl_pct < -5:
            main_blockers.append(
                f"Pozycja {round(pnl_pct, 1)}% pod kreską — wymaga najpierw odrobienia strat"
            )
        if not main_blockers:
            main_blockers.append(
                "Brak poważnych blokerów — warunki neutralne lub sprzyjające"
            )

        # 13. Alternatywne cele oparte na ATR
        safe_target = None
        balanced_target = None
        aggressive_target = None
        ai_exit_target = None

        if pos_value_eur is not None and atr_daily_eur:
            safe_val = round(pos_value_eur + atr_daily_eur * 3, 2)
            bal_val = round(pos_value_eur + atr_daily_eur * 7, 2)
            agg_val = round(pos_value_eur + atr_daily_eur * 14, 2)

            safe_target = {
                "value": safe_val,
                "reason": "Cel bezpieczny: +3 dni ruchu ATR (duże prawdopodobieństwo osiągnięcia)",
                "reality_score": _score_for_alt_target(
                    safe_val, quantity, current_price, atr_hourly_pct, trend
                ),
            }
            balanced_target = {
                "value": bal_val,
                "reason": "Cel wyważony: +7 dni ruchu ATR (dobry balans ryzyko/zysk)",
                "reality_score": _score_for_alt_target(
                    bal_val, quantity, current_price, atr_hourly_pct, trend
                ),
            }
            aggressive_target = {
                "value": agg_val,
                "reason": "Cel agresywny: +14 dni ruchu ATR (wymaga długoterminowej cierpliwości)",
                "reality_score": _score_for_alt_target(
                    agg_val, quantity, current_price, atr_hourly_pct, trend
                ),
            }

            # AI Exit: na podstawie stanu technicznego
            if trend == "WZROSTOWY" and rsi is not None and rsi < rsi_sell:
                ai_val = round(pos_value_eur + atr_daily_eur * 5, 2)
                ai_exit_target = {
                    "value": ai_val,
                    "reason": "Wyjście AI: trend wzrostowy + RSI nie wykupione → optymalne okno 5-dniowe",
                    "reality_score": _score_for_alt_target(
                        ai_val, quantity, current_price, atr_hourly_pct, trend
                    ),
                }
            elif trend == "SPADKOWY" and pnl_pct is not None and pnl_pct > 0:
                ai_val = round(pos_value_eur + atr_daily_eur * 1, 2)
                ai_exit_target = {
                    "value": ai_val,
                    "reason": "Wyjście AI: trend spadkowy z małym zyskiem → szybkie zabezpieczenie",
                    "reality_score": _score_for_alt_target(
                        ai_val, quantity, current_price, atr_hourly_pct, trend
                    ),
                }
            elif pnl_pct is not None and pnl_pct < -3 and cost_eur:
                ai_exit_target = {
                    "value": round(cost_eur, 2),
                    "reason": "Wyjście AI: odczekaj na break-even (zero strat) i zamknij pozycję",
                    "reality_score": _score_for_alt_target(
                        cost_eur, quantity, current_price, atr_hourly_pct, trend
                    ),
                }
            else:
                ai_val = round(pos_value_eur + atr_daily_eur * 3, 2)
                ai_exit_target = {
                    "value": ai_val,
                    "reason": "Wyjście AI: neutralne warunki — ostrożny cel 3-dniowy",
                    "reality_score": _score_for_alt_target(
                        ai_val, quantity, current_price, atr_hourly_pct, trend
                    ),
                }

        # 14. Decyzja główna
        goal_decision = "czekaj"
        goal_decision_reason_pl = "Brak wystarczających danych do oceny celu."

        if effective_target and pos_value_eur is not None:
            if needed_move_pct is not None and needed_move_pct <= 0:
                goal_decision = "sprzedaj_teraz"
                goal_decision_reason_pl = (
                    f"Cel {round(effective_target, 2)} EUR osiągnięty! "
                    f"Aktualna wartość pozycji ({round(pos_value_eur, 2)} EUR) przekracza cel. "
                    f"Zalecamy sprzedaż teraz, aby zabezpieczyć zysk."
                )
            elif reality_score < 20:
                alt_val = safe_target["value"] if safe_target else "N/A"
                goal_decision = "zmień_cel"
                goal_decision_reason_pl = (
                    f"Cel {round(effective_target, 2)} EUR jest mało realny (score: {reality_score}/100). "
                    f"Potrzebny ruch +{round(needed_move_pct or 0, 2)}% wymaga ~{days_needed} dni przy obecnej zmienności. "
                    f"Rozważ cel bezpieczny: {alt_val} EUR."
                )
            elif pnl_pct is not None and pnl_pct < -5 and trend == "SPADKOWY":
                goal_decision = "rozważ_zamknięcie"
                goal_decision_reason_pl = (
                    f"Pozycja traci {round(pnl_pct, 1)}% przy spadkowym trendzie. "
                    f"Cel {round(effective_target, 2)} EUR jest trudny do osiągnięcia. "
                    f"Rozważ zamknięcie pozycji i ograniczenie strat."
                )
            elif (
                trend == "WZROSTOWY"
                and rsi is not None
                and rsi < rsi_sell
                and reality_score >= 40
            ):
                goal_decision = "czekaj"
                goal_decision_reason_pl = (
                    f"System pracuje w kierunku celu. Trend wzrostowy, RSI {round(rsi, 1)} nie osiągnęło "
                    f"wykupienia ({int(rsi_sell)}). Do celu brakuje {round(needed_move_eur or 0, 2)} EUR "
                    f"(+{round(needed_move_pct or 0, 2)}%). Szacowany czas: {eta_label or 'nieznany'}. Trzymaj pozycję."
                )
            elif trend == "SPADKOWY" and rsi is not None and rsi < rsi_buy:
                goal_decision = "czekaj_na_odbicie"
                goal_decision_reason_pl = (
                    f"Rynek wyprzedany (RSI {round(rsi, 1)} < {int(rsi_buy)}), mimo trendu spadkowego. "
                    f"Możliwe techniczne odbicie. Cel {round(effective_target, 2)} EUR może być osiągalny "
                    f"po potwierdzeniu odwrócenia trendu. Poczekaj na sygnał."
                )
            else:
                goal_decision = "czekaj"
                trend_pl = trend.lower() if trend != "BRAK DANYCH" else "nieznany"
                goal_decision_reason_pl = (
                    f"Cel {round(effective_target, 2)} EUR jest {reality_label_pl.lower()} "
                    f"(score: {reality_score}/100, ETA: {eta_label or 'nieznany'}). "
                    f"Trend: {trend_pl}. RSI: {round(rsi, 1) if rsi is not None else 'N/A'}. "
                    f"Monitoruj warunki rynkowe."
                )

        return {
            "symbol": symbol,
            "mode": mode,
            # Pozycja
            "has_position": has_position,
            "current_price": current_price,
            "entry_price": entry_price,
            "quantity": quantity,
            "position_value_eur": pos_value_eur,
            "cost_eur": cost_eur,
            "current_pnl_eur": pnl_eur,
            "current_pnl_pct": pnl_pct,
            # Cel
            "goal_source": goal_source,
            "goal_label": goal_label,
            "goal_set_at": goal_set_at,
            "goal_type": "target_value_eur",
            "goal_value": effective_target,
            "target_price": round(target_price, 8) if target_price else None,
            # Ocena realności
            "goal_reality_score": reality_score,
            "goal_reality_label": reality_label,
            "goal_reality_label_pl": reality_label_pl,
            "needed_move_pct": needed_move_pct,
            "needed_move_eur": (
                round(needed_move_eur, 4) if needed_move_eur is not None else None
            ),
            "distance_to_goal_eur": (
                round(needed_move_eur, 4) if needed_move_eur is not None else None
            ),
            # Czas
            "days_needed": days_needed,
            "eta_label": eta_label,
            # Wskaźniki techniczne
            "trend": trend,
            "rsi": round(rsi, 1) if rsi is not None else None,
            "rsi_buy_threshold": round(rsi_buy, 1),
            "rsi_sell_threshold": round(rsi_sell, 1),
            "ema_20": round(ema_20, 8) if ema_20 else None,
            "ema_50": round(ema_50, 8) if ema_50 else None,
            "atr": round(atr, 8) if atr else None,
            "atr_hourly_pct": round(atr_hourly_pct, 4) if atr_hourly_pct else None,
            # Analiza jakościowa
            "required_conditions": required_conditions,
            "main_blockers": main_blockers,
            # Alternatywy
            "suggested_safe_target": safe_target,
            "suggested_balanced_target": balanced_target,
            "suggested_aggressive_target": aggressive_target,
            "suggested_ai_exit": ai_exit_target,
            # Decyzja
            "goal_decision": goal_decision,
            "goal_decision_reason_pl": goal_decision_reason_pl,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd analizy celu: {str(e)}")


# GOALS SUMMARY — skrócone podsumowanie wszystkich celów dla dashboardu
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/goals-summary")
def get_goals_summary(
    mode: str = Query("live", description="demo lub live"),
    db: Session = Depends(get_db),
):
    """
    Zwraca listę wszystkich pozycji z ustawionymi celami i ich oceną.
    Używane przez dashboard do bloku 'Na jakie cele teraz pracuje system?'
    """
    try:
        positions = db.query(Position).filter(Position.mode == mode).all()

        # Dla LIVE: uzupełnij pozycjami z Binance spot (mogą nie być w lokalnej DB)
        all_symbols_data: Dict[str, Dict[str, Any]] = {}
        for pos in positions:
            all_symbols_data[pos.symbol] = {
                "current_price": float(pos.current_price or 0),
                "quantity": float(pos.quantity or 0),
            }
        if mode == "live":
            for s in _get_live_spot_positions(db):
                sym = s["symbol"]
                if sym not in all_symbols_data:
                    all_symbols_data[sym] = {
                        "current_price": s.get("current_price", 0),
                        "quantity": s.get("quantity", 0),
                    }

        result = []

        for sym, pos_data in all_symbols_data.items():
            goal_key = f"user_goal_{sym}"
            goal_rec = (
                db.query(RuntimeSetting).filter(RuntimeSetting.key == goal_key).first()
            )
            if not goal_rec:
                continue
            try:
                stored_goal = json.loads(goal_rec.value)
            except Exception:
                continue

            target_eur = float(stored_goal.get("target_eur", 0) or 0)
            if not target_eur:
                continue

            current_price = pos_data["current_price"]
            quantity = pos_data["quantity"]
            pos_value_eur = (
                round(current_price * quantity, 4)
                if current_price and quantity
                else None
            )

            ctx = get_live_context(db, sym, timeframe="1h", limit=200)
            if not ctx or not pos_value_eur:
                result.append(
                    {
                        "symbol": sym,
                        "goal_value": target_eur,
                        "goal_label": stored_goal.get("label", ""),
                        "position_value_eur": pos_value_eur,
                        "needed_move_eur": (
                            round(target_eur - pos_value_eur, 4)
                            if pos_value_eur
                            else None
                        ),
                        "goal_reality_label_pl": "Brak danych",
                        "goal_reality_score": 50,
                        "goal_decision": "brak_danych",
                        "eta_label": None,
                        "trend": "BRAK DANYCH",
                    }
                )
                continue

            # Oblicz osnovowe wskaźniki
            atr = ctx.get("atr")
            ema_20 = ctx.get("ema_20")
            ema_50 = ctx.get("ema_50")
            rsi = ctx.get("rsi")
            rsi_buy = float(ctx.get("rsi_buy") or 30.0)
            rsi_sell = float(ctx.get("rsi_sell") or 70.0)
            atr_hourly_pct = (
                (atr / current_price * 100) if atr and current_price > 0 else None
            )

            if ema_20 and ema_50:
                trend = "WZROSTOWY" if ema_20 > ema_50 else "SPADKOWY"
            else:
                trend = "BRAK DANYCH"

            needed_move_eur = round(target_eur - pos_value_eur, 4)
            needed_move_pct = None
            days_needed = None
            if quantity > 0 and current_price > 0:
                target_price = target_eur / quantity
                needed_move_pct = round(
                    (target_price - current_price) / current_price * 100, 2
                )
                if atr_hourly_pct and atr_hourly_pct > 0 and needed_move_pct > 0:
                    hours = needed_move_pct / (atr_hourly_pct * 0.25)
                    days_needed = round(hours / 24, 1)

            # Reality score
            reality_score = 50
            if needed_move_pct is not None and atr_hourly_pct and atr_hourly_pct > 0:
                if needed_move_pct <= 0:
                    reality_score = 95
                elif days_needed is not None:
                    s = max(5, min(95, 100 - days_needed * 7))
                    if trend == "WZROSTOWY":
                        s = min(95, s + 10)
                    elif trend == "SPADKOWY":
                        s = max(5, s - 15)
                    reality_score = int(s)

            if reality_score >= 80:
                reality_label_pl = "Bardzo realny"
                reality_label = "bardzo_realny"
            elif reality_score >= 60:
                reality_label_pl = "Realny"
                reality_label = "realny"
            elif reality_score >= 40:
                reality_label_pl = "Możliwy"
                reality_label = "mozliwy"
            elif reality_score >= 20:
                reality_label_pl = "Trudny"
                reality_label = "trudny"
            else:
                reality_label_pl = "Mało realny"
                reality_label = "malo_realny"

            eta_label = None
            if days_needed is not None:
                if days_needed < 1:
                    eta_label = "możliwe dzisiaj"
                elif days_needed < 3:
                    eta_label = "kilka dni"
                elif days_needed < 7:
                    eta_label = "~tydzień"
                elif days_needed < 14:
                    eta_label = "~2 tygodnie"
                elif days_needed < 30:
                    eta_label = "~miesiąc"
                else:
                    eta_label = "ponad miesiąc"
            elif needed_move_pct is not None and needed_move_pct <= 0:
                eta_label = "osiągnięty!"

            # Prosta decyzja
            goal_decision = "czekaj"
            if needed_move_pct is not None and needed_move_pct <= 0:
                goal_decision = "sprzedaj_teraz"
            elif reality_score < 20:
                goal_decision = "zmień_cel"
            elif rsi and rsi > rsi_sell and trend == "SPADKOWY":
                goal_decision = "rozważ_zamknięcie"
            elif trend == "WZROSTOWY" and reality_score >= 40:
                goal_decision = "czekaj"

            result.append(
                {
                    "symbol": sym,
                    "goal_value": target_eur,
                    "goal_label": stored_goal.get("label", ""),
                    "position_value_eur": pos_value_eur,
                    "needed_move_eur": needed_move_eur,
                    "needed_move_pct": needed_move_pct,
                    "goal_reality_label": reality_label,
                    "goal_reality_label_pl": reality_label_pl,
                    "goal_reality_score": reality_score,
                    "goal_decision": goal_decision,
                    "eta_label": eta_label,
                    "trend": trend,
                    "rsi": round(rsi, 1) if rsi else None,
                    "days_needed": days_needed,
                }
            )

        return {
            "success": True,
            "mode": mode,
            "count": len(result),
            "data": result,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Błąd podsumowania celów: {str(e)}"
        )


# GOAL EVALUATOR — ocena celu użytkownika (POST)
# ─────────────────────────────────────────────────────────────────────────────


class GoalEvaluateRequest(BaseModel):
    mode: str = "demo"
    goal_type: str = "target_value_eur"  # target_value_eur | target_profit_pct
    current_value: Optional[float] = None  # nadpisanie (opcjonalnie)
    target_value: float
    horizon_days: Optional[int] = None
    symbol: Optional[str] = None  # None = cel portfoliowy


@router.post("/goals/evaluate")
def evaluate_goal(
    body: GoalEvaluateRequest,
    db: Session = Depends(get_db),
):
    """
    Ocenia realność celu użytkownika.
    Obsługuje cele per-symbol (gdy symbol podany) i portfoliowe (gdy symbol=null).
    Zwraca: required_move_pct, required_profit_eur, realism, suggested_path.
    """
    try:
        mode = body.mode
        symbol = body.symbol
        target_value = body.target_value
        horizon_days = body.horizon_days

        # --- Określ aktualną wartość ---
        actual_value: Optional[float] = body.current_value

        if symbol:
            # Per-symbol evaluation
            ctx = get_live_context(db, symbol, timeframe="1h", limit=200)
            current_price = ctx["close"] if ctx else None

            pos = (
                db.query(Position)
                .filter(Position.symbol == symbol, Position.mode == mode)
                .first()
            )
            quantity = float(pos.quantity) if pos and pos.quantity else None

            if not quantity and mode == "live":
                for s in _get_live_spot_positions(db):
                    if s["symbol"] == symbol:
                        quantity = s.get("quantity")
                        current_price = s.get("current_price") or current_price
                        break

            if actual_value is None and current_price and quantity:
                actual_value = round(current_price * quantity, 4)

            # Wskaźniki
            atr = ctx.get("atr") if ctx else None
            ema_20 = ctx.get("ema_20") if ctx else None
            ema_50 = ctx.get("ema_50") if ctx else None
            rsi = ctx.get("rsi") if ctx else None
            atr_hourly_pct = (
                (atr / current_price * 100)
                if atr and current_price and current_price > 0
                else None
            )
        else:
            # Portfolio-level evaluation
            current_price = None
            quantity = None
            atr = None
            ema_20 = None
            ema_50 = None
            rsi = None
            atr_hourly_pct = None

            if actual_value is None:
                if mode == "live":
                    from backend.routers.portfolio import _build_live_spot_portfolio

                    port = _build_live_spot_portfolio(db)
                    actual_value = round(
                        sum(
                            s.get("value_eur", 0)
                            for s in port.get("spot_positions", [])
                        ),
                        2,
                    )
                else:
                    from backend.accounting import compute_demo_account_state

                    state = compute_demo_account_state(db)
                    actual_value = round(state.get("equity", 0), 2)

        if actual_value is None or actual_value <= 0:
            return {
                "success": False,
                "error": "Nie udało się ustalić aktualnej wartości. Podaj current_value ręcznie.",
            }

        # --- Obliczenia ---
        required_profit_eur = round(target_value - actual_value, 2)
        required_move_pct = (
            round((target_value - actual_value) / actual_value * 100, 2)
            if actual_value > 0
            else None
        )

        # Trend
        if ema_20 and ema_50:
            trend = "WZROSTOWY" if ema_20 > ema_50 else "SPADKOWY"
        else:
            trend = "BRAK DANYCH"

        # Reality score
        reality_score = 50
        days_needed: Optional[float] = None

        if required_move_pct is not None and required_move_pct <= 0:
            reality_score = 95
        elif required_move_pct is not None and atr_hourly_pct and atr_hourly_pct > 0:
            hours = required_move_pct / (atr_hourly_pct * 0.25)
            days_needed = round(hours / 24, 1)
            if horizon_days and days_needed > horizon_days:
                reality_score = max(5, int(50 - (days_needed - horizon_days) * 3))
            else:
                reality_score = max(5, min(95, int(100 - days_needed * 7)))
            if trend == "WZROSTOWY":
                reality_score = min(95, reality_score + 10)
            elif trend == "SPADKOWY":
                reality_score = max(5, reality_score - 15)
        elif required_move_pct is not None and not atr_hourly_pct:
            # Brak ATR — ocena na podstawie samego move%
            if required_move_pct < 5:
                reality_score = 75
            elif required_move_pct < 20:
                reality_score = 50
            elif required_move_pct < 50:
                reality_score = 30
            else:
                reality_score = 15

        # Reality label
        if reality_score >= 80:
            realism = "bardzo_realny"
        elif reality_score >= 60:
            realism = "realny"
        elif reality_score >= 40:
            realism = "mozliwy"
        elif reality_score >= 20:
            realism = "trudny"
        else:
            realism = "malo_realny"

        # Suggested path
        suggested_path: List[str] = []
        if required_move_pct is not None and required_move_pct <= 0:
            suggested_path.append("Cel już osiągnięty — rozważ zabezpieczenie zysku.")
        else:
            if trend == "WZROSTOWY":
                suggested_path.append("Trend wzrostowy sprzyja — trzymaj pozycję.")
            elif trend == "SPADKOWY":
                suggested_path.append(
                    "Trend spadkowy — rozważ częściową redukcję lub poczekaj na odwrócenie."
                )
            if rsi is not None and rsi > 70:
                suggested_path.append(
                    "RSI wykupione — możliwa korekta przed dalszym wzrostem."
                )
            if days_needed and days_needed > 14:
                suggested_path.append(
                    f"Szacowany czas ~{days_needed} dni — cel wymaga cierpliwości."
                )
            if horizon_days and days_needed and days_needed > horizon_days:
                suggested_path.append(
                    f"Przy obecnej zmienności cel wymaga ~{days_needed} dni, a horyzont to {horizon_days} dni. "
                    f"Rozważ obniżenie celu lub wydłużenie horyzontu."
                )
            if not suggested_path:
                suggested_path.append("Monitoruj warunki rynkowe i sygnały systemu.")

        return {
            "success": True,
            "mode": mode,
            "symbol": symbol,
            "goal_type": body.goal_type,
            "current_value": actual_value,
            "target_value": target_value,
            "horizon_days": horizon_days,
            "required_profit_eur": required_profit_eur,
            "required_move_pct": required_move_pct,
            "realism": realism,
            "reality_score": reality_score,
            "days_needed": days_needed,
            "trend": trend,
            "rsi": round(rsi, 1) if rsi else None,
            "suggested_path": suggested_path,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd oceny celu: {str(e)}")


# DECISION HISTORY — historia decyzji bota per symbol
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/decisions/{symbol}")
def get_decision_history(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Zwraca historię decyzji systemu dla symbolu (z tabeli decision_traces)."""
    try:
        traces = (
            db.query(DecisionTrace)
            .filter(DecisionTrace.symbol == symbol)
            .order_by(desc(DecisionTrace.timestamp))
            .limit(limit)
            .all()
        )
        items = []
        for t in traces:
            items.append(
                {
                    "id": t.id,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "action_type": t.action_type,
                    "reason_code": t.reason_code,
                    "mode": t.mode,
                    "strategy_name": t.strategy_name,
                    "signal_summary": t.signal_summary,
                    "timeframe": t.timeframe,
                }
            )
        return {"success": True, "symbol": symbol, "count": len(items), "data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd historii decyzji: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATE GOAL — ocena realności celu użytkownika
# ─────────────────────────────────────────────────────────────────────────────


class GoalEvaluateRequest(BaseModel):
    mode: str = "demo"
    target_type: (
        str  # "position_value" | "portfolio_value" | "price_target" | "profit_pct"
    )
    symbol: Optional[str] = None
    current_value: Optional[float] = None  # EUR albo cena
    target_value: Optional[float] = None  # wartość docelowa
    current_price: Optional[float] = None
    entry_price: Optional[float] = None
    quantity: Optional[float] = None


@router.post("/evaluate-goal")
def evaluate_goal(
    req: GoalEvaluateRequest,
    db: Session = Depends(get_db),
):
    """
    Ocenia realność celu użytkownika.
    Przykłady: 'z 500 zrobić 650 EUR', 'ETHEUR do +8%', 'BTC przy cenie 62000'.

    Zwraca: ocenę realności, wymagany ruch %, czas potrzebny, wyjaśnienie po polsku.
    """
    try:
        sym = (req.symbol or "").strip().upper().replace("/", "").replace("-", "")
        current_v = float(req.current_value or 0)
        target_v = float(req.target_value or 0)
        entry_p = float(req.entry_price or 0)
        current_p = float(req.current_price or 0)
        qty = float(req.quantity or 0)

        # Jeśli cena nie podana, pobierz z DB lub MarketData
        if sym and current_p <= 0:
            md = (
                db.query(MarketData)
                .filter(MarketData.symbol == sym)
                .order_by(MarketData.timestamp.desc())
                .first()
            )
            if md and md.price:
                current_p = float(md.price)

        # Pobierz wskaźniki techniczne jeśli dostępny symbol
        ctx = get_live_context(db, sym, timeframe="1h", limit=200) if sym else None
        atr = float(ctx.get("atr") or 0) if ctx else 0
        ema_20 = float(ctx.get("ema_20") or 0) if ctx else 0
        ema_50 = float(ctx.get("ema_50") or 0) if ctx else 0
        rsi = float(ctx.get("rsi") or 50) if ctx else 50

        trend_support = None
        if ema_20 > 0 and ema_50 > 0:
            if ema_20 > ema_50:
                trend_support = "wzrostowy"
            else:
                trend_support = "spadkowy"

        # ─── Oblicz wymagany ruch ─────────────────────────────────────────────
        required_move_pct: float = 0.0
        required_price: Optional[float] = None
        required_profit_eur: Optional[float] = None

        if req.target_type == "position_value":
            # Cel: wartość pozycji w EUR. np. "WLFI do 300 EUR"
            if qty > 0 and current_p > 0:
                current_pos_value = current_p * qty
                target_pos_value = target_v
                if current_pos_value > 0:
                    required_move_pct = round(
                        (target_pos_value - current_pos_value)
                        / current_pos_value
                        * 100,
                        2,
                    )
                required_price = round(target_pos_value / qty, 8) if qty > 0 else None
                required_profit_eur = (
                    round(target_pos_value - current_pos_value, 2) if qty > 0 else None
                )
                current_v = current_pos_value

        elif req.target_type == "portfolio_value":
            # Cel: wartość całego portfela. np. "z 500 zrobić 650"
            if current_v > 0 and target_v > 0:
                required_move_pct = round((target_v - current_v) / current_v * 100, 2)
                required_profit_eur = round(target_v - current_v, 2)

        elif req.target_type == "price_target":
            # Cel: konkretna cena. np. "BTC przy 62000"
            if current_p > 0 and target_v > 0:
                required_move_pct = round((target_v - current_p) / current_p * 100, 2)
                required_price = target_v
                if qty > 0:
                    required_profit_eur = round(
                        (target_v - (entry_p or current_p)) * qty, 2
                    )

        elif req.target_type == "profit_pct":
            # Cel: procent zysku. np. "+8%"
            required_move_pct = float(target_v)
            if entry_p > 0 and qty > 0:
                required_price = round(entry_p * (1 + required_move_pct / 100), 8)
                required_profit_eur = round((required_price - entry_p) * qty, 2)

        # ─── Szacuj czas ─────────────────────────────────────────────────────
        atr_hourly_pct = (atr / current_p * 100) if atr > 0 and current_p > 0 else 0
        abs_move = abs(required_move_pct)

        def _estimate_horizon(multiplier: float) -> str:
            if atr_hourly_pct <= 0 or abs_move <= 0:
                return "brak danych"
            h = abs_move / (atr_hourly_pct * multiplier)
            if h < 1:
                return "możliwe w ciągu godziny"
            elif h < 6:
                return f"ok. {h:.0f}h"
            elif h < 24:
                return "dzisiaj lub jutro"
            elif h < 72:
                return f"ok. {h / 24:.0f} dni"
            elif h < 168:
                return "ok. tydzień"
            else:
                return "ponad tydzień"

        horizon_estimate = {
            "1h": _estimate_horizon(0.5),  # wolny rynek
            "4h": _estimate_horizon(1.0),  # normalny rynek
            "24h": _estimate_horizon(2.0),  # szybki rynek
            "7d": _estimate_horizon(5.0),  # bardzo szybki rynek
        }

        # ─── Ocena realności ─────────────────────────────────────────────────
        if required_move_pct <= 0:
            realism = "bardzo_realny"
            realism_score = 95
        elif atr_hourly_pct > 0:
            hours_needed = abs_move / (atr_hourly_pct * 1.0)
            base_score = max(5, min(95, 100 - hours_needed * 5))
            if trend_support == "wzrostowy" and required_move_pct > 0:
                base_score = min(95, base_score + 12)
            elif trend_support == "spadkowy" and required_move_pct > 0:
                base_score = max(5, base_score - 20)
            realism_score = int(base_score)
            if realism_score >= 80:
                realism = "bardzo_realny"
            elif realism_score >= 60:
                realism = "realny"
            elif realism_score >= 40:
                realism = "mozliwy"
            elif realism_score >= 20:
                realism = "trudny"
            else:
                realism = "malo_realny"
        else:
            realism_score = 50
            realism = "mozliwy"

        # ─── Ocena ryzyka do celu ─────────────────────────────────────────────
        risk_to_target = None
        if atr > 0 and current_p > 0 and required_move_pct != 0:
            atr_moves_needed = abs_move / (atr / current_p * 100)
            risk_to_target = round(atr_moves_needed, 1)

        # ─── Wyjaśnienie po polsku ─────────────────────────────────────────────
        target_type_pl = {
            "position_value": "wartości pozycji",
            "portfolio_value": "wartości portfela",
            "price_target": "ceny docelowej",
            "profit_pct": "procentu zysku",
        }.get(req.target_type, req.target_type)

        if required_move_pct <= 0:
            explanation_pl = (
                f"Cel {target_type_pl} already osiągnięty lub nie wymaga ruchu rynku."
            )
        else:
            trend_comment = ""
            if trend_support == "wzrostowy":
                trend_comment = " Trend jest wzrostowy — sprzyja osiągnięciu celu."
            elif trend_support == "spadkowy":
                trend_comment = (
                    " Uwaga: trend jest teraz spadkowy — to utrudnia osiągnięcie celu."
                )

            realism_pl = {
                "bardzo_realny": "Bardzo realny",
                "realny": "Realny",
                "mozliwy": "Możliwy",
                "trudny": "Trudny",
                "malo_realny": "Mało realny",
            }.get(realism, realism)

            explanation_pl = (
                f"Cel {target_type_pl}: wymaga ruchu +{required_move_pct:.1f}% od aktualnej wartości."
                f"{trend_comment}"
                f" Ocena: {realism_pl}."
            )
            if required_profit_eur is not None:
                explanation_pl += f" Potrzebny zysk: {required_profit_eur:.2f} EUR."
            if rsi < 35:
                explanation_pl += (
                    f" RSI = {rsi:.0f} — rynek wyprzedany, szansa na wzrost."
                )
            elif rsi > 70:
                explanation_pl += f" RSI = {rsi:.0f} — rynek wykupiony, ryzyko korekty."

        return {
            "success": True,
            "target_type": req.target_type,
            "symbol": sym or None,
            "current_value": round(current_v, 4),
            "target_value": round(target_v, 4),
            "realism": realism,
            "realism_score": realism_score,
            "required_move_pct": required_move_pct,
            "required_price": required_price,
            "required_profit_eur": required_profit_eur,
            "horizon_estimate": horizon_estimate,
            "trend_support": trend_support,
            "rsi": round(rsi, 1) if rsi else None,
            "risk_to_target": risk_to_target,
            "explanation_pl": explanation_pl,
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Błąd oceny celu: {str(exc)}")


# ─────────────────────────────────────────────────────────────────────────────
# SYNC — import pozycji z Binance do bazy bota
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/sync-from-binance")
def sync_positions_from_binance(
    mode: str = Query(
        "live", description="Tryb: live (odczyt z Binance) lub demo (symulacja)"
    ),
    overwrite: bool = Query(False, description="Nadpisz istniejące pozycje jeśli true"),
    db: Session = Depends(get_db),
):
    """
    Importuje posiadane aktywa z Binance jako pozycje bota.
    Dla każdego aktywa z niezerowym saldem:
    - szuka istniejącej pozycji w DB,
    - jeśli nie ma → tworzy nową z aktualną ceną rynkową,
    - data otwarcia = data ostatniej transakcji BUY na Binance (jeśli dostępna),
    - entry_price = średnia ważona z historii zleceń (lub aktualny kurs jeśli brak historii).
    """
    try:
        binance = get_binance_client()
        balances = binance.get_balances() or {}

        from backend.database import get_demo_quote_ccy

        quote_ccy = get_demo_quote_ccy()

        synced = []
        skipped = []
        errors = []
        now = utc_now_naive()

        for asset, info in balances.items():
            if asset == quote_ccy:
                continue
            free = float(info.get("free", 0.0))
            locked = float(info.get("locked", 0.0))
            total_qty = free + locked
            if total_qty < 1e-8:
                continue

            symbol = f"{asset}{quote_ccy}"

            ticker = binance.get_ticker_price(symbol)
            if not ticker or not ticker.get("price"):
                errors.append(
                    {
                        "symbol": symbol,
                        "error": "Brak ceny rynkowej (para może nie istnieć)",
                    }
                )
                continue
            current_price = float(ticker["price"])

            # Pomiń pył (wartość < min_order_notional z config, domyślnie 25 EUR)
            from backend.runtime_settings import get_runtime_config

            _rt_cfg = get_runtime_config(db)
            _min_notional_sync = float(_rt_cfg.get("min_order_notional", 25.0))
            position_value = total_qty * current_price
            if position_value < _min_notional_sync:
                skipped.append(
                    {
                        "symbol": symbol,
                        "reason": f"Pył — wartość {position_value:.4f} EUR < min {_min_notional_sync:.0f} EUR",
                        "qty": round(total_qty, 8),
                    }
                )
                continue

            existing = (
                db.query(Position)
                .filter(
                    Position.symbol == symbol,
                    Position.mode == mode,
                )
                .first()
            )

            if existing and not overwrite:
                skipped.append(
                    {
                        "symbol": symbol,
                        "reason": "Pozycja już istnieje (użyj overwrite=true żeby nadpisać)",
                        "qty": float(existing.quantity),
                        "entry_price": float(existing.entry_price),
                    }
                )
                continue

            baseline = _resolve_live_position_baseline(
                db,
                symbol,
                total_qty,
                current_price,
                binance_client=binance,
            )

            entry_price = baseline.get("entry_price")
            opened_at = baseline.get("opened_at") or now
            if entry_price is None:
                skipped.append(
                    {
                        "symbol": symbol,
                        "reason": "Brak historii transakcji do wyliczenia ceny wejścia",
                        "qty": round(total_qty, 8),
                    }
                )
                continue

            unrealized_pnl = (current_price - entry_price) * total_qty

            if existing and overwrite:
                existing.entry_price = entry_price
                existing.quantity = total_qty
                existing.current_price = current_price
                existing.unrealized_pnl = unrealized_pnl
                existing.updated_at = now
                existing.opened_at = opened_at
                existing.entry_reason_code = "synced_from_binance"
            else:
                new_pos = Position(
                    symbol=symbol,
                    side="LONG",
                    entry_price=entry_price,
                    quantity=total_qty,
                    current_price=current_price,
                    unrealized_pnl=unrealized_pnl,
                    gross_pnl=unrealized_pnl,
                    net_pnl=unrealized_pnl,
                    total_cost=0.0,
                    fee_cost=0.0,
                    slippage_cost=0.0,
                    spread_cost=0.0,
                    mode=mode,
                    opened_at=opened_at,
                    entry_reason_code="synced_from_binance",
                )
                db.add(new_pos)

            synced.append(
                {
                    "symbol": symbol,
                    "qty": round(total_qty, 8),
                    "entry_price": round(entry_price, 6),
                    "current_price": round(current_price, 6),
                    "unrealized_pnl": round(unrealized_pnl, 4),
                    "opened_at": opened_at.isoformat(),
                    "overwritten": existing is not None and overwrite,
                }
            )

        db.commit()
        return {
            "success": True,
            "mode": mode,
            "synced_count": len(synced),
            "skipped_count": len(skipped),
            "error_count": len(errors),
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "message": f"Zsynchronizowano {len(synced)} pozycji z Binance do trybu {mode.upper()}.",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Błąd synchronizacji Binance: {str(exc)}"
        )
