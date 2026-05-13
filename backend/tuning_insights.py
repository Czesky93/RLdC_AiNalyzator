"""
Tuning Insights — kandydaci zmian parametrów na podstawie diagnostyki tradingu.

Pomost: trading_effectiveness → konkretne propozycje zmian konfiguracji.

NIE wdraża zmian automatycznie.
NIE tworzy ConfigSnapshot / Recommendation / Experiment.
NIE modyfikuje runtime_settings, accounting, risk, reporting.

Tylko: czyta diagnostykę, mapuje ją na konkretne klucze konfiguracyjne
i zwraca listę kandydatów z uzasadnieniem i metrykami.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.accounting import _float, _round_metric
from backend.trading_effectiveness import (
    symbol_effectiveness,
    reason_code_effectiveness,
    strategy_effectiveness,
    cost_leakage_analysis,
    overtrading_analysis,
    edge_analysis,
    filter_effectiveness,
    trading_effectiveness_summary,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progi kwalifikacji (ile danych potrzeba, żeby sugestia była wiarygodna)
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_SYMBOL = 5       # min transakcji, żeby wyrokować o symbolu
MIN_TRADES_FOR_REASON = 3       # min transakcji per reason code
MIN_TRADES_FOR_STRATEGY = 5     # min transakcji per strategia
COST_LEAKAGE_HIGH = 0.50        # ratio powyzej którego koszty są problemem
COST_LEAKAGE_WARNING = 0.30     # próg ostrzeżenia
OVERTRADING_THRESHOLD = 0.40    # score powyżej = overtrading
EDGE_GAP_THRESHOLD = -0.5       # realizacja dużo gorsza od oczekiwanej


# ---------------------------------------------------------------------------
# I.  Kandydaci: symbole do wyłączenia / ograniczenia
# ---------------------------------------------------------------------------

def _symbol_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Symbole z trwałe ujemną expectancją lub zjadanym edge."""
    sym = symbol_effectiveness(db, mode)
    candidates = []

    for s in sym:
        trades = s["closed_trades"]
        if trades < MIN_TRADES_FOR_SYMBOL:
            continue

        if s["verdict"] == "niezyskowny" and s["net_expectancy"] < 0:
            candidates.append({
                "id": f"symbol_remove_{s['symbol']}",
                "category": "symbol_filter",
                "priority": "wysoki",
                "action": "usuń_z_watchlist",
                "setting_key": "watchlist",
                "target": s["symbol"],
                "current_impact": {
                    "net_expectancy": s["net_expectancy"],
                    "net_pnl": s["net_pnl"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Symbol {s['symbol']} ma trwale negatywną expectancy netto "
                    f"({s['net_expectancy']:.4f}) po {trades} transakcjach. "
                    f"Łączna strata netto: {s['net_pnl']:.2f}."
                ),
                "confidence": _confidence(trades, abs(s["net_expectancy"])),
            })
        elif s["verdict"] == "koszty_zjadają_edge":
            candidates.append({
                "id": f"symbol_min_edge_{s['symbol']}",
                "category": "cost_optimization",
                "priority": "średni",
                "action": "podnieś_min_edge_multiplier",
                "setting_key": "min_edge_multiplier",
                "target": s["symbol"],
                "current_impact": {
                    "cost_leakage_ratio": s["cost_leakage_ratio"],
                    "gross_pnl": s["gross_pnl"],
                    "net_pnl": s["net_pnl"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Symbol {s['symbol']} jest zyskowny brutto ({s['gross_pnl']:.2f}), "
                    f"ale koszty zjadają edge (leakage {s['cost_leakage_ratio']:.0%}). "
                    f"Podnieś min_edge_multiplier, żeby odciąć wejścia z za małym marginesem."
                ),
                "confidence": _confidence(trades, s["cost_leakage_ratio"]),
            })
        elif s["verdict"] == "overtrade":
            candidates.append({
                "id": f"symbol_freq_{s['symbol']}",
                "category": "activity_limit",
                "priority": "średni",
                "action": "ogranicz_max_trades_per_hour_per_symbol",
                "setting_key": "max_trades_per_hour_per_symbol",
                "target": s["symbol"],
                "current_impact": {
                    "overtrading_score": s["overtrading_score"],
                    "net_expectancy": s["net_expectancy"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Symbol {s['symbol']} ma overtrading score {s['overtrading_score']:.2f} "
                    f"przy ujemnej expectancy ({s['net_expectancy']:.4f}). "
                    f"Ogranicz częstotliwość transakcji."
                ),
                "confidence": _confidence(trades, s["overtrading_score"]),
            })

    return candidates


# ---------------------------------------------------------------------------
# II.  Kandydaci: reason codes do zaostrzenia / wyłączenia
# ---------------------------------------------------------------------------

def _reason_code_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Entry reason codes z ujemną expectancją."""
    reasons = reason_code_effectiveness(db, mode)
    candidates = []

    for r in reasons:
        trades = r["closed_trades"]
        if trades < MIN_TRADES_FOR_REASON:
            continue

        if r["verdict"] == "niezyskowny" and r["net_expectancy"] < 0:
            candidates.append({
                "id": f"reason_tighten_{r['reason_code']}",
                "category": "entry_filter",
                "priority": "wysoki",
                "action": "zaostrz_lub_wyłącz_reason_code",
                "setting_key": None,  # reason codes nie mają pokrętła — to sygnał do analizy
                "target": r["reason_code"],
                "current_impact": {
                    "net_expectancy": r["net_expectancy"],
                    "net_pnl": r["net_pnl"],
                    "win_rate_net": r["win_rate_net"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Entry reason '{r['reason_code']}' traci netto "
                    f"({r['net_expectancy']:.4f}) po {trades} transakcjach. "
                    f"Win rate: {r['win_rate_net']:.0%}. Rozważ zaostrzenie warunków wejścia."
                ),
                "confidence": _confidence(trades, abs(r["net_expectancy"])),
            })
        elif r["verdict"] == "koszty_zjadają_edge":
            candidates.append({
                "id": f"reason_edge_{r['reason_code']}",
                "category": "cost_optimization",
                "priority": "średni",
                "action": "podnieś_min_edge_dla_reason_code",
                "setting_key": "min_edge_multiplier",
                "target": r["reason_code"],
                "current_impact": {
                    "cost_leakage_ratio": r["cost_leakage_ratio"],
                    "gross_pnl": r["gross_pnl"],
                    "net_pnl": r["net_pnl"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Entry '{r['reason_code']}' jest zyskowny brutto, "
                    f"ale koszty zjadają edge (leakage {r['cost_leakage_ratio']:.0%}). "
                    f"Podnieś min_edge_multiplier, żeby filtrować słabe wejścia."
                ),
                "confidence": _confidence(trades, r["cost_leakage_ratio"]),
            })

    return candidates


# ---------------------------------------------------------------------------
# III.  Kandydaci: strategie do ograniczenia / rewizji
# ---------------------------------------------------------------------------

def _strategy_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Strategie z ujemną expectancją, złym edge gap lub overtradingiem."""
    strats = strategy_effectiveness(db, mode)
    candidates = []

    for s in strats:
        trades = s["closed_trades"]
        if trades < MIN_TRADES_FOR_STRATEGY:
            continue

        if s["net_expectancy"] < 0 and s["verdict"] == "niezyskowny":
            candidates.append({
                "id": f"strategy_disable_{s['strategy_name']}",
                "category": "strategy_filter",
                "priority": "wysoki",
                "action": "usuń_z_enabled_strategies",
                "setting_key": "enabled_strategies",
                "target": s["strategy_name"],
                "current_impact": {
                    "net_expectancy": s["net_expectancy"],
                    "net_pnl": s["net_pnl"],
                    "profit_factor_net": s["profit_factor_net"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Strategia '{s['strategy_name']}' ma negatywną expectancy netto "
                    f"({s['net_expectancy']:.4f}) i profit factor {s['profit_factor_net']:.2f} "
                    f"po {trades} transakcjach."
                ),
                "confidence": _confidence(trades, abs(s["net_expectancy"])),
            })
        elif s["edge_gap"] < EDGE_GAP_THRESHOLD and s["expected_edge_avg"] > 0:
            candidates.append({
                "id": f"strategy_edge_{s['strategy_name']}",
                "category": "execution_quality",
                "priority": "średni",
                "action": "sprawdź_execution_quality_i_min_expected_rr",
                "setting_key": "min_expected_rr",
                "target": s["strategy_name"],
                "current_impact": {
                    "expected_edge_avg": s["expected_edge_avg"],
                    "realized_rr_avg": s["realized_rr_avg"],
                    "edge_gap": s["edge_gap"],
                    "closed_trades": trades,
                },
                "reason": (
                    f"Strategia '{s['strategy_name']}' realizuje znacznie mniej niż obiecuje. "
                    f"Expected edge avg: {s['expected_edge_avg']:.2f}, realized: {s['realized_rr_avg']:.2f}, "
                    f"gap: {s['edge_gap']:.2f}. Sprawdź jakość execution i podnieś min_expected_rr."
                ),
                "confidence": _confidence(trades, abs(s["edge_gap"])),
            })

    return candidates


# ---------------------------------------------------------------------------
# IV.  Kandydaci: globalne pokrętła kosztowe
# ---------------------------------------------------------------------------

def _cost_tuning_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Globalne sugestie kosztowe na bazie cost leakage analysis."""
    leakage = cost_leakage_analysis(db, mode)
    candidates = []

    if leakage["total_cost_killed_trades"] > 0:
        lost = leakage.get("cost_killed_gross_pnl_lost", 0)
        candidates.append({
            "id": "global_cost_killed",
            "category": "cost_optimization",
            "priority": "wysoki" if leakage["total_cost_killed_trades"] >= 3 else "średni",
            "action": "podnieś_min_edge_multiplier_globalnie",
            "setting_key": "min_edge_multiplier",
            "target": "global",
            "current_impact": {
                "cost_killed_trades": leakage["total_cost_killed_trades"],
                "gross_pnl_lost": lost,
                "dominant_cost_type": leakage["dominant_cost_type"],
            },
            "reason": (
                f"{leakage['total_cost_killed_trades']} transakcji było zyskownych brutto, "
                f"ale koszty zabrały cały zysk (utracone brutto: {lost:.2f}). "
                f"Dominujący koszt: {leakage['dominant_cost_type']}. "
                f"Podnieś min_edge_multiplier, żeby odciąć wejścia z za małym marginesem."
            ),
            "confidence": min(1.0, leakage["total_cost_killed_trades"] / 10),
        })

    dom = leakage.get("dominant_cost_type", "none")
    if dom == "slippage" and leakage.get("total_slippage", 0) > 0:
        candidates.append({
            "id": "global_slippage",
            "category": "cost_optimization",
            "priority": "średni",
            "action": "zwiększ_slippage_bps_buffer",
            "setting_key": "slippage_bps",
            "target": "global",
            "current_impact": {
                "total_slippage": leakage["total_slippage"],
                "cost_breakdown": leakage["cost_breakdown"],
            },
            "reason": (
                f"Slippage jest dominującym kosztem ({leakage['total_slippage']:.2f}). "
                f"Rozważ zwiększenie slippage_bps, żeby model kosztowy lepiej odzwierciedlał "
                f"rzeczywiste poślizgi i filtrował wejścia z za cienkim edge."
            ),
            "confidence": 0.6,
        })
    elif dom == "spread" and leakage.get("total_spread", 0) > 0:
        candidates.append({
            "id": "global_spread",
            "category": "cost_optimization",
            "priority": "średni",
            "action": "zwiększ_spread_buffer_bps",
            "setting_key": "spread_buffer_bps",
            "target": "global",
            "current_impact": {
                "total_spread": leakage["total_spread"],
                "cost_breakdown": leakage["cost_breakdown"],
            },
            "reason": (
                f"Spread jest dominującym kosztem ({leakage['total_spread']:.2f}). "
                f"Rozważ zwiększenie spread_buffer_bps, żeby odfiltrować "
                f"wejścia na symbolach z szerokim spreadem."
            ),
            "confidence": 0.6,
        })

    return candidates


# ---------------------------------------------------------------------------
# V.  Kandydaci: ograniczenie aktywności (overtrading)
# ---------------------------------------------------------------------------

def _activity_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Sugestie ograniczenia aktywności przy ujemnych wynikach."""
    ot = overtrading_analysis(db, mode)
    candidates = []

    for s in ot.get("overtrade_symbols", []):
        if s["overtrading_score"] >= OVERTRADING_THRESHOLD:
            candidates.append({
                "id": f"activity_symbol_{s['symbol']}",
                "category": "activity_limit",
                "priority": "średni",
                "action": "zmniejsz_max_trades_per_hour_per_symbol",
                "setting_key": "max_trades_per_hour_per_symbol",
                "target": s["symbol"],
                "current_impact": {
                    "overtrading_score": s["overtrading_score"],
                    "net_expectancy": s["net_expectancy"],
                    "closed_trades": s["closed_trades"],
                },
                "reason": (
                    f"Symbol {s['symbol']} jest overtradowany "
                    f"(score {s['overtrading_score']:.2f}, expectancy {s['net_expectancy']:.4f}). "
                    f"Zmniejsz max_trades_per_hour_per_symbol."
                ),
                "confidence": _confidence(s["closed_trades"], s["overtrading_score"]),
            })

    summary = trading_effectiveness_summary(db, mode)
    if summary["verdict"] == "niezyskowny" and summary["closed_trades"] > 10:
        candidates.append({
            "id": "activity_global_reduce",
            "category": "activity_limit",
            "priority": "wysoki",
            "action": "zmniejsz_max_trades_per_day",
            "setting_key": "max_trades_per_day",
            "target": "global",
            "current_impact": {
                "net_expectancy": summary["net_expectancy"],
                "closed_trades": summary["closed_trades"],
                "verdict": summary["verdict"],
            },
            "reason": (
                f"Bot ma globalnie negatywną expectancy ({summary['net_expectancy']:.4f}) "
                f"po {summary['closed_trades']} transakcjach. "
                f"Zmniejsz max_trades_per_day, żeby ograniczyć straty."
            ),
            "confidence": min(1.0, summary["closed_trades"] / 20),
        })

    return candidates


# ---------------------------------------------------------------------------
# VI.  Kandydaci: korekta progów risk gate
# ---------------------------------------------------------------------------

def _risk_gate_candidates(db: Session, mode: str) -> List[Dict[str, Any]]:
    """Sugestie dotyczące progów risk gates na bazie ich efektywności."""
    filt = filter_effectiveness(db, mode)
    candidates = []

    for g in filt.get("gates", []):
        # Gate który dużo blokuje i jest jedyną obroną
        if g["blocked"] > 10 and g["block_rate"] > 0.7:
            candidates.append({
                "id": f"gate_keep_{g['gate']}",
                "category": "risk_discipline",
                "priority": "informacyjny",
                "action": "zachowaj_obecny_próg",
                "setting_key": _gate_to_setting(g["gate"]),
                "target": g["gate"],
                "current_impact": {
                    "blocked": g["blocked"],
                    "block_rate": g["block_rate"],
                    "total": g["total"],
                },
                "reason": (
                    f"Gate '{g['gate']}' blokuje {g['blocked']}/{g['total']} decyzji "
                    f"({g['block_rate']:.0%}). Prawdopodobnie chroni kapitał — nie poluzowuj."
                ),
                "confidence": 0.8,
            })
        # Gate który nigdy nie blokuje — może za łagodny
        elif g["total"] > 10 and g["blocked"] == 0:
            candidates.append({
                "id": f"gate_tighten_{g['gate']}",
                "category": "risk_discipline",
                "priority": "niski",
                "action": "rozważ_zaostrzenie",
                "setting_key": _gate_to_setting(g["gate"]),
                "target": g["gate"],
                "current_impact": {
                    "blocked": 0,
                    "total": g["total"],
                },
                "reason": (
                    f"Gate '{g['gate']}' nie zablokował żadnej z {g['total']} decyzji. "
                    f"Sprawdź czy progi nie są zbyt łagodne."
                ),
                "confidence": 0.4,
            })

    return candidates


# ---------------------------------------------------------------------------
# VII.  Agregacja: pełna lista kandydatów zmian
# ---------------------------------------------------------------------------

def generate_tuning_candidates(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Pełna lista kandydatów zmian konfiguracji na bazie diagnostyki tradingu.

    Każdy kandydat ma:
    - id: unikalny identyfikator
    - category: symbol_filter / entry_filter / strategy_filter /
                cost_optimization / activity_limit / execution_quality / risk_discipline
    - priority: wysoki / średni / niski / informacyjny
    - action: co należy rozważyć
    - setting_key: klucz w runtime_settings (lub None jeśli nie dotyczy pokrętła)
    - target: co konkretnie zmienić (symbol / reason code / strategy / global)
    - current_impact: metryki uzasadniające sugestię
    - reason: czytelne uzasadnienie po polsku
    - confidence: 0.0-1.0 — jak pewna jest sugestia (zależy od ilości danych)
    """
    all_candidates: List[Dict[str, Any]] = []
    all_candidates.extend(_symbol_candidates(db, mode))
    all_candidates.extend(_reason_code_candidates(db, mode))
    all_candidates.extend(_strategy_candidates(db, mode))
    all_candidates.extend(_cost_tuning_candidates(db, mode))
    all_candidates.extend(_activity_candidates(db, mode))
    all_candidates.extend(_risk_gate_candidates(db, mode))

    # Deduplikacja po id
    seen = set()
    unique = []
    for c in all_candidates:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)

    # Sortuj: wysoki → średni → niski → informacyjny, potem confidence desc
    priority_order = {"wysoki": 0, "średni": 1, "niski": 2, "informacyjny": 3}
    unique.sort(key=lambda c: (priority_order.get(c["priority"], 4), -c["confidence"]))

    # Podsumowanie
    by_priority = {}
    for c in unique:
        by_priority[c["priority"]] = by_priority.get(c["priority"], 0) + 1

    by_category = {}
    for c in unique:
        by_category[c["category"]] = by_category.get(c["category"], 0) + 1

    # Settings keys affected
    affected_keys = sorted({c["setting_key"] for c in unique if c["setting_key"]})

    return {
        "mode": mode,
        "candidates_count": len(unique),
        "by_priority": by_priority,
        "by_category": by_category,
        "affected_settings": affected_keys,
        "candidates": unique,
    }


# ---------------------------------------------------------------------------
# VIII.  Quick summary: co teraz poprawić?
# ---------------------------------------------------------------------------

def tuning_summary(db: Session, mode: str = "demo") -> Dict[str, Any]:
    """
    Krótkie podsumowanie: ile kandydatów, ile pilnych, top 5 akcji.
    Szybki snapshot bez pełnej listy.
    """
    full = generate_tuning_candidates(db, mode)
    top_actions = full["candidates"][:5]

    summary = trading_effectiveness_summary(db, mode)

    return {
        "mode": mode,
        "trading_verdict": summary["verdict"],
        "trading_verdict_reason": summary["verdict_reason"],
        "net_expectancy": summary["net_expectancy"],
        "cost_leakage_ratio": summary["cost_leakage_ratio"],
        "candidates_count": full["candidates_count"],
        "high_priority_count": full["by_priority"].get("wysoki", 0),
        "affected_settings": full["affected_settings"],
        "top_actions": [
            {
                "id": c["id"],
                "priority": c["priority"],
                "action": c["action"],
                "target": c["target"],
                "setting_key": c["setting_key"],
                "confidence": c["confidence"],
                "reason": c["reason"],
            }
            for c in top_actions
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _confidence(trades: int, effect_magnitude: float) -> float:
    """
    Prosta heurystyka pewności sugestii:
    - więcej transakcji = większa pewność
    - większy efekt = większa pewność
    Min 0.1, max 0.95.
    """
    trade_factor = min(1.0, trades / 20)
    effect_factor = min(1.0, abs(effect_magnitude) * 2)
    raw = (trade_factor * 0.7 + effect_factor * 0.3)
    return max(0.1, min(0.95, round(raw, 2)))


_GATE_SETTING_MAP = {
    "kill_switch_gate": "kill_switch_enabled",
    "daily_net_drawdown_gate": "max_daily_drawdown",
    "loss_streak_gate": "loss_streak_limit",
    "max_open_positions_gate": "max_open_positions",
    "activity_gate_day": "max_trades_per_day",
    "activity_gate_symbol_hour": "max_trades_per_hour_per_symbol",
    "exposure_gate_total": "max_total_exposure_ratio",
    "exposure_gate_symbol": "max_symbol_exposure_ratio",
    "leakage_gate_symbol": "max_cost_leakage_ratio",
    "expectancy_gate_symbol": "min_symbol_net_expectancy",
    "expectancy_gate_strategy": None,
}


def _gate_to_setting(gate_name: str) -> str | None:
    """Mapuj nazwę risk gate na klucz runtime_settings."""
    return _GATE_SETTING_MAP.get(gate_name)
