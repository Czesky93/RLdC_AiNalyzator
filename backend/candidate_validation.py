"""
Candidate Validation — selekcja i pakowanie kandydatów zmian w paczki eksperymentalne.

Pomost: tuning_insights → sensowne paczki do create_experiment.

NIE wdraża zmian automatycznie.
NIE wywołuje create_experiment (tylko przygotowuje dane).
NIE modyfikuje runtime_settings, accounting, risk, reporting.

Zadania:
1. Walidacja kandydatów — czy mają wystarczające dane, żeby wejść do eksperymentu?
2. Wykrywanie konfliktów — które kandydaty się wzajemnie gryzą?
3. Grupowanie — które można łączyć w jedną paczkę eksperymentalną?
4. Kwalifikacja — separation into actionable / needs_more_data / informational only
5. Generowanie gotowych propozycji paczek eksperymentalnych (experiment feed)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.tuning_insights import generate_tuning_candidates

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progi kwalifikacji
# ---------------------------------------------------------------------------

# Minimalna confidence, żeby kandydat mógł trafić do eksperymentu
MIN_CONFIDENCE_FOR_EXPERIMENT = 0.35

# Priorytety kwalifikujące do eksperymentu (informacyjny = nie)
EXPERIMENT_ELIGIBLE_PRIORITIES = {"wysoki", "średni", "niski"}

# Maksymalna liczba kandydatów w jednej paczce
MAX_CANDIDATES_PER_BUNDLE = 4

# Maksymalna liczba paczek do wygenerowania
MAX_BUNDLES = 5


# ---------------------------------------------------------------------------
# I.  Klasyfikacja kandydatów
# ---------------------------------------------------------------------------

_STATUS_ACTIONABLE = "actionable"       # gotowy do eksperymentu
_STATUS_NEEDS_DATA = "needs_more_data"  # za mało danych → czekaj
_STATUS_INFO_ONLY = "info_only"         # informacyjny → nie do eksperymentu
_STATUS_CONFLICT = "conflict"           # gryzący się z innym kandydatem


def _classify_candidate(candidate: Dict[str, Any]) -> str:
    """Sklasyfikuj kandydata: actionable / needs_more_data / info_only."""
    if candidate["priority"] == "informacyjny":
        return _STATUS_INFO_ONLY

    if candidate["confidence"] < MIN_CONFIDENCE_FOR_EXPERIMENT:
        return _STATUS_NEEDS_DATA

    if candidate["priority"] not in EXPERIMENT_ELIGIBLE_PRIORITIES:
        return _STATUS_INFO_ONLY

    return _STATUS_ACTIONABLE


def classify_candidates(
    candidates: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Rozdziel kandydatów na grupy wg statusu kwalifikacji.

    Zwraca:
        {
            "actionable": [...],
            "needs_more_data": [...],
            "info_only": [...]
        }
    """
    result: Dict[str, List[Dict[str, Any]]] = {
        _STATUS_ACTIONABLE: [],
        _STATUS_NEEDS_DATA: [],
        _STATUS_INFO_ONLY: [],
    }

    for c in candidates:
        status = _classify_candidate(c)
        enriched = {**c, "qualification_status": status}
        result[status].append(enriched)

    return result


# ---------------------------------------------------------------------------
# II.  Wykrywanie konfliktów
# ---------------------------------------------------------------------------

# Pary setting_key, które mogą się wzajemnie gryzać
_CONFLICT_PAIRS: List[Tuple[str, str]] = [
    # Usuwanie symbolu z watchlist vs. ograniczanie go per-hour
    ("watchlist", "max_trades_per_hour_per_symbol"),
    # Ograniczenie strategii vs. zmiana min_expected_rr dla strategii
    ("enabled_strategies", "min_expected_rr"),
]

# Ustawienia, które operują na tym samym "pokrętle" — zmiana jednego
# wpływa na drugie
_SAME_KNOB_GROUPS: List[Set[str]] = [
    {"min_edge_multiplier", "slippage_bps", "spread_buffer_bps"},  # koszty
    {"max_trades_per_day", "max_trades_per_hour_per_symbol"},       # aktywność
    {"max_daily_drawdown", "max_weekly_drawdown"},                  # drawdown
]


def _candidates_conflict(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    """
    Sprawdź, czy dwaj kandydaci się gryzą.

    Zwraca opis konfliktu lub None, jeśli brak.
    """
    key_a = a.get("setting_key")
    key_b = b.get("setting_key")

    if not key_a or not key_b:
        return None

    # Ten sam symbol + ten sam setting_key = duplikat, nie konflikt
    if key_a == key_b and a.get("target") == b.get("target"):
        return None

    # Jawne pary konfliktowe
    for pair_a, pair_b in _CONFLICT_PAIRS:
        if (key_a == pair_a and key_b == pair_b) or (key_a == pair_b and key_b == pair_a):
            target_a = a.get("target", "global")
            target_b = b.get("target", "global")
            # Konflikt tylko jeśli dotyczą tego samego targetu
            if target_a == target_b or target_a == "global" or target_b == "global":
                return (
                    f"Kandydaty '{a['id']}' ({key_a}) i '{b['id']}' ({key_b}) "
                    f"dotyczą powiązanych ustawień dla {target_a}/{target_b}"
                )

    # Usuwanie z watchlist + dowolna zmiana dotycząca tego samego symbolu
    if key_a == "watchlist" and a.get("action") == "usuń_z_watchlist":
        if b.get("target") == a.get("target"):
            return (
                f"Kandydat '{a['id']}' usuwa symbol {a['target']} z watchlist, "
                f"więc '{b['id']}' (tuning {key_b} dla {b['target']}) jest zbędny"
            )
    if key_b == "watchlist" and b.get("action") == "usuń_z_watchlist":
        if a.get("target") == b.get("target"):
            return (
                f"Kandydat '{b['id']}' usuwa symbol {b['target']} z watchlist, "
                f"więc '{a['id']}' (tuning {key_a} dla {a['target']}) jest zbędny"
            )

    return None


def detect_conflicts(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Wykryj pary kandydatów, które się nawzajem gryzą.

    Zwraca listę opisów konfliktów:
    [
        {
            "candidate_a": "id_a",
            "candidate_b": "id_b",
            "reason": "opis konfliktu",
            "resolution": "sugerowane rozwiązanie"
        },
        ...
    ]
    """
    conflicts: List[Dict[str, Any]] = []

    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            reason = _candidates_conflict(a, b)
            if reason:
                # Sugerowane rozwiązanie: zostaw tego z wyższym priorytetem/confidence
                if _priority_rank(a) < _priority_rank(b):
                    preferred, dropped = a["id"], b["id"]
                elif _priority_rank(a) > _priority_rank(b):
                    preferred, dropped = b["id"], a["id"]
                elif a["confidence"] >= b["confidence"]:
                    preferred, dropped = a["id"], b["id"]
                else:
                    preferred, dropped = b["id"], a["id"]

                conflicts.append({
                    "candidate_a": a["id"],
                    "candidate_b": b["id"],
                    "reason": reason,
                    "resolution": f"Preferuj '{preferred}', odrzuć '{dropped}'",
                })

    return conflicts


def _priority_rank(candidate: Dict[str, Any]) -> int:
    """Numeryczny ranking priorytetu (niższy = ważniejszy)."""
    return {"wysoki": 0, "średni": 1, "niski": 2, "informacyjny": 3}.get(
        candidate.get("priority", "informacyjny"), 4
    )


# ---------------------------------------------------------------------------
# III.  Grupowanie kompatybilnych kandydatów
# ---------------------------------------------------------------------------

def _same_knob_group(key: str) -> Optional[Set[str]]:
    """Zwróć grupę pokręteł, do której należy key, lub None."""
    for group in _SAME_KNOB_GROUPS:
        if key in group:
            return group
    return None


def _are_compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Czy dwóch kandydatów można bezpiecznie łączyć w jednej paczce?"""
    if _candidates_conflict(a, b) is not None:
        return False

    key_a = a.get("setting_key")
    key_b = b.get("setting_key")

    # Ten sam setting_key, różne targety — OK (np. ograniczenie dwóch symboli)
    if key_a == key_b and a.get("target") != b.get("target"):
        return True

    # Różne setting_key, ale ta sama grupa pokręteł — ryzykowne razem
    if key_a and key_b:
        group_a = _same_knob_group(key_a)
        if group_a and key_b in group_a:
            return False

    return True


def group_compatible(
    actionable: List[Dict[str, Any]],
) -> List[List[Dict[str, Any]]]:
    """
    Zgrupuj actionable kandydatów w kompatybilne paczki.

    Greedy: bierze najważniejszego nieprzydzielonego kandydata,
    dorzuca do niego kompatybilnych (max MAX_CANDIDATES_PER_BUNDLE).

    Zwraca listę paczek (list of lists).
    """
    used: Set[str] = set()
    bundles: List[List[Dict[str, Any]]] = []

    # Sortuj wg priorytetu, potem confidence (już posortowane z tuning_insights)
    sorted_candidates = sorted(
        actionable,
        key=lambda c: (_priority_rank(c), -c.get("confidence", 0)),
    )

    for seed in sorted_candidates:
        if seed["id"] in used:
            continue
        if len(bundles) >= MAX_BUNDLES:
            break

        bundle = [seed]
        used.add(seed["id"])

        for other in sorted_candidates:
            if other["id"] in used:
                continue
            if len(bundle) >= MAX_CANDIDATES_PER_BUNDLE:
                break
            # Sprawdź kompatybilność z każdym w paczce
            if all(_are_compatible(existing, other) for existing in bundle):
                bundle.append(other)
                used.add(other["id"])

        bundles.append(bundle)

    return bundles


# ---------------------------------------------------------------------------
# IV.  Generowanie propozycji paczek eksperymentalnych (experiment feed)
# ---------------------------------------------------------------------------

def _bundle_scope(bundle: List[Dict[str, Any]]) -> str:
    """Określ scope paczki: symbol / strategy / global."""
    targets = {c.get("target") for c in bundle if c.get("target")}
    categories = {c["category"] for c in bundle}

    if len(targets) == 1 and "symbol_filter" in categories:
        return "symbol"
    if len(targets) == 1 and "strategy_filter" in categories:
        return "strategy"
    return "global"


def _bundle_name(bundle: List[Dict[str, Any]], index: int) -> str:
    """Generuj czytelną nazwę paczki."""
    categories = {c["category"] for c in bundle}
    targets = sorted({c.get("target", "global") for c in bundle if c.get("target")})

    if len(targets) == 1:
        prefix = targets[0]
    elif targets:
        prefix = f"{targets[0]}+{len(targets)-1}"
    else:
        prefix = "global"

    cat_label = "+".join(sorted(categories))
    return f"paczka_{index+1}_{prefix}_{cat_label}"


def _bundle_description(bundle: List[Dict[str, Any]]) -> str:
    """Czytelny opis paczki po polsku."""
    parts = []
    for c in bundle:
        parts.append(f"- [{c['priority']}] {c['action']}: {c.get('target', 'global')} "
                      f"(setting: {c.get('setting_key', '?')}, confidence: {c['confidence']:.0%})")
    return "\n".join(parts)


def _bundle_settings_diff(bundle: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Zbierz mapę setting_key → sugerowana zmiana z kandydatów w paczce.

    Nie oblicza nowych wartości (to zadanie operatora).
    Zwraca info o kierunku zmiany.
    """
    diff: Dict[str, Any] = {}
    for c in bundle:
        key = c.get("setting_key")
        if not key:
            continue
        diff[key] = {
            "candidate_id": c["id"],
            "action": c.get("action"),
            "target": c.get("target"),
            "current_impact": c.get("current_impact"),
        }
    return diff


def generate_experiment_feed(
    db: Session,
    mode: str = "demo",
) -> Dict[str, Any]:
    """
    Pełny pipeline: tuning_insights → klasyfikacja → konflikty → paczki.

    Zwraca:
    {
        "mode": str,
        "total_candidates": int,
        "classification": {
            "actionable": int,
            "needs_more_data": int,
            "info_only": int,
        },
        "conflicts": [...],
        "bundles": [
            {
                "name": str,
                "scope": str,
                "priority": str,  # max priorytet w paczce
                "avg_confidence": float,
                "settings_affected": [str, ...],
                "description": str,
                "candidates": [...],
                "settings_diff": {...},
            },
            ...
        ],
        "needs_more_data": [...],
        "info_only": [...],
    }
    """
    full = generate_tuning_candidates(db, mode)
    all_candidates = full["candidates"]

    # 1. Klasyfikacja
    classified = classify_candidates(all_candidates)
    actionable = classified[_STATUS_ACTIONABLE]
    needs_data = classified[_STATUS_NEEDS_DATA]
    info_only = classified[_STATUS_INFO_ONLY]

    # 2. Konflikty wśród actionable
    conflicts = detect_conflicts(actionable)

    # 3. Usuń przegranych z konfliktów
    dropped_ids: Set[str] = set()
    for conflict in conflicts:
        resolution = conflict["resolution"]
        # "Preferuj 'X', odrzuć 'Y'" — wyciągnij Y
        if "odrzuć '" in resolution:
            dropped = resolution.split("odrzuć '")[1].rstrip("'")
            dropped_ids.add(dropped)

    filtered_actionable = [c for c in actionable if c["id"] not in dropped_ids]

    # 4. Grupowanie w paczki
    raw_bundles = group_compatible(filtered_actionable)

    # 5. Sformatuj paczki
    bundles = []
    for i, bundle in enumerate(raw_bundles):
        priorities = [c["priority"] for c in bundle]
        max_priority = min(priorities, key=lambda p: _priority_rank({"priority": p}))
        avg_conf = sum(c["confidence"] for c in bundle) / len(bundle) if bundle else 0.0

        settings_keys = sorted({c.get("setting_key") for c in bundle if c.get("setting_key")})

        bundles.append({
            "name": _bundle_name(bundle, i),
            "scope": _bundle_scope(bundle),
            "priority": max_priority,
            "avg_confidence": round(avg_conf, 2),
            "candidates_count": len(bundle),
            "settings_affected": settings_keys,
            "description": _bundle_description(bundle),
            "candidates": [
                {
                    "id": c["id"],
                    "category": c["category"],
                    "priority": c["priority"],
                    "action": c["action"],
                    "setting_key": c.get("setting_key"),
                    "target": c.get("target"),
                    "confidence": c["confidence"],
                    "reason": c["reason"],
                }
                for c in bundle
            ],
            "settings_diff": _bundle_settings_diff(bundle),
        })

    return {
        "mode": mode,
        "total_candidates": len(all_candidates),
        "classification": {
            "actionable": len(actionable),
            "needs_more_data": len(needs_data),
            "info_only": len(info_only),
        },
        "conflicts": conflicts,
        "conflicts_resolved": len(dropped_ids),
        "bundles_count": len(bundles),
        "bundles": bundles,
        "needs_more_data": [
            {
                "id": c["id"],
                "category": c["category"],
                "action": c["action"],
                "confidence": c["confidence"],
                "reason": c["reason"],
            }
            for c in needs_data
        ],
        "info_only": [
            {
                "id": c["id"],
                "category": c["category"],
                "action": c["action"],
                "reason": c["reason"],
            }
            for c in info_only
        ],
    }


# ---------------------------------------------------------------------------
# V.  Quick summary: co warto teraz testować?
# ---------------------------------------------------------------------------

def experiment_feed_summary(
    db: Session,
    mode: str = "demo",
) -> Dict[str, Any]:
    """
    Szybki snapshot: ile paczek gotowych, ile konflikty, ile czeka na dane.

    Nie zwraca pełnych list — tylko liczby i top paczki.
    """
    feed = generate_experiment_feed(db, mode)

    top_bundles = []
    for b in feed["bundles"][:3]:
        top_bundles.append({
            "name": b["name"],
            "scope": b["scope"],
            "priority": b["priority"],
            "avg_confidence": b["avg_confidence"],
            "candidates_count": b["candidates_count"],
            "settings_affected": b["settings_affected"],
        })

    return {
        "mode": mode,
        "total_candidates": feed["total_candidates"],
        "classification": feed["classification"],
        "conflicts_count": len(feed["conflicts"]),
        "conflicts_resolved": feed["conflicts_resolved"],
        "bundles_ready": feed["bundles_count"],
        "top_bundles": top_bundles,
    }
