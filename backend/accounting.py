"""
Central accounting layer for net-PnL, cost-aware rollups, and risk/reporting inputs.

Definitions used across the system:
- gross_pnl: realized profit/loss before trading costs
- total_cost: sum of fee_cost + slippage_cost + spread_cost + other cost ledger items
- net_pnl: gross_pnl - total_cost
- cost_leakage_ratio: total_cost / abs(gross_pnl) when gross_pnl != 0 else 0
- net_expectancy: average net_pnl per closed order
- profit_factor_net: sum(net wins) / abs(sum(net losses))
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import os
from typing import Dict, Iterable, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database import CostLedger, DecisionTrace, MarketData, Order, Position, utc_now_naive


def get_demo_quote_ccy() -> str:
    v = (os.getenv("DEMO_QUOTE_CCY", "") or "").strip().upper()
    if v:
        return v
    quotes = [q.strip().upper() for q in (os.getenv("PORTFOLIO_QUOTES", "") or "").split(",") if q.strip()]
    return quotes[0] if quotes else "EUR"


def _quotes_candidates() -> List[str]:
    env_quotes = [q.strip().upper() for q in (os.getenv("PORTFOLIO_QUOTES", "EUR,USDC") or "").split(",") if q.strip()]
    common = ["USDT", "USDC", "BUSD", "EUR", "USD", "BTC", "ETH"]
    merged: List[str] = []
    for q in env_quotes + common:
        if q and q not in merged:
            merged.append(q)
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


def _float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _round_metric(value: float) -> float:
    if math.isfinite(value):
        return float(value)
    return 0.0


@dataclass
class _Holding:
    qty: float = 0.0
    avg_entry: float = 0.0
    total_cost: float = 0.0


def compute_order_cost_summary(order: Order, db: Session | None = None) -> Dict[str, float]:
    fee_cost = _float(order.fee_cost)
    slippage_cost = _float(order.slippage_cost)
    spread_cost = _float(order.spread_cost)
    total_cost = _float(order.total_cost)

    if db is not None and (total_cost <= 0.0 and order.id is not None):
        rows = db.query(CostLedger).filter(CostLedger.order_id == int(order.id)).all()
        if rows:
            fee_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type in {"maker_fee", "taker_fee"})
            slippage_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type == "slippage")
            spread_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type == "spread")
            total_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows)

    gross_pnl = _float(order.gross_pnl)
    net_pnl = _float(order.net_pnl, gross_pnl - total_cost)
    cost_leakage_ratio = (total_cost / abs(gross_pnl)) if abs(gross_pnl) > 1e-12 else 0.0

    return {
        "gross_pnl": _round_metric(gross_pnl),
        "net_pnl": _round_metric(net_pnl),
        "total_cost": _round_metric(total_cost),
        "fee_cost": _round_metric(fee_cost),
        "slippage_cost": _round_metric(slippage_cost),
        "spread_cost": _round_metric(spread_cost),
        "expected_edge": _round_metric(_float(order.expected_edge)),
        "realized_rr": _round_metric(_float(order.realized_rr)),
        "cost_leakage_ratio": _round_metric(cost_leakage_ratio),
    }


def validate_order_economics(order: Order, db: Session | None = None, tolerance: float = 1e-6) -> Dict[str, object]:
    summary = compute_order_cost_summary(order, db=db)
    gross_pnl = summary["gross_pnl"]
    total_cost = summary["total_cost"]
    expected_net = gross_pnl - total_cost
    net_pnl = summary["net_pnl"]
    is_consistent = abs(net_pnl - expected_net) <= tolerance
    return {
        "order_id": order.id,
        "is_consistent": is_consistent,
        "expected_net_pnl": _round_metric(expected_net),
        "stored_net_pnl": _round_metric(net_pnl),
        "difference": _round_metric(net_pnl - expected_net),
    }


def summarize_orders(
    orders: Iterable[Order],
    db: Session | None = None,
    *,
    label: str | None = None,
) -> Dict[str, object]:
    order_list = list(orders)
    gross_pnl = 0.0
    net_pnl = 0.0
    total_cost = 0.0
    fee_cost = 0.0
    slippage_cost = 0.0
    spread_cost = 0.0
    expected_edge_sum = 0.0
    net_wins = 0.0
    net_losses = 0.0
    win_count = 0
    loss_count = 0
    realized_rr_values: List[float] = []
    inconsistencies: List[Dict[str, object]] = []

    for order in order_list:
        summary = compute_order_cost_summary(order, db=db)
        gross_pnl += summary["gross_pnl"]
        net_pnl += summary["net_pnl"]
        total_cost += summary["total_cost"]
        fee_cost += summary["fee_cost"]
        slippage_cost += summary["slippage_cost"]
        spread_cost += summary["spread_cost"]
        expected_edge_sum += summary["expected_edge"]
        if summary["net_pnl"] > 0:
            win_count += 1
            net_wins += summary["net_pnl"]
        elif summary["net_pnl"] < 0:
            loss_count += 1
            net_losses += summary["net_pnl"]
        if summary["realized_rr"] > 0:
            realized_rr_values.append(summary["realized_rr"])
        validation = validate_order_economics(order, db=db)
        if not validation["is_consistent"]:
            inconsistencies.append(validation)

    closed_count = sum(1 for o in order_list if (o.side or "").upper() == "SELL")
    net_expectancy = (net_pnl / closed_count) if closed_count > 0 else 0.0
    profit_factor_net = (net_wins / abs(net_losses)) if abs(net_losses) > 1e-12 else (net_wins if net_wins > 0 else 0.0)
    cost_leakage_ratio = (total_cost / abs(gross_pnl)) if abs(gross_pnl) > 1e-12 else 0.0

    return {
        "label": label,
        "orders": len(order_list),
        "closed_orders": closed_count,
        "gross_pnl": _round_metric(gross_pnl),
        "net_pnl": _round_metric(net_pnl),
        "total_cost": _round_metric(total_cost),
        "fee_cost": _round_metric(fee_cost),
        "slippage_cost": _round_metric(slippage_cost),
        "spread_cost": _round_metric(spread_cost),
        "expected_edge_avg": _round_metric(expected_edge_sum / len(order_list)) if order_list else 0.0,
        "realized_rr_avg": _round_metric(sum(realized_rr_values) / len(realized_rr_values)) if realized_rr_values else 0.0,
        "cost_leakage_ratio": _round_metric(cost_leakage_ratio),
        "net_expectancy": _round_metric(net_expectancy),
        "profit_factor_net": _round_metric(profit_factor_net),
        "win_rate_net": _round_metric(win_count / closed_count) if closed_count > 0 else 0.0,
        "wins": win_count,
        "losses": loss_count,
        "inconsistencies": inconsistencies,
    }


def position_cost_summary(position: Position, db: Session | None = None) -> Dict[str, float]:
    gross_pnl = _float(position.gross_pnl)
    net_pnl = _float(position.net_pnl)
    total_cost = _float(position.total_cost)
    fee_cost = _float(position.fee_cost)
    slippage_cost = _float(position.slippage_cost)
    spread_cost = _float(position.spread_cost)

    if db is not None and position.id is not None and total_cost <= 0.0:
        rows = db.query(CostLedger).filter(CostLedger.position_id == int(position.id)).all()
        if rows:
            fee_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type in {"maker_fee", "taker_fee"})
            slippage_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type == "slippage")
            spread_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows if r.cost_type == "spread")
            total_cost = sum(_float(r.actual_value if r.actual_value is not None else r.expected_value) for r in rows)
            net_pnl = gross_pnl - total_cost

    cost_leakage_ratio = (total_cost / abs(gross_pnl)) if abs(gross_pnl) > 1e-12 else 0.0
    return {
        "gross_pnl": _round_metric(gross_pnl),
        "net_pnl": _round_metric(net_pnl),
        "total_cost": _round_metric(total_cost),
        "fee_cost": _round_metric(fee_cost),
        "slippage_cost": _round_metric(slippage_cost),
        "spread_cost": _round_metric(spread_cost),
        "expected_edge": _round_metric(_float(position.expected_edge)),
        "realized_rr": _round_metric(_float(position.realized_rr)),
        "cost_leakage_ratio": _round_metric(cost_leakage_ratio),
    }


def summarize_positions(positions: Iterable[Position], db: Session | None = None, *, label: str | None = None) -> Dict[str, object]:
    items = list(positions)
    gross_pnl = sum(position_cost_summary(p, db=db)["gross_pnl"] for p in items)
    net_pnl = sum(position_cost_summary(p, db=db)["net_pnl"] for p in items)
    total_cost = sum(position_cost_summary(p, db=db)["total_cost"] for p in items)
    fee_cost = sum(position_cost_summary(p, db=db)["fee_cost"] for p in items)
    slippage_cost = sum(position_cost_summary(p, db=db)["slippage_cost"] for p in items)
    spread_cost = sum(position_cost_summary(p, db=db)["spread_cost"] for p in items)
    exposure = sum(_float(p.current_price or p.entry_price) * _float(p.quantity) for p in items)
    return {
        "label": label,
        "positions": len(items),
        "gross_pnl": _round_metric(gross_pnl),
        "net_pnl": _round_metric(net_pnl),
        "total_cost": _round_metric(total_cost),
        "fee_cost": _round_metric(fee_cost),
        "slippage_cost": _round_metric(slippage_cost),
        "spread_cost": _round_metric(spread_cost),
        "exposure": _round_metric(exposure),
    }


def compute_daily_performance(db: Session, mode: str = "demo", now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or utc_now_naive()
    day_ago = now - timedelta(hours=24)
    orders = (
        db.query(Order)
        .filter(Order.mode == mode, Order.status == "FILLED", Order.timestamp >= day_ago)
        .order_by(Order.timestamp.asc(), Order.id.asc())
        .all()
    )
    summary = summarize_orders(orders, db=db, label="day")
    summary["start_at"] = day_ago.isoformat()
    summary["end_at"] = now.isoformat()
    return summary


def compute_activity_snapshot(db: Session, mode: str = "demo", now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or utc_now_naive()
    day_ago = now - timedelta(hours=24)
    hour_ago = now - timedelta(hours=1)
    orders = (
        db.query(Order)
        .filter(Order.mode == mode, Order.status == "FILLED", Order.timestamp >= day_ago)
        .all()
    )
    by_symbol_24h: Dict[str, int] = {}
    by_symbol_1h: Dict[str, int] = {}
    for order in orders:
        symbol = (order.symbol or "").upper()
        if not symbol:
            continue
        by_symbol_24h[symbol] = by_symbol_24h.get(symbol, 0) + 1
        if order.timestamp and order.timestamp >= hour_ago:
            by_symbol_1h[symbol] = by_symbol_1h.get(symbol, 0) + 1
    return {
        "timestamp": now.isoformat(),
        "trades_24h": len(orders),
        "trades_1h": sum(by_symbol_1h.values()),
        "by_symbol_24h": by_symbol_24h,
        "by_symbol_1h": by_symbol_1h,
    }


def compute_symbol_performance(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    grouped: Dict[str, List[Order]] = {}
    for order in orders:
        grouped.setdefault((order.symbol or "").upper(), []).append(order)
    result = []
    for symbol, items in grouped.items():
        if not symbol:
            continue
        summary = summarize_orders(items, db=db, label=symbol)
        summary["symbol"] = symbol
        result.append(summary)
    result.sort(key=lambda item: float(item.get("net_pnl") or 0.0), reverse=True)
    return result


def compute_strategy_performance(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    traces = (
        db.query(DecisionTrace)
        .filter(DecisionTrace.mode == mode)
        .all()
    )
    strategy_by_order: Dict[int, str] = {}
    for trace in traces:
        if trace.order_id and trace.strategy_name:
            strategy_by_order[int(trace.order_id)] = trace.strategy_name

    grouped: Dict[str, List[Order]] = {}
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    for order in orders:
        strategy = strategy_by_order.get(int(order.id or 0), "unknown")
        grouped.setdefault(strategy, []).append(order)

    result = []
    for strategy, items in grouped.items():
        summary = summarize_orders(items, db=db, label=strategy)
        summary["strategy_name"] = strategy
        result.append(summary)
    result.sort(key=lambda item: float(item.get("net_pnl") or 0.0), reverse=True)
    return result


def blocked_decisions_summary(db: Session, mode: str = "demo") -> Dict[str, int]:
    traces = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()
    blocked: Dict[str, int] = {}
    for trace in traces:
        action = (trace.action_type or "").upper()
        if "SKIP" in action or "BLOCK" in action or "REJECT" in action:
            blocked[trace.reason_code] = blocked.get(trace.reason_code, 0) + 1
    return dict(sorted(blocked.items(), key=lambda item: item[1], reverse=True))


def cost_breakdown_by_symbol(db: Session, mode: str = "demo") -> List[Dict[str, object]]:
    orders = db.query(Order).filter(Order.mode == mode, Order.status == "FILLED").all()
    grouped: Dict[str, List[Order]] = {}
    for order in orders:
        grouped.setdefault((order.symbol or "").upper(), []).append(order)
    result = []
    for symbol, items in grouped.items():
        summary = summarize_orders(items, db=db, label=symbol)
        result.append(
            {
                "symbol": symbol,
                "total_cost": summary["total_cost"],
                "fee_cost": summary["fee_cost"],
                "slippage_cost": summary["slippage_cost"],
                "spread_cost": summary["spread_cost"],
                "cost_leakage_ratio": summary["cost_leakage_ratio"],
            }
        )
    result.sort(key=lambda item: float(item["total_cost"]), reverse=True)
    return result


def compute_risk_snapshot(db: Session, mode: str = "demo", now: Optional[datetime] = None) -> Dict[str, object]:
    now = now or utc_now_naive()
    day_perf = compute_daily_performance(db, mode=mode, now=now)
    positions = db.query(Position).filter(Position.mode == mode).all()
    exposure_per_symbol = {
        (p.symbol or "").upper(): _round_metric(_float(p.current_price or p.entry_price) * _float(p.quantity))
        for p in positions
        if p.symbol
    }
    total_exposure = sum(exposure_per_symbol.values())

    closed_orders = (
        db.query(Order)
        .filter(Order.mode == mode, Order.status == "FILLED", Order.side == "SELL")
        .order_by(desc(Order.timestamp), desc(Order.id))
        .all()
    )
    loss_streak = 0
    for order in closed_orders:
        summary = compute_order_cost_summary(order, db=db)
        if summary["net_pnl"] < 0:
            loss_streak += 1
        else:
            break

    daily_net_pnl = _float(day_perf["net_pnl"])
    # Dolicz unrealized PnL z otwartych pozycji (mark-to-market)
    unrealized_pnl = 0.0
    for p in positions:
        entry = _float(p.entry_price)
        qty = _float(p.quantity)
        if entry > 0 and qty > 0:
            current = _get_latest_price(db, (p.symbol or "").upper()) or _float(p.current_price) or entry
            unrealized_pnl += (current - entry) * qty
    daily_total_pnl = daily_net_pnl + unrealized_pnl
    if mode == "demo":
        initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
    else:
        # Dla LIVE używamy total_exposure jako proxy bazowego kapitału
        initial_balance = max(1.0, total_exposure)
    daily_net_drawdown = min(0.0, daily_total_pnl)
    kill_switch_triggered = daily_net_drawdown <= -(initial_balance * 0.03) if initial_balance > 0 else False

    return {
        "mode": mode,
        "timestamp": now.isoformat(),
        "daily_net_pnl": _round_metric(daily_net_pnl),
        "unrealized_pnl": _round_metric(unrealized_pnl),
        "daily_total_pnl": _round_metric(daily_total_pnl),
        "daily_net_drawdown": _round_metric(daily_net_drawdown),
        "loss_streak_net": loss_streak,
        "open_positions_count": len(positions),
        "total_exposure": _round_metric(total_exposure),
        "exposure_per_symbol": exposure_per_symbol,
        "kill_switch_triggered": kill_switch_triggered,
    }


def compute_demo_account_state(
    db: Session,
    quote_ccy: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict:
    now = now or utc_now_naive()
    quote_ccy = (quote_ccy or get_demo_quote_ccy()).strip().upper()
    # Czytaj initial_balance z RuntimeSetting (override po resecie demo)
    # lub fallback do ENV DEMO_INITIAL_BALANCE
    from backend.database import RuntimeSetting
    _ib_row = db.query(RuntimeSetting).filter(RuntimeSetting.key == "demo_initial_balance").first()
    if _ib_row and _ib_row.value:
        try:
            initial_balance = float(_ib_row.value)
        except (ValueError, TypeError):
            initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
    else:
        initial_balance = float(os.getenv("DEMO_INITIAL_BALANCE", "10000") or 10000)
    quotes = _quotes_candidates()

    cash = float(initial_balance)
    warnings: List[str] = []
    holdings: Dict[str, _Holding] = {}
    day_ago = now - timedelta(hours=24)

    orders = (
        db.query(Order)
        .filter(Order.mode == "demo", Order.status == "FILLED")
        .order_by(Order.timestamp.asc(), Order.id.asc())
        .all()
    )
    closed_orders_for_quote: List[Order] = []

    for order in orders:
        sym = (order.symbol or "").strip().upper()
        if not sym or symbol_quote(sym, quotes) != quote_ccy:
            continue

        qty_f = _float(order.executed_quantity if order.executed_quantity is not None else order.quantity)
        px_f = _float(order.executed_price if order.executed_price is not None else order.price)
        if qty_f <= 0 or px_f <= 0:
            continue

        side = (order.side or "").strip().upper()
        holding = holdings.get(sym) or _Holding()
        costs = compute_order_cost_summary(order, db=db)

        if side == "BUY":
            cash -= (px_f * qty_f) + costs["total_cost"]
            new_qty = holding.qty + qty_f
            if new_qty > 0:
                holding.avg_entry = ((holding.avg_entry * holding.qty) + (px_f * qty_f)) / new_qty
            holding.qty = new_qty
            holding.total_cost += costs["total_cost"]
            holdings[sym] = holding
        elif side == "SELL":
            if holding.qty <= 0:
                warnings.append(f"SELL bez pozycji: {sym} qty={qty_f}")
                continue
            sell_qty = min(qty_f, holding.qty)
            if sell_qty < qty_f:
                warnings.append(f"SELL clamp: {sym} requested={qty_f} used={sell_qty}")

            cash += (px_f * sell_qty) - costs["total_cost"]
            holding.qty -= sell_qty
            if holding.qty <= 1e-12:
                holdings.pop(sym, None)
            else:
                holdings[sym] = holding
            closed_orders_for_quote.append(order)

    realized_summary = summarize_orders(closed_orders_for_quote, db=db, label="demo_quote_closed")
    realized_pnl_total = _float(realized_summary["net_pnl"])
    realized_gross_pnl_total = _float(realized_summary["gross_pnl"])
    total_cost = _float(realized_summary["total_cost"])

    realized_pnl_24h = 0.0
    for order in closed_orders_for_quote:
        if order.timestamp and order.timestamp >= day_ago:
            realized_pnl_24h += compute_order_cost_summary(order, db=db)["net_pnl"]

    positions: List[Dict[str, object]] = []
    positions_value = 0.0
    unrealized_pnl = 0.0
    exposure = 0.0
    for sym, holding in holdings.items():
        current = _get_latest_price(db, sym) or holding.avg_entry
        value = float(current) * float(holding.qty)
        upnl = (float(current) - float(holding.avg_entry)) * float(holding.qty)
        positions_value += value
        unrealized_pnl += upnl
        exposure += value
        positions.append(
            {
                "symbol": sym,
                "qty": float(holding.qty),
                "avg_entry": float(holding.avg_entry),
                "current_price": float(current),
                "value": float(value),
                "unrealized_pnl": float(upnl),
            }
        )

    equity = cash + positions_value
    roi = (equity - initial_balance) / initial_balance if initial_balance > 0 else 0.0
    symbol_perf = compute_symbol_performance(db, mode="demo")
    blocked_summary = blocked_decisions_summary(db, mode="demo")
    risk_snapshot = compute_risk_snapshot(db, mode="demo", now=now)

    return {
        "mode": "demo",
        "quote_ccy": quote_ccy,
        "initial_balance": float(initial_balance),
        "cash": float(cash),
        "positions_value": float(positions_value),
        "equity": float(equity),
        "exposure": float(exposure),
        "unrealized_pnl": float(unrealized_pnl),
        "realized_pnl_total": float(realized_pnl_total),
        "realized_pnl_24h": float(realized_pnl_24h),
        "realized_gross_pnl_total": float(realized_gross_pnl_total),
        "total_cost": float(total_cost),
        "fee_cost": float(realized_summary["fee_cost"]),
        "slippage_cost": float(realized_summary["slippage_cost"]),
        "spread_cost": float(realized_summary["spread_cost"]),
        "cost_leakage_ratio": float(realized_summary["cost_leakage_ratio"]),
        "net_expectancy": float(realized_summary["net_expectancy"]),
        "profit_factor_net": float(realized_summary["profit_factor_net"]),
        "win_rate_net": float(realized_summary["win_rate_net"]),
        "blocked_decisions": blocked_summary,
        "symbol_performance": symbol_perf,
        "risk_snapshot": risk_snapshot,
        "roi": float(roi),
        "positions": positions,
        "warnings": warnings + [f"order_economics_inconsistencies={len(realized_summary['inconsistencies'])}"],
        "timestamp": now.isoformat(),
    }
