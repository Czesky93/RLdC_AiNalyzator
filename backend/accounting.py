"""
DEMO accounting utilities (cash/equity/PnL) computed deterministically from DB.

Source of truth:
- Orders (mode=demo, status=FILLED)
- Latest MarketData prices (fallback: entry price)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import MarketData, Order


def get_demo_quote_ccy() -> str:
    """
    DEMO quote currency used for KPIs and trading.
    Priority:
      1) DEMO_QUOTE_CCY
      2) first entry in PORTFOLIO_QUOTES
      3) EUR
    """
    v = (os.getenv("DEMO_QUOTE_CCY", "") or "").strip().upper()
    if v:
        return v
    quotes = [q.strip().upper() for q in (os.getenv("PORTFOLIO_QUOTES", "") or "").split(",") if q.strip()]
    return quotes[0] if quotes else "EUR"


def _quotes_candidates() -> List[str]:
    env_quotes = [q.strip().upper() for q in (os.getenv("PORTFOLIO_QUOTES", "EUR,USDC") or "").split(",") if q.strip()]
    # add common quotes to avoid mis-detection when PORTFOLIO_QUOTES is narrow
    common = ["USDT", "USDC", "BUSD", "EUR", "USD", "BTC", "ETH"]
    merged = []
    for q in env_quotes + common:
        if q and q not in merged:
            merged.append(q)
    # longest first (USDC before USD, etc.)
    merged.sort(key=len, reverse=True)
    return merged


def symbol_quote(symbol: str, quotes: List[str]) -> Optional[str]:
    if not symbol:
        return None
    s = symbol.strip().upper().replace("/", "").replace("-", "")
    for q in quotes:
        if q and s.endswith(q):
            return q
    return None


def _get_latest_price(db: Session, symbol: str) -> Optional[float]:
    if not symbol:
        return None
    latest = (
        db.query(MarketData)
        .filter(MarketData.symbol == symbol)
        .order_by(desc(MarketData.timestamp))
        .first()
    )
    if not latest or latest.price is None:
        return None
    try:
        return float(latest.price)
    except Exception:
        return None


@dataclass
class _Holding:
    qty: float = 0.0
    avg_entry: float = 0.0


def compute_demo_account_state(
    db: Session,
    quote_ccy: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict:
    """
    Deterministic DEMO accounting.

    Notes:
    - No fees/slippage.
    - No shorts (SELL is clamped to current holdings).
    - Only considers symbols whose quote currency matches `quote_ccy`.
    """
    now = now or datetime.utcnow()
    quote_ccy = (quote_ccy or get_demo_quote_ccy()).strip().upper()
    initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)

    quotes = _quotes_candidates()

    cash = float(initial_balance)
    realized_pnl_total = 0.0
    realized_pnl_24h = 0.0
    warnings: List[str] = []

    holdings: Dict[str, _Holding] = {}
    day_ago = now - timedelta(hours=24)

    orders = (
        db.query(Order)
        .filter(Order.mode == "demo", Order.status == "FILLED")
        .order_by(Order.timestamp.asc(), Order.id.asc())
        .all()
    )

    for o in orders:
        sym = (o.symbol or "").strip().upper()
        if not sym:
            continue
        if symbol_quote(sym, quotes) != quote_ccy:
            continue

        qty = o.executed_quantity if o.executed_quantity is not None else o.quantity
        px = o.executed_price if o.executed_price is not None else o.price
        try:
            qty_f = float(qty or 0.0)
            px_f = float(px or 0.0)
        except Exception:
            continue
        if qty_f <= 0 or px_f <= 0:
            continue

        side = (o.side or "").strip().upper()
        h = holdings.get(sym) or _Holding()

        if side == "BUY":
            cash -= px_f * qty_f
            new_qty = h.qty + qty_f
            if new_qty > 0:
                h.avg_entry = ((h.avg_entry * h.qty) + (px_f * qty_f)) / new_qty
            h.qty = new_qty
            holdings[sym] = h
        elif side == "SELL":
            if h.qty <= 0:
                warnings.append(f"SELL bez pozycji: {sym} qty={qty_f}")
                continue
            sell_qty = min(qty_f, h.qty)
            if sell_qty < qty_f:
                warnings.append(f"SELL clamp: {sym} requested={qty_f} used={sell_qty}")

            cash += px_f * sell_qty
            realized = (px_f - h.avg_entry) * sell_qty
            realized_pnl_total += realized
            if o.timestamp and o.timestamp >= day_ago:
                realized_pnl_24h += realized

            h.qty -= sell_qty
            if h.qty <= 1e-12:
                holdings.pop(sym, None)
            else:
                holdings[sym] = h

    positions: List[Dict] = []
    positions_value = 0.0
    unrealized_pnl = 0.0
    for sym, h in holdings.items():
        current = _get_latest_price(db, sym)
        if current is None:
            current = h.avg_entry
        value = float(current) * float(h.qty)
        upnl = (float(current) - float(h.avg_entry)) * float(h.qty)
        positions_value += value
        unrealized_pnl += upnl
        positions.append(
            {
                "symbol": sym,
                "qty": float(h.qty),
                "avg_entry": float(h.avg_entry),
                "current_price": float(current),
                "value": float(value),
                "unrealized_pnl": float(upnl),
            }
        )

    equity = cash + positions_value
    roi = (equity - initial_balance) / initial_balance if initial_balance > 0 else 0.0

    return {
        "mode": "demo",
        "quote_ccy": quote_ccy,
        "initial_balance": float(initial_balance),
        "cash": float(cash),
        "positions_value": float(positions_value),
        "equity": float(equity),
        "unrealized_pnl": float(unrealized_pnl),
        "realized_pnl_total": float(realized_pnl_total),
        "realized_pnl_24h": float(realized_pnl_24h),
        "roi": float(roi),
        "positions": positions,
        "warnings": warnings,
        "timestamp": now.isoformat(),
    }

