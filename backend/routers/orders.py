"""
Orders API Router - endpoints dla zleceń (demo i live)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel
import io
import csv
import json

from backend.database import get_db, Order, Alert, PendingOrder, MarketData, Position, utc_now_naive
from backend.auth import require_admin
from backend.binance_client import get_binance_client
from backend.analysis import build_market_snapshot, consult_trade_plan, evaluate_plan_revision
from backend.accounting import build_profitability_guard

router = APIRouter()


def _load_plan_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _plan_payload(plan: Optional[Dict[str, Any]], item: Any) -> Dict[str, Any]:
    plan = plan or {}
    last_consulted_at = getattr(item, "last_consulted_at", None)
    return {
        "plan_status": getattr(item, "plan_status", None) or plan.get("plan_status"),
        "action": plan.get("action"),
        "entry_price": plan.get("entry_price"),
        "acceptable_entry_range": plan.get("acceptable_entry_range"),
        "take_profit_price": plan.get("take_profit_price"),
        "stop_loss_price": plan.get("stop_loss_price"),
        "break_even_price": plan.get("break_even_price"),
        "trailing_activation_price": plan.get("trailing_activation_price"),
        "trailing_distance": plan.get("trailing_distance"),
        "expected_total_cost": plan.get("expected_total_cost"),
        "expected_net_profit": plan.get("expected_net_profit"),
        "expected_net_profit_pct": plan.get("expected_net_profit_pct"),
        "confidence_score": plan.get("confidence_score"),
        "risk_score": plan.get("risk_score"),
        "trade_quality_score": plan.get("trade_quality_score"),
        "cost_efficiency_score": plan.get("cost_efficiency_score"),
        "requires_revision": bool(getattr(item, "requires_revision", False) or plan.get("requires_revision")),
        "invalidation_reason": getattr(item, "invalidation_reason", None) or plan.get("invalidation_reason"),
        "last_consulted_at": last_consulted_at.isoformat() if isinstance(last_consulted_at, datetime) else plan.get("last_consulted_at"),
        "plan": plan,
    }


class OrderCreate(BaseModel):
    """Model do tworzenia zlecenia"""
    symbol: str
    side: str  # BUY, SELL
    order_type: str = "MARKET"  # MARKET, LIMIT
    price: Optional[float] = None
    quantity: float


class PendingOrderCreate(BaseModel):
    symbol: str
    side: str  # BUY, SELL
    quantity: float
    price: Optional[float] = None
    reason: Optional[str] = None


@router.get("")
def get_orders(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    status: Optional[str] = Query(None, description="Filtr po statusie (FILLED, CANCELLED, etc.)"),
    symbol: Optional[str] = Query(None, description="Filtr po symbolu"),
    limit: int = Query(100, ge=1, le=500, description="Limit zleceń"),
    db: Session = Depends(get_db)
):
    """
    Pobierz listę zleceń
    """
    try:
        # Query builder
        query = db.query(Order).filter(Order.mode == mode)
        
        if status:
            query = query.filter(Order.status == status)
        
        if symbol:
            query = query.filter(Order.symbol == symbol)
        
        # Pobierz zlecenia
        orders = query.order_by(desc(Order.timestamp)).limit(limit).all()
        
        # Bez generatora demo - tylko realne dane
        
        # Formatuj dane
        result = []
        for order in orders:
            plan = _load_plan_json(getattr(order, "decision_plan_json", None))
            # Spróbuj znaleźć powiązany alert z powodem
            reason = None
            alert = db.query(Alert).filter(
                Alert.symbol == order.symbol,
                Alert.alert_type == "SIGNAL",
                Alert.timestamp <= order.timestamp + timedelta(minutes=2),
                Alert.timestamp >= order.timestamp - timedelta(minutes=2)
            ).order_by(Alert.timestamp.desc()).first()
            if alert and alert.message:
                reason = alert.message
            result.append({
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "type": order.order_type,
                "price": order.price,
                "quantity": order.quantity,
                "status": order.status,
                "executed_price": order.executed_price,
                "executed_quantity": order.executed_quantity,
                "timestamp": order.timestamp.isoformat(),
                "reason": reason,
                "exchange_order_id": order.exchange_order_id,
                "notes": order.notes,
                **_plan_payload(plan, order),
            })
        
        return {
            "success": True,
            "mode": mode,
            "data": result,
            "count": len(result)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting orders: {str(e)}")


@router.get("/pending")
def get_pending_orders(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    status: Optional[str] = Query(None, description="PENDING/CONFIRMED/REJECTED/EXECUTED"),
    limit: int = Query(100, ge=1, le=500, description="Limit"),
    include_total: bool = Query(False, description="Jeśli true: zwróć total (count bez limit)"),
    db: Session = Depends(get_db)
):
    try:
        query = db.query(PendingOrder).filter(PendingOrder.mode == mode)
        if status:
            query = query.filter(PendingOrder.status == status)
        total = query.count() if include_total else None
        items = query.order_by(desc(PendingOrder.created_at)).limit(limit).all()
        data = []
        for p in items:
            plan = _load_plan_json(getattr(p, "decision_plan_json", None))
            data.append({
                "id": p.id,
                "symbol": p.symbol,
                "side": p.side,
                "order_type": p.order_type,
                "price": p.price,
                "quantity": p.quantity,
                "status": p.status,
                "reason": p.reason,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None,
                **_plan_payload(plan, p),
            })
        payload = {"success": True, "mode": mode, "data": data, "count": len(data)}
        if include_total:
            payload["total"] = int(total or 0)
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pending orders: {str(e)}")


@router.post("/pending")
def create_pending_order(
    payload: PendingOrderCreate,
    mode: str = Query("demo", description="Tryb: demo lub live (na start: tylko demo)"),
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Utwórz pending order (web/manual). Na start: tylko DEMO.
    """
    if mode != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be created")

    symbol = (payload.symbol or "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    symbol = symbol.replace(" ", "").replace("/", "").replace("-", "").upper()

    side = (payload.side or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="Invalid side. Use BUY or SELL")

    try:
        qty = float(payload.quantity or 0.0)
    except Exception:
        qty = 0.0
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    price = payload.price
    if price is None:
        latest = (
            db.query(MarketData)
            .filter(MarketData.symbol == symbol)
            .order_by(desc(MarketData.timestamp))
            .first()
        )
        if latest and latest.price is not None:
            try:
                price = float(latest.price)
            except Exception:
                price = None
    if price is None:
        raise HTTPException(status_code=400, detail="Price is required (no market data available)")
    try:
        price_f = float(price)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid price")
    if price_f <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")

    snapshot = build_market_snapshot(db, symbol, mode=mode)
    plan = consult_trade_plan(snapshot) if snapshot else None
    revision = evaluate_plan_revision(snapshot or {}, plan or {}) if snapshot and plan else None

    p = PendingOrder(
        symbol=symbol,
        side=side,
        order_type="MARKET",
        price=price_f,
        quantity=qty,
        mode="demo",
        status="PENDING",
        reason=(payload.reason or None),
        created_at=utc_now_naive(),
        decision_plan_json=json.dumps(plan, ensure_ascii=False) if plan else None,
        plan_status=(plan or {}).get("plan_status"),
        requires_revision=bool(revision and revision.get("requires_revision")),
        invalidation_reason=(revision or {}).get("reason") if revision else None,
        last_consulted_at=utc_now_naive() if plan else None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {
        "success": True,
        "data": {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side,
            "quantity": p.quantity,
            "price": p.price,
            "status": p.status,
            "reason": p.reason,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            **_plan_payload(plan, p),
        },
    }


@router.post("/pending/{pending_id}/confirm")
def confirm_pending_order(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Potwierdź pending order (web/admin). Na start: tylko DEMO.
    """
    p = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pending order not found")
    if (p.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be confirmed")
    if (p.status or "").upper() != "PENDING":
        raise HTTPException(status_code=409, detail="Pending order is not in PENDING status")

    p.status = "CONFIRMED"
    p.confirmed_at = utc_now_naive()
    db.commit()
    db.refresh(p)
    return {"success": True, "data": {"id": p.id, "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}}


@router.post("/pending/{pending_id}/reject")
def reject_pending_order(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Odrzuć pending order (web/admin). Na start: tylko DEMO.
    """
    p = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pending order not found")
    if (p.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be rejected")
    if (p.status or "").upper() != "PENDING":
        raise HTTPException(status_code=409, detail="Pending order is not in PENDING status")

    p.status = "REJECTED"
    p.confirmed_at = utc_now_naive()
    db.commit()
    db.refresh(p)
    return {"success": True, "data": {"id": p.id, "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}}


@router.post("/pending/{pending_id}/cancel")
def cancel_pending_order(
    pending_id: int,
    db: Session = Depends(get_db),
    admin: None = Depends(require_admin),
):
    """
    Anuluj pending order (web/admin). Na start: tylko DEMO. Działa tylko dla status=PENDING.
    """
    p = db.query(PendingOrder).filter(PendingOrder.id == pending_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Pending order not found")
    if (p.mode or "").lower() != "demo":
        raise HTTPException(status_code=403, detail="Only demo pending orders can be cancelled")
    if (p.status or "").upper() != "PENDING":
        raise HTTPException(status_code=409, detail="Pending order is not in PENDING status")

    p.status = "REJECTED"
    p.reason = (p.reason or "").strip() or None
    if p.reason:
        p.reason = f"{p.reason} (cancelled)"
    else:
        p.reason = "cancelled"
    p.confirmed_at = utc_now_naive()
    db.commit()
    db.refresh(p)
    return {"success": True, "data": {"id": p.id, "status": p.status, "confirmed_at": p.confirmed_at.isoformat()}}


@router.post("")
def create_order(
    order: OrderCreate,
    mode: str = Query("demo", description="Tryb: demo lub live"),
    db: Session = Depends(get_db)
):
    """
    Utwórz nowe zlecenie.
    - DEMO: zapis do lokalnej bazy, natychmiastowe FILLED.
    - LIVE: MARKET order na Binance → zapis fills do DB.
    """
    try:
        # Walidacja wspólna
        if order.side not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="Nieprawidłowy side. Użyj BUY lub SELL")
        if order.order_type not in ["MARKET", "LIMIT"]:
            raise HTTPException(status_code=400, detail="Nieprawidłowy typ. Użyj MARKET lub LIMIT")
        if order.quantity <= 0:
            raise HTTPException(status_code=400, detail="Ilość musi być większa od zera")
        symbol = (order.symbol or "").strip().replace(" ", "").replace("/", "").replace("-", "").upper()
        snapshot = build_market_snapshot(db, symbol, mode=mode)
        plan = consult_trade_plan(snapshot) if snapshot else None
        revision = evaluate_plan_revision(snapshot or {}, plan or {}) if snapshot and plan else None

        # ─── DEMO ───────────────────────────────────────────────────────────────
        if mode == "demo":
            if order.order_type == "LIMIT" and order.price:
                executed_price = order.price
            else:
                md = (
                    db.query(MarketData)
                    .filter(MarketData.symbol == symbol)
                    .order_by(MarketData.timestamp.desc())
                    .first()
                )
                if not md or not md.price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Brak danych rynkowych dla {symbol}. Uruchom kolektor."
                    )
                executed_price = float(md.price)

            new_order = Order(
                symbol=symbol,
                side=order.side,
                order_type=order.order_type,
                price=order.price,
                quantity=order.quantity,
                status="FILLED",
                mode="demo",
                executed_price=executed_price,
                executed_quantity=order.quantity,
                timestamp=utc_now_naive(),
                decision_plan_json=json.dumps(plan, ensure_ascii=False) if plan else None,
            )
            db.add(new_order)
            db.commit()
            db.refresh(new_order)

            return {
                "success": True,
                "message": f"Zlecenie demo {order.side} {order.quantity} {symbol} @ {executed_price:.4f}",
                "data": {
                    "id": new_order.id,
                    "symbol": new_order.symbol,
                    "side": new_order.side,
                    "type": new_order.order_type,
                    "quantity": new_order.quantity,
                    "status": new_order.status,
                    "executed_price": new_order.executed_price,
                    "executed_quantity": new_order.executed_quantity,
                    "timestamp": new_order.timestamp.isoformat(),
                    "mode": "demo",
                    **_plan_payload(plan, new_order),
                },
            }

        # ─── LIVE ────────────────────────────────────────────────────────────────
        binance = get_binance_client()

        # Sprawdź klucze
        if not binance.api_key or not binance.api_secret:
            raise HTTPException(
                status_code=503,
                detail="Brak kluczy Binance API. Ustaw BINANCE_API_KEY i BINANCE_API_SECRET w .env"
            )

        # Tylko MARKET na start (bezpieczeństwo)
        if order.order_type != "MARKET":
            raise HTTPException(
                status_code=400,
                detail="Tryb LIVE obsługuje tylko MARKET orders. Zmień order_type na MARKET."
            )

        if not snapshot or not plan:
            raise HTTPException(status_code=409, detail="Brak kompletnego planu transakcji dla zlecenia LIVE")

        market_price = float(snapshot.get("price") or 0.0)
        qty = binance.normalize_quantity(symbol, float(order.quantity))
        if qty <= 0:
            raise HTTPException(status_code=409, detail="Ilość po normalizacji Binance jest zerowa")

        allowed = binance.get_allowed_symbols().get(symbol) or {}
        min_qty = float(allowed.get("min_qty") or 0.0)
        min_notional = float(allowed.get("min_notional") or 0.0)
        if min_qty > 0 and qty < min_qty:
            raise HTTPException(status_code=409, detail=f"Ilość {qty} jest poniżej minQty {min_qty} dla {symbol}")
        if min_notional > 0 and market_price > 0 and qty * market_price < min_notional:
            raise HTTPException(
                status_code=409,
                detail=f"Wartość zlecenia {qty * market_price:.4f} jest poniżej minNotional {min_notional} dla {symbol}",
            )

        if order.side == "BUY":
            if str(plan.get("action") or "").upper() != "BUY":
                raise HTTPException(status_code=409, detail="Plan transakcji nie pozwala na BUY w obecnych warunkach")
            if float(plan.get("expected_net_profit") or 0.0) <= float(plan.get("expected_total_cost") or 0.0):
                raise HTTPException(status_code=409, detail="BUY zablokowany: oczekiwany zysk netto nie pokrywa kosztów")
        if order.side == "SELL":
            sell_guard = build_profitability_guard(
                entry_price=float((snapshot.get("position") or {}).get("entry_price") or market_price),
                quantity=qty,
                target_price=float(plan.get("take_profit_price") or market_price),
                stop_price=float(plan.get("stop_loss_price") or market_price),
                taker_fee_rate=float(snapshot.get("costs", {}).get("fee_rate") or 0.001),
                spread_bps=float((snapshot.get("market") or {}).get("spread_pct") or 0.03) * 100.0,
                slippage_bps=float(snapshot.get("costs", {}).get("slippage_rate") or 0.0005) * 10000.0,
            )
            sell_reason = str(plan.get("decision_reason") or plan.get("invalidation_reason") or "").lower()
            sell_ok = (
                str(plan.get("action") or "").upper() in {"SELL", "REDUCE"}
                and (
                    bool(sell_guard.get("eligible"))
                    or bool(revision and revision.get("requires_revision"))
                    or any(tag in sell_reason for tag in ("hard_stop_loss", "risk_exit", "plan_invalidated"))
                )
            )
            if not sell_ok:
                raise HTTPException(status_code=409, detail="SELL zablokowany: brak twardego powodu lub przewagi netto")

        # Złóż zlecenie na Binance
        result = binance.place_order(
            symbol=symbol,
            side=order.side,
            order_type="MARKET",
            quantity=qty,
        )

        if result is None:
            raise HTTPException(
                status_code=502,
                detail="Binance nie odpowiedział. Sprawdź klucze API i połączenie."
            )
        if result.get("_error"):
            raise HTTPException(
                status_code=400,
                detail=f"Binance odrzucił zlecenie: {result.get('error_message', 'nieznany błąd')} (kod: {result.get('error_code', '?')})"
            )

        binance_order_id = result.get("orderId")
        binance_status = result.get("status", "UNKNOWN")

        # Pobierz fills (cena wykonania)
        fills = result.get("fills") or []
        exec_qty = float(result.get("executedQty", qty) or qty)
        cum_quote = float(result.get("cummulativeQuoteQty", 0) or 0)
        executed_price = (cum_quote / exec_qty) if exec_qty > 0 else 0.0

        # Fallback — pobierz cenę z fills jeśli cummulativeQuoteQty = 0
        if executed_price == 0 and fills:
            total_cost = sum(float(f.get("price", 0)) * float(f.get("qty", 0)) for f in fills)
            total_qty = sum(float(f.get("qty", 0)) for f in fills)
            executed_price = total_cost / total_qty if total_qty > 0 else 0.0

        # Całkowita prowizja (w quote asset lub BNB)
        total_fee = sum(float(f.get("commission", 0)) for f in fills)
        fee_asset = fills[0].get("commissionAsset", "") if fills else ""

        # Zapis do DB
        new_order = Order(
            symbol=symbol,
            side=order.side,
            order_type="MARKET",
            price=None,
            quantity=exec_qty,
            status=binance_status,
            mode="live",
            executed_price=executed_price if executed_price > 0 else None,
            executed_quantity=exec_qty,
            timestamp=utc_now_naive(),
            exchange_order_id=str(binance_order_id or ""),
            notes=f"fee={total_fee} {fee_asset}",
            decision_plan_json=json.dumps(plan, ensure_ascii=False),
        )
        db.add(new_order)
        db.flush()

        # Jeśli BUY FILLED → utwórz/aktualizuj Position
        if order.side == "BUY" and binance_status in ("FILLED", "PARTIALLY_FILLED") and executed_price > 0:
            existing = (
                db.query(Position)
                .filter(Position.symbol == symbol, Position.mode == "live")
                .first()
            )
            if existing:
                # Uśrednij cenę wejścia
                old_cost = float(existing.entry_price or 0) * float(existing.quantity or 0)
                new_cost = executed_price * exec_qty
                total_qty = float(existing.quantity or 0) + exec_qty
                existing.entry_price = (old_cost + new_cost) / total_qty if total_qty > 0 else executed_price
                existing.quantity = total_qty
                existing.current_price = executed_price
                existing.unrealized_pnl = 0.0
                existing.decision_plan_json = json.dumps(plan, ensure_ascii=False)
                existing.plan_status = plan.get("plan_status")
                existing.requires_revision = bool(revision and revision.get("requires_revision"))
                existing.invalidation_reason = (revision or {}).get("reason") if revision else None
                existing.last_consulted_at = utc_now_naive()
            else:
                pos = Position(
                    symbol=symbol,
                    side="BUY",
                    entry_price=executed_price,
                    current_price=executed_price,
                    quantity=exec_qty,
                    unrealized_pnl=0.0,
                    mode="live",
                    opened_at=utc_now_naive(),
                    decision_plan_json=json.dumps(plan, ensure_ascii=False),
                    plan_status=plan.get("plan_status"),
                    requires_revision=bool(revision and revision.get("requires_revision")),
                    invalidation_reason=(revision or {}).get("reason") if revision else None,
                    last_consulted_at=utc_now_naive(),
                )
                db.add(pos)

        # Jeśli SELL FILLED → zmniejsz/usuń Position
        if order.side == "SELL" and binance_status in ("FILLED", "PARTIALLY_FILLED"):
            existing = (
                db.query(Position)
                .filter(Position.symbol == symbol, Position.mode == "live")
                .first()
            )
            if existing:
                remaining = float(existing.quantity or 0) - exec_qty
                if remaining <= 1e-8:
                    db.delete(existing)
                else:
                    existing.quantity = remaining
                    existing.decision_plan_json = json.dumps(plan, ensure_ascii=False)
                    existing.plan_status = plan.get("plan_status")
                    existing.requires_revision = bool(revision and revision.get("requires_revision"))
                    existing.invalidation_reason = (revision or {}).get("reason") if revision else None
                    existing.last_consulted_at = utc_now_naive()

        db.commit()
        db.refresh(new_order)

        return {
            "success": True,
            "message": (
                f"✓ Zlecenie LIVE {order.side} {exec_qty} {symbol} "
                f"@ {executed_price:.4f} EUR · prowizja {total_fee:.8f} {fee_asset}"
            ),
            "data": {
                "id": new_order.id,
                "binance_order_id": binance_order_id,
                "symbol": new_order.symbol,
                "side": new_order.side,
                "type": new_order.order_type,
                "quantity": exec_qty,
                "status": binance_status,
                "executed_price": executed_price,
                "executed_quantity": exec_qty,
                "fee": total_fee,
                "fee_asset": fee_asset,
                "timestamp": new_order.timestamp.isoformat(),
                "mode": "live",
                **_plan_payload(plan, new_order),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd tworzenia zlecenia: {str(e)}")


@router.get("/export.csv")
def export_orders_csv(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    days: int = Query(7, ge=1, le=90, description="Ile dni wstecz (max 90)"),
    db: Session = Depends(get_db)
):
    """
    Eksportuj zlecenia do CSV
    """
    try:
        # Pobierz zlecenia z ostatnich N dni
        since = utc_now_naive() - timedelta(days=days)
        
        orders = db.query(Order).filter(
            Order.mode == mode,
            Order.timestamp >= since
        ).order_by(desc(Order.timestamp)).all()

        # Utwórz CSV w pamięci
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            "ID",
            "Symbol",
            "Side",
            "Type",
            "Price",
            "Quantity",
            "Status",
            "Executed Price",
            "Executed Quantity",
            "Timestamp"
        ])
        
        # Dane
        for order in orders:
            writer.writerow([
                order.id,
                order.symbol,
                order.side,
                order.order_type,
                order.price or "",
                order.quantity,
                order.status,
                order.executed_price or "",
                order.executed_quantity or "",
                order.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            ])
        
        # Przygotuj odpowiedź
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=orders_{mode}_{utc_now_naive().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exporting CSV: {str(e)}")


@router.get("/stats")
def get_order_stats(
    mode: str = Query("demo", description="Tryb: demo lub live"),
    days: int = Query(7, ge=1, le=90, description="Period statystyk"),
    db: Session = Depends(get_db)
):
    """
    Statystyki zleceń
    """
    try:
        since = utc_now_naive() - timedelta(days=days)
        
        orders = db.query(Order).filter(
            Order.mode == mode,
            Order.timestamp >= since
        ).all()
        
        if not orders:
            return {
                "success": True,
                "mode": mode,
                "data": {
                    "total": 0,
                    "filled": 0,
                    "cancelled": 0,
                    "rejected": 0,
                    "buy_count": 0,
                    "sell_count": 0
                }
            }
        
        # Oblicz statystyki
        total = len(orders)
        filled = sum(1 for o in orders if o.status == "FILLED")
        cancelled = sum(1 for o in orders if o.status == "CANCELLED")
        rejected = sum(1 for o in orders if o.status == "REJECTED")
        buy_count = sum(1 for o in orders if o.side == "BUY")
        sell_count = sum(1 for o in orders if o.side == "SELL")
        
        return {
            "success": True,
            "mode": mode,
            "period_days": days,
            "data": {
                "total": total,
                "filled": filled,
                "cancelled": cancelled,
                "rejected": rejected,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "fill_rate": round((filled / total * 100) if total > 0 else 0, 2)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting stats: {str(e)}")
