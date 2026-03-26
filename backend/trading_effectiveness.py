"""
Trading Effectiveness Review — diagnostyka skuteczności tradingu.

Warstwa read-only, budowana na wierzchu accounting.py.
Odpowiada na kluczowe pytania:
  - Które symbole zarabiają netto?
  - Które reason_codes tracą?
  - Gdzie koszty zjadają edge?
  - Gdzie bot overtraduje?
  - Które filtry wejścia zaostrzyć / poluzować?
  - Które parametry mają największy wpływ na net expectancy?

NIE wykonuje żadnych akcji technicznych.
NIE zmienia configu, accounting, risk, reporting.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from backend.accounting import (
    _float,
    _round_metric,
    compute_order_cost_summary,
    compute_symbol_performance,
    compute_strategy_performance,
    blocked_decisions_summary,
    cost_breakdown_by_symbol,
    summarize_orders,
)
from backend.database import (
    CostLedger,
    DecisionTrace,
    Order,
    Position,
    Signal,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# I.  Główne podsumowanie skuteczności
# ---------------------------------------------------------------------------

def trading_effectiveness_summary(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Odpowiada na pytanie: czy bot generuje przewagę netto po kosztach?
    Zwraca zagregowane KPI i verdict.
    """
    orders = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED",
    ).all()
    sells = [o for o in orders if (o.side or "").upper() == "SELL"]
    buys = [o for o in orders if (o.side or "").upper() == "BUY"]

    # Metryki zagregowane
    total_gross = 0.0
    total_net = 0.0
    total_cost = 0.0
    total_fee = 0.0
    total_slippage = 0.0
    total_spread = 0.0
    wins_net = 0
    losses_net = 0
    gross_positive_net_negative = 0  # "cost-killed" trades

    for order in sells:
        s = compute_order_cost_summary(order, db=db)
        total_gross += s["gross_pnl"]
        total_net += s["net_pnl"]
        total_cost += s["total_cost"]
        total_fee += s["fee_cost"]
        total_slippage += s["slippage_cost"]
        total_spread += s["spread_cost"]
        if s["net_pnl"] > 0:
            wins_net += 1
        elif s["net_pnl"] < 0:
            losses_net += 1
        if s["gross_pnl"] > 0 and s["net_pnl"] < 0:
            gross_positive_net_negative += 1

    closed_count = len(sells)
    net_expectancy = total_net / closed_count if closed_count > 0 else 0.0
    win_rate = wins_net / closed_count if closed_count > 0 else 0.0
    cost_leakage = total_cost / abs(total_gross) if abs(total_gross) > 1e-12 else 0.0

    # Blocked decision count
    blocked = blocked_decisions_summary(db, mode=mode)
    blocked_total = sum(blocked.values())

    # Verdict
    if closed_count == 0:
        verdict = "brak_danych"
        verdict_reason = "Brak zamkniętych transakcji do analizy."
    elif net_expectancy > 0 and win_rate > 0.45:
        verdict = "zyskowny"
        verdict_reason = "Pozytywna expectancy netto i przyzwoity win rate."
    elif net_expectancy > 0:
        verdict = "marginalny"
        verdict_reason = "Expectancy dodatnia, ale niski win rate — duże ryzyko serii strat."
    elif total_gross > 0 and total_net <= 0:
        verdict = "koszty_zjadają_edge"
        verdict_reason = f"Strategia jest zyskowna brutto ({total_gross:.2f}), ale koszty ({total_cost:.2f}) pochłaniają przewagę."
    else:
        verdict = "niezyskowny"
        verdict_reason = "Negatywna expectancy netto — strategia traci pieniądze."

    return {
        "mode": mode,
        "closed_trades": closed_count,
        "open_positions": len(buys) - len(sells),
        "total_orders": len(orders),
        "gross_pnl": _round_metric(total_gross),
        "net_pnl": _round_metric(total_net),
        "total_cost": _round_metric(total_cost),
        "fee_cost": _round_metric(total_fee),
        "slippage_cost": _round_metric(total_slippage),
        "spread_cost": _round_metric(total_spread),
        "net_expectancy": _round_metric(net_expectancy),
        "win_rate_net": _round_metric(win_rate),
        "cost_leakage_ratio": _round_metric(cost_leakage),
        "cost_killed_trades": gross_positive_net_negative,
        "blocked_decisions_total": blocked_total,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
    }


# ---------------------------------------------------------------------------
# II.  Skuteczność per symbol
# ---------------------------------------------------------------------------

def symbol_effectiveness(db: Session, mode: str = "demo") -> List[Dict[str, Any]]:
    """
    Ranking symboli: które zarabiają netto, które przepalają kapitał na kosztach,
    które są overtradowane.
    """
    orders = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED",
    ).all()

    grouped: Dict[str, List[Order]] = defaultdict(list)
    for o in orders:
        sym = (o.symbol or "").upper()
        if sym:
            grouped[sym].append(o)

    # Activity per symbol (all-time)
    blocked_by_symbol = _blocked_by_symbol(db, mode)

    result = []
    for symbol, sym_orders in grouped.items():
        sells = [o for o in sym_orders if (o.side or "").upper() == "SELL"]
        summary = summarize_orders(sells, db=db, label=symbol)

        closed = int(summary.get("closed_orders", len(sells)))
        net_pnl = _float(summary.get("net_pnl", 0))
        gross_pnl = _float(summary.get("gross_pnl", 0))
        total_cost = _float(summary.get("total_cost", 0))
        net_expectancy = _float(summary.get("net_expectancy", 0))
        cost_leakage = _float(summary.get("cost_leakage_ratio", 0))

        # Cost-killed trades for this symbol
        cost_killed = 0
        for o in sells:
            s = compute_order_cost_summary(o, db=db)
            if s["gross_pnl"] > 0 and s["net_pnl"] < 0:
                cost_killed += 1

        # Overtrading score: wiele transakcji + ujemna expectancy = źle
        overtrading_score = 0.0
        if closed > 3 and net_expectancy < 0:
            overtrading_score = min(1.0, closed * abs(net_expectancy) / max(abs(total_cost), 1.0))

        blocked_count = blocked_by_symbol.get(symbol, 0)

        # Per-symbol verdict
        if closed == 0:
            s_verdict = "brak_danych"
        elif net_expectancy > 0 and cost_leakage < 0.5:
            s_verdict = "zyskowny"
        elif net_expectancy > 0:
            s_verdict = "zyskowny_ale_kosztowny"
        elif gross_pnl > 0 > net_pnl:
            s_verdict = "koszty_zjadają_edge"
        elif overtrading_score > 0.5:
            s_verdict = "overtrade"
        else:
            s_verdict = "niezyskowny"

        result.append({
            "symbol": symbol,
            "closed_trades": closed,
            "gross_pnl": _round_metric(gross_pnl),
            "net_pnl": _round_metric(net_pnl),
            "total_cost": _round_metric(total_cost),
            "net_expectancy": _round_metric(net_expectancy),
            "win_rate_net": _round_metric(_float(summary.get("win_rate_net", 0))),
            "cost_leakage_ratio": _round_metric(cost_leakage),
            "cost_killed_trades": cost_killed,
            "overtrading_score": _round_metric(overtrading_score),
            "blocked_decisions": blocked_count,
            "verdict": s_verdict,
        })

    result.sort(key=lambda x: x["net_pnl"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# III.  Skuteczność per reason_code (entry)
# ---------------------------------------------------------------------------

def reason_code_effectiveness(db: Session, mode: str = "demo") -> List[Dict[str, Any]]:
    """
    Które entry_reason_code generują profit, a które straty?
    Odpowiada na: „jakie wejścia wyglądają dobrze brutto, ale odpadają netto?"
    """
    orders = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED", Order.side == "SELL",
    ).all()

    # Mapuj order → entry_reason_code
    # Szukamy reason_code z powiązanych BUY orderów lub z DecisionTrace
    reason_map = _build_reason_map(db, mode)

    grouped: Dict[str, List[Order]] = defaultdict(list)
    for o in orders:
        reason = reason_map.get(int(o.id or 0), o.entry_reason_code or "unknown")
        grouped[reason].append(o)

    result = []
    for reason_code, reason_orders in grouped.items():
        summary = summarize_orders(reason_orders, db=db, label=reason_code)
        closed = int(summary.get("closed_orders", len(reason_orders)))
        gross_pnl = _float(summary.get("gross_pnl", 0))
        net_pnl = _float(summary.get("net_pnl", 0))

        # Gross-positive / net-negative count
        cost_killed = 0
        for o in reason_orders:
            s = compute_order_cost_summary(o, db=db)
            if s["gross_pnl"] > 0 and s["net_pnl"] < 0:
                cost_killed += 1

        if closed == 0:
            r_verdict = "brak_danych"
        elif _float(summary.get("net_expectancy", 0)) > 0:
            r_verdict = "zyskowny"
        elif gross_pnl > 0 > net_pnl:
            r_verdict = "koszty_zjadają_edge"
        else:
            r_verdict = "niezyskowny"

        result.append({
            "reason_code": reason_code,
            "closed_trades": closed,
            "gross_pnl": _round_metric(gross_pnl),
            "net_pnl": _round_metric(net_pnl),
            "total_cost": _round_metric(_float(summary.get("total_cost", 0))),
            "net_expectancy": _round_metric(_float(summary.get("net_expectancy", 0))),
            "win_rate_net": _round_metric(_float(summary.get("win_rate_net", 0))),
            "cost_leakage_ratio": _round_metric(_float(summary.get("cost_leakage_ratio", 0))),
            "cost_killed_trades": cost_killed,
            "verdict": r_verdict,
        })

    result.sort(key=lambda x: x["net_pnl"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# IV.  Skuteczność per strategia (rozszerzona)
# ---------------------------------------------------------------------------

def strategy_effectiveness(db: Session, mode: str = "demo") -> List[Dict[str, Any]]:
    """
    Głębsza diagnostyka per strategia: expectancy, edge gap, cost leakage,
    overtrading, blocked decisions, verdict.
    """
    # Strategia → orders (via DecisionTrace)
    traces = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()
    strategy_by_order: Dict[int, str] = {}
    blocked_by_strategy: Dict[str, int] = defaultdict(int)
    for t in traces:
        if t.order_id and t.strategy_name:
            strategy_by_order[int(t.order_id)] = t.strategy_name
        if t.strategy_name and (t.action_type or "").upper() in ("SKIP", "BLOCK", "REJECT"):
            blocked_by_strategy[t.strategy_name] += 1

    orders = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED", Order.side == "SELL",
    ).all()

    grouped: Dict[str, List[Order]] = defaultdict(list)
    for o in orders:
        strategy = strategy_by_order.get(int(o.id or 0), "unknown")
        grouped[strategy].append(o)

    result = []
    for strategy_name, strat_orders in grouped.items():
        summary = summarize_orders(strat_orders, db=db, label=strategy_name)
        closed = int(summary.get("closed_orders", len(strat_orders)))
        net_exp = _float(summary.get("net_expectancy", 0))
        gross_pnl = _float(summary.get("gross_pnl", 0))
        net_pnl = _float(summary.get("net_pnl", 0))

        # Expected edge vs realized
        realized_rr_avg = _float(summary.get("realized_rr_avg", 0))
        expected_edge_avg = _float(summary.get("expected_edge_avg", 0))
        edge_gap = realized_rr_avg - expected_edge_avg if expected_edge_avg > 0 else 0.0

        # Cost-killed
        cost_killed = sum(
            1 for o in strat_orders
            if compute_order_cost_summary(o, db=db)["gross_pnl"] > 0
            and compute_order_cost_summary(o, db=db)["net_pnl"] < 0
        )

        blocked = blocked_by_strategy.get(strategy_name, 0)

        if closed == 0:
            sv = "brak_danych"
        elif net_exp > 0 and _float(summary.get("cost_leakage_ratio", 0)) < 0.5:
            sv = "zyskowny"
        elif gross_pnl > 0 > net_pnl:
            sv = "koszty_zjadają_edge"
        else:
            sv = "niezyskowny" if net_exp <= 0 else "marginalny"

        result.append({
            "strategy_name": strategy_name,
            "closed_trades": closed,
            "gross_pnl": _round_metric(gross_pnl),
            "net_pnl": _round_metric(net_pnl),
            "total_cost": _round_metric(_float(summary.get("total_cost", 0))),
            "net_expectancy": _round_metric(net_exp),
            "win_rate_net": _round_metric(_float(summary.get("win_rate_net", 0))),
            "profit_factor_net": _round_metric(_float(summary.get("profit_factor_net", 0))),
            "cost_leakage_ratio": _round_metric(_float(summary.get("cost_leakage_ratio", 0))),
            "expected_edge_avg": _round_metric(expected_edge_avg),
            "realized_rr_avg": _round_metric(realized_rr_avg),
            "edge_gap": _round_metric(edge_gap),
            "cost_killed_trades": cost_killed,
            "blocked_decisions": blocked,
            "verdict": sv,
        })

    result.sort(key=lambda x: x["net_pnl"], reverse=True)
    return result


# ---------------------------------------------------------------------------
# V.  Cost leakage deep-dive
# ---------------------------------------------------------------------------

def cost_leakage_analysis(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Gdzie koszty (fee, spread, slippage) zjadają edge?
    Rankingi symboli i strategii wg utraty przewagi na kosztach.
    """
    sells = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED", Order.side == "SELL",
    ).all()

    if not sells:
        return {"mode": mode, "total_cost_killed_trades": 0, "worst_symbols": [], "worst_strategies": [], "cost_breakdown": {}}

    # Global cost-killed count
    cost_killed_total = 0
    cost_killed_pnl_lost = 0.0
    total_fee = 0.0
    total_slippage = 0.0
    total_spread = 0.0

    for o in sells:
        s = compute_order_cost_summary(o, db=db)
        total_fee += s["fee_cost"]
        total_slippage += s["slippage_cost"]
        total_spread += s["spread_cost"]
        if s["gross_pnl"] > 0 and s["net_pnl"] < 0:
            cost_killed_total += 1
            cost_killed_pnl_lost += s["gross_pnl"]

    # Worst symbols (by cost leakage)
    sym_perf = symbol_effectiveness(db, mode)
    worst_symbols = [
        s for s in sym_perf
        if s["cost_leakage_ratio"] > 0.3 and s["closed_trades"] > 0
    ]
    worst_symbols.sort(key=lambda x: x["cost_leakage_ratio"], reverse=True)

    # Worst strategies
    strat_perf = strategy_effectiveness(db, mode)
    worst_strategies = [
        s for s in strat_perf
        if s["cost_leakage_ratio"] > 0.3 and s["closed_trades"] > 0
    ]
    worst_strategies.sort(key=lambda x: x["cost_leakage_ratio"], reverse=True)

    # Dominant cost type
    costs = {"fee": total_fee, "slippage": total_slippage, "spread": total_spread}
    dominant_cost = max(costs, key=costs.get) if any(v > 0 for v in costs.values()) else "none"

    return {
        "mode": mode,
        "total_cost_killed_trades": cost_killed_total,
        "cost_killed_gross_pnl_lost": _round_metric(cost_killed_pnl_lost),
        "total_fee": _round_metric(total_fee),
        "total_slippage": _round_metric(total_slippage),
        "total_spread": _round_metric(total_spread),
        "dominant_cost_type": dominant_cost,
        "cost_breakdown": {k: _round_metric(v) for k, v in costs.items()},
        "worst_symbols": worst_symbols[:10],
        "worst_strategies": worst_strategies[:10],
    }


# ---------------------------------------------------------------------------
# VI.  Overtrading detection
# ---------------------------------------------------------------------------

def overtrading_analysis(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Wykrywanie symboli/strategii, gdzie aktywność jest wysoka,
    ale wynik netto jest negatywny — bot traci, bo za dużo handluje.
    """
    sym_data = symbol_effectiveness(db, mode)
    strat_data = strategy_effectiveness(db, mode)

    overtrade_symbols = [
        s for s in sym_data
        if s["overtrading_score"] > 0.3 and s["closed_trades"] >= 3
    ]
    overtrade_symbols.sort(key=lambda x: x["overtrading_score"], reverse=True)

    overtrade_strategies = []
    for s in strat_data:
        if s["closed_trades"] >= 3 and s["net_expectancy"] < 0:
            score = min(1.0, s["closed_trades"] * abs(s["net_expectancy"]) / max(abs(s["total_cost"]), 1.0))
            overtrade_strategies.append({**s, "overtrading_score": _round_metric(score)})
    overtrade_strategies.sort(key=lambda x: x["overtrading_score"], reverse=True)

    # Recommendations
    recommendations = []
    for s in overtrade_symbols[:5]:
        recommendations.append({
            "type": "symbol",
            "target": s["symbol"],
            "action": "zmniejsz_częstotliwość" if s["net_pnl"] < 0 else "monitoruj",
            "reason": f"Symbol {s['symbol']} ma overtrading score {s['overtrading_score']:.2f} "
                       f"przy {s['closed_trades']} transakcjach i net PnL {s['net_pnl']:.2f}.",
        })

    return {
        "mode": mode,
        "overtrade_symbols": overtrade_symbols,
        "overtrade_strategies": overtrade_strategies,
        "recommendations": recommendations,
    }


# ---------------------------------------------------------------------------
# VII.  Filter / gate effectiveness
# ---------------------------------------------------------------------------

def filter_effectiveness(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Które risk gates blokują najczęściej i czy słusznie?
    Analiza: ile razy gate zablokował vs. ogólny wynik netto.
    """
    blocked = blocked_decisions_summary(db, mode=mode)

    # DecisionTraces — executed vs blocked per gate
    traces = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()

    # Gate aktivations
    gate_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"blocked": 0, "executed": 0})
    for t in traces:
        action = (t.action_type or "").upper()
        rc = t.reason_code or "unknown"
        if "BLOCK" in action or "SKIP" in action or "REJECT" in action:
            gate_stats[rc]["blocked"] += 1
        elif "EXECUTE" in action:
            gate_stats[rc]["executed"] += 1

    # Build gate report
    gates = []
    for gate_name, counts in gate_stats.items():
        total = counts["blocked"] + counts["executed"]
        block_rate = counts["blocked"] / total if total > 0 else 0.0
        gates.append({
            "gate": gate_name,
            "blocked": counts["blocked"],
            "executed": counts["executed"],
            "total": total,
            "block_rate": _round_metric(block_rate),
        })
    gates.sort(key=lambda x: x["blocked"], reverse=True)

    # Suggestion: gates that block a lot but overall strategy still loses
    sym_perf = symbol_effectiveness(db, mode)
    losing_symbols = [s["symbol"] for s in sym_perf if s["net_pnl"] < 0]

    suggestions = []
    for g in gates:
        if g["blocked"] > 5 and g["block_rate"] > 0.5:
            suggestions.append({
                "gate": g["gate"],
                "suggestion": "zachowaj",
                "reason": f"Gate {g['gate']} blokuje {g['blocked']} decyzji — prawdopodobnie chroni kapitał.",
            })
        elif g["blocked"] > 0 and g["block_rate"] < 0.1:
            suggestions.append({
                "gate": g["gate"],
                "suggestion": "monitoruj",
                "reason": f"Gate {g['gate']} rzadko blokuje ({g['blocked']}/{g['total']}) — sprawdź czy progi są optymalne.",
            })

    return {
        "mode": mode,
        "gates": gates,
        "total_blocked": sum(g["blocked"] for g in gates),
        "total_executed": sum(g["executed"] for g in gates),
        "losing_symbols": losing_symbols,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# VIII.  Edge analysis — expected vs realized
# ---------------------------------------------------------------------------

def edge_analysis(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Porównanie oczekiwanej przewagi (expected_edge) z rzeczywistą (realized_rr).
    Odpowiedź na: „czy bot realizuje tyle, ile obiecuje sygnał?"
    """
    sells = db.query(Order).filter(
        Order.mode == mode, Order.status == "FILLED", Order.side == "SELL",
    ).all()

    edges = []
    for o in sells:
        s = compute_order_cost_summary(o, db=db)
        expected = s["expected_edge"]
        realized = s["realized_rr"]
        if expected > 0:
            edges.append({
                "order_id": int(o.id),
                "symbol": (o.symbol or "").upper(),
                "expected_edge": _round_metric(expected),
                "realized_rr": _round_metric(realized),
                "gap": _round_metric(realized - expected),
                "net_pnl": _round_metric(s["net_pnl"]),
                "cost": _round_metric(s["total_cost"]),
            })

    if not edges:
        return {
            "mode": mode,
            "trades_with_edge": 0,
            "avg_expected_edge": 0.0,
            "avg_realized_rr": 0.0,
            "avg_gap": 0.0,
            "edge_hit_rate": 0.0,
            "details": [],
        }

    avg_expected = sum(e["expected_edge"] for e in edges) / len(edges)
    avg_realized = sum(e["realized_rr"] for e in edges) / len(edges)
    avg_gap = avg_realized - avg_expected
    edge_hits = sum(1 for e in edges if e["realized_rr"] >= e["expected_edge"])
    edge_hit_rate = edge_hits / len(edges) if edges else 0.0

    return {
        "mode": mode,
        "trades_with_edge": len(edges),
        "avg_expected_edge": _round_metric(avg_expected),
        "avg_realized_rr": _round_metric(avg_realized),
        "avg_gap": _round_metric(avg_gap),
        "edge_hit_rate": _round_metric(edge_hit_rate),
        "worst_misses": sorted(edges, key=lambda e: e["gap"])[:10],
        "best_hits": sorted(edges, key=lambda e: e["gap"], reverse=True)[:10],
    }


# ---------------------------------------------------------------------------
# IX.  Improvement suggestions (read-only, data-driven)
# ---------------------------------------------------------------------------

def improvement_suggestions(db: Session, mode: str = "demo") -> List[Dict[str, Any]]:
    """
    Sugestie poprawy parametrów na podstawie danych.
    NIE wykonuje żadnych zmian — tylko wskazuje kierunek.
    """
    suggestions: List[Dict[str, Any]] = []

    # 1. Symbole do odfiltrowania
    sym = symbol_effectiveness(db, mode)
    for s in sym:
        if s["closed_trades"] >= 5 and s["net_expectancy"] < 0 and s["verdict"] == "niezyskowny":
            suggestions.append({
                "priority": "wysoki",
                "area": "symbol_filter",
                "target": s["symbol"],
                "action": "rozważ_wyłączenie",
                "reason": f"Symbol {s['symbol']} ma negatywną expectancy netto "
                          f"({s['net_expectancy']:.4f}) po {s['closed_trades']} transakcjach.",
                "metric": s["net_expectancy"],
            })
        elif s["verdict"] == "koszty_zjadają_edge" and s["closed_trades"] >= 3:
            suggestions.append({
                "priority": "średni",
                "area": "cost_optimization",
                "target": s["symbol"],
                "action": "ogranicz_frequency_lub_zwiększ_min_edge",
                "reason": f"Symbol {s['symbol']} jest zyskowny brutto, ale koszty zjadają "
                          f"edge (leakage {s['cost_leakage_ratio']:.1%}).",
                "metric": s["cost_leakage_ratio"],
            })

    # 2. Reason codes do odfiltrowania
    reasons = reason_code_effectiveness(db, mode)
    for r in reasons:
        if r["closed_trades"] >= 3 and r["net_expectancy"] < 0 and r["verdict"] == "niezyskowny":
            suggestions.append({
                "priority": "wysoki",
                "area": "entry_filter",
                "target": r["reason_code"],
                "action": "zaostrz_lub_wyłącz",
                "reason": f"Entry reason '{r['reason_code']}' traci netto "
                          f"({r['net_expectancy']:.4f}) po {r['closed_trades']} transakcjach.",
                "metric": r["net_expectancy"],
            })

    # 3. Strategy adjustments
    strats = strategy_effectiveness(db, mode)
    for s in strats:
        if s["closed_trades"] >= 5 and s["edge_gap"] < -0.5:
            suggestions.append({
                "priority": "średni",
                "area": "strategy_tuning",
                "target": s["strategy_name"],
                "action": "sprawdź_execution_quality",
                "reason": f"Strategia '{s['strategy_name']}' realizuje znacznie mniej niż obiecuje "
                          f"(edge gap: {s['edge_gap']:.2f}).",
                "metric": s["edge_gap"],
            })

    suggestions.sort(key=lambda x: {"wysoki": 0, "średni": 1, "niski": 2}.get(x["priority"], 3))
    return suggestions


# ---------------------------------------------------------------------------
# X.  Master effectiveness bundle
# ---------------------------------------------------------------------------

def effectiveness_bundle(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Pełny raport skuteczności tradingu w jednym wywołaniu.
    """
    return {
        "summary": trading_effectiveness_summary(db, mode),
        "by_symbol": symbol_effectiveness(db, mode),
        "by_reason_code": reason_code_effectiveness(db, mode),
        "by_strategy": strategy_effectiveness(db, mode),
        "cost_leakage": cost_leakage_analysis(db, mode),
        "overtrading": overtrading_analysis(db, mode),
        "filters": filter_effectiveness(db, mode),
        "edge": edge_analysis(db, mode),
        "suggestions": improvement_suggestions(db, mode),
    }


# ---------------------------------------------------------------------------
# Helpers (internals)
# ---------------------------------------------------------------------------

def _blocked_by_symbol(db: Session, mode: str) -> Dict[str, int]:
    """Policz blokady ryzyka per symbol."""
    traces = db.query(DecisionTrace).filter(DecisionTrace.mode == mode).all()
    counts: Dict[str, int] = defaultdict(int)
    for t in traces:
        action = (t.action_type or "").upper()
        if "BLOCK" in action or "SKIP" in action or "REJECT" in action:
            sym = (t.symbol or "").upper()
            if sym:
                counts[sym] += 1
    return dict(counts)


def _build_reason_map(db: Session, mode: str) -> Dict[int, str]:
    """
    Mapuj order_id → entry_reason_code.
    Najpierw z Order.entry_reason_code, potem z DecisionTrace.
    """
    # From DecisionTrace (primary source)
    traces = db.query(DecisionTrace).filter(
        DecisionTrace.mode == mode,
        DecisionTrace.order_id.isnot(None),
        DecisionTrace.reason_code.isnot(None),
    ).all()
    mapping: Dict[int, str] = {}
    for t in traces:
        if t.order_id:
            mapping[int(t.order_id)] = t.reason_code
    return mapping
